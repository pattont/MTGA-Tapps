import json
import sqlite3
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.dashboard import (
    card_detail,
    DashboardHandler,
    dashboard_snapshot,
    deck_detail,
    game_detail,
    render_dashboard_html,
    search_cards,
)


def _sample_dashboard_db(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "insert into tracker_sessions (id, started_at) values ('session-1', '2026-06-04T00:00:00')"
        )
        conn.execute(
            """
            insert into matches (id, session_id, format, queue, event_name, best_of)
            values ('match-1', 'session-1', 'Play', 'Play', 'Play', 1)
            """
        )
        conn.execute(
            """
            insert into games (
                id, session_id, match_id, game_number, started_at, outcome,
                outcome_reason, duration_seconds, total_turns, player_turns, opponent_turns
            )
            values (
                'game-1', 'session-1', 'match-1', 1, '2026-06-04T00:01:00', 'win',
                'opponent_conceded', 240, 8, 4, 4
            )
            """
        )
        conn.execute(
            """
            insert into participants (
                id, game_id, seat_id, role, display_name, deck_name, went_first,
                mulligans, opening_hand_size, starting_life, ending_life
            )
            values (
                'player-1', 'game-1', 1, 'player', 'Tapps', 'Boros Mouse', 1,
                0, 7, 20, 12
            )
            """
        )
        conn.execute(
            """
            insert into participants (
                id, game_id, seat_id, role, display_name, starting_life, ending_life
            )
            values ('opponent-1', 'game-1', 2, 'opponent', 'Opponent', 20, 0)
            """
        )
        conn.execute(
            """
            insert into games (
                id, session_id, match_id, game_number, started_at, outcome,
                duration_seconds, total_turns, player_turns, opponent_turns
            )
            values ('game-2', 'session-1', 'match-1', 2, '2026-06-04T00:10:00', 'loss', 300, 10, 5, 5)
            """
        )
        conn.execute(
            """
            insert into participants (
                id, game_id, seat_id, role, display_name, deck_name, went_first,
                mulligans, opening_hand_size, starting_life, ending_life
            )
            values (
                'player-2', 'game-2', 1, 'player', 'Tapps', 'Boros Mouse', 0,
                1, 6, 20, 0
            )
            """
        )
        conn.execute(
            """
            insert into participants (
                id, game_id, seat_id, role, display_name, starting_life, ending_life
            )
            values ('opponent-2', 'game-2', 2, 'opponent', 'Opponent', 20, 7)
            """
        )
        conn.executemany(
            """
            insert into game_turns (
                game_id, turn_number, seat_id, duration_seconds, timing_source
            ) values (?, ?, ?, ?, ?)
            """,
            [
                ("game-1", 1, 1, 40, "live"),
                ("game-1", 2, 2, 30, "live"),
                ("game-1", 3, 1, 20, "estimated_header_events"),
                ("game-2", 1, 2, 45, "live"),
                ("game-2", 2, 1, 25, "live"),
                ("game-2", 3, 2, 35, "live"),
            ],
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
        conn.executemany(
            """
            insert into game_events (
                session_id, match_id, game_id, event_time, elapsed_seconds, turn_number,
                phase, step, actor_role, event_type, text, player_life, opponent_life
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "session-1",
                    "match-1",
                    "game-1",
                    "2026-06-04T00:01:05",
                    5,
                    1,
                    "beginning",
                    "upkeep",
                    "player",
                    "turn",
                    "Turn 1 begins",
                    20,
                    20,
                ),
                (
                    "session-1",
                    "match-1",
                    "game-1",
                    "2026-06-04T00:03:00",
                    120,
                    4,
                    "combat",
                    "damage",
                    "player",
                    "damage",
                    "Mouse Mentor attacks",
                    12,
                    0,
                ),
            ],
        )
    return db_path


def _dashboard_handler_for(db_path):
    class TestDashboardHandler(DashboardHandler):
        pass

    TestDashboardHandler.db_path = db_path
    return TestDashboardHandler


def test_dashboard_snapshot_and_html_render_latest_game(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    snapshot = dashboard_snapshot(db_path)
    html = render_dashboard_html(snapshot)

    assert snapshot["summary"]["games"] == 2
    assert snapshot["summary"]["wins"] == 1
    assert snapshot["draw_quality"][1]["known_draws"] == 1
    assert snapshot["drawn_cards"][0]["display_name"] == "Llanowar Elves"
    assert snapshot["momentum"][0]["split"] == "After a win"
    assert snapshot["recent"][0]["player_avg_turn_seconds"] == 25.0
    assert snapshot["recent"][0]["opponent_avg_turn_seconds"] == 40.0
    # Bo1 matches duplicate Recent Games rows, so the matches section is Bo3-only.
    assert snapshot["matches"] == []
    assert snapshot["sessions"][0]["session_id"] == "session-1"
    assert snapshot["sessions"][0]["games"] == 2
    assert "Boros Mouse" in html
    assert "Draw Quality" in html
    assert "Visible Drawn Cards" in html
    assert "Momentum" in html
    assert "Llanowar Elves" in html
    assert "Standard Best-of-1" in html


def test_dashboard_snapshot_missing_db_does_not_create_file(tmp_path):
    db_path = tmp_path / "missing.sqlite3"

    with pytest.raises(FileNotFoundError, match="Dashboard database not found"):
        dashboard_snapshot(db_path)

    assert not db_path.exists()


def test_dashboard_handler_serves_snapshot_json(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/snapshot")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 200
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    assert response.getheader("Cache-Control") == "no-store"
    payload = json.loads(body)
    assert payload["summary"]["games"] == 2
    assert payload["decks"][0]["deck_name"] == "Boros Mouse"
    assert payload["recent"][0]["format_label"] == "Standard Best-of-1 (Unranked)"


def test_dashboard_handler_reports_missing_snapshot_db(tmp_path):
    db_path = tmp_path / "missing.sqlite3"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/snapshot")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 404
    assert response.getheader("Cache-Control") == "no-store"
    assert "Dashboard database not found" in body
    assert not db_path.exists()


def test_dashboard_handler_serves_built_frontend_index(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
    handler = type(
        "TestDashboardHandler",
        (DashboardHandler,),
        {"db_path": db_path, "static_dir": dist_dir},
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert "<div id='root'></div>" in body


def test_dashboard_handler_blocks_static_path_escape(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    handler = type(
        "TestDashboardHandler",
        (DashboardHandler,),
        {"db_path": db_path, "static_dir": dist_dir},
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/../secret.txt")
        response = conn.getresponse()
        response.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 404


def test_dashboard_handler_blocks_symlinked_static_directory_index_escape(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    dist_dir = tmp_path / "dist"
    sub_dir = dist_dir / "sub"
    sub_dir.mkdir(parents=True)
    secret_path = tmp_path / "secret.html"
    secret_path.write_text("<!doctype html>secret", encoding="utf-8")
    try:
        (sub_dir / "index.html").symlink_to(secret_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unsupported: {exc}")
    handler = type(
        "TestDashboardHandler",
        (DashboardHandler,),
        {"db_path": db_path, "static_dir": dist_dir},
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/sub")
        response = conn.getresponse()
        response.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 404


def test_dashboard_snapshot_includes_local_only_deck_visual(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values ('game-1', 'player-1', 12345, 'Mouse Mentor', 'Creature', 3)
            """
        )

    snapshot = dashboard_snapshot(db_path)
    deck = snapshot["decks"][0]

    assert deck["deck_visual"]["card_name"] == "Mouse Mentor"
    assert deck["deck_visual"]["card_id"] == 12345
    assert deck["deck_visual"]["type_category"] == "Creature"
    assert deck["deck_visual"]["image_url"] == (
        "https://api.scryfall.com/cards/named?fuzzy=Mouse%20Mentor&format=image&version=art_crop"
    )
    assert deck["deck_visual"]["source"] == "local_metadata"


def test_dashboard_snapshot_includes_stable_game_ids(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    snapshot = dashboard_snapshot(db_path)

    assert snapshot["draw_quality"][0]["game_id"] == "game-2"
    assert snapshot["recent"][0]["game_id"] == "game-2"


def test_dashboard_snapshot_supports_deck_and_format_filters(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into matches (id, session_id, format, queue, event_name)
            values ('match-2', 'session-1', 'Constructed_BestOf3', 'Ladder', 'Ladder')
            """
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds)
            values ('game-3', 'session-1', 'match-2', '2026-06-05T00:01:00', 'win', 200)
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values ('player-3', 'game-3', 'player', 'Izzet Wizards', 1, 0)
            """
        )

    unfiltered = dashboard_snapshot(db_path)
    assert unfiltered["summary"]["games"] == 3
    assert unfiltered["filters"] == {"deck": None, "format": None, "days": None}
    assert "Izzet Wizards" in unfiltered["filter_options"]["decks"]
    assert {"raw_format": "Play", "format_label": "Standard Best-of-1 (Unranked)"} in unfiltered[
        "filter_options"
    ]["formats"]

    by_deck = dashboard_snapshot(db_path, deck="Izzet Wizards")
    assert by_deck["summary"]["games"] == 1
    assert by_deck["summary"]["wins"] == 1
    assert [row["deck_name"] for row in by_deck["decks"]] == ["Izzet Wizards"]
    assert [row["game_id"] for row in by_deck["recent"]] == ["game-3"]
    # Filter options stay global so the UI can switch between decks.
    assert "Boros Mouse" in by_deck["filter_options"]["decks"]

    by_format = dashboard_snapshot(db_path, fmt="Play")
    assert by_format["summary"]["games"] == 2
    assert [row["raw_formats"] for row in by_format["formats"]] == ["Play"]
    assert [row["format_label"] for row in by_format["formats"]] == [
        "Standard Best-of-1 (Unranked)"
    ]

    combined = dashboard_snapshot(db_path, deck="Boros Mouse", fmt="Constructed_BestOf3")
    assert combined["summary"]["games"] == 0


def test_dashboard_snapshot_groups_formats_and_excludes_jump_in(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into matches (id, session_id, format, queue, event_name, best_of)
            values (?, 'session-1', ?, ?, ?, ?)
            """,
            [
                ("match-mwm1", "MWM_SlowStart_20260602", "MWM_SlowStart_20260602", "MWM", 1),
                ("match-mwm2", "MWM_Brawl_20260623", "MWM_Brawl_20260623", "MWM", 1),
                ("match-ladder", "Ladder", "Ladder", "Ladder", 1),
                ("match-unknown", "Unknown", None, None, 1),
                ("match-jump", "Jump_In_MSH", "Jump_In_MSH", "Jump_In", 1),
                ("match-bo3", "TraditionalLadder", "TraditionalLadder", "TraditionalLadder", 3),
            ],
        )
        games = [
            ("game-mwm1", "match-mwm1", "2026-06-02T00:01:00", "win"),
            ("game-mwm2", "match-mwm2", "2026-06-23T00:01:00", "loss"),
            ("game-ladder", "match-ladder", "2026-06-24T00:01:00", "win"),
            ("game-unknown", "match-unknown", "2026-06-24T01:01:00", "loss"),
            ("game-jump", "match-jump", "2026-06-25T00:01:00", "win"),
            ("game-bo3a", "match-bo3", "2026-06-26T00:01:00", "win"),
            ("game-bo3b", "match-bo3", "2026-06-26T00:20:00", "win"),
        ]
        conn.executemany(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds)
            values (?, 'session-1', ?, ?, ?, 200)
            """,
            games,
        )
        conn.executemany(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values (?, ?, 'player', 'Boros Mouse', 1, 0)
            """,
            [(f"player-{game_id}", game_id) for game_id, *_ in games],
        )

    snapshot = dashboard_snapshot(db_path)

    # Jump In games are fully untracked.
    assert snapshot["summary"]["games"] == 8
    assert all(row["game_id"] != "game-jump" for row in snapshot["recent"])
    assert all("Jump" not in opt["raw_format"] for opt in snapshot["filter_options"]["formats"])

    by_label = {row["format_label"]: row for row in snapshot["formats"]}
    # Missing metadata remains unknown rather than being assumed to be Play.
    assert by_label["Standard Best-of-1 (Unranked)"]["games"] == 2
    assert by_label["Standard Best-of-1 (Unranked)"]["raw_formats"] == "Play"
    assert by_label["Unknown"]["games"] == 1
    assert by_label["Unknown"]["raw_formats"] == "Unknown"
    assert by_label["Standard Best-of-1 (Ranked)"]["games"] == 1
    assert by_label["Standard Best-of-3 (Ranked)"]["games"] == 2
    # Midweek Magic rolls up into a single category with a separate breakdown.
    assert by_label["Midweek Magic"]["games"] == 2
    assert "Midweek Magic - Slow Start" not in by_label
    assert {row["format_label"]: row["games"] for row in snapshot["midweek_formats"]} == {
        "Midweek Magic - Slow Start": 1,
        "Midweek Magic - Brawl": 1,
    }

    # Matches section only reports Bo3 matches.
    assert [row["match_id"] for row in snapshot["matches"]] == ["match-bo3"]
    assert snapshot["matches"][0]["record"] == "2-0"
    assert snapshot["matches"][0]["format_label"] == "Standard Best-of-3 (Ranked)"


def test_dashboard_snapshot_days_filter_keeps_recent_games(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    from datetime import datetime, timedelta

    recent_started = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds)
            values ('game-3', 'session-1', 'match-1', ?, 'win', 200)
            """,
            (recent_started,),
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values ('player-3', 'game-3', 'player', 'Boros Mouse', 1, 0)
            """
        )

    snapshot = dashboard_snapshot(db_path, days=7)
    assert snapshot["summary"]["games"] == 1
    assert snapshot["recent"][0]["game_id"] == "game-3"
    assert snapshot["filters"]["days"] == 7


def test_dashboard_snapshot_includes_win_rate_trend(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    snapshot = dashboard_snapshot(db_path)

    assert [row["game_id"] for row in snapshot["trend"]] == ["game-1", "game-2"]
    assert snapshot["trend"][0]["outcome"] == "win"
    assert snapshot["trend"][1]["outcome"] == "loss"


def test_dashboard_handler_applies_snapshot_query_filters(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/snapshot?deck=Boros%20Mouse&format=Play&days=bogus")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 200
    payload = json.loads(body)
    assert payload["summary"]["games"] == 2
    assert payload["filters"] == {"deck": "Boros Mouse", "format": "Play", "days": None}


def test_deck_detail_reports_cards_openers_and_mulligans(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count, drawn_count
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 11, "Mouse Mentor (Creature 2/1)", "Creature", 2, 0),
                ("game-2", "player-2", 11, "Mouse Mentor (Creature 2/1)", "Creature", 1, 0),
                ("game-2", "player-2", 12, "Mountain (Land)", "Land", 3, 0),
            ],
        )
        conn.execute(
            """
            insert into game_opening_hand_cards (
                game_id, participant_id, display_name, type_category, hand_position, copy_number
            )
            values ('game-2', 'player-2', 'Mountain', 'Land', 1, 1)
            """
        )
        # Visible draws are recorded under the clean card name in game_drawn_cards.
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number
            )
            values ('game-2', 'player-2', 'Mouse Mentor', 'Creature', 1, 3, 1)
            """
        )

    detail = deck_detail(db_path, "Boros Mouse")

    assert detail["deck_name"] == "Boros Mouse"
    assert detail["summary"] == {"games": 2, "wins": 1, "losses": 1, "draws": 0, "win_rate": 50.0}
    assert detail["profile"]["avg_mulligans"] == 0.5
    assert detail["profile"]["on_play_pct"] == 50.0
    assert detail["profile"]["avg_duration_seconds"] == 270.0

    mentor = next(row for row in detail["card_performance"] if row["display_name"] == "Mouse Mentor")
    assert mentor["games_seen"] == 2
    assert mentor["times_played"] == 3
    assert mentor["times_drawn"] == 1
    assert mentor["win_rate_when_seen"] == 50.0

    # game-1 opener has a Mountain (from the shared fixture); game-2 adds another.
    mountain = next(row for row in detail["opening_hands"] if row["display_name"] == "Mountain")
    assert mountain["games_in_opener"] == 2

    assert detail["mulligans"] == [
        {"mulligans": 0, "games": 1, "wins": 1, "losses": 0, "win_rate": 100.0},
        {"mulligans": 1, "games": 1, "wins": 0, "losses": 1, "win_rate": 0.0},
    ]
    assert [row["game_id"] for row in detail["recent"]] == ["game-2", "game-1"]
    assert detail["recent"][0]["play_draw"] == "On the draw"
    assert [row["game_id"] for row in detail["trend"]] == ["game-1", "game-2"]


def test_deck_detail_applies_format_filter_to_all_sections(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into matches (id, session_id, format, queue, event_name, best_of)
            values ('match-2', 'session-1', 'Constructed_BestOf3', 'Ladder', 'Ladder', 3)
            """
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds, total_turns)
            values ('game-3', 'session-1', 'match-2', '2026-06-05T00:01:00', 'win', 200, 9)
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values ('player-3', 'game-3', 'player', 'Boros Mouse', 1, 0)
            """
        )
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 11, "Mouse Mentor (Creature 2/1)", "Creature", 2),
                ("game-3", "player-3", 12, "Ladder Specialist (Creature 2/2)", "Creature", 1),
            ],
        )
        conn.execute(
            """
            insert into game_opening_hand_cards (
                game_id, participant_id, display_name, type_category, hand_position, copy_number
            )
            values ('game-3', 'player-3', 'Ladder Specialist', 'Creature', 1, 1)
            """
        )
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number
            )
            values ('game-3', 'player-3', 'Ladder Specialist', 'Creature', 1, 2, 1)
            """
        )

    detail = deck_detail(db_path, "Boros Mouse", fmt="Constructed_BestOf3")

    assert detail["summary"]["games"] == 1
    assert [row["raw_formats"] for row in detail["formats"]] == ["Constructed_BestOf3"]
    assert [row["format_label"] for row in detail["formats"]] == [
        "Standard Best-of-3 (Unranked)"
    ]
    assert [row["game_id"] for row in detail["recent"]] == ["game-3"]
    assert [row["game_id"] for row in detail["trend"]] == ["game-3"]
    assert [row["display_name"] for row in detail["card_performance"]] == ["Ladder Specialist"]
    assert [row["display_name"] for row in detail["opening_hands"]] == ["Ladder Specialist"]
    assert detail["card_performance"][0]["times_drawn"] == 1


def test_deck_detail_rejects_unknown_deck(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    with pytest.raises(LookupError, match="No recorded games for deck"):
        deck_detail(db_path, "Missing Deck")


def test_game_detail_reports_header_cards_and_timeline(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values ('game-1', 'player-1', 101, 'Mouse Mentor (Creature 2/1)', 'Creature', 2)
            """
        )

    detail = game_detail(db_path, "game-1")

    assert detail["game"]["game_id"] == "game-1"
    assert detail["game"]["outcome"] == "win"
    assert detail["game"]["outcome_reason"] == "opponent_conceded"
    assert detail["game"]["format_label"] == "Standard Best-of-1 (Unranked)"
    assert detail["game"]["best_of"] == 1
    assert detail["game"]["total_turns"] == 8
    assert detail["player"]["deck_name"] == "Boros Mouse"
    assert detail["player"]["went_first"] == 1
    assert detail["player"]["mulligans"] == 0
    assert detail["player"]["opening_hand_size"] == 7
    assert detail["player"]["ending_life"] == 12
    assert detail["opponent"]["ending_life"] == 0
    assert detail["opening_hand"] == [
        {"display_name": "Mountain", "type_category": "Land", "hand_position": 1, "copy_number": 1}
    ]
    assert detail["drawn"] == [
        {
            "display_name": "Llanowar Elves",
            "type_category": "Creature",
            "turn_number": 2,
            "draw_position": 1,
            "copy_number": 1,
        }
    ]
    assert detail["draw_quality"] == {
        "total_draws": 1,
        "identified_draws": 1,
        "land_draws": 0,
        "land_draw_pct": 0.0,
        "is_flood": False,
    }
    assert detail["turn_timing"] == {
        "player": {"total_seconds": 60, "turns_timed": 2, "avg_seconds": 30.0},
        "opponent": {"total_seconds": 30, "turns_timed": 1, "avg_seconds": 30.0},
    }
    assert detail["turns"] == [
        {
            "turn_number": 1,
            "seat_id": 1,
            "started_at": None,
            "ended_at": None,
            "duration_seconds": 40,
            "timing_source": "live",
            "role": "player",
        },
        {
            "turn_number": 2,
            "seat_id": 2,
            "started_at": None,
            "ended_at": None,
            "duration_seconds": 30,
            "timing_source": "live",
            "role": "opponent",
        },
        {
            "turn_number": 3,
            "seat_id": 1,
            "started_at": None,
            "ended_at": None,
            "duration_seconds": 20,
            "timing_source": "estimated_header_events",
            "role": "player",
        },
    ]
    assert detail["cards_played"] == [
        {"display_name": "Mouse Mentor", "type_category": "Creature", "played_count": 2}
    ]
    assert [row["event_type"] for row in detail["timeline"]] == ["turn", "damage"]
    assert detail["life_curve"] == [
        {"turn_number": 1, "player_life": 20, "opponent_life": 20},
        {"turn_number": 4, "player_life": 12, "opponent_life": 0},
    ]


