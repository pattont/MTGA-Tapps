"""Card tracking module.

Tracks cards played by the player and opponents.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from .log_parser import MTGALogParser
from .card_database import CardDatabase
from .paths import DEBUG_LOG_PATH_STR
from .deck_llm import identify_deck, is_deck_llm_enabled, diagnose as deck_llm_diagnose


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
        self.last_player_turn_number = 0  # Turn number when it was last the player's turn (for attributing late-arriving player events)

        # Auto-detected seat IDs
        self.player_seat_id: Optional[int] = None
        self.opponent_seat_id: Optional[int] = None

        # Your account ID for matching against reservedPlayers
        self.my_user_id: Optional[str] = None

        # Starting hand tracking
        self.starting_hand: List[str] = []
        self.mulligan_count = 0
        self.initial_hand_size = 7
        self._hand_before_mulligan: List[str] = []  # 7-card hand before mulligan (to show card thrown away)

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

        # Defer "Turn N - OPPONENT'S TURN" until we see an opponent action or next turn.
        # Avoids printing that header before late-arriving player actions (e.g. cast on turn 1).
        self.pending_opponent_turn_header: Optional[tuple] = None  # (turn_num, active_player) or None

        # Match type tracking
        self.match_type: str = "best_of_1"  # "best_of_1" or "best_of_3"
        self.game_number: int = 1  # Current game number in the match (1, 2, or 3)

        # Match metadata (for display: "Match started", "Format", "Players")
        self.format_str: str = "Unknown"  # e.g. Brawl, Standard (from match room event if available)
        self.player_display_name: Optional[str] = None  # Your screen name from auth (logs), if seen
        self.opponent_display_name: Optional[str] = None  # Opponent name from reservedPlayers if in log
        self._reserved_players: List[Dict[str, Any]] = []  # reservedPlayers from match room (seat -> name)

    def reset(self):
        """Reset the game state for a new game. Seat IDs are cleared so we re-detect from hand visibility each game."""
        player_seat = self.player_seat_id
        opponent_seat = self.opponent_seat_id
        format_str = self.format_str
        player_display_name = self.player_display_name
        self.__init__()
        # Do NOT preserve seats: re-evaluate each game from opening hand visibility
        self.player_seat_id = None
        self.opponent_seat_id = None
        self.format_str = format_str
        self.player_display_name = player_display_name


class CardEvent:
    """Represents a card play event."""

    def __init__(self, card_name: str, player: str, timestamp: Optional[datetime] = None, card_type_category: Optional[str] = None):
        """Initialize a card event.

        Args:
            card_name: Name of the card played.
            player: 'player' or 'opponent'.
            timestamp: When the card was played.
            card_type_category: Primary type for breakdown (Land, Creature, Instant, Sorcery, Enchantment, Artifact, Planeswalker, Other).
        """
        self.card_name = card_name
        self.player = player
        self.timestamp = timestamp or datetime.now()
        self.card_type_category = card_type_category or "Other"

    def __repr__(self) -> str:
        return f"CardEvent(card={self.card_name}, player={self.player}, time={self.timestamp})"


class CardTracker:
    """Tracks cards played during MTGA matches."""

    def __init__(self, log_parser: Optional[MTGALogParser] = None,
                 card_db: Optional[CardDatabase] = None,
                 mtga_data_dir: Optional[str] = None):
        """Initialize the card tracker.

        Args:
            log_parser: Optional MTGALogParser instance. If not provided, creates one.
            card_db: Optional CardDatabase instance. If not provided, creates one.
            mtga_data_dir: Optional path to MTGA data root for local card DB (Raw_CardDatabase_*.mtga).
        """
        self.parser = log_parser or MTGALogParser()
        self.card_db = card_db or CardDatabase(
            log_path=self.parser.log_path,
            mtga_data_dir=mtga_data_dir,
        )
        self.game_state = GameState()
        self.player_cards: List[CardEvent] = []
        self.opponent_cards: List[CardEvent] = []
        self.running = False
        self.match_games: List[Dict] = []  # Track games in the match for summary
        self.waiting_for_next_game: bool = False  # True if launched mid-game, waiting for next game
        self._pending_game_summary: bool = False  # Defer summary until end of line batch (so ConcedeReq can set winner)

    def start(self):
        """Start tracking cards."""
        print("\n" + "=" * 75)
        print("🟡 🔵 ⚫ 🔴 🟢 MTGA Card Tracker - Real-time Match Analyzer 🟡 🔵 ⚫ 🔴 🟢")
        print("=" * 75)
        # Show log path with ~ instead of actual username when under home dir
        try:
            log_path = Path(self.parser.log_path).resolve()
            display_path = ("~/" + str(log_path.relative_to(Path.home()))) if log_path.is_relative_to(Path.home()) else str(log_path)
        except Exception:
            display_path = self.parser.log_path
        print(f"📂 Monitoring: {display_path}")

        # Player seat will be detected automatically when a game starts
        print("⏳ Seat will be detected automatically")

        # print("\n   Waiting for game events...")
        print("\n   Play a game in MTGA to see cards tracked in real-time!")
        print("\n   Press Ctrl+C to stop")
        print("=" * 75 + "\n")

        # Start from current end of file
        # #region agent log
        import json as json_module
        try:
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"K","location":"tracker.py:127","message":"Starting tracker loop","data":{"log_path":self.parser.log_path,"player_seat_id":self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        self.parser.reset_position()
        
        # Check if we're launching mid-game
        self._check_if_mid_game()
        
        # #region agent log
        try:
            import os
            log_exists = os.path.exists(self.parser.log_path)
            log_size = os.path.getsize(self.parser.log_path) if log_exists else 0
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"L","location":"tracker.py:132","message":"After reset_position","data":{"log_path":self.parser.log_path,"log_exists":log_exists,"log_size":log_size,"last_position":self.parser.last_position,"waiting_for_next_game":self.waiting_for_next_game},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # Safety: If waiting_for_next_game is set, give it a timeout
        # After 5 minutes, assume we can start tracking
        self.waiting_start_time = time.time() if self.waiting_for_next_game else None
        
        self.running = True

        try:
            while self.running:
                # Safety: If we've been waiting for next game for more than 5 minutes, clear the flag
                if self.waiting_for_next_game and self.waiting_start_time:
                    if time.time() - self.waiting_start_time > 300:  # 5 minutes
                        print("\n" + "="*75)
                        print("⚠️  TIMEOUT: Clearing waiting flag - starting to track")
                        print("="*75 + "\n")
                        self.waiting_for_next_game = False
                        self.waiting_start_time = None
                
                self._process_new_events()
                time.sleep(0.5)  # Check for new events twice per second
        except KeyboardInterrupt:
            print("\n" + "=" * 75)
            print("🛑 Stopping tracker...")
            self._print_summary()
            print("=" * 75)

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

    def _check_if_mid_game(self):
        """Only set mid-game if the tail of the log shows an active game and no match-end (lobby = match already ended)."""
        import json as json_module
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-300:] if len(lines) > 300 else lines

            # If the tail contains match-end, we're in lobby or between games — not mid-game
            match_end_markers = (
                "matchcompleted", "gamecompleted", "concedereq", "matchendscene",
                "you left", "opponent left", "you concede", "opponent concede",
                "finalresults", "on sceneloaded for matchendscene"
            )
            tail_text = "\n".join(tail).lower()
            if any(m in tail_text for m in match_end_markers):
                return

            # No match-end in tail; check for active game state (turn > 0 or zones with cards)
            for line in reversed(tail):
                event = self.parser.extract_card_events(line)
                if not event or event.get("type") != "game_state":
                    continue
                data = event.get("data", {})
                if "turnInfo" in data:
                    turn_num = (data.get("turnInfo") or {}).get("turnNumber", 0)
                    if turn_num and turn_num > 0:
                        self.waiting_for_next_game = True
                        print("\n" + "="*75)
                        print("⚠️  DETECTED GAME IN PROGRESS")
                        print("="*75)
                        print("   Tracker launched mid-game.")
                        print("   Will start tracking at the beginning of the next game.")
                        print("="*75 + "\n")
                        return
                if "zones" in data:
                    for zone in (data.get("zones") or []):
                        ztype = (zone.get("type") or "")
                        objs = zone.get("objectInstanceIds", [])
                        if objs and ("Battlefield" in ztype or "Hand" in ztype):
                            self.waiting_for_next_game = True
                            print("\n" + "="*75)
                            print("⚠️  DETECTED GAME IN PROGRESS")
                            print("="*75)
                            print("   Tracker launched mid-game.")
                            print("   Will start tracking at the beginning of the next game.")
                            print("="*75 + "\n")
                            return
        except Exception:
            pass

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
                    with open(DEBUG_LOG_PATH_STR, 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"tracker.py:198","message":"Reading log line","data":{"line_count":line_count,"line_preview":line[:100] if line else None,"log_path":self.parser.log_path},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
            # #endregion
            self._process_line(line)
        # Defer game summary until after all lines processed (so ConcedeReq can set winner before we print)
        if self.game_state.match_complete and self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False
        # #region agent log
        if line_count == 0:
            try:
                with open(DEBUG_LOG_PATH_STR, 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"tracker.py:207","message":"No new lines read","data":{"log_path":self.parser.log_path,"last_position":self.parser.last_position},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
        # #endregion

    def _process_line(self, line: str):
        """Process a single line from the log file.

        Args:
            line: A line from the MTGA log file.
        """
        # Always try to pick up match metadata (format, player name) from any line
        self._parse_match_metadata(line)

        # Skip processing if we're waiting for the next game (launched mid-game)
        if self.waiting_for_next_game:
            # Only check for new game start, ignore everything else
            self._check_game_start(line)
            return
        
        # #region agent log
        import json as json_module
        try:
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"I","location":"tracker.py:222","message":"Processing line","data":{"line_length":len(line),"has_reservedplayers":"reservedplayers" in line.lower(),"has_gamestate":"gamestatemessage" in line.lower(),"player_seat_id":self.game_state.player_seat_id,"in_match":self.game_state.in_match},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        # Try to detect player seat if not yet detected
        if self.game_state.player_seat_id is None:
            self._try_detect_player_seat(line)

        # Check for game start
        if not self.game_state.in_match:
            self._check_game_start(line)

        # Check for game end (always call when in_match so ConcedeReq can set winner even after MatchCompleted)
        if self.game_state.in_match:
            self._check_game_end(line)

        # Look for card-related events
        event = self.parser.extract_card_events(line)
        if event:
            # #region agent log
            try:
                with open(DEBUG_LOG_PATH_STR, 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"J","location":"tracker.py:241","message":"Event extracted","data":{"event_type":event.get("type") if event else None},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            self._handle_event(event)

    def _try_detect_player_seat(self, line: str):
        """Set player/opponent by hand visibility only: we can see our cards (grpId known), we cannot see opponent's."""
        event = self.parser.extract_card_events(line)
        if not event or event.get("type") != "game_state":
            return
        data = event.get("data", {})
        zones = data.get("zones", [])
        game_objects = data.get("gameObjects", [])

        instance_to_grp = {}
        for obj in game_objects:
            iid, gid = obj.get("instanceId"), obj.get("grpId", 0)
            if iid and gid and gid > 0:
                instance_to_grp[iid] = gid

        hands = []
        for zone in zones:
            if "Hand" not in (zone.get("type") or ""):
                continue
            owner_seat = zone.get("ownerSeatId")
            obj_ids = zone.get("objectInstanceIds", [])
            if not obj_ids or not owner_seat:
                continue
            visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
            hands.append({"seat": owner_seat, "visible": visible, "total": len(obj_ids)})

        if len(hands) != 2 or hands[0]["total"] == 0 or hands[1]["total"] == 0:
            return

        h1, h2 = hands[0], hands[1]
        # Hand we can see (visible > 0) = me. Hand we cannot see (visible == 0) = opponent.
        if h1["visible"] > 0 and h2["visible"] == 0:
            self.game_state.player_seat_id = h1["seat"]
            self.game_state.opponent_seat_id = h2["seat"]
        elif h2["visible"] > 0 and h1["visible"] == 0:
            self.game_state.player_seat_id = h2["seat"]
            self.game_state.opponent_seat_id = h1["seat"]
        elif h1["visible"] != h2["visible"]:
            # One hand we see more of = that seat is us
            if h1["visible"] > h2["visible"]:
                self.game_state.player_seat_id = h1["seat"]
                self.game_state.opponent_seat_id = h2["seat"]
            else:
                self.game_state.player_seat_id = h2["seat"]
                self.game_state.opponent_seat_id = h1["seat"]
        else:
            return
        # Resolve player/opponent names from reservedPlayers if we have them (match room may have been parsed earlier)
        if self.game_state._reserved_players:
            for r in self.game_state._reserved_players:
                if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                    self.game_state.player_display_name = self.game_state.player_display_name or r["name"]
                elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                    self.game_state.opponent_display_name = r["name"]
        print(f"Detected: You are Seat {self.game_state.player_seat_id} (hand we can see = you, hand we cannot see = opponent)")
        print("="*75)

    def _get_name_from_dict(self, d: Dict[str, Any]) -> Optional[str]:
        """Get first non-empty string from dict using common name keys (any casing)."""
        if not d or not isinstance(d, dict):
            return None
        for key in ("screenName", "ScreenName", "displayName", "DisplayName", "accountName", "userName", "name"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _parse_match_metadata(self, line: str) -> None:
        """Extract format and player display name from log lines (match room, auth)."""
        data = self.parser.parse_json_from_line(line)
        if not data:
            return
        # Your screen name from authenticateResponse (seen when connecting). Try multiple keys.
        if "authenticateResponse" in data and self.game_state.player_display_name is None:
            auth = data.get("authenticateResponse")
            if isinstance(auth, dict):
                name = self._get_name_from_dict(auth)
                if name:
                    self.game_state.player_display_name = name
        # Format and reserved players from match room event (when a match is set up)
        if "matchGameRoomStateChangedEvent" in data:
            event = data.get("matchGameRoomStateChangedEvent") or {}
            room = event.get("gameRoomInfo") or {}
            config = room.get("gameRoomConfig") or {}
            # Reserved players: may include display/screen name per seat (e.g. "BigFudge55")
            reserved = config.get("reservedPlayers") or config.get("ReservedPlayers")
            if isinstance(reserved, list) and reserved:
                self.game_state._reserved_players = []
                for p in reserved:
                    if isinstance(p, dict):
                        seat = p.get("systemSeatId") or p.get("systemSeat")
                        name = self._get_name_from_dict(p)
                        self.game_state._reserved_players.append({"seat": seat, "name": name})
                # If we know our seat, resolve our name and opponent's from reserved list
                if self.game_state.player_seat_id is not None and self.game_state._reserved_players:
                    for r in self.game_state._reserved_players:
                        if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                            self.game_state.player_display_name = self.game_state.player_display_name or r["name"]
                        elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                            self.game_state.opponent_display_name = r["name"]
            # Format
            fmt = (
                config.get("eventType")
                or config.get("variant")
                or config.get("gameMode")
                or config.get("format")
            )
            if isinstance(fmt, str) and fmt:
                self.game_state.format_str = fmt
            elif isinstance(fmt, (int, float)):
                self.game_state.format_str = str(fmt)

    def _print_match_started_block(self) -> None:
        """Print match started time, format, and players (like reference UI)."""
        g = self.game_state
        time_str = g.game_start_time.strftime("%I:%M %p") if g.game_start_time else "?"
        print(f"   Match started: {time_str}")
        # Use match_type when format not in log: "Standard Best-of-1" / "Standard Best-of-3"
        format_display = g.format_str if g.format_str != "Unknown" else (
            "Standard Best-of-3" if g.match_type == "best_of_3" else "Standard Best-of-1"
        )
        print(f"   Format: {format_display}")
        player_label = g.player_display_name or "You"
        opponent_label = g.opponent_display_name or "Opponent"
        print(f"   Players: {player_label} vs {opponent_label}")

    def _check_game_start(self, line: str):
        """Check if a game is starting."""
        # If we're waiting for next game, check if this is a new game start
        if self.waiting_for_next_game:
            # Check if this is actually a new game start (mulligan or turn 1)
            line_lower = line.lower()
            # More robust mulligan detection
            if ("mulligantype" in line_lower or 
                ("mulligan" in line_lower and ("gretolient" in line_lower or "gretoclient" in line_lower)) or
                "mulliganreq" in line_lower):
                self.waiting_for_next_game = False
                print("\n" + "="*75)
                print("✅ NEW GAME DETECTED - Starting to track!")
                print("="*75 + "\n")
            else:
                # Check for turn 1 in game state
                event = self.parser.extract_card_events(line)
                if event and event.get("type") == "game_state":
                    data = event.get("data", {})
                    if "turnInfo" in data:
                        turn_info = data.get("turnInfo", {})
                        turn_num = turn_info.get("turnNumber", 0)
                        if turn_num == 1:
                            self.waiting_for_next_game = False
                            print("\n" + "="*75)
                            print("✅ NEW GAME DETECTED - Starting to track!")
                            print("="*75 + "\n")
                    # Also check for zones with cards (indicates new game)
                    elif "zones" in data:
                        zones = data.get("zones", [])
                        for zone in zones:
                            if zone.get("type") == "ZoneType_Hand" and zone.get("objectInstanceIds"):
                                # Found a hand with cards - this is likely a new game
                                self.waiting_for_next_game = False
                                print("\n" + "="*75)
                                print("✅ NEW GAME DETECTED - Starting to track!")
                                print("="*75 + "\n")
                                break
        
        # If we're waiting for next game, don't process game start yet
        if self.waiting_for_next_game:
            return
        
        # If we're already in a match but it's complete, reset for a new game
        if self.game_state.in_match and self.game_state.match_complete:
            # Print summary first if we haven't yet (e.g. new game started in same batch)
            if self._pending_game_summary:
                self._print_game_summary()
                self._pending_game_summary = False
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
            print("\n" + "="*75)
            print(f"🔄 GAME {self.game_state.game_number} STARTING (Best-of-3 Match)")
            print("="*75 + "\n")
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
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"U","location":"tracker.py:365","message":"Checking game start","data":{"line_preview":line[:100],"in_match":self.game_state.in_match,"mulligan_found":"mulligantype" in line_lower or ("mulligan" in line_lower and "gretolient" in line_lower)},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # Look for game start indicators - mulligan phase means game is starting
        # More robust mulligan detection patterns
        if ("mulligantype" in line_lower or 
            ("mulligan" in line_lower and ("gretolient" in line_lower or "gretoclient" in line_lower)) or
            "mulliganreq" in line_lower):
            # Clear waiting flag if we were waiting for next game
            if self.waiting_for_next_game:
                self.waiting_for_next_game = False
                print("\n" + "="*75)
                print("✅ NEW GAME DETECTED - Starting to track!")
                print("="*75 + "\n")
            
            self.game_state.game_start_time = datetime.now()
            self.game_state.in_match = True
            self.game_state.match_complete = False  # Reset match complete flag for new game
            self.player_cards = []
            self.opponent_cards = []
            # #region agent log
            try:
                with open(DEBUG_LOG_PATH_STR, 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"U","location":"tracker.py:375","message":"Game started via mulligan","data":{"reason":"mulligan","match_type":self.game_state.match_type,"game_number":self.game_state.game_number},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            format_display = "Standard Best-of-3" if self.game_state.match_type == "best_of_3" else "Standard Best-of-1"
            game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
            print("\n" + "="*75)
            print(f"🎮 🎮 🎮 GAME STARTED 🎮 🎮 🎮")
            print("="*75)
            self._print_match_started_block()
            print()
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
                    # Clear waiting flag if we were waiting for next game
                    if self.waiting_for_next_game:
                        self.waiting_for_next_game = False
                        print("\n" + "="*75)
                        print("✅ NEW GAME DETECTED - Starting to track!")
                        print("="*75 + "\n")
                    
                    self.game_state.game_start_time = datetime.now()
                    self.game_state.in_match = True
                    self.game_state.match_complete = False  # Reset match complete flag for new game
                    self.player_cards = []
                    self.opponent_cards = []
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"U","location":"tracker.py:395","message":"Game started via turn 1","data":{"turn_num":turn_num,"match_type":self.game_state.match_type,"game_number":self.game_state.game_number},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    format_display = "Standard Best-of-3" if self.game_state.match_type == "best_of_3" else "Standard Best-of-1"
                    game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
                    print("\n" + "="*75)
                    print(f"🎮 GAME STARTED - {format_display}{game_num_display}")
                    print("="*75)
                    self._print_match_started_block()
                    print()
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
                                    if len(hand_cards) == 7 and not self.game_state.starting_hand and not self.game_state._hand_before_mulligan:
                                        self.game_state._hand_before_mulligan = hand_cards
                                    elif not self.game_state.starting_hand:
                                        self.game_state.starting_hand = hand_cards
                                        self.game_state.initial_hand_size = len(hand_cards)
                                        self.game_state.mulligan_count = 7 - len(hand_cards)
                                        if self.game_state._hand_before_mulligan:
                                            thrown = [c for c in self.game_state._hand_before_mulligan if c not in hand_cards]
                                            if thrown:
                                                print(f"🔄 Mulliganed away: {', '.join(thrown)}")
                                            self.game_state._hand_before_mulligan = []
                                        elif len(hand_cards) < 7:
                                            print(f"🔄 Mulligan to {len(hand_cards)} (mulligans: {self.game_state.mulligan_count})")
                                        n = len(self.game_state.starting_hand)
                                        print(f"\n🎴 Your Starting Hand ({n} cards):")
                                        for card in self.game_state.starting_hand:
                                            print(f"   • {card}")
                                        print()

    def _check_game_end(self, line: str):
        """Check if the game has ended."""
        if not self.game_state.in_match:
            return
        line_lower = line.lower()
        
        # #region agent log
        import json as json_module
        try:
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:428","message":"Checking game end","data":{"line_preview":line[:150],"in_match":self.game_state.in_match,"match_complete":self.game_state.match_complete,"patterns_found":{"gamecompleted":any(x in line_lower for x in ["gamecompletedtype","matchcompleted","finalresults"]),"opponent_left":any(x in line_lower for x in ["opponentleft","concede","disconnect"]),"you_left":any(x in line_lower for x in ["playerleft","youleft","you left","i left"])}},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # Check for concede requests - need to check WHO conceded
        # Process even when match_complete so we can set winner_seat before deferred summary
        if "concedereq" in line_lower or "ClientMessageType_ConcedeReq" in line:
            json_data = self.parser.parse_json_from_line(line)
            seat_id = self._find_nested(json_data, "systemSeatId") if json_data else None
            if seat_id is not None:
                if seat_id == self.game_state.player_seat_id:
                    self.game_state.winner_seat = self.game_state.opponent_seat_id
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:concede_req","message":"Player conceded","data":{"seat_id":seat_id,"player_seat_id":self.game_state.player_seat_id,"winner_seat":self.game_state.winner_seat},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                elif seat_id == self.game_state.opponent_seat_id:
                    self.game_state.winner_seat = self.game_state.player_seat_id
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:concede_req","message":"Opponent conceded","data":{"seat_id":seat_id,"opponent_seat_id":self.game_state.opponent_seat_id,"winner_seat":self.game_state.winner_seat},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
            else:
                # ConcedeReq in our log is from our client → we conceded (opponent wins)
                if self.game_state.opponent_seat_id is not None:
                    self.game_state.winner_seat = self.game_state.opponent_seat_id
            if self.game_state.winner_seat is not None and not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self._pending_game_summary = True
                return
        
        # Check for you leaving/conceding FIRST (you lose) - must check before opponent patterns
        # Always set winner_seat when we see explicit "you left" so we overwrite any wrong winner from an earlier line.
        if any(pattern in line_lower for pattern in [
            "youleft", "you left", "i left",
            "i concede", "you concede", "conceded the match",
            "quit the match", "defeat", "you were defeated",
            "you disconnected", "i disconnected",
            "forfeit", "you forfeit", "i forfeit", "forfeited",
        ]) and not any(pattern in line_lower for pattern in ["opponentleft", "opponent left", "opponent quit"]):
            self.game_state.winner_seat = self.game_state.opponent_seat_id
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self._pending_game_summary = True
            # #region agent log
            try:
                with open(DEBUG_LOG_PATH_STR, 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:456","message":"You left/forfeited detected","data":{"winner_seat":self.game_state.winner_seat,"opponent_seat_id":self.game_state.opponent_seat_id,"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            return
        
        # Check for match completion state changes - be very specific
        # Only set match_complete here; do NOT set winner_seat (we don't know who won from this line).
        if '"old":"matchcompleted"' in line_lower or '"old":"MatchCompleted"' in line:
            if '"new":"matchcompleted"' in line_lower or '"new":"MatchCompleted"' in line or '"new":"disconnected"' in line_lower:
                if not self.game_state.match_complete:
                    self.game_state.match_complete = True
                    self.game_state.game_end_time = datetime.now()
                    self._pending_game_summary = True
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:456","message":"Match completed state transition detected","data":{"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    return
        
        # Check for opponent leaving/conceding (you win). Always set winner_seat so we overwrite
        # any wrong winner from an earlier generic completion line.
        if any(pattern in line_lower for pattern in [
            "opponentleft", "opponent concede", "opponent disconnected",
            "opponent left", "opponent quit", "opponent conceded"
        ]):
            self.game_state.winner_seat = self.game_state.player_seat_id
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self._pending_game_summary = True
            # #region agent log
            try:
                with open(DEBUG_LOG_PATH_STR, 'a') as f:
                    f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:467","message":"Opponent left detected","data":{"winner_seat":self.game_state.winner_seat,"player_seat_id":self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
            except: pass
            # #endregion
            return
        
        # Check for game completion messages (try to parse JSON)
        # Only set winner_seat from winningTeamId if we don't already have it (e.g. from ConcedeReq / opponent left).
        if any(pattern in line_lower for pattern in [
            "gamecompletedtype", "finalresults",
            "matchendscene", "on sceneloaded for matchendscene"
        ]):
            json_data = self.parser.parse_json_from_line(line)
            if json_data and not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                if self.game_state.winner_seat is None:
                    winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(json_data, "winningteamid")
                    if winner_team is not None and winner_team in (1, 2):
                        self.game_state.winner_seat = int(winner_team)
                self._pending_game_summary = True
                # #region agent log
                try:
                    with open(DEBUG_LOG_PATH_STR, 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:475","message":"Game completion detected","data":{"winner_seat":self.game_state.winner_seat,"json_keys":list(json_data.keys()) if isinstance(json_data, dict) else None,"line_preview":line[:150]},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                return
        
        # Check for state change FROM "Playing" TO "MatchCompleted" - this is the actual game end
        if '"old":"playing"' in line_lower and '"new":"matchcompleted"' in line_lower:
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                if self.game_state.winner_seat is None:
                    json_data = self.parser.parse_json_from_line(line)
                    if json_data:
                        winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(json_data, "winningteamid")
                        if winner_team is not None and winner_team in (1, 2):
                            self.game_state.winner_seat = int(winner_team)
                self._pending_game_summary = True
                # #region agent log
                try:
                    with open(DEBUG_LOG_PATH_STR, 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"X","location":"tracker.py:state_transition","message":"MatchCompleted state transition detected (Playing -> MatchCompleted)","data":{"line_preview":line[:150],"winner_seat":self.game_state.winner_seat},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
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

        # Then process annotations (card plays, etc.) so they appear under the turn header.
        self._process_game_events(event_data)

    def _update_game_state(self, data: Dict[str, Any]):
        """Update the tracked game state from event data."""
        # Process turn info and print turn header FIRST so "Turn N - YOUR TURN" appears
        # before card plays and life changes from this same message.
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
                with open(DEBUG_LOG_PATH_STR, 'a') as f:
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

            # Capture who went first as soon as we see turn 1 (don't require turn_changed)
            if turn_num == 1 and self.game_state.first_player_seat is None and active_player is not None:
                self.game_state.first_player_seat = active_player
            
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
                    with open(DEBUG_LOG_PATH_STR, 'a') as f:
                        f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"V","location":"tracker.py:495","message":"New turn detected","data":{"old_turn":self.game_state.turn_number,"new_turn":turn_num,"old_active_player":self.game_state.active_player,"new_active_player":active_player,"player_seat_id":self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                except: pass
                # #endregion
                
                # Detect who went first (on turn 1)
                if turn_num == 1 and self.game_state.first_player_seat is None and active_player is not None:
                    self.game_state.first_player_seat = active_player
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"tracker.py:510","message":"Turn 1 detected - storing first player","data":{"first_player_seat":active_player,"player_seat_id":self.game_state.player_seat_id,"player_went_first":active_player==self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion

                # Announce turn change
                # Defer "Turn N - OPPONENT'S TURN" until we see an opponent action or next turn,
                # so late-arriving player actions (e.g. cast on turn 1) show under "Turn 1 - YOUR TURN".
                if turn_num == 1 and self.game_state.last_turn_announced < 1:
                    # First turn - always announce
                    self.game_state.last_turn_announced = turn_num
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"tracker.py:518","message":"Announcing turn 1","data":{"turn_num":turn_num,"active_player":active_player,"player_seat_id":self.game_state.player_seat_id,"comparison_result":active_player == self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    if active_player == self.game_state.player_seat_id:
                        self.game_state.last_player_turn_number = turn_num
                        print(f"\n{'='*75}")
                        print(f"⚔️  Turn {turn_num} - YOUR TURN")
                        print(f"   Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
                        print(f"{'='*75}\n")
                    else:
                        self.game_state.pending_opponent_turn_header = (turn_num, active_player)
                elif turn_num > self.game_state.last_turn_announced:
                    # Subsequent turns - only announce if turn number increased
                    self.game_state.last_turn_announced = turn_num
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"tracker.py:518","message":"Announcing turn","data":{"turn_num":turn_num,"active_player":active_player,"player_seat_id":self.game_state.player_seat_id,"comparison_result":active_player == self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    if active_player == self.game_state.player_seat_id:
                        self.game_state.last_player_turn_number = turn_num
                        self._flush_pending_opponent_turn_header()
                        print(f"\n{'='*75}")
                        print(f"⚔️  Turn {turn_num} - YOUR TURN")
                        print(f"   Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
                        print(f"{'='*75}\n")
                    else:
                        self.game_state.pending_opponent_turn_header = (turn_num, active_player)

        # Update life totals (after turn header so header prints first)
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

    def _flush_pending_opponent_turn_header(self) -> None:
        """Print and clear deferred 'Turn N - OPPONENT'S TURN' header if set.

        Called at start of _process_annotation (so opponent actions appear under the
        correct header) and before announcing 'Turn N - YOUR TURN' (so we don't
        skip the opponent turn header when opponent passed with no actions).
        """
        pending = self.game_state.pending_opponent_turn_header
        if not pending:
            return
        turn_num, active_player = pending
        self.game_state.pending_opponent_turn_header = None
        self.game_state.last_turn_announced = turn_num
        print(f"\n{'='*75}")
        print(f"⚔️  Turn {turn_num} - OPPONENT'S TURN")
        print(f"   Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
        print(f"{'='*75}\n")

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
                    
                    # For copied cards (like from graveyards), use controller_seat instead of owner_seat
                    # Controller is who actually played/cast the card, owner is the original owner
                    determining_seat = controller_seat if controller_seat is not None else owner_seat
                    
                    # Check if card name is directly available in the log (fallback)
                    # Try ALL possible name fields aggressively
                    card_name_from_log = None
                    for name_field in ["name", "cardName", "titleId", "displayName", "title", "cardTitle"]:
                        if name_field in card_obj:
                            potential_name = card_obj.get(name_field)
                            if potential_name and isinstance(potential_name, str) and not potential_name.isdigit() and len(potential_name) > 1:
                                card_name_from_log = potential_name
                                break
                    
                    # #region agent log
                    import json as json_module
                    in_cache = grp_id in self.card_db.cache if grp_id else False
                    cached_value = self.card_db.cache.get(grp_id) if grp_id else None
                    # Log available fields for debugging
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"CARD_FIELDS","location":"tracker.py:card_play","message":"Card object fields","data":{"grp_id":grp_id,"available_fields":list(card_obj.keys())[:20],"has_name":"name" in card_obj,"has_cardName":"cardName" in card_obj,"has_titleId":"titleId" in card_obj},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    
                    # Try to get card name - use log name as fallback if API fails
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    
                    # If API lookup failed and we have a name from the log, use it
                    if card_name.startswith("Card #") and card_name_from_log:
                        card_name = card_name_from_log
                        # Cache it for future use
                        if grp_id:
                            self.card_db.cache[grp_id] = card_name
                            self.card_db._save_cache()
                            # Also add to log cache for future lookups
                            if hasattr(self.card_db, 'log_cache'):
                                self.card_db.log_cache[grp_id] = card_name
                    
                    # If still no name, try overlayGrpId as fallback (e.g. "Through the Omenpaths"
                    # cards may use one ID in-print and overlayGrpId in MTGA; overlayGrpId often
                    # matches DB sources like 17Lands).
                    if card_name.startswith("Card #") and card_obj:
                        overlay_grp_id = card_obj.get("overlayGrpId")
                        if overlay_grp_id is not None:
                            try:
                                overlay_id_int = int(overlay_grp_id)
                                overlay_name = self.card_db.get_card_name(overlay_id_int)
                                if overlay_name and not overlay_name.startswith("Card #"):
                                    card_name = overlay_name
                                    if grp_id:
                                        self.card_db.cache[grp_id] = card_name
                                        self.card_db._save_cache()
                                        if hasattr(self.card_db, 'log_cache'):
                                            self.card_db.log_cache[grp_id] = card_name
                                    # Also cache overlayGrpId so future lookups by it hit cache
                                    self.card_db.cache[overlay_id_int] = card_name
                                    self.card_db._save_cache()
                            except (ValueError, TypeError):
                                pass
                    # If still no name, try to extract from the card_obj itself more aggressively
                    if card_name.startswith("Card #") and card_obj:
                        # Check all possible name fields in card_obj
                        for name_field in ["name", "cardName", "titleId", "displayName", "title", "cardTitle"]:
                            if name_field in card_obj:
                                potential_name = card_obj.get(name_field)
                                if potential_name and isinstance(potential_name, str) and not potential_name.isdigit() and len(potential_name) > 1:
                                    card_name = potential_name
                                    if grp_id:
                                        self.card_db.cache[grp_id] = card_name
                                        self.card_db._save_cache()
                                        if hasattr(self.card_db, 'log_cache'):
                                            self.card_db.log_cache[grp_id] = card_name
                                    break
                    
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"R","location":"tracker.py:580","message":"Card name lookup","data":{"grp_id":grp_id,"card_name":card_name,"in_cache":in_cache,"cached_value":cached_value,"cache_size":len(self.card_db.cache),"used_log_name":card_name == card_name_from_log if card_name_from_log else False},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion
                    # #region agent log
                    try:
                        with open(DEBUG_LOG_PATH_STR, 'a') as f:
                            f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"O","location":"tracker.py:590","message":"Card play detected","data":{"card_name":card_name,"grp_id":grp_id,"owner_seat":owner_seat,"controller_seat":controller_seat,"determining_seat":determining_seat,"player_seat_id":self.game_state.player_seat_id,"opponent_seat_id":self.game_state.opponent_seat_id,"category":category,"owner_matches_player":owner_seat==self.game_state.player_seat_id,"controller_matches_player":controller_seat==self.game_state.player_seat_id if controller_seat else None,"determining_matches_player":determining_seat==self.game_state.player_seat_id},"timestamp":__import__('time').time()*1000})+'\n')
                    except: pass
                    # #endregion

                    player = "You" if determining_seat == self.game_state.player_seat_id else "Opponent"
                    player_symbol = ">" if determining_seat == self.game_state.player_seat_id else " "
                    if determining_seat == self.game_state.opponent_seat_id:
                        self._flush_pending_opponent_turn_header()

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
                    # For player actions, use last_player_turn_number so late-arriving events (e.g. play land) aren't attributed to the next turn
                    turn_for_display = (
                        self.game_state.last_player_turn_number
                        if owner_seat == self.game_state.player_seat_id
                        else self.game_state.last_turn_announced
                    )
                    turn_prefix = f"[Turn {turn_for_display}] " if turn_for_display > 0 else ""
                    if category == "PlayLand":
                        land_symbol = "⛰️" if owner_seat == self.game_state.player_seat_id else "⛰️"
                        print(f"{turn_prefix}{land_symbol} {player:8} played [{card_name} ({type_str})]")
                    elif "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        print(f"{turn_prefix}{player_symbol} {player:8} cast [{card_name} ({type_str} {power}/{toughness})]{target_str}")
                    else:
                        print(f"{turn_prefix}{player_symbol} {player:8} cast [{card_name} ({type_str})]{target_str}")
                    
                    # Small delay to make output more readable
                    import time
                    time.sleep(0.1)

                    # Track the event using same format as turn log: "Card Name (Type P/T)" or "Card Name (Type)"
                    if "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        track_name = f"{card_name} ({type_str} {power}/{toughness})"
                    else:
                        track_name = f"{card_name} ({type_str})"
                    if card_name.isdigit() or card_name.startswith("Card #"):
                        # #region agent log
                        try:
                            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"UNKNOWN_CARD","location":"tracker.py:card_tracking","message":"Tracking unidentified card with fallback name","data":{"grp_id":grp_id,"card_name":card_name,"track_name":track_name},"timestamp":__import__('time').time()*1000})+'\n')
                        except: pass
                        # #endregion
                    type_category = self._get_card_type_category(card_types)
                    event = CardEvent(track_name, player.lower(), card_type_category=type_category)
                    if determining_seat == self.game_state.player_seat_id:
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
                    if owner_seat == self.game_state.opponent_seat_id:
                        self._flush_pending_opponent_turn_header()

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
                    print(f"{icon} [{card_name}] ({owner_label}) was {action}")

            # Counter spells
            elif category == "Countered":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    if owner_seat == self.game_state.opponent_seat_id:
                        self._flush_pending_opponent_turn_header()
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    owner_label = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    print(f"🚫 [{card_name}] ({owner_label}) was countered")

            # Draw cards
            elif category == "Draw":
                if card_obj:
                    owner_seat = card_obj.get("ownerSeatId")
                    if owner_seat == self.game_state.opponent_seat_id:
                        self._flush_pending_opponent_turn_header()
                    player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    print(f"📥 {player:8} drew a card")

            # Mill effects
            elif category == "Mill":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    if owner_seat == self.game_state.opponent_seat_id:
                        self._flush_pending_opponent_turn_header()
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                    print(f"🌊 {player:8} milled [{card_name}]")

        # Handle resolution annotations
        elif "AnnotationType_ResolutionStart" in ann_type:
            # This tracks when spells resolve - useful for seeing instants resolve
            pass  # Can be used for more detailed instant tracking

        elif "AnnotationType_Scry" in ann_type:
            # Scry events - show when players scry
            if affected_ids and card_obj:
                owner_seat = card_obj.get("ownerSeatId")
                if owner_seat == self.game_state.opponent_seat_id:
                    self._flush_pending_opponent_turn_header()
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

    def _get_card_type_category(self, card_types: List[str]) -> str:
        """Return a single category for breakdown: Land, Creature, Instant, Sorcery, Enchantment, Artifact, Planeswalker, or Other."""
        if not card_types:
            return "Other"
        types = [t.replace("CardType_", "") for t in card_types]
        for cat in ["Land", "Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker"]:
            if cat in types:
                return cat
        return "Other"

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

                        if owner_seat == self.game_state.opponent_seat_id:
                            self._flush_pending_opponent_turn_header()
                        player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                        player_symbol = "⚔️" if owner_seat == self.game_state.player_seat_id else "🗡️"

                        print(f"{player_symbol} {player:8} attacking with [{card_name} ({power}/{toughness})]")
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
            if blocker_owner_seat == self.game_state.opponent_seat_id:
                self._flush_pending_opponent_turn_header()
            player = "You" if blocker_owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "🛡️"

            if attacker_name != "Unknown":
                print(f"{player_symbol} {player:8} blocking [{attacker_name}] with [{blocker_name} ({blocker_pt})]")
            else:
                print(f"{player_symbol} {player:8} blocking with [{blocker_name} ({blocker_pt})]")

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
                        if owner_seat == self.game_state.opponent_seat_id:
                            self._flush_pending_opponent_turn_header()
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
                                print(f"⚔️ Combat: [{source_name}] dealt {damage_amount} damage to [{card_name}] ({owner})")
                            else:
                                print(f"⚔️ Combat: [{card_name}] ({owner}) took {damage_amount} damage")
                        else:
                            print(f"💢 [{card_name}] ({owner}) took {damage_amount} damage")
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
            if owner_seat == self.game_state.opponent_seat_id:
                self._flush_pending_opponent_turn_header()
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
            
            print(f"{player_symbol} {player:8} activated ability: [{card_name}] ({'your' if owner_seat == self.game_state.player_seat_id else 'opponent\'s'}){target_str}")

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
            if owner_seat == self.game_state.opponent_seat_id:
                self._flush_pending_opponent_turn_header()
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            
            player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "✨"
            
            trigger_desc = trigger_type if trigger_type else "triggered"
            print(f"{player_symbol} Triggered: [{card_name}] ({'your' if owner_seat == self.game_state.player_seat_id else 'opponent\'s'}) - {trigger_desc}")

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
        
        print("\n" + "="*75)
        print(f"🏁 🏁 🏁 GAME ENDED 🏁 🏁 🏁")
        print("="*75)

        # Calculate game time
        if self.game_state.game_start_time and self.game_state.game_end_time:
            duration = self.game_state.game_end_time - self.game_state.game_start_time
            minutes = int(duration.total_seconds() // 60)
            seconds = int(duration.total_seconds() % 60)
            print(f"\n⏱️  Game Duration: {minutes}m {seconds}s")

        # Winner - MAKE THIS VERY PROMINENT
        print("\n" + "="*75)
        # #region agent log
        import json as json_module
        try:
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
                f.write(json_module.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"W","location":"tracker.py:900","message":"Printing game summary","data":{"winner_seat":self.game_state.winner_seat,"player_seat_id":self.game_state.player_seat_id,"opponent_seat_id":self.game_state.opponent_seat_id,"player_life":self.game_state.player_life,"opponent_life":self.game_state.opponent_life,"match_type":self.game_state.match_type,"game_number":self.game_state.game_number},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        
        # 1) Someone at 0 life = that player lost (definitive).
        # 2) winner_seat set from log (concede/leave) = use it. Concede = loss for the conceder.
        # 3) Else show result from life totals only (no guessing who conceded).
        pl, ol = self.game_state.player_life, self.game_state.opponent_life
        if pl <= 0:
            print("💀💀💀 YOU LOST THIS GAME 💀💀💀")
            print("   (You reached 0 life)")
        elif ol <= 0:
            print("🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉")
            print("   (Opponent reached 0 life)")
        elif self.game_state.winner_seat is not None:
            if self.game_state.winner_seat == self.game_state.player_seat_id:
                print("🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉")
                print("   (Opponent conceded/disconnected)")
            else:
                print("💀💀💀 YOU LOST THIS GAME 💀💀💀")
                print("   (You conceded/left the game)")
        else:
            # No winner_seat from log; both have life > 0 — could be concede/disconnect. Don't infer you won.
            print("🏁 Game ended")
            print(f"   (Life totals: You {pl} - {ol} Opponent)")
            print("   (Result unclear — possible concede or disconnect)")
        
        # Show best-of-3 match status if applicable
        if self.game_state.match_type == "best_of_3":
            print("\n" + "="*75)
            print(f"📊 Best-of-3 Match Status:")
            print(f"   Game {self.game_state.game_number} of 3")
            if self.match_games:
                print(f"   Previous games:")
                for game in self.match_games:
                    game_winner = "You" if game["winner"] == self.game_state.player_seat_id else "Opponent"
                    print(f"      Game {game['game_number']}: {game_winner} won")
            print("="*75)
        
        print("="*75)

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
        if is_deck_llm_enabled() and self.opponent_cards:
            card_names = [e.card_name for e in self.opponent_cards]
            archetype = identify_deck(card_names)
            if archetype:
                print(f"   Opponent deck: {archetype}")
            else:
                d = deck_llm_diagnose()
                if not d.get("has_api_key"):
                    key_name = {"gemini": "GEMINI_API_KEY", "openai": "CHATGPT_API_KEY", "claude": "CLAUDE_API_KEY"}.get(d.get("provider") or "gemini", "GEMINI_API_KEY")
                    print(f"   Opponent deck: (LLM: no API key — set {key_name} in config.py or env)")
                else:
                    print(f"   Opponent deck: (LLM: request failed — check key/network)")

        if self.player_cards:
            print(f"\n   🎯 Your Cards:")
            print(f"      {self._format_type_breakdown(self.player_cards)}")
            card_counts = {}
            for event in self.player_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    print(f"      • [{card_name_str}] x{count}")
                else:
                    print(f"      • [{card_name_str}]")

        if self.opponent_cards:
            print(f"\n   👤 Opponent's Cards:")
            print(f"      {self._format_type_breakdown(self.opponent_cards)}")
            card_counts = {}
            for event in self.opponent_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    print(f"      • [{card_name_str}] x{count}")
                else:
                    print(f"      • [{card_name_str}]")

        print("\n" + "="*75)
        print("Ready for next game...\n")

        # Reset game state for next game
        self.game_state.reset()

    def _print_summary(self):
        """Print a summary of tracked cards."""
        print()
        print("📊 Session Summary")
        print("=" * 75)

        if not self.game_state.in_match and not self.player_cards:
            print("   No matches tracked this session.")
            print("   Make sure to start the tracker before playing a game!")
            return

        print(f"   Final Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
        print(f"   Turns Played: {self.game_state.turn_number}")
        # #region agent log
        import json as json_module
        try:
            with open(DEBUG_LOG_PATH_STR, 'a') as f:
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
            print(f"      {self._format_type_breakdown(self.player_cards)}")
            # Count duplicates
            card_counts = {}
            for event in self.player_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    print(f"      • [{card_name_str}] x{count}")
                else:
                    print(f"      • [{card_name_str}]")

        if self.opponent_cards:
            print(f"\n   👤 Opponent's Cards This Game:")
            print(f"      {self._format_type_breakdown(self.opponent_cards)}")
            # Count duplicates
            card_counts = {}
            for event in self.opponent_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    print(f"      • [{card_name_str}] x{count}")
                else:
                    print(f"      • [{card_name_str}]")

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
