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
        self.active_player = None  # Seat ID of active player
        self.phase = ""
        self.step = ""
        self.in_match = False
        self.match_complete = False
        self.seen_instance_ids: Set[int] = set()  # Track cards we've already announced
        self.last_turn_announced = 0

        # Auto-detected seat IDs
        self.player_seat_id: Optional[int] = None
        self.opponent_seat_id: Optional[int] = None

        # Your account ID for matching against reservedPlayers
        self.my_user_id: Optional[str] = None

        # Starting hand tracking
        self.starting_hand: List[str] = []
        self.mulligan_count = 0
        self.initial_hand_size = 7

        # Combat tracking
        self.attackers: List[int] = []  # Instance IDs of attacking creatures
        self.blockers: Dict[int, int] = {}  # blocker_id: attacker_id

        # Game timing
        self.game_start_time: Optional[datetime] = None
        self.game_end_time: Optional[datetime] = None

        # Match result
        self.winner_seat: Optional[int] = None

    def reset(self):
        """Reset the game state for a new match."""
        player_seat = self.player_seat_id
        opponent_seat = self.opponent_seat_id
        self.__init__()
        # Preserve seat IDs across matches
        self.player_seat_id = player_seat
        self.opponent_seat_id = opponent_seat


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

        # Try to detect player seat from recent log history
        print("🔍 Detecting player seat ID...")
        self._detect_player_seat_from_log()

        if self.game_state.player_seat_id:
            print(f"✓ You are Seat {self.game_state.player_seat_id}")
        else:
            print("⚠ Could not detect seat ID yet - will detect during next match")

        print("\n   Waiting for game events...")
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

    def _reset_game_state(self):
        """Reset game state for a new game."""
        self.game_state = GameState()
        self.player_cards = []
        self.opponent_cards = []

    def _detect_player_seat_from_log(self):
        """Scan recent log history to detect player seat ID.

        Strategy: YOUR client always lists YOU first in reservedPlayers.
        Find the most recent reservedPlayers entry and use the first player as YOU.
        """
        try:
            with open(self.parser.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            # Find the MOST RECENT reservedPlayers entry
            # YOUR client lists YOU first, so first player = YOU
            for line in reversed(lines):
                if "reservedplayers" in line.lower():
                    json_data = self.parser.parse_json_from_line(line)
                    if json_data:
                        reserved = self._find_nested(json_data, "reservedPlayers")
                        if reserved and isinstance(reserved, list) and len(reserved) >= 2:
                            # First player in the list is YOU
                            my_player = reserved[0]
                            seat_id = my_player.get("systemSeatId")
                            if seat_id:
                                self.game_state.player_seat_id = seat_id
                                self.game_state.opponent_seat_id = 2 if seat_id == 1 else 1
                                self.game_state.my_user_id = my_player.get("userId")
                                print(f"Detected: You are Seat {seat_id}")
                                return

        except Exception as e:
            print(f"Warning: Could not scan log for seat detection: {e}")

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

    def _process_new_events(self):
        """Process new events from the log file."""
        for line in self.parser.read_new_lines():
            self._process_line(line)

    def _process_line(self, line: str):
        """Process a single line from the log file.

        Args:
            line: A line from the MTGA log file.
        """
        # Try to detect player seat if not yet detected
        if self.game_state.player_seat_id is None:
            self._try_detect_player_seat(line)

        # Check for game start
        if not self.game_state.in_match:
            self._check_game_start(line)

        # Check for game end
        if self.game_state.in_match and not self.game_state.match_complete:
            self._check_game_end(line)

        # Look for card-related events
        event = self.parser.extract_card_events(line)
        if event:
            self._handle_event(event)

    def _try_detect_player_seat(self, line: str):
        """Try to detect which seat ID belongs to the player.

        YOUR client always lists YOU first in reservedPlayers.
        When we see a new reservedPlayers, it means a new game started.

        Args:
            line: A line from the MTGA log file.
        """
        line_lower = line.lower()

        # Look for reservedPlayers in match config - this indicates a new game
        if "reservedplayers" in line_lower:
            json_data = self.parser.parse_json_from_line(line)
            if json_data:
                reserved = self._find_nested(json_data, "reservedPlayers")
                if reserved and isinstance(reserved, list) and len(reserved) >= 2:
                    # First player in the list is always YOU
                    my_player = reserved[0]
                    seat_id = my_player.get("systemSeatId")
                    if seat_id:
                        # Check if this is a NEW game (different seat or first detection)
                        old_seat = self.game_state.player_seat_id
                        new_user_id = my_player.get("userId")

                        # Reset game state for new game
                        if old_seat != seat_id or self.game_state.my_user_id != new_user_id:
                            self._reset_game_state()

                        self.game_state.player_seat_id = seat_id
                        self.game_state.opponent_seat_id = 2 if seat_id == 1 else 1
                        self.game_state.my_user_id = new_user_id
                        print(f"Detected: You are Seat {seat_id}")

    def _check_game_start(self, line: str):
        """Check if a game is starting."""
        # Look for game start indicators - mulligan phase means game is starting
        line_lower = line.lower()
        if "mulligantype" in line_lower or ("mulligan" in line_lower and "gretolient" in line_lower):
            if not self.game_state.in_match:
                self.game_state.game_start_time = datetime.now()
                self.game_state.in_match = True
                print("\n" + "="*70)
                print("🎮 GAME STARTED")
                print("="*70 + "\n")

        # Check for opening hand
        event = self.parser.extract_card_events(line)
        if event and event.get("type") == "game_state":
            data = event.get("data", {})

            # Detect game start from turnInfo (turn 1 means game started)
            if "turnInfo" in data and not self.game_state.in_match:
                turn_info = data["turnInfo"]
                turn_num = turn_info.get("turnNumber", 0)
                if turn_num >= 1:
                    self.game_state.game_start_time = datetime.now()
                    self.game_state.in_match = True
                    print("\n" + "="*70)
                    print("🎮 GAME STARTED")
                    print("="*70 + "\n")

            # Look for opening hand
            if "zones" in data:
                for zone in data["zones"]:
                    if zone.get("type") == "ZoneType_Hand":
                        owner_seat = zone.get("ownerSeatId")
                        if owner_seat == self.game_state.player_seat_id:
                            # This is your hand
                            obj_ids = zone.get("objectInstanceIds", [])
                            if obj_ids and not self.game_state.starting_hand:
                                # Get card names
                                game_objects = data.get("gameObjects", [])
                                hand_cards = []
                                for obj in game_objects:
                                    if obj.get("instanceId") in obj_ids:
                                        grp_id = obj.get("grpId")
                                        if grp_id:
                                            card_name = self.card_db.get_card_name(grp_id)
                                            hand_cards.append(card_name)

                                if hand_cards and len(hand_cards) <= 7:
                                    self.game_state.starting_hand = hand_cards
                                    self.game_state.initial_hand_size = len(hand_cards)

                                    if len(hand_cards) < 7:
                                        self.game_state.mulligan_count = 7 - len(hand_cards)
                                        print(f"🔄 Mulligan to {len(hand_cards)} (mulligans: {self.game_state.mulligan_count})")

                                    print(f"\n🎴 Your Starting Hand ({len(hand_cards)} cards):")
                                    for card in hand_cards:
                                        print(f"   • {card}")
                                    print()

    def _check_game_end(self, line: str):
        """Check if the game has ended."""
        # Look for game result indicators
        if "gamecompletedtype" in line.lower() or "matchcompleted" in line.lower() or "finalresults" in line.lower():
            json_data = self.parser.parse_json_from_line(line)
            if json_data and not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()

                # Try to determine winner
                if "winningteamid" in str(json_data).lower():
                    # Parse winner from the data
                    pass

                # Print summary
                self._print_game_summary()

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

                if life is not None and seat_id is not None:
                    if seat_id == self.game_state.player_seat_id:
                        old_life = self.game_state.player_life
                        if life != old_life:
                            diff = life - old_life
                            self.game_state.player_life = life
                            # Announce life changes once game has started
                            if self.game_state.in_match:
                                if diff > 0:
                                    print(f"💚 You gained {diff} life (now {life})")
                                elif diff < 0:
                                    print(f"💔 You lost {-diff} life (now {life})")
                    elif seat_id == self.game_state.opponent_seat_id:
                        old_life = self.game_state.opponent_life
                        if life != old_life:
                            diff = life - old_life
                            self.game_state.opponent_life = life
                            # Announce life changes once game has started
                            if self.game_state.in_match:
                                if diff > 0:
                                    print(f"   Opponent gained {diff} life (now {life})")
                                elif diff < 0:
                                    print(f"   Opponent lost {-diff} life (now {life})")

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
                    player_name = "YOUR" if active_player == self.game_state.player_seat_id else "OPPONENT'S"
                    print(f"\n{'='*70}")
                    print(f"⚔️  Turn {turn_num} - {player_name} TURN")
                    print(f"   Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
                    print(f"{'='*70}\n")

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
        zone_src = None
        zone_dest = None
        target_id = None

        for detail in details:
            key = detail.get("key", "")
            if key == "category":
                category = detail.get("valueString", [None])[0]
            elif key == "zone_src":
                zone_src = detail.get("valueInt32", [None])[0]
            elif key == "zone_dest":
                zone_dest = detail.get("valueInt32", [None])[0]
            elif key == "target" or key == "target_id":
                target_id = detail.get("valueInt32", [None])[0]

        # Handle combat-specific annotations
        if "AnnotationType_AttackerDeclared" in ann_type:
            self._handle_attacker_declared(affected_ids, game_objects)
            return
        elif "AnnotationType_BlockerDeclared" in ann_type:
            self._handle_blocker_declared(affected_ids, annotation, game_objects)
            return
        elif "AnnotationType_Damage" in ann_type or "AnnotationType_DamageDealt" in ann_type:
            self._handle_damage(affected_ids, annotation, game_objects)
            return

        # Only process if we have affected cards
        if not affected_ids:
            return

        instance_id = affected_ids[0]

        # Find the card object for this instance
        card_obj = None
        target_obj = None
        for obj in game_objects:
            if obj.get("instanceId") == instance_id:
                card_obj = obj
            if target_id and obj.get("instanceId") == target_id:
                target_obj = obj

        # Handle different annotation types
        if "AnnotationType_ZoneTransfer" in ann_type:
            # Casting spells and playing lands
            if category in ["CastSpell", "PlayLand"] and instance_id not in self.game_state.seen_instance_ids:
                self.game_state.seen_instance_ids.add(instance_id)
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                    player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    player_symbol = ">" if owner_seat == self.game_state.player_seat_id else " "

                    # Get card type info
                    card_types = card_obj.get("cardTypes", [])
                    type_str = self._format_card_type(card_types)

                    # Format output based on card type
                    target_str = ""
                    if target_obj:
                        target_grp_id = target_obj.get("grpId")
                        target_name = self.card_db.get_card_name(target_grp_id) if target_grp_id else "Unknown"
                        target_owner_seat = target_obj.get("ownerSeatId")
                        target_owner = "your" if target_owner_seat == self.game_state.player_seat_id else "opponent's"
                        target_str = f" targeting {target_name} ({target_owner})"

                    # Use appropriate verb based on card type
                    if category == "PlayLand":
                        print(f"{player_symbol} {player:8} played {card_name} ({type_str})")
                    elif "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        print(f"{player_symbol} {player:8} cast {card_name} ({type_str} {power}/{toughness}){target_str}")
                    else:
                        print(f"{player_symbol} {player:8} cast {card_name} ({type_str}){target_str}")

                    # Track the event
                    event = CardEvent(card_name, player.lower())
                    if owner_seat == self.game_state.player_seat_id:
                        self.player_cards.append(event)
                    else:
                        self.opponent_cards.append(event)

            # Destruction and removal effects
            elif category in ["Destroy", "Exile", "Sacrifice", "Discard"]:
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                    # Determine who owned the destroyed card
                    owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"

                    # Choose appropriate icon
                    if category == "Destroy":
                        icon = "💥"
                        action = "destroyed"
                    elif category == "Exile":
                        icon = "🚫"
                        action = "exiled"
                    elif category == "Sacrifice":
                        icon = "⚰️"
                        action = "sacrificed"
                    elif category == "Discard":
                        icon = "🗑️"
                        action = "discarded"
                    else:
                        icon = "💥"
                        action = category.lower()

                    print(f"{icon} {card_name} ({owner}) was {action}")

            # Counter spells
            elif category == "Countered":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    print(f"🚫 {card_name} ({owner}) was countered")

            # Draw cards
            elif category == "Draw":
                if card_obj:
                    owner_seat = card_obj.get("ownerSeatId")
                    if owner_seat == self.game_state.player_seat_id:
                        print(f"📥 You drew a card")
                    else:
                        print(f"   Opponent drew a card")

            # Mill effects
            elif category == "Mill":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    owner = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    print(f"🌊 {owner} milled {card_name}")

        # Handle resolution annotations
        elif "AnnotationType_ResolutionStart" in ann_type:
            # This tracks when spells resolve - useful for seeing instants resolve
            pass  # Can be used for more detailed instant tracking

        elif "AnnotationType_Scry" in ann_type:
            # Scry events - show when players scry
            if affected_ids and card_obj:
                owner_seat = card_obj.get("ownerSeatId")
                player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                print(f"🔮 {player} scried")

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

    def _handle_attacker_declared(self, affected_ids: List[int], game_objects: List[Dict[str, Any]]):
        """Handle attacker declarations."""
        for instance_id in affected_ids:
            if instance_id not in self.game_state.attackers:
                self.game_state.attackers.append(instance_id)

                # Find the attacker
                for obj in game_objects:
                    if obj.get("instanceId") == instance_id:
                        grp_id = obj.get("grpId")
                        owner_seat = obj.get("ownerSeatId")
                        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                        power = obj.get("power", {}).get("value", "?")
                        toughness = obj.get("toughness", {}).get("value", "?")

                        player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                        player_symbol = "⚔️" if owner_seat == self.game_state.player_seat_id else "🗡️"

                        print(f"{player_symbol} {player:8} attacking with {card_name} ({power}/{toughness})")
                        break

    def _handle_blocker_declared(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle blocker declarations."""
        if not affected_ids:
            return

        blocker_id = affected_ids[0]

        # Try to find which attacker is being blocked
        attacker_id = None
        details = annotation.get("details", [])
        for detail in details:
            if detail.get("key") == "attacker_id" or detail.get("key") == "target":
                attacker_id = detail.get("valueInt32", [None])[0]
                break

        # Find blocker and attacker names
        blocker_name = "Unknown"
        blocker_owner_seat = None
        blocker_pt = "?/?"
        attacker_name = "Unknown"
        attacker_owner_seat = None

        for obj in game_objects:
            if obj.get("instanceId") == blocker_id:
                grp_id = obj.get("grpId")
                blocker_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                blocker_owner_seat = obj.get("ownerSeatId")
                power = obj.get("power", {}).get("value", "?")
                toughness = obj.get("toughness", {}).get("value", "?")
                blocker_pt = f"{power}/{toughness}"
            elif attacker_id and obj.get("instanceId") == attacker_id:
                grp_id = obj.get("grpId")
                attacker_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                attacker_owner_seat = obj.get("ownerSeatId")

        if blocker_owner_seat is not None:
            player = "You" if blocker_owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "🛡️"

            if attacker_name != "Unknown":
                print(f"{player_symbol} {player:8} blocking {attacker_name} with {blocker_name} ({blocker_pt})")
            else:
                print(f"{player_symbol} {player:8} blocking with {blocker_name} ({blocker_pt})")

            if attacker_id:
                self.game_state.blockers[blocker_id] = attacker_id

    def _handle_damage(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle damage events."""
        # Extract damage amount
        details = annotation.get("details", [])
        damage_amount = None
        for detail in details:
            if detail.get("key") == "damage" or detail.get("key") == "amount":
                damage_amount = detail.get("valueInt32", [None])[0]
                break

        if damage_amount and affected_ids:
            for instance_id in affected_ids:
                for obj in game_objects:
                    if obj.get("instanceId") == instance_id:
                        grp_id = obj.get("grpId")
                        owner_seat = obj.get("ownerSeatId")
                        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                        owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                        print(f"💢 {card_name} ({owner}) took {damage_amount} damage")
                        break

    def _print_game_summary(self):
        """Print summary when game ends."""
        print("\n" + "="*70)
        print("🏁 GAME ENDED")
        print("="*70)

        # Calculate game time
        if self.game_state.game_start_time and self.game_state.game_end_time:
            duration = self.game_state.game_end_time - self.game_state.game_start_time
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            print(f"\n⏱️  Game Duration: {minutes}m {seconds}s")

        # Winner
        if self.game_state.player_life <= 0:
            print(f"💀 You lost (0 life)")
        elif self.game_state.opponent_life <= 0:
            print(f"🎉 You won! (Opponent at 0 life)")
        else:
            print(f"\n   Final Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")

        # Starting hand
        if self.game_state.starting_hand:
            print(f"\n🎴 Starting Hand ({self.game_state.initial_hand_size} cards):")
            if self.game_state.mulligan_count > 0:
                print(f"   (After {self.game_state.mulligan_count} mulligan(s))")
            for card in self.game_state.starting_hand:
                print(f"   • {card}")

        # Cards played
        print(f"\n📊 Cards Played:")
        print(f"   Your cards: {len(self.player_cards)}")
        print(f"   Opponent cards: {len(self.opponent_cards)}")

        if self.player_cards:
            print(f"\n   🎯 Your Cards:")
            card_counts = {}
            for event in self.player_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items()):
                if count > 1:
                    print(f"      • {card_name} x{count}")
                else:
                    print(f"      • {card_name}")

        if self.opponent_cards:
            print(f"\n   👤 Opponent's Cards:")
            card_counts = {}
            for event in self.opponent_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items()):
                if count > 1:
                    print(f"      • {card_name} x{count}")
                else:
                    print(f"      • {card_name}")

        print("\n" + "="*70)
        print("Ready for next game...\n")

        # Reset game state for next game
        self.game_state.reset()

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
