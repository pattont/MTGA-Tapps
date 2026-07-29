import sqlite3

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.analytics_persistence import (
    analytics_card_base_name,
    analytics_card_power_toughness,
    persist_card_summary,
    persist_commanders,
    persist_drawn_cards,
    persist_mulligan_hands,
    persist_opening_hand,
    persist_submitted_deck,
)
from mtga_tracker.state import CardEvent


def test_analytics_card_display_name_normalization():
    assert analytics_card_base_name("Likeness Looter (Creature 1/1)") == "Likeness Looter"
    assert analytics_card_power_toughness("Likeness Looter (Creature 1/1)") == ("1", "1")
    assert analytics_card_power_toughness("Swamp (Land)") == (None, None)


def test_persist_card_summary_opening_hand_and_commanders(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    assert conn is not None
    with conn:
        conn.execute(
            """
            insert into tracker_sessions (id, started_at)
            values ('session-1', '2026-05-07T00:00:00')
            """
        )
        conn.execute(
            """
            insert into matches (id, session_id)
            values ('match-1', 'session-1')
            """
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id)
            values ('game-1', 'session-1', 'match-1')
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role)
            values ('participant-1', 'game-1', 'player')
            """
        )
        persist_card_summary(
            conn,
            "game-1",
            "participant-1",
            [
                CardEvent("Island (Land)", "player", card_type_category="Land"),
                CardEvent("Island (Land)", "player", card_type_category="Land"),
                CardEvent(
                    "Likeness Looter (Creature 1/1)", "player", card_type_category="Creature"
                ),
            ],
            refresh_display_name=lambda name: name,
        )
        persist_opening_hand(
            conn,
            "game-1",
            "participant-1",
            starting_hand_events=[
                CardEvent("Island", "player", card_type_category="Land"),
                CardEvent("Island", "player", card_type_category="Land"),
            ],
            starting_hand=[],
            refresh_display_name=lambda name: name,
        )
        persist_commanders(
            conn,
            "participant-1",
            ["Niv-Mizzet, Parun"],
            refresh_display_name=lambda name: name,
        )
        draw_one = CardEvent("Island", "player", card_type_category="Land")
        draw_one.turn_number = 2
        draw_two = CardEvent(
            "Likeness Looter (Creature 1/1)", "player", card_type_category="Creature"
        )
        draw_two.turn_number = 3
        persist_drawn_cards(
            conn,
            "game-1",
            "participant-1",
            [draw_one, draw_two],
            refresh_display_name=lambda name: name,
        )
    store.close()

    with sqlite3.connect(db_path) as check:
        summary = check.execute(
            "select display_name, played_count from game_card_summary order by display_name"
        ).fetchall()
        opening_hand = check.execute(
            "select display_name, hand_position, copy_number from game_opening_hand_cards order by hand_position"
        ).fetchall()
        drawn_cards = check.execute(
            """
            select display_name, draw_position, turn_number, copy_number
            from game_drawn_cards
            order by draw_position
            """
        ).fetchall()
        commander = check.execute("select card_name from participant_commanders").fetchone()

    assert summary == [("Island (Land)", 2), ("Likeness Looter (Creature 1/1)", 1)]
    assert opening_hand == [("Island", 1, 1), ("Island", 2, 2)]
    assert drawn_cards == [("Island", 1, 2, 1), ("Likeness Looter (Creature 1/1)", 2, 3, 1)]
    assert commander == ("Niv-Mizzet, Parun",)


def test_persist_mulligan_hands_records_each_hand_and_bottomed_cards(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    assert conn is not None
    with conn:
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-29T00:00:00')"
        )
        conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
        conn.execute("insert into games (id, session_id, match_id) values ('game-1', 'session-1', 'match-1')")
        conn.execute("insert into participants (id, game_id, role) values ('participant-1', 'game-1', 'player')")
        persist_mulligan_hands(
            conn,
            "game-1",
            "participant-1",
            [
                {
                    "events": [
                        CardEvent("Swamp (Land)", "player", card_type_category="Land"),
                        CardEvent("Swamp (Land)", "player", card_type_category="Land"),
                        CardEvent("Duress", "player", card_type_category="Sorcery"),
                    ],
                    "bottomed": [],
                },
                {
                    "events": [
                        CardEvent("Swamp (Land)", "player", card_type_category="Land"),
                        CardEvent("Liliana of the Veil", "player", card_type_category="Planeswalker"),
                        CardEvent("Duress", "player", card_type_category="Sorcery"),
                    ],
                    "bottomed": [2],
                },
            ],
            refresh_display_name=lambda name: name,
        )
    store.close()

    with sqlite3.connect(db_path) as check:
        rows = check.execute(
            """
            select hand_number, hand_position, display_name, bottomed
            from game_mulligan_hands
            order by hand_number, hand_position
            """
        ).fetchall()

    assert rows == [
        (1, 1, "Swamp (Land)", 0),
        (1, 2, "Swamp (Land)", 0),
        (1, 3, "Duress", 0),
        (2, 1, "Swamp (Land)", 0),
        (2, 2, "Liliana of the Veil", 0),
        (2, 3, "Duress", 1),
    ]


def test_persist_submitted_deck_groups_main_deck_and_sideboard(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    assert conn is not None
    with conn:
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-27')"
        )
        conn.execute(
            "insert into matches (id, session_id) values ('match-1', 'session-1')"
        )
        conn.execute(
            "insert into games (id, session_id, match_id) values ('game-1', 'session-1', 'match-1')"
        )
        conn.execute(
            "insert into participants (id, game_id, role) values ('player-1', 'game-1', 'player')"
        )
        names = {1: "Swamp", 2: "Unholy Annex // Ritual Chamber", 3: "Duress"}
        types = {1: "Land", 2: "Enchantment", 3: "Sorcery"}
        persist_submitted_deck(
            conn,
            "game-1",
            "player-1",
            deck_cards=[1, 1, 1, 2],
            sideboard_cards=[3],
            resolve_name=names.__getitem__,
            resolve_type_category=types.get,
        )
    store.close()

    with sqlite3.connect(db_path) as check:
        rows = check.execute(
            """
            select arena_id, display_name, deck_zone, quantity
            from game_deck_cards
            order by deck_zone, arena_id
            """
        ).fetchall()

    assert rows == [
        (1, "Swamp", "deck", 3),
        (2, "Unholy Annex // Ritual Chamber", "deck", 1),
        (3, "Duress", "sideboard", 1),
    ]
