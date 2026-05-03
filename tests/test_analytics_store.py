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

