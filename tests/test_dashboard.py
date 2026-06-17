import json
import sqlite3
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.dashboard import DashboardHandler, dashboard_snapshot, render_dashboard_html


def _sample_dashboard_db(tmp_path):
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
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds)
            values ('game-2', 'session-1', 'match-1', '2026-06-04T00:10:00', 'loss', 300)
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values ('player-2', 'game-2', 'player', 'Boros Mouse', 0, 1)
            """
        )
        conn.execute(
            """
            insert into game_opening_hand_cards (
                game_id, participant_id, display_name, type_category, hand_position, copy_number
            )
            values ('game-1', 'player-1', 'Mountain', 'Land', 1, 1)
            """
        )
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number
            )
            values ('game-1', 'player-1', 'Llanowar Elves', 'Creature', 1, 2, 1)
            """
        )
    return db_path


def test_dashboard_snapshot_and_html_render_latest_game(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    snapshot = dashboard_snapshot(db_path)
    html = render_dashboard_html(snapshot)

    assert snapshot["summary"]["games"] == 2
    assert snapshot["summary"]["wins"] == 1
    assert snapshot["draw_quality"][1]["known_draws"] == 1
    assert snapshot["drawn_cards"][0]["display_name"] == "Llanowar Elves"
    assert snapshot["momentum"][0]["split"] == "After a win"
    assert "Boros Mouse" in html
    assert "Draw Quality" in html
    assert "Visible Drawn Cards" in html
    assert "Momentum" in html
    assert "Llanowar Elves" in html
    assert "Standard Best-of-1" in html


def test_dashboard_handler_serves_snapshot_json(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    DashboardHandler.db_path = db_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/snapshot")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert response.status == 200
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    payload = json.loads(body)
    assert payload["summary"]["games"] == 2
    assert payload["decks"][0]["deck_name"] == "Boros Mouse"
    assert payload["recent"][0]["format_label"] == "Standard Best-of-1"
