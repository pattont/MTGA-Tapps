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


def test_persist_card_summary_normalizes_split_card_half_names(tmp_path):
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
        # The full split-card name is already known from decklists/draws.
        conn.execute("insert into cards (name, primary_type, first_seen_at) values ('Unholy Annex // Ritual Chamber', 'Enchantment', '2026-07-29T00:00:00')")
        drawn = CardEvent("Unholy Annex // Ritual Chamber", "player", card_type_category="Enchantment")
        persist_card_summary(
            conn,
            "game-1",
            "participant-1",
            [
                CardEvent("Unholy Annex (Enchantment)", "player", card_type_category="Enchantment"),
                CardEvent("Ritual Chamber (Enchantment)", "player", card_type_category="Enchantment"),
            ],
            drawn_events=[drawn],
            refresh_display_name=lambda name: name,
        )
    store.close()

    with sqlite3.connect(db_path) as check:
        rows = check.execute(
            "select display_name, played_count, drawn_count from game_card_summary order by display_name"
        ).fetchall()

    # Both door plays and the draw collapse into one full-name row.
    assert rows == [("Unholy Annex // Ritual Chamber (Enchantment)", 2, 1)]


def test_migration_v6_merges_split_card_half_summary_rows(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-29T00:00:00')"
        )
        conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
        conn.execute("insert into games (id, session_id, match_id) values ('game-1', 'session-1', 'match-1')")
        conn.execute("insert into participants (id, game_id, role) values ('participant-1', 'game-1', 'player')")
        conn.execute("insert into cards (name, primary_type, first_seen_at) values ('Unholy Annex // Ritual Chamber', 'Enchantment', '2026-07-29T00:00:00')")
        conn.executemany(
            """
            insert into game_card_summary (game_id, participant_id, display_name, type_category, played_count, drawn_count)
            values ('game-1', 'participant-1', ?, ?, ?, ?)
            """,
            [
                ("Unholy Annex (Enchantment)", "Enchantment", 2, 0),
                ("Ritual Chamber (Enchantment)", "Enchantment", 1, 0),
                ("Unholy Annex // Ritual Chamber", "Enchantment", 0, 2),
                ("Llanowar Elves (Creature 1/1)", "Creature", 1, 1),
            ],
        )
        # Re-run migrations: v6 should merge the three variants into one row.
        conn.execute("delete from schema_migrations where version = 6")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        rows = check.execute(
            "select display_name, played_count, drawn_count from game_card_summary order by display_name"
        ).fetchall()

    assert ("Llanowar Elves (Creature 1/1)", 1, 1) in rows
    merged = [row for row in rows if "Unholy Annex" in row[0] or "Ritual Chamber" in row[0]]
    assert len(merged) == 1
    assert merged[0][1] == 3  # both doors' plays merged
    assert merged[0][2] == 2  # draws preserved


def test_migration_v7_backfills_bottomed_card_from_console_line(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-29T00:00:00')"
        )
        conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at)
            values ('game-1', 'session-1', 'match-1', '2026-07-29T00:05:00')
            """
        )
        conn.execute(
            "insert into participants (id, game_id, role, mulligans) values ('participant-1', 'game-1', 'player', 1)"
        )
        kept = [
            ("Fomori Vault", "Land"),
            ("Swamp", "Land"),
            ("Swamp", "Land"),
            ("Requiting Hex", "Instant"),
            ("Firdoch Core", "Artifact"),
            ("Arc Reactor", "Artifact"),
        ]
        conn.executemany(
            """
            insert into game_opening_hand_cards (game_id, participant_id, display_name, type_category, hand_position, copy_number)
            values ('game-1', 'participant-1', ?, ?, ?, 1)
            """,
            [(name, cat, position + 1) for position, (name, cat) in enumerate(kept)],
        )
        conn.execute(
            "insert into cards (name, primary_type, first_seen_at) values ('Ancient Vendetta', 'Sorcery', '2026-07-29T00:00:00')"
        )
        conn.execute(
            """
            insert into console_logs (session_id, created_at, match_started_at, text)
            values ('session-1', '2026-07-29T00:06:00', '2026-07-29T00:05:00', '🔄 Mulliganed away: Ancient Vendetta')
            """
        )
        conn.execute("delete from schema_migrations where version = 7")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        rows = check.execute(
            """
            select hand_number, hand_position, display_name, type_category, bottomed
            from game_mulligan_hands
            order by hand_position
            """
        ).fetchall()

    assert len(rows) == 7
    assert all(hand_number == 2 for hand_number, *_ in rows)
    assert rows[-1] == (2, 7, "Ancient Vendetta", "Sorcery", 1)
    assert all(bottomed == 0 for *_, bottomed in rows[:-1])


def test_migration_v7_skips_unreconcilable_mulligan_lines(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-29T00:00:00')"
        )
        conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at)
            values ('game-1', 'session-1', 'match-1', '2026-07-29T00:05:00')
            """
        )
        # Two mulligans but the console line names only one card: ambiguous.
        conn.execute(
            "insert into participants (id, game_id, role, mulligans) values ('participant-1', 'game-1', 'player', 2)"
        )
        conn.executemany(
            """
            insert into game_opening_hand_cards (game_id, participant_id, display_name, type_category, hand_position, copy_number)
            values ('game-1', 'participant-1', ?, 'Land', ?, 1)
            """,
            [("Swamp", position) for position in range(1, 6)],
        )
        conn.execute(
            """
            insert into console_logs (session_id, created_at, match_started_at, text)
            values ('session-1', '2026-07-29T00:06:00', '2026-07-29T00:05:00', '🔄 Mulliganed away: Duress')
            """
        )
        conn.execute("delete from schema_migrations where version = 7")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        count = check.execute("select count(*) from game_mulligan_hands").fetchone()[0]

    assert count == 0


