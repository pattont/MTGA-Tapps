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
        self.combat_phase_active: bool = False  # Track if we're in combat phase
        self.current_combat_attackers: Dict[int, Dict] = {}  # instance_id -> {card_name, power, toughness, target}
        self.combat_damage_events: List[Dict] = []  # Track combat damage for summary

        # Game timing
        self.game_start_time: Optional[datetime] = None
        self.game_end_time: Optional[datetime] = None

        # Match result
        self.winner_seat: Optional[int] = None
        
        # Who went first (seat ID of player who went first)
        self.first_player_seat: Optional[int] = None
        
        # Match type tracking
        self.match_type: str = "best_of_1"  # "best_of_1" or "best_of_3"
        self.game_number: int = 1  # Current game number in the match (1, 2, or 3)

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
        self.match_games: List[Dict] = []  # Track games in the match for summary

    def start(self):
        """Start tracking cards."""
        print("\n" + "=" * 70)
        print("🎮 MTGA Card Tracker - Real-time Match Analyzer")
        print("=" * 70)
        print(f"📂 Monitoring: {self.parser.log_path}")
        local_cache_count = len(self.card_db.cache)
        mtgjson_count = len(self.card_db.mtgjson_cache) if hasattr(self.card_db, 'mtgjson_cache') else 0
        print(f"💾 Local cache: {local_cache_count} cards | MTGJSON DB: {mtgjson_count} cards")

        # Player seat will be detected automatically when a game starts
        print("⏳ Waiting for game to start - seat will be detected automatically")

        print("\n   Waiting for game events...")
        print("   Play a game in MTGA to see cards tracked in real-time!")
        print("\n   Press Ctrl+C to stop")
        print("=" * 70 + "\n")

        # Start from current end of file
        # #region agent log
        import json as json_module
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"K","location":"tracker.py:127","message":"Starting tracker loop","data":{"log_path":self.parser.log_path,"player_seat_id":self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        self.parser.reset_position()
        # #region agent log
        try:
            import os
            log_exists = os.path.exists(self.parser.log_path)
            log_size = os.path.getsize(self.parser.log_path) if log_exists else 0
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"L","location":"tracker.py:132","message":"After reset_position","data":{"log_path":self.parser.log_path,"log_exists":log_exists,"log_size":log_size,"last_position":self.parser.last_position},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
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
        # #region agent log
        import json as json_module
        line_count = 0
        # #endregion
        for line in self.parser.read_new_lines():
            # #region agent log
            line_count += 1
            if line_count <= 5:  # Log first 5 lines
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"tracker.py:198","message":"Reading log line","data":{"line_count":line_count,"line_preview":line[:100] if line else None,"log_path":self.parser.log_path},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
            # #endregion
            self._process_line(line)
        # #region agent log
        if line_count == 0:
            try:
                with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"tracker.py:207","message":"No new lines read","data":{"log_path":self.parser.log_path,"last_position":self.parser.last_position},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
        # #endregion

    def _process_line(self, line: str):
        """Process a single line from the log file.

        Args:
            line: A line from the MTGA log file.
        """
        # #region agent log
        import json as json_module
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"I","location":"tracker.py:222","message":"Processing line","data":{"line_length":len(line),"has_reservedplayers":"reservedplayers" in line.lower(),"has_gamestate":"gamestatemessage" in line.lower(),"player_seat_id":self.game_state.player_seat_id,"in_match":self.game_state.in_match},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
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
            # #region agent log
            try:
                with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"J","location":"tracker.py:241","message":"Event extracted","data":{"event_type":event.get("type") if event else None},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            self._handle_event(event)

    def _try_detect_player_seat(self, line: str):
        """Try to detect which seat ID belongs to the player.

        Uses hand visibility: YOUR hand has visible cards (grpId > 0), opponent's is hidden.
        Falls back to reservedPlayers method if hand visibility doesn't work.

        Args:
            line: A line from the MTGA log file.
        """
        # Try hand visibility detection first (more reliable)
        event = self.parser.extract_card_events(line)
        if event and event.get("type") == "game_state":
            data = event.get("data", {})
            zones = data.get("zones", [])
            game_objects = data.get("gameObjects", [])

            # Build instanceId -> grpId map for this game state
            instance_to_grp = {}
            for obj in game_objects:
                instance_id = obj.get("instanceId")
                grp_id = obj.get("grpId", 0)
                if instance_id and grp_id and grp_id > 0:
                    instance_to_grp[instance_id] = grp_id

            # Find hand zones
            hands = []
            for zone in zones:
                zone_type = zone.get("type", "")
                if "Hand" in zone_type:
                    owner_seat = zone.get("ownerSeatId")
                    obj_ids = zone.get("objectInstanceIds", [])

                    if obj_ids and owner_seat:
                        visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
                        hidden = len(obj_ids) - visible

                        hands.append({
                            'seat': owner_seat,
                            'visible': visible,
                            'hidden': hidden,
                            'total': len(obj_ids)
                        })
                        # #region agent log
                        import json as json_module
                        try:
                            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Q","location":"tracker.py:270","message":"Hand zone found","data":{"owner_seat":owner_seat,"total_cards":len(obj_ids),"visible":visible,"hidden":hidden,"instance_to_grp_size":len(instance_to_grp)},"timestamp":__import__('time').time()*1000})+'\n')
                        except: pass
                        # #endregion

            # If we have 2 hands with cards, determine player seat
            if len(hands) == 2 and hands[0]['total'] > 0 and hands[1]['total'] > 0:
                hand1, hand2 = hands
                # #region agent log
                import json as json_module
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Q","location":"tracker.py:285","message":"Evaluating 2 hands for seat detection","data":{"hand1_seat":hand1['seat'],"hand1_visible":hand1['visible'],"hand1_hidden":hand1['hidden'],"hand1_total":hand1['total'],"hand2_seat":hand2['seat'],"hand2_visible":hand2['visible'],"hand2_hidden":hand2['hidden'],"hand2_total":hand2['total']},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion

                # Determine which seat is the player
                your_seat = None
                detection_reason = None
                # Clear case: one hand all visible, other all hidden
                if hand1['visible'] > 0 and hand1['hidden'] == 0 and hand2['visible'] == 0:
                    your_seat = hand1['seat']
                    detection_reason = "hand1_all_visible_hand2_all_hidden"
                elif hand2['visible'] > 0 and hand2['hidden'] == 0 and hand1['visible'] == 0:
                    your_seat = hand2['seat']
                    detection_reason = "hand2_all_visible_hand1_all_hidden"
                # Compare visible counts (player's hand has more visible cards)
                elif hand1['visible'] > hand2['visible']:
                    your_seat = hand1['seat']
                    detection_reason = "hand1_more_visible"
                elif hand2['visible'] > hand1['visible']:
                    your_seat = hand2['seat']
                    detection_reason = "hand2_more_visible"

                if your_seat:
                    self.game_state.player_seat_id = your_seat
                    self.game_state.opponent_seat_id = 2 if your_seat == 1 else 1
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"tracker.py:310","message":"Player seat detected via hand visibility","data":{"player_seat_id":your_seat,"opponent_seat_id":self.game_state.opponent_seat_id,"hand1_seat":hand1['seat'],"hand1_visible":hand1['visible'],"hand1_hidden":hand1['hidden'],"hand2_seat":hand2['seat'],"hand2_visible":hand2['visible'],"hand2_hidden":hand2['hidden'],"detection_reason":detection_reason},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    print(f"Detected: You are Seat {your_seat} (hand visibility: {detection_reason})")
                    return
                else:
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Q","location":"tracker.py:320","message":"Could not determine seat from hand visibility","data":{"hand1_seat":hand1['seat'],"hand1_visible":hand1['visible'],"hand1_hidden":hand1['hidden'],"hand2_seat":hand2['seat'],"hand2_visible":hand2['visible'],"hand2_hidden":hand2['hidden']},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion

        # DO NOT use reservedPlayers - it's unreliable. Only use hand visibility.
        # If hand visibility doesn't work, we'll detect later when more game state is available.

    def _check_game_start(self, line: str):
        """Check if a game is starting."""
        # If we're already in a match but it's complete, reset for a new game
        if self.game_state.in_match and self.game_state.match_complete:
            # New game in a best-of-3 match - detect match type and increment game number
            if self.game_state.match_type == "best_of_1":
                # This is actually a best-of-3 match!
                self.game_state.match_type = "best_of_3"
                self.game_state.game_number = 2
            else:
                # Already detected as best-of-3, increment game number
                self.game_state.game_number += 1
            
            # Store previous game results
            self.match_games.append({
                "game_number": self.game_state.game_number - 1,
                "winner": self.game_state.winner_seat,
                "player_cards": self.player_cards.copy(),
                "opponent_cards": self.opponent_cards.copy(),
                "player_life": self.game_state.player_life,
                "opponent_life": self.game_state.opponent_life
            })
            
            # New game in a best-of-3 match - reset game state but keep seat IDs and match type
            print("\n" + "="*70)
            print(f"🔄 GAME {self.game_state.game_number} STARTING (Best-of-3 Match)")
            print("="*70 + "\n")
            # Reset game state but preserve match type, game number, and seat IDs
            player_seat = self.game_state.player_seat_id
            opponent_seat = self.game_state.opponent_seat_id
            match_type = self.game_state.match_type
            game_number = self.game_state.game_number
            self.game_state.reset()  # This preserves seat IDs
            self.game_state.match_type = match_type
            self.game_state.game_number = game_number
            self.player_cards = []
            self.opponent_cards = []
            
        # Only check if we're not already in a match
        if self.game_state.in_match:
            return
            
        line_lower = line.lower()
        
        # #region agent log
        import json as json_module
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"U","location":"tracker.py:365","message":"Checking game start","data":{"line_preview":line[:100],"in_match":self.game_state.in_match,"mulligan_found":"mulligantype" in line_lower or ("mulligan" in line_lower and "gretolient" in line_lower)},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # Look for game start indicators - mulligan phase means game is starting
        if "mulligantype" in line_lower or ("mulligan" in line_lower and "gretolient" in line_lower):
            self.game_state.game_start_time = datetime.now()
            self.game_state.in_match = True
            self.game_state.match_complete = False  # Reset match complete flag for new game
            # #region agent log
            try:
                with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"U","location":"tracker.py:375","message":"Game started via mulligan","data":{"reason":"mulligan","match_type":self.game_state.match_type,"game_number":self.game_state.game_number},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            match_type_display = "Best-of-3" if self.game_state.match_type == "best_of_3" else "Best-of-1"
            game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
            print("\n" + "="*70)
            print(f"🎮 GAME STARTED - {match_type_display}{game_num_display} (Mulligan Phase)")
            print("="*70 + "\n")
            return  # Don't process further - wait for turn info

        # Check for opening hand
        event = self.parser.extract_card_events(line)
        if event and event.get("type") == "game_state":
            data = event.get("data", {})

            # Detect game start from turnInfo (turn 1 means game started)
            if "turnInfo" in data:
                turn_info = data["turnInfo"]
                turn_num = turn_info.get("turnNumber", 0)
                if turn_num >= 1:
                    self.game_state.game_start_time = datetime.now()
                    self.game_state.in_match = True
                    self.game_state.match_complete = False  # Reset match complete flag for new game
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"U","location":"tracker.py:395","message":"Game started via turn 1","data":{"turn_num":turn_num,"match_type":self.game_state.match_type,"game_number":self.game_state.game_number},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    match_type_display = "Best-of-3" if self.game_state.match_type == "best_of_3" else "Best-of-1"
                    game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
                    print("\n" + "="*70)
                    print(f"🎮 GAME STARTED - {match_type_display}{game_num_display} (Turn 1)")
                    print("="*70 + "\n")
                    return  # Don't process further - wait for hand info

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
        if not self.game_state.in_match or self.game_state.match_complete:
            return  # Only check if we're in a match and it's not already complete
            
        line_lower = line.lower()
        
        # #region agent log
        import json as json_module
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:428","message":"Checking game end","data":{"line_preview":line[:150],"in_match":self.game_state.in_match,"match_complete":self.game_state.match_complete,"patterns_found":{"gamecompleted":any(x in line_lower for x in ["gamecompletedtype","matchcompleted","finalresults"]),"opponent_left":any(x in line_lower for x in ["opponentleft","concede","disconnect"]),"you_left":any(x in line_lower for x in ["playerleft","youleft","you left","i left"])}},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # Check for you leaving/conceding FIRST (you lose) - must check before opponent patterns
        # This prevents generic "concede" from matching when you concede
        if any(pattern in line_lower for pattern in [
            "playerleft", "youleft", "you left", "i left", 
            "i concede", "you concede", "conceded the match", 
            "quit the match", "defeat", "you were defeated",
            "clientmessagetype_concedereq",  # When you send concede request
            "you disconnected", "i disconnected", "player disconnected",
            "forfeit", "you forfeit", "i forfeit", "forfeited",  # Forfeit patterns
            "matchcompleted",  # Match completed (you lost)
            "state changed",  # Check for state changes
        ]):
            # Check if this is a state change indicating match completion
            if '"old":"matchcompleted"' in line_lower or '"old":"MatchCompleted"' in line:
                if not self.game_state.match_complete:
                    self.game_state.match_complete = True
                    self.game_state.game_end_time = datetime.now()
                    self.game_state.winner_seat = self.game_state.opponent_seat_id
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:456","message":"Match completed - you lost","data":{"winner_seat":self.game_state.winner_seat,"opponent_seat_id":self.game_state.opponent_seat_id,"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    print("\n" + "="*70)
                    print("💀 GAME FORFEITED - YOU LOST")
                    print("="*70)
                    self._print_game_summary()
                    return
            
            # Check for explicit forfeit/concede patterns
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self.game_state.winner_seat = self.game_state.opponent_seat_id
                # #region agent log
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:456","message":"You left/forfeited detected","data":{"winner_seat":self.game_state.winner_seat,"opponent_seat_id":self.game_state.opponent_seat_id,"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                print("\n" + "="*70)
                print("💀 GAME FORFEITED - YOU LOST")
                print("="*70)
                self._print_game_summary()
                return
        
        # Check for opponent leaving/conceding (you win) - only after checking player patterns
        # Use specific patterns to avoid matching when you concede
        if any(pattern in line_lower for pattern in [
            "opponentleft", "opponent concede", "opponent disconnected",
            "opponent left", "opponent quit"
        ]):
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self.game_state.winner_seat = self.game_state.player_seat_id
                # #region agent log
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:467","message":"Opponent left detected","data":{"winner_seat":self.game_state.winner_seat,"player_seat_id":self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                self._print_game_summary()
                return
        
        # Check for game completion messages (try to parse JSON)
        # Also check for MatchCompleted state changes
        if any(pattern in line_lower for pattern in [
            "gamecompletedtype", "matchcompleted", "finalresults",
            "matchendscene", "on sceneloaded for matchendscene"
        ]) or '"old":"matchcompleted"' in line_lower or '"old":"MatchCompleted"' in line:
            json_data = self.parser.parse_json_from_line(line)
            if json_data and not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()

                # Try to determine winner from JSON
                if "winningteamid" in str(json_data).lower():
                    # Parse winner from the data
                    pass
                
                # #region agent log
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:475","message":"Game completion detected","data":{"winner_seat":self.game_state.winner_seat,"json_keys":list(json_data.keys()) if isinstance(json_data, dict) else None,"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion

                self._print_game_summary()
                return
            
            # Handle MatchCompleted state change even without JSON
            if not self.game_state.match_complete and ('matchcompleted' in line_lower or 'MatchCompleted' in line):
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                # #region agent log
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:510","message":"MatchCompleted state detected","data":{"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                self._print_game_summary()
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
                                    print(f"💚 {'You':8} gained {diff} life (now {life})")
                                elif diff < 0:
                                    print(f"💔 {'You':8} lost {-diff} life (now {life})")
                    elif seat_id == self.game_state.opponent_seat_id:
                        old_life = self.game_state.opponent_life
                        if life != old_life:
                            diff = life - old_life
                            self.game_state.opponent_life = life
                            # Announce life changes once game has started
                            if self.game_state.in_match:
                                if diff > 0:
                                    print(f"💚 {'Opponent':8} gained {diff} life (now {life})")
                                elif diff < 0:
                                    print(f"💔 {'Opponent':8} lost {-diff} life (now {life})")

        # Update turn info
        if "turnInfo" in data:
            turn_info = data["turnInfo"]
            turn_num = turn_info.get("turnNumber")
            active_player = turn_info.get("activePlayer")
            phase = turn_info.get("phase", "")
            step = turn_info.get("step", "")
            # #region agent log
            import json as json_module
            try:
                with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"tracker.py:384","message":"TurnInfo received","data":{"turn_num":turn_num,"active_player":active_player,"player_seat_id":self.game_state.player_seat_id,"opponent_seat_id":self.game_state.opponent_seat_id,"current_turn":self.game_state.turn_number,"first_player_seat":self.game_state.first_player_seat},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion

            # Detect new turn - only announce if turn number increased AND active player changed
            # A turn only changes when the active player changes (not just when turn number increments)
            turn_changed = False
            if turn_num and turn_num > self.game_state.turn_number:
                # Verify that the active player actually changed (a real turn change)
                if active_player is not None and active_player != self.game_state.active_player:
                    turn_changed = True
                # Also allow if we don't have an active player yet (first turn)
                elif self.game_state.active_player is None:
                    turn_changed = True
            # Special case: Always announce turn 1 if we haven't announced it yet
            elif turn_num == 1 and self.game_state.last_turn_announced < 1:
                if active_player is not None:
                    turn_changed = True
            
            # Always update turn info (for display purposes), but only announce if it's a real turn change
            if turn_num is not None:
                self.game_state.turn_number = turn_num
            if active_player is not None:
                self.game_state.active_player = active_player
            if phase:
                self.game_state.phase = phase
            if step:
                self.game_state.step = step
            
            # Detect combat phase
            if phase and "Combat" in phase:
                if not self.game_state.combat_phase_active:
                    self.game_state.combat_phase_active = True
                    # Clear previous combat data
                    self.game_state.current_combat_attackers = {}
                    self.game_state.combat_damage_events = []
            else:
                # If we were in combat and now we're not, show combat summary
                if self.game_state.combat_phase_active:
                    self._display_combat_summary()
                    self.game_state.combat_phase_active = False
                    self.game_state.current_combat_attackers = {}
                    self.game_state.combat_damage_events = []
            
            if turn_changed:
                # #region agent log
                try:
                    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"V","location":"tracker.py:495","message":"New turn detected","data":{"old_turn":self.game_state.turn_number,"new_turn":turn_num,"old_active_player":self.game_state.active_player,"new_active_player":active_player,"player_seat_id":self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                
                # Detect who went first (on turn 1)
                if turn_num == 1 and self.game_state.first_player_seat is None and active_player is not None:
                    self.game_state.first_player_seat = active_player
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"tracker.py:510","message":"Turn 1 detected - storing first player","data":{"first_player_seat":active_player,"player_seat_id":self.game_state.player_seat_id,"player_went_first":active_player==self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion

                # Announce turn change
                # Always announce turn 1, or announce if turn number increased
                if turn_num == 1 and self.game_state.last_turn_announced < 1:
                    # First turn - always announce
                    self.game_state.last_turn_announced = turn_num
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"tracker.py:518","message":"Announcing turn 1","data":{"turn_num":turn_num,"active_player":active_player,"player_seat_id":self.game_state.player_seat_id,"comparison_result":active_player == self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    player_name = "YOUR" if active_player == self.game_state.player_seat_id else "OPPONENT'S"
                    print(f"\n{'='*70}")
                    print(f"⚔️  Turn {turn_num} - {player_name} TURN")
                    print(f"   Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
                    print(f"{'='*70}\n")
                elif turn_num > self.game_state.last_turn_announced:
                    # Subsequent turns - only announce if turn number increased
                    self.game_state.last_turn_announced = turn_num
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"tracker.py:518","message":"Announcing turn","data":{"turn_num":turn_num,"active_player":active_player,"player_seat_id":self.game_state.player_seat_id,"comparison_result":active_player == self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
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
        target_ids = []  # For multiple targets

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
                if target_id:
                    target_ids.append(target_id)
            elif key == "targets":
                # Handle multiple targets
                target_list = detail.get("valueInt32", [])
                if target_list:
                    target_ids.extend(target_list)
                    if not target_id and target_list:
                        target_id = target_list[0]  # Use first for backward compatibility

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
        
        # Handle ability annotations
        if "AnnotationType_AbilityActivated" in ann_type or "AnnotationType_ActivatedAbility" in ann_type:
            self._handle_ability_activated(affected_ids, annotation, game_objects)
            return
        elif "AnnotationType_TriggeredAbility" in ann_type or "AnnotationType_Triggered" in ann_type:
            self._handle_triggered_ability(affected_ids, annotation, game_objects)
            return

        # Only process if we have affected cards
        if not affected_ids:
            return

        instance_id = affected_ids[0]

        # Find the card object for this instance
        card_obj = None
        target_obj = None
        target_objs = []  # For multiple targets
        
        for obj in game_objects:
            if obj.get("instanceId") == instance_id:
                card_obj = obj
            if target_id and obj.get("instanceId") == target_id:
                target_obj = obj
            # Also check for multiple targets
            if target_ids and obj.get("instanceId") in target_ids:
                target_objs.append(obj)

        # Handle different annotation types
        if "AnnotationType_ZoneTransfer" in ann_type:
            # Casting spells and playing lands
            if category in ["CastSpell", "PlaySpell", "PlayLand"] and instance_id not in self.game_state.seen_instance_ids:
                self.game_state.seen_instance_ids.add(instance_id)
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    controller_seat = card_obj.get("controllerSeatId")
                    # #region agent log
                    import json as json_module
                    in_cache = grp_id in self.card_db.cache if grp_id else False
                    cached_value = self.card_db.cache.get(grp_id) if grp_id else None
                    # #endregion
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"R","location":"tracker.py:580","message":"Card name lookup","data":{"grp_id":grp_id,"card_name":card_name,"in_cache":in_cache,"cached_value":cached_value,"cache_size":len(self.card_db.cache)},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    # #region agent log
                    try:
                        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"O","location":"tracker.py:590","message":"Card play detected","data":{"card_name":card_name,"grp_id":grp_id,"owner_seat":owner_seat,"controller_seat":controller_seat,"player_seat_id":self.game_state.player_seat_id,"opponent_seat_id":self.game_state.opponent_seat_id,"category":category,"owner_matches_player":owner_seat==self.game_state.player_seat_id,"controller_matches_player":controller_seat==self.game_state.player_seat_id if controller_seat else None},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion

                    player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    player_symbol = ">" if owner_seat == self.game_state.player_seat_id else " "

                    # Get card type info
                    card_types = card_obj.get("cardTypes", [])
                    type_str = self._format_card_type(card_types)

                    # Format output based on card type - handle multiple targets
                    target_str = ""
                    if target_objs:
                        # Multiple targets
                        target_names = []
                        for t_obj in target_objs:
                            t_grp_id = t_obj.get("grpId")
                            t_name = self.card_db.get_card_name(t_grp_id) if t_grp_id else "Unknown"
                            t_owner_seat = t_obj.get("ownerSeatId")
                            t_owner = "your" if t_owner_seat == self.game_state.player_seat_id else "opponent's"
                            target_names.append(f"{t_name} ({t_owner})")
                        target_str = f" targeting {', '.join(target_names)}"
                    elif target_obj:
                        # Single target
                        target_grp_id = target_obj.get("grpId")
                        target_name = self.card_db.get_card_name(target_grp_id) if target_grp_id else "Unknown"
                        target_owner_seat = target_obj.get("ownerSeatId")
                        target_owner = "your" if target_owner_seat == self.game_state.player_seat_id else "opponent's"
                        target_str = f" targeting {target_name} ({target_owner})"
                    elif target_id:
                        # Target ID exists but object not found - might be player/planeswalker
                        # Check if it's a player seat ID
                        if target_id == self.game_state.player_seat_id:
                            target_str = " targeting you"
                        elif target_id == self.game_state.opponent_seat_id:
                            target_str = " targeting opponent"
                        else:
                            target_str = f" targeting [ID: {target_id}]"

                    # Use appropriate verb based on card type
                    # Add turn indicator if we're in a turn
                    turn_prefix = f"[Turn {self.game_state.turn_number}] " if self.game_state.turn_number > 0 else ""
                    if category == "PlayLand":
                        print(f"{turn_prefix}{player_symbol} {player:8} played {card_name} ({type_str})")
                    elif "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        print(f"{turn_prefix}{player_symbol} {player:8} cast {card_name} ({type_str} {power}/{toughness}){target_str}")
                    else:
                        print(f"{turn_prefix}{player_symbol} {player:8} cast {card_name} ({type_str}){target_str}")
                    
                    # Small delay to make output more readable
                    import time
                    time.sleep(0.1)

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

                    owner_label = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    print(f"{icon} {card_name:30} ({owner_label}) was {action}")

            # Counter spells
            elif category == "Countered":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    owner_label = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    print(f"🚫 {card_name:30} ({owner_label}) was countered")

            # Draw cards
            elif category == "Draw":
                if card_obj:
                    owner_seat = card_obj.get("ownerSeatId")
                    player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    print(f"📥 {player:8} drew a card")

            # Mill effects
            elif category == "Mill":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    print(f"🌊 {player:8} milled {card_name}")

        # Handle resolution annotations
        elif "AnnotationType_ResolutionStart" in ann_type:
            # This tracks when spells resolve - useful for seeing instants resolve
            pass  # Can be used for more detailed instant tracking

        elif "AnnotationType_Scry" in ann_type:
            # Scry events - show when players scry
            if affected_ids and card_obj:
                owner_seat = card_obj.get("ownerSeatId")
                player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                print(f"🔮 {player:8} scried")

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

                        # Store combat info for summary
                        self.game_state.current_combat_attackers[instance_id] = {
                            "card_name": card_name,
                            "power": power,
                            "toughness": toughness,
                            "owner_seat": owner_seat
                        }

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
        source_id = None
        is_combat_damage = False
        
        for detail in details:
            if detail.get("key") == "damage" or detail.get("key") == "amount":
                damage_amount = detail.get("valueInt32", [None])[0]
            elif detail.get("key") == "source" or detail.get("key") == "source_id":
                source_id = detail.get("valueInt32", [None])[0]
            elif detail.get("key") == "combat" or detail.get("key") == "is_combat":
                is_combat_damage = detail.get("valueBool", [False])[0] or detail.get("valueInt32", [0])[0] == 1

        # Check if we're in combat phase
        if self.game_state.combat_phase_active:
            is_combat_damage = True

        if damage_amount and affected_ids:
            for instance_id in affected_ids:
                for obj in game_objects:
                    if obj.get("instanceId") == instance_id:
                        grp_id = obj.get("grpId")
                        owner_seat = obj.get("ownerSeatId")
                        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                        owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                        
                        # Find source if available
                        source_name = None
                        if source_id:
                            for source_obj in game_objects:
                                if source_obj.get("instanceId") == source_id:
                                    source_grp_id = source_obj.get("grpId")
                                    source_name = self.card_db.get_card_name(source_grp_id) if source_grp_id else None
                                    break
                        
                        if is_combat_damage:
                            # Store for combat summary
                            self.game_state.combat_damage_events.append({
                                "source": source_name,
                                "target": card_name,
                                "target_owner": owner,
                                "amount": damage_amount
                            })
                            
                            if source_name:
                                print(f"⚔️ Combat: {source_name} dealt {damage_amount} damage to {card_name} ({owner})")
                            else:
                                print(f"⚔️ Combat: {card_name} ({owner}) took {damage_amount} damage")
                        else:
                            print(f"💢 {card_name:30} ({owner}) took {damage_amount} damage")
                        break

    def _handle_ability_activated(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle activated ability events."""
        if not affected_ids:
            return
        
        details = annotation.get("details", [])
        ability_source_id = affected_ids[0] if affected_ids else None
        target_ids = []
        
        # Extract ability details
        for detail in details:
            key = detail.get("key", "")
            if key == "target" or key == "target_id":
                target_id = detail.get("valueInt32", [None])[0]
                if target_id:
                    target_ids.append(target_id)
            elif key == "targets":
                target_list = detail.get("valueInt32", [])
                if target_list:
                    target_ids.extend(target_list)
        
        # Find the source card
        source_obj = None
        for obj in game_objects:
            if obj.get("instanceId") == ability_source_id:
                source_obj = obj
                break
        
        if source_obj:
            grp_id = source_obj.get("grpId")
            owner_seat = source_obj.get("ownerSeatId")
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            
            player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "🔮"
            
            # Find targets
            target_str = ""
            if target_ids:
                target_names = []
                for t_id in target_ids:
                    # Check if it's a player seat
                    if t_id == self.game_state.player_seat_id:
                        target_names.append("you")
                    elif t_id == self.game_state.opponent_seat_id:
                        target_names.append("opponent")
                    else:
                        # Find target object
                        for obj in game_objects:
                            if obj.get("instanceId") == t_id:
                                t_grp_id = obj.get("grpId")
                                t_name = self.card_db.get_card_name(t_grp_id) if t_grp_id else f"[ID: {t_id}]"
                                t_owner_seat = obj.get("ownerSeatId")
                                t_owner = "your" if t_owner_seat == self.game_state.player_seat_id else "opponent's"
                                target_names.append(f"{t_name} ({t_owner})")
                                break
                        else:
                            target_names.append(f"[ID: {t_id}]")
                
                if target_names:
                    target_str = f" targeting {', '.join(target_names)}"
            
            print(f"{player_symbol} {player:8} activated ability: {card_name} ({'your' if owner_seat == self.game_state.player_seat_id else 'opponent\'s'}){target_str}")

    def _handle_triggered_ability(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle triggered ability events."""
        if not affected_ids:
            return
        
        details = annotation.get("details", [])
        trigger_source_id = affected_ids[0] if affected_ids else None
        
        # Extract trigger details
        trigger_type = None
        for detail in details:
            key = detail.get("key", "")
            if key == "trigger_type" or key == "trigger":
                trigger_type = detail.get("valueString", [None])[0]
                break
        
        # Find the source card
        source_obj = None
        for obj in game_objects:
            if obj.get("instanceId") == trigger_source_id:
                source_obj = obj
                break
        
        if source_obj:
            grp_id = source_obj.get("grpId")
            owner_seat = source_obj.get("ownerSeatId")
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            
            player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "✨"
            
            trigger_desc = trigger_type if trigger_type else "triggered"
            print(f"{player_symbol} Triggered: {card_name} ({'your' if owner_seat == self.game_state.player_seat_id else 'opponent\'s'}) - {trigger_desc}")

    def _display_combat_summary(self):
        """Display a summary of combat after it ends."""
        if not self.game_state.current_combat_attackers and not self.game_state.combat_damage_events:
            return
        
        # Show combat summary if we have significant combat activity
        if self.game_state.combat_damage_events:
            print("\n⚔️ Combat Summary:")
            for event in self.game_state.combat_damage_events:
                if event.get("source"):
                    print(f"   {event['source']} → {event['target']} ({event['target_owner']}): {event['amount']} damage")
            print()

    def _print_game_summary(self):
        """Print summary when game ends."""
        match_type_display = "Best-of-3" if self.game_state.match_type == "best_of_3" else "Best-of-1"
        game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
        
        print("\n" + "="*70)
        print(f"🏁 GAME ENDED - {match_type_display}{game_num_display}")
        print("="*70)

        # Calculate game time
        if self.game_state.game_start_time and self.game_state.game_end_time:
            duration = self.game_state.game_end_time - self.game_state.game_start_time
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            print(f"\n⏱️  Game Duration: {minutes}m {seconds}s")

        # Winner - MAKE THIS VERY PROMINENT
        print("\n" + "="*70)
        # #region agent log
        import json as json_module
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"W","location":"tracker.py:900","message":"Printing game summary","data":{"winner_seat":self.game_state.winner_seat,"player_seat_id":self.game_state.player_seat_id,"opponent_seat_id":self.game_state.opponent_seat_id,"player_life":self.game_state.player_life,"opponent_life":self.game_state.opponent_life,"match_type":self.game_state.match_type,"game_number":self.game_state.game_number},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        if self.game_state.winner_seat is not None:
            if self.game_state.winner_seat == self.game_state.player_seat_id:
                print("🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉")
                print("   (Opponent conceded/disconnected)")
            else:
                print("💀💀💀 YOU LOST THIS GAME 💀💀💀")
                print("   (You conceded/left the game)")
        elif self.game_state.player_life <= 0:
            print("💀💀💀 YOU LOST THIS GAME 💀💀💀")
            print("   (You reached 0 life)")
        elif self.game_state.opponent_life <= 0:
            print("🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉")
            print("   (Opponent reached 0 life)")
        else:
            # Fallback - determine by life totals if no clear winner
            if self.game_state.player_life < self.game_state.opponent_life:
                print("💀💀💀 YOU LOST THIS GAME 💀💀💀")
                print(f"   (Life totals: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent)")
            elif self.game_state.player_life > self.game_state.opponent_life:
                print("🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉")
                print(f"   (Life totals: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent)")
            else:
                print("🏁 GAME ENDED")
                print(f"   (Life totals: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent)")
        
        # Show best-of-3 match status if applicable
        if self.game_state.match_type == "best_of_3":
            print("\n" + "="*70)
            print(f"📊 Best-of-3 Match Status:")
            print(f"   Game {self.game_state.game_number} of 3")
            if self.match_games:
                print(f"   Previous games:")
                for game in self.match_games:
                    game_winner = "You" if game["winner"] == self.game_state.player_seat_id else "Opponent"
                    print(f"      Game {game['game_number']}: {game_winner} won")
            print("="*70)
        
        print("="*70)
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
        # #region agent log
        import json as json_module
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"tracker.py:756","message":"Printing summary","data":{"first_player_seat":self.game_state.first_player_seat,"player_seat_id":self.game_state.player_seat_id,"turn_number":self.game_state.turn_number},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        if self.game_state.first_player_seat is not None:
            went_first = "You" if self.game_state.first_player_seat == self.game_state.player_seat_id else "Opponent"
            print(f"   Went First: {went_first}")
        else:
            print(f"   Went First: Unknown (first_player_seat={self.game_state.first_player_seat}, player_seat_id={self.game_state.player_seat_id})")
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
