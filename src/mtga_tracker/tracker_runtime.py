"""Runtime start/stop loop for CardTracker."""

from __future__ import annotations

import time


class TrackerRuntimeMixin:
    """Console startup and live log polling loop used by CardTracker."""

    def start(self):
        """Start tracking cards."""
        self._print_line("\n" + "=" * 75)
        self._print_line(
            "🟡 🔵 ⚫ 🔴 🟢 MTGA Card Tracker - Real-time Match Analyzer 🟡 🔵 ⚫ 🔴 🟢"
        )
        self._print_line("=" * 75)
        self._print_line(
            f" Monitoring: {self._display_path_without_username(self.parser.log_path)}"
        )
        card_db_path = None
        resolve_db_path = getattr(self.card_db, "_resolve_mtga_db_path", None)
        if callable(resolve_db_path):
            card_db_path = resolve_db_path()
        self._print_line(f" Local Card DB: {self._display_path_without_username(card_db_path)}")
        self._print_line(f" Log DB: {self._display_path_without_username(self._console_db_path)}")
        from . import __version__ as tracker_version

        self._print_line(f" Tracker Version: {tracker_version}")
        self._print_line("\n")

        self._print_startup_legend()
        # self._print_event(f"Session: {self._session_stats_line()}", "turn")

        # self._print_line("\n   Waiting for game events...")
        self._print_line("\n Now reaady to track games in MTGA!")
        self._print_line("\n Press Ctrl+C to stop")
        self._print_line("=" * 75 + "\n")

        # Deck metadata is often logged before startup; backfill from recent lines once.
        self._recover_missing_turn_timings()
        self._backfill_card_colors()
        self._backfill_unresolved_card_labels()
        self._backfill_recent_match_metadata()
        self._backfill_rank_progress()

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
