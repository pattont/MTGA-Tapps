import sqlite3
from datetime import datetime, timedelta

from mtga_tracker.analytics import AnalyticsStore, SessionSnapshot


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
    conn.execute(
        "INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')"
    )
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
