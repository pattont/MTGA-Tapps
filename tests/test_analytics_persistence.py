import sqlite3

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.analytics_persistence import (
    analytics_card_base_name,
    analytics_card_power_toughness,
    persist_card_summary,
    persist_commanders,
    persist_opening_hand,
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
                CardEvent("Likeness Looter (Creature 1/1)", "player", card_type_category="Creature"),
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
    store.close()

    with sqlite3.connect(db_path) as check:
        summary = check.execute(
            "select display_name, played_count from game_card_summary order by display_name"
        ).fetchall()
        opening_hand = check.execute(
            "select display_name, hand_position, copy_number from game_opening_hand_cards order by hand_position"
        ).fetchall()
        commander = check.execute("select card_name from participant_commanders").fetchone()

    assert summary == [("Island (Land)", 2), ("Likeness Looter (Creature 1/1)", 1)]
    assert opening_hand == [("Island", 1, 1), ("Island", 2, 2)]
    assert commander == ("Niv-Mizzet, Parun",)
