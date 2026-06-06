import sqlite3

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.dashboard import dashboard_snapshot, render_dashboard_html


def test_dashboard_snapshot_and_html_render_latest_game(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-06-04T00:00:00')"
        )
        conn.execute(
            """
            insert into matches (id, session_id, format, queue, event_name)
            values ('match-1', 'session-1', 'Play', 'Play', 'Play')
            """
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds)
            values ('game-1', 'session-1', 'match-1', '2026-06-04T00:01:00', 'win', 240)
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values ('player-1', 'game-1', 'player', 'Boros Mouse', 1, 0)
            """
        )

    snapshot = dashboard_snapshot(db_path)
    html = render_dashboard_html(snapshot)

    assert snapshot["summary"]["games"] == 1
    assert snapshot["summary"]["wins"] == 1
    assert "Boros Mouse" in html
    assert "Standard Best-of-1" in html
