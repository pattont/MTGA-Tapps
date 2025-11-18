"""Card tracking module.

Tracks cards played by the player and opponents.
"""

import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from .log_parser import MTGALogParser


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

    def __init__(self, log_parser: Optional[MTGALogParser] = None):
        """Initialize the card tracker.

        Args:
            log_parser: Optional MTGALogParser instance. If not provided, creates one.
        """
        self.parser = log_parser or MTGALogParser()
        self.player_cards: List[CardEvent] = []
        self.opponent_cards: List[CardEvent] = []
        self.running = False

    def start(self):
        """Start tracking cards."""
        print("=" * 70)
        print("MTGA Card Tracker")
        print("=" * 70)
        print(f"Monitoring log file: {self.parser.log_path}")
        print("Starting from current position (new events only)...")
        print("Press Ctrl+C to stop")
        print("=" * 70)
        print()

        # Start from current end of file
        self.parser.reset_position()
        self.running = True

        try:
            while self.running:
                self._process_new_events()
                time.sleep(1)  # Check for new events every second
        except KeyboardInterrupt:
            print("\n" + "=" * 70)
            print("Stopping tracker...")
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

        # Also look for simpler card play patterns
        # This is a basic implementation - MTGA log parsing can be quite complex
        if "CardInstance" in line or "cast" in line.lower():
            # Try to extract card name
            card_info = self._extract_card_info(line)
            if card_info:
                self._log_card_play(card_info)

    def _extract_card_info(self, line: str) -> Optional[Dict[str, Any]]:
        """Extract card information from a log line.

        This is a simplified extraction. MTGA logs are complex and this
        may need refinement based on actual log format.

        Args:
            line: A line from the MTGA log file.

        Returns:
            Dictionary with card info or None.
        """
        # Parse JSON if present
        data = self.parser.parse_json_from_line(line)
        if not data:
            return None

        card_info = {}

        # Look for card instance data
        if "grpId" in data:  # Card ID
            card_info["card_id"] = data["grpId"]

        # Look for zone transfers (when cards move zones, like hand to battlefield)
        if "zoneId" in data or "destinationZoneId" in data:
            card_info["zone_change"] = True

        # Try to determine if it's player or opponent
        # This is simplified - actual determination requires tracking seat IDs
        if "ownerSeatId" in data or "controllerSeatId" in data:
            seat_id = data.get("ownerSeatId") or data.get("controllerSeatId")
            card_info["seat_id"] = seat_id

        return card_info if card_info else None

    def _handle_event(self, event: Dict[str, Any]):
        """Handle a card event.

        Args:
            event: Event data extracted from the log.
        """
        # This is a placeholder for more sophisticated event handling
        # You would parse the event data to extract card names, players, etc.
        if event.get("type") == "zone_change":
            # Handle zone changes (cards moving between zones)
            pass

    def _log_card_play(self, card_info: Dict[str, Any]):
        """Log a card play event to console.

        Args:
            card_info: Information about the card played.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Determine player (simplified - would need proper seat tracking)
        player = "Player" if card_info.get("seat_id", 1) == 1 else "Opponent"

        # Get card ID (would need card database to convert to name)
        card_id = card_info.get("card_id", "Unknown")

        print(f"[{timestamp}] {player} played card ID: {card_id}")

        # Create event
        event = CardEvent(
            card_name=f"Card_{card_id}",
            player=player.lower(),
        )

        # Store event
        if player == "Player":
            self.player_cards.append(event)
        else:
            self.opponent_cards.append(event)

    def _print_summary(self):
        """Print a summary of tracked cards."""
        print()
        print("Session Summary:")
        print(f"  Your cards played: {len(self.player_cards)}")
        print(f"  Opponent cards played: {len(self.opponent_cards)}")

        if self.player_cards:
            print("\nYour cards:")
            for event in self.player_cards[-10:]:  # Show last 10
                print(f"  - {event.card_name} at {event.timestamp.strftime('%H:%M:%S')}")

        if self.opponent_cards:
            print("\nOpponent cards:")
            for event in self.opponent_cards[-10:]:  # Show last 10
                print(f"  - {event.card_name} at {event.timestamp.strftime('%H:%M:%S')}")

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
