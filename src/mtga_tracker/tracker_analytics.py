"""Analytics-related CardTracker mixin methods."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .analytics import AnalyticsStore, SessionSnapshot
from .analytics_persistence import (
    persist_card_summary,
    persist_commanders,
    persist_drawn_cards,
    persist_mulligan_hands,
    persist_opening_hand,
    persist_submitted_deck,
)
from .format_normalizer import (
    is_jump_in_format,
    is_midweek_format,
    is_momir_format,
    is_welcome_deck_format,
    normalize_match_format,
)
from .deck_llm import identify_deck, is_deck_llm_enabled
from .rank_progress import (
    iter_constructed_rank_snapshots,
    parse_constructed_rank_snapshot,
    parse_limited_rank_snapshot,
)
from .state import CardEvent


class TrackerAnalyticsMixin:
    """SQLite analytics and dashboard persistence helpers used by CardTracker."""

    def _is_bot_match(self) -> bool:
        """Return True for MTGA bot matches that should stay out of analytics."""
        opponent_name = str(self.game_state.opponent_display_name or "").strip().lower()
        if opponent_name == "sparky":
            return True
        format_text = str(self.game_state.format_str or "").strip().lower()
        return format_text.startswith("aibotmatch")

    def _is_untracked_match(self) -> bool:
        """Return True for matches intentionally excluded from saved analytics."""
        return self._untracked_mode_reason() is not None or self.game_state.mid_game_attach

    def _untracked_mode_reason(self) -> Optional[str]:
        """Name the excluded game mode, or None for a tracked match.

        Both the resolved format and the raw queue/event name are checked:
        a Jump In game can persist with format "Unknown" while the event
        name still says Jump_In_MSH.
        """
        if self._is_bot_match():
            return "practice game vs Sparky"
        for value in (self.game_state.format_str, self.game_state.player_deck_event_name):
            if is_jump_in_format(value):
                return "Jump In"
            if is_midweek_format(value):
                return "Midweek Magic"
            if is_momir_format(value):
                return "Momir"
            if is_welcome_deck_format(value):
                return "Welcome Deck Duels"
        return None

    def _session_snapshot(self) -> SessionSnapshot:
        """Return the current session counters for analytics persistence."""
        return SessionSnapshot(
            session_id=self.session_id,
            started_at=self.session_start_time,
            games_played=self.session_games_played,
            wins=self.session_wins,
            losses=self.session_losses,
            draws=getattr(self, "session_draws", 0),
            unknown_results=self.session_unknown,
            runtime_seconds=self._session_play_runtime_seconds(),
        )

    def _analytics_store(self) -> AnalyticsStore:
        """Return an AnalyticsStore aligned with the current DB path."""
        path = getattr(self, "_console_db_path", None)
        store = getattr(self, "analytics", None)
        store_path = getattr(store, "path", None)
        desired_path = Path(path) if path is not None else None
        if store is None or store_path != desired_path:
            if store is not None:
                store.close()
            store = AnalyticsStore(desired_path)
            self.analytics = store
        return store

    def _record_console_log(self, text: str, style: Optional[str] = None) -> None:
        """Best-effort persistent storage for terminal output."""
        if self._is_untracked_match():
            return
        try:
            now = self._now()
            elapsed_seconds = None
            if self.game_state.game_start_time is not None:
                elapsed_seconds = max(
                    0, int((now - self.game_state.game_start_time).total_seconds())
                )
            self._analytics_store().record_console_log(
                self._session_snapshot(),
                created_at=now,
                match_started_at=self.game_state.game_start_time,
                elapsed_seconds=elapsed_seconds,
                turn_number=self.game_state.turn_number or None,
                active_player=self.game_state.active_player,
                style=style,
                text=text,
                player_life=self.game_state.player_life,
                opponent_life=self.game_state.opponent_life,
                live=self._live_status_snapshot(now),
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return

    def _live_status_snapshot(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Current-state row for live_status (the dashboard's Live Log page)."""
        g = self.game_state
        in_game = bool(g.in_match and g.game_start_time and not g.match_complete)
        active_role: Optional[str] = None
        if g.active_player is not None:
            if g.active_player == g.player_seat_id:
                active_role = "player"
            elif g.active_player == g.opponent_seat_id:
                active_role = "opponent"
        on_play: Optional[int] = None
        if g.first_player_seat is not None and g.player_seat_id is not None:
            on_play = 1 if g.first_player_seat == g.player_seat_id else 0
        game_id: Optional[str] = None
        match_id: Optional[str] = None
        if in_game:
            try:
                match_id = self._current_match_id()
                game_id = self._current_game_id()
            except Exception:
                pass
        format_label: Optional[str] = None
        if g.format_str and g.format_str != "Unknown":
            try:
                # Friendly label ("Standard Best-of-3 Ranked"), same family the
                # dashboard's Recent Games shows — not the raw queue string.
                format_label = self._friendly_format_label()
            except Exception:
                format_label = g.format_str
        return {
            "session_id": self.session_id,
            "updated_at": (now or self._now()).isoformat(),
            "in_game": 1 if in_game else 0,
            "match_id": match_id,
            "game_id": game_id,
            "format": format_label,
            "match_type": g.match_type,
            "game_number": g.game_number,
            "player_name": g.player_display_name,
            "opponent_name": g.opponent_display_name,
            "deck_name": g.player_deck_name,
            "turn_number": g.turn_number or None,
            "active_role": active_role,
            "on_play": on_play,
            "player_life": g.player_life,
            "opponent_life": g.opponent_life,
            "mulligans": g.mulligan_count or 0,
            "game_started_at": g.game_start_time.isoformat() if g.game_start_time else None,
            "player_commanders": json.dumps(g.player_commanders) if g.player_commanders else None,
            "opponent_commanders": (
                json.dumps(g.opponent_commanders) if g.opponent_commanders else None
            ),
            "log_path": str(self.parser.log_path) if self.parser.log_path else None,
            "card_db_path": self._live_card_db_path(),
            "db_path": str(self._console_db_path),
            "tracker_version": self._live_tracker_version(),
        }

    def _live_card_db_path(self) -> Optional[str]:
        cached = getattr(self, "_live_card_db_path_cache", "unset")
        if cached != "unset":
            return cached
        resolved: Optional[str] = None
        resolve = getattr(self.card_db, "_resolve_mtga_db_path", None)
        if callable(resolve):
            try:
                path = resolve()
                resolved = str(path) if path else None
            except Exception:
                resolved = None
        self._live_card_db_path_cache = resolved
        return resolved

    def _live_tracker_version(self) -> str:
        from . import __version__ as tracker_version

        return tracker_version

    def _live_heartbeat(self) -> None:
        """Bump live_status.updated_at every few seconds while idle, so the
        dashboard can tell a quiet tracker from a stopped one."""
        now_monotonic = time.monotonic()
        last = getattr(self, "_last_live_heartbeat", 0.0)
        if now_monotonic - last < 5.0:
            return
        self._last_live_heartbeat = now_monotonic
        try:
            self._analytics_store().touch_live_status(self.session_id, datetime.now())
        except (OSError, sqlite3.Error):
            return

    def _record_raw_payload_snapshot(self, payload_type: str, payload_text: str) -> None:
        """Best-effort sanitized raw payload persistence for diagnostics/replay."""
        if self._is_untracked_match() or is_momir_format(payload_text):
            return
        try:
            game_id = self._current_game_id() if self.game_state.game_start_time else None
            match_id = self._current_match_id() if self.game_state.game_start_time else None
            self._analytics_store().record_raw_payload(
                session_id=self.session_id,
                created_at=self._now(),
                payload_type=payload_type,
                payload_json=str(payload_text or ""),
                match_id=match_id,
                game_id=game_id,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return

    def _process_rank_progress(self, line: str) -> None:
        """Persist changed rank responses, linked to a ranked game when possible."""
        limited = parse_limited_rank_snapshot(line)
        if limited is not None:
            try:
                self._analytics_store().record_rank_snapshot(
                    self._session_snapshot(),
                    captured_at=self._now(),
                    rank_format="limited",
                    **limited,
                )
            except (OSError, sqlite3.Error, TypeError, ValueError):
                pass
        snapshot = parse_constructed_rank_snapshot(line)
        if snapshot is None:
            return
        match_id = None
        game_id = None
        if (
            self.game_state.game_start_time
            and self.game_state.match_complete
            and not self._is_untracked_match()
        ):
            normalized = normalize_match_format(
                self.game_state.format_str,
                default_best_of=3 if self.game_state.match_type == "best_of_3" else 1,
            )
            if normalized.family == "standard" and "(Ranked)" in normalized.label:
                match_id = self._current_match_id()
                game_id = self._current_game_id()
        try:
            self._analytics_store().record_rank_snapshot(
                self._session_snapshot(),
                captured_at=self._now(),
                match_id=match_id,
                game_id=game_id,
                **snapshot,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return

    def _backfill_rank_progress(self) -> None:
        """Import changed rank snapshots already present in the current Arena log."""
        log_path = getattr(self.parser, "log_path", None)
        if not log_path:
            return
        try:
            store = self._analytics_store()
            for captured_at, snapshot in iter_constructed_rank_snapshots(log_path):
                store.record_rank_snapshot(
                    self._session_snapshot(),
                    captured_at=captured_at,
                    **snapshot,
                )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return

    def _analytics_connect(self) -> Optional[sqlite3.Connection]:
        """Return initialized analytics DB connection, or None when disabled/unavailable."""
        try:
            conn = self._analytics_store().connect()
            if conn is None:
                return None
            # Commit (or roll back) immediately: leaving this upsert pending
            # would hold the WAL write lock for as long as the tracker idles,
            # blocking the dashboard's note saves with "database is locked".
            with conn:
                self._upsert_session_row(conn)
            return conn
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None

    def _ensure_analytics_schema(self, conn: sqlite3.Connection) -> None:
        """Create dashboard-friendly analytics tables if needed."""
        AnalyticsStore.ensure_schema(conn)

    @staticmethod
    def _run_analytics_write(
        conn: sqlite3.Connection,
        operation: Callable[[], None],
        *,
        attempts: int = 3,
    ) -> None:
        """Run a SQLite write with bounded retries for transient lock contention."""
        for attempt in range(attempts):
            try:
                with conn:
                    operation()
                return
            except sqlite3.OperationalError as exc:
                conn.rollback()
                transient = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if not transient or attempt + 1 >= attempts:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def _backfill_card_colors(self) -> None:
        """Fill missing card color identities from the Arena card database."""
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            index = self.card_db.color_identity_index_by_name()
            if index:
                AnalyticsStore.backfill_card_colors(conn, index)
            mana_index = self.card_db.mana_cost_index_by_name()
            if mana_index:
                AnalyticsStore.backfill_card_mana(conn, mana_index)
        except (AttributeError, sqlite3.Error, OSError, TypeError, ValueError):
            return

    #: Every table whose display_name can carry a "Card #N" placeholder.
    _CARD_LABEL_TABLES = (
        "game_card_summary",
        "game_drawn_cards",
        "game_opening_hand_cards",
        "game_deck_cards",
        "game_mulligan_hands",
    )

    def _backfill_unresolved_card_labels(self) -> None:
        """Resolve leftover "Card #N" labels once the Arena card DB knows them.

        Cards can persist under their numeric fallback when a set is newer
        than the local card database, an object id slipped through, or —
        the big one — games were recorded while Arena's card DB could not be
        found at all. Each startup retries the lookup and rewrites every
        display_name that carried the placeholder, so a database recorded
        "blind" heals itself on the first launch that can see the card DB.

        Cost when there is nothing to fix: one SELECT per table returning
        zero rows. This must stay cheap — it runs on every startup.
        """
        conn = self._analytics_connect()
        if conn is None:
            return
        get_name = getattr(self.card_db, "get_card_name", None)
        if get_name is None:
            return
        # Collect labels from the cards table AND the game tables: a
        # display_name can carry a placeholder with no matching cards row.
        labels = set()
        try:
            for row in conn.execute("SELECT name FROM cards WHERE name LIKE 'Card #%'"):
                labels.add(str(row[0] or ""))
            for table_name in self._CARD_LABEL_TABLES:
                for row in conn.execute(
                    f"SELECT DISTINCT display_name FROM {table_name} "
                    "WHERE display_name LIKE 'Card #%'"
                ):
                    labels.add(str(row[0] or ""))
        except sqlite3.Error:
            return
        resolved = 0
        try:
            with conn:
                for old_name in sorted(labels):
                    match = re.match(r"^Card #(\d+)$", old_name)
                    if not match:
                        continue
                    grp_id = int(match.group(1))
                    try:
                        new_name = str(get_name(grp_id) or "")
                    except Exception:
                        continue
                    if not new_name or new_name.startswith("Card #"):
                        continue
                    changes_before = conn.total_changes
                    conn.execute(
                        "UPDATE OR IGNORE cards SET name = ?, arena_id = COALESCE(arena_id, ?) "
                        "WHERE name = ?",
                        (new_name, grp_id, old_name),
                    )
                    # OR IGNORE everywhere: a row for the real name may already
                    # exist in the same game (UNIQUE constraints) — never let
                    # one collision roll back the whole repair.
                    for table_name in self._CARD_LABEL_TABLES:
                        conn.execute(
                            f"UPDATE OR IGNORE {table_name} SET display_name = ? "
                            "WHERE display_name = ?",
                            (new_name, old_name),
                        )
                    conn.execute(
                        "UPDATE OR IGNORE participant_commanders SET card_name = ? "
                        "WHERE card_name = ?",
                        (new_name, old_name),
                    )
                    self._fold_stale_card_row(conn, old_name, new_name)
                    # Only labels where a row actually changed count — a
                    # duplicate-name no-op must not report "Resolved N" on
                    # every single launch.
                    if conn.total_changes != changes_before:
                        resolved += 1
        except sqlite3.Error:
            return
        if resolved:
            self._print_line(
                f"🃏 Resolved {resolved} previously unknown card label(s) from the Arena card DB."
            )

    def _fold_stale_card_row(self, conn, old_name: str, new_name: str) -> None:
        """Fold a leftover "Card #N" cards row into the real card's row.

        When the real name already had its own cards row, the rename above
        was a no-op and the placeholder row would linger — and be re-scanned
        on every launch. Repoint card_id references at the real row and
        delete the placeholder once nothing references it.
        """
        stale = conn.execute("SELECT id FROM cards WHERE name = ?", (old_name,)).fetchone()
        if stale is None:
            return
        real = conn.execute("SELECT id FROM cards WHERE name = ?", (new_name,)).fetchone()
        if real is None:
            return
        stale_id, real_id = int(stale[0]), int(real[0])
        reference_tables = self._CARD_LABEL_TABLES + ("participant_commanders",)
        remaining = 0
        for table_name in reference_tables:
            conn.execute(
                f"UPDATE OR IGNORE {table_name} SET card_id = ? WHERE card_id = ?",
                (real_id, stale_id),
            )
            remaining += int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE card_id = ?", (stale_id,)
                ).fetchone()[0]
            )
        if remaining == 0:
            conn.execute("DELETE FROM cards WHERE id = ?", (stale_id,))

    def _reassign_misattributed_game_events(self) -> None:
        """Startup repair: move events that fall inside a DIFFERENT game's window.

        Same operation as db_audit --repair's event reassignment, run
        automatically so non-technical users never need the CLI. Costs one
        indexed pass over game_events (~150ms on an 80k-event database);
        events outside every game window are deliberately left where they
        are (post-game tails belong to their game).
        """
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            from .db_audit import _repair_game_event_assignments

            repaired = 0

            def _run() -> None:
                nonlocal repaired
                repaired = _repair_game_event_assignments(conn)

            self._run_analytics_write(conn, _run)
        except (ImportError, sqlite3.Error, OSError):
            return
        if repaired:
            self._print_line(
                f"🧭 Reassigned {repaired} game event(s) to the game matching their timestamps."
            )

    def _recover_missing_turn_timings(self) -> None:
        """Recover persisted turn durations from durable console headers at startup."""
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            self._run_analytics_write(
                conn,
                lambda: AnalyticsStore.backfill_recovered_game_turn_times(conn),
            )
        except sqlite3.Error as exc:
            self._report_analytics_persistence_error(
                "historical turn timing recovery", "startup", exc
            )

    @staticmethod
    def _ensure_table_column(
        conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str
    ) -> None:
        """Add a nullable column when an older analytics DB lacks it."""
        AnalyticsStore.ensure_table_column(conn, table_name, column_name, column_type)

    def _upsert_session_row(self, conn: sqlite3.Connection) -> None:
        """Persist current session counters."""
        runtime_seconds = self._session_play_runtime_seconds()
        conn.execute(
            """
            INSERT INTO tracker_sessions (
                id, started_at, ended_at, app_version, games_played, wins, losses, draws, unknown_results, runtime_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ended_at = excluded.ended_at,
                games_played = excluded.games_played,
                wins = excluded.wins,
                losses = excluded.losses,
                draws = excluded.draws,
                unknown_results = excluded.unknown_results,
                runtime_seconds = excluded.runtime_seconds
            """,
            (
                self.session_id,
                self.session_start_time.isoformat(),
                datetime.now().isoformat(),
                None,
                self.session_games_played,
                self.session_wins,
                self.session_losses,
                getattr(self, "session_draws", 0),
                self.session_unknown,
                runtime_seconds,
            ),
        )

    def _current_game_ordinal(self) -> int:
        """Return stable 1-based game ordinal for DB ids."""
        completed_games = int(self.session_games_played or 0)
        if self.game_state.in_match and not self._session_stats_recorded_this_game:
            return completed_games + 1
        return max(1, completed_games)

    def _current_match_ordinal(self) -> int:
        """Return stable 1-based match ordinal for DB ids.

        When Arena's match UUID is known, the ordinal computed on first sight
        of that UUID is pinned for the session, so every game of a Bo3 match
        persists under the same tracker match id even if the heuristic inputs
        (session game count, game number) shift between games.
        """
        game_ordinal = self._current_game_ordinal()
        if self.game_state.match_type == "best_of_3":
            heuristic = max(1, game_ordinal - int(self.game_state.game_number or 1) + 1)
        else:
            heuristic = game_ordinal
        arena_match_id = getattr(self.game_state, "arena_match_id", None)
        if arena_match_id:
            ordinals = getattr(self, "_arena_match_ordinal_by_id", None)
            if ordinals is None:
                ordinals = self._arena_match_ordinal_by_id = {}
            return ordinals.setdefault(arena_match_id, heuristic)
        return heuristic

    def _current_match_id(self) -> str:
        """Return deterministic match id scoped to this tracker session."""
        return f"{self.session_id}:match:{self._current_match_ordinal()}"

    def _current_game_id(self) -> str:
        """Return deterministic game id scoped to this tracker session."""
        game_number = int(self.game_state.game_number or self._current_game_ordinal())
        return f"{self._current_match_id()}:game:{game_number}"

    def _purge_ghost_game_breadcrumbs(self) -> None:
        """Delete live-written rows for a game the ghost guard refused to save.

        Events and turn timings stream to SQLite during play, before the guard
        can know the "game" is a post-concede tail. Leaving them orphaned makes
        db_audit report a missing completed game and offer to reconstruct the
        very ghost we skipped — so remove the breadcrumbs with the skip.
        """
        conn = self._analytics_connect()
        if conn is None:
            return
        game_id = self._current_game_id()
        try:
            with conn:
                for table_name in ("game_events", "game_turns"):
                    conn.execute(
                        f"DELETE FROM {table_name} WHERE game_id = ?", (game_id,)
                    )
        except sqlite3.Error:
            # Cleanup is best-effort; the audit's orphan sweep also covers it.
            pass

    def _participant_id_for_role(self, game_id: str, role: str) -> str:
        """Return deterministic participant id for player/opponent roles."""
        return f"{game_id}:participant:{role}"

    def _participant_id_for_seat(self, game_id: str, seat_id: Optional[int]) -> Optional[str]:
        """Map a seat id to a deterministic participant id."""
        if seat_id == self.game_state.player_seat_id:
            return self._participant_id_for_role(game_id, "player")
        if seat_id == self.game_state.opponent_seat_id:
            return self._participant_id_for_role(game_id, "opponent")
        return None

    def _participant_snapshot(
        self, game_id: str, role: str, seat_id: Optional[int]
    ) -> Dict[str, Any]:
        """Return current participant metadata for summary persistence."""
        is_player = role == "player"
        observed_deck_size = None
        if seat_id in self.game_state.observed_starting_deck_total_by_seat:
            observed_deck_size = self.game_state.observed_starting_deck_total_by_seat[seat_id]
        metadata_deck_size = self.game_state.player_deck_total_cards if is_player else None
        deck_size = metadata_deck_size or observed_deck_size
        deck_size_source = (
            "metadata" if metadata_deck_size else ("observed" if observed_deck_size else None)
        )
        return {
            "id": self._participant_id_for_role(game_id, role),
            "game_id": game_id,
            "seat_id": seat_id,
            "role": role,
            "display_name": (
                self.game_state.player_display_name
                if is_player
                else self.game_state.opponent_display_name
            )
            or ("You" if is_player else "Opponent"),
            "deck_name": self.game_state.player_deck_name if is_player else None,
            "deck_id": self.game_state.player_deck_id if is_player else None,
            "deck_archetype": None if is_player else self._opponent_archetype(game_id),
            "deck_size": deck_size,
            "deck_size_source": deck_size_source,
            "opening_hand_size": (
                len(self.game_state.starting_hand)
                if is_player and self.game_state.starting_hand
                else None
            ),
            "mulligans": self.game_state.mulligan_count if is_player else None,
            "starting_life": self._starting_life_total_for_current_format(),
            "ending_life": (
                self.game_state.player_life if is_player else self.game_state.opponent_life
            ),
            "went_first": (
                1 if seat_id is not None and self.game_state.first_player_seat == seat_id else 0
            ),
        }

    def _infer_event_actor(self, text: str) -> tuple:
        """Infer actor role/seat from formatted terminal text."""
        body = str(text or "")
        if "] " in body:
            body = body.split("] ", 1)[1]
        body = body.lstrip()
        if body.startswith("\t"):
            body = body.lstrip("\t ")
        if body.startswith("You:") or body.startswith("Combat:") and "(your" in body:
            return "player", self.game_state.player_seat_id
        if body.startswith("Opponent:") or body.startswith("Combat:") and "(opponent" in body:
            return "opponent", self.game_state.opponent_seat_id
        return None, None

    def _record_game_event(self, text: str, style: Optional[str] = None) -> None:
        """Best-effort structured event row for turn-log lines."""
        if not self.game_state.game_start_time:
            return
        if self._is_untracked_match():
            return
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            match_id = self._current_match_id()
            game_id = self._current_game_id()
            actor_role, seat_id = self._infer_event_actor(text)
            participant_id = self._participant_id_for_seat(game_id, seat_id)
            now = self._now()
            elapsed_seconds = max(0, int((now - self.game_state.game_start_time).total_seconds()))
            with conn:
                conn.execute(
                    """
                    INSERT INTO game_events (
                        session_id,
                        match_id,
                        game_id,
                        event_time,
                        elapsed_seconds,
                        turn_number,
                        phase,
                        step,
                        participant_id,
                        seat_id,
                        actor_role,
                        event_type,
                        text,
                        player_life,
                        opponent_life
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.session_id,
                        match_id,
                        game_id,
                        now.isoformat(),
                        elapsed_seconds,
                        self.game_state.turn_number or None,
                        self.game_state.phase or None,
                        self.game_state.step or None,
                        participant_id,
                        seat_id,
                        actor_role,
                        style,
                        str(text or ""),
                        self.game_state.player_life,
                        self.game_state.opponent_life,
                    ),
                )
        except sqlite3.Error:
            return

    def _persist_participant_stats(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        participant_id: str,
        seat_id: Optional[int],
        cards_played: int,
    ) -> None:
        """Persist per-game stats for one participant."""
        stats = self.game_state.match_stats.get(int(seat_id), {}) if seat_id in (1, 2) else {}
        damage_dealt = int(stats.get("total_damage", 0))
        life_lost = int(stats.get("life_lost", 0))
        self_damage = int(stats.get("self_damage", 0))
        # damage_taken means externally inflicted life loss; life_lost keeps the
        # raw total including the participant's own payments/self damage.
        damage_taken = max(0, life_lost - self_damage)
        conn.execute(
            """
            INSERT INTO game_participant_stats (
                game_id,
                participant_id,
                attack_steps,
                attacking_creatures,
                attackers_lost,
                blocking_creatures,
                blockers_lost,
                damage_dealt,
                damage_taken,
                life_lost,
                self_damage,
                life_gained,
                cards_played,
                cards_drawn,
                cards_discarded,
                cards_milled,
                cards_exiled,
                removal_drawn,
                removal_played,
                wipes_drawn,
                wipes_played,
                bounces_drawn,
                bounces_played,
                creatures_removed,
                noncreatures_removed,
                creatures_bounced,
                noncreatures_bounced,
                poison_added,
                counters_drawn,
                counters_played,
                spells_countered,
                lands_lost,
                lands_replaced,
                tokens_created,
                tokens_destroyed,
                tokens_sacrificed,
                tokens_exiled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, participant_id) DO UPDATE SET
                attack_steps = excluded.attack_steps,
                attacking_creatures = excluded.attacking_creatures,
                attackers_lost = excluded.attackers_lost,
                blocking_creatures = excluded.blocking_creatures,
                blockers_lost = excluded.blockers_lost,
                damage_dealt = excluded.damage_dealt,
                damage_taken = excluded.damage_taken,
                life_lost = excluded.life_lost,
                self_damage = excluded.self_damage,
                life_gained = excluded.life_gained,
                cards_played = excluded.cards_played,
                cards_drawn = excluded.cards_drawn,
                cards_discarded = excluded.cards_discarded,
                cards_milled = excluded.cards_milled,
                cards_exiled = excluded.cards_exiled,
                removal_drawn = excluded.removal_drawn,
                removal_played = excluded.removal_played,
                wipes_drawn = excluded.wipes_drawn,
                wipes_played = excluded.wipes_played,
                bounces_drawn = excluded.bounces_drawn,
                bounces_played = excluded.bounces_played,
                creatures_removed = excluded.creatures_removed,
                noncreatures_removed = excluded.noncreatures_removed,
                creatures_bounced = excluded.creatures_bounced,
                noncreatures_bounced = excluded.noncreatures_bounced,
                poison_added = excluded.poison_added,
                counters_drawn = excluded.counters_drawn,
                counters_played = excluded.counters_played,
                spells_countered = excluded.spells_countered,
                lands_lost = excluded.lands_lost,
                lands_replaced = excluded.lands_replaced,
                tokens_created = excluded.tokens_created,
                tokens_destroyed = excluded.tokens_destroyed,
                tokens_sacrificed = excluded.tokens_sacrificed,
                tokens_exiled = excluded.tokens_exiled
            """,
            (
                game_id,
                participant_id,
                int(stats.get("attacks", 0)),
                int(stats.get("attacking_creatures", 0)),
                int(stats.get("attackers_lost", 0)),
                int(stats.get("blocking_creatures", 0)),
                int(stats.get("blockers_lost", 0)),
                damage_dealt,
                damage_taken,
                life_lost,
                self_damage,
                int(stats.get("life_gain", 0)),
                cards_played,
                int(stats.get("cards_drawn", 0)),
                int(stats.get("cards_discarded", 0)),
                int(stats.get("cards_milled", 0)),
                int(stats.get("cards_exiled", 0)),
                int(stats.get("removal_drawn", 0)),
                int(stats.get("removal_played", 0)),
                int(stats.get("wipes_drawn", 0)),
                int(stats.get("wipes_played", 0)),
                int(stats.get("bounces_drawn", 0)),
                int(stats.get("bounces_played", 0)),
                int(stats.get("creatures_removed", 0)),
                int(stats.get("noncreatures_removed", 0)),
                int(stats.get("creatures_bounced", 0)),
                int(stats.get("noncreatures_bounced", 0)),
                int(stats.get("poison_added", 0)),
                int(stats.get("counters_drawn", 0)),
                int(stats.get("counters_played", 0)),
                int(stats.get("spells_countered", 0)),
                int(stats.get("lands_lost", 0)),
                int(stats.get("lands_replaced", 0)),
                int(stats.get("tokens_created", 0)),
                int(stats.get("tokens_destroyed", 0)),
                int(stats.get("tokens_sacrificed", 0)),
                int(stats.get("tokens_exiled", 0)),
            ),
        )

    def _refresh_session_participant_stats(self, conn: sqlite3.Connection) -> None:
        """Recompute session role aggregates from persisted game rows."""
        conn.execute(
            """
            INSERT INTO session_participant_stats (
                session_id,
                role,
                games,
                wins,
                losses,
                cards_played,
                cards_drawn,
                cards_discarded,
                cards_milled,
                damage_dealt,
                damage_taken
            )
            SELECT
                g.session_id,
                p.role,
                COUNT(*),
                SUM(CASE
                    WHEN (p.role = 'player' AND g.outcome = 'win')
                      OR (p.role = 'opponent' AND g.outcome = 'loss')
                    THEN 1 ELSE 0
                END),
                SUM(CASE
                    WHEN (p.role = 'player' AND g.outcome = 'loss')
                      OR (p.role = 'opponent' AND g.outcome = 'win')
                    THEN 1 ELSE 0
                END),
                SUM(s.cards_played),
                SUM(s.cards_drawn),
                SUM(s.cards_discarded),
                SUM(s.cards_milled),
                SUM(s.damage_dealt),
                SUM(s.damage_taken)
            FROM game_participant_stats s
            JOIN participants p ON p.id = s.participant_id
            JOIN games g ON g.id = s.game_id
            WHERE g.session_id = ?
            GROUP BY g.session_id, p.role
            ON CONFLICT(session_id, role) DO UPDATE SET
                games = excluded.games,
                wins = excluded.wins,
                losses = excluded.losses,
                cards_played = excluded.cards_played,
                cards_drawn = excluded.cards_drawn,
                cards_discarded = excluded.cards_discarded,
                cards_milled = excluded.cards_milled,
                damage_dealt = excluded.damage_dealt,
                damage_taken = excluded.damage_taken
            """,
            (self.session_id,),
        )

    def _upsert_match_analytics(
        self,
        conn: sqlite3.Connection,
        match_id: str,
        started_at: Optional[str],
        ended_at: str,
        winner_participant_id: Optional[str],
    ) -> None:
        """Persist the current match row."""
        normalized_format = normalize_match_format(
            self.game_state.format_str,
            default_best_of=3 if self.game_state.match_type == "best_of_3" else 1,
        )
        conn.execute(
            """
            INSERT INTO matches (
                id,
                session_id,
                raw_match_id,
                started_at,
                ended_at,
                match_type,
                format,
                queue,
                event_name,
                best_of,
                games_played,
                winner_participant_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                raw_match_id = COALESCE(excluded.raw_match_id, matches.raw_match_id),
                ended_at = excluded.ended_at,
                match_type = excluded.match_type,
                format = excluded.format,
                queue = excluded.queue,
                event_name = excluded.event_name,
                best_of = excluded.best_of,
                games_played = excluded.games_played,
                winner_participant_id = excluded.winner_participant_id
            """,
            (
                match_id,
                self.session_id,
                getattr(self.game_state, "arena_match_id", None),
                started_at,
                ended_at,
                self.game_state.match_type,
                self.game_state.format_str,
                self.game_state.player_deck_event_name,
                self.game_state.player_deck_event_name,
                normalized_format.best_of,
                int(self.game_state.game_number or 1),
                winner_participant_id,
            ),
        )

    def _upsert_game_analytics(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        match_id: str,
        started_at: Optional[str],
        ended_at: str,
        duration_seconds: Optional[int],
        outcome: str,
        reason: str,
        winner_participant_id: Optional[str],
    ) -> None:
        """Persist the current game row."""
        player_turns, opponent_turns = self._participant_turn_counts()
        conn.execute(
            """
            INSERT INTO games (
                id,
                session_id,
                match_id,
                game_number,
                started_at,
                ended_at,
                duration_seconds,
                total_turns,
                player_turns,
                opponent_turns,
                outcome,
                outcome_reason,
                winner_participant_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ended_at = excluded.ended_at,
                duration_seconds = excluded.duration_seconds,
                total_turns = excluded.total_turns,
                player_turns = excluded.player_turns,
                opponent_turns = excluded.opponent_turns,
                outcome = excluded.outcome,
                outcome_reason = excluded.outcome_reason,
                winner_participant_id = excluded.winner_participant_id
            """,
            (
                game_id,
                self.session_id,
                match_id,
                int(self.game_state.game_number or 1),
                started_at,
                ended_at,
                duration_seconds,
                self._turns_completed(),
                player_turns,
                opponent_turns,
                outcome,
                reason,
                winner_participant_id,
            ),
        )

    def _upsert_participant_analytics(
        self, conn: sqlite3.Connection, participants: List[Dict[str, Any]]
    ) -> None:
        """Persist player/opponent participant rows."""
        for participant in participants:
            conn.execute(
                """
                INSERT INTO participants (
                    id,
                    game_id,
                    seat_id,
                    role,
                    display_name,
                    deck_name,
                    deck_id,
                    deck_archetype,
                    deck_size,
                    deck_size_source,
                    opening_hand_size,
                    mulligans,
                    starting_life,
                    ending_life,
                    went_first
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    seat_id = excluded.seat_id,
                    display_name = excluded.display_name,
                    deck_name = excluded.deck_name,
                    deck_id = excluded.deck_id,
                    deck_archetype = excluded.deck_archetype,
                    deck_size = excluded.deck_size,
                    deck_size_source = excluded.deck_size_source,
                    opening_hand_size = excluded.opening_hand_size,
                    mulligans = excluded.mulligans,
                    starting_life = excluded.starting_life,
                    ending_life = excluded.ending_life,
                    went_first = excluded.went_first
                """,
                (
                    participant["id"],
                    participant["game_id"],
                    participant["seat_id"],
                    participant["role"],
                    participant["display_name"],
                    participant["deck_name"],
                    participant["deck_id"],
                    participant["deck_archetype"],
                    participant["deck_size"],
                    participant["deck_size_source"],
                    participant["opening_hand_size"],
                    participant["mulligans"],
                    participant["starting_life"],
                    participant["ending_life"],
                    participant["went_first"],
                ),
            )

    def _opponent_archetype(self, game_id: str) -> Optional[str]:
        """Cached AI archetype for a game, if the background lookup finished.

        Never calls the API — _start_opponent_archetype_lookup does that on a
        daemon thread so a slow provider can't hold up live tracking.
        """
        cache = getattr(self, "_archetype_cache", None) or {}
        return cache.get(game_id)

    def _opponent_card_names(self) -> List[str]:
        """Distinct opponent card names seen this game, in observed order."""
        names: List[str] = []
        seen = set()
        for event in getattr(self, "opponent_cards", []) or []:
            name = str(getattr(event, "card_name", "") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def _start_opponent_archetype_lookup(self, game_id: str) -> None:
        """Fire one background AI deck-identification call for a finished game.

        Fire-and-forget: tracking never waits on the provider. When the call
        succeeds the worker caches the name and updates the persisted opponent
        row (with brief retries in case persistence is still in flight); the
        dashboard's Game Detail page surfaces it. At most one call per game.
        """
        try:
            if not is_deck_llm_enabled() or self._is_untracked_match():
                return
        except Exception:
            return
        cache = getattr(self, "_archetype_cache", None)
        if cache is None:
            cache = {}
            self._archetype_cache = cache
        if game_id in cache:
            return
        card_names = self._opponent_card_names()
        if len(card_names) < 3:
            return
        cache[game_id] = None  # mark attempted so no second call ever fires
        db_path = getattr(self._analytics_store(), "path", None)

        def _worker() -> None:
            try:
                archetype = identify_deck(card_names)
            except Exception:
                archetype = None
            if not archetype:
                return
            cache[game_id] = archetype
            if db_path is not None:
                # Persistence may still be finishing on the main thread —
                # retry briefly until the opponent row exists to update.
                for attempt in range(5):
                    try:
                        conn = sqlite3.connect(str(db_path), timeout=5)
                        try:
                            with conn:
                                cursor = conn.execute(
                                    "UPDATE participants SET deck_archetype = ? "
                                    "WHERE game_id = ? AND role = 'opponent'",
                                    (archetype, game_id),
                                )
                            if cursor.rowcount > 0:
                                break
                        finally:
                            conn.close()
                    except sqlite3.Error:
                        pass
                    time.sleep(2 * (attempt + 1))
            # No console output: the result arrives after "Ready for next
            # game..." and a late line looks out of place. The dashboard's
            # Game Detail page shows the identified archetype instead.

        threading.Thread(target=_worker, name="deck-ai-lookup", daemon=True).start()

    def _persist_game_detail_analytics(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        player_participant_id: str,
        opponent_participant_id: str,
    ) -> None:
        """Persist per-participant stats, cards, opening hand, commanders, and session aggregates."""
        self._persist_participant_stats(
            conn,
            game_id,
            player_participant_id,
            self.game_state.player_seat_id,
            len(self.player_cards),
        )
        self._persist_participant_stats(
            conn,
            game_id,
            opponent_participant_id,
            self.game_state.opponent_seat_id,
            len(self.opponent_cards),
        )
        drawn_cards_by_seat = getattr(self.game_state, "drawn_card_events", {}) or {}
        persist_card_summary(
            conn,
            game_id,
            player_participant_id,
            self.player_cards,
            refresh_display_name=self._refresh_fallback_name_text,
            drawn_events=drawn_cards_by_seat.get(self.game_state.player_seat_id, []),
        )
        persist_card_summary(
            conn,
            game_id,
            opponent_participant_id,
            self.opponent_cards,
            refresh_display_name=self._refresh_fallback_name_text,
            drawn_events=drawn_cards_by_seat.get(self.game_state.opponent_seat_id, []),
        )
        if self.game_state.submitted_deck_cards:
            persist_submitted_deck(
                conn,
                game_id,
                player_participant_id,
                deck_cards=self.game_state.submitted_deck_cards,
                sideboard_cards=self.game_state.submitted_sideboard_cards,
                resolve_name=self.card_db.get_card_name,
                resolve_type_category=self.card_db.get_card_type_category,
            )
        persist_opening_hand(
            conn,
            game_id,
            player_participant_id,
            starting_hand_events=self.game_state.starting_hand_events,
            starting_hand=self.game_state.starting_hand,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_mulligan_hands(
            conn,
            game_id,
            player_participant_id,
            self.game_state.mulligan_hand_history,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_drawn_cards(
            conn,
            game_id,
            player_participant_id,
            drawn_cards_by_seat.get(self.game_state.player_seat_id, []),
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_drawn_cards(
            conn,
            game_id,
            opponent_participant_id,
            drawn_cards_by_seat.get(self.game_state.opponent_seat_id, []),
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_commanders(
            conn,
            player_participant_id,
            self.game_state.player_commanders,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_commanders(
            conn,
            opponent_participant_id,
            self.game_state.opponent_commanders,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        try:
            color_index = self.card_db.color_identity_index_by_name()
            if color_index:
                AnalyticsStore.backfill_card_colors(conn, color_index)
            mana_index = self.card_db.mana_cost_index_by_name()
            if mana_index:
                AnalyticsStore.backfill_card_mana(conn, mana_index)
        except (AttributeError, sqlite3.Error, OSError, TypeError, ValueError):
            pass
        try:
            # Import-and-queue-immediately games arrive from Arena named
            # "Imported Deck"; once the SAME exact maindeck shows up under
            # the real name (usually the very next game), retitle them now
            # instead of waiting for the next tracker restart.
            AnalyticsStore.canonicalize_imported_deck_names(conn)
        except sqlite3.Error:
            pass
        try:
            # Game boundary: allow one re-scan for a newer Arena card DB
            # (set-release day drops a new Raw_CardDatabase mid-session).
            self.card_db.allow_db_recheck()
        except AttributeError:
            pass
        self._refresh_session_participant_stats(conn)

    def _persist_turn_timings(self, conn: sqlite3.Connection, game_id: str) -> None:
        """Persist one timing row for each observed turn in the completed game."""
        conn.execute("DELETE FROM game_turns WHERE game_id = ?", (game_id,))
        turns_by_number: Dict[int, Dict[str, Any]] = {}
        for turn in self.game_state.completed_turns:
            turn_number = int(turn.get("turn_number", 0))
            existing = turns_by_number.get(turn_number)
            if existing is None:
                turns_by_number[turn_number] = dict(turn)
                continue
            started_at = turn.get("started_at")
            ended_at = turn.get("ended_at")
            if isinstance(started_at, datetime) and (
                not isinstance(existing.get("started_at"), datetime)
                or started_at < existing["started_at"]
            ):
                existing["started_at"] = started_at
            if isinstance(ended_at, datetime) and (
                not isinstance(existing.get("ended_at"), datetime)
                or ended_at > existing["ended_at"]
            ):
                existing["ended_at"] = ended_at
            existing["duration_seconds"] = int(existing.get("duration_seconds", 0)) + int(
                turn.get("duration_seconds", 0)
            )

        for turn_number in sorted(turns_by_number):
            turn = turns_by_number[turn_number]
            started_at = turn.get("started_at")
            ended_at = turn.get("ended_at")
            conn.execute(
                """
                INSERT INTO game_turns (
                    game_id, turn_number, seat_id, started_at, ended_at, duration_seconds,
                    timing_source
                ) VALUES (?, ?, ?, ?, ?, ?, 'live')
                """,
                (
                    game_id,
                    turn_number,
                    turn.get("seat_id"),
                    started_at.isoformat() if isinstance(started_at, datetime) else None,
                    ended_at.isoformat() if isinstance(ended_at, datetime) else None,
                    int(turn.get("duration_seconds", 0)),
                ),
            )

    def _persist_turn_timings_with_recovery(self, conn: sqlite3.Connection, game_id: str) -> None:
        """Persist live timings and recover immediately if the write is incomplete."""
        self._persist_turn_timings(conn, game_id)
        observed_turns = len(
            {
                int(turn.get("turn_number", 0))
                for turn in self.game_state.completed_turns
                if int(turn.get("turn_number", 0)) > 0
            }
        )
        total_turns = self._turns_completed()
        persisted_turns = int(
            conn.execute(
                "SELECT COUNT(*) FROM game_turns WHERE game_id = ?", (game_id,)
            ).fetchone()[0]
        )
        if persisted_turns < total_turns:
            AnalyticsStore.backfill_recovered_game_turn_times(conn, game_id)
            persisted_turns = int(
                conn.execute(
                    "SELECT COUNT(*) FROM game_turns WHERE game_id = ?", (game_id,)
                ).fetchone()[0]
            )
        if persisted_turns < observed_turns:
            raise sqlite3.IntegrityError(
                f"saved {persisted_turns} of {observed_turns} observed turn timing rows"
            )

    def _persist_game_analytics(self, outcome: str, reason: str) -> None:
        """Persist dashboard-ready summary data for a completed game."""
        if self._is_untracked_match():
            return
        # A "game" with no turns, no opening hand, and no draws is a ghost:
        # typically a post-concede message tail misread as a new game. BUT a
        # concede during the mulligan decision is a REAL game with a real
        # result (an opponent scooping to your opener is a win Arena scores)
        # — the opening mulligan prompt is the tell, because re-sent final
        # states never carry one.
        took_any_turn = any(self.game_state.turns_taken_by_seat.get(seat) for seat in (1, 2))
        pregame_concede = (
            self.game_state.opening_mulligan_prompt_seen
            or bool(self.game_state._hand_before_mulligan)
        ) and outcome in ("win", "loss")
        if (
            not took_any_turn
            and not self.game_state.starting_hand
            and not self.game_state.drawn_card_events.get(self.game_state.player_seat_id)
            and not pregame_concede
        ):
            self._print_line("👻 Skipping ghost game record (no turns or cards observed).")
            self._purge_ghost_game_breadcrumbs()
            return
        # Pre-keep concede: the hand shown during the mulligan decision IS
        # the opening hand — adopt it so the game record shows those cards.
        if not self.game_state.starting_hand and self.game_state._hand_before_mulligan:
            self._finalize_starting_hand(
                list(self.game_state._hand_before_mulligan),
                list(self.game_state._hand_before_mulligan_ids),
                list(self.game_state._hand_before_mulligan_events),
            )
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            match_id = self._current_match_id()
            game_id = self._current_game_id()
            player_participant_id = self._participant_id_for_role(game_id, "player")
            opponent_participant_id = self._participant_id_for_role(game_id, "opponent")
            winner_participant_id = None
            if outcome == "win":
                winner_participant_id = player_participant_id
            elif outcome == "loss":
                winner_participant_id = opponent_participant_id
            started_at = (
                self.game_state.game_start_time.isoformat()
                if self.game_state.game_start_time
                else None
            )
            ended_at = (self.game_state.game_end_time or datetime.now()).isoformat()
            duration_seconds = None
            if self.game_state.game_start_time:
                duration_seconds = max(
                    0,
                    int(
                        (
                            (self.game_state.game_end_time or datetime.now())
                            - self.game_state.game_start_time
                        ).total_seconds()
                    ),
                )
            player = self._participant_snapshot(game_id, "player", self.game_state.player_seat_id)
            opponent = self._participant_snapshot(
                game_id, "opponent", self.game_state.opponent_seat_id
            )

            # Keep the dashboard's core game record independent from optional
            # card/stat detail. One malformed detail row must not erase a
            # completed game from Recent Games.
            def persist_core() -> None:
                self._upsert_session_row(conn)
                self._upsert_match_analytics(
                    conn, match_id, started_at, ended_at, winner_participant_id
                )
                self._upsert_game_analytics(
                    conn,
                    game_id,
                    match_id,
                    started_at,
                    ended_at,
                    duration_seconds,
                    outcome,
                    reason,
                    winner_participant_id,
                )
                self._upsert_participant_analytics(conn, [player, opponent])

            self._run_analytics_write(conn, persist_core)

            try:

                def persist_details() -> None:
                    self._persist_game_detail_analytics(
                        conn,
                        game_id,
                        player_participant_id,
                        opponent_participant_id,
                    )

                self._run_analytics_write(conn, persist_details)
            except sqlite3.Error as exc:
                self._report_analytics_persistence_error("game details", game_id, exc)

            try:
                self._run_analytics_write(
                    conn, lambda: self._persist_turn_timings_with_recovery(conn, game_id)
                )
            except sqlite3.Error as exc:
                self._report_analytics_persistence_error("turn timings", game_id, exc)
                try:
                    self._run_analytics_write(
                        conn,
                        lambda: AnalyticsStore.backfill_recovered_game_turn_times(conn, game_id),
                    )
                except sqlite3.Error as recovery_exc:
                    self._report_analytics_persistence_error(
                        "turn timing recovery", game_id, recovery_exc
                    )
        except sqlite3.Error as exc:
            game_id = locals().get("game_id", "unknown")
            self._report_analytics_persistence_error("core game", game_id, exc)

    def _report_analytics_persistence_error(
        self, stage: str, game_id: str, error: sqlite3.Error
    ) -> None:
        """Write persistence failures without recursively writing to SQLite."""
        output_stream = getattr(self, "output_stream", sys.stdout)
        output_stream.write(
            self._style(
                f"Analytics warning: could not save {stage} for {game_id}: {error}",
                "warning",
            )
            + "\n"
        )
        output_stream.flush()