def test_game_detail_marks_flood_when_over_half_of_draws_are_lands(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 5)
            """
        )
        conn.executemany(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category,
                draw_position, turn_number, copy_number
            ) values ('game-1', 'player-1', ?, 'Land', ?, ?, 1)
            """,
            [
                ("Plains", 2, 3),
                ("Mountain", 3, 4),
                ("Restless Anchorage", 4, 5),
            ],
        )

    detail = game_detail(db_path, "game-1")

    assert detail["draw_quality"] == {
        "total_draws": 5,
        "identified_draws": 4,
        "land_draws": 3,
        "land_draw_pct": 60.0,
        "is_flood": True,
    }


def test_game_detail_does_not_mark_exactly_half_land_draws_as_flood(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 2)
            """
        )
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category,
                draw_position, turn_number, copy_number
            ) values ('game-1', 'player-1', 'Plains', 'Land', 2, 3, 1)
            """
        )

    quality = game_detail(db_path, "game-1")["draw_quality"]

    assert quality["land_draw_pct"] == 50.0
    assert quality["is_flood"] is False


def test_game_detail_rejects_unknown_game(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    with pytest.raises(LookupError, match="No recorded game"):
        game_detail(db_path, "missing-game")


def test_dashboard_handler_serves_game_detail(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/game?id=game-1")
        response = conn.getresponse()
        body = response.read().decode("utf-8")

        conn.request("GET", "/api/game?id=missing-game")
        missing_response = conn.getresponse()
        missing_response.read()

        conn.request("GET", "/api/game")
        bad_response = conn.getresponse()
        bad_response.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 200
    payload = json.loads(body)
    assert payload["game"]["game_id"] == "game-1"
    assert payload["timeline"][0]["text"] == "Turn 1 begins"
    assert missing_response.status == 404
    assert bad_response.status == 400


def test_card_detail_reports_summary_by_deck_and_opener_impact(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 11, "Mouse Mentor (Creature 2/1)", "Creature", 2),
                ("game-2", "player-2", 11, "Mouse Mentor (Creature 2/1)", "Creature", 1),
                ("game-1", "opponent-1", 11, "Mouse Mentor (Creature 2/1)", "Creature", 1),
            ],
        )
        conn.execute(
            """
            insert into game_opening_hand_cards (
                game_id, participant_id, display_name, type_category, hand_position, copy_number
            )
            values ('game-2', 'player-2', 'Mouse Mentor', 'Creature', 2, 1)
            """
        )
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number
            )
            values ('game-2', 'player-2', 'Mouse Mentor', 'Creature', 2, 4, 1)
            """
        )

    detail = card_detail(db_path, "Mouse Mentor")

    assert detail["card_name"] == "Mouse Mentor"
    assert detail["summary"] == {
        "games_seen": 2,
        "total_played": 3,
        "wins": 1,
        "losses": 1,
        "win_rate": 50.0,
    }
    assert detail["all_usage"] == {
        "games_seen": 2,
        "total_played": 4,
        "player_games_seen": 2,
        "player_played": 3,
        "opponent_games_seen": 1,
        "opponent_played": 1,
    }
    assert detail["by_role"] == [
        {
            "role": "player",
            "side_label": "You",
            "games_seen": 2,
            "total_played": 3,
            "wins": 1,
            "losses": 1,
            "win_rate": 50.0,
        },
        {
            "role": "opponent",
            "side_label": "Opponent",
            "games_seen": 1,
            "total_played": 1,
            "wins": 0,
            "losses": 1,
            "win_rate": 0.0,
        },
    ]
    assert detail["by_deck"] == [
        {
            "deck_name": "Boros Mouse",
            "games_seen": 2,
            "total_played": 3,
            "wins": 1,
            "losses": 1,
            "win_rate": 50.0,
        }
    ]
    assert detail["opener_impact"] == {
        "games_in_opener": 1,
        "wins": 0,
        "losses": 1,
        "win_rate": 0.0,
        "times_drawn": 1,
    }
    assert detail["image_url"] == (
        "https://api.scryfall.com/cards/named?fuzzy=Mouse%20Mentor&format=image&version=art_crop"
    )


def test_card_detail_rejects_unknown_card(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    with pytest.raises(LookupError, match="No recorded card"):
        card_detail(db_path, "Missing Card")


def test_card_detail_supports_cards_seen_only_from_opponents(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, display_name, type_category, played_count
            ) values ('game-1', 'opponent-1', 'Opponent Tech', 'Instant', 2)
            """
        )

    detail = card_detail(db_path, "Opponent Tech")

    assert detail["summary"]["games_seen"] == 0
    assert detail["all_usage"]["games_seen"] == 1
    assert detail["all_usage"]["opponent_played"] == 2
    assert detail["by_deck"] == []


