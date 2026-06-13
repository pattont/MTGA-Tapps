"""Console rendering and display-formatting CardTracker mixin methods."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .log_sanitize import scrub_raw_log
from .rendering import apply_style, display_path_without_username, should_use_colors


class TrackerRenderingMixin:
    """Extracted helpers used by CardTracker."""

    def _should_use_colors(self) -> bool:
        """Return True when ANSI colors should be emitted."""
        return should_use_colors()

    def _style(self, text: str, style: Optional[str] = None) -> str:
        """Apply ANSI style if enabled."""
        return apply_style(
            text,
            style,
            use_colors=self.use_colors,
            styles=self._ansi_styles,
            reset=self._ansi_reset,
        )

    @staticmethod
    def _display_path_without_username(path_value: Any) -> str:
        """Return a display path with the user's home directory shortened to ~/."""
        return display_path_without_username(path_value)

    def _print_line(self, text: str = "", style: Optional[str] = None) -> None:
        """Print one console line and persist the same logical output for dashboards."""
        raw_text = "" if text is None else str(text)
        self._record_console_log(raw_text, style=style)
        sys.stdout.write(self._style(raw_text, style) + "\n")

    def _print_event(self, text: str, style: Optional[str] = None) -> None:
        """Print an event line with optional style."""
        self._print_line(text, style=style)
        self._record_game_event(text, style=style)

    def _print_summary_heading(self, text: str, style: str = "turn") -> None:
        """Print a more prominent summary heading."""
        self._print_line(text.upper(), style=style)

    def _turn_prefix_for_number(self, turn_num: Optional[int]) -> str:
        """Return elapsed match time prefix for event lines."""
        if self.game_state.game_start_time is None:
            return "[0:00] "
        elapsed = max(0, int((self._now() - self.game_state.game_start_time).total_seconds()))
        return f"[{self._format_duration(elapsed)}] "

    def _seat_label(self, seat_id: Optional[int]) -> str:
        """Map seat id to display actor label."""
        if seat_id == self.game_state.player_seat_id:
            return "You"
        if seat_id == self.game_state.opponent_seat_id:
            return "Opponent"
        return "Unknown"

    def _event_turn_number(
        self, seat_id: Optional[int], preferred_turn: Optional[int] = None
    ) -> int:
        """Best-effort event turn number with startup fallback when turnInfo has not arrived yet."""
        if preferred_turn is not None and int(preferred_turn) > 0:
            return int(preferred_turn)
        inferred = self._turn_for_seat(seat_id)
        if inferred > 0:
            return int(inferred)
        if (
            self.game_state.in_match
            and self.game_state.last_turn_announced == 0
            and seat_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
        ):
            return 1
        return int(inferred) if inferred else 0

    def _format_actor_event(
        self,
        icon: str,
        seat_id: Optional[int],
        text: str,
        *,
        turn_override: Optional[int] = None,
    ) -> str:
        """Format one event line with consistent turn + actor prefix."""
        turn_num = self._event_turn_number(seat_id, turn_override)
        self._ensure_turn_header_for_event(seat_id, turn_num)
        turn_prefix = self._turn_prefix_for_number(turn_num)
        return f"{turn_prefix}{self._seat_label(seat_id)}: {text}"

    @staticmethod
    def _format_mana_cost(mana_cost: Any) -> str:
        """Format MTGA manaCost arrays as {1}{R}-style text."""
        if not isinstance(mana_cost, list):
            return ""
        parts: List[str] = []
        for item in mana_cost:
            if not isinstance(item, dict):
                continue
            colors = item.get("color") or []
            count = item.get("count", 1)
            if not isinstance(count, int) or count <= 0:
                count = 1
            if not isinstance(colors, list) or not colors:
                continue
            tokens: List[str] = []
            for color in colors:
                raw = str(color).replace("ManaColor_", "")
                if raw == "Generic":
                    tokens.append(str(count))
                    continue
                if raw == "Colorless":
                    tokens.extend(["C"] * count)
                    continue
                if raw == "X":
                    tokens.extend(["X"] * count)
                    continue
                if raw.startswith("Phyrexian"):
                    tokens.extend([raw.replace("Phyrexian", "") + "/P"] * count)
                    continue
                if raw.startswith("Hybrid"):
                    symbol = raw.replace("Hybrid", "")
                    tokens.extend([symbol] * count)
                    continue
                tokens.extend([raw[:1]] * count)
            parts.extend(f"{{{token}}}" for token in tokens if token)
        return "".join(parts)

    @staticmethod
    def _normalize_ability_text(text: Optional[str]) -> str:
        """Convert MTGA localization ability text to a cleaner readable form."""
        if not isinstance(text, str):
            return ""
        cleaned = text.strip()
        if not cleaned:
            return ""
        cleaned = re.sub(
            r"\{o([^}]*)\}",
            lambda m: "".join(f"{{{tok}}}" for tok in re.findall(r"[A-Z]+|\d+", m.group(1))),
            cleaned,
        )
        cleaned = re.sub(r"\{T\}", "tap", cleaned)
        cleaned = re.sub(r"\{Q\}", "untap", cleaned)
        cleaned = re.sub(r"\{([^{}]+)\}", r"\1", cleaned)
        cleaned = re.sub(r"CLASSLEVEL \[(\d+\+?)\] \[\] \[(.*)\]", r"Level \1: \2", cleaned)
        cleaned = cleaned.replace("oT", "T")
        return cleaned

    @staticmethod
    def _is_mana_ability_text(text: Optional[str]) -> bool:
        """Return True for visible mana abilities that should not clutter the log."""
        normalized = TrackerRenderingMixin._normalize_ability_text(text).lower()
        if not normalized:
            return False
        return bool(
            re.search(r"(^|:)\s*add\s+(\{|\w+ mana)", normalized)
            or re.search(r"\badd\s+\{", normalized)
            or re.search(r"(^|:)\s*add\s+[wubrgcx0-9]+(?:\.|,|$)", normalized)
        )

    def _emit_ability_event(
        self,
        icon: str,
        seat_id: Optional[int],
        card_name: str,
        ability_text: str,
        *,
        target_text: str = "",
        turn_override: Optional[int] = None,
        style: str = "ability",
    ) -> None:
        """Print one normalized ability event line."""
        normalized = self._normalize_ability_text(ability_text)
        if not normalized:
            normalized = "activated ability"
        self._print_event(
            self._format_actor_event(
                icon,
                seat_id,
                f"[{card_name}] - {normalized}{target_text}",
                turn_override=turn_override,
            ),
            style,
        )

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        """Format duration as H:MM:SS or M:SS."""
        total_seconds = max(0, int(total_seconds))
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _session_runtime_str(self) -> str:
        """Return active session game time."""
        return self._format_duration(self._session_play_runtime_seconds())

    def _session_first_counts(self) -> tuple[int, int, int]:
        """Return session first-player counts as player, opponent, unknown."""
        return (
            int(getattr(self, "session_player_went_first", 0) or 0),
            int(getattr(self, "session_opponent_went_first", 0) or 0),
            int(getattr(self, "session_first_unknown", 0) or 0),
        )

    def _session_first_split_line(self) -> str:
        """Return detailed session first-player split."""
        player_first, opponent_first, unknown = self._session_first_counts()
        known = player_first + opponent_first
        if known <= 0:
            if unknown:
                return f"Went First: Not captured ({unknown} unknown)"
            return "Went First: Not captured"
        player_pct = 100.0 * player_first / known
        opponent_pct = 100.0 * opponent_first / known
        line = (
            f"Went First: You {player_first}/{known} ({player_pct:.1f}%), "
            f"Opponent {opponent_first}/{known} ({opponent_pct:.1f}%)"
        )
        if unknown:
            line += f", Unknown {unknown}"
        return line

    def _session_first_split_compact(self) -> str:
        """Return compact first-player split for one-line session stats."""
        player_first, opponent_first, _unknown = self._session_first_counts()
        known = player_first + opponent_first
        if known <= 0:
            return "First: n/a"
        return (
            f"First: You {100.0 * player_first / known:.1f}% / "
            f"Opp {100.0 * opponent_first / known:.1f}%"
        )

    def _session_stats_line(self) -> str:
        """Return one-line session W/L stats."""
        known_results = self.session_wins + self.session_losses
        win_rate = (self.session_wins / known_results * 100.0) if known_results > 0 else 0.0
        draw_part = (
            f" D:{getattr(self, 'session_draws', 0)}" if getattr(self, "session_draws", 0) else ""
        )
        unknown_part = f", ?:{self.session_unknown}" if self.session_unknown else ""
        return (
            f"W:{self.session_wins} L:{self.session_losses}{draw_part}{unknown_part} | "
            f"Games:{self.session_games_played} | WR:{win_rate:.1f}% | "
            f"{self._session_first_split_compact()} | Play Time:{self._session_runtime_str()}"
        )

    def _refresh_fallback_name_text(self, text: Optional[str]) -> str:
        """Replace fallback ``Card #<id>`` tokens with local DB names when available."""
        if not isinstance(text, str) or not text:
            return text or ""

        def _replace(match: re.Match[str]) -> str:
            grp_id = int(match.group(1))
            resolved = self.card_db.get_card_name(grp_id)
            if isinstance(resolved, str) and resolved and not resolved.startswith("Card #"):
                return resolved
            return match.group(0)

        return re.sub(r"Card #(\d+)", _replace, text)

    def _print_startup_legend(self) -> None:
        """Print a short event color legend."""
        self._print_line(" Card Event Colors:")
        self._print_line("  Turn / Session Header", "turn")
        self._print_line("  Cast / Spell Played", "cast")
        self._print_line("  Land Played", "land")
        self._print_line("  Ability / Trigger", "ability")
        self._print_line("  Stack Resolved", "stack_resolve")
        self._print_line("  Stack Countered / Unresolved", "stack_fail")
        self._print_line("  Attack", "attack")
        self._print_line("  Block", "block")
        self._print_line("  Combat Damage", "combat_damage")
        self._print_line("  Damage", "damage")
        self._print_line("  Life Gained", "life_gain")
        self._print_line("  Life Lost", "life_loss")
        self._print_line("  Draw", "draw")
        self._print_line("  Card Movement", "zone")
        if not self.use_colors:
            self._print_line("     (Color is off; set MTGA_TRACKER_COLOR=1 to force)")

    def _turn_for_seat(self, seat_id: Optional[int]) -> int:
        """Best-effort turn number for events attributed to a seat."""
        if seat_id == self.game_state.player_seat_id:
            return self.game_state.last_player_turn_number or self.game_state.last_turn_announced
        if seat_id == self.game_state.opponent_seat_id:
            return self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced
        return self.game_state.last_turn_announced

    def _ensure_turn_header_for_event(
        self, seat_id: Optional[int], turn_num: Optional[int]
    ) -> None:
        """Ensure first missing turn header appears when the first stamped event arrives."""
        if not turn_num or turn_num <= 0:
            return
        if not self._is_tracked_seat(seat_id):
            return

        if seat_id == self.game_state.player_seat_id and self.game_state.pending_player_turn_header:
            self._flush_pending_player_turn_header()
            return
        if (
            seat_id == self.game_state.opponent_seat_id
            and self.game_state.pending_opponent_turn_header
        ):
            self._flush_pending_opponent_turn_header()
            return

        if self.game_state.last_turn_announced == 0:
            if seat_id == self.game_state.player_seat_id:
                self.game_state.pending_player_turn_header = self._turn_header_snapshot(
                    turn_num, seat_id
                )
                self._flush_pending_player_turn_header()
            else:
                self.game_state.pending_opponent_turn_header = self._turn_header_snapshot(
                    turn_num, seat_id
                )
                self._flush_pending_opponent_turn_header()

    def _ability_turn_override(self, seat_id: Optional[int]) -> Optional[int]:
        """Best-effort turn number for ability logs that can resolve after turnInfo advances."""
        if seat_id == self.game_state.player_seat_id:
            return (
                self.game_state.last_player_turn_number
                or self.game_state.last_turn_announced
                or None
            )
        if seat_id == self.game_state.opponent_seat_id:
            return (
                self.game_state.last_opponent_turn_number
                or self.game_state.last_turn_announced
                or None
            )
        return self.game_state.last_turn_announced or None

    def _current_game_duration_seconds(self, *, now: Optional[datetime] = None) -> int:
        """Return elapsed seconds for the current game only."""
        if self.game_state.game_start_time is None:
            return 0
        end_time = self.game_state.game_end_time or now or datetime.now()
        return max(0, int((end_time - self.game_state.game_start_time).total_seconds()))

    def _session_play_runtime_seconds(self) -> int:
        """Return active game time, excluding tracker idle/lobby uptime."""
        total = max(0, int(self.session_game_runtime_seconds))
        if (
            self.game_state.in_match
            and not self.game_state.match_complete
            and not self._session_stats_recorded_this_game
        ):
            total += self._current_game_duration_seconds()
        return max(0, int(total))
