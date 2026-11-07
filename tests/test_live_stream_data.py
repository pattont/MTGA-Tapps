"""Live-row data the Stream Kit reads: the opponent's played cards and the
player's flood/screw reading so far."""

import json

from mtga_tracker.state import CardEvent
from tests.test_tracker_combat_winner import make_tracker


class CostCardDB:
    """Arena's mana-cost index, by name."""

    def __init__(self, costs):
        self.costs = costs

    def mana_cost_index_by_name(self):
        return self.costs

    def get_card_name(self, grp_id):
        return f"Card{grp_id}"

    def get_card_type_category(self, grp_id):
        return "Land" if grp_id < 100 else "Creature"


def test_opponent_seen_lists_each_card_once_with_type_cost_and_count():
    tracker = make_tracker()
    tracker.card_db = CostCardDB(
        {"Shock": ("{R}", 1.0), "Fable of the Mirror-Breaker": ("{2}{R}", 3.0)}
    )
    tracker.opponent_cards = [
        CardEvent("Mountain", "opponent", card_type_category="Land"),
        CardEvent("Shock", "opponent", card_type_category="Instant"),
        CardEvent(
            "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
            "opponent",
            card_type_category="Enchantment",
        ),
        CardEvent("Shock", "opponent", card_type_category="Instant"),
        CardEvent("Card #12345", "opponent"),
    ]
    seen = json.loads(tracker._live_opponent_seen())
    assert seen == [
        {"name": "Mountain", "type": "Land", "mana_cost": None, "mana_value": None, "count": 1},
        {"name": "Shock", "type": "Instant", "mana_cost": "{R}", "mana_value": 1.0, "count": 2},
        {
            "name": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
            "type": "Enchantment",
            "mana_cost": "{2}{R}",
            "mana_value": 3.0,
            "count": 1,
        },
    ]
    tracker.opponent_cards = []
    assert tracker._live_opponent_seen() is None


def _land(name="Mountain"):
    return CardEvent(name, "player", card_type_category="Land")


def _spell(name="Shock"):
    return CardEvent(name, "player", card_type_category="Instant")


def _setup_draws(opening, drawn, deck=(60, 24)):
    tracker = make_tracker()
    tracker._live_deck_land_stats = lambda: deck
    g = tracker.game_state
    g.player_seat_id = 1
    g.starting_hand_events = list(opening)
    g.drawn_card_events = {1: list(drawn), 2: []}
    return tracker


def test_live_draw_quality_reads_flood_like_game_detail():
    # 3-land keep, then 7 lands in 8 draws from a 24-land 60-card deck.
    tracker = _setup_draws(
        [_land(), _land(), _land(), _spell(), _spell(), _spell(), _spell()],
        [_land(), _land(), _land(), _spell(), _land(), _land(), _land(), _land()],
    )
    overlay = json.dumps(
        {"cards": [{}], "land_odds": {"1": 31.1}, "library_size": 45, "lands_left": 14}
    )
    quality = json.loads(tracker._live_draw_quality(overlay))
    assert quality["lands_seen"] == 10 and quality["total_cards_seen"] == 15
    assert quality["is_flood"] is True and quality["is_screw"] is False
    assert quality["reason"] == "7 of 8 post-opening draws were lands"
    assert quality["expected_lands_seen"] == 6.0
    assert (quality["next_land_pct"], quality["library_size"], quality["lands_left"]) == (
        31.1,
        45,
        14,
    )


def test_live_draw_quality_reads_screw_and_normal():
    screwed = _setup_draws(
        [_land(), _spell(), _spell(), _spell(), _spell(), _spell(), _spell()],
        [_spell(), _spell(), _spell(), _spell(), _spell()],
    )
    quality = json.loads(screwed._live_draw_quality())
    assert quality["is_screw"] is True and quality["is_flood"] is False
    assert quality["next_land_pct"] is None

    normal = _setup_draws(
        [_land(), _land(), _land(), _spell(), _spell(), _spell(), _spell()],
        [_spell(), _land(), _spell()],
    )
    quality = json.loads(normal._live_draw_quality())
    assert not (quality["is_flood"] or quality["is_screw"] or quality["is_land_streak"])
    assert quality["reason"] is None


def test_live_draw_quality_needs_a_decklist_and_skips_mid_game_attach():
    tracker = _setup_draws([_land()], [], deck=None)
    assert tracker._live_draw_quality() is None
    tracker = _setup_draws([_land()], [])
    tracker.game_state.mid_game_attach = True
    assert tracker._live_draw_quality() is None