def test_card_search_finds_partial_names_and_ranks_prefixes(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, display_name, type_category, played_count
            ) values (?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", "Sheltered by Ghosts (Enchantment)", "Enchantment", 1),
                ("game-2", "player-2", "Sheltered by Ghosts (Enchantment)", "Enchantment", 2),
                ("game-1", "opponent-1", "Sheltered by Ghosts (Enchantment)", "Enchantment", 2),
                ("game-1", "player-1", "Ghost Vacuum (Artifact)", "Artifact", 1),
            ],
        )

    results = search_cards(db_path, "ghost")

    assert [row["card_name"] for row in results] == ["Ghost Vacuum", "Sheltered by Ghosts"]
    sheltered = results[1]
    assert sheltered["type_category"] == "Enchantment"
    assert sheltered["games_seen"] == 2
    assert sheltered["deck_count"] == 1
    assert sheltered["total_played"] == 5


def test_dashboard_handler_serves_card_search(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, display_name, type_category, played_count
            ) values ('game-1', 'player-1', 'Sheltered by Ghosts', 'Enchantment', 1)
            """
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/cards?q=ghost&limit=5")
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))

        conn.request("GET", "/api/cards")
        bad_response = conn.getresponse()
        bad_response.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert body[0]["card_name"] == "Sheltered by Ghosts"
    assert bad_response.status == 400


def test_dashboard_handler_serves_card_detail(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values ('game-1', 'player-1', 11, 'Mouse Mentor (Creature 2/1)', 'Creature', 2)
            """
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/card?name=Mouse%20Mentor")
        response = conn.getresponse()
        body = response.read().decode("utf-8")

        conn.request("GET", "/api/card?name=Missing%20Card")
        missing_response = conn.getresponse()
        missing_response.read()

        conn.request("GET", "/api/card")
        bad_response = conn.getresponse()
        bad_response.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 200
    payload = json.loads(body)
    assert payload["card_name"] == "Mouse Mentor"
    assert payload["summary"]["games_seen"] == 1
    assert missing_response.status == 404
    assert bad_response.status == 400


