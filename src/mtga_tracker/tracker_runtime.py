"""Runtime start/stop loop for CardTracker."""

from __future__ import annotations

import time
from typing import Optional

#: Arena stamps this near the top of every Player.log at boot.
DETAILED_LOGS_DISABLED_MARKER = "DETAILED LOGS: DISABLED"
DETAILED_LOGS_ENABLED_MARKER = "DETAILED LOGS: ENABLED"


class TrackerRuntimeMixin:
    """Console startup and live log polling loop used by CardTracker."""

    def _detailed_logs_enabled(self) -> Optional[bool]:
        """Return Arena's DETAILED LOGS state from the log head, None if unknown."""
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as handle:
                head = handle.read(200_000)
        except Exception:
            return None
        state: Optional[bool] = None
        for line in head.splitlines():
            if DETAILED_LOGS_DISABLED_MARKER in line:
                state = False
            elif DETAILED_LOGS_ENABLED_MARKER in line:
                state = True
        return state

    def _print_deck_ai_status(self) -> None:
        """One startup line saying whether AI deck identification is active."""
        try:
            from .deck_llm import diagnose

            status = diagnose()
            if not status.get("enabled"):
                return
            provider_label = {
                "openai": "OpenAI",
                "claude": "Anthropic (Claude)",
                "gemini": "Gemini",
            }.get(str(status.get("provider") or ""), str(status.get("provider") or "?"))
            if status.get("has_api_key"):
                self._print_line(
                    f" Deck AI: enabled — {provider_label} ({status.get('model') or '?'})"
                )
            else:
                self._print_line(
                    f" Deck AI: enabled but NO API KEY for {provider_label} — "
                    "add one in Settings"
                )
        except Exception:
            return

    def _print_detailed_logs_warning(self) -> None:
        """Print the can't-track warning for Arena's Detailed Logs setting."""
        self._print_line("")
        self._print_line("=" * 75)
        self._print_line(
            "⚠️  DETAILED LOGS ARE DISABLED IN ARENA — GAMES CANNOT BE TRACKED!", "attack"
        )
        self._print_line("=" * 75)
        self._print_line("   To fix it, in MTG Arena:")
        self._print_line("   1. Click the gear icon (top right) → Adjust Options")
        self._print_line("   2. Open Account")
        self._print_line('   3. Check "Detailed Logs (Plugin Support)"')
        self._print_line("   4. Restart MTG Arena")
        self._print_line("=" * 75 + "\n")

    def start(self):
        """Start tracking cards."""
        self._print_line("\n" + "=" * 75)
        self._print_line(
            "🟡 🔵 ⚫ 🔴 🟢 MTGA Card Tracker - Real-time Match Analyzer 🟡 🔵 ⚫ 🔴 🟢"
        )
        self._print_line("=" * 75)
        # Paths / Deck AI / version live on the dashboard's Settings page now
        # (fed through live_status), and the color legend is rendered under
        # the Live Log feed — neither clutters the log itself anymore.
        card_db_path = self._live_card_db_path()
        if card_db_path is None:
            self._print_line(
                " ⚠️  Without Arena's card database, cards appear as 'Card #NNNN'. If Arena is"
            )
            self._print_line(
                "    installed somewhere custom, set the MTGA_DATA_DIR environment variable to"
            )
            self._print_line(
                "    its card-data folder: <Arena install>\\MTGA_Data\\Downloads\\Raw"
            )

        # Remember the state so the live loop only announces CHANGES —
        # Arena restamps it on relaunch and repeats cluttered the startup.
        detailed_logs_state = self._detailed_logs_enabled()
        self._detailed_logs_last_state = detailed_logs_state
        if detailed_logs_state is False:
            self._print_detailed_logs_warning()

        # One-time maintenance runs INSIDE the startup block so its messages
        # (resolved card labels, recovered timings) sit with the banner
        # instead of dangling after "Now ready to track".
        self._recover_missing_turn_timings()
        self._reassign_misattributed_game_events()
        self._backfill_card_colors()
        self._backfill_unresolved_card_labels()
        self._backfill_recent_match_metadata()
        self._backfill_rank_progress()
        self._backfill_inventory()

        # self._print_line("\n   Waiting for game events...")
        self._print_line("\n Now ready to track games in MTGA!")
        self._print_line("\n Press Ctrl+C to stop")
        self._print_line("=" * 75 + "\n")

        # Start from current end of file
        self.parser.reset_position()

        # Check if we're launching mid-game
        self._check_if_mid_game()

        # Safety: If waiting_for_next_game is set, give it a timeout.
        # After 5 minutes, assume we can start tracking.
        self.waiting_start_time = time.time() if self.waiting_for_next_game else None

        self.running = True

        try:
            while self.running:
                # Safety: If we've been waiting for next game for more than 5 minutes, clear the flag.
                if self.waiting_for_next_game and self.waiting_start_time:
                    if time.time() - self.waiting_start_time > 300:
                        self._print_line("\n" + "=" * 75)
                        self._print_line("⚠️  TIMEOUT: Clearing waiting flag - starting to track")
                        self._print_line("=" * 75 + "\n")
                        self.waiting_for_next_game = False
                        self.waiting_start_time = None

                self._process_new_events()
                self._live_heartbeat()
                time.sleep(0.5)
        except KeyboardInterrupt:
            self._print_line("\n" + "=" * 75)
            self._print_line("🛑 Stopping tracker...")
            self._print_summary()
            self._print_line("=" * 75)
        finally:
            self.analytics.close()

    def stop(self):
        """Stop tracking cards."""
        self.running = False
        self.analytics.close()

    def request_stop(self) -> None:
        """Ask the polling loop to stop and let its owning thread close resources."""
        self.running = False