def test_migration_v8_merges_explored_cards_into_draw_order(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-30T00:00:00')"
        )
        conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
        conn.execute(
            "insert into games (id, session_id, match_id, started_at) values ('game-1', 'session-1', 'match-1', '2026-07-30T01:00:00')"
        )
        conn.execute(
            "insert into participants (id, game_id, role) values ('participant-1', 'game-1', 'player')"
        )
        conn.execute(
            "insert into game_participant_stats (game_id, participant_id, cards_drawn) values ('game-1', 'participant-1', 2)"
        )
        conn.executemany(
            """
            insert into game_drawn_cards (game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number)
            values ('game-1', 'participant-1', ?, ?, ?, ?, ?)
            """,
            [
                ("Swamp", "Land", 1, 3, 1),
                ("Corpses of the Lost", "Creature", 2, 7, 1),
            ],
        )
        conn.executemany(
            """
            insert into game_events (session_id, game_id, event_time, turn_number, actor_role, event_type, text)
            values ('session-1', 'game-1', ?, ?, 'player', 'zone', ?)
            """,
            [
                ("2026-07-30T01:01:00", 3, "[0:30] You: drew [Swamp]"),
                ("2026-07-30T01:03:00", 5, "[2:30] You: put [Soulstone Sanctuary] into your hand"),
                ("2026-07-30T01:05:00", 7, "[4:30] You: drew [Corpses of the Lost]"),
            ],
        )
        conn.execute("delete from schema_migrations where version = 8")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        rows = check.execute(
            """
            select draw_position, display_name, turn_number from game_drawn_cards
            where game_id = 'game-1' order by draw_position
            """
        ).fetchall()
        summary = check.execute(
            "select display_name, drawn_count from game_card_summary where game_id = 'game-1'"
        ).fetchall()
        stats = check.execute(
            "select cards_drawn from game_participant_stats where game_id = 'game-1'"
        ).fetchone()

    # The explored land lands between the two real draws, in event order.
    assert rows == [
        (1, "Swamp", 3),
        (2, "Soulstone Sanctuary", 5),
        (3, "Corpses of the Lost", 7),
    ]
    assert ("Soulstone Sanctuary", 1) in summary
    assert stats == (3,)


