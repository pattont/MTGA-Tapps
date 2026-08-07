"""Game lifecycle and result CardTracker mixin methods."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .opening_hand import state_has_opening_hand_zone
from .state import GameState


class TrackerLifecycleMixin:
    """Game start/end, winner, and match lifecycle helpers used by CardTracker."""

    def _reset_game_state(self):
        """Reset game state for a new game."""
        self.game_state = GameState()
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False

    def _find_nested(self, data: Any, key: str) -> Any:
        """Find a key in nested data structure."""
        if isinstance(data, dict):
            if key in data:
                return data[key]
            for value in data.values():
                result = self._find_nested(value, key)
                if result is not None:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self._find_nested(item, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _normalize_seat_id(value: Any) -> Optional[int]:
        """Convert seat/team IDs to 1/2 when possible."""
        try:
            seat = int(value)
        except (TypeError, ValueError):
            return None
        return seat if seat in (1, 2) else None

    def _set_winner_seat(self, seat_id: Any, *, reason: str, priority: int) -> bool:
        """Set winner seat if source priority is strong enough.

        Priority guide:
          4: Structured game-over JSON (authoritative)
          3: Local client concede request
          2: Seat-specific concede / generic JSON hints
          1: Text heuristics (left/disconnect/concede phrases)
        """
        seat = self._normalize_seat_id(seat_id)
        if seat is None:
            return False

        current = self.game_state.winner_seat
        current_priority = getattr(self.game_state, "winner_priority", 0)

        # Never let weaker evidence override stronger evidence.
        if current is not None and priority < current_priority:
            return False

        # Avoid flip-flopping on same-priority contradictory hints.
        if current is not None and priority == current_priority:
            return False

        self.game_state.winner_seat = seat
        self.game_state.winner_priority = priority
        self.game_state.winner_reason = reason

        return True

    def _try_parse_winner_from_json(self, data: Optional[Dict[str, Any]]) -> Optional[int]:
        """Try to get winner seat (1 or 2) from parsed game-end JSON. Returns None if not found."""
        if not data or not isinstance(data, dict):
            return None

        latest_result = self._extract_latest_game_result(data)
        if latest_result is not None:
            seat = self._normalize_seat_id(
                latest_result.get("winningTeamId")
                or latest_result.get("winningteamid")
                or latest_result.get("winnerSeatId")
                or latest_result.get("winningSeatId")
            )
            if seat is not None:
                return seat

        # Loser seat → winner is the other seat
        loser = self._find_nested(data, "loserSeatId") or self._find_nested(data, "loserSeat")
        loser_seat = self._normalize_seat_id(loser)
        if loser_seat is not None:
            return 2 if loser_seat == 1 else 1

        # Winning team/seat fallback (MTGA may use different keys outside structured result arrays).
        for key in (
            "winningTeamId",
            "winningteamid",
            "winnerSeatId",
            "winnerSeat",
            "winningSeatId",
            "winner",
        ):
            v = self._find_nested(data, key)
            seat = self._normalize_seat_id(v)
            if seat is not None:
                return seat

        # Fallback: infer from player statuses (PendingLoss/InGame) at game over.
        players = self._find_nested(data, "players")
        if isinstance(players, list):
            pending_loss_seats: List[int] = []
            in_game_seats: List[int] = []
            for player in players:
                if not isinstance(player, dict):
                    continue
                seat = self._normalize_seat_id(player.get("systemSeatNumber"))
                if seat is None:
                    continue
                status = str(player.get("status", ""))
                if "PendingLoss" in status:
                    pending_loss_seats.append(seat)
                elif "InGame" in status:
                    in_game_seats.append(seat)
            if len(in_game_seats) == 1:
                return in_game_seats[0]
            if len(pending_loss_seats) == 1:
                return 2 if pending_loss_seats[0] == 1 else 1

        # Fallback: infer from team statuses.
        teams = self._find_nested(data, "teams")
        if isinstance(teams, list):
            pending_loss_teams: List[int] = []
            for team in teams:
                if not isinstance(team, dict):
                    continue
                team_id = self._normalize_seat_id(team.get("id"))
                if team_id is None:
                    continue
                if "PendingLoss" in str(team.get("status", "")):
                    pending_loss_teams.append(team_id)
            if len(pending_loss_teams) == 1:
                return 2 if pending_loss_teams[0] == 1 else 1

        return None

    def _extract_latest_game_result(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the newest structured WinLoss game result, falling back to match scope."""
        return self._extract_latest_structured_result(data, "WinLoss")

    def _extract_latest_draw_result(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the newest structured draw result, falling back to match scope."""
        return self._extract_latest_structured_result(data, "Draw")

    def _extract_latest_structured_result(
        self,
        data: Dict[str, Any],
        result_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Return newest result matching `result_name`, preferring game scope."""
        result_groups: List[List[Dict[str, Any]]] = []
        game_info = self._find_nested(data, "gameInfo")
        if isinstance(game_info, dict) and isinstance(game_info.get("results"), list):
            result_groups.append([r for r in game_info["results"] if isinstance(r, dict)])
        final_match = self._find_nested(data, "finalMatchResult")
        if isinstance(final_match, dict) and isinstance(final_match.get("resultList"), list):
            result_groups.append([r for r in final_match["resultList"] if isinstance(r, dict)])
        intermission = self._find_nested(data, "intermissionReq")
        if isinstance(intermission, dict) and isinstance(intermission.get("result"), dict):
            result_groups.append([intermission["result"]])

        match_scope_fallback: Optional[Dict[str, Any]] = None
        unscoped_fallback: Optional[Dict[str, Any]] = None
        for results in result_groups:
            for result in reversed(results):
                result_type = str(result.get("result", ""))
                if result_name not in result_type:
                    continue
                scope = str(result.get("scope", ""))
                if "MatchScope_Game" in scope:
                    return result
                if match_scope_fallback is None and "MatchScope_Match" in scope:
                    match_scope_fallback = result
                elif match_scope_fallback is None and unscoped_fallback is None:
                    unscoped_fallback = result
        return match_scope_fallback or unscoped_fallback

    def _check_if_mid_game(self):
        """Only set mid-game if the tail of the log shows an active game and no match-end (lobby = match already ended)."""
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-300:] if len(lines) > 300 else lines

            # If the tail contains match-end, we're in lobby or between games — not mid-game
            match_end_markers = (
                "matchcompleted",
                "gamecompleted",
                "concedereq",
                "matchendscene",
                "you left",
                "opponent left",
                "you concede",
                "opponent concede",
                "finalresults",
                "on sceneloaded for matchendscene",
            )
            tail_text = "\n".join(tail).lower()
            if any(m in tail_text for m in match_end_markers):
                return

            # No match-end in tail; check for active game state (turn > 0 or zones with cards)
            for line in reversed(tail):
                for event in self._extract_game_state_events(line):
                    if event.get("type") != "game_state":
                        continue
                    data = event.get("data", {})
                    if "turnInfo" in data:
                        turn_num = (data.get("turnInfo") or {}).get("turnNumber", 0)
                        if turn_num and turn_num > 0:
                            self.waiting_for_next_game = True
                            self._print_line("\n" + "=" * 75)
                            self._print_line("⚠️  DETECTED GAME IN PROGRESS")
                            self._print_line("=" * 75)
                            self._print_line("   Tracker launched mid-game.")
                            self._print_line(
                                "   Will start tracking at the beginning of the next game."
                            )
                            self._print_line("=" * 75 + "\n")
                            return
                    if "zones" in data:
                        for zone in data.get("zones") or []:
                            ztype = zone.get("type") or ""
                            objs = zone.get("objectInstanceIds", [])
                            if objs and ("Battlefield" in ztype or "Hand" in ztype):
                                self.waiting_for_next_game = True
                                self._print_line("\n" + "=" * 75)
                                self._print_line("⚠️  DETECTED GAME IN PROGRESS")
                                self._print_line("=" * 75)
                                self._print_line("   Tracker launched mid-game.")
                                self._print_line(
                                    "   Will start tracking at the beginning of the next game."
                                )
                                self._print_line("=" * 75 + "\n")
                                return
        except Exception:
            pass

    def _process_new_events(self):
        """Process new events from the log file."""
        read_entries = getattr(self.parser, "read_new_entries", None)
        if callable(read_entries):
            for entry in read_entries():
                routed = (
                    self.parser.route_entry(entry) if hasattr(self.parser, "route_entry") else None
                )
                if routed is not None:
                    category = getattr(routed, "category", None)
                    if category == "unknown":
                        self._append_parser_diagnostic_log(entry.body)
                    if (
                        category == "unknown"
                        or getattr(routed, "malformed_json", False)
                        or category
                        in {
                            "connection_state",
                            "tcp_connection_close",
                            "websocket_closed",
                            "connection_error",
                        }
                    ):
                        self._record_raw_payload_snapshot(str(category or "unknown"), entry.body)
                line = self.parser._entry_to_legacy_line(entry)
                self._process_line(line, timestamp=getattr(entry, "timestamp", None))
        else:
            for line in self.parser.read_new_lines():
                self._process_line(line)
        # Defer game summary until after all lines processed (so ConcedeReq can set winner before we print)
        if self.game_state.match_complete and self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False

    def _process_line(self, line: str, timestamp: Optional[datetime] = None):
        """Process a single line from the log file.

        Args:
            line: A line from the MTGA log file.
        """
        prior_event_time = getattr(self, "_current_event_time", None)
        self._current_event_time = timestamp
        try:
            # Arena restamps its Detailed Logs state whenever it relaunches.
            if "DETAILED LOGS: DISABLED" in line:
                self._print_detailed_logs_warning()
            elif "DETAILED LOGS: ENABLED" in line:
                self._print_line("✅ Detailed Logs are enabled in Arena — ready to track.")
            self._process_rank_progress(line)
            # Always try to pick up match metadata (format, player name) from any line
            self._parse_match_metadata(line)
            for message in self._extract_gre_messages(line):
                self._capture_submitted_deck_message(message)
                self._capture_casting_time_options_requests(message)
            for payload in self._extract_client_gre_payloads(line):
                self._handle_client_gre_payload(payload)

            # Skip processing if we're waiting for the next game (launched mid-game)
            if self.waiting_for_next_game:
                # Only check for new game start, ignore everything else
                self._check_game_start(line)
                return

            # Try to detect player seat if not yet detected
            if self.game_state.player_seat_id is None:
                self._try_detect_player_seat(line)

            # Check for game start. A completed game keeps in_match=True until the next
            # game's first state packet arrives, so completed matches must still listen.
            if not self.game_state.in_match or self.game_state.match_complete:
                self._check_game_start(line)

            # Check for game end (always call when in_match so ConcedeReq can set winner even after MatchCompleted)
            if self.game_state.in_match:
                self._check_game_end(line)
                # Recent MTGA logs include DeclareBlockersReq; use it for snapshots only (not definitive block output).
                self._process_blocker_requests_from_line(line)

            # Look for card-related events in GRE message order.
            for event in self._extract_game_state_events(line):
                self._handle_event(event)
        finally:
            self._current_event_time = prior_event_time

    def _line_indicates_live_mulligan_start(self, line: str) -> bool:
        """Return True when a mulligan marker line represents a live game start, not a game-over payload."""
        line_lower = line.lower()
        # "mulliganCount" appears in ordinary player state diffs (including
        # the Bo3 sideboard SubmitDeckReq batch, which still carries the
        # PREVIOUS game's turnInfo) — it is bookkeeping, not a mulligan
        # prompt, so it must never read as a game-start marker.
        mulligan_markers = line_lower.replace("mulligancount", "")
        if not (
            "mulligantype" in mulligan_markers
            or (
                "mulligan" in mulligan_markers
                and ("gretolient" in mulligan_markers or "gretoclient" in mulligan_markers)
            )
            or "mulliganreq" in mulligan_markers
        ):
            return False

        json_data = self.parser.parse_json_from_line(line)
        if isinstance(json_data, dict):
            game_info = self._find_nested(json_data, "gameInfo")
            if isinstance(game_info, dict):
                stage = str(game_info.get("stage", ""))
                match_state = str(game_info.get("matchState", ""))
                if (
                    "GameStage_GameOver" in stage
                    or "MatchState_GameComplete" in match_state
                    or "MatchState_MatchComplete" in match_state
                ):
                    return False
        return True

    def _print_new_game_detected(self) -> None:
        """Print the marker used when a new game starts after a completed game."""
        self._print_line("\n" + "=" * 75)
        self._print_line("✅ NEW GAME DETECTED - Starting to track!")
        self._print_line("=" * 75 + "\n")

    def _line_has_state_game_start(self, line: str) -> bool:
        """Return True when state packets show turn 1 or an opening hand."""
        for event in self._extract_game_state_events(line):
            if event.get("type") != "game_state":
                continue
            data = event.get("data", {})
            if "turnInfo" in data:
                turn_info = data.get("turnInfo", {})
                if turn_info.get("turnNumber", 0) == 1:
                    return True
            if state_has_opening_hand_zone(data):
                return True
        return False

    def _capture_arena_game_info(self, data: Dict[str, Any]) -> None:
        """Harvest Arena's own match identity from a gameStateMessage's gameInfo.

        Arena stamps game-state packets with the match UUID, the game number
        within the match, and the win condition. That is the authoritative
        signal for grouping Bo3 games — far more reliable than the event-name
        heuristics, which stay as a fallback for logs without gameInfo.
        """
        if self.game_state.match_complete:
            # A completed game's state is frozen; the game-start boundary in
            # _check_game_start owns the transition to the next game/match.
            return
        game_info = data.get("gameInfo")
        if not isinstance(game_info, dict):
            return
        stage = str(game_info.get("stage", ""))
        match_state = str(game_info.get("matchState", ""))
        if not self.game_state.in_match and (
            "GameStage_GameOver" in stage
            or "MatchState_GameComplete" in match_state
            or "MatchState_MatchComplete" in match_state
        ):
            # Arena re-sends a match's final GameOver state even after the
            # summary reset. Adopting identity from a dying packet outside a
            # match would poison the NEXT game with the previous game's match
            # UUID — its persist would then overwrite the finished game's row.
            return
        match_id = game_info.get("matchID")
        if isinstance(match_id, str) and match_id and self.game_state.arena_match_id is None:
            self.game_state.arena_match_id = match_id
        win_condition = str(game_info.get("matchWinCondition") or "")
        if "Best2of3" in win_condition:
            self.game_state.match_type = "best_of_3"
        try:
            game_number = int(game_info.get("gameNumber"))
        except (TypeError, ValueError):
            game_number = 0
        if game_number >= 1:
            self.game_state.game_number = game_number
            if game_number > 1:
                self.game_state.match_type = "best_of_3"

    def _line_arena_game_info(self, line: str) -> Dict[str, Any]:
        """Return Arena gameInfo identity fields present on a log line."""
        info: Dict[str, Any] = {}
        if "matchid" not in line.lower():
            return info
        for event in self._extract_game_state_events(line):
            if event.get("type") != "game_state":
                continue
            game_info = (event.get("data") or {}).get("gameInfo")
            if not isinstance(game_info, dict):
                continue
            match_id = game_info.get("matchID")
            if isinstance(match_id, str) and match_id:
                info["match_id"] = match_id
            try:
                game_number = int(game_info.get("gameNumber"))
            except (TypeError, ValueError):
                game_number = 0
            if game_number >= 1:
                info["game_number"] = game_number
            if info:
                break
        return info

    def _line_has_game_over_payload(self, line: str) -> bool:
        """Return True when a line's gameInfo marks a game or match as over."""
        json_data = self.parser.parse_json_from_line(line)
        if not isinstance(json_data, dict):
            return False
        game_info = self._find_nested(json_data, "gameInfo")
        if not isinstance(game_info, dict):
            return False
        stage = str(game_info.get("stage", ""))
        match_state = str(game_info.get("matchState", ""))
        return (
            "GameStage_GameOver" in stage
            or "MatchState_GameComplete" in match_state
            or "MatchState_MatchComplete" in match_state
        )

    def _release_waiting_for_next_game_if_detected(self, line: str) -> None:
        """Clear waiting mode when a new game's first marker appears."""
        if not self.waiting_for_next_game:
            return
        if self._line_indicates_live_mulligan_start(line):
            self.game_state.opening_mulligan_prompt_seen = True
            self.waiting_for_next_game = False
            self._print_new_game_detected()
        elif self._line_has_state_game_start(line):
            self.waiting_for_next_game = False
            self._print_new_game_detected()

    def _bo3_match_continues(self) -> bool:
        """Return True when the just-completed game leaves its Bo3 match undecided.

        Requires Arena's match UUID: without it we cannot safely match the next
        game start to this match, so legacy logs keep the old reset behavior.
        """
        if self.game_state.match_type != "best_of_3":
            return False
        if not self.game_state.arena_match_id:
            return False
        if self.game_state.arena_match_over:
            return False
        wins = {1: 0, 2: 0}
        for game in self.match_games:
            winner = game.get("winner")
            if winner in (1, 2):
                wins[winner] += 1
        if self.game_state.winner_seat in (1, 2):
            wins[self.game_state.winner_seat] += 1
        return wins[1] < 2 and wins[2] < 2

    def _prepare_next_match_game(self) -> None:
        """Reset state when another game starts in the same match."""
        was_best_of_three = self.game_state.match_type == "best_of_3"
        next_game_number = int(self.game_state.game_number or 1) + 1
        completed_game = {
            "game_number": self.game_state.game_number,
            "winner": self.game_state.winner_seat,
            "player_cards": self.player_cards.copy(),
            "opponent_cards": self.opponent_cards.copy(),
            "player_life": self.game_state.player_life,
            "opponent_life": self.game_state.opponent_life,
        }
        # Carry match-scoped identity across the per-game reset: the next game
        # belongs to the same Arena match, and game 2+ log lines rarely restate
        # the format, opponent, or deck. Built BEFORE the summary flush below,
        # which may reset game_state. Applied in _reset_new_game_tracking after
        # its metadata backfill, so freshly detected data still wins.
        continuation = {
            "game_number": next_game_number,
            "format_str": self.game_state.format_str,
            "opponent_display_name": self.game_state.opponent_display_name,
            "arena_match_id": self.game_state.arena_match_id,
            "player_deck_event_name": self.game_state.player_deck_event_name,
            "player_deck_name": self.game_state.player_deck_name,
            "player_deck_id": self.game_state.player_deck_id,
        }
        if self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False
        if not was_best_of_three:
            return

        self.match_games.append(completed_game)
        self._pending_bo3_continuation = continuation

        self._print_line("\n" + "=" * 75)
        self._print_line(f"🔄 GAME {next_game_number} STARTING (Best-of-3 Match)")
        self._print_line("=" * 75 + "\n")
        self.game_state.reset()
        self.game_state.match_type = "best_of_3"
        self.game_state.game_number = next_game_number
        self.game_state.arena_match_id = continuation["arena_match_id"]
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False
        self._active_deck_candidate_key = None

    def _finish_completed_best_of_one_before_new_start(self) -> None:
        """Flush a completed BO1 game before processing the next match start."""
        if self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False
        else:
            self.game_state.reset()
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False
        self._active_deck_candidate_key = None
        self._require_explicit_game_start = False

    def _reset_new_game_tracking(self, *, opening_mulligan_prompt_seen: bool) -> None:
        """Initialize tracking fields for a newly detected game."""
        self.game_state.format_str = "Unknown"
        self.game_state.match_type = "best_of_1"
        # A stale Arena match UUID here is poison: this game's rows would be
        # written under the PREVIOUS match's pinned ordinal, overwriting it.
        # The current start line (or a Bo3 continuation below) re-supplies it.
        self.game_state.arena_match_id = None
        self.game_state.arena_match_over = False
        self._format_from_backfill = False
        self.game_state.game_start_time = self._now()
        self.game_state.in_match = True
        self.game_state.match_complete = False
        self.game_state.mid_game_attach = False
        self.game_state.starting_hand = []
        self.game_state.starting_hand_events = []
        self.game_state.initial_hand_size = 7
        self.game_state.mulligan_count = 0
        self.game_state._hand_before_mulligan = []
        self.game_state._hand_before_mulligan_ids = []
        self.game_state._hand_before_mulligan_instance_ids = []
        self.game_state._hand_before_mulligan_events = []
        self.game_state.opening_hand_capture_closed = False
        self.game_state.opening_mulligan_prompt_seen = opening_mulligan_prompt_seen
        self.game_state.explicit_mulligan_count = 0
        self.game_state.opening_keep_confirmed = False
        self.game_state.opening_select_n_ids = []
        self.game_state.submitted_deck_cards = list(
            getattr(self, "_pending_submitted_deck_cards", [])
        )
        self.game_state.submitted_sideboard_cards = list(
            getattr(self, "_pending_submitted_sideboard_cards", [])
        )
        self.game_state.player_seat_id = None
        self.game_state.opponent_seat_id = None
        self.game_state.opponent_display_name = None
        self.game_state._reserved_players = []
        self.game_state.seat_line_announced = False
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False
        self._deck_candidates = {}
        self._active_deck_candidate_key = None
        self.game_state.player_deck_name = None
        self.game_state.player_deck_id = None
        self.game_state.player_deck_event_name = None
        self.game_state.player_deck_last_played = None
        self._backfill_recent_match_metadata(
            max_lines=1800, force=True, trust_match_room_format=False
        )
        if not self._refresh_current_match_room_metadata():
            self.game_state.format_str = "Unknown"
            self.game_state.match_type = "best_of_1"
            self._format_from_backfill = False
        self._pending_event_format = None
        self._require_explicit_game_start = False

        continuation = getattr(self, "_pending_bo3_continuation", None)
        self._pending_bo3_continuation = None
        if not continuation:
            # A brand-new match: completed games of the previous match must not
            # leak into this match's Bo3 status or win counting.
            self.match_games = []
        if continuation:
            # This start is game 2+ of the same Arena match: restore the
            # match-scoped identity the per-game reset and metadata backfill
            # could not re-derive. Freshly detected values keep priority.
            self.game_state.match_type = "best_of_3"
            self.game_state.game_number = int(continuation.get("game_number") or 1)
            carried_format = continuation.get("format_str")
            if carried_format and carried_format != "Unknown" and (
                self.game_state.format_str in (None, "", "Unknown")
            ):
                self.game_state.format_str = carried_format
            if self.game_state.arena_match_id is None:
                self.game_state.arena_match_id = continuation.get("arena_match_id")
            if not self.game_state.opponent_display_name:
                self.game_state.opponent_display_name = continuation.get(
                    "opponent_display_name"
                )
            if not self.game_state.player_deck_event_name:
                self.game_state.player_deck_event_name = continuation.get(
                    "player_deck_event_name"
                )
            if not self.game_state.player_deck_name:
                self.game_state.player_deck_name = continuation.get("player_deck_name")
                self.game_state.player_deck_id = continuation.get("player_deck_id")

    def _hydrate_start_line_state(self, line: str) -> None:
        """Apply state metadata bundled on the same line as a start marker."""
        for state_event in self._extract_game_state_events(line):
            event_data = state_event.get("data", {})
            if isinstance(event_data, dict):
                self._capture_arena_game_info(event_data)
                self._update_format_from_game_state(event_data)
                self._remove_deleted_instances(event_data.get("diffDeletedInstanceIds"))
                self._snapshot_game_objects(event_data.get("gameObjects", []))
                self._update_commanders_from_game_state(event_data)
                self._capture_opening_hand(event_data)

    def _print_game_started_banner(self, *, verbose: bool) -> None:
        """Print the game-start banner."""
        self._print_line("\n" + "=" * 75)
        if verbose:
            self._print_line("🟡 🔵 ⚫ 🔴 🟢 GAME STARTED 🟡 🔵 ⚫ 🔴 🟢")
        else:
            format_display = self._friendly_format_label(self.game_state.format_str)
            game_num_display = (
                f" (Game {self.game_state.game_number})"
                if self.game_state.match_type == "best_of_3"
                else ""
            )
            self._print_line(
                f"🟡 🔵 ⚫ 🔴 🟢 GAME STARTED - {format_display}{game_num_display} 🟡 🔵 ⚫ 🔴 🟢"
            )
        self._print_line("=" * 75)
        self._print_match_started_block()

    def _check_game_start(self, line: str):
        """Check if a game is starting."""
        explicit_start_required = (
            self._require_explicit_game_start and not self.waiting_for_next_game
        )

        self._release_waiting_for_next_game_if_detected(line)
        if self.waiting_for_next_game:
            return

        if self.game_state.in_match and self.game_state.match_complete:
            if not (
                self._line_indicates_live_mulligan_start(line)
                or self._line_has_state_game_start(line)
            ):
                return
            if self._line_has_game_over_payload(line):
                # The completed game's own tail: its final full snapshot
                # carries hand zones that read as an "opening hand" and its
                # old turnInfo. Treating it as the next game's start builds a
                # ghost game 2 from game 1's dying state.
                return
            incoming = self._line_arena_game_info(line)
            incoming_match_id = incoming.get("match_id")
            incoming_game_number = int(incoming.get("game_number") or 0)
            previous_match_id = self.game_state.arena_match_id
            if (
                incoming_match_id
                and previous_match_id
                and incoming_match_id == previous_match_id
                and incoming_game_number
                and incoming_game_number <= int(self.game_state.game_number or 1)
            ):
                # Same match, same (or older) game number: more tail packets
                # of the game that just ended — not a new game starting.
                return
            if incoming_match_id and previous_match_id:
                # Arena's own match UUID is authoritative: the same UUID means
                # this start is the next game of the same Bo3 match; a
                # different UUID means a brand-new match — regardless of what
                # the event-name heuristics concluded about the match type.
                if incoming_match_id == previous_match_id:
                    self.game_state.match_type = "best_of_3"
                    self._prepare_next_match_game()
                else:
                    self._finish_completed_best_of_one_before_new_start()
            elif self.game_state.match_type == "best_of_3":
                self._prepare_next_match_game()
            else:
                self._finish_completed_best_of_one_before_new_start()

        if self.game_state.in_match:
            return

        if self._line_indicates_live_mulligan_start(line):
            if self.waiting_for_next_game:
                self.waiting_for_next_game = False
                self._print_new_game_detected()
            self._reset_new_game_tracking(opening_mulligan_prompt_seen=True)
            self._hydrate_start_line_state(line)
            self._print_game_started_banner(verbose=True)
            return

        for event in self._extract_game_state_events(line):
            if event.get("type") != "game_state":
                continue
            data = event.get("data", {})

            if "turnInfo" in data:
                turn_info = data["turnInfo"]
                turn_num = turn_info.get("turnNumber", 0)
                if turn_num >= 1:
                    if explicit_start_required and turn_num != 1:
                        return
                    if self.waiting_for_next_game:
                        self.waiting_for_next_game = False
                        self._print_new_game_detected()
                    self._reset_new_game_tracking(opening_mulligan_prompt_seen=False)
                    # Arena's gameInfo rides the same packet; capture it now so
                    # the start banner already knows Bo3 / the game number.
                    self._capture_arena_game_info(data)
                    if turn_num > 1:
                        # The game's start was never observed (truncated log or
                        # tracker launched mid-game): partial data would poison
                        # draw, opener, and timing stats, so show it live only.
                        self.game_state.mid_game_attach = True
                    self._print_game_started_banner(verbose=False)
                    if self.game_state.mid_game_attach:
                        self._print_line(
                            f"⏱️  Joined mid-game at turn {turn_num} — this game is shown live "
                            "but won't be saved. Tracking resumes with the next game."
                        )
                    return

            if explicit_start_required:
                break

            if state_has_opening_hand_zone(data) and not self.game_state.in_match:
                if self.waiting_for_next_game:
                    self.waiting_for_next_game = False
                    self._print_new_game_detected()
                self._reset_new_game_tracking(
                    opening_mulligan_prompt_seen=self._has_mulligan_prompt_in_state(data)
                )
                self._capture_arena_game_info(data)
                self._capture_opening_hand(data)
                self._print_game_started_banner(verbose=False)
                return

            self._capture_opening_hand(data)

    def _mark_match_complete_now(self) -> bool:
        """Mark the current match complete and queue summary printing."""
        if self.game_state.match_complete:
            return False
        self.game_state.match_complete = True
        self.game_state.game_end_time = self._now()
        self._pending_game_summary = True
        return True

    def _parse_line_winner_hint(self, line: str) -> tuple[Optional[Dict[str, Any]], bool]:
        """Parse a line for structured winner hints and return payload plus game-over flag."""
        json_data = self.parser.parse_json_from_line(line)
        structured_match_complete = False
        if json_data:
            game_info = self._find_nested(json_data, "gameInfo")
            if isinstance(game_info, dict):
                stage = str(game_info.get("stage", ""))
                match_state = str(game_info.get("matchState", ""))
                if "GameStage_GameOver" in stage and "MatchState_GameComplete" in match_state:
                    structured_match_complete = True
                if "MatchState_MatchComplete" in match_state:
                    self.game_state.arena_match_over = True
            if isinstance(self._find_nested(json_data, "finalMatchResult"), dict):
                self.game_state.arena_match_over = True
            winner = self._try_parse_winner_from_json(json_data)
            if winner is not None:
                winner_priority = 4 if structured_match_complete else 2
                winner_reason = (
                    "structured_game_over_json" if structured_match_complete else "json_winner_hint"
                )
                self._set_winner_seat(winner, reason=winner_reason, priority=winner_priority)
            draw_result = self._extract_latest_draw_result(json_data)
            if draw_result is not None:
                self.game_state.result_type = str(draw_result.get("result") or "ResultType_Draw")
                self.game_state.result_reason = str(
                    draw_result.get("reason") or "ResultReason_Draw"
                )
                structured_match_complete = True
        return json_data, structured_match_complete

    def _handle_concede_end_line(
        self, line: str, line_lower: str, json_data: Optional[Dict[str, Any]]
    ) -> bool:
        """Handle explicit concede request lines."""
        if "concedereq" not in line_lower and "clientmessagetype_concedereq" not in line_lower:
            return False
        seat_id = self._find_nested(json_data, "systemSeatId") if json_data else None
        if seat_id is not None:
            if seat_id == self.game_state.player_seat_id:
                self._set_winner_seat(
                    self.game_state.opponent_seat_id,
                    reason="concede_req:player_conceded",
                    priority=2,
                )
            elif seat_id == self.game_state.opponent_seat_id:
                self._set_winner_seat(
                    self.game_state.player_seat_id,
                    reason="concede_req:opponent_conceded",
                    priority=2,
                )
        elif "clienttogremessage" in line_lower or "clientmessagetype_concedereq" in line_lower:
            # This log stream is from the local client, so an outgoing concede request is ours.
            self._set_winner_seat(
                self.game_state.opponent_seat_id,
                reason="concede_req:local_player_conceded",
                priority=3,
            )
        return self.game_state.winner_seat is not None and self._mark_match_complete_now()

    @staticmethod
    def _line_indicates_local_player_loss(line_lower: str) -> bool:
        """Return True for text patterns showing the local player left or lost."""
        local_loss = any(
            pattern in line_lower
            for pattern in [
                "youleft",
                "you left",
                "i left",
                "i concede",
                "you concede",
                "conceded the match",
                "quit the match",
                "defeat",
                "you were defeated",
                "you disconnected",
                "i disconnected",
                "forfeit",
                "you forfeit",
                "i forfeit",
                "forfeited",
            ]
        )
        opponent_left = any(
            pattern in line_lower
            for pattern in [
                "opponentleft",
                "opponent left",
                "opponent quit",
            ]
        )
        return local_loss and not opponent_left

    def _handle_game_completion_pattern(self, line: str, line_lower: str) -> bool:
        """Handle explicit game-completion payload patterns."""
        if not any(
            pattern in line_lower
            for pattern in [
                "gamecompletedtype",
                "finalresults",
                "matchendscene",
                "on sceneloaded for matchendscene",
            ]
        ):
            return False
        json_data = self.parser.parse_json_from_line(line)
        if not json_data or self.game_state.match_complete:
            return False
        self.game_state.match_complete = True
        self.game_state.game_end_time = self._now()
        winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(
            json_data, "winningteamid"
        )
        if winner_team is not None and winner_team in (1, 2):
            self._set_winner_seat(
                winner_team, reason="game_complete_pattern:winner_team", priority=4
            )
        self._pending_game_summary = True
        return True

    def _handle_playing_to_completed_transition(self, line: str, line_lower: str) -> bool:
        """Handle state transition from Playing to MatchCompleted."""
        if '"old":"playing"' not in line_lower or '"new":"matchcompleted"' not in line_lower:
            return False
        if self.game_state.match_complete:
            return False
        self.game_state.match_complete = True
        self.game_state.game_end_time = self._now()
        json_data = self.parser.parse_json_from_line(line)
        if json_data:
            winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(
                json_data, "winningteamid"
            )
            if winner_team is not None and winner_team in (1, 2):
                self._set_winner_seat(
                    winner_team, reason="state_transition:winner_team", priority=4
                )
        self._pending_game_summary = True
        return True

    def _check_game_end(self, line: str):
        """Check if the game has ended."""
        if not self.game_state.in_match:
            return
        line_lower = line.lower()
        json_data, structured_match_complete = self._parse_line_winner_hint(line)

        if self._handle_concede_end_line(line, line_lower, json_data):
            return

        # Structured end-of-game records from current MTGA logs.
        if structured_match_complete and self._mark_match_complete_now():
            return

        if self._line_indicates_local_player_loss(line_lower):
            self._set_winner_seat(
                self.game_state.opponent_seat_id,
                reason="text:player_left_or_forfeited",
                priority=1,
            )
            self._mark_match_complete_now()
            return

        # Check for match completion state changes - be very specific
        # Only set match_complete here; do NOT set winner_seat (we don't know who won from this line).
        if '"old":"matchcompleted"' in line_lower or '"old":"MatchCompleted"' in line:
            if (
                '"new":"matchcompleted"' in line_lower
                or '"new":"MatchCompleted"' in line
                or '"new":"disconnected"' in line_lower
            ):
                if self._mark_match_complete_now():
                    return

        if self._handle_game_completion_pattern(line, line_lower):
            return

        if self._handle_playing_to_completed_transition(line, line_lower):
            return

    def _handle_event(self, event: Dict[str, Any]):
        """Handle a card event.

        Args:
            event: Event data extracted from the log.
        """
        event_type = event.get("type")
        event_data = event.get("data", {})

        if event_type != "game_state":
            return

        # Process turn and print header FIRST so "Turn 1 - YOUR TURN" appears before
        # card plays and life changes from this message.
        self._update_game_state(event_data)
        self._capture_opening_hand(event_data)

        # Then process annotations (card plays, etc.) so they appear under the turn header.
        self._process_game_events(event_data)

    def _resolve_game_outcome(self) -> tuple:
        """Resolve game outcome as ('win'|'loss'|'draw'|'unknown', reason)."""
        if str(getattr(self.game_state, "result_type", "")) == "ResultType_Draw":
            return "draw", self._draw_reason_text(getattr(self.game_state, "result_reason", None))

        pl, ol = self.game_state.player_life, self.game_state.opponent_life
        if pl <= 0:
            return "loss", "You reached 0 life"
        if ol <= 0:
            return "win", "Opponent reached 0 life"

        if self.game_state.winner_seat is not None and self.game_state.player_seat_id in (1, 2):
            if self.game_state.winner_seat == self.game_state.player_seat_id:
                return "win", "Opponent conceded/disconnected"
            if self.game_state.winner_seat == self.game_state.opponent_seat_id:
                return "loss", "You conceded/left the game"
            return "unknown", f"Winning seat: {self.game_state.winner_seat}"

        if self.game_state.winner_seat is not None:
            return "unknown", f"Winning seat: {self.game_state.winner_seat}"

        return "unknown", f"Life totals: You {pl} - {ol} Opponent"

    @staticmethod
    def _draw_reason_text(result_reason: Optional[str]) -> str:
        """Return a user-facing reason for a structured draw result."""
        if result_reason == "ResultReason_Force":
            return "Match ended in a forced draw"
        if result_reason:
            return str(result_reason).replace("ResultReason_", "").replace("_", " ")
        return "Match ended in a draw"

    def _record_session_outcome(self, outcome: str) -> None:
        """Record one game result in session totals exactly once."""
        if self._session_stats_recorded_this_game or self._is_untracked_match():
            return

        self.session_games_played += 1
        self.session_game_runtime_seconds += self._current_game_duration_seconds()
        if (
            self.game_state.first_player_seat in (1, 2)
            and self.game_state.player_seat_id in (1, 2)
            and self.game_state.first_player_seat == self.game_state.player_seat_id
        ):
            self.session_player_went_first = getattr(self, "session_player_went_first", 0) + 1
        elif (
            self.game_state.first_player_seat in (1, 2)
            and self.game_state.opponent_seat_id in (1, 2)
            and self.game_state.first_player_seat == self.game_state.opponent_seat_id
        ):
            self.session_opponent_went_first = getattr(self, "session_opponent_went_first", 0) + 1
        else:
            self.session_first_unknown = getattr(self, "session_first_unknown", 0) + 1
        if outcome == "win":
            self.session_wins += 1
        elif outcome == "loss":
            self.session_losses += 1
        elif outcome == "draw":
            self.session_draws = getattr(self, "session_draws", 0) + 1
        else:
            self.session_unknown += 1
        self._record_session_deck_outcome(outcome)
        self._session_stats_recorded_this_game = True

    def _try_resolve_winner_from_log_tail(self) -> None:
        """Last-chance winner lookup from recent structured log payloads."""
        if self.game_state.winner_seat is not None:
            return
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-100:] if len(lines) > 100 else lines
            for line in reversed(tail):
                data = self.parser.parse_json_from_line(line)
                if not data:
                    continue
                winner = self._try_parse_winner_from_json(data)
                if winner is not None:
                    self._set_winner_seat(
                        winner, reason="summary_tail:json_winner_hint", priority=2
                    )
                    return
        except Exception:
            return

    def _game_duration_display(self) -> str:
        """Return the current game duration label."""
        if not (self.game_state.game_start_time and self.game_state.game_end_time):
            return "Unknown"
        duration = self.game_state.game_end_time - self.game_state.game_start_time
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)
        return f"{minutes}m {seconds}s"
