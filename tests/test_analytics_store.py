import sqlite3
from datetime import datetime, timedelta

from mtga_tracker.analytics import AnalyticsStore, SessionSnapshot
from mtga_tracker.tracker_analytics import TrackerAnalyticsMixin


def test_analytics_store_uses_persistent_connection(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")

    first = store.connect()
    second = store.connect()

    assert first is second
    assert first is not None

    store.close()
    reopened = store.connect()

    assert reopened is not None
    assert reopened is not first
    store.close()


def test_analytics_store_records_console_log(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    started_at = datetime(2026, 5, 2, 12, 0, 0)
    created_at = started_at + timedelta(seconds=5)
    session = SessionSnapshot(
        session_id="session-1",
        started_at=started_at,
        games_played=1,
        wins=1,
        losses=0,
        unknown_results=0,
    )

    store.record_console_log(
        session,
        created_at=created_at,
        match_started_at=started_at,
        elapsed_seconds=5,
        turn_number=1,
        active_player=2,
        style="cast",
        text="[0:05] You: cast [Opt]",
        player_life=20,
        opponent_life=19,
    )
    store.close()

    with sqlite3.connect(db_path) as conn:
        session_row = conn.execute(
            "SELECT games_played, wins, losses, runtime_seconds FROM tracker_sessions WHERE id = ?",
            ("session-1",),
        ).fetchone()
        log_row = conn.execute(
            """
            SELECT session_id, elapsed_seconds, turn_number, active_player, style, text, player_life, opponent_life
            FROM console_logs
            """
        ).fetchone()

    assert session_row == (1, 1, 0, 5)
    assert log_row == (
        "session-1",
        5,
        1,
        2,
        "cast",
        "[0:05] You: cast [Opt]",
        20,
        19,
    )


def test_record_raw_payload_sanitizes_before_persisting(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)

    store.record_raw_payload(
        session_id="session-1",
        created_at=None,
        payload_type="unknown",
        payload_json='{"token":"secret","path":"/Users/travispatton/file","playerName":"Player#123"}',
    )
    store.close()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_type, payload_json FROM raw_game_payloads").fetchone()

    assert row[0] == "unknown"
    assert "secret" not in row[1]
    assert "/Users/travispatton/" not in row[1]
    assert "Player#123" not in row[1]
    assert "<redacted>" in row[1]


def test_tracker_raw_payload_snapshot_uses_current_match_context(tmp_path):
    from tests.test_tracker_combat_winner import make_tracker

    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.game_state.game_start_time = datetime(2026, 5, 13, 20, 0, 0)
    tracker.game_state.match_id = "match-1"
    tracker.game_state.game_number = 2

    tracker._record_raw_payload_snapshot(
        "connection_error",
        '{"playerName":"Player#123","path":"/Users/travispatton/log"}',
    )

    with sqlite3.connect(tracker._console_db_path) as conn:
        row = conn.execute(
            "SELECT match_id, game_id, payload_type, payload_json FROM raw_game_payloads"
        ).fetchone()

    assert row[0] == tracker._current_match_id()
    assert row[1] == tracker._current_game_id()
    assert row[2] == "connection_error"
    assert "Player#123" not in row[3]
    assert "/Users/travispatton/" not in row[3]


def test_current_game_id_is_stable_before_and_after_outcome_is_counted():
    from tests.test_tracker_combat_winner import make_tracker

    tracker = make_tracker()
    tracker.session_games_played = 3
    tracker.game_state.in_match = True
    tracker.game_state.game_number = 1

    active_game_id = tracker._current_game_id()
    tracker.session_games_played = 4
    tracker._session_stats_recorded_this_game = True

    assert active_game_id == "test-session:match:4:game:1"
    assert tracker._current_game_id() == active_game_id


def test_backfill_estimated_game_turn_times_is_idempotent_and_preserves_live_rows(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    assert conn is not None
    conn.execute(
        "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-01T12:00:00')"
    )
    conn.execute("INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')")
    conn.execute(
        """
        INSERT INTO games (id, session_id, match_id, ended_at, total_turns)
        VALUES ('game-1', 'session-1', 'match-1', '2026-07-01T12:03:00', 3)
        """
    )
    conn.executemany(
        """
        INSERT INTO participants (id, game_id, seat_id, role)
        VALUES (?, 'game-1', ?, ?)
        """,
        (("player-1", 2, "player"), ("opponent-1", 1, "opponent")),
    )
    conn.executemany(
        """
        INSERT INTO game_events (
            session_id, game_id, event_time, turn_number, text
        ) VALUES ('session-1', 'game-1', ?, ?, ?)
        """,
        (
            ("2026-07-01T12:00:10", 1, "Turn 1 - YOUR TURN"),
            ("2026-07-01T12:00:50", 2, "Turn 2 - OPPONENT'S TURN"),
            ("2026-07-01T12:02:00", 3, "Turn 3 - YOUR TURN"),
        ),
    )
    conn.execute(
        """
        INSERT INTO game_turns (
            game_id, turn_number, seat_id, duration_seconds, timing_source
        ) VALUES ('game-1', 1, 2, 5, 'live')
        """
    )

    inserted = AnalyticsStore.backfill_estimated_game_turn_times(conn)
    inserted_again = AnalyticsStore.backfill_estimated_game_turn_times(conn)
    rows = conn.execute(
        """
        SELECT turn_number, seat_id, duration_seconds, timing_source
        FROM game_turns
        ORDER BY turn_number
        """
    ).fetchall()
    store.close()

    assert inserted == 2
    assert inserted_again == 0
    assert rows == [
        (1, 2, 5, "live"),
        (2, 1, 70, "estimated_header_events"),
        (3, 2, 60, "estimated_header_events"),
    ]


def test_connection_uses_wal_and_waits_for_transient_writers(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    assert conn is not None

    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
    store.close()


def test_analytics_write_retries_transient_database_locks(monkeypatch, tmp_path):
    conn = sqlite3.connect(tmp_path / "analytics.sqlite3")
    conn.execute("CREATE TABLE retries (attempt INTEGER)")
    attempts = 0
    monkeypatch.setattr("mtga_tracker.tracker_analytics.time.sleep", lambda _seconds: None)

    def write_after_two_locks():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        conn.execute("INSERT INTO retries (attempt) VALUES (?)", (attempts,))

    TrackerAnalyticsMixin._run_analytics_write(conn, write_after_two_locks)

    assert attempts == 3
    assert conn.execute("SELECT attempt FROM retries").fetchall() == [(3,)]
    conn.close()


def test_backfill_recovered_game_turn_times_uses_exact_console_durations(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    assert conn is not None
    conn.execute(
        "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-01T12:00:00')"
    )
    conn.execute("INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')")
    conn.execute(
        """
        INSERT INTO games (
            id, session_id, match_id, started_at, ended_at, total_turns, outcome
        ) VALUES (
            'game-1', 'session-1', 'match-1',
            '2026-07-01T12:00:00', '2026-07-01T12:03:00', 3, 'win'
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO participants (id, game_id, seat_id, role)
        VALUES (?, 'game-1', ?, ?)
        """,
        (("player-1", 2, "player"), ("opponent-1", 1, "opponent")),
    )
    conn.executemany(
        """
        INSERT INTO game_events (
            session_id, game_id, event_time, turn_number, event_type, text
        ) VALUES ('session-1', 'game-1', ?, ?, 'turn', ?)
        """,
        (
            ("2026-07-01T12:00:10", 1, "Turn 1 - YOUR TURN"),
            ("2026-07-01T12:00:40", 2, "Turn 2 - OPPONENT'S TURN"),
            ("2026-07-01T12:01:50", 3, "Turn 3 - YOUR TURN"),
        ),
    )
    conn.executemany(
        """
        INSERT INTO console_logs (
            session_id, created_at, match_started_at, turn_number, text
        ) VALUES ('session-1', ?, '2026-07-01T12:00:00', ?, ?)
        """,
        (
            ("2026-07-01T12:00:40", 2, "Previous Turn (You): 30s"),
            ("2026-07-01T12:01:50", 3, "Previous Turn (Opponent): 1m 10s"),
        ),
    )

    inserted = AnalyticsStore.backfill_recovered_game_turn_times(conn)
    inserted_again = AnalyticsStore.backfill_recovered_game_turn_times(conn)
    rows = conn.execute(
        """
        SELECT turn_number, seat_id, duration_seconds, timing_source
        FROM game_turns
        ORDER BY turn_number
        """
    ).fetchall()
    store.close()

    assert inserted == 3
    assert inserted_again == 0
    assert rows == [
        (1, 2, 30, "recovered_previous_turn_logs"),
        (2, 1, 70, "recovered_previous_turn_logs"),
        (3, 2, 70, "recovered_previous_turn_logs"),
    ]


def test_migration_backfills_card_arena_ids_from_deck_cards(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()

    conn.execute(
        "INSERT INTO cards (name, first_seen_at) VALUES ('Llanowar Elves', datetime('now'))"
    )
    card_id = conn.execute(
        "SELECT id FROM cards WHERE name = 'Llanowar Elves'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO game_deck_cards (
            game_id, participant_id, card_id, arena_id, display_name,
            type_category, deck_zone, quantity
        )
        VALUES ('game-1', 'part-1', ?, 12345, 'Llanowar Elves', 'Creature', 'deck', 4)
        """,
        (card_id,),
    )
    # Remove the applied marker and re-run so the migration sees the new rows.
    conn.execute("DELETE FROM schema_migrations WHERE version = 2")
    AnalyticsStore.apply_pending_migrations(conn)

    arena_id = conn.execute(
        "SELECT arena_id FROM cards WHERE name = 'Llanowar Elves'"
    ).fetchone()[0]
    assert arena_id == 12345

    # Running again is a no-op.
    AnalyticsStore.apply_pending_migrations(conn)
    versions = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    assert {1, 2, 3} <= versions
    store.close()


def test_migration_backfills_summary_drawn_counts(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()

    conn.execute(
        "INSERT INTO cards (name, first_seen_at) VALUES ('Opt', datetime('now'))"
    )
    card_id = conn.execute("SELECT id FROM cards WHERE name = 'Opt'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO game_card_summary (
            game_id, participant_id, card_id, display_name, type_category, played_count
        )
        VALUES ('game-1', 'part-1', ?, 'Opt', 'Instant', 2)
        """,
        (card_id,),
    )
    for position in (1, 2, 3):
        conn.execute(
            """
            INSERT INTO game_drawn_cards (
                game_id, participant_id, card_id, display_name, type_category,
                draw_position, copy_number
            )
            VALUES ('game-1', 'part-1', ?, 'Opt', 'Instant', ?, ?)
            """,
            (card_id, position, position),
        )
    # A drawn-but-never-played card should gain its own summary row.
    conn.execute(
        "INSERT INTO cards (name, first_seen_at) VALUES ('Consider', datetime('now'))"
    )
    other_id = conn.execute("SELECT id FROM cards WHERE name = 'Consider'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO game_drawn_cards (
            game_id, participant_id, card_id, display_name, type_category,
            draw_position, copy_number
        )
        VALUES ('game-1', 'part-1', ?, 'Consider', 'Instant', 4, 1)
        """,
        (other_id,),
    )
    conn.execute("DELETE FROM schema_migrations WHERE version = 3")
    AnalyticsStore.apply_pending_migrations(conn)

    drawn = conn.execute(
        """
        SELECT drawn_count FROM game_card_summary
        WHERE game_id = 'game-1' AND participant_id = 'part-1' AND display_name = 'Opt'
        """
    ).fetchone()[0]
    assert drawn == 3
    row = conn.execute(
        """
        SELECT played_count, drawn_count FROM game_card_summary
        WHERE game_id = 'game-1' AND participant_id = 'part-1' AND display_name = 'Consider'
        """
    ).fetchone()
    assert row == (0, 1)
    store.close()


def test_migration_backfills_drawn_card_names_in_events(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()

    conn.execute(
        "insert into participants (id, game_id, role) values ('p1', 'g1', 'player')"
    )
    conn.executemany(
        """
        insert into game_drawn_cards (
            game_id, participant_id, display_name, type_category, draw_position,
            turn_number, copy_number
        ) values ('g1', 'p1', ?, 'Instant', ?, ?, 1)
        """,
        [("Opt", 1, 2), ("Consider", 2, 4)],
    )
    conn.executemany(
        """
        insert into game_events (
            session_id, game_id, event_time, turn_number, actor_role, event_type, text
        ) values ('s1', 'g1', ?, ?, 'player', 'draw', ?)
        """,
        [
            ("2026-06-04T00:01:00", 2, "[0:31] You: drew a card"),
            ("2026-06-04T00:02:00", 4, "[1:02] You: drew a card"),
        ],
    )
    # Ambiguous game: two events, one recorded draw, different turn counts.
    conn.execute(
        "insert into participants (id, game_id, role) values ('p2', 'g2', 'player')"
    )
    conn.execute(
        """
        insert into game_drawn_cards (
            game_id, participant_id, display_name, type_category, draw_position,
            turn_number, copy_number
        ) values ('g2', 'p2', 'Shock', 'Instant', 1, NULL, 1)
        """
    )
    conn.executemany(
        """
        insert into game_events (
            session_id, game_id, event_time, turn_number, actor_role, event_type, text
        ) values ('s1', 'g2', ?, NULL, 'player', 'draw', ?)
        """,
        [
            ("2026-06-04T00:03:00", "[0:10] You: drew a card"),
            ("2026-06-04T00:04:00", "[0:20] You: drew a card"),
        ],
    )
    conn.execute("DELETE FROM schema_migrations WHERE version = 5")
    AnalyticsStore.apply_pending_migrations(conn)

    texts = [
        row[0]
        for row in conn.execute(
            "SELECT text FROM game_events WHERE game_id = 'g1' ORDER BY event_time"
        )
    ]
    assert texts == ["[0:31] You: drew [Opt]", "[1:02] You: drew [Consider]"]
    ambiguous = [
        row[0]
        for row in conn.execute(
            "SELECT text FROM game_events WHERE game_id = 'g2' ORDER BY event_time"
        )
    ]
    assert all("drew a card" in text for text in ambiguous)
    store.close()
