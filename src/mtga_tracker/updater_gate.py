"""The updater's safety gate: what an install would interrupt right now.

Mixed into `UpdateManager`. Reads in-process tracker state when the tracker
runs in this process, the database's live row otherwise, the Arena process
probe, and the job flags of the Deck Manager, collection export and backup
restore. See docs/plans/AUTO_UPDATE.md section 7.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from .updater_support import (
    BO3_BETWEEN_GAMES_WINDOW_S,
    BUSY_ORDER,
    IDLE_REQUIRED_S,
    QUEUED_EVENT_WINDOW_S,
    _naive,
)


class UpdateGateMixin:
    def _probe_arena(self) -> Optional[bool]:
        if self._arena_probe is not None:
            return self._arena_probe()
        from .paths import arena_process_running

        return arena_process_running()

    def _game_busy(self) -> bool:
        now_m = self._monotonic()
        now = datetime.now()
        busy = False
        tracker = getattr(self.launcher, "tracker", None)
        if tracker is not None:
            game = getattr(tracker, "game_state", None)
            if game is not None:
                in_match = bool(getattr(game, "in_match", False))
                ended = _naive(getattr(game, "game_end_time", None))
                if (
                    in_match
                    and getattr(game, "game_start_time", None)
                    and not getattr(game, "match_complete", False)
                ):
                    busy = True
                if (
                    in_match
                    and getattr(game, "match_type", "") == "best_of_3"
                    and not getattr(game, "arena_match_over", False)
                    and (
                        ended is None or now - ended < timedelta(seconds=BO3_BETWEEN_GAMES_WINDOW_S)
                    )
                ):
                    busy = True
                if ended is not None and now - ended < timedelta(seconds=IDLE_REQUIRED_S):
                    busy = True
                event_id = getattr(game, "authoritative_event_id", None)
                if event_id and not in_match:
                    first = self._event_first_seen.setdefault(str(event_id), now_m)
                    if now_m - first < QUEUED_EVENT_WINDOW_S:
                        busy = True
            if getattr(tracker, "waiting_for_next_game", False):
                busy = True
        if self.db_path is not None:
            from .live_api import game_activity

            try:
                activity = game_activity(self.db_path)
            except Exception:
                activity = {"tracker": "live", "in_game": True, "last_game_ended_at": None}
            if activity.get("tracker") == "live":
                busy = True
            ended_db = _naive(activity.get("last_game_ended_at"))
            if ended_db is not None and now - ended_db < timedelta(seconds=IDLE_REQUIRED_S):
                busy = True
        if busy:
            self._last_game_seen = now_m
        elif self._last_game_seen is not None and now_m - self._last_game_seen < IDLE_REQUIRED_S:
            busy = True
        return busy

    def busy_reasons(self, gate: str = "auto") -> List[str]:
        """What an install would interrupt. `gate` is "auto" (unattended:
        Arena must be closed, an unknown probe counts as open), "manual" (a
        user click; Arena open needs a confirm), "pending" ("install after
        this game"), or "forced" (confirmed: game and Arena gates skipped)."""
        reasons = set()
        try:
            from . import deck_native_api

            if deck_native_api.job_active():
                reasons.add("deck-transfer")
        except Exception:
            pass
        try:
            from . import collection_api

            if collection_api.job_running():
                reasons.add("collection-export")
        except Exception:
            pass
        try:
            from . import backup_api

            if backup_api.restore_in_progress():
                reasons.add("backup-restore")
        except Exception:
            pass
        if gate != "forced":
            if self._game_busy():
                reasons.add("game-in-progress")
            if gate in ("auto", "manual"):
                arena = self._probe_arena()
                if arena is True or (gate == "auto" and arena is None):
                    reasons.add("arena-running")
        return [reason for reason in BUSY_ORDER if reason in reasons]
