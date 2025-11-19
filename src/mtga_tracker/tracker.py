"""Card tracking module.

Tracks cards played by the player and opponents.
"""

import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from .log_parser import MTGALogParser
from .card_database import CardDatabase


class GameState:
    """Tracks the current game state."""

    def __init__(self):
        self.player_life = 20
        self.opponent_life = 20
        self.turn_number = 0
        self.active_player = None  # 1 for you, 2 for opponent
        self.phase = ""
        self.step = ""
        self.in_match = False
        self.seen_instance_ids: Set[int] = set()  # Track cards we've already announced
        self.last_turn_announced = 0

    def reset(self):
        """Reset the game state for a new match."""
        self.__init__()


class CardEvent:
    """Represents a card play event."""

    def __init__(self, card_name: str, player: str, timestamp: Optional[datetime] = None):
        """Initialize a card event.

        Args:
            card_name: Name of the card played.
            player: 'player' or 'opponent'.
            timestamp: When the card was played.
        """
        self.card_name = card_name
        self.player = player
        self.timestamp = timestamp or datetime.now()

    def __repr__(self) -> str:
        return f"CardEvent(card={self.card_name}, player={self.player}, time={self.timestamp})"


class CardTracker:
    """Tracks cards played during MTGA matches."""

    def __init__(self, log_parser: Optional[MTGALogParser] = None,
                 card_db: Optional[CardDatabase] = None):
        """Initialize the card tracker.

        Args:
            log_parser: Optional MTGALogParser instance. If not provided, creates one.
            card_db: Optional CardDatabase instance. If not provided, creates one.
        """
        self.parser = log_parser or MTGALogParser()
        self.card_db = card_db or CardDatabase()
        self.game_state = GameState()
        self.player_cards: List[CardEvent] = []
        self.opponent_cards: List[CardEvent] = []
        self.running = False

    def start(self):
        """Start tracking cards."""
        print("\n" + "=" * 70)
        print("🎮 MTGA Card Tracker - Real-time Match Analyzer")
        print("=" * 70)
        print(f"📂 Monitoring: {self.parser.log_path}")
        print(f"💾 Card cache: {len(self.card_db.cache)} cards loaded")
        print("\n   Waiting for match to start...")
        print("   Play a game in MTGA to see cards tracked in real-time!")
        print("\n   Press Ctrl+C to stop")
        print("=" * 70 + "\n")

        # Start from current end of file
        self.parser.reset_position()
        self.running = True

        try:
            while self.running:
                self._process_new_events()
                time.sleep(0.5)  # Check for new events twice per second
        except KeyboardInterrupt:
            print("\n" + "=" * 70)
            print("🛑 Stopping tracker...")
            self._print_summary()
            print("=" * 70)

    def stop(self):
        """Stop tracking cards."""
        self.running = False

    def _process_new_events(self):
        """Process new events from the log file."""
        for line in self.parser.read_new_lines():
            self._process_line(line)

    def _process_line(self, line: str):
        """Process a single line from the log file.

        Args:
            line: A line from the MTGA log file.
        """
        # Look for card-related events
        event = self.parser.extract_card_events(line)
        if event:
            self._handle_event(event)


    def _handle_event(self, event: Dict[str, Any]):
        """Handle a card event.

        Args:
            event: Event data extracted from the log.
        """
        event_type = event.get("type")
        event_data = event.get("data", {})

        if event_type != "game_state":
            return

        # Update game state first
        self._update_game_state(event_data)

        # Process important events only
        self._process_game_events(event_data)

    def _update_game_state(self, data: Dict[str, Any]):
        """Update the tracked game state from event data."""
        # Update life totals
        if "players" in data:
            for player in data["players"]:
                seat_id = player.get("systemSeatNumber")
                life = player.get("lifeTotal")

                if life is not None:
                    if seat_id == 1:
                        old_life = self.game_state.player_life
                        self.game_state.player_life = life
                        if old_life != life and self.game_state.in_match:
                            diff = life - old_life
                            if diff > 0:
                                print(f"💚 You gained {diff} life ({life})")
                            elif diff < 0:
                                print(f"💔 You lost {-diff} life ({life})")
                    elif seat_id == 2:
                        old_life = self.game_state.opponent_life
                        self.game_state.opponent_life = life
                        if old_life != life and self.game_state.in_match:
                            diff = life - old_life
                            if diff > 0:
                                print(f"   Opponent gained {diff} life ({life})")
                            elif diff < 0:
                                print(f"   Opponent lost {-diff} life ({life})")

        # Update turn info
        if "turnInfo" in data:
            turn_info = data["turnInfo"]
            turn_num = turn_info.get("turnNumber")
            active_player = turn_info.get("activePlayer")
            phase = turn_info.get("phase", "")
            step = turn_info.get("step", "")

            # Detect new turn
            if turn_num and turn_num != self.game_state.turn_number:
                self.game_state.turn_number = turn_num
                self.game_state.active_player = active_player
                self.game_state.phase = phase
                self.game_state.step = step

                # Announce turn change
                if turn_num > self.game_state.last_turn_announced:
                    self.game_state.last_turn_announced = turn_num
                    player_name = "YOUR" if active_player == 1 else "OPPONENT'S"
                    print(f"\n{'='*70}")
                    print(f"⚔️  Turn {turn_num} - {player_name} TURN")
                    print(f"   Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
                    print(f"{'='*70}\n")

                    if not self.game_state.in_match:
                        self.game_state.in_match = True

    def _process_game_events(self, data: Dict[str, Any]):
        """Process and display important game events."""
        # Process annotations for high-level events
        if "annotations" in data:
            for annotation in data["annotations"]:
                self._process_annotation(annotation, data.get("gameObjects", []))

    def _process_annotation(self, annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Process a single annotation (game event)."""
        ann_type = annotation.get("type", [])
        affected_ids = annotation.get("affectedIds", [])
        details = annotation.get("details", [])

        # Extract category and other details
        category = None
        for detail in details:
            if detail.get("key") == "category":
                category = detail.get("valueString", [None])[0]

        # Only process if we haven't seen this card instance before
        if not affected_ids:
            return

        instance_id = affected_ids[0]

        # Find the card object for this instance
        card_obj = None
        for obj in game_objects:
            if obj.get("instanceId") == instance_id:
                card_obj = obj
                break

        # Handle different annotation types
        if "AnnotationType_ZoneTransfer" in ann_type:
            if category == "CastSpell" and instance_id not in self.game_state.seen_instance_ids:
                self.game_state.seen_instance_ids.add(instance_id)
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                    player = "You" if owner_seat == 1 else "Opponent"
                    player_symbol = "🎯" if owner_seat == 1 else "👤"

                    # Get card type info
                    card_types = card_obj.get("cardTypes", [])
                    type_str = self._format_card_type(card_types)

                    # Format output based on card type
                    if "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        print(f"{player_symbol} {player:8} cast {card_name} ({type_str} {power}/{toughness})")
                    else:
                        print(f"{player_symbol} {player:8} cast {card_name} ({type_str})")

                    # Track the event
                    event = CardEvent(card_name, player.lower())
                    if owner_seat == 1:
                        self.player_cards.append(event)
                    else:
                        self.opponent_cards.append(event)

            elif category == "Destroy":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    print(f"💥 {card_name} was destroyed")

            elif category == "Damage":
                # Track damage events
                pass  # Could be implemented for more detailed tracking

        elif "AnnotationType_Scry" in ann_type:
            # Scry events
            pass  # Could show scry information

    def _format_card_type(self, card_types: List[str]) -> str:
        """Format card types for display."""
        if not card_types:
            return "Card"

        # Clean up and prioritize card types
        types = [t.replace("CardType_", "") for t in card_types]

        # Show main types
        main_types = []
        for t in ["Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Land"]:
            if t in types:
                main_types.append(t)

        return ", ".join(main_types) if main_types else "Card"

    def _print_summary(self):
        """Print a summary of tracked cards."""
        print()
        print("📊 Session Summary")
        print("=" * 70)

        if not self.game_state.in_match and not self.player_cards:
            print("   No matches tracked this session.")
            print("   Make sure to start the tracker before playing a game!")
            return

        print(f"   Final Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
        print(f"   Turns Played: {self.game_state.turn_number}")
        print(f"   Your cards played: {len(self.player_cards)}")
        print(f"   Opponent cards played: {len(self.opponent_cards)}")

        if self.player_cards:
            print(f"\n   🎯 Your Cards This Game:")
            # Count duplicates
            card_counts = {}
            for event in self.player_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items()):
                if count > 1:
                    print(f"      • {card_name} x{count}")
                else:
                    print(f"      • {card_name}")

        if self.opponent_cards:
            print(f"\n   👤 Opponent's Cards This Game:")
            # Count duplicates
            card_counts = {}
            for event in self.opponent_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items()):
                if count > 1:
                    print(f"      • {card_name} x{count}")
                else:
                    print(f"      • {card_name}")

    def get_player_cards(self) -> List[CardEvent]:
        """Get list of cards played by the player."""
        return self.player_cards.copy()

    def get_opponent_cards(self) -> List[CardEvent]:
        """Get list of cards played by opponents."""
        return self.opponent_cards.copy()

    def clear_history(self):
        """Clear card history."""
        self.player_cards.clear()
        self.opponent_cards.clear()
