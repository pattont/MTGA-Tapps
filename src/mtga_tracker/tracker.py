"""Card tracking module.

Tracks cards played by the player and opponents.
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from .log_parser import MTGALogParser
from .card_database import CardDatabase
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
        self.last_opponent_turn_number = 0  # Turn number when it was last the opponent's turn

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
        self._hand_before_mulligan_ids: List[int] = []
        self.opening_hand_capture_closed = False  # Stop opening-hand inference once gameplay actions begin.
        self.opening_mulligan_prompt_seen = False  # True when mulligan prompt markers are observed in the log.
        self.instance_roots: Dict[int, int] = {}  # objectIdChanged lineage map (new_id -> canonical root id).
        self.pending_spell_roots: Dict[int, Dict[str, Any]] = {}  # CastSpell seen, waiting for Resolve.

        # Combat tracking
        self.attackers: List[int] = []  # Instance IDs of attacking creatures
        self.blockers: Dict[int, List[int]] = {}  # blocker_id: [attacker_ids]
        self.combat_phase_active: bool = False  # Track if we're in combat phase
        self.current_combat_attackers: Dict[int, Dict] = {}  # instance_id -> {card_name, power, toughness, target}
        self.combat_damage_events: List[Dict] = []  # Track combat damage for summary
        self.reported_block_pairs: Set[tuple] = set()  # (turn, blocker_id, attacker_id)
        self.reported_attack_keys: Set[tuple] = set()  # (turn, attacker_instance_id, owner_seat)
        self.recent_combat_returns: List[Dict[str, Any]] = []  # recent "return to hand" records used for combat-swap inference
        self.object_snapshots: Dict[int, Dict[str, Any]] = {}  # last known gameObject payload by instanceId (for late/missing combat refs)

        # Game timing
        self.game_start_time: Optional[datetime] = None
        self.game_end_time: Optional[datetime] = None

        # Match result
        self.winner_seat: Optional[int] = None
        self.winner_priority: int = 0  # Higher priority sources override lower-confidence winner guesses.
        self.winner_reason: str = ""
        
        # Who went first (seat ID of player who went first)
        self.first_player_seat: Optional[int] = None

        # Defer turn headers until we see that side's action (or the following turn), which avoids
        # banners appearing before late-arriving events from the previous turn.
        self.pending_player_turn_header: Optional[tuple] = None  # (turn_num, active_player) or None
        self.pending_opponent_turn_header: Optional[tuple] = None  # (turn_num, active_player) or None

        # Match type tracking
        self.match_type: str = "best_of_1"  # "best_of_1" or "best_of_3"
        self.game_number: int = 1  # Current game number in the match (1, 2, or 3)

        # Match metadata (for display: "Match started", "Format", "Players")
        self.format_str: str = "Unknown"  # e.g. Brawl, Standard (from match room event if available)
        self.player_display_name: Optional[str] = None  # Your screen name from auth (logs), if seen
        self.opponent_display_name: Optional[str] = None  # Opponent name from reservedPlayers if in log
        self.player_deck_name: Optional[str] = None  # Your selected deck name from Courses metadata
        self.player_deck_id: Optional[str] = None  # Deck UUID
        self.player_deck_event_name: Optional[str] = None  # Internal event/queue identifier
        self.player_deck_last_played: Optional[datetime] = None  # LastPlayed attribute (if present)
        self._reserved_players: List[Dict[str, Any]] = []  # reservedPlayers from match room (seat -> name)
        self.player_cards_exiled = 0
        self.opponent_cards_exiled = 0
        self.player_cards_exiled_by_opponent = 0
        self.opponent_cards_exiled_by_player = 0
        self.commanders_by_seat: Dict[int, List[str]] = {}
        self.player_commanders: List[str] = []
        self.opponent_commanders: List[str] = []
        self.player_commanders_announced = False
        self.opponent_commanders_announced = False

    def reset(self):
        """Reset state for a new game while keeping only stable account-level metadata."""
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
        self.session_start_time = datetime.now()
        self.session_games_played = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_unknown = 0
        self.session_player_cards_played = 0
        self.session_opponent_cards_played = 0
        self.session_total_mulligans = 0
        self._session_stats_recorded_this_game = False
        self._deck_candidates: Dict[str, Dict[str, Any]] = {}
        self._metadata_backfilled = False
        self._ansi_reset = "\033[0m"
        self._ansi_styles: Dict[str, str] = {
            "turn": "\033[1;36m",          # bright cyan
            "cast": "\033[0;36m",          # cyan
            "land": "\033[0;32m",          # green
            "attack": "\033[1;31m",        # bright red
            "block": "\033[1;35m",         # bright magenta
            "combat_damage": "\033[0;31m", # red
            "damage": "\033[0;33m",        # yellow
            "ability": "\033[0;34m",       # blue
            "zone": "\033[0;35m",          # magenta
            "counter": "\033[1;33m",       # bright yellow
            "draw": "\033[0;37m",          # white
            "life_gain": "\033[0;32m",     # green
            "life_loss": "\033[0;31m",     # red
        }
        self.use_colors = self._should_use_colors()

    def _should_use_colors(self) -> bool:
        """Return True when ANSI colors should be emitted."""
        if os.getenv("NO_COLOR") is not None:
            return False
        color_env = (os.getenv("MTGA_TRACKER_COLOR") or "").strip().lower()
        if color_env in ("0", "false", "no", "off"):
            return False
        if color_env in ("1", "true", "yes", "on", "always"):
            return True
        if os.getenv("FORCE_COLOR"):
            return True
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _style(self, text: str, style: Optional[str] = None) -> str:
        """Apply ANSI style if enabled."""
        if not style or not self.use_colors:
            return text
        prefix = self._ansi_styles.get(style)
        if not prefix:
            return text
        return f"{prefix}{text}{self._ansi_reset}"

    def _print_event(self, text: str, style: Optional[str] = None) -> None:
        """Print an event line with optional style."""
        print(self._style(text, style))

    @staticmethod
    def _turn_prefix_for_number(turn_num: Optional[int]) -> str:
        """Return '[Turn N] ' when turn number is known."""
        if turn_num and int(turn_num) > 0:
            return f"[Turn {int(turn_num)}] "
        return ""

    def _seat_label(self, seat_id: Optional[int]) -> str:
        """Map seat id to display actor label."""
        if seat_id == self.game_state.player_seat_id:
            return "You"
        if seat_id == self.game_state.opponent_seat_id:
            return "Opponent"
        return "Unknown"

    def _turn_for_seat(self, seat_id: Optional[int]) -> int:
        """Best-effort turn number for events attributed to a seat."""
        if seat_id == self.game_state.player_seat_id:
            return self.game_state.last_player_turn_number or self.game_state.last_turn_announced
        if seat_id == self.game_state.opponent_seat_id:
            return self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced
        return self.game_state.last_turn_announced

    def _event_turn_number(self, seat_id: Optional[int], preferred_turn: Optional[int] = None) -> int:
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
        return f"{turn_prefix}{icon} {self._seat_label(seat_id)}: {text}"

    def _ensure_turn_header_for_event(self, seat_id: Optional[int], turn_num: Optional[int]) -> None:
        """Ensure first missing turn header appears when the first stamped event arrives."""
        if not turn_num or turn_num <= 0:
            return
        if seat_id not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return

        if seat_id == self.game_state.player_seat_id and self.game_state.pending_player_turn_header:
            self._flush_pending_player_turn_header()
            return
        if seat_id == self.game_state.opponent_seat_id and self.game_state.pending_opponent_turn_header:
            self._flush_pending_opponent_turn_header()
            return

        if self.game_state.last_turn_announced == 0:
            if seat_id == self.game_state.player_seat_id:
                self.game_state.pending_player_turn_header = (turn_num, seat_id)
                self._flush_pending_player_turn_header()
            else:
                self.game_state.pending_opponent_turn_header = (turn_num, seat_id)
                self._flush_pending_opponent_turn_header()

    def _should_announce_attack(self, turn_num: int, instance_id: Optional[int], owner_seat: Optional[int]) -> bool:
        """Return True if this attacker for this turn has not already been announced."""
        if not turn_num or turn_num <= 0 or instance_id is None:
            return True
        key = (int(turn_num), int(instance_id), owner_seat)
        if key in self.game_state.reported_attack_keys:
            return False
        self.game_state.reported_attack_keys.add(key)
        return True

    @staticmethod
    def _extract_stat_value(value: Any) -> Optional[int]:
        """Extract integer stat value from MTGA stat objects."""
        if isinstance(value, int):
            return value
        if isinstance(value, dict):
            inner = value.get("value")
            if isinstance(inner, int):
                return inner
        return None

    def _snapshot_game_objects(self, game_objects: List[Dict[str, Any]]) -> None:
        """Persist latest known gameObject fields for later combat/summary lookups."""
        max_snapshots = 4000
        trim_batch = 200
        for obj in game_objects:
            if not isinstance(obj, dict):
                continue
            instance_id = obj.get("instanceId")
            if instance_id is None:
                continue
            snap = self.game_state.object_snapshots.get(instance_id, {}).copy()
            snap.update({k: v for k, v in obj.items() if v is not None})
            self.game_state.object_snapshots[instance_id] = snap
        # Keep snapshot map bounded across long sessions.
        if len(self.game_state.object_snapshots) > max_snapshots:
            for old_id in list(self.game_state.object_snapshots.keys())[:trim_batch]:
                self.game_state.object_snapshots.pop(old_id, None)

    def _lookup_object(self, instance_id: Optional[int], game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Get best-known object payload from current state + snapshot fallback."""
        if instance_id is None:
            return {}
        canonical_id = self._canonical_instance_id(instance_id)
        current_obj = (game_objects_by_id or {}).get(instance_id) or {}
        snapshot_obj = self.game_state.object_snapshots.get(instance_id) or {}
        if canonical_id is not None and canonical_id != instance_id:
            canonical_current = (game_objects_by_id or {}).get(canonical_id) or {}
            canonical_snapshot = self.game_state.object_snapshots.get(canonical_id) or {}
        else:
            canonical_current = {}
            canonical_snapshot = {}
        merged = canonical_snapshot.copy()
        merged.update(canonical_current)
        merged.update(snapshot_obj)
        merged.update(current_obj)
        return merged

    def _canonical_instance_id(self, instance_id: Optional[int]) -> Optional[int]:
        """Resolve instance id to canonical root id across ObjectIdChanged events."""
        if instance_id is None:
            return None
        current = int(instance_id)
        seen: Set[int] = set()
        while current in self.game_state.instance_roots and current not in seen:
            seen.add(current)
            parent = self.game_state.instance_roots.get(current)
            if parent is None:
                break
            current = int(parent)
        return current

    def _record_object_id_change(self, orig_id: Optional[int], new_id: Optional[int]) -> None:
        """Track object id remaps so cast/resolve stages can be deduped as one spell."""
        if orig_id is None or new_id is None:
            return
        orig_root = self._canonical_instance_id(orig_id) or int(orig_id)
        self.game_state.instance_roots[int(orig_id)] = orig_root
        self.game_state.instance_roots[int(new_id)] = orig_root

    def _object_display_name(self, obj: Dict[str, Any], instance_id: Optional[int]) -> str:
        """Return best-effort card/permanent display name for a game object."""
        grp_id = obj.get("grpId") or obj.get("overlayGrpId") or obj.get("objectSourceGrpId")
        if grp_id:
            name = self.card_db.get_card_name(grp_id)
            if name:
                return name
        return f"ID {instance_id}" if instance_id is not None else "Unknown"

    def _object_pt(self, obj: Dict[str, Any]) -> str:
        """Return creature stats as P/T when available."""
        p = self._extract_stat_value(obj.get("power"))
        t = self._extract_stat_value(obj.get("toughness"))
        if p is not None and t is not None:
            return f"{p}/{t}"
        return "?/?"

    def _highest_known_creature_snapshot(self, seat_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Return highest P/T creature snapshot seen this game (optionally filtered by owner seat)."""
        best: Optional[Dict[str, Any]] = None
        for instance_id, obj in self.game_state.object_snapshots.items():
            if not isinstance(obj, dict):
                continue
            if seat_id in (1, 2) and obj.get("ownerSeatId") != seat_id:
                continue
            card_types = obj.get("cardTypes")
            if isinstance(card_types, list):
                if "CardType_Creature" not in card_types:
                    continue
            else:
                # If card types are missing, skip to avoid false positives.
                continue
            p = self._extract_stat_value(obj.get("power"))
            t = self._extract_stat_value(obj.get("toughness"))
            if p is None or t is None:
                continue
            score = max(p, t)
            if best is None or score > best["score"]:
                best = {
                    "instance_id": instance_id,
                    "name": self._object_display_name(obj, instance_id),
                    "power": p,
                    "toughness": t,
                    "owner_seat": obj.get("ownerSeatId"),
                    "score": score,
                }
        return best

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
        """Return tracker runtime string."""
        return self._format_duration((datetime.now() - self.session_start_time).total_seconds())

    def _session_stats_line(self) -> str:
        """Return one-line session W/L stats."""
        known_results = self.session_wins + self.session_losses
        win_rate = (self.session_wins / known_results * 100.0) if known_results > 0 else 0.0
        unknown_part = f", ?:{self.session_unknown}" if self.session_unknown else ""
        return (
            f"W:{self.session_wins} L:{self.session_losses}{unknown_part} | "
            f"Games:{self.session_games_played} | WR:{win_rate:.1f}% | Runtime:{self._session_runtime_str()}"
        )

    @staticmethod
    def _unique_names(names: List[str]) -> List[str]:
        """Return ordered unique non-empty names."""
        out: List[str] = []
        seen: Set[str] = set()
        for name in names:
            if not isinstance(name, str):
                continue
            clean = name.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            out.append(clean)
        return out

    def _format_commander_names(self, names: List[str]) -> str:
        """Format one or two commander names for display."""
        unique = self._unique_names(names)
        return " + ".join(unique) if unique else "Unknown"

    def _set_player_commanders_from_ids(self, command_zone_ids: List[int]) -> None:
        """Store player's commander names from deck metadata command zone ids."""
        names = self._unique_names(
            [self.card_db.get_card_name(int(card_id)) for card_id in command_zone_ids if card_id is not None]
        )
        if names:
            self.game_state.player_commanders = names

    def _sync_commander_views_from_seats(self) -> None:
        """Sync player/opponent commander lists from seat-indexed commander map."""
        g = self.game_state
        if g.player_seat_id in g.commanders_by_seat:
            g.player_commanders = self._unique_names(g.commanders_by_seat[g.player_seat_id])
        if g.opponent_seat_id in g.commanders_by_seat:
            g.opponent_commanders = self._unique_names(g.commanders_by_seat[g.opponent_seat_id])

    def _best_brawl_format_label(self) -> str:
        """Return best Brawl label based on known metadata."""
        candidates = [self.game_state.format_str, self.game_state.player_deck_event_name]
        for candidate in self._deck_candidates.values():
            candidates.append(candidate.get("format_attr"))
            candidates.append(candidate.get("internal_event_name"))
        for raw in candidates:
            text = self._normalize_match_text(raw)
            if not text:
                continue
            if "historicbrawl" in text:
                return "Historic Brawl"
            if "brawl" in text:
                return "Brawl"
        return "Brawl"

    def _update_format_from_game_state(self, data: Dict[str, Any]) -> None:
        """Infer Brawl/Historic Brawl from live game state."""
        game_info = data.get("gameInfo")
        variant_text = ""
        if isinstance(game_info, dict):
            variant = game_info.get("variant")
            if isinstance(variant, str):
                variant_text = self._normalize_match_text(variant)
        deck_constraint = data.get("deckConstraintInfo")
        min_commander_size = None
        if isinstance(deck_constraint, dict):
            min_commander_size = deck_constraint.get("minCommanderSize")
        zones = data.get("zones", [])
        has_command_zone = any(
            isinstance(zone, dict) and zone.get("type") == "ZoneType_Command"
            for zone in zones
        ) if isinstance(zones, list) else False

        if "brawl" in variant_text or (isinstance(min_commander_size, int) and min_commander_size > 0) or has_command_zone:
            self.game_state.format_str = self._best_brawl_format_label()

    def _update_commanders_from_game_state(self, data: Dict[str, Any]) -> None:
        """Capture visible commanders from the shared command zone."""
        zones = data.get("zones", [])
        if not isinstance(zones, list):
            return

        game_objects = data.get("gameObjects", [])
        game_objects_by_id = {
            obj.get("instanceId"): obj
            for obj in game_objects
            if isinstance(obj, dict) and obj.get("instanceId") is not None
        }

        command_by_seat: Dict[int, List[str]] = {}
        for zone in zones:
            if not isinstance(zone, dict) or zone.get("type") != "ZoneType_Command":
                continue
            for obj_id in zone.get("objectInstanceIds", []) or []:
                obj = self._lookup_object(obj_id, game_objects_by_id)
                owner_seat = obj.get("ownerSeatId")
                grp_id = obj.get("grpId") or obj.get("overlayGrpId") or obj.get("objectSourceGrpId")
                if owner_seat is None or grp_id is None:
                    continue
                command_by_seat.setdefault(int(owner_seat), []).append(self.card_db.get_card_name(int(grp_id)))

        if not command_by_seat:
            return

        self.game_state.commanders_by_seat = {
            seat: self._unique_names(names)
            for seat, names in command_by_seat.items()
            if self._unique_names(names)
        }

        if self.game_state.player_seat_id not in (1, 2) and self.game_state.player_commanders:
            player_commander_names = set(self._unique_names(self.game_state.player_commanders))
            matching_seats = [
                seat for seat, names in self.game_state.commanders_by_seat.items()
                if set(names) == player_commander_names
            ]
            if len(matching_seats) == 1:
                self.game_state.player_seat_id = matching_seats[0]
                other_seats = [seat for seat in self.game_state.commanders_by_seat.keys() if seat != matching_seats[0]]
                if len(other_seats) == 1:
                    self.game_state.opponent_seat_id = other_seats[0]

        if self.game_state.player_seat_id in (1, 2) and self.game_state.opponent_seat_id not in (1, 2):
            other_seats = [seat for seat in self.game_state.commanders_by_seat.keys() if seat != self.game_state.player_seat_id]
            if len(other_seats) == 1:
                self.game_state.opponent_seat_id = other_seats[0]

        self._sync_commander_views_from_seats()
        if self.game_state._reserved_players:
            for r in self.game_state._reserved_players:
                if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                    self.game_state.player_display_name = self.game_state.player_display_name or r["name"]
                elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                    self.game_state.opponent_display_name = r["name"]

    def _maybe_print_pregame_commander_lines(self) -> None:
        """Print commander lines after game start once discovered, before turn banners."""
        if not self.game_state.in_match or self.game_state.last_turn_announced > 0:
            return
        if self.game_state.player_commanders and not self.game_state.player_commanders_announced:
            print(f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}")
            self.game_state.player_commanders_announced = True
        if self.game_state.opponent_commanders and not self.game_state.opponent_commanders_announced:
            print(f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}")
            self.game_state.opponent_commanders_announced = True

    def _maybe_print_seat_resolution(self) -> None:
        """Print seat resolution once if it becomes known after the start block."""
        if (
            not self.game_state.in_match
            or self.game_state.last_turn_announced > 0
            or self.game_state.game_start_time is None
        ):
            return
        if self.game_state.player_seat_id in (1, 2):
            print(f"   Seat: {self.game_state.player_seat_id}")

    def _print_startup_legend(self) -> None:
        """Print a short event color legend."""
        print("   Event Colors:")
        self._print_event("     ⚔️ Attack / Combat Damage", "attack")
        self._print_event("     🛡️ Block", "block")
        self._print_event("     > / cast", "cast")
        self._print_event("     ⛰️ Land", "land")
        self._print_event("     🔮/✨ Ability", "ability")
        self._print_event("     💚/💔 Life Change", "life_gain")
        if not self.use_colors:
            print("     (Color is off; set MTGA_TRACKER_COLOR=1 to force)")

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
        self._print_startup_legend()
        self._print_event(f"📈 Session: {self._session_stats_line()}", "turn")

        # print("\n   Waiting for game events...")
        print("\n   Play a game in MTGA to see cards tracked in real-time!")
        print("\n   Press Ctrl+C to stop")
        print("=" * 75 + "\n")

        # Deck metadata is often logged before startup; backfill from recent lines once.
        self._backfill_recent_match_metadata()

        # Start from current end of file
        self.parser.reset_position()
        
        # Check if we're launching mid-game
        self._check_if_mid_game()
        
        
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
        self._session_stats_recorded_this_game = False


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

    @staticmethod
    def _normalize_seat_id(value: Any) -> Optional[int]:
        """Convert seat/team IDs to 1/2 when possible."""
        try:
            seat = int(value)
        except (TypeError, ValueError):
            return None
        return seat if seat in (1, 2) else None

    def _set_winner_seat(self, seat_id: Any, *, reason: str, priority: int) -> bool:
        """Set winner seat if source priority is strong enough.

        Priority guide:
          4: Structured game-over JSON (authoritative)
          2: Seat-specific concede / generic JSON hints
          1: Text heuristics (left/disconnect/concede phrases)
        """
        seat = self._normalize_seat_id(seat_id)
        if seat is None:
            return False

        current = self.game_state.winner_seat
        current_priority = getattr(self.game_state, "winner_priority", 0)

        # Never let weaker evidence override stronger evidence.
        if current is not None and priority < current_priority:
            return False

        # Avoid flip-flopping on same-priority contradictory hints.
        if current is not None and priority == current_priority:
            return False

        self.game_state.winner_seat = seat
        self.game_state.winner_priority = priority
        self.game_state.winner_reason = reason


        return True

    def _try_parse_winner_from_json(self, data: Optional[Dict[str, Any]]) -> Optional[int]:
        """Try to get winner seat (1 or 2) from parsed game-end JSON. Returns None if not found."""
        if not data or not isinstance(data, dict):
            return None

        # Winning team/seat (MTGA may use different keys)
        for key in ("winningTeamId", "winningteamid", "winnerSeatId", "winnerSeat", "winningSeatId", "winner"):
            v = self._find_nested(data, key)
            seat = self._normalize_seat_id(v)
            if seat is not None:
                return seat

        # Structured results arrays (most reliable in recent MTGA logs)
        result_entries: List[Dict[str, Any]] = []
        game_info = self._find_nested(data, "gameInfo")
        if isinstance(game_info, dict) and isinstance(game_info.get("results"), list):
            result_entries.extend([r for r in game_info["results"] if isinstance(r, dict)])
        final_match = self._find_nested(data, "finalMatchResult")
        if isinstance(final_match, dict) and isinstance(final_match.get("resultList"), list):
            result_entries.extend([r for r in final_match["resultList"] if isinstance(r, dict)])
        intermission = self._find_nested(data, "intermissionReq")
        if isinstance(intermission, dict) and isinstance(intermission.get("result"), dict):
            result_entries.append(intermission["result"])

        if result_entries:
            scored_winners: List[tuple] = []
            for result in result_entries:
                result_type = str(result.get("result", ""))
                if "WinLoss" not in result_type:
                    continue
                seat = self._normalize_seat_id(
                    result.get("winningTeamId")
                    or result.get("winningteamid")
                    or result.get("winnerSeatId")
                    or result.get("winningSeatId")
                )
                if seat is None:
                    continue
                scope = str(result.get("scope", ""))
                scope_priority = 0 if "MatchScope_Game" in scope else 1 if "MatchScope_Match" in scope else 2
                scored_winners.append((scope_priority, seat))
            if scored_winners:
                scored_winners.sort(key=lambda item: item[0])
                return scored_winners[0][1]

        # Loser seat → winner is the other seat
        loser = self._find_nested(data, "loserSeatId") or self._find_nested(data, "loserSeat")
        loser_seat = self._normalize_seat_id(loser)
        if loser_seat is not None:
            return 2 if loser_seat == 1 else 1

        # Fallback: infer from player statuses (PendingLoss/InGame) at game over.
        players = self._find_nested(data, "players")
        if isinstance(players, list):
            pending_loss_seats: List[int] = []
            in_game_seats: List[int] = []
            for player in players:
                if not isinstance(player, dict):
                    continue
                seat = self._normalize_seat_id(player.get("systemSeatNumber"))
                if seat is None:
                    continue
                status = str(player.get("status", ""))
                if "PendingLoss" in status:
                    pending_loss_seats.append(seat)
                elif "InGame" in status:
                    in_game_seats.append(seat)
            if len(in_game_seats) == 1:
                return in_game_seats[0]
            if len(pending_loss_seats) == 1:
                return 2 if pending_loss_seats[0] == 1 else 1

        # Fallback: infer from team statuses.
        teams = self._find_nested(data, "teams")
        if isinstance(teams, list):
            pending_loss_teams: List[int] = []
            for team in teams:
                if not isinstance(team, dict):
                    continue
                team_id = self._normalize_seat_id(team.get("id"))
                if team_id is None:
                    continue
                if "PendingLoss" in str(team.get("status", "")):
                    pending_loss_teams.append(team_id)
            if len(pending_loss_teams) == 1:
                return 2 if pending_loss_teams[0] == 1 else 1

        return None

    def _check_if_mid_game(self):
        """Only set mid-game if the tail of the log shows an active game and no match-end (lobby = match already ended)."""
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
        for line in self.parser.read_new_lines():
            self._process_line(line)
        # Defer game summary until after all lines processed (so ConcedeReq can set winner before we print)
        if self.game_state.match_complete and self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False

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
        
        # Try to detect player seat if not yet detected
        if self.game_state.player_seat_id is None:
            self._try_detect_player_seat(line)

        # Check for game start
        if not self.game_state.in_match:
            self._check_game_start(line)

        # Check for game end (always call when in_match so ConcedeReq can set winner even after MatchCompleted)
        if self.game_state.in_match:
            self._check_game_end(line)
            # Recent MTGA logs include DeclareBlockersReq; use it for snapshots only (not definitive block output).
            self._process_blocker_requests_from_line(line)

        # Look for card-related events
        event = self.parser.extract_card_events(line)
        if event:
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
        self._maybe_print_seat_resolution()
        self._sync_commander_views_from_seats()
        self._maybe_print_pregame_commander_lines()

    def _get_name_from_dict(self, d: Dict[str, Any]) -> Optional[str]:
        """Get first non-empty string from dict using common name keys (any casing)."""
        if not d or not isinstance(d, dict):
            return None
        for key in ("screenName", "ScreenName", "displayName", "DisplayName", "accountName", "userName", "name"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    @staticmethod
    def _is_localized_placeholder_name(name: Optional[str]) -> bool:
        """Return True for MTGA localization placeholder deck names (e.g. '?=?Loc/...')."""
        if not isinstance(name, str):
            return False
        return name.startswith("?=?Loc/")

    @staticmethod
    def _normalize_match_text(value: Optional[str]) -> str:
        """Normalize strings for loose event/format matching."""
        if not isinstance(value, str):
            return ""
        return "".join(ch for ch in value.lower() if ch.isalnum())

    @staticmethod
    def _parse_attr_timestamp(value: Optional[str]) -> Optional[datetime]:
        """Parse MTGA timestamp attribute values, tolerating wrapped quotes."""
        if not isinstance(value, str):
            return None
        raw = value.strip().strip('"')
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _ingest_course_deck_metadata(self, courses: List[Dict[str, Any]]) -> bool:
        """Capture deck metadata from inventory 'Courses' payloads."""
        if not isinstance(courses, list):
            return False
        now = datetime.now()
        updated = False
        for course in courses:
            if not isinstance(course, dict):
                continue
            summary = course.get("CourseDeckSummary")
            if not isinstance(summary, dict):
                continue
            deck_id = summary.get("DeckId")
            deck_name = summary.get("Name")
            if not deck_id and not deck_name:
                continue

            attrs_raw = summary.get("Attributes")
            attr_map: Dict[str, str] = {}
            if isinstance(attrs_raw, list):
                for attr in attrs_raw:
                    if not isinstance(attr, dict):
                        continue
                    key = attr.get("name")
                    val = attr.get("value")
                    if isinstance(key, str) and isinstance(val, str):
                        attr_map[key] = val

            last_played = self._parse_attr_timestamp(attr_map.get("LastPlayed"))
            key = str(deck_id) if deck_id else f"{course.get('InternalEventName')}::{deck_name}"
            candidate = self._deck_candidates.get(key, {})

            existing_name = candidate.get("deck_name")
            if isinstance(deck_name, str) and deck_name.strip():
                if (
                    not existing_name
                    or (
                        self._is_localized_placeholder_name(existing_name)
                        and not self._is_localized_placeholder_name(deck_name)
                    )
                ):
                    candidate["deck_name"] = deck_name.strip()
                    updated = True

            if isinstance(deck_id, str) and deck_id:
                if candidate.get("deck_id") != deck_id:
                    candidate["deck_id"] = deck_id
                    updated = True

            internal_event = course.get("InternalEventName")
            if isinstance(internal_event, str) and internal_event:
                if candidate.get("internal_event_name") != internal_event:
                    candidate["internal_event_name"] = internal_event
                    updated = True

            module = course.get("CurrentModule")
            if isinstance(module, str) and module:
                if candidate.get("current_module") != module:
                    candidate["current_module"] = module
                    updated = True

            format_attr = attr_map.get("Format")
            if isinstance(format_attr, str) and format_attr:
                if candidate.get("format_attr") != format_attr:
                    candidate["format_attr"] = format_attr
                    updated = True

            course_deck = course.get("CourseDeck")
            if isinstance(course_deck, dict):
                main_deck = course_deck.get("MainDeck")
                if isinstance(main_deck, list):
                    main_ids = {
                        int(entry.get("cardId"))
                        for entry in main_deck
                        if isinstance(entry, dict) and entry.get("cardId") is not None
                    }
                    if main_ids and candidate.get("main_deck_ids") != main_ids:
                        candidate["main_deck_ids"] = main_ids
                        updated = True
                command_zone = course_deck.get("CommandZone")
                if isinstance(command_zone, list):
                    command_zone_ids = [
                        int(entry.get("cardId"))
                        for entry in command_zone
                        if isinstance(entry, dict) and entry.get("cardId") is not None
                    ]
                    if command_zone_ids and candidate.get("command_zone_ids") != command_zone_ids:
                        candidate["command_zone_ids"] = command_zone_ids
                        updated = True

            if last_played is not None:
                existing_last_played = candidate.get("last_played")
                if not isinstance(existing_last_played, datetime) or last_played > existing_last_played:
                    candidate["last_played"] = last_played
                    updated = True

            candidate["last_seen"] = now
            self._deck_candidates[key] = candidate
        return updated

    def _candidate_score(self, candidate: Dict[str, Any], format_hint: str) -> tuple:
        """Return sortable score tuple for selecting likely active deck."""
        score = 0
        deck_name = candidate.get("deck_name")
        if isinstance(deck_name, str) and deck_name and not self._is_localized_placeholder_name(deck_name):
            score += 3
        module = str(candidate.get("current_module", "")).lower()
        if module == "creatematch":
            score += 5
        elif "create" in module:
            score += 3
        elif "match" in module:
            score += 2

        event_norm = self._normalize_match_text(candidate.get("internal_event_name"))
        format_norm = self._normalize_match_text(format_hint)
        format_attr_norm = self._normalize_match_text(candidate.get("format_attr"))

        if format_norm and event_norm:
            if format_norm == event_norm:
                score += 8
            elif format_norm in event_norm or event_norm in format_norm:
                score += 5
            else:
                score -= 2
        if format_norm and format_attr_norm:
            if format_norm == format_attr_norm:
                score += 6
            elif format_norm in format_attr_norm or format_attr_norm in format_norm:
                score += 3
            else:
                score -= 4
            if "bestof3" in format_norm and "traditionalstandard" in format_attr_norm:
                score += 2
            if "bestof1" in format_norm and format_attr_norm == "standard":
                score += 2

        if candidate.get("deck_id") and candidate.get("deck_id") == self.game_state.player_deck_id:
            score += 1

        last_played = candidate.get("last_played")
        last_played_ts = last_played.timestamp() if isinstance(last_played, datetime) else 0.0
        last_seen = candidate.get("last_seen")
        last_seen_ts = last_seen.timestamp() if isinstance(last_seen, datetime) else 0.0
        return (score, last_played_ts, last_seen_ts)

    def _resolve_player_deck_from_candidates(self) -> None:
        """Pick most likely active player deck from observed course metadata."""
        if not self._deck_candidates:
            return
        format_hint = self.game_state.format_str if self.game_state.format_str != "Unknown" else ""
        if not format_hint:
            return
        ranked = sorted(
            self._deck_candidates.values(),
            key=lambda candidate: self._candidate_score(candidate, format_hint),
            reverse=True,
        )
        best = ranked[0]
        best_score = self._candidate_score(best, format_hint)[0]
        second_score = self._candidate_score(ranked[1], format_hint)[0] if len(ranked) > 1 else -999
        if best_score < 6:
            return
        # Avoid locking in a deck when candidates are similarly plausible.
        if (best_score - second_score) < 3:
            return

        self._set_active_deck_from_candidate(best)

    def _set_active_deck_from_candidate(self, candidate: Dict[str, Any]) -> bool:
        """Apply candidate as active deck and report whether it changed."""
        deck_name = candidate.get("deck_name")
        if self._is_localized_placeholder_name(deck_name):
            deck_name = None
        deck_id = candidate.get("deck_id")
        changed = (
            deck_name != self.game_state.player_deck_name
            or deck_id != self.game_state.player_deck_id
        )
        self.game_state.player_deck_name = deck_name
        self.game_state.player_deck_id = deck_id
        self.game_state.player_deck_event_name = candidate.get("internal_event_name")
        self.game_state.player_deck_last_played = candidate.get("last_played")
        command_zone_ids = candidate.get("command_zone_ids")
        if isinstance(command_zone_ids, list):
            self._set_player_commanders_from_ids(command_zone_ids)
        return changed

    def _resolve_player_deck_from_hand_ids(self, hand_grp_ids: List[int]) -> bool:
        """Resolve active deck by matching opening hand grpIds against known candidate main decks."""
        if not hand_grp_ids or not self._deck_candidates:
            return False
        hand_set = {int(grp_id) for grp_id in hand_grp_ids if grp_id}
        if not hand_set:
            return False

        format_hint = self.game_state.format_str if self.game_state.format_str != "Unknown" else ""
        best_candidate: Optional[Dict[str, Any]] = None
        best_key: Optional[tuple] = None
        for candidate in self._deck_candidates.values():
            deck_ids = candidate.get("main_deck_ids")
            if not isinstance(deck_ids, set) or not deck_ids:
                continue
            match_count = len(hand_set & deck_ids)
            if match_count <= 0:
                continue
            confidence = self._candidate_score(candidate, format_hint)
            key = (match_count, confidence[0], confidence[1], confidence[2])
            if best_key is None or key > best_key:
                best_key = key
                best_candidate = candidate

        if not best_candidate or not best_key or best_key[0] < 2:
            return False

        return self._set_active_deck_from_candidate(best_candidate)

    def _resolve_player_deck_fallback(self) -> bool:
        """Pick best-available deck candidate when strict matching could not determine one yet."""
        if not self._deck_candidates:
            return False
        format_hint = self.game_state.format_str if self.game_state.format_str != "Unknown" else ""
        ranked = sorted(
            self._deck_candidates.values(),
            key=lambda candidate: self._candidate_score(candidate, format_hint),
            reverse=True,
        )
        best = ranked[0]
        return self._set_active_deck_from_candidate(best)

    def _backfill_recent_match_metadata(self, max_lines: int = 1200, force: bool = False) -> None:
        """Scan recent log tail so metadata is available even when starting at EOF."""
        if self._metadata_backfilled and not force:
            return
        if not force:
            self._metadata_backfilled = True
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        for raw_line in tail:
            line = raw_line.rstrip("\n")
            if line:
                self._parse_match_metadata(line)

    def _parse_match_metadata(self, line: str) -> None:
        """Extract format, players, and deck metadata from log lines."""
        data = self.parser.parse_json_from_line(line)
        if not data:
            return
        format_updated = False
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
                if self.game_state.format_str != fmt:
                    self.game_state.format_str = fmt
                    format_updated = True
            elif isinstance(fmt, (int, float)):
                fmt_value = str(fmt)
                if self.game_state.format_str != fmt_value:
                    self.game_state.format_str = fmt_value
                    format_updated = True

        courses = self._find_nested(data, "Courses")
        deck_updated = self._ingest_course_deck_metadata(courses) if isinstance(courses, list) else False
        if deck_updated or format_updated:
            self._resolve_player_deck_from_candidates()

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
        opponent_name_known = (
            isinstance(g.opponent_display_name, str)
            and g.opponent_display_name.strip()
            and g.opponent_display_name.strip().lower() != "opponent"
        )
        if opponent_name_known:
            player_label = g.player_display_name or "You"
            print(f"   Players: {player_label} vs {g.opponent_display_name.strip()}")
        if g.player_seat_id in (1, 2):
            print(f"   Seat: {g.player_seat_id}")
        if g.player_commanders:
            print(f"   Your Commander: {self._format_commander_names(g.player_commanders)}")
            g.player_commanders_announced = True
        if g.opponent_commanders:
            print(f"   Opponent Commander: {self._format_commander_names(g.opponent_commanders)}")
            g.opponent_commanders_announced = True

    def _capture_opening_hand(self, data: Dict[str, Any]) -> None:
        """Capture starting hand + mulligan count from early hand-zone snapshots."""
        if self.game_state.starting_hand:
            return
        if self.game_state.opening_hand_capture_closed:
            return
        if self.game_state.turn_number and self.game_state.turn_number > 1:
            self.game_state.opening_hand_capture_closed = True
            return

        zones = data.get("zones", [])
        if not isinstance(zones, list) or not zones:
            return

        game_objects = data.get("gameObjects", [])
        if not isinstance(game_objects, list):
            return
        objects_by_id = {
            obj.get("instanceId"): obj
            for obj in game_objects
            if isinstance(obj, dict) and obj.get("instanceId") is not None
        }
        turn_num = (data.get("turnInfo") or {}).get("turnNumber")
        gameplay_annotations_present = self._has_gameplay_annotations(data)
        mulligan_prompt_present = self._has_mulligan_prompt_in_state(data)

        # Once real gameplay actions appear, stop trying to infer opening hand from shrinking hand size.
        if gameplay_annotations_present:
            self.game_state.opening_hand_capture_closed = True
            return

        def finalize_starting_hand(hand_cards: List[str], hand_grp_ids: List[int]) -> None:
            self.game_state.starting_hand = hand_cards
            self.game_state.initial_hand_size = len(hand_cards)
            self.game_state.mulligan_count = max(self.game_state.mulligan_count, 7 - len(hand_cards))
            self.session_total_mulligans += self.game_state.mulligan_count
            self._resolve_player_deck_from_hand_ids(hand_grp_ids)
            if self.game_state._hand_before_mulligan:
                thrown = [c for c in self.game_state._hand_before_mulligan if c not in hand_cards]
                if thrown:
                    print(f"🔄 Mulliganed away: {', '.join(thrown)}")
            elif len(hand_cards) < 7:
                print(f"🔄 Mulligan to {len(hand_cards)} (mulligans: {self.game_state.mulligan_count})")
            self.game_state._hand_before_mulligan = []
            self.game_state._hand_before_mulligan_ids = []
            self.game_state.opening_hand_capture_closed = True
            n = len(self.game_state.starting_hand)
            print(f"\n🎴 Your Starting Hand ({n} cards):")
            for card in self.game_state.starting_hand:
                print(f"   • {card}")
            print()

        for zone in zones:
            if not isinstance(zone, dict) or zone.get("type") != "ZoneType_Hand":
                continue
            owner_seat = zone.get("ownerSeatId")
            obj_ids = zone.get("objectInstanceIds", [])
            if owner_seat is None or not obj_ids:
                continue

            hand_cards: List[str] = []
            hand_grp_ids: List[int] = []
            for obj_id in obj_ids:
                obj = objects_by_id.get(obj_id) or self.game_state.object_snapshots.get(obj_id) or {}
                grp_id = obj.get("grpId")
                if grp_id:
                    hand_cards.append(self.card_db.get_card_name(grp_id))
                    hand_grp_ids.append(int(grp_id))

            # Opponent hand is hidden (no grpIds), so a visible hand is ours.
            if not hand_grp_ids:
                continue
            # Partial gameState diffs can omit most hand objects; don't finalize from incomplete snapshots.
            if len(hand_grp_ids) < len(obj_ids):
                continue

            if self.game_state.player_seat_id is None:
                self.game_state.player_seat_id = owner_seat
                players = data.get("players", [])
                if isinstance(players, list):
                    seat_ids = [
                        p.get("systemSeatNumber")
                        for p in players
                        if isinstance(p, dict) and p.get("systemSeatNumber") is not None
                    ]
                    for seat_id in seat_ids:
                        if seat_id != owner_seat:
                            self.game_state.opponent_seat_id = seat_id
                            break
                self._maybe_print_seat_resolution()
                self._sync_commander_views_from_seats()

            if owner_seat != self.game_state.player_seat_id:
                continue

            if len(hand_cards) > 7:
                continue

            if len(hand_cards) == 7:
                current_sig = sorted(hand_grp_ids)
                previous_sig = sorted(self.game_state._hand_before_mulligan_ids)
                if not self.game_state._hand_before_mulligan_ids:
                    self.game_state._hand_before_mulligan = hand_cards
                    self.game_state._hand_before_mulligan_ids = hand_grp_ids
                elif current_sig == previous_sig and turn_num and turn_num >= 1:
                    finalize_starting_hand(hand_cards, hand_grp_ids)
                    return
                elif current_sig != previous_sig:
                    self.game_state.mulligan_count += 1
                    self.game_state._hand_before_mulligan = hand_cards
                    self.game_state._hand_before_mulligan_ids = hand_grp_ids
                continue

            # Final kept hand (typically < 7 after London bottoming) finalizes mulligan count.
            can_finalize_short_hand = (
                bool(self.game_state._hand_before_mulligan_ids)
                or mulligan_prompt_present
                or (turn_num in (None, 0, 1) and self.game_state.last_turn_announced == 0)
            )
            if not can_finalize_short_hand:
                continue
            finalize_starting_hand(hand_cards, hand_grp_ids)
            return

    @staticmethod
    def _annotation_category(annotation: Dict[str, Any]) -> Optional[str]:
        """Get zone-transfer category string from one annotation payload."""
        details = annotation.get("details", [])
        if not isinstance(details, list):
            return None
        for detail in details:
            if not isinstance(detail, dict):
                continue
            if detail.get("key") != "category":
                continue
            value = detail.get("valueString", [])
            if isinstance(value, list) and value:
                first = value[0]
                return str(first) if first is not None else None
        return None

    def _has_gameplay_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when annotations indicate gameplay has started (not mulligan setup)."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if any(
                ann in ann_types
                for ann in (
                    "AnnotationType_AttackerDeclared",
                    "AnnotationType_BlockerDeclared",
                    "AnnotationType_Damage",
                    "AnnotationType_DamageDealt",
                )
            ):
                return True
            if "AnnotationType_ZoneTransfer" in ann_types:
                category = self._annotation_category(annotation)
                if category in {
                    "PlayLand",
                    "CastSpell",
                    "PlaySpell",
                    "Resolve",
                    "Draw",
                    "Destroy",
                    "Exile",
                    "Countered",
                    "Sacrifice",
                    "Discard",
                    "Mill",
                }:
                    return True
        return False

    def _has_mulligan_prompt_in_state(self, data: Dict[str, Any]) -> bool:
        """Best-effort signal for mulligan/keep prompt presence in gameState payload."""
        if self.game_state.opening_mulligan_prompt_seen:
            return True
        players = data.get("players", [])
        if not isinstance(players, list):
            return False
        for player in players:
            if not isinstance(player, dict):
                continue
            pending = (
                player.get("pendingMessageType")
                or player.get("pendingMessage")
                or player.get("pendingDecisionType")
            )
            if pending is None:
                continue
            pending_text = str(pending).lower()
            if "mulligan" in pending_text or "choosestartingplayer" in pending_text:
                return True
        return False

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
                self.game_state.opening_mulligan_prompt_seen = True
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
            self._session_stats_recorded_this_game = False
            
        # Only check if we're not already in a match
        if self.game_state.in_match:
            return
            
        line_lower = line.lower()
        
        
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
            self.game_state.opening_hand_capture_closed = False
            self.game_state.opening_mulligan_prompt_seen = True
            self.player_cards = []
            self.opponent_cards = []
            self._session_stats_recorded_this_game = False
            self._deck_candidates = {}
            self.game_state.player_deck_name = None
            self.game_state.player_deck_id = None
            self.game_state.player_deck_event_name = None
            self.game_state.player_deck_last_played = None
            self._backfill_recent_match_metadata(max_lines=1800, force=True)
            format_display = "Standard Best-of-3" if self.game_state.match_type == "best_of_3" else "Standard Best-of-1"
            game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
            print("\n" + "="*75)
            print(f"🎮 🎮 🎮 GAME STARTED 🎮 🎮 🎮")
            print("="*75)
            self._print_match_started_block()
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
                    self.game_state.opening_hand_capture_closed = False
                    self.game_state.opening_mulligan_prompt_seen = False
                    self.player_cards = []
                    self.opponent_cards = []
                    self._session_stats_recorded_this_game = False
                    self._deck_candidates = {}
                    self.game_state.player_deck_name = None
                    self.game_state.player_deck_id = None
                    self.game_state.player_deck_event_name = None
                    self.game_state.player_deck_last_played = None
                    self._backfill_recent_match_metadata(max_lines=1800, force=True)
                    format_display = "Standard Best-of-3" if self.game_state.match_type == "best_of_3" else "Standard Best-of-1"
                    game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
                    print("\n" + "="*75)
                    print(f"🎮 GAME STARTED - {format_display}{game_num_display}")
                    print("="*75)
                    self._print_match_started_block()
                    return  # Don't process further - wait for hand info

            self._capture_opening_hand(data)

    def _check_game_end(self, line: str):
        """Check if the game has ended."""
        if not self.game_state.in_match:
            return
        line_lower = line.lower()

        # Try to get winner from JSON on any line.
        # Structured game-over records are treated as authoritative and get higher priority.
        json_data = self.parser.parse_json_from_line(line)
        structured_match_complete = False
        if json_data:
            game_info = self._find_nested(json_data, "gameInfo")
            if isinstance(game_info, dict):
                stage = str(game_info.get("stage", ""))
                match_state = str(game_info.get("matchState", ""))
                if (
                    "GameStage_GameOver" in stage
                    or "MatchState_GameComplete" in match_state
                    or "MatchState_MatchComplete" in match_state
                ):
                    structured_match_complete = True
            state_type = self._find_nested(json_data, "stateType")
            if isinstance(state_type, str) and "MatchCompleted" in state_type:
                structured_match_complete = True
            if isinstance(self._find_nested(json_data, "intermissionReq"), dict):
                structured_match_complete = True
            w = self._try_parse_winner_from_json(json_data)
            if w is not None:
                winner_priority = 4 if structured_match_complete else 2
                winner_reason = "structured_game_over_json" if structured_match_complete else "json_winner_hint"
                self._set_winner_seat(w, reason=winner_reason, priority=winner_priority)
        
        
        # Check for concede requests - need to check WHO conceded
        # Process even when match_complete so we can set winner_seat before deferred summary
        if "concedereq" in line_lower or "clientmessagetype_concedereq" in line_lower:
            json_data = self.parser.parse_json_from_line(line)
            seat_id = self._find_nested(json_data, "systemSeatId") if json_data else None
            if seat_id is not None:
                if seat_id == self.game_state.player_seat_id:
                    self._set_winner_seat(
                        self.game_state.opponent_seat_id,
                        reason="concede_req:player_conceded",
                        priority=2,
                    )
                elif seat_id == self.game_state.opponent_seat_id:
                    self._set_winner_seat(
                        self.game_state.player_seat_id,
                        reason="concede_req:opponent_conceded",
                        priority=2,
                    )
            if self.game_state.winner_seat is not None and not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self._pending_game_summary = True
                return

        # Structured end-of-game records from current MTGA logs.
        if structured_match_complete and not self.game_state.match_complete:
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
            self._set_winner_seat(
                self.game_state.opponent_seat_id,
                reason="text:player_left_or_forfeited",
                priority=1,
            )
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self._pending_game_summary = True
            return
        
        # Check for match completion state changes - be very specific
        # Only set match_complete here; do NOT set winner_seat (we don't know who won from this line).
        if '"old":"matchcompleted"' in line_lower or '"old":"MatchCompleted"' in line:
            if '"new":"matchcompleted"' in line_lower or '"new":"MatchCompleted"' in line or '"new":"disconnected"' in line_lower:
                if not self.game_state.match_complete:
                    self.game_state.match_complete = True
                    self.game_state.game_end_time = datetime.now()
                    self._pending_game_summary = True
                    return
        
        # Check for opponent leaving/conceding (you win). Always set winner_seat so we overwrite
        # any wrong winner from an earlier generic completion line.
        # Match many phrasings: "opponent left", "opponent has left", "the opponent left", etc.
        opponent_leave_patterns = [
            "opponentleft", "opponent left", "opponent quit", "opponent conceded", "opponent concede",
            "opponent disconnected", "opponent has left", "opponent has conceded", "opponent has disconnected",
            "opponent has quit", "the opponent left", "the opponent concede", "your opponent left",
            "opponent left the", "opponent conceded the", "opponent disconnected from",
        ]
        if any(pattern in line_lower for pattern in opponent_leave_patterns):
            self._set_winner_seat(
                self.game_state.player_seat_id,
                reason="text:opponent_left_or_forfeited",
                priority=1,
            )
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                self._pending_game_summary = True
            return
        
        # Check for game completion messages (try to parse JSON)
        # Structured winner here is authoritative and may override weaker hints.
        if any(pattern in line_lower for pattern in [
            "gamecompletedtype", "finalresults",
            "matchendscene", "on sceneloaded for matchendscene"
        ]):
            json_data = self.parser.parse_json_from_line(line)
            if json_data and not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(json_data, "winningteamid")
                if winner_team is not None and winner_team in (1, 2):
                    self._set_winner_seat(winner_team, reason="game_complete_pattern:winner_team", priority=4)
                self._pending_game_summary = True
                return
        
        # Check for state change FROM "Playing" TO "MatchCompleted" - this is the actual game end
        if '"old":"playing"' in line_lower and '"new":"matchcompleted"' in line_lower:
            if not self.game_state.match_complete:
                self.game_state.match_complete = True
                self.game_state.game_end_time = datetime.now()
                json_data = self.parser.parse_json_from_line(line)
                if json_data:
                    winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(json_data, "winningteamid")
                    if winner_team is not None and winner_team in (1, 2):
                        self._set_winner_seat(winner_team, reason="state_transition:winner_team", priority=4)
                self._pending_game_summary = True
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
        self._capture_opening_hand(event_data)

        # Then process annotations (card plays, etc.) so they appear under the turn header.
        self._process_game_events(event_data)

    def _has_combat_or_damage_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when this payload includes combat/damage annotations."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if any(
                ann in ann_types
                for ann in (
                    "AnnotationType_AttackerDeclared",
                    "AnnotationType_BlockerDeclared",
                    "AnnotationType_Damage",
                    "AnnotationType_DamageDealt",
                )
            ):
                return True
        return False

    def _has_new_turn_action_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when payload likely contains real actions from the newly active turn."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if "AnnotationType_ZoneTransfer" in ann_types:
                category = self._annotation_category(annotation)
                if category in {"PlayLand", "CastSpell", "PlaySpell", "Resolve", "Draw"}:
                    return True
        return False

    def _emit_life_change(
        self,
        seat_id: int,
        diff: int,
        life: int,
        turn_override: Optional[int] = None,
    ) -> None:
        """Print one life-change line with optional turn override for late-arriving events."""
        if not self.game_state.in_match or diff == 0:
            return
        turn_for_display = self._event_turn_number(
            seat_id,
            turn_override if turn_override is not None else (
                self.game_state.turn_number if self.game_state.turn_number > 0 else None
            ),
        )
        late_life_event = (
            self.game_state.turn_number > 0
            and turn_for_display > 0
            and turn_for_display < self.game_state.turn_number
        )
        if not late_life_event:
            self._flush_pending_turn_header_for_seat(seat_id)
        actor = self._seat_label(seat_id)
        turn_prefix = self._turn_prefix_for_number(turn_for_display)
        if diff > 0:
            text = f"{turn_prefix}💚 {actor}: gained {diff} life (now {life})"
            if late_life_event:
                self._print_event(text, "life_gain")
            else:
                self._print_event(
                    self._format_actor_event("💚", seat_id, f"gained {diff} life (now {life})", turn_override=turn_for_display),
                    "life_gain",
                )
        elif diff < 0:
            text = f"{turn_prefix}💔 {actor}: lost {-diff} life (now {life})"
            if late_life_event:
                self._print_event(text, "life_loss")
            else:
                self._print_event(
                    self._format_actor_event("💔", seat_id, f"lost {-diff} life (now {life})", turn_override=turn_for_display),
                    "life_loss",
                )

    def _update_game_state(self, data: Dict[str, Any]):
        """Update the tracked game state from event data."""
        # Process turn info and print turn header FIRST so "Turn N - YOUR TURN" appears
        # before card plays and life changes from this same message.
        self._snapshot_game_objects(data.get("gameObjects", []))
        self._update_format_from_game_state(data)
        self._update_commanders_from_game_state(data)
        self._maybe_print_seat_resolution()
        self._maybe_print_pregame_commander_lines()
        turn_changed = False
        exited_combat_this_update = False
        # Update turn info
        if "turnInfo" in data:
            turn_info = data["turnInfo"]
            turn_num = turn_info.get("turnNumber")
            active_player = turn_info.get("activePlayer")
            phase = turn_info.get("phase", "")
            step = turn_info.get("step", "")

            # Detect new turn - only announce if turn number increased AND active player changed
            # A turn only changes when the active player changes (not just when turn number increments)
            seats_known = (
                self.game_state.player_seat_id in (1, 2)
                and self.game_state.opponent_seat_id in (1, 2)
            )
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

            # If the first observed turn is > 1, call this out so "missing turn 1" is explicit.
            if (
                turn_num is not None
                and turn_num > 2
                and self.game_state.last_turn_announced == 0
                and seats_known
            ):
                missed_turns = list(range(1, turn_num))
                missing_text = ", ".join(str(t) for t in missed_turns[:3])
                if len(missed_turns) > 3:
                    missing_text += ", ..."
                self._print_event(
                    f"⚠️ First observed turn is {turn_num}; earlier turn(s) ({missing_text}) were not present in the captured log stream.",
                    "turn",
                )
            
            # Detect combat phase
            if phase and "Combat" in phase:
                if not self.game_state.combat_phase_active:
                    self.game_state.combat_phase_active = True
                    # Clear previous combat data
                    self.game_state.attackers = []
                    self.game_state.blockers = {}
                    self.game_state.current_combat_attackers = {}
                    self.game_state.combat_damage_events = []
                    self.game_state.reported_block_pairs = set()
                    self.game_state.recent_combat_returns = []
            else:
                # If we were in combat and now we're not, show combat summary
                if self.game_state.combat_phase_active:
                    exited_combat_this_update = True
                    self._display_combat_summary()
                    self.game_state.combat_phase_active = False
                    self.game_state.attackers = []
                    self.game_state.blockers = {}
                    self.game_state.current_combat_attackers = {}
                    self.game_state.combat_damage_events = []
                    self.game_state.reported_block_pairs = set()
                    self.game_state.recent_combat_returns = []
            if turn_changed and turn_num:
                # Drop stale per-turn dedupe keys when turn advances.
                self.game_state.reported_attack_keys = {
                    k for k in self.game_state.reported_attack_keys if isinstance(k, tuple) and k and k[0] >= int(turn_num) - 1
                }
            
            if turn_changed and seats_known:
                
                # Detect who went first (on turn 1)
                if turn_num == 1 and self.game_state.first_player_seat is None and active_player is not None:
                    self.game_state.first_player_seat = active_player

                # Announce turn change
                # Defer both turn headers until we see an action from that side or the next turn.
                if turn_num == 1 and self.game_state.last_turn_announced < 1:
                    if active_player == self.game_state.player_seat_id:
                        self.game_state.pending_player_turn_header = (turn_num, active_player)
                    else:
                        self.game_state.pending_opponent_turn_header = (turn_num, active_player)
                elif turn_num > self.game_state.last_turn_announced:
                    if active_player == self.game_state.player_seat_id:
                        self._flush_pending_opponent_turn_header()
                        self.game_state.pending_player_turn_header = (turn_num, active_player)
                    else:
                        self._flush_pending_player_turn_header()
                        self.game_state.pending_opponent_turn_header = (turn_num, active_player)

        late_life_turn_override: Optional[int] = None
        if (
            turn_changed
            and self.game_state.turn_number > 1
            and (exited_combat_this_update or self._has_combat_or_damage_annotations(data))
            and not self._has_new_turn_action_annotations(data)
        ):
            late_life_turn_override = self.game_state.turn_number - 1

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
                            self._emit_life_change(
                                seat_id,
                                diff,
                                life,
                                turn_override=late_life_turn_override,
                            )
                    elif seat_id == self.game_state.opponent_seat_id:
                        old_life = self.game_state.opponent_life
                        if life != old_life:
                            diff = life - old_life
                            self.game_state.opponent_life = life
                            self._emit_life_change(
                                seat_id,
                                diff,
                                life,
                                turn_override=late_life_turn_override,
                            )

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
        if active_player == self.game_state.opponent_seat_id:
            self.game_state.last_opponent_turn_number = turn_num
        print(f"\n{'='*75}")
        self._print_event(f"⚔️  Turn {turn_num} - OPPONENT'S TURN", "turn")
        print(f"   ❤️ Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
        print(f"{'='*75}\n")

    def _flush_pending_player_turn_header(self) -> None:
        """Print and clear deferred 'Turn N - YOUR TURN' header if set."""
        pending = self.game_state.pending_player_turn_header
        if not pending:
            return
        turn_num, active_player = pending
        self.game_state.pending_player_turn_header = None
        self.game_state.last_turn_announced = turn_num
        if active_player == self.game_state.player_seat_id:
            self.game_state.last_player_turn_number = turn_num
        print(f"\n{'='*75}")
        self._print_event(f"⚔️  Turn {turn_num} - YOUR TURN", "turn")
        print(f"   ❤️ Life: You {self.game_state.player_life} - {self.game_state.opponent_life} Opponent")
        print(f"{'='*75}\n")

    def _flush_pending_turn_header_for_seat(self, seat_id: Optional[int]) -> None:
        """Flush deferred turn header for the side that owns the current event."""
        if seat_id == self.game_state.player_seat_id:
            self._flush_pending_player_turn_header()
        elif seat_id == self.game_state.opponent_seat_id:
            self._flush_pending_opponent_turn_header()

    def _process_game_events(self, data: Dict[str, Any]):
        """Process and display important game events."""
        game_objects = data.get("gameObjects", [])

        # Newer MTGA logs often represent attackers via gameObjects.attackState
        # instead of AnnotationType_AttackerDeclared.
        if game_objects:
            self._handle_attack_state_objects(game_objects)

        # Process annotations for high-level events
        if "annotations" in data:
            for annotation in data["annotations"]:
                self._process_annotation(annotation, game_objects)

    def _resolve_target_label(self, target_id: Optional[int], game_objects_by_id: Dict[int, Dict[str, Any]]) -> Optional[str]:
        """Return display text for attack targets (player or permanent)."""
        if target_id is None:
            return None
        if target_id == self.game_state.player_seat_id:
            return "you"
        if target_id == self.game_state.opponent_seat_id:
            return "opponent"

        target_obj = game_objects_by_id.get(target_id)
        if not target_obj:
            return f"ID {target_id}"

        grp_id = target_obj.get("grpId")
        target_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        owner_seat = target_obj.get("ownerSeatId")
        if owner_seat == self.game_state.player_seat_id:
            owner = "your"
        elif owner_seat == self.game_state.opponent_seat_id:
            owner = "opponent's"
        else:
            owner = "unknown"
        return f"{target_name} ({owner})"

    def _handle_attack_state_objects(self, game_objects: List[Dict[str, Any]]) -> None:
        """Handle combat attacks emitted as gameObjects with attackState."""
        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in game_objects:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                game_objects_by_id[instance_id] = obj

        for obj in game_objects:
            attack_state = str(obj.get("attackState", ""))
            if attack_state not in ("AttackState_Declared", "AttackState_Attacking"):
                continue

            instance_id = obj.get("instanceId")
            if instance_id is None or instance_id in self.game_state.attackers:
                continue
            self.game_state.attackers.append(instance_id)

            grp_id = obj.get("grpId")
            owner_seat = obj.get("ownerSeatId")
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            power = obj.get("power", {}).get("value", "?")
            toughness = obj.get("toughness", {}).get("value", "?")
            target_id = (obj.get("attackInfo") or {}).get("targetId")
            target_label = self._resolve_target_label(target_id, game_objects_by_id)

            self.game_state.current_combat_attackers[instance_id] = {
                "card_name": card_name,
                "power": power,
                "toughness": toughness,
                "owner_seat": owner_seat,
                "target": target_label,
            }

            self._flush_pending_turn_header_for_seat(owner_seat)
            player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "⚔️" if owner_seat == self.game_state.player_seat_id else "🗡️"
            turn_for_display = (
                self.game_state.turn_number
                if owner_seat == self.game_state.active_player and self.game_state.turn_number > 0
                else self._turn_for_seat(owner_seat)
            )
            turn_for_display = self._event_turn_number(owner_seat, turn_for_display)
            if not self._should_announce_attack(turn_for_display, instance_id, owner_seat):
                continue
            self._ensure_turn_header_for_event(owner_seat, turn_for_display)
            turn_prefix = self._turn_prefix_for_number(turn_for_display)

            if target_label:
                self._print_event(
                    f"{turn_prefix}{player_symbol} {player:8} attacking [{target_label}] with [{card_name} ({power}/{toughness})]",
                    "attack",
                )
            else:
                self._print_event(
                    f"{turn_prefix}{player_symbol} {player:8} attacking with [{card_name} ({power}/{toughness})]",
                    "attack",
                )

    def _process_blocker_requests_from_line(self, line: str) -> None:
        """Handle GREMessageType_DeclareBlockersReq events from raw line JSON.

        Note: this message is a *request* to choose blockers, not authoritative proof that
        a block actually happened. We only use it to capture object snapshots for fallback
        card lookups and do not emit block lines from it.
        """
        if "declareblockersreq" not in line.lower():
            return

        data = self.parser.parse_json_from_line(line)
        if not data or not isinstance(data, dict):
            return
        gre_event = data.get("greToClientEvent")
        if not isinstance(gre_event, dict):
            return

        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for message in (gre_event.get("greToClientMessages") or []):
            if not isinstance(message, dict):
                continue
            msg_type = message.get("type")
            if msg_type == "GREMessageType_GameStateMessage":
                game_state = message.get("gameStateMessage") or {}
                game_objects = game_state.get("gameObjects") or []
                self._snapshot_game_objects(game_objects)
                for obj in game_objects:
                    if not isinstance(obj, dict):
                        continue
                    instance_id = obj.get("instanceId")
                    if instance_id is not None:
                        game_objects_by_id[instance_id] = obj

    def _handle_blockers_request(self, blockers: List[Dict[str, Any]], game_objects_by_id: Dict[int, Dict[str, Any]]) -> None:
        """Display blocker mappings from DeclareBlockersReq payloads."""
        for block in blockers:
            if not isinstance(block, dict):
                continue
            blocker_id = block.get("blockerInstanceId")
            if blocker_id is None:
                continue
            attacker_ids = block.get("attackerInstanceIds") or []
            if not isinstance(attacker_ids, list) or not attacker_ids:
                continue

            blocker_obj = self._lookup_object(blocker_id, game_objects_by_id)
            blocker_name = self._object_display_name(blocker_obj, blocker_id)
            blocker_owner_seat = blocker_obj.get("ownerSeatId")
            blocker_pt = self._object_pt(blocker_obj)

            self._flush_pending_turn_header_for_seat(blocker_owner_seat)
            if blocker_owner_seat == self.game_state.player_seat_id:
                player = "You"
            elif blocker_owner_seat == self.game_state.opponent_seat_id:
                player = "Opponent"
            else:
                player = "Unknown"
            player_symbol = "🛡️"
            inferred_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else self._turn_for_seat(blocker_owner_seat)
            for attacker_id in attacker_ids:
                if attacker_id is None:
                    continue
                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_owner_seat = attacker_obj.get("ownerSeatId")
                if attacker_owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                    inferred_turn = self._turn_for_seat(attacker_owner_seat) or inferred_turn
                    break
            self._ensure_turn_header_for_event(blocker_owner_seat, inferred_turn)
            turn_prefix = self._turn_prefix_for_number(inferred_turn)

            blocker_targets = self.game_state.blockers.setdefault(blocker_id, [])
            for attacker_id in attacker_ids:
                dedupe_key = (self.game_state.turn_number, blocker_id, attacker_id)
                if dedupe_key in self.game_state.reported_block_pairs:
                    continue
                self.game_state.reported_block_pairs.add(dedupe_key)

                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_name = self._object_display_name(attacker_obj, attacker_id)
                if attacker_name.startswith("ID "):
                    attacker_name = (self.game_state.current_combat_attackers.get(attacker_id) or {}).get("card_name")
                if not attacker_name:
                    attacker_name = f"ID {attacker_id}"

                self._print_event(f"{player_symbol} {player:8} blocking [{attacker_name}] with [{blocker_name} ({blocker_pt})]", "block")

                if attacker_id not in blocker_targets:
                    blocker_targets.append(attacker_id)

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
        source_id = None
        orig_instance_id = None
        new_instance_id = None

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
            elif key in ("source", "source_id", "sourceId", "abilitySource", "affector", "cause"):
                source_vals = detail.get("valueInt32", [])
                if isinstance(source_vals, list) and source_vals:
                    source_id = source_vals[0]
                elif isinstance(source_vals, int):
                    source_id = source_vals
            elif key == "orig_id":
                orig_instance_id = detail.get("valueInt32", [None])[0]
            elif key == "new_id":
                new_instance_id = detail.get("valueInt32", [None])[0]

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
        elif "AnnotationType_ObjectIdChanged" in ann_type:
            self._record_object_id_change(orig_instance_id, new_instance_id)
            return

        # Only process if we have affected cards
        if not affected_ids:
            return

        instance_id = affected_ids[0]

        # Find the card object for this instance
        game_objects_by_id = {
            obj.get("instanceId"): obj
            for obj in game_objects
            if isinstance(obj, dict) and obj.get("instanceId") is not None
        }
        card_obj = self._lookup_object(instance_id, game_objects_by_id)
        target_obj = self._lookup_object(target_id, game_objects_by_id) if target_id else None
        target_objs = []  # For multiple targets
        if target_ids:
            seen_targets = set()
            for tid in target_ids:
                if tid in seen_targets:
                    continue
                seen_targets.add(tid)
                t_obj = self._lookup_object(tid, game_objects_by_id)
                if t_obj:
                    target_objs.append(t_obj)

        # Handle different annotation types
        if "AnnotationType_ZoneTransfer" in ann_type:
            canonical_instance_id = self._canonical_instance_id(instance_id) or int(instance_id)
            # Casting spells and playing lands
            if (
                category in ["CastSpell", "PlaySpell", "PlayLand", "Resolve"]
                and instance_id not in self.game_state.seen_instance_ids
                and canonical_instance_id not in self.game_state.seen_instance_ids
            ):
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
                    

                    player = self._seat_label(determining_seat)
                    self._flush_pending_turn_header_for_seat(determining_seat)

                    # Get card type info
                    card_types = card_obj.get("cardTypes", [])
                    type_str = self._format_card_type(card_types)
                    if category in ["CastSpell", "PlaySpell"]:
                        # Defer non-land spell display until Resolve so cancelled/countered casts
                        # do not create duplicate or phantom cast lines.
                        if "CardType_Land" not in card_types:
                            self.game_state.pending_spell_roots[canonical_instance_id] = {
                                "name": card_name,
                                "seat": determining_seat,
                            }
                            return

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
                        else (self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced)
                    )
                    # Land plays cannot happen on the other player's turn. If we see that pattern,
                    # treat it as a late-arriving record from the previous turn.
                    if (
                        category == "PlayLand"
                        and determining_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
                        and self.game_state.active_player in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
                        and determining_seat != self.game_state.active_player
                        and self.game_state.turn_number > 1
                    ):
                        turn_for_display = self.game_state.turn_number - 1
                    turn_for_display = self._event_turn_number(determining_seat, turn_for_display)
                    is_late_event = (
                        self.game_state.turn_number > 0
                        and turn_for_display > 0
                        and turn_for_display < self.game_state.turn_number
                    )
                    late_marker = "⏪ " if is_late_event else ""

                    if category == "PlayLand":
                        self._print_event(
                            self._format_actor_event(
                                "⛰️",
                                determining_seat,
                                f"{late_marker}played [{card_name} ({type_str})]",
                                turn_override=turn_for_display,
                            ),
                            "land",
                        )
                    elif "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        self._print_event(
                            self._format_actor_event(
                                ">",
                                determining_seat,
                                f"{late_marker}cast [{card_name} ({type_str} {power}/{toughness})]{target_str}",
                                turn_override=turn_for_display,
                            ),
                            "cast",
                        )
                    else:
                        self._print_event(
                            self._format_actor_event(
                                ">",
                                determining_seat,
                                f"{late_marker}cast [{card_name} ({type_str})]{target_str}",
                                turn_override=turn_for_display,
                            ),
                            "cast",
                        )
                    
                    # Track the event using same format as turn log: "Card Name (Type P/T)" or "Card Name (Type)"
                    if "CardType_Creature" in card_types:
                        power = card_obj.get("power", {}).get("value", "?")
                        toughness = card_obj.get("toughness", {}).get("value", "?")
                        track_name = f"{card_name} ({type_str} {power}/{toughness})"
                    else:
                        track_name = f"{card_name} ({type_str})"
                    type_category = self._get_card_type_category(card_types)
                    event = CardEvent(track_name, player.lower(), card_type_category=type_category)
                    if determining_seat == self.game_state.player_seat_id:
                        self.player_cards.append(event)
                        self.session_player_cards_played += 1
                    else:
                        self.opponent_cards.append(event)
                        self.session_opponent_cards_played += 1
                    self.game_state.seen_instance_ids.add(instance_id)
                    self.game_state.seen_instance_ids.add(canonical_instance_id)
                    self.game_state.pending_spell_roots.pop(canonical_instance_id, None)

            # Combat swap-related zone transfers (e.g. Ninjutsu-like patterns).
            elif category in ["Return", "Put"]:
                self.game_state.pending_spell_roots.pop(canonical_instance_id, None)
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    controller_seat = card_obj.get("controllerSeatId")
                    determining_seat = controller_seat if controller_seat is not None else owner_seat
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    self._flush_pending_turn_header_for_seat(determining_seat)

                    turn_for_display = self._turn_for_seat(determining_seat)
                    # Mulligan/opening-hand setup can emit generic Return/Put zone transfers before
                    # turn flow starts; suppress those so they are not misreported as battlefield actions.
                    pre_turn_zone_noise = turn_for_display <= 0 and not self.game_state.combat_phase_active
                    if category == "Return":
                        if pre_turn_zone_noise:
                            return
                        self._print_event(
                            self._format_actor_event(
                                "↩️",
                                determining_seat,
                                f"returned [{card_name}] to hand",
                                turn_override=turn_for_display,
                            ),
                            "zone",
                        )
                        if self.game_state.combat_phase_active:
                            self.game_state.recent_combat_returns.append({
                                "seat_id": determining_seat,
                                "turn": turn_for_display,
                                "card_name": card_name,
                            })
                            # Keep small bounded history.
                            self.game_state.recent_combat_returns = self.game_state.recent_combat_returns[-6:]
                    else:
                        attack_state = str(card_obj.get("attackState", ""))
                        put_in_attacking = "Attacking" in attack_state or bool(card_obj.get("attackInfo"))
                        if pre_turn_zone_noise and not put_in_attacking:
                            return
                        matched_return = None
                        if put_in_attacking and self.game_state.recent_combat_returns:
                            for idx in range(len(self.game_state.recent_combat_returns) - 1, -1, -1):
                                prev = self.game_state.recent_combat_returns[idx]
                                if prev.get("seat_id") == determining_seat and prev.get("turn") == turn_for_display:
                                    matched_return = self.game_state.recent_combat_returns.pop(idx)
                                    break
                        if matched_return:
                            self._print_event(
                                self._format_actor_event(
                                    "🥷",
                                    determining_seat,
                                    f"Combat swap: returned [{matched_return['card_name']}] and put [{card_name}] onto battlefield attacking (possible Ninjutsu/Sneak)",
                                    turn_override=turn_for_display,
                                ),
                                "attack",
                            )
                        else:
                            put_suffix = " onto battlefield attacking" if put_in_attacking else " onto battlefield"
                            self._print_event(
                                self._format_actor_event(
                                    "✨",
                                    determining_seat,
                                    f"put [{card_name}]{put_suffix}",
                                    turn_override=turn_for_display,
                                ),
                                "zone",
                            )

            # Destruction and removal effects
            elif category in ["Destroy", "Exile", "Sacrifice", "Discard"]:
                self.game_state.pending_spell_roots.pop(canonical_instance_id, None)
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                    # Determine who owned the destroyed card
                    owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                    self._flush_pending_turn_header_for_seat(owner_seat)

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
                    event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None

                    self._print_event(
                        self._format_actor_event(icon, owner_seat, f"[{card_name}] was {action}", turn_override=event_turn),
                        "zone",
                    )
                    if category == "Exile":
                        if owner_seat == self.game_state.player_seat_id:
                            self.game_state.player_cards_exiled += 1
                        elif owner_seat == self.game_state.opponent_seat_id:
                            self.game_state.opponent_cards_exiled += 1

                        exiler_seat = None
                        if source_id is not None:
                            source_obj = self._lookup_object(source_id, game_objects_by_id)
                            exiler_seat = source_obj.get("controllerSeatId")
                            if exiler_seat is None:
                                exiler_seat = source_obj.get("ownerSeatId")
                        if exiler_seat is None and self.game_state.active_player in (
                            self.game_state.player_seat_id,
                            self.game_state.opponent_seat_id,
                        ):
                            exiler_seat = self.game_state.active_player

                        if (
                            owner_seat == self.game_state.player_seat_id
                            and exiler_seat == self.game_state.opponent_seat_id
                        ):
                            self.game_state.player_cards_exiled_by_opponent += 1
                        elif (
                            owner_seat == self.game_state.opponent_seat_id
                            and exiler_seat == self.game_state.player_seat_id
                        ):
                            self.game_state.opponent_cards_exiled_by_player += 1

            # Counter spells
            elif category == "Countered":
                self.game_state.pending_spell_roots.pop(canonical_instance_id, None)
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    self._flush_pending_turn_header_for_seat(owner_seat)
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
                    self._print_event(
                        self._format_actor_event("🚫", owner_seat, f"[{card_name}] was countered", turn_override=event_turn),
                        "counter",
                    )

            # Draw cards
            elif category == "Draw":
                if card_obj:
                    owner_seat = card_obj.get("ownerSeatId")
                    self._flush_pending_turn_header_for_seat(owner_seat)
                    event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
                    self._print_event(
                        self._format_actor_event("📥", owner_seat, "drew a card", turn_override=event_turn),
                        "draw",
                    )

            # Mill effects
            elif category == "Mill":
                if card_obj:
                    grp_id = card_obj.get("grpId")
                    owner_seat = card_obj.get("ownerSeatId")
                    self._flush_pending_turn_header_for_seat(owner_seat)
                    card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                    event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
                    self._print_event(
                        self._format_actor_event("🌊", owner_seat, f"milled [{card_name}]", turn_override=event_turn),
                        "zone",
                    )

        # Handle resolution annotations
        elif "AnnotationType_ResolutionStart" in ann_type:
            # This tracks when spells resolve - useful for seeing instants resolve
            pass  # Can be used for more detailed instant tracking

        elif "AnnotationType_Scry" in ann_type:
            # Scry events - show when players scry
            if affected_ids and card_obj:
                owner_seat = card_obj.get("ownerSeatId")
                self._flush_pending_turn_header_for_seat(owner_seat)
                self._print_event(
                    self._format_actor_event("🔮", owner_seat, "scried"),
                    "ability",
                )

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
        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in game_objects:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                game_objects_by_id[instance_id] = obj

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
                        target_id = (obj.get("attackInfo") or {}).get("targetId")
                        target_label = self._resolve_target_label(target_id, game_objects_by_id)

                        # Store combat info for summary
                        self.game_state.current_combat_attackers[instance_id] = {
                            "card_name": card_name,
                            "power": power,
                            "toughness": toughness,
                            "owner_seat": owner_seat,
                            "target": target_label,
                        }

                        self._flush_pending_turn_header_for_seat(owner_seat)
                        player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                        player_symbol = "⚔️" if owner_seat == self.game_state.player_seat_id else "🗡️"
                        turn_for_display = (
                            self.game_state.turn_number
                            if owner_seat == self.game_state.active_player and self.game_state.turn_number > 0
                            else self._turn_for_seat(owner_seat)
                        )
                        if not self._should_announce_attack(turn_for_display, instance_id, owner_seat):
                            break
                        self._ensure_turn_header_for_event(owner_seat, turn_for_display)
                        turn_prefix = self._turn_prefix_for_number(turn_for_display)

                        if target_label:
                            self._print_event(
                                f"{turn_prefix}{player_symbol} {player:8} attacking [{target_label}] with [{card_name} ({power}/{toughness})]",
                                "attack",
                            )
                        else:
                            self._print_event(
                                f"{turn_prefix}{player_symbol} {player:8} attacking with [{card_name} ({power}/{toughness})]",
                                "attack",
                            )
                        break

    def _handle_blocker_declared(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle blocker declarations."""
        if not affected_ids:
            return

        blocker_id = affected_ids[0]

        # Try to find which attackers are being blocked
        attacker_ids: List[int] = []
        details = annotation.get("details", [])
        for detail in details:
            key = detail.get("key")
            if key in ("attacker_id", "target"):
                attacker_id = detail.get("valueInt32", [None])[0]
                if attacker_id is not None:
                    attacker_ids.append(attacker_id)
            elif key in ("attacker_ids", "targets"):
                ids = detail.get("valueInt32", [])
                if isinstance(ids, list):
                    attacker_ids.extend([i for i in ids if i is not None])
        if not attacker_ids:
            attacker_ids = [None]

        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in game_objects:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                game_objects_by_id[instance_id] = obj

        blocker_obj = self._lookup_object(blocker_id, game_objects_by_id)
        blocker_name = self._object_display_name(blocker_obj, blocker_id)
        blocker_owner_seat = blocker_obj.get("ownerSeatId")
        blocker_pt = self._object_pt(blocker_obj)
        attackers_by_id: Dict[int, str] = {}
        for attacker_id in attacker_ids:
            if attacker_id is None:
                continue
            attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
            attackers_by_id[attacker_id] = self._object_display_name(attacker_obj, attacker_id)

        if blocker_owner_seat is not None:
            self._flush_pending_turn_header_for_seat(blocker_owner_seat)
            if blocker_owner_seat == self.game_state.player_seat_id:
                player = "You"
            elif blocker_owner_seat == self.game_state.opponent_seat_id:
                player = "Opponent"
            else:
                player = "Unknown"
            player_symbol = "🛡️"
            inferred_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else self._turn_for_seat(blocker_owner_seat)
            for attacker_id in attacker_ids:
                if attacker_id is None:
                    continue
                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_owner_seat = attacker_obj.get("ownerSeatId")
                if attacker_owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                    inferred_turn = self._turn_for_seat(attacker_owner_seat) or inferred_turn
                    break
            self._ensure_turn_header_for_event(blocker_owner_seat, inferred_turn)
            turn_prefix = self._turn_prefix_for_number(inferred_turn)

            blocker_targets = self.game_state.blockers.setdefault(blocker_id, [])
            for attacker_id in attacker_ids:
                dedupe_key = (self.game_state.turn_number, blocker_id, attacker_id)
                if dedupe_key in self.game_state.reported_block_pairs:
                    continue
                self.game_state.reported_block_pairs.add(dedupe_key)

                attacker_name = attackers_by_id.get(attacker_id) if attacker_id is not None else None
                if attacker_name:
                    self._print_event(
                        f"{turn_prefix}{player_symbol} {player:8} blocking [{attacker_name}] with [{blocker_name} ({blocker_pt})]",
                        "block",
                    )
                else:
                    self._print_event(
                        f"{turn_prefix}{player_symbol} {player:8} blocking with [{blocker_name} ({blocker_pt})]",
                        "block",
                    )

                if attacker_id is not None and attacker_id not in blocker_targets:
                    blocker_targets.append(attacker_id)

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
                        self._flush_pending_turn_header_for_seat(owner_seat)
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
                                self._print_event(f"⚔️ Combat: [{source_name}] dealt {damage_amount} damage to [{card_name}] ({owner})", "combat_damage")
                            else:
                                self._print_event(f"⚔️ Combat: [{card_name}] ({owner}) took {damage_amount} damage", "combat_damage")
                        else:
                            self._print_event(f"💢 [{card_name}] ({owner}) took {damage_amount} damage", "damage")
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
            self._flush_pending_turn_header_for_seat(owner_seat)
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
            
            self._print_event(f"{player_symbol} {player:8} activated ability: [{card_name}] ({'your' if owner_seat == self.game_state.player_seat_id else 'opponent\'s'}){target_str}", "ability")

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
            self._flush_pending_turn_header_for_seat(owner_seat)
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            
            player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
            player_symbol = "✨"
            
            trigger_desc = trigger_type if trigger_type else "triggered"
            self._print_event(f"{player_symbol} Triggered: [{card_name}] ({'your' if owner_seat == self.game_state.player_seat_id else 'opponent\'s'}) - {trigger_desc}", "ability")

    def _display_combat_summary(self):
        """Display a summary of combat after it ends."""
        if not self.game_state.current_combat_attackers and not self.game_state.combat_damage_events:
            return
        
        # Show combat summary if we have significant combat activity
        if self.game_state.combat_damage_events:
            print("\n" + self._style("⚔️ Combat Summary:", "attack"))
            for event in self.game_state.combat_damage_events:
                if event.get("source"):
                    self._print_event(f"   {event['source']} → {event['target']} ({event['target_owner']}): {event['amount']} damage", "combat_damage")
            print()

    def _resolve_game_outcome(self) -> tuple:
        """Resolve game outcome as ('win'|'loss'|'unknown', reason)."""
        pl, ol = self.game_state.player_life, self.game_state.opponent_life
        if pl <= 0:
            return "loss", "You reached 0 life"
        if ol <= 0:
            return "win", "Opponent reached 0 life"

        if self.game_state.winner_seat is not None and self.game_state.player_seat_id in (1, 2):
            if self.game_state.winner_seat == self.game_state.player_seat_id:
                return "win", "Opponent conceded/disconnected"
            if self.game_state.winner_seat == self.game_state.opponent_seat_id:
                return "loss", "You conceded/left the game"
            return "unknown", f"Winning seat: {self.game_state.winner_seat}"

        if self.game_state.winner_seat is not None:
            return "unknown", f"Winning seat: {self.game_state.winner_seat}"

        return "unknown", f"Life totals: You {pl} - {ol} Opponent"

    def _record_session_outcome(self, outcome: str) -> None:
        """Record one game result in session totals exactly once."""
        if self._session_stats_recorded_this_game:
            return

        self.session_games_played += 1
        if outcome == "win":
            self.session_wins += 1
        elif outcome == "loss":
            self.session_losses += 1
        else:
            self.session_unknown += 1
        self._session_stats_recorded_this_game = True

    def _print_game_summary(self):
        """Print summary when game ends."""
        # Last-chance: if we still don't know winner, scan recent log for opponent-left or winner in JSON
        if self.game_state.winner_seat is None:
            try:
                with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                tail = lines[-100:] if len(lines) > 100 else lines
                for ln in reversed(tail):
                    ln_lower = ln.lower()
                    if "opponent" in ln_lower and any(x in ln_lower for x in ("left", "concede", "disconnect", "quit")):
                        self._set_winner_seat(
                            self.game_state.player_seat_id,
                            reason="summary_tail:opponent_left_text",
                            priority=1,
                        )
                        break
                    if self.game_state.winner_seat is not None:
                        break
                    data = self.parser.parse_json_from_line(ln)
                    if data:
                        w = self._try_parse_winner_from_json(data)
                        if w is not None:
                            self._set_winner_seat(w, reason="summary_tail:json_winner_hint", priority=2)
                            break
            except Exception:
                pass

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
        
        outcome, reason = self._resolve_game_outcome()
        if outcome == "win":
            print("🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉")
            print(f"   ({reason})")
        elif outcome == "loss":
            print("💀💀💀 YOU LOST THIS GAME 💀💀💀")
            print(f"   ({reason})")
        else:
            print("🏁 Game ended")
            print(f"   ({reason})")
            if self.game_state.winner_seat is None:
                print("   (Result unclear — possible concede or disconnect)")

        self._record_session_outcome(outcome)
        self._print_event(f"📈 Session: {self._session_stats_line()}", "turn")
        
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
        if not self.game_state.player_deck_name:
            self._resolve_player_deck_from_candidates()
        print(f"   Your Deck: {self.game_state.player_deck_name or 'Unknown'}")
        if self.game_state.player_commanders:
            print(f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}")
        if self.game_state.opponent_commanders:
            print(f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}")
        print(f"   Mulligans: {self.game_state.mulligan_count}")
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

        print(f"\n📤 Cards Exiled:")
        print(f"   By Me: {self.game_state.opponent_cards_exiled_by_player}")
        print(f"   By Opponent: {self.game_state.player_cards_exiled_by_opponent}")

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
            top_player_creature = self._highest_known_creature_snapshot(self.game_state.player_seat_id)
            if top_player_creature:
                print(
                    f"      💪 Highest observed creature: [{top_player_creature['name']}] "
                    f"reached {top_player_creature['power']}/{top_player_creature['toughness']}"
                )

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
            top_opponent_creature = self._highest_known_creature_snapshot(self.game_state.opponent_seat_id)
            if top_opponent_creature:
                print(
                    f"      💪 Highest observed creature: [{top_opponent_creature['name']}] "
                    f"reached {top_opponent_creature['power']}/{top_opponent_creature['toughness']}"
                )

        print("\n" + "="*75)
        print("Ready for next game...\n")

        # Reset game state for next game
        self.game_state.reset()

    def _print_summary(self):
        """Print a summary of tracked cards."""
        print()
        print("📊 Session Summary")
        print("=" * 75)
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
            print("   No matches tracked this session.")
            print("   Make sure to start the tracker before playing a game!")
            return

        print(f"   Games Played: {self.session_games_played}")
        print(f"   Wins: {self.session_wins}")
        print(f"   Losses: {self.session_losses}")
        if self.session_unknown:
            print(f"   Unknown Results: {self.session_unknown}")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Runtime: {self._session_runtime_str()}")
        print(f"   Total Mulligans: {self.session_total_mulligans}")
        print(f"   Total Cards Played: {self.session_player_cards_played}")
        print(f"   Total Opponent Cards Played: {self.session_opponent_cards_played}")

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
