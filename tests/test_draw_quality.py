import sqlite3

import pytest

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.draw_quality import (
    analyze_draw_quality,
    hypergeom_tail_at_least,
    hypergeom_tail_at_most,
)


def _insert_game(conn: sqlite3.Connection, game_id: str = "game-1") -> str:
    conn.execute(
        "insert into tracker_sessions (id, started_at) values ('session-1', '2026-06-11T00:00:00')"
    )
    conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
    conn.execute(
        """
        insert into games (id, session_id, match_id, started_at, outcome)
        values (?, 'session-1', 'match-1', '2026-06-11T00:05:00', 'loss')
        """,
        (game_id,),
    )
    participant_id = f"{game_id}-player"
    conn.execute(
        """
        insert into participants (id, game_id, role, deck_name, deck_size)
        values (?, ?, 'player', 'Golgari Test', 60)
        """,
        (participant_id, game_id),
    )
    return participant_id


def _insert_seen_card(
    conn: sqlite3.Connection,
    table: str,
    game_id: str,
    participant_id: str,
    display_name: str,
    type_category: str,
    position: int,
) -> None:
    position_column = "hand_position" if table == "game_opening_hand_cards" else "draw_position"
    conn.execute(
        f"""
        insert into {table} (
            game_id, participant_id, display_name, type_category, {position_column}, copy_number
        )
        values (?, ?, ?, ?, ?, 1)
        """,
        (game_id, participant_id, display_name, type_category, position),
    )


def test_hypergeom_tails_match_exact_combinatorics():
    assert hypergeom_tail_at_least(
        4, population_size=60, success_count=22, draw_count=4
    ) == pytest.approx(
        7315 / 487635,
        rel=1e-12,
    )
    assert hypergeom_tail_at_most(
        0, population_size=60, success_count=22, draw_count=4
    ) == pytest.approx(
        73815 / 487635,
        rel=1e-12,
    )


def test_draw_quality_analysis_uses_opening_hand_and_known_draws(tmp_path):
    db_path = tmp_path / "tracker.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    assert conn is not None
    with conn:
        participant_id = _insert_game(conn)
        for index in range(1, 4):
            _insert_seen_card(
                conn,
                "game_opening_hand_cards",
                "game-1",
                participant_id,
                f"Forest {index} (Land)",
                "Land",
                index,
            )
        for index in range(4, 8):
            _insert_seen_card(
                conn,
                "game_opening_hand_cards",
                "game-1",
                participant_id,
                f"Spell {index}",
                "Creature",
                index,
            )
        for index in range(1, 5):
            _insert_seen_card(
                conn,
                "game_drawn_cards",
                "game-1",
                participant_id,
                f"Swamp {index} (Land)",
                "Land",
                index,
            )
        for index in range(5, 9):
            _insert_seen_card(
                conn,
                "game_drawn_cards",
                "game-1",
                participant_id,
                "Llanowar Elves (Creature 1/1)",
                "Creature",
                index,
            )
    store.close()

    result = analyze_draw_quality(
        db_path,
        target_card="Llanowar Elves",
        expected_land_rate=0.37,
        target_card_copies=4,
        limit=5,
    )

    assert result.total_games == 1
    game = result.games[0]
    assert game.cards_seen == 15
    assert game.lands_seen == 7
    assert game.known_draws == 8
    assert game.target_card_seen == 4
    assert game.target_card_probability is not None
    assert game.flood_probability is not None