def test_migration_v22_backfills_ramped_lands_only(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-08-01T00:00:00')"
        )
        conn.execute("insert into matches (id, session_id) values ('match-1', 'session-1')")
        conn.execute(
            "insert into games (id, session_id, match_id, started_at) values ('game-1', 'session-1', 'match-1', '2026-08-01T01:00:00')"
        )
        conn.execute(
            "insert into participants (id, game_id, role) values ('participant-1', 'game-1', 'player')"
        )
        conn.execute(
            "insert into game_participant_stats (game_id, participant_id, cards_drawn) values ('game-1', 'participant-1', 1)"
        )
        conn.execute(
            "insert into game_drawn_cards (game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number) "
            "values ('game-1', 'participant-1', 'Forsaken Miner', 'Creature', 1, 2, 1)"
        )
        # A nonbasic land in the card DB, so the land filter can resolve it.
        conn.execute(
            "insert into cards (name, type_line, primary_type, first_seen_at) "
            "values ('Realm of Koh', 'Land', 'Land', '2026-01-01')"
        )
        conn.executemany(
            """
            insert into game_events (session_id, game_id, event_time, turn_number, actor_role, event_type, text)
            values ('session-1', 'game-1', ?, ?, 'player', 'zone', ?)
            """,
            [
                ("2026-08-01T01:01:00", 2, "[0:20] You: drew [Forsaken Miner]"),
                # Turn 3: a basic ramped in, plus a nonbasic land searched in.
                ("2026-08-01T01:02:00", 3, "[1:10] You: put [Forest] onto battlefield"),
                ("2026-08-01T01:02:30", 3, "[1:20] You: put [Realm of Koh] onto battlefield"),
                # A creature cheated into play must NOT be counted (source zone
                # is unknown from stored events).
                ("2026-08-01T01:03:00", 4, "[2:00] You: put [Desolation Prowler] onto battlefield"),
            ],
        )
        conn.execute("delete from schema_migrations where version = 22")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        names = [
            r[0]
            for r in check.execute(
                "select display_name from game_drawn_cards where game_id='game-1' order by draw_position"
            )
        ]
        stats = check.execute(
            "select cards_drawn from game_participant_stats where game_id='game-1'"
        ).fetchone()

    # Both lands are backfilled; the creature put onto the battlefield is not.
    assert "Forest" in names
    assert "Realm of Koh" in names
    assert "Desolation Prowler" not in names
    assert names.count("Forest") == 1  # not double-counted
    assert stats == (3,)  # 1 original + 2 ramped lands


