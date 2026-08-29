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
        source: Optional[str] = None,
    ):
        """Initialize a card event."""
        self.card_name = card_name
        self.player = player
        self.timestamp = timestamp or datetime.now()
        self.card_type_category = card_type_category or "Other"
        # How the card was seen: None/"draw" for a normal draw, "ramp" for a
        # land forced from the library straight onto the battlefield (ramp /
        # search). "ramp" cards stay in Lands Seen but are excluded from the
        # flood side of the flood/screw math (see draw_quality).
        self.source = source

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
            # Removal tracking (classification is text-based; see
            # removal_classifier.py). Drawn counts only fill for the player —
            # opponent draws are hidden.
            "removal_drawn": 0,
            "removal_played": 0,
            "wipes_drawn": 0,
            "wipes_played": 0,
            "bounces_drawn": 0,
            "bounces_played": 0,
            "counters_drawn": 0,
            "counters_played": 0,
            # This seat's spells that GOT countered (the other seat's counters
            # landing) — from stack lifecycle, not text classification.
            "spells_countered": 0,
            # Poison counters accumulated by this seat (highest total observed
            # in the GRE player state; poison only ever goes up in practice).
            "poison_added": 0,
            # This seat's permanents removed from the battlefield by destroy,
            # exile, or non-combat lethal damage / zero toughness (board wipes
            # included), split creature vs non-creature (lands excluded — they
            # get their own category below).
            "creatures_removed": 0,
            "noncreatures_removed": 0,
            # This seat's permanents returned from the battlefield to hand
            # (self-bounce paid as a cost excluded).
            "creatures_bounced": 0,
            "noncreatures_bounced": 0,
            # Lands this seat LOST to an enemy card, and how many of those
            # they answered with a land drop by the end of their next turn.
            "lands_lost": 0,
            "lands_replaced": 0,
            # Token lifecycle for this seat's tokens.
            "tokens_created": 0,
            "tokens_destroyed": 0,
            "tokens_sacrificed": 0,
            "tokens_exiled": 0,
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
        self.turns_taken_by_seat: Dict[int, Set[int]] = {1: set(), 2: set()}
        self.turn_started_at: Optional[datetime] = None
        self.turn_started_number: Optional[int] = None
        self.turn_started_seat: Optional[int] = None
        self.turn_time_seconds_by_seat: Dict[int, int] = {1: 0, 2: 0}
        self.completed_turns: List[Dict[str, Any]] = []
        self.player_seat_id: Optional[int] = None
        self.opponent_seat_id: Optional[int] = None
        self.my_user_id: Optional[str] = None

        # True when the tracker first saw this game already past turn 1 (its
        # start was never observed). Such games are shown live but not saved.
        self.mid_game_attach = False
        self.starting_hand: List[str] = []
        self.starting_hand_events: List[CardEvent] = []
        # Every full hand that was mulliganed away (or bottomed from), in order.
        # Entries: {"events": List[CardEvent], "bottomed": List[int] (0-based positions)}.
        self.mulligan_hand_history: List[Dict[str, Any]] = []
        self.mulligan_count = 0
        self.initial_hand_size = 7
        self._hand_before_mulligan: List[str] = []
        self._hand_before_mulligan_ids: List[int] = []
        self._hand_before_mulligan_instance_ids: List[int] = []
        self._hand_before_mulligan_events: List[CardEvent] = []
        self.opening_hand_capture_closed = False
        self.opening_mulligan_prompt_seen = False
        self.explicit_mulligan_count = 0
        self.opening_keep_confirmed = False
        self.opening_select_n_ids: List[int] = []
        self.submitted_deck_cards: List[int] = []
        self.submitted_sideboard_cards: List[int] = []

        self.instance_roots: Dict[int, int] = {}
        # Targets printed as "[ID: N]" because the object was still hidden
        # when the line logged (e.g. a graveyard card Arena had only listed
        # by id). instance_id -> the literal token; when the object's
        # identity arrives, the recorded lines are patched in place.
        self.unresolved_target_ids: Dict[int, str] = {}
        self.pending_spell_roots: Dict[int, Dict[str, Any]] = {}
        self.stack_items: Dict[int, Dict[str, Any]] = {}
        self.ability_instance_sources: Dict[int, int] = {}
        self.instance_target_ids: Dict[int, List[int]] = {}
        self.logged_ability_actions: Set[tuple] = set()
        self.logged_ability_resolutions: Set[tuple] = set()
        self.logged_tap_untap_events: Set[tuple] = set()
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
        #: Pending land-replacement watches per seat: global turn deadlines by
        #: which the seat must drop a land for the destruction to count as
        #: "replaced" (victim's next turn ≈ destruction turn + 2).
        self.pending_land_replacements: Dict[int, List[int]] = {1: [], 2: []}
        #: Battlefield instance ids already counted as lost to removal /
        #: bounced to hand (dedupe across repeated annotations for one leave).
        self.counted_removal_losses: Set[int] = set()
        #: Battlefield zone id (from the GRE zone list), for board censuses.
        self.battlefield_zone_id: Optional[int] = None
        #: Threshold sweepers (damage-to-each / type-qualified wipes) awaiting
        #: an outcome verdict: each entry {"seat_id", "turn", "census"} where
        #: census is the set of creature instance ids on the battlefield at
        #: cast. Board cleared -> wipe; survivors -> removal (design ruling:
        #: a wipe removes EVERYTHING; killing 2 of 4 is removal).
        self.pending_threshold_wipes: List[Dict[str, Any]] = []
        self.counted_bounce_returns: Set[int] = set()
        #: Token instance ids already counted as created (dedupe across diffs).
        self.counted_token_creations: Set[int] = set()
        #: (instance_id, category) pairs already counted as token losses.
        self.counted_token_losses: Set[tuple] = set()
        self.drawn_card_events: Dict[int, List[CardEvent]] = {1: [], 2: []}

        self.game_start_time: Optional[datetime] = None
        self.game_end_time: Optional[datetime] = None
        self.winner_seat: Optional[int] = None
        self.winner_priority = 0
        self.winner_reason = ""
        self.result_type: Optional[str] = None
        self.result_reason: Optional[str] = None
        #: ResultReason_* from the structured WinLoss result (Concede/Game/Timeout).
        self.win_result_reason: Optional[str] = None
        #: SBA_* code from AnnotationType_LossOfGame (LifeTotal/DrawEmptyLibrary/
        #: Poisoned...) plus the seat it hit — the precise "how the game ended".
        self.loss_reason_code: Optional[str] = None
        self.loss_reason_seat: Optional[int] = None
        self.first_player_seat: Optional[int] = None
        self.pending_player_turn_header: Optional[tuple] = None
        self.pending_opponent_turn_header: Optional[tuple] = None

        self.match_type = "best_of_1"
        self.game_number = 1
        self.format_str = "Unknown"
        #: Arena's own match UUID from GRE gameInfo — the authoritative way to
        #: group Bo3 games into one match (heuristics are only a fallback).
        self.arena_match_id: Optional[str] = None
        #: True once Arena declared the whole MATCH over (MatchState_MatchComplete
        #: or a finalMatchResult) — distinguishes "game over, match continues"
        #: from "match over" for Bo3.
        self.arena_match_over = False
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