def test_dashboard_handler_serves_deck_detail(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/deck?name=Boros%20Mouse&format=Play")
        response = conn.getresponse()
        body = response.read().decode("utf-8")

        conn.request("GET", "/api/deck?name=Missing%20Deck")
        missing_response = conn.getresponse()
        missing_response.read()

        conn.request("GET", "/api/deck")
        bad_response = conn.getresponse()
        bad_response.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert response.status == 200
    payload = json.loads(body)
    assert payload["deck_name"] == "Boros Mouse"
    assert payload["summary"]["games"] == 2
    assert missing_response.status == 404
    assert bad_response.status == 400


def test_dashboard_snapshot_deck_visual_prefers_nonland_cards(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 1, "Mountain (Land)", "Land", 9),
                ("game-1", "player-1", 2, "Emberheart Challenger (Creature)", "Creature", 2),
            ],
        )

    snapshot = dashboard_snapshot(db_path)
    deck = snapshot["decks"][0]

    assert deck["deck_visual"]["card_name"] == "Emberheart Challenger"
    assert deck["deck_visual"]["type_category"] == "Creature"


def test_dashboard_snapshot_deck_visual_ranking_has_stable_tiebreakers(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into games (id, session_id, match_id, started_at, outcome, duration_seconds)
            values ('game-3', 'session-1', 'match-1', '2026-06-04T00:20:00', 'win', 180)
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name, went_first, mulligans)
            values ('player-3', 'game-3', 'player', 'Boros Mouse', 1, 0)
            """
        )
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values (?, ?, ?, 'Shared Mascot', ?, 2)
            """,
            [
                ("game-1", "player-1", 11111, "Creature"),
                ("game-2", "player-2", 99999, "Artifact"),
                ("game-3", "player-3", 88888, "Artifact"),
            ],
        )

    snapshot = dashboard_snapshot(db_path)
    deck = snapshot["decks"][0]

    assert deck["deck_visual"]["card_name"] == "Shared Mascot"
    assert deck["deck_visual"]["card_id"] == 88888
    assert deck["deck_visual"]["type_category"] == "Artifact"
    assert deck["deck_visual"]["source"] == "local_metadata"