def test_migration_v22_is_idempotent_across_reruns(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute("insert into tracker_sessions (id, started_at) values ('s', '2026-08-01T00:00:00')")
        conn.execute("insert into matches (id, session_id) values ('m', 's')")
        conn.execute("insert into games (id, session_id, match_id, started_at) values ('g', 's', 'm', '2026-08-01T01:00:00')")
        conn.execute("insert into participants (id, game_id, role) values ('p', 'g', 'player')")
        conn.execute("insert into game_participant_stats (game_id, participant_id, cards_drawn) values ('g', 'p', 0)")
        conn.execute(
            "insert into game_events (session_id, game_id, event_time, turn_number, actor_role, event_type, text) "
            "values ('s', 'g', '2026-08-01T01:02:00', 3, 'player', 'zone', '[1:10] You: put [Forest] onto battlefield')"
        )
        conn.execute("delete from schema_migrations where version = 22")
        AnalyticsStore.apply_pending_migrations(conn)
        # Force a second run: the per-game already-counted guard must skip it.
        conn.execute("delete from schema_migrations where version = 22")
        AnalyticsStore.apply_pending_migrations(conn)
        forests = conn.execute(
            "select count(*) from game_drawn_cards where game_id='g' and display_name='Forest'"
        ).fetchone()[0]
    assert forests == 1


def test_migration_v23_tags_ramped_lands_source(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute("insert into tracker_sessions (id, started_at) values ('s', '2026-08-01T00:00:00')")
        conn.execute("insert into matches (id, session_id) values ('m', 's')")
        conn.execute("insert into games (id, session_id, match_id, started_at) values ('g', 's', 'm', '2026-08-01T01:00:00')")
        conn.execute("insert into participants (id, game_id, role) values ('p', 'g', 'player')")
        conn.execute("insert into game_participant_stats (game_id, participant_id, cards_drawn) values ('g', 'p', 3)")
        # A land drawn naturally on turn 2, plus a Forest that v22 backfilled
        # from a turn-6 "put onto battlefield" event (source left NULL).
        conn.executemany(
            "insert into game_drawn_cards (game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number) values (?,?,?,?,?,?,?)",
            [
                ("g", "p", "Island", "Land", 1, 2, 1),
                ("g", "p", "Forest", "Land", 2, 6, 1),
            ],
        )
        conn.execute(
            "insert into game_events (session_id, game_id, event_time, turn_number, actor_role, event_type, text) "
            "values ('s', 'g', '2026-08-01T01:06:00', 6, 'player', 'zone', '[1:13] You: put [Forest] onto battlefield')"
        )
        conn.execute("delete from schema_migrations where version = 23")
        AnalyticsStore.apply_pending_migrations(conn)
        rows = dict(
            conn.execute(
                "select display_name, source from game_drawn_cards where game_id='g' order by draw_position"
            ).fetchall()
        )
    # The ramped Forest is tagged; the naturally drawn Island is untouched.
    assert rows == {"Island": None, "Forest": "ramp"}


def test_migration_v23_is_idempotent(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute("insert into tracker_sessions (id, started_at) values ('s', '2026-08-01T00:00:00')")
        conn.execute("insert into matches (id, session_id) values ('m', 's')")
        conn.execute("insert into games (id, session_id, match_id, started_at) values ('g', 's', 'm', '2026-08-01T01:00:00')")
        conn.execute("insert into participants (id, game_id, role) values ('p', 'g', 'player')")
        conn.execute("insert into game_participant_stats (game_id, participant_id, cards_drawn) values ('g', 'p', 1)")
        conn.execute(
            "insert into game_drawn_cards (game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number) "
            "values ('g', 'p', 'Forest', 'Land', 1, 6, 1)"
        )
        conn.execute(
            "insert into game_events (session_id, game_id, event_time, turn_number, actor_role, event_type, text) "
            "values ('s', 'g', '2026-08-01T01:06:00', 6, 'player', 'zone', '[1:13] You: put [Forest] onto battlefield')"
        )
        conn.execute("delete from schema_migrations where version = 23")
        AnalyticsStore.apply_pending_migrations(conn)
        conn.execute("delete from schema_migrations where version = 23")
        AnalyticsStore.apply_pending_migrations(conn)
        tagged = conn.execute(
            "select count(*) from game_drawn_cards where game_id='g' and source='ramp'"
        ).fetchone()[0]
    assert tagged == 1


def test_persist_drawn_cards_records_ramp_source(tmp_path):
    from mtga_tracker.analytics_persistence import persist_drawn_cards
    from mtga_tracker.state import CardEvent

    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute("insert into tracker_sessions (id, started_at) values ('s', '2026-08-01T00:00:00')")
        conn.execute("insert into matches (id, session_id) values ('m', 's')")
        conn.execute("insert into games (id, session_id, match_id, started_at) values ('g', 's', 'm', '2026-08-01T01:00:00')")
        conn.execute("insert into participants (id, game_id, role) values ('p', 'g', 'player')")
        drawn = CardEvent("Llanowar Elves", "player", card_type_category="Creature")
        ramped = CardEvent("Forest", "player", card_type_category="Land", source="ramp")
        persist_drawn_cards(
            conn, "g", "p", [drawn, ramped], refresh_display_name=lambda name: name
        )
        rows = dict(
            conn.execute(
                "select display_name, source from game_drawn_cards where game_id='g'"
            ).fetchall()
        )
    assert rows == {"Llanowar Elves": None, "Forest": "ramp"}


def test_migration_v9_deletes_post_concede_ghost_games(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-07-31T21:00:00')"
        )
        conn.executemany(
            "insert into matches (id, session_id) values (?, 'session-1')",
            (("match-6",), ("match-7",)),
        )
        # A real game and a ghost born the second it ended.
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, ended_at, total_turns, duration_seconds, outcome)
            values ('game-real', 'session-1', 'match-6', '2026-07-31T23:17:31', '2026-07-31T23:24:28', 17, 417, 'loss')
            """
        )
        conn.execute(
            "insert into game_turns (game_id, turn_number, duration_seconds) values ('game-real', 1, 30)"
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, ended_at, total_turns, duration_seconds, outcome)
            values ('game-ghost', 'session-1', 'match-7', '2026-07-31T23:24:28', '2026-07-31T23:24:28', 0, 0, 'loss')
            """
        )
        conn.execute(
            "insert into participants (id, game_id, role) values ('ghost-player', 'game-ghost', 'player')"
        )
        conn.execute(
            """
            insert into game_events (session_id, game_id, event_time, actor_role, event_type, text)
            values ('session-1', 'game-ghost', '2026-07-31T23:24:28', null, 'zone', 'cast [Firebending Lesson]')
            """
        )
        conn.execute("delete from schema_migrations where version = 9")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        games = [r[0] for r in check.execute("select id from games order by id")]
        matches = [r[0] for r in check.execute("select id from matches order by id")]
        events = check.execute("select count(*) from game_events where game_id='game-ghost'").fetchone()[0]

    assert games == ["game-real"]
    assert matches == ["match-6"]
    assert events == 0


def test_migration_v10_deletes_unknown_deck_games(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-04-26T21:00:00')"
        )
        conn.executemany(
            "insert into matches (id, session_id) values (?, 'session-1')",
            (("match-1",), ("match-2",)),
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, total_turns)
            values ('game-known', 'session-1', 'match-1', '2026-04-26T21:05:00', 'win', 9)
            """
        )
        conn.execute(
            "insert into participants (id, game_id, role, deck_name) values ('p-known', 'game-known', 'player', 'Mono Black Skellies')"
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, total_turns)
            values ('game-unknown', 'session-1', 'match-2', '2026-04-26T21:30:00', 'loss', 12)
            """
        )
        conn.execute(
            "insert into participants (id, game_id, role) values ('p-unknown', 'game-unknown', 'player')"
        )
        conn.execute(
            """
            insert into game_events (session_id, game_id, event_time, actor_role, event_type, text)
            values ('session-1', 'game-unknown', '2026-04-26T21:31:00', 'player', 'zone', 'cast [Something]')
            """
        )
        conn.execute("delete from schema_migrations where version = 10")
        AnalyticsStore.apply_pending_migrations(conn)

    with sqlite3.connect(db_path) as check:
        games = [r[0] for r in check.execute("select id from games order by id")]
        matches = [r[0] for r in check.execute("select id from matches order by id")]
        session = check.execute("select games_played, wins, losses from tracker_sessions").fetchone()

    assert games == ["game-known"]
    assert matches == ["match-1"]
    assert session == (1, 1, 0)


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


