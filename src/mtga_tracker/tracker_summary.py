"""Summary rendering CardTracker mixin methods."""

from __future__ import annotations

from typing import Dict, List, Optional

from .deck_llm import identify_deck, is_deck_llm_enabled, diagnose as deck_llm_diagnose
from .state import CardEvent



class TrackerSummaryMixin:
    """End-game and session summary rendering helpers used by CardTracker."""

    def _turns_completed(self) -> int:
        """Return best-effort total turn count for the finished game."""
        return max(
            int(self.game_state.turn_number or 0),
            int(self.game_state.last_turn_announced or 0),
            int(self.game_state.last_player_turn_number or 0),
            int(self.game_state.last_opponent_turn_number or 0),
        )

    def _print_match_stats_section(self) -> None:
        """Print per-player match stats block."""
        self._print_line()
        self._print_summary_heading("Match Stats", "turn")
        self._print_line(f"   Total Turns: {self._turns_completed()}")
        for seat_id, label in (
            (self.game_state.player_seat_id, "You"),
            (self.game_state.opponent_seat_id, "Opponent"),
        ):
            if seat_id not in (1, 2):
                continue
            stats = self.game_state.match_stats[int(seat_id)]
            cards_played = len(self.player_cards) if seat_id == self.game_state.player_seat_id else len(self.opponent_cards)
            self._print_line(f"\n   {label}:")
            self._print_line(
                f"      Combat: {stats['attacks']} attack step(s), {stats['attacking_creatures']} attacking creature(s), "
                f"{stats['attackers_lost']} attacker(s) lost"
            )
            self._print_line(
                f"      Defense: {stats['blocking_creatures']} blocker(s), {stats['blockers_lost']} blocker(s) lost"
            )
            self._print_line(
                f"      Damage/Life: {stats['total_damage']} damage dealt, {stats['life_lost']} life lost, "
                f"{stats['self_damage']} self-damage, {stats['life_gain']} life gained"
            )
            self._print_line(
                f"      Cards: {cards_played} played, {stats['cards_drawn']} drawn, "
                f"{stats['cards_discarded']} discarded, {stats['cards_milled']} milled, {stats['cards_exiled']} exiled"
            )
            stack_stats = self.game_state.stack_stats[int(seat_id)]
            self._print_line(
                f"      Stack: {stack_stats['put_on_stack']} put on stack, {stack_stats['resolved']} resolved, "
                f"{stack_stats['countered']} countered, {stack_stats['fizzled']} left unresolved"
            )

    def _starting_hand_heading(self) -> str:
        """Return the end-summary heading for the kept opening hand."""
        if not self.game_state.starting_hand:
            return "Starting Hand (Not Captured)"
        card_count = len(self.game_state.starting_hand)
        card_word = "Card" if card_count == 1 else "Cards"
        heading = f"Starting Hand ({card_count} {card_word}"
        if self.game_state.mulligan_count > 0:
            heading += f" - After {self.game_state.mulligan_count} mulligan(s)"
        heading += ")"
        return heading

    @staticmethod
    def _summary_result_line(outcome: str) -> tuple[str, str]:
        """Return result header text and style for a resolved outcome."""
        if outcome == "win":
            return "GAME ENDED - YOU WON", "land"
        if outcome == "loss":
            return "GAME ENDED - YOU LOST", "damage"
        if outcome == "draw":
            return "GAME ENDED - DRAW", "turn"
        return "GAME ENDED - RESULT UNKNOWN", "turn"

    def _print_result_summary(self, outcome: str, reason: str, duration_display: str) -> None:
        """Print the consolidated game-end result block."""
        result_line, result_style = self._summary_result_line(outcome)
        self._print_line("\n" + "="*75)
        self._print_line(result_line, result_style)
        self._print_line(f"Reason: {reason}")
        if outcome == "unknown" and self.game_state.winner_seat is None:
            self._print_line("Result Note: Result unclear — possible concede or disconnect")
        self._print_line(f"Duration: {duration_display}")
        self._print_line(f"Session Stats: {self._session_stats_line()}")
        self._print_line("="*75)

    def _print_best_of_three_status(self) -> None:
        """Print best-of-three game status when applicable."""
        if self.game_state.match_type != "best_of_3":
            return
        self._print_line()
        self._print_summary_heading("Best-of-3 Match Status", "turn")
        self._print_line(f"   Game {self.game_state.game_number} of 3")
        if self.match_games:
            self._print_line("   Previous games:")
            for game in self.match_games:
                game_winner = "You" if game["winner"] == self.game_state.player_seat_id else "Opponent"
                self._print_line(f"      Game {game['game_number']}: {game_winner} won")

    def _print_starting_hand_summary(self) -> None:
        """Print captured starting hand details."""
        self._print_line()
        self._print_summary_heading(self._starting_hand_heading(), "ability")
        if self.game_state.starting_hand:
            for card in self.game_state.starting_hand:
                self._print_line(f"   • [{self._refresh_fallback_name_text(card)}]")
        else:
            self._print_line("   Not captured. Start the tracker before the mulligan/keep screen to record this.")

    def _print_cards_played_summary(self) -> None:
        """Print deck metadata and played-card counts."""
        self._print_line()
        self._print_summary_heading("Cards Played", "cast")
        if not self.game_state.player_deck_name:
            self._resolve_player_deck_from_candidates()
        self._print_line(
            f"   Your Deck: {self.game_state.player_deck_name or 'Unknown (not found in Arena metadata)'}"
        )
        if self.game_state.player_deck_total_cards:
            self._print_line(f"   Your deck total: {self.game_state.player_deck_total_cards}")
        elif self.game_state.player_seat_id in self.game_state.observed_starting_deck_total_by_seat:
            self._print_line(
                f"   Your deck total (estimated): "
                f"{self.game_state.observed_starting_deck_total_by_seat[self.game_state.player_seat_id]}"
            )
        if self._is_brawl_format() and self.game_state.player_commanders:
            self._print_line(f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}")
        if self._is_brawl_format() and self.game_state.opponent_commanders:
            self._print_line(f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}")
        self._print_line(f"   Mulligans: {self.game_state.mulligan_count}")
        self._print_line(f"   Your cards: {len(self.player_cards)}")
        self._print_line(f"   Opponent cards: {len(self.opponent_cards)}")
        if self.game_state.opponent_seat_id in self.game_state.observed_starting_deck_total_by_seat:
            self._print_line(
                f"   Opponent deck total (estimated): "
                f"{self.game_state.observed_starting_deck_total_by_seat[self.game_state.opponent_seat_id]}"
            )
        if is_deck_llm_enabled() and self.opponent_cards:
            self._print_opponent_deck_guess()

    def _print_opponent_deck_guess(self) -> None:
        """Print opponent archetype guess when deck LLM support is enabled."""
        card_names = [event.card_name for event in self.opponent_cards]
        archetype = identify_deck(card_names)
        if archetype:
            self._print_line(f"   Opponent deck: {archetype}")
            return
        diagnostics = deck_llm_diagnose()
        if not diagnostics.get("has_api_key"):
            key_name = {
                "gemini": "GEMINI_API_KEY",
                "openai": "CHATGPT_API_KEY",
                "claude": "CLAUDE_API_KEY",
            }.get(diagnostics.get("provider") or "gemini", "GEMINI_API_KEY")
            self._print_line(f"   Opponent deck: (LLM: no API key — set {key_name} in config.py or env)")
        else:
            self._print_line("   Opponent deck: (LLM: request failed — check key/network)")

    def _print_exile_and_match_stats_summary(self) -> None:
        """Print exile counters and aggregate match stats."""
        self._print_line()
        self._print_summary_heading("Cards Exiled", "zone")
        self._print_line(f"   By Me: {self.game_state.opponent_cards_exiled_by_player}")
        self._print_line(f"   By Opponent: {self.game_state.player_cards_exiled_by_opponent}")
        self._print_match_stats_section()

    def _format_type_breakdown(self, events: List["CardEvent"]) -> str:
        """Return a 'By type: N Lands, M Creatures, ...' string for a list of card events (non-zero only)."""
        order = ["Land", "Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Other"]
        plurals = {"Land": "Lands", "Creature": "Creatures", "Instant": "Instants", "Sorcery": "Sorceries",
                   "Enchantment": "Enchantments", "Artifact": "Artifacts", "Planeswalker": "Planeswalkers", "Other": "Other"}
        counts: Dict[str, int] = {cat: 0 for cat in order}
        for e in events:
            cat = getattr(e, "card_type_category", None) or "Other"
            counts[cat] = counts.get(cat, 0) + 1
        parts = [f"{counts[cat]} {plurals[cat]}" for cat in order if counts[cat] > 0]
        return "By type: " + ", ".join(parts) if parts else "By type: —"

    def _print_card_collection_summary(
        self,
        cards: List[CardEvent],
        *,
        heading: str,
        seat_id: Optional[int],
    ) -> None:
        """Print card list and highest observed creature for one participant."""
        if not cards:
            return
        self._print_line()
        self._print_summary_heading(heading, "cast")
        self._print_line(f"      {self._format_type_breakdown(cards)}")
        card_counts = {}
        for event in cards:
            display_name = self._refresh_fallback_name_text(event.card_name)
            card_counts[display_name] = card_counts.get(display_name, 0) + 1

        for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
            card_name_str = str(card_name)
            suffix = f" x{count}" if count > 1 else ""
            self._print_line(f"      • [{card_name_str}]{suffix}")

        top_creature = self._highest_known_creature_snapshot(seat_id)
        if top_creature:
            self._print_line(
                f"      Highest observed creature: [{top_creature['name']}] "
                f"reached {top_creature['power']}/{top_creature['toughness']}"
            )

    def _print_game_summary(self):
        """Print summary when game ends."""
        self._try_resolve_winner_from_log_tail()
        duration_display = self._game_duration_display()
        outcome, reason = self._resolve_game_outcome()
        self._record_session_outcome(outcome)
        self._print_result_summary(outcome, reason, duration_display)
        self._print_best_of_three_status()
        self._print_starting_hand_summary()
        self._print_cards_played_summary()
        self._print_exile_and_match_stats_summary()
        self._print_card_collection_summary(self.player_cards, heading="Your Cards", seat_id=self.game_state.player_seat_id)
        self._print_card_collection_summary(self.opponent_cards, heading="Opponent's Cards", seat_id=self.game_state.opponent_seat_id)

        self._print_line("\n" + "="*75)
        self._print_line("Ready for next game...\n")

        self._persist_game_analytics(outcome, reason)

        # Reset game state for next game
        self.game_state.reset()
        self._active_deck_candidate_key = None
        self._require_explicit_game_start = True

    def _print_summary(self):
        """Print a summary of tracked cards."""
        self._print_line()
        self._print_summary_heading("Session Summary", "turn")
        self._print_line("=" * 75)
        known_results = self.session_wins + self.session_losses
        win_rate = (self.session_wins / known_results * 100.0) if known_results > 0 else 0.0

        if (
            not self.game_state.in_match
            and not self.player_cards
            and not self.opponent_cards
            and self.session_games_played == 0
            and self.session_player_cards_played == 0
            and self.session_opponent_cards_played == 0
        ):
            self._print_line("   No matches tracked this session.")
            self._print_line("   Make sure to start the tracker before playing a game!")
            return

        self._print_line(f"   Games Played: {self.session_games_played}")
        self._print_line(f"   Wins: {self.session_wins}")
        self._print_line(f"   Losses: {self.session_losses}")
        if getattr(self, "session_draws", 0):
            self._print_line(f"   Draws: {self.session_draws}")
        if self.session_unknown:
            self._print_line(f"   Unknown Results: {self.session_unknown}")
        self._print_line(f"   Win Rate: {win_rate:.1f}%")
        self._print_line(f"   Play Time: {self._session_runtime_str()}")
        self._print_line(f"   Total Mulligans: {self.session_total_mulligans}")
        self._print_line(f"   Total Cards Played: {self.session_player_cards_played}")
        self._print_line(f"   Total Opponent Cards Played: {self.session_opponent_cards_played}")

        if self.player_cards:
            self._print_line()
            self._print_summary_heading("Your Cards This Game", "cast")
            self._print_line(f"      {self._format_type_breakdown(self.player_cards)}")
            # Count duplicates
            card_counts = {}
            for event in self.player_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    self._print_line(f"      • [{card_name_str}] x{count}")
                else:
                    self._print_line(f"      • [{card_name_str}]")

        if self.opponent_cards:
            self._print_line()
            self._print_summary_heading("Opponent's Cards This Game", "cast")
            self._print_line(f"      {self._format_type_breakdown(self.opponent_cards)}")
            # Count duplicates
            card_counts = {}
            for event in self.opponent_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    self._print_line(f"      • [{card_name_str}] x{count}")
                else:
                    self._print_line(f"      • [{card_name_str}]")
