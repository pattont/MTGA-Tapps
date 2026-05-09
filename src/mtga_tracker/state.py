"""Mutable tracker state and event models."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set


class CardEvent:
    """Represents a card play event."""

    def __init__(
        self,
        card_name: str,
        player: str,
        timestamp: Optional[datetime] = None,
        card_type_category: Optional[str] = None,
    ):
        """Initialize a card event."""
        self.card_name = card_name
        self.player = player
        self.timestamp = timestamp or datetime.now()
        self.card_type_category = card_type_category or "Other"

    def __repr__(self) -> str:
        return f"CardEvent(card={self.card_name}, player={self.player}, time={self.timestamp})"


class GameState:
    """Tracks the current game state."""

    @staticmethod
    def _new_match_stats() -> Dict[int, Dict[str, int]]:
        """Return zeroed per-seat match stats."""
        base = {
            "attacks": 0,
            "attacking_creatures": 0,
            "attackers_lost": 0,
            "blocking_creatures": 0,
            "blockers_lost": 0,
            "total_damage": 0,
            "life_lost": 0,
            "life_gain": 0,
            "self_damage": 0,
            "cards_drawn": 0,
            "cards_discarded": 0,
            "cards_milled": 0,
            "cards_exiled": 0,
        }
        return {1: base.copy(), 2: base.copy()}

    @staticmethod
    def _new_stack_stats() -> Dict[int, Dict[str, int]]:
        """Return zeroed per-seat stack lifecycle stats."""
        base = {
            "put_on_stack": 0,
            "resolved": 0,
            "countered": 0,
            "fizzled": 0,
        }
        return {1: base.copy(), 2: base.copy()}

    def __init__(self):
        self.player_life = 20
        self.opponent_life = 20
        self.turn_number = 0
        self.active_player = None
        self.phase = ""
        self.step = ""
        self.in_match = False
        self.match_complete = False
        self.seen_instance_ids: Set[int] = set()
        self.last_turn_announced = 0
        self.last_player_turn_number = 0
        self.last_opponent_turn_number = 0
        self.player_seat_id: Optional[int] = None
        self.opponent_seat_id: Optional[int] = None
        self.my_user_id: Optional[str] = None

        self.starting_hand: List[str] = []
        self.starting_hand_events: List[CardEvent] = []
        self.mulligan_count = 0
        self.initial_hand_size = 7
        self._hand_before_mulligan: List[str] = []
        self._hand_before_mulligan_ids: List[int] = []
        self._hand_before_mulligan_events: List[CardEvent] = []
        self.opening_hand_capture_closed = False
        self.opening_mulligan_prompt_seen = False
        self.explicit_mulligan_count = 0
        self.opening_keep_confirmed = False
        self.opening_select_n_ids: List[int] = []
        self.submitted_deck_cards: List[int] = []
        self.submitted_sideboard_cards: List[int] = []

        self.instance_roots: Dict[int, int] = {}
        self.pending_spell_roots: Dict[int, Dict[str, Any]] = {}
        self.stack_items: Dict[int, Dict[str, Any]] = {}
        self.ability_instance_sources: Dict[int, int] = {}
        self.logged_ability_actions: Set[tuple] = set()
        self.logged_ability_resolutions: Set[tuple] = set()
        self.ability_instance_action_texts: Dict[int, str] = {}
        self.logged_identity_changes: Set[tuple] = set()
        self.logged_unhandled_annotations: Set[tuple] = set()
        self.pending_modal_requests: Dict[tuple, Dict[str, Any]] = {}
        self.logged_modal_choices: Set[tuple] = set()

        self.attackers: List[int] = []
        self.blockers: Dict[int, List[int]] = {}
        self.combat_phase_active = False
        self.current_combat_attackers: Dict[int, Dict] = {}
        self.current_combat_blockers: Dict[int, Dict[str, Any]] = {}
        self.combat_damage_events: List[Dict] = []
        self.reported_block_pairs: Set[tuple] = set()
        self.reported_attack_keys: Set[tuple] = set()
        self.recent_combat_returns: List[Dict[str, Any]] = []
        self.object_snapshots: Dict[int, Dict[str, Any]] = {}
        self.highest_creature_by_seat: Dict[int, Dict[str, Any]] = {}
        self.counted_attack_turns: Set[tuple] = set()
        self.combat_loss_events_counted: Set[tuple] = set()
        self.match_stats = self._new_match_stats()
        self.stack_stats = self._new_stack_stats()

        self.game_start_time: Optional[datetime] = None
        self.game_end_time: Optional[datetime] = None
        self.winner_seat: Optional[int] = None
        self.winner_priority = 0
        self.winner_reason = ""
        self.first_player_seat: Optional[int] = None
        self.pending_player_turn_header: Optional[tuple] = None
        self.pending_opponent_turn_header: Optional[tuple] = None

        self.match_type = "best_of_1"
        self.game_number = 1
        self.format_str = "Unknown"
        self.player_display_name: Optional[str] = None
        self.opponent_display_name: Optional[str] = None
        self.player_deck_name: Optional[str] = None
        self.player_deck_id: Optional[str] = None
        self.player_deck_event_name: Optional[str] = None
        self.player_deck_last_played: Optional[datetime] = None
        self.player_deck_total_cards: Optional[int] = None
        self.observed_starting_deck_total_by_seat: Dict[int, int] = {}
        self._reserved_players: List[Dict[str, Any]] = []
        self.player_cards_exiled = 0
        self.opponent_cards_exiled = 0
        self.player_cards_exiled_by_opponent = 0
        self.opponent_cards_exiled_by_player = 0
        self.commanders_by_seat: Dict[int, List[str]] = {}
        self.player_commanders: List[str] = []
        self.opponent_commanders: List[str] = []
        self.player_commanders_announced = False
        self.opponent_commanders_announced = False
        self.seat_line_announced = False
        self.last_emitted_life_event: Optional[tuple] = None
        self.pending_damage_to_seat: Dict[int, int] = {}
        self.last_hand_size_by_seat: Dict[int, int] = {}
        self.recent_attack_sources_by_target: Dict[int, Set[int]] = {}

    def reset(self):
        """Reset state for a new game while keeping only stable account-level metadata."""
        player_display_name = self.player_display_name
        self.__init__()
        self.player_seat_id = None
        self.opponent_seat_id = None
        self.player_display_name = player_display_name