class _FakeCardDb:
    """Ability texts for the v24 reclassification test."""

    TEXTS = {
        101: ["{2}: Exile target card from a graveyard."],  # graveyard hate
        102: ["Destroy target nonblack creature."],  # real removal
        103: ["Exile all creatures."],  # wipe
    }

    def __init__(self, *args, **kwargs):
        pass

    def get_card_ability_texts(self, grp_id):
        return self.TEXTS.get(int(grp_id), [])


def _seed_removal_game(conn):
    conn.execute("insert into tracker_sessions (id, started_at) values ('s', '2026-08-01T00:00:00')")
    conn.execute("insert into matches (id, session_id) values ('m', 's')")
    conn.execute(
        "insert into games (id, session_id, match_id, started_at) values ('g', 's', 'm', '2026-08-01T01:00:00')"
    )
    conn.executemany(
        "insert into participants (id, game_id, role) values (?, 'g', ?)",
        [("p", "player"), ("o", "opponent")],
    )
    conn.executemany(
        "insert into cards (name, arena_id, first_seen_at) values (?, ?, '2026-01-01')",
        [("Grave Robber", 101), ("Doom Blade", 102), ("Farewell", 103)],
    )
    # Opponent played graveyard hate twice (miscounted as removal=2 before);
    # player played one real removal and drew one wipe.
    conn.executemany(
        "insert into game_card_summary (game_id, participant_id, display_name, played_count) "
        "values ('g', ?, ?, ?)",
        [
            ("o", "Grave Robber (Creature 2/2)", 2),
            ("p", "Doom Blade (Sorcery)", 1),
        ],
    )
    conn.execute(
        "insert into game_drawn_cards (game_id, participant_id, display_name, draw_position) "
        "values ('g', 'p', 'Farewell', 1)"
    )
    # The corrupted historical numbers the migration must correct.
    conn.executemany(
        "insert into game_participant_stats (game_id, participant_id, removal_played, removal_drawn, wipes_drawn) "
        "values ('g', ?, ?, 0, 0)",
        [("p", 0), ("o", 2)],
    )
    conn.commit()


def test_migration_v24_reclassifies_removal_stats(tmp_path, monkeypatch):
    import mtga_tracker.card_database as card_database_module

    monkeypatch.setattr(card_database_module, "CardDatabase", _FakeCardDb)
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        _seed_removal_game(conn)
        conn.execute("delete from schema_migrations where version = 24")
        AnalyticsStore.apply_pending_migrations(conn)
        rows = {
            pid: dict(removal_played=rp, removal_drawn=rd, wipes_drawn=wd)
            for pid, rp, rd, wd in conn.execute(
                "select participant_id, removal_played, removal_drawn, wipes_drawn "
                "from game_participant_stats where game_id='g'"
            )
        }
    # Graveyard hate no longer counts as removal; real removal now does.
    assert rows["o"]["removal_played"] == 0
    assert rows["p"]["removal_played"] == 1
    # The drawn wipe is picked up too.
    assert rows["p"]["wipes_drawn"] == 1


def test_migration_v24_leaves_stats_alone_without_card_texts(tmp_path, monkeypatch):
    import mtga_tracker.card_database as card_database_module

    class _EmptyDb(_FakeCardDb):
        TEXTS = {}

    monkeypatch.setattr(card_database_module, "CardDatabase", _EmptyDb)
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        _seed_removal_game(conn)
        conn.execute("delete from schema_migrations where version = 24")
        AnalyticsStore.apply_pending_migrations(conn)
        row = conn.execute(
            "select removal_played from game_participant_stats where participant_id='o'"
        ).fetchone()
    # No ability texts readable -> zeroing everything would be data loss.
    assert row[0] == 2
