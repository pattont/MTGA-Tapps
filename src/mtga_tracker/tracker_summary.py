"""Summary rendering CardTracker mixin methods."""

from __future__ import annotations

from typing import Dict, List, Optional

from .deck_llm import is_deck_llm_enabled, diagnose as deck_llm_diagnose
from .state import CardEvent


class TrackerSummaryMixin:
    """End-game and session summary rendering helpers used by CardTracker."""

    def _turns_completed(self) -> int:
        """Return best-effort total turn count for the finished game."""
        player_turns, opponent_turns = self._participant_turn_counts()
        if player_turns or opponent_turns:
            return player_turns + opponent_turns
        return max(
            int(self.game_state.turn_number or 0),
            int(self.game_state.last_turn_announced or 0),
            int(self.game_state.last_player_turn_number or 0),
            int(self.game_state.last_opponent_turn_number or 0),
        )

    def _participant_turn_counts(self) -> tuple[int, int]:
        """Return tracked player/opponent turn counts."""
        turns_by_seat = getattr(self.game_state, "turns_taken_by_seat", {}) or {}
        player_turns = (
            len(turns_by_seat.get(int(self.game_state.player_seat_id), set()))
            if self.game_state.player_seat_id in (1, 2)
            else 0
        )
        opponent_turns = (
            len(turns_by_seat.get(int(self.game_state.opponent_seat_id), set()))
            if self.game_state.opponent_seat_id in (1, 2)
            else 0
        )
        if player_turns or opponent_turns:
            return player_turns, opponent_turns

        player_last = int(self.game_state.last_player_turn_number or 0)
        opponent_last = int(self.game_state.last_opponent_turn_number or 0)
        return (1 if player_last else 0), (1 if opponent_last else 0)

    def _turn_time_summary(self, seat_id: Optional[int]) -> tuple[int, int]:
        """Return total timed seconds and completed turns for one seat."""
        if seat_id not in (1, 2):
            return 0, 0
        total_seconds = int(self.game_state.turn_time_seconds_by_seat.get(int(seat_id), 0))
        turn_count = sum(
            1 for turn in self.game_state.completed_turns if turn.get("seat_id") == seat_id
        )
        return total_seconds, turn_count

    def _turn_time_display(self, seat_id: Optional[int]) -> str:
        """Format total and average timed turn length for a participant."""
        total_seconds, turn_count = self._turn_time_summary(seat_id)
        if turn_count == 0:
            return "not available"
        average_seconds = total_seconds // turn_count
        return (
            f"{self._format_duration(total_seconds)} across {turn_count} turn(s) "
            f"({self._format_duration(average_seconds)} avg)"
        )

    def _current_deck_session_key(self) -> tuple[str, str]:
        """Return a stable session key and display name for the active player deck."""
        if not self.game_state.player_deck_name:
            self._resolve_player_deck_from_candidates()
        deck_id = str(self.game_state.player_deck_id or "").strip()
        deck_name = str(self.game_state.player_deck_name or "").strip()
        if deck_id:
            return f"id:{deck_id}", deck_name or "Unnamed deck"
        if deck_name:
            return f"name:{deck_name.casefold()}", deck_name
        return "unknown", "Unknown deck"

    def _record_session_deck_outcome(self, outcome: str) -> None:
        """Accumulate one completed game result under the active player deck."""
        key, display_name = self._current_deck_session_key()
        records = getattr(self, "session_deck_records", None)
        if not isinstance(records, dict):
            records = {}
            self.session_deck_records = records
        record = records.setdefault(
            key,
            {"display_name": display_name, "wins": 0, "losses": 0, "draws": 0, "unknown": 0},
        )
        record["display_name"] = display_name
        if outcome == "win":
            record["wins"] += 1
        elif outcome == "loss":
            record["losses"] += 1
        elif outcome == "draw":
            record["draws"] += 1
        else:
            record["unknown"] += 1

    def _session_deck_record_lines(self) -> List[str]:
        """Render per-deck session win/loss records in stable display order."""
        records = getattr(self, "session_deck_records", {}) or {}
        lines = []
        for record in sorted(records.values(), key=lambda item: str(item["display_name"]).casefold()):
            wins = int(record.get("wins", 0))
            losses = int(record.get("losses", 0))
            known = wins + losses
            win_rate = (wins / known * 100.0) if known else 0.0
            suffixes = []
            if record.get("draws"):
                suffixes.append(f"{record['draws']} draw(s)")
            if record.get("unknown"):
                suffixes.append(f"{record['unknown']} unknown")
            suffix = f"; {', '.join(suffixes)}" if suffixes else ""
            lines.append(
                f"{record['display_name']}: {wins}-{losses} ({win_rate:.1f}%){suffix}"
            )
        return lines

    def _first_player_label_for_current_game(self) -> str:
        """Return user-facing first-player label for the current game."""
        if (
            self.game_state.first_player_seat in (1, 2)
            and self.game_state.player_seat_id in (1, 2)
            and self.game_state.first_player_seat == self.game_state.player_seat_id
        ):
            return "You"
        if (
            self.game_state.first_player_seat in (1, 2)
            and self.game_state.opponent_seat_id in (1, 2)
            and self.game_state.first_player_seat == self.game_state.opponent_seat_id
        ):
            return "Opponent"
        return "Unknown"

    def _print_match_stats_section(self) -> None:
        """Print per-player match stats block."""
        self._print_line()
        self._print_summary_heading("Match Stats", "turn")
        self._print_line(f"   Total Turns: {self._turns_completed()}")
        player_turns, opponent_turns = self._participant_turn_counts()
        self._print_line(f"   Turns: You {player_turns}, Opponent {opponent_turns}")
        self._print_line(
            f"   Turn Time: You {self._turn_time_display(self.game_state.player_seat_id)}, "
            f"Opponent {self._turn_time_display(self.game_state.opponent_seat_id)}"
        )
        self._print_line(f"   Went First This Game: {self._first_player_label_for_current_game()}")
        self._print_line(f"   {self._session_first_split_line()}")
        for seat_id, label in (
            (self.game_state.player_seat_id, "You"),
            (self.game_state.opponent_seat_id, "Opponent"),
        ):
            if seat_id not in (1, 2):
                continue
            stats = self.game_state.match_stats[int(seat_id)]
            cards_played = (
                len(self.player_cards)
                if seat_id == self.game_state.player_seat_id
                else len(self.opponent_cards)
            )
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
        self._print_line("\n" + "=" * 75)
        self._print_line(result_line, result_style)
        self._print_line(f"Reason: {reason}")
        if outcome == "unknown" and self.game_state.winner_seat is None:
            self._print_line("Result Note: Result unclear — possible concede or disconnect")
        self._print_line(f"Format: {self._friendly_format_label()}")
        self._print_line(f"Duration: {duration_display}")
        self._print_line(f"Session Stats: {self._session_stats_line()}")
        for line in self._session_deck_record_lines():
            self._print_line(f"Deck Session: {line}")
        self._print_line("=" * 75)

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
                game_winner = (
                    "You" if game["winner"] == self.game_state.player_seat_id else "Opponent"
                )
                self._print_line(f"      Game {game['game_number']}: {game_winner} won")

    def _print_starting_hand_summary(self) -> None:
        """Print captured starting hand details."""
        self._print_line()
        self._print_summary_heading(self._starting_hand_heading(), "ability")
        if self.game_state.starting_hand:
            for card in self.game_state.starting_hand:
                self._print_line(f"   • [{self._refresh_fallback_name_text(card)}]")
        else:
            self._print_line(
                "   Not captured. Start the tracker before the mulligan/keep screen to record this."
            )

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
            self._print_line(
                f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}"
            )
        if self._is_brawl_format() and self.game_state.opponent_commanders:
            self._print_line(
                f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}"
            )
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
        """Kick off (or report) the AI opponent-deck identification.

        The API call runs on a background thread so a slow provider never
        holds up tracking. The result lands silently in the game's saved
        record (shown on the dashboard's Game Detail page) — a late console
        line after "Ready for next game..." looked out of place. One call
        per game.
        """
        diagnostics = deck_llm_diagnose()
        if not diagnostics.get("has_api_key"):
            key_name = {
                "gemini": "GEMINI_API_KEY",
                "openai": "CHATGPT_API_KEY",
                "claude": "CLAUDE_API_KEY",
            }.get(diagnostics.get("provider") or "gemini", "GEMINI_API_KEY")
            self._print_line(
                f"   Opponent deck: (AI: no API key — set {key_name} in Settings or config.py)"
            )
            return
        game_id = self._current_game_id()
        archetype = self._opponent_archetype(game_id)
        if archetype:
            self._print_line(f"   Opponent deck (AI): {archetype}")
            return
        self._start_opponent_archetype_lookup(game_id)

    def _print_exile_and_match_stats_summary(self) -> None:
        """Print exile counters and aggregate match stats."""
        self._print_line()
        self._print_summary_heading("Cards Exiled", "zone")
        self._print_line(f"   By Me: {self.game_state.opponent_cards_exiled_by_player}")
        self._print_line(f"   By Opponent: {self.game_state.player_cards_exiled_by_opponent}")
        self._print_match_stats_section()

    def _format_type_breakdown(self, events: List["CardEvent"]) -> str:
        """Return a 'By type: N Lands, M Creatures, ...' string for a list of card events (non-zero only)."""
        order = [
            "Land",
            "Creature",
            "Instant",
            "Sorcery",
            "Enchantment",
            "Artifact",
            "Planeswalker",
            "Other",
        ]
        plurals = {
            "Land": "Lands",
            "Creature": "Creatures",
            "Instant": "Instants",
            "Sorcery": "Sorceries",
            "Enchantment": "Enchantments",
            "Artifact": "Artifacts",
            "Planeswalker": "Planeswalkers",
            "Other": "Other",
        }
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
                f"      Biggest Creature: [{top_creature['name']}] "
                f"reached {top_creature['power']}/{top_creature['toughness']}"
            )

    def _print_game_summary(self):
        """Print summary when game ends."""
        self._try_resolve_winner_from_log_tail()
        self._finalize_turn_timing()
        duration_display = self._game_duration_display()
        outcome, reason = self._resolve_game_outcome()
        self._record_session_outcome(outcome)
        self._print_result_summary(outcome, reason, duration_display)
        untracked_reason = self._untracked_mode_reason()
        if untracked_reason:
            self._print_line(
                f"🚫 Not tracked: {untracked_reason}. Jump In, Midweek Magic, Momir, "
                "Welcome Deck Duels, and games vs Sparky are excluded from your saved stats."
            )
        self._print_best_of_three_status()
        self._print_starting_hand_summary()
        self._print_cards_played_summary()
        self._print_exile_and_match_stats_summary()
        self._print_card_collection_summary(
            self.player_cards, heading="Your Cards", seat_id=self.game_state.player_seat_id
        )
        self._print_card_collection_summary(
            self.opponent_cards,
            heading="Opponent's Cards",
            seat_id=self.game_state.opponent_seat_id,
        )

        self._print_line("\n" + "=" * 75)
        self._print_line("Ready for next game...\n")

        self._persist_game_analytics(outcome, reason)

        if self._bo3_match_continues():
            # The Bo3 match is undecided, so the next game belongs to THIS
            # match. Freeze the completed game's state (in_match=True,
            # match_complete=True) instead of resetting: the next game's start
            # may arrive minutes later in a different read batch, and the
            # completed-match branch of _check_game_start needs the format,
            # opponent, and Arena match UUID intact to carry them over.
            self._require_explicit_game_start = True
            return

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
        self._print_line(f"   {self._session_first_split_line()}")
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