def test_flood_counts_opening_hand_lands():
    from mtga_tracker.draw_quality import draw_quality_metrics

    land = {"display_name": "Swamp", "type_category": "Land"}
    spell = {"display_name": "Spell", "type_category": "Creature"}
    opener = [dict(land) for _ in range(3)] + [dict(spell) for _ in range(4)]
    drawn = [
        {**land, "draw_position": 1},
        {**land, "draw_position": 2},
        {**spell, "draw_position": 3},
    ]

    # 3-land keep plus 2 lands in only 3 draws: 5 of 10 cards seen were lands.
    quality = draw_quality_metrics(opener, drawn, 3, 60, deck_lands=22)
    assert quality["is_flood"] is True
    assert any("opening hand included" in reason for reason in quality["flood_reasons"])

    # Same pattern in a 17-land limited deck is within normal range.
    limited = draw_quality_metrics(opener, drawn, 3, 40, deck_lands=17)
    assert limited["is_flood"] is False

    # A normal 4-of-10 land share never fires the combined rule.
    normal_drawn = [
        {**land, "draw_position": 1},
        {**spell, "draw_position": 2},
        {**spell, "draw_position": 3},
    ]
    normal = draw_quality_metrics(opener, normal_drawn, 3, 60, deck_lands=22)
    assert normal["is_flood"] is False


def test_ramped_lands_count_as_seen_but_not_as_flood():
    from mtga_tracker.draw_quality import draw_quality_metrics

    land = {"display_name": "Forest", "type_category": "Land"}
    ramp = {"display_name": "Forest", "type_category": "Land", "source": "ramp"}
    spell = {"display_name": "Spell", "type_category": "Creature"}
    opener = [dict(land) for _ in range(3)] + [dict(spell) for _ in range(4)]
    # Post-opening: three lands FORCED out of the library, one real spell draw.
    drawn = [
        {**ramp, "draw_position": 1},
        {**ramp, "draw_position": 2},
        {**ramp, "draw_position": 3},
        {**spell, "draw_position": 4},
    ]
    quality = draw_quality_metrics(opener, drawn, 4, 60, deck_lands=22)

    # Every ramped land stays visible in the seen counts.
    assert quality["ramped_lands"] == 3
    assert quality["lands_seen"] == 6  # 3 opening + 3 ramped
    assert quality["total_cards_seen"] == 11

    # Flood ignores the ramped lands entirely: only the 3 opening lands remain
    # among 8 flood-relevant cards, so this is not flood.
    assert quality["flood_lands_seen"] == 3
    assert quality["flood_cards_seen"] == 8
    assert quality["is_flood"] is False
    assert not any("consecutive land draws" in r for r in quality["flood_reasons"])

    # The same three lands drawn naturally WOULD read as flood.
    natural = [
        {**land, "draw_position": 1},
        {**land, "draw_position": 2},
        {**land, "draw_position": 3},
        {**spell, "draw_position": 4},
    ]
    natural_quality = draw_quality_metrics(opener, natural, 4, 60, deck_lands=22)
    assert natural_quality["is_flood"] is True


def test_ramped_lands_protect_against_screw():
    from mtga_tracker.draw_quality import draw_quality_metrics

    land = {"display_name": "Forest", "type_category": "Land"}
    ramp = {"display_name": "Forest", "type_category": "Land", "source": "ramp"}
    spell = {"display_name": "Spell", "type_category": "Creature"}
    # One-land opener, a long nonland run, but a land fetched out mid-game.
    opener = [dict(land)] + [dict(spell) for _ in range(6)]
    drawn_screwed = [{**spell, "draw_position": i} for i in range(1, 9)]
    screwed = draw_quality_metrics(opener, drawn_screwed, 8, 60, deck_lands=24)

    drawn_ramped = [
        {**spell, "draw_position": 1},
        {**spell, "draw_position": 2},
        {**ramp, "draw_position": 3},
        {**spell, "draw_position": 4},
        {**spell, "draw_position": 5},
        {**spell, "draw_position": 6},
        {**spell, "draw_position": 7},
        {**spell, "draw_position": 8},
    ]
    protected = draw_quality_metrics(opener, drawn_ramped, 8, 60, deck_lands=24)

    # The fetched land counts as a land you have: screw probability rises
    # (less screwed) once a ramped land is on the board, and it still shows in
    # Lands Seen. Screw KEEPS ramped lands, unlike flood which drops them.
    assert protected["lands_seen"] == screwed["lands_seen"] + 1
    assert protected["screw_probability_pct"] > screwed["screw_probability_pct"]
    # Flood, by contrast, would not see that fetched land at all.
    assert protected["flood_lands_seen"] == protected["lands_seen"] - 1
