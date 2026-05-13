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
