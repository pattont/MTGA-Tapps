import json
import sqlite3
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.dashboard import (
    _timeline_text_segments,
    all_games,
    card_detail,
    DashboardHandler,
    dashboard_snapshot,
    deck_detail,
    game_detail,
    opponent_detail,
    audit_report,
    game_annotation,
    global_search,
    render_dashboard_html,
    reset_database,
    save_game_annotation,
    search_cards,
)


def test_reset_database_wipes_history_but_keeps_schema_and_backup(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    result = reset_database(db_path)

    from pathlib import Path

    assert result["ok"] is True
    backup = Path(result["backup"])
    assert backup.is_file() and ".pre-reset" in backup.name
    # The backup still holds the old games; the live DB is empty.
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] > 0
    with sqlite3.connect(db_path) as conn:
        for table in ("games", "matches", "participants", "tracker_sessions", "console_logs"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        # Schema, migrations, and the cards cache survive the reset.
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] > 0
    snapshot = dashboard_snapshot(db_path)
    assert snapshot["summary"]["games"] == 0
from mtga_tracker.format_normalizer import normalize_match_format


@pytest.mark.parametrize(
    ("text", "expected_cards"),
    [
        ("You: cast [Sheltered by Ghosts (Enchantment)]", ["Sheltered by Ghosts"]),
        (
            "You: [Sheltered by Ghosts] - exile target -> [Mouse Mentor (2/1)]",
            ["Sheltered by Ghosts", "Mouse Mentor"],
        ),
        (
            "Stack: [Sheltered by Ghosts (Enchantment)] [resolved]",
            ["Sheltered by Ghosts"],
        ),
        ("You: [Mouse Mentor] was exiled", ["Mouse Mentor"]),
        (
            "Combat: [Mouse Mentor (2/1)] dealt damage to [you]",
            ["Mouse Mentor"],
        ),
    ],
)
def test_timeline_text_segments_link_cards_across_event_formats(text, expected_cards):
    segments = _timeline_text_segments(
        text, {"Sheltered by Ghosts", "Mouse Mentor"}
    )

    assert [
        segment["card_name"] for segment in segments if segment["kind"] == "card"
    ] == expected_cards
    assert "".join(segment["text"] for segment in segments) == text


def test_timeline_text_segments_include_known_card_types():
    segments = _timeline_text_segments(
        "You: cast [Sheltered by Ghosts (Enchantment)]",
        {"Sheltered by Ghosts": "Enchantment"},
    )

    assert [segment for segment in segments if segment["kind"] == "card"] == [
        {
            "kind": "card",
            "text": "Sheltered by Ghosts",
            "card_name": "Sheltered by Ghosts",
            "card_type": "Enchantment",
        }
    ]


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
        conn.executemany(
            """
            insert into game_deck_cards (
                game_id, participant_id, card_id, arena_id, display_name,
                type_category, deck_zone, quantity
            ) values (?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 90001, "Mountain", "Land", "deck", 24),
                ("game-1", "player-1", 90002, "Mouse Mentor", "Creature", "deck", 4),
                ("game-1", "player-1", 90003, "Shock", "Instant", "deck", 32),
                ("game-1", "player-1", 90004, "Sheltered by Ghosts", "Enchantment", "sideboard", 2),
                ("game-2", "player-2", 90001, "Mountain", "Land", "deck", 24),
                ("game-2", "player-2", 90002, "Mouse Mentor", "Creature", "deck", 2),
                ("game-2", "player-2", 90003, "Shock", "Instant", "deck", 32),
                ("game-2", "player-2", 90004, "Sheltered by Ghosts", "Enchantment", "deck", 2),
            ],
        )
        conn.executemany(
            """
            insert into game_participant_stats (
                game_id, participant_id, attack_steps, attacking_creatures,
                attackers_lost, blocking_creatures, blockers_lost, damage_dealt,
                damage_taken, life_lost, self_damage, life_gained, cards_played,
                cards_drawn, cards_discarded, cards_milled, cards_exiled
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 4, 9, 1, 2, 3, 20, 6, 8, 2, 3, 12, 1, 0, 0, 1),
                ("game-1", "opponent-1", 2, 3, 3, 4, 1, 8, 18, 20, 2, 0, 10, 8, 1, 0, 0),
                ("game-2", "player-2", 2, 4, 2, 1, 0, 9, 18, 20, 2, 1, 9, 10, 2, 3, 0),
                ("game-2", "opponent-2", 3, 7, 1, 2, 2, 20, 8, 9, 1, 4, 11, 9, 0, 0, 2),
            ],
        )
        conn.execute(
            """
            insert into rank_snapshots (
                session_id, match_id, game_id, captured_at, season_ordinal,
                rank_class, rank_level, rank_step, rank_steps, raw_step,
                matches_won, matches_lost
            ) values (
                'session-1', 'match-1', 'game-1', '2026-06-04T00:05:01', 91,
                'Platinum', 3, 3, 6, 4, 60, 43
            )
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
                    (
                        "[0:20] Combat: [Mouse Mentor (2/1)] dealt 2 damage to "
                        "[Graveyard Trespasser (3/3)] [resolved] [you] [Skeleton Pirate]"
                    ),
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
    assert snapshot["recent"][0]["total_turns"] == 10
    assert "player_avg_turn_seconds" not in snapshot["recent"][0]
    assert "opponent_avg_turn_seconds" not in snapshot["recent"][0]
    assert snapshot["recent"][0]["is_flood"] is False
    assert snapshot["recent"][0]["is_screw"] is False
    assert snapshot["rank_progress"][0]["rank_label"] == "Platinum 3 (4/6)"
    assert snapshot["rank_progress"][0]["rank_score"] == 82
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


def test_fallback_recent_games_combines_lands_seen_with_ceiling_percentage(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category,
                draw_position, turn_number, copy_number
            ) values ('game-1', 'player-1', 'Mouse Mentor', 'Creature', 2, 3, 1)
            """
        )

    html = render_dashboard_html(dashboard_snapshot(db_path))

    assert "1 (34%)" in html
    assert "Mulligan(s)" in html
    assert "Total Turns" in html


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


def test_dashboard_handler_serves_opponents_list(tmp_path):
    """Regression: the /api/opponents dispatch read db_path off the wrong
    object (self.server.db_path) and every request 500'd on the real server."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("update participants set display_name = 'RealPerson' where id = 'opponent-1'")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/opponents")
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
    assert payload["total"] == 1
    assert payload["opponents"][0]["opponent_name"] == "RealPerson"
    assert payload["opponents"][0]["games"] == 1


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
    assert unfiltered["filters"] == {"deck": None, "format": None, "days": None, "season": None, "since": None, "until": None}
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

    # Jump In and Midweek Magic games are fully untracked.
    assert snapshot["summary"]["games"] == 6
    excluded = {"game-jump", "game-mwm1", "game-mwm2"}
    assert all(row["game_id"] not in excluded for row in snapshot["recent"])
    assert all(
        "Jump" not in opt["raw_format"] and "MWM" not in opt["raw_format"]
        for opt in snapshot["filter_options"]["formats"]
    )

    by_label = {row["format_label"]: row for row in snapshot["formats"]}
    # Missing metadata remains unknown rather than being assumed to be Play.
    assert by_label["Standard Best-of-1 (Unranked)"]["games"] == 2
    assert by_label["Standard Best-of-1 (Unranked)"]["raw_formats"] == "Play"
    assert by_label["Unknown"]["games"] == 1
    assert by_label["Unknown"]["raw_formats"] == "Unknown"
    assert by_label["Standard Best-of-1 (Ranked)"]["games"] == 1
    assert by_label["Standard Best-of-3 (Ranked)"]["games"] == 2
    assert all("Midweek Magic" not in label for label in by_label)
    assert snapshot["midweek_formats"] == []
    assert all(
        not normalize_match_format(option["raw_format"]).is_midweek
        for option in snapshot["filter_options"]["formats"]
    )

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
    assert payload["filters"] == {"deck": "Boros Mouse", "format": "Play", "days": None, "season": None, "since": None, "until": None}


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
                ("game-1", "player-1", 13, "Stolen Dragon (Creature 5/5)", "Creature", 1, 0),
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
    assert "Stolen Dragon" not in {
        row["display_name"] for row in detail["card_performance"]
    }

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

    # Per-deck streaks (win then loss in the fixture -> longest 1 each).
    assert detail["streaks"]["longest_win"] == 1
    assert detail["streaks"]["longest_loss"] == 1
    assert detail["streaks"]["current"] == {"kind": "loss", "length": 1}


def test_deck_detail_uses_submitted_deck_for_card_performance_and_arena_export(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        # This test pins its own submitted decklist; drop the shared fixture's.
        conn.execute("delete from game_deck_cards")
        conn.executemany(
            """
            insert into cards (id, arena_id, name, primary_type, first_seen_at)
            values (?, ?, ?, ?, '2026-07-27')
            """,
            [
                (21, 1001, "Mouse Mentor", "Creature"),
                (22, 1002, "Unholy Annex", "Enchantment"),
                (23, 1003, "Duress", "Sorcery"),
                (24, 1004, "Stolen Dragon", "Creature"),
                (25, None, "Unholy Annex // Ritual Chamber", "Enchantment"),
            ],
        )
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            )
            values (?, 'player-1', ?, ?, ?, 1)
            """,
            [
                ("game-1", 21, "Mouse Mentor (Creature 2/1)", "Creature"),
                ("game-1", 22, "Unholy Annex (Enchantment)", "Enchantment"),
                ("game-1", 24, "Stolen Dragon (Creature 5/5)", "Creature"),
            ],
        )
        conn.executemany(
            """
            insert into game_deck_cards (
                game_id, participant_id, card_id, arena_id, display_name,
                type_category, deck_zone, quantity
            )
            values ('game-1', 'player-1', ?, ?, ?, ?, ?, ?)
            """,
            [
                (21, 1001, "Mouse Mentor", "Creature", "deck", 4),
                (22, 1002, "Unholy Annex", "Enchantment", "deck", 1),
                (23, 1003, "Duress", "Sorcery", "sideboard", 2),
            ],
        )

    detail = deck_detail(db_path, "Boros Mouse")

    assert [row["display_name"] for row in detail["card_performance"]] == [
        "Mouse Mentor",
        "Unholy Annex",
    ]
    assert detail["deck_export"]["available"] is True
    assert detail["deck_export"]["main_deck"] == [
        {"display_name": "Mouse Mentor", "quantity": 4, "type_category": "Creature"},
        {
            "display_name": "Unholy Annex // Ritual Chamber",
            "quantity": 1,
            "type_category": "Enchantment",
        },
    ]
    assert detail["deck_export"]["sideboard"] == [
        {"display_name": "Duress", "quantity": 2, "type_category": "Sorcery"}
    ]
    assert detail["deck_export"]["text"] == (
        "About\n"
        "Name Boros Mouse\n"
        "\n"
        "Deck\n"
        "4 Mouse Mentor\n"
        "1 Unholy Annex // Ritual Chamber\n"
        "\n"
        "Sideboard\n"
        "2 Duress"
    )


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
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category,
                played_count, discarded_count, exiled_count
            )
            values ('game-1', 'opponent-1', 102, 'Graveyard Trespasser (Creature)', 'Creature', 1, 1, 1)
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
    assert detail["mulligan_hands"] == []
    assert detail["drawn"] == [
        {
            "display_name": "Llanowar Elves",
            "type_category": "Creature",
            "turn_number": 2,
            "draw_position": 1,
            "copy_number": 1,
            "source": None,
        }
    ]
    quality = detail["draw_quality"]
    assert quality["total_draws"] == 1
    assert quality["identified_draws"] == 1
    assert quality["land_draws"] == 0
    assert quality["land_draw_pct"] == 0.0
    assert quality["total_cards_seen"] == 2
    assert quality["opening_lands"] == 1
    assert quality["lands_seen"] == 1
    assert quality["land_seen_pct"] == 50.0
    assert quality["expected_land_rate"] == 40.0
    assert quality["expected_lands_seen"] == 0.8
    assert quality["flood_probability_pct"] == 64.4
    assert quality["screw_probability_pct"] == 84.4
    assert quality["longest_land_streak"] == 0
    assert quality["max_lands_in_eight"] is None
    assert quality["longest_low_land_drought"] == 1
    assert quality["low_land_drought_lands"] == 1
    assert quality["flood_reasons"] == []
    assert quality["is_flood"] is False
    assert quality["screw_reasons"] == []
    assert quality["is_screw"] is False
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
        {
            "display_name": "Mouse Mentor",
            "type_category": "Creature",
            "played_count": 2,
            "turns_played": [],
        }
    ]
    assert detail["opponent_cards"] == [
        {
            "display_name": "Graveyard Trespasser",
            "type_category": "Creature",
            "played_count": 1,
            "drawn_count": 0,
            "discarded_count": 1,
            "milled_count": 0,
            "exiled_count": 1,
            "turns_played": [],
            "first_seen_turn": None,
        }
    ]
    assert [row["event_type"] for row in detail["timeline"]] == ["turn", "damage"]
    damage_event = detail["timeline"][1]
    assert "".join(segment["text"] for segment in damage_event["text_segments"]) == damage_event["text"]
    assert [
        segment
        for segment in damage_event["text_segments"]
        if segment["kind"] == "card"
    ] == [
        {
            "kind": "card",
            "text": "Mouse Mentor",
            "card_name": "Mouse Mentor",
            "card_type": "Creature",
        },
        {
            "kind": "card",
            "text": "Graveyard Trespasser",
            "card_name": "Graveyard Trespasser",
            "card_type": "Creature",
        },
    ]
    plain_timeline_text = "".join(
        segment["text"]
        for segment in damage_event["text_segments"]
        if segment["kind"] == "text"
    )
    assert "[0:20]" in plain_timeline_text
    assert "(2/1)" in plain_timeline_text
    assert "(3/3)" in plain_timeline_text
    assert "[resolved]" in plain_timeline_text
    assert "[you]" in plain_timeline_text
    assert "[Skeleton Pirate]" in plain_timeline_text
    assert detail["life_curve"] == [
        {"turn_number": 1, "player_life": 20, "opponent_life": 20},
        {"turn_number": 4, "player_life": 12, "opponent_life": 0},
    ]


def test_game_detail_reports_played_and_revealed_turns(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category,
                played_count, drawn_count, milled_count
            )
            values (?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", "Mouse Mentor (Creature 2/1)", "Creature", 2, 0, 0),
                ("game-1", "player-1", "Mountain (Land)", "Land", 1, 0, 0),
                ("game-1", "opponent-1", "Lightning Helix (Instant)", "Instant", 2, 0, 0),
                # Never cast: revealed only through a mill.
                ("game-1", "opponent-1", "Duress (Sorcery)", "Sorcery", 0, 0, 1),
            ],
        )
        conn.executemany(
            """
            insert into game_events (
                session_id, match_id, game_id, event_time, elapsed_seconds, turn_number,
                phase, step, actor_role, event_type, text, player_life, opponent_life
            )
            values ('session-1', 'match-1', 'game-1', ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, NULL)
            """,
            [
                ("2026-06-04T00:01:05", 5, 1, "player", "land", "[0:05] You: played [Mountain (Land)]"),
                (
                    "2026-06-04T00:01:20",
                    20,
                    3,
                    "player",
                    "cast",
                    "[0:20] You: cast [Mouse Mentor (Creature 2/1)]",
                ),
                (
                    "2026-06-04T00:01:40",
                    40,
                    4,
                    "opponent",
                    "cast",
                    "[0:40] Opponent: cast [Lightning Helix (Instant)] -> [Mouse Mentor (2/1)]",
                ),
                (
                    "2026-06-04T00:01:55",
                    55,
                    5,
                    "player",
                    "cast",
                    "[0:55] You: cast [Mouse Mentor (Creature 2/1)]",
                ),
                (
                    "2026-06-04T00:02:05",
                    65,
                    6,
                    "opponent",
                    "cast",
                    "[1:05] Opponent: cast [Lightning Helix (Instant)]",
                ),
                (
                    "2026-06-04T00:02:15",
                    75,
                    7,
                    "opponent",
                    "zone",
                    "[1:15] Opponent: [Duress] was milled",
                ),
            ],
        )

    detail = game_detail(db_path, "game-1")

    played = {row["display_name"]: row for row in detail["cards_played"]}
    # Every cast turn is listed, one entry per cast.
    assert played["Mouse Mentor"]["turns_played"] == [3, 5]
    assert played["Mountain"]["turns_played"] == [1]

    opponent = {row["display_name"]: row for row in detail["opponent_cards"]}
    # First reveal = the first cast, even though it was cast twice...
    assert opponent["Lightning Helix"]["first_seen_turn"] == 4
    # ...and zone events (mill/discard/exile) count as reveals too.
    assert opponent["Duress"]["first_seen_turn"] == 7
    # The opponent's Helix targeting Mouse Mentor must NOT credit the player's
    # Mouse Mentor with a turn-4 play (only the event's primary card counts).
    assert played["Mouse Mentor"]["turns_played"] == [3, 5]


def test_opponent_detail_reports_head_to_head_history(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    detail = opponent_detail(db_path, "opponent")

    assert detail["opponent_name"] == "Opponent"
    assert detail["summary"] == {
        "games": 2,
        "wins": 1,
        "losses": 1,
        "draws": 0,
        "win_rate": 50.0,
        # The fixture keeps both games under one match row; a 1–1 split is
        # neither a match win nor a match loss.
        "matches": 1,
        "match_wins": 0,
        "match_losses": 0,
    }
    assert [row["game_id"] for row in detail["games"]] == ["game-2", "game-1"]
    assert detail["games"][0]["deck_name"] == "Boros Mouse"
    assert detail["games"][0]["play_draw"] == "On the draw"
    assert detail["games"][0]["format_label"] == "Standard Best-of-1 (Unranked)"


def test_opponent_detail_rejects_unknown_name(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    with pytest.raises(LookupError, match="No recorded games against opponent"):
        opponent_detail(db_path, "Missing Opponent")


def test_card_detail_combines_split_card_name_variants(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into cards (name, primary_type, first_seen_at)
            values ('Unholy Annex // Ritual Chamber', 'Enchantment', '2026-06-04T00:00:00')
            """
        )
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, display_name, type_category, played_count, drawn_count
            )
            values (?, ?, ?, 'Enchantment', ?, ?)
            """,
            [
                ("game-1", "player-1", "Unholy Annex (Enchantment)", 2, 0),
                ("game-1", "player-1", "Unholy Annex // Ritual Chamber", 0, 1),
                ("game-2", "player-2", "Ritual Chamber (Enchantment)", 1, 0),
            ],
        )

    detail = card_detail(db_path, "Unholy Annex")

    # Door plays, half plays, and full-name draws all count as one card.
    assert detail["card_name"] == "Unholy Annex // Ritual Chamber"
    assert detail["all_usage"]["games_seen"] == 2
    assert detail["all_usage"]["total_played"] == 3
    assert detail["summary"]["games_seen"] == 2

    # Looking it up by the other half or the full name gives the same card.
    assert card_detail(db_path, "Ritual Chamber")["all_usage"]["total_played"] == 3
    assert (
        card_detail(db_path, "Unholy Annex // Ritual Chamber")["all_usage"]["total_played"] == 3
    )


def test_game_detail_reports_opponent_color_combo(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into cards (name, primary_type, color_identity, first_seen_at)
            values (?, ?, ?, '2026-06-04T00:00:00')
            """,
            [
                ("Steam Vents", "Land", "UR"),
                ("Lightning Strike", "Instant", "R"),
                ("Sleight of Hand", "Sorcery", "U"),
            ],
        )
        card_ids = {
            name: conn.execute("select id from cards where name = ?", (name,)).fetchone()[0]
            for name in ("Steam Vents", "Lightning Strike", "Sleight of Hand")
        }
        conn.executemany(
            """
            insert into game_card_summary (game_id, participant_id, card_id, display_name, type_category, played_count)
            values ('game-1', 'opponent-1', ?, ?, ?, 1)
            """,
            [
                (card_ids["Steam Vents"], "Steam Vents", "Land"),
                (card_ids["Lightning Strike"], "Lightning Strike (Instant)", "Instant"),
                (card_ids["Sleight of Hand"], "Sleight of Hand (Sorcery)", "Sorcery"),
            ],
        )

    detail = game_detail(db_path, "game-1")

    assert detail["opponent"]["colors"] == "UR"
    assert detail["opponent"]["color_label"] == "Izzet"

    snapshot = dashboard_snapshot(db_path)
    colors = {row["color_label"]: row for row in snapshot["opponent_colors"]}
    assert "Izzet" in colors
    assert colors["Izzet"]["games"] == 1


def test_game_detail_groups_mulligan_hands_in_order(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_mulligan_hands (
                game_id, participant_id, hand_number, hand_position,
                display_name, type_category, bottomed
            )
            values ('game-1', 'player-1', ?, ?, ?, ?, ?)
            """,
            [
                (1, 1, "Swamp", "Land", 0),
                (1, 2, "Duress", "Sorcery", 0),
                (2, 1, "Mountain", "Land", 0),
                (2, 2, "Lightning Strike", "Instant", 1),
            ],
        )

    detail = game_detail(db_path, "game-1")

    assert detail["mulligan_hands"] == [
        {
            "hand_number": 1,
            "cards": [
                {"hand_position": 1, "display_name": "Swamp", "type_category": "Land", "bottomed": False},
                {"hand_position": 2, "display_name": "Duress", "type_category": "Sorcery", "bottomed": False},
            ],
        },
        {
            "hand_number": 2,
            "cards": [
                {"hand_position": 1, "display_name": "Mountain", "type_category": "Land", "bottomed": False},
                {"hand_position": 2, "display_name": "Lightning Strike", "type_category": "Instant", "bottomed": True},
            ],
        },
    ]


def test_game_detail_marks_flood_when_over_half_of_draws_are_lands(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert or replace into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 6)
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
                ("Swamp", 5, 6),
            ],
        )

    detail = game_detail(db_path, "game-1")

    quality = detail["draw_quality"]
    assert quality["total_draws"] == 6
    assert quality["identified_draws"] == 5
    assert quality["land_draws"] == 4
    assert quality["land_draw_pct"] == 66.7
    assert quality["total_cards_seen"] == 7
    assert quality["lands_seen"] == 5
    assert quality["longest_land_streak"] == 4
    assert "4 of 6 post-opening draws were lands" in quality["flood_reasons"]
    assert quality["is_flood"] is True
    recent_games = {
        row["game_id"]: row for row in dashboard_snapshot(db_path)["recent"]
    }
    assert recent_games["game-1"]["is_flood"] is True
    assert "4 of 6 post-opening draws were lands" in recent_games["game-1"]["flood_reasons"]


def test_game_detail_does_not_mark_exactly_half_land_draws_as_flood(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert or replace into game_participant_stats (game_id, participant_id, cards_drawn)
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


def test_game_detail_marks_three_nonland_draws_while_stuck_on_one_land_as_screw(
    tmp_path,
):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_opening_hand_cards (
                game_id, participant_id, display_name, type_category,
                hand_position, copy_number
            ) values ('game-1', 'player-1', ?, 'Creature', ?, 1)
            """,
            [(f"Opening Nonland {position}", position) for position in range(2, 8)],
        )
        conn.execute(
            """
            insert or replace into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 3)
            """
        )
        conn.executemany(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category,
                draw_position, turn_number, copy_number
            ) values ('game-1', 'player-1', ?, 'Creature', ?, ?, 1)
            """,
            [
                ("Second Nonland", 2, 4),
                ("Third Nonland", 3, 6),
            ],
        )

    quality = game_detail(db_path, "game-1")["draw_quality"]

    assert quality["opening_lands"] == 1
    assert quality["land_draws"] == 0
    assert quality["longest_low_land_drought"] == 3
    assert quality["low_land_drought_lands"] == 1
    assert quality["screw_probability_pct"] <= 10.0
    assert quality["is_screw"] is True
    assert "3 consecutive nonland draws while stuck on 1 land" in quality["screw_reasons"]

    recent_games = {
        row["game_id"]: row for row in dashboard_snapshot(db_path)["recent"]
    }
    assert recent_games["game-1"]["is_screw"] is True


def test_game_detail_does_not_treat_unidentified_draws_as_nonland_drought(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert or replace into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 3)
            """
        )

    quality = game_detail(db_path, "game-1")["draw_quality"]

    assert quality["identified_draws"] == 1
    assert quality["longest_low_land_drought"] == 1
    assert quality["screw_probability_pct"] is None
    assert quality["is_screw"] is False


def test_game_detail_marks_four_consecutive_land_draws_as_flood(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert or replace into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 10)
            """
        )
        conn.executemany(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category,
                draw_position, turn_number, copy_number
            ) values ('game-1', 'player-1', ?, 'Land', ?, ?, 1)
            """,
            [(f"Land {position}", position, position) for position in range(2, 7)],
        )

    quality = game_detail(db_path, "game-1")["draw_quality"]

    assert quality["land_draw_pct"] == 50.0
    assert quality["longest_land_streak"] == 5
    assert quality["is_flood"] is True
    assert "5 consecutive land draws" in quality["flood_reasons"]


def test_game_detail_marks_six_lands_in_eight_draws_as_flood(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert or replace into game_participant_stats (game_id, participant_id, cards_drawn)
            values ('game-1', 'player-1', 20)
            """
        )
        conn.executemany(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category,
                draw_position, turn_number, copy_number
            ) values ('game-1', 'player-1', ?, 'Land', ?, ?, 1)
            """,
            [(f"Land {position}", position, position) for position in (2, 3, 5, 6, 8, 9)],
        )

    quality = game_detail(db_path, "game-1")["draw_quality"]

    assert quality["land_draw_pct"] == 30.0
    assert quality["longest_land_streak"] == 2
    assert quality["max_lands_in_eight"] == 6
    assert quality["is_flood"] is True
    assert "6 lands in an 8-draw window" in quality["flood_reasons"]


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
            "wins": 1,
            "losses": 0,
            "win_rate": 100.0,
        },
    ]
    assert detail["opponent_impact"] == {
        "games": 1,
        "plays": 1,
        "wins": 1,
        "losses": 0,
        "win_rate": 100.0,
        "loss_rate": 0.0,
    }
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
    assert detail["opponent_impact"] == {
        "games": 1,
        "plays": 2,
        "wins": 1,
        "losses": 0,
        "win_rate": 100.0,
        "loss_rate": 0.0,
    }
    assert detail["by_deck"] == []


def test_card_detail_excludes_revealed_only_cards_from_opponent_impact(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, display_name, type_category,
                played_count, exiled_count
            ) values ('game-1', 'opponent-1', 'Revealed Tech', 'Instant', 0, 1)
            """
        )

    detail = card_detail(db_path, "Revealed Tech")

    assert detail["all_usage"]["games_seen"] == 1
    assert detail["all_usage"]["opponent_games_seen"] == 0
    assert detail["opponent_impact"] == {
        "games": 0,
        "plays": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "loss_rate": None,
    }


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


def test_dashboard_snapshot_reports_combat_profiles(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    snapshot = dashboard_snapshot(db_path)

    combat_decks = snapshot["combat_decks"]
    assert len(combat_decks) == 1
    deck = combat_decks[0]
    assert deck["deck_name"] == "Boros Mouse"
    assert deck["games"] == 2
    assert deck["avg_damage_dealt"] == 14.5
    assert deck["avg_damage_taken"] == 12.0
    assert deck["avg_attack_steps"] == 3.0
    assert deck["attackers_per_attack"] == 2.17
    assert deck["attackers_lost"] == 3
    assert deck["blockers_lost"] == 3
    assert deck["trade_ratio"] == 1.0
    assert deck["aggression_profile"] == "Aggro"

    split = {row["split"]: row for row in snapshot["combat_split"]}
    assert split["Wins"]["avg_damage_dealt"] == 20.0
    assert split["Losses"]["avg_damage_dealt"] == 9.0
    assert split["Losses"]["avg_cards_denied"] == 5.0


def test_deck_detail_includes_combat_profile(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    detail = deck_detail(db_path, "Boros Mouse")

    profile = detail["combat_profile"]
    assert profile is not None
    assert profile["deck_name"] == "Boros Mouse"
    assert profile["avg_damage_dealt"] == 14.5


def test_game_detail_includes_participant_stats(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    detail = game_detail(db_path, "game-1")

    stats = detail["participant_stats"]
    assert [row["role"] for row in stats] == ["player", "opponent"]
    assert stats[0]["damage_dealt"] == 20
    assert stats[0]["damage_taken"] == 6
    assert stats[1]["damage_dealt"] == 8


def test_deck_detail_reports_composition_and_versions(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    detail = deck_detail(db_path, "Boros Mouse")

    composition = {row["display_name"]: row for row in detail["composition"]}
    mountain = composition["Mountain"]
    assert mountain["games_in_deck"] == 2
    assert mountain["games_seen"] == 1
    assert mountain["times_seen"] == 1
    # game-1 saw 2 cards from a 60-card deck: expected 2*24/60 = 0.8
    assert mountain["expected_seen"] == 0.8
    assert mountain["games_seen_multiple"] == 0
    assert mountain["multiple_pct"] == 0.0
    assert mountain["win_rate_when_seen"] == 100.0
    assert mountain["win_rate_when_not_seen"] == 0.0

    versions = detail["versions"]
    assert len(versions) == 2
    assert versions[0]["games"] == 1
    assert versions[0]["wins"] == 1
    assert versions[1]["games"] == 1
    assert versions[1]["losses"] == 1
    assert versions[1]["added"] == ["2x Sheltered by Ghosts"]
    assert versions[1]["removed"] == ["2x Mouse Mentor"]

    sideboard = detail["sideboard"]
    assert sideboard is not None
    assert sideboard["matches"] == 1
    assert sideboard["game_one"]["wins"] == 1
    assert sideboard["post_board"]["losses"] == 1
    assert sideboard["boarded_in"][0]["display_name"] == "Sheltered by Ghosts"

    swaps = {row["display_name"]: row for row in sideboard["swaps"]}
    assert swaps["Sheltered by Ghosts"]["boarded_in"] == 2
    assert swaps["Sheltered by Ghosts"]["boarded_out"] == 0
    assert swaps["Sheltered by Ghosts"]["games_in"] == 1
    assert swaps["Sheltered by Ghosts"]["losses_in"] == 1
    assert swaps["Sheltered by Ghosts"]["win_rate_in"] == 0.0
    assert swaps["Mouse Mentor"]["boarded_out"] == 2
    assert swaps["Mouse Mentor"]["boarded_in"] == 0


def test_dashboard_snapshot_reports_mana_readiness(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        # game-1: opening Mountain (1 land) + no land draws by turn 2 -> behind.
        # Give game-2 an opening hand with two lands and a land drawn on turn 2.
        conn.executemany(
            """
            insert into game_opening_hand_cards (
                game_id, participant_id, display_name, type_category, hand_position, copy_number
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-2", "player-2", "Mountain", "Land", 1, 1),
                ("game-2", "player-2", "Mountain", "Land", 2, 2),
                ("game-2", "player-2", "Shock", "Instant", 3, 1),
            ],
        )
        conn.execute(
            """
            insert into game_drawn_cards (
                game_id, participant_id, display_name, type_category, draw_position, turn_number, copy_number
            ) values ('game-2', 'player-2', 'Mountain', 'Land', 1, 2, 3)
            """
        )

    snapshot = dashboard_snapshot(db_path)

    readiness = {row["threshold"]: row for row in snapshot["mana_readiness"]}
    two = readiness[2]
    assert two["games"] == 2
    # game-1 has 1 land by turn 2 (behind, a win); game-2 has 3 (on time, a loss).
    assert two["on_time_games"] == 1
    assert two["on_time_pct"] == 50.0
    assert two["on_time_win_rate"] == 0.0
    assert two["behind_win_rate"] == 100.0


def test_dashboard_snapshot_counts_bo3_matches_once_and_splits_ranked(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into matches (id, session_id, format, queue, event_name, best_of) values (?, 'session-1', ?, ?, ?, ?)",
            [
                ("match-bo3", "Traditional_Ladder", "Traditional_Ladder", "Traditional_Ladder", 3),
                ("match-brawl", "Brawl_Ladder", "Brawl_Ladder", "Brawl_Ladder", 1),
            ],
        )
        games = [
            # Ranked Bo3 that went 2-1: one ranked match win, not three results.
            ("game-b1", "match-bo3", "2026-06-05T00:01:00", "win"),
            ("game-b2", "match-bo3", "2026-06-05T00:10:00", "loss"),
            ("game-b3", "match-bo3", "2026-06-05T00:20:00", "win"),
            # Ranked Brawl: counts in the combined row, not the constructed ranked row.
            ("game-br", "match-brawl", "2026-06-05T01:00:00", "win"),
        ]
        for game_id, match_id, started, outcome in games:
            conn.execute(
                """
                insert into games (id, session_id, match_id, game_number, started_at, outcome,
                                   duration_seconds, total_turns, player_turns, opponent_turns)
                values (?, 'session-1', ?, 1, ?, ?, 300, 10, 5, 5)
                """,
                (game_id, match_id, started, outcome),
            )
            conn.execute(
                """
                insert into participants (id, game_id, seat_id, role, display_name, deck_name,
                                          went_first, mulligans, opening_hand_size, starting_life, ending_life)
                values (?, ?, 1, 'player', 'Tapps', 'Boros Mouse', 1, 0, 7, 20, 12)
                """,
                (f"p-{game_id}", game_id),
            )

    snapshot = dashboard_snapshot(db_path)

    # Combined: 2 fixture Bo1 games (1-1) + Bo3 match (one win) + brawl win.
    match_summary = snapshot["match_summary"]
    assert match_summary["matches"] == 4
    assert match_summary["wins"] == 3
    assert match_summary["losses"] == 1
    assert match_summary["win_rate"] == 75.0
    # win, loss (fixture) then Bo3 win + brawl win back-to-back.
    assert match_summary["longest_win"] == 2
    assert match_summary["longest_loss"] == 1

    # Constructed ranked only: just the Bo3 ladder match; Brawl (Ranked) excluded.
    ranked = snapshot["ranked_summary"]
    assert ranked == {
        "matches": 1,
        "wins": 1,
        "losses": 0,
        "win_rate": 100.0,
        "longest_win": 1,
        "longest_loss": 0,
    }


def test_dashboard_snapshot_splits_ranked_stats_by_season(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into matches (id, session_id, format, queue, event_name, best_of) "
            "values ('match-l1', 'session-1', 'Ladder', 'Ladder', 'Ladder', 1)"
        )
        games = [
            # Season 92: one win (fixture itself carries seasons 90/91).
            ("game-s5", "2026-07-10T10:00:00", "win"),
            # Season 93: a win and a loss.
            ("game-s6a", "2026-08-10T10:00:00", "win"),
            ("game-s6b", "2026-08-11T10:00:00", "loss"),
        ]
        for game_id, started, outcome in games:
            conn.execute(
                """
                insert into games (id, session_id, match_id, game_number, started_at, outcome,
                                   duration_seconds, total_turns, player_turns, opponent_turns)
                values (?, 'session-1', 'match-l1', 1, ?, ?, 300, 10, 5, 5)
                """,
                (game_id, started, outcome),
            )
            conn.execute(
                """
                insert into participants (id, game_id, seat_id, role, display_name, deck_name,
                                          went_first, mulligans, opening_hand_size, starting_life, ending_life)
                values (?, ?, 1, 'player', 'Tapps', 'Boros Mouse', 1, 0, 7, 20, 12)
                """,
                (f"p-{game_id}", game_id),
            )
        conn.executemany(
            """
            insert into rank_snapshots (session_id, game_id, captured_at, season_ordinal,
                                        rank_format, rank_class, rank_level, rank_step, rank_steps)
            values ('session-1', ?, ?, ?, 'constructed', 'Gold', 4, 2, 6)
            """,
            [
                ("game-s5", "2026-07-10T10:05:00", 92),
                ("game-s6a", "2026-08-10T10:05:00", 93),
                ("game-s6b", "2026-08-11T10:05:00", 93),
            ],
        )

    latest = dashboard_snapshot(db_path)
    # Lifetime spans both seasons; the season row defaults to the latest (93).
    assert latest["ranked_summary"]["matches"] == 3
    season6 = latest["ranked_season_summary"]
    assert season6["season_ordinal"] == 93
    assert (season6["wins"], season6["losses"]) == (1, 1)

    season5 = dashboard_snapshot(db_path, season=92)["ranked_season_summary"]
    assert season5["season_ordinal"] == 92
    assert (season5["wins"], season5["losses"]) == (1, 0)


def test_card_detail_reports_multiplicity(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values ('game-1', 'player-1', NULL, 'Mountain', 'Land', 1)
            """
        )

    detail = card_detail(db_path, "Mountain")

    multiplicity = detail["multiplicity"]
    # Mountain is in both games' decklists (24 copies each).
    assert multiplicity["games"] == 2
    buckets = {row["copies_seen"]: row for row in multiplicity["buckets"]}
    # game-2 never saw it; game-1 saw one copy in the opener.
    assert buckets[0]["games"] == 1
    assert buckets[1]["games"] == 1
    assert buckets[1]["pct_of_games"] == 50.0
    assert buckets[1]["win_rate"] == 100.0
    assert buckets[1]["expected_pct_at_least"] is not None
    # Buckets 2–4+ are always emitted (even at zero games) so the expected
    # percentages for rare multiples stay visible.
    for key in (2, 3, 4):
        assert buckets[key]["games"] == 0
        assert buckets[key]["win_rate"] is None
        assert buckets[key]["expected_pct_at_least"] is not None
    assert buckets[4]["label"] == "4+"


def test_card_detail_reports_opponent_multiplicity(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category,
                played_count, drawn_count
            ) values (?, ?, NULL, 'Lightning Helix', 'Instant', ?, ?)
            """,
            [
                # game-1 (a win for the player): opponent resolved it 3 times.
                ("game-1", "opponent-1", 3, 0),
                # game-2 (a loss): one copy, visible as both a draw and a cast
                # (max, not sum, so it still counts as one copy).
                ("game-2", "opponent-2", 1, 1),
            ],
        )

    detail = card_detail(db_path, "Lightning Helix")

    opp = detail["opponent_multiplicity"]
    assert opp["games"] == 2
    buckets = {row["copies_seen"]: row for row in opp["buckets"]}
    assert set(buckets) == {1, 2, 3, 4}
    assert buckets[3]["games"] == 1
    assert buckets[3]["win_rate"] == 100.0
    assert buckets[3]["pct_at_least"] == 50.0
    assert buckets[1]["games"] == 1
    assert buckets[1]["win_rate"] == 0.0
    assert buckets[1]["pct_at_least"] == 100.0
    assert buckets[2]["games"] == 0
    assert buckets[2]["win_rate"] is None
    # At-least is cumulative over higher buckets even through empty ones.
    assert buckets[2]["pct_at_least"] == 50.0
    assert buckets[4]["games"] == 0
    assert buckets[4]["label"] == "4+"
    # No decklist knowledge for opponents: expectation is always absent.
    assert all(row["expected_pct_at_least"] is None for row in opp["buckets"])
    # Player-side multiplicity has no data for this card.
    assert detail["multiplicity"]["games"] == 0


def test_dashboard_snapshot_reports_schedule_fatigue_and_streaks(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    snapshot = dashboard_snapshot(db_path)

    weekdays = snapshot["schedule"]["by_weekday"]
    assert sum(row["games"] for row in weekdays) == 2
    assert all("label" in row for row in weekdays)
    time_buckets = snapshot["schedule"]["by_time_of_day"]
    assert sum(row["games"] for row in time_buckets) == 2

    fatigue = snapshot["fatigue"]
    assert fatigue[0]["label"] == "Games 1–4"
    assert fatigue[0]["games"] == 2

    streaks = snapshot["streaks"]
    assert streaks["games"] == 2
    assert streaks["longest_win"] == 1
    assert streaks["longest_loss"] == 1
    assert streaks["current"] == {"kind": "loss", "length": 1}

    reasons = {row["reason"]: row for row in snapshot["outcome_reasons"]}
    assert reasons["opponent_conceded"]["wins"] == 1

    # Bo1 games count individually at match level too.
    match_summary = snapshot["match_summary"]
    assert match_summary == {
        "matches": 2,
        "wins": 1,
        "losses": 1,
        "win_rate": 50.0,
        "longest_win": 1,
        "longest_loss": 1,
    }
    # The fixture's Play queue is unranked, so the ranked slice is empty.
    assert snapshot["ranked_summary"]["matches"] == 0

    opener = {row["lands"]: row for row in snapshot["opener_lands"]}
    # game-1 kept a 1-land opener and won; game-2 has no recorded opener rows
    # in the shared fixture, so only games with opener data are counted.
    assert opener[1]["games"] == 1
    assert opener[1]["win_rate"] == 100.0


def test_dashboard_snapshot_supports_rank_season_selection(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into rank_snapshots (
                session_id, captured_at, season_ordinal, rank_format,
                rank_class, rank_level, rank_step, rank_steps, raw_step
            ) values ('session-1', '2026-05-01T00:00:00', 90, 'constructed', 'Gold', 2, 1, 6, 1)
            """
        )

    latest = dashboard_snapshot(db_path)
    assert latest["filter_options"]["rank_seasons"] == [91, 90]
    assert all(row["season_ordinal"] == 91 for row in latest["rank_progress"])

    previous = dashboard_snapshot(db_path, season=90)
    assert previous["filters"]["season"] == 90
    assert all(row["season_ordinal"] == 90 for row in previous["rank_progress"])
    assert previous["rank_progress"][0]["rank_class"] == "Gold"


def test_dashboard_snapshot_reports_opponent_threats_and_matchups(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, NULL, ?, ?, ?)
            """,
            [
                ("game-1", "opponent-1", "Graveyard Trespasser (Creature 3/3)", "Creature", 1),
                ("game-2", "opponent-2", "Graveyard Trespasser (Creature 3/3)", "Creature", 2),
            ],
        )
        conn.execute(
            "update participants set deck_archetype = 'Dimir Midrange' where id = 'opponent-2'"
        )

    snapshot = dashboard_snapshot(db_path)

    threats = snapshot["opponent_threats"]
    assert threats[0]["display_name"] == "Graveyard Trespasser"
    assert threats[0]["games"] == 2
    assert threats[0]["plays"] == 3
    assert threats[0]["loss_rate"] == 50.0

    matchups = {
        (row["deck_name"], row["opponent_archetype"]): row for row in snapshot["matchups"]
    }
    assert matchups[("Boros Mouse", "Dimir Midrange")]["losses"] == 1
    assert matchups[("Boros Mouse", "(unidentified)")]["wins"] == 1


def test_dashboard_snapshot_matchups_empty_without_archetypes(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    snapshot = dashboard_snapshot(db_path)

    assert snapshot["matchups"] == []


def test_dashboard_snapshot_supports_custom_date_range(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    # Both fixture games start on 2026-06-04.
    inside = dashboard_snapshot(db_path, since="2026-06-04", until="2026-06-04")
    assert inside["summary"]["games"] == 2

    before = dashboard_snapshot(db_path, until="2026-06-03")
    assert before["summary"]["games"] == 0

    after = dashboard_snapshot(db_path, since="2026-06-05")
    assert after["summary"]["games"] == 0


def test_card_and_opponent_details_honor_filters(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, NULL, 'Mountain', 'Land', 1)
            """,
            [("game-1", "player-1"), ("game-2", "player-2")],
        )

    unfiltered = card_detail(db_path, "Mountain")
    assert unfiltered["summary"]["games_seen"] == 2

    filtered = card_detail(db_path, "Mountain", until="2026-06-04")
    assert filtered["summary"]["games_seen"] == 2

    # No games in range -> the card lookup itself 404s.
    try:
        card_detail(db_path, "Mountain", since="2026-06-05")
        raised = False
    except LookupError:
        raised = True
    assert raised

    opponent = opponent_detail(db_path, "Opponent")
    assert opponent["summary"]["games"] == 2

    try:
        opponent_detail(db_path, "Opponent", since="2026-06-05")
        opponent_raised = False
    except LookupError:
        opponent_raised = True
    assert opponent_raised


def test_global_search_returns_cards_decks_and_opponents(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values ('game-1', 'player-1', NULL, 'Mouse Mentor (Creature 2/1)', 'Creature', 1)
            """
        )
        conn.execute("update participants set display_name = 'MouseFan#12345' where id = 'opponent-1'")

    result = global_search(db_path, "Mouse")

    assert any(card["card_name"] == "Mouse Mentor" for card in result["cards"])
    assert result["decks"][0]["deck_name"] == "Boros Mouse"
    assert result["decks"][0]["games"] == 2
    assert result["opponents"][0]["display_name"] == "MouseFan#12345"


def test_search_endpoint_serves_global_results(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/search?q=Boros")
        response = conn.getresponse()
        assert response.status == 200
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert payload["decks"][0]["deck_name"] == "Boros Mouse"
    assert "cards" in payload and "opponents" in payload


def test_game_annotation_round_trip(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    saved = save_game_annotation(db_path, "game-1", note="Misplayed turn 4", tags=["misplay", "flood"])
    assert saved == {"game_id": "game-1", "note": "Misplayed turn 4", "tags": ["misplay", "flood"]}

    detail = game_detail(db_path, "game-1")
    assert detail["annotation"]["note"] == "Misplayed turn 4"
    assert detail["annotation"]["tags"] == ["misplay", "flood"]

    # Clearing removes the row.
    save_game_annotation(db_path, "game-1", note="", tags=[])
    assert game_annotation(db_path, "game-1")["note"] == ""

    try:
        save_game_annotation(db_path, "missing-game", note="x")
        raised = False
    except LookupError:
        raised = True
    assert raised


def test_annotation_post_endpoint(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _dashboard_handler_for(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    conn = None
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        body = json.dumps({"game_id": "game-1", "note": "great game", "tags": ["fun"]})
        conn.request("POST", "/api/game/annotation", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 200
        payload = json.loads(response.read().decode("utf-8"))

        conn.request("POST", "/api/game/annotation", body="{}", headers={"Content-Type": "application/json"})
        bad = conn.getresponse()
        bad_status = bad.status
        bad.read()
    finally:
        if conn is not None:
            conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert payload["note"] == "great game"
    assert payload["tags"] == ["fun"]
    assert bad_status == 400


def test_audit_endpoint_reports_findings(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    report = audit_report(db_path)

    assert "findings" in report and "total" in report and "by_code" in report
    assert report["total"] == len(report["findings"])


def test_audit_report_works_while_a_writer_holds_the_lock(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    writer = sqlite3.connect(db_path)
    writer.execute("BEGIN IMMEDIATE")
    try:
        report = audit_report(db_path)
    finally:
        writer.rollback()
        writer.close()
    assert "findings" in report


def test_all_games_returns_full_history_with_flags(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)

    result = all_games(db_path)

    assert result["total"] == 2
    rows = {row["game_id"]: row for row in result["games"]}
    assert rows["game-1"]["deck_name"] == "Boros Mouse"
    assert rows["game-1"]["format_label"] == "Standard Best-of-1 (Unranked)"
    assert rows["game-1"]["match_wins"] == 1
    assert rows["game-1"]["match_losses"] == 1
    assert "is_flood" in rows["game-1"] and "is_screw" in rows["game-1"]
    assert rows["game-1"]["cards_seen"] == 2

    filtered = all_games(db_path, since="2026-06-05")
    assert filtered["total"] == 0


def test_game_detail_timeline_not_truncated_for_long_games(tmp_path):
    """A 35-turn grind produced 667 events; the old LIMIT 500 silently cut the
    timeline (and life curve) after mid-game. Long games must return complete."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM game_events WHERE game_id = 'game-1'")
        rows = []
        for index in range(700):
            turn = index // 20 + 1
            rows.append(
                (
                    "session-1",
                    "match-1",
                    "game-1",
                    f"2026-06-04T00:{index // 60:02d}:{index % 60:02d}",
                    index,
                    turn,
                    "main",
                    "main",
                    "player",
                    "cast" if index % 3 else "turn",
                    f"Event {index}",
                    20,
                    20,
                )
            )
        conn.executemany(
            """
            insert into game_events (
                session_id, match_id, game_id, event_time, elapsed_seconds, turn_number,
                phase, step, actor_role, event_type, text, player_life, opponent_life
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    detail = game_detail(db_path, "game-1")

    assert len(detail["timeline"]) == 700
    assert detail["timeline"][-1]["turn_number"] == 35
    assert detail["timeline"][-1]["text"] == "Event 699"


def test_game_detail_reports_bo3_match_games(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE matches SET best_of = 3 WHERE id = 'match-1'")

    detail = game_detail(db_path, "game-1")

    match_games = detail["match_games"]
    assert [row["game_id"] for row in match_games] == ["game-1", "game-2"]
    assert [row["outcome"] for row in match_games] == ["win", "loss"]
    assert match_games[1]["game_number"] == 2
    assert match_games[1]["total_turns"] == 10


def test_game_detail_bo1_single_game_has_no_match_games(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into matches (id, session_id, format, best_of)
            values ('match-9', 'session-1', 'Play', 1)
            """
        )
        conn.execute(
            """
            insert into games (id, session_id, match_id, game_number, started_at, outcome)
            values ('game-9', 'session-1', 'match-9', 1, '2026-06-06T00:01:00', 'win')
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role, deck_name)
            values ('player-9', 'game-9', 'player', 'Boros Mouse')
            """
        )
        conn.execute(
            """
            insert into participants (id, game_id, role)
            values ('opponent-9', 'game-9', 'opponent')
            """
        )
    detail = game_detail(db_path, "game-9")
    assert detail["match_games"] == []


def test_snapshot_recent_rows_carry_match_identity(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    snapshot = dashboard_snapshot(db_path)
    row = snapshot["recent"][0]
    assert row["match_id"] == "match-1"
    assert "game_number" in row


def test_game_detail_deck_changes_compare_against_match_original(tmp_path):
    """Post-board games show cumulative deck changes vs the ORIGINAL deck."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE matches SET best_of = 3 WHERE id = 'match-1'")

    detail = game_detail(db_path, "game-2")

    assert detail["sideboard_changes"] == {
        "added": ["2x Sheltered by Ghosts"],
        "removed": ["2x Mouse Mentor"],
    }
    changes = detail["deck_changes"]
    assert changes["base_game_number"] == 1
    assert changes["deck_total"] == 60
    assert changes["base_deck_total"] == 60
    assert changes["lands"] == 24
    assert changes["base_lands"] == 24
    by_name = {row["display_name"]: row for row in changes["cards"]}
    assert by_name["Sheltered by Ghosts"]["delta"] == 2
    assert by_name["Mouse Mentor"]["delta"] == -2
    assert by_name["Mouse Mentor"]["quantity"] == 2
    assert by_name["Mountain"]["delta"] == 0
    assert changes["removed"] == []
    # Game 1 itself has no changes section.
    assert game_detail(db_path, "game-1")["deck_changes"] is None


def test_deck_detail_interaction_profile_and_mode_splits(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        # game-1 has full interaction telemetry; game-2 predates it (all NULL).
        conn.execute(
            """
            update game_participant_stats set
              removal_played = 4, removal_drawn = 6, wipes_played = 1, wipes_drawn = 1,
              bounces_played = 2, bounces_drawn = 3, counters_played = 3, counters_drawn = 4,
              creatures_removed = 2, noncreatures_removed = 1,
              creatures_bounced = 1, noncreatures_bounced = 0,
              lands_lost = 2, lands_replaced = 1,
              tokens_created = 5, tokens_destroyed = 2, tokens_sacrificed = 1, tokens_exiled = 0
            where game_id = 'game-1' and participant_id = 'player-1'
            """
        )
        conn.execute(
            "update game_participant_stats set spells_countered = 2 "
            "where game_id = 'game-1' and participant_id = 'opponent-1'"
        )
        # A ranked Bo1 match, a Bo3 match, a Competitive Brawl match, and a
        # draft match (excluded from every split) for the same deck.
        extra = [
            ("match-l", "Ladder", 1, "game-l", "win"),
            ("match-b3", "Constructed_BestOf3", 3, "game-b3", "loss"),
            ("match-cb", "Brawl_Ladder", 1, "game-cb", "win"),
            ("match-d", "PremierDraft_MSH_20260623", 1, "game-d", "win"),
        ]
        for match_id, fmt, best_of, game_id, outcome in extra:
            conn.execute(
                "insert into matches (id, session_id, format, queue, event_name, best_of) "
                "values (?, 'session-1', ?, ?, ?, ?)",
                (match_id, fmt, fmt, fmt, best_of),
            )
            conn.execute(
                "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
                "values (?, 'session-1', ?, 1, '2026-06-05T00:01:00', ?)",
                (game_id, match_id, outcome),
            )
            conn.execute(
                "insert into participants (id, game_id, seat_id, role, deck_name) "
                "values (?, ?, 1, 'player', 'Boros Mouse')",
                (f"{game_id}-p", game_id),
            )

    detail = deck_detail(db_path, "Boros Mouse")

    interaction = detail["interaction_profile"]
    # Only game-1 carries telemetry; game-2's NULLs never dilute the averages.
    assert interaction["games_tracked"] == 1
    you = interaction["player"]
    assert you["removal_played"] == 4
    assert you["removal_drawn"] == 6
    assert you["counters_landed"] == 2  # opponent's spells_countered
    assert you["counters_failed"] == 1  # 3 played - 2 landed
    assert you["creatures_removed"] == 2
    assert you["lands_lost"] == 2
    assert you["lands_unreplaced"] == 1  # 2 destroyed - 1 replaced
    assert you["land_replacement_pct"] == 50
    assert you["tokens_created"] == 5
    assert you["tokens_destroyed"] == 2
    opp = interaction["opponent"]
    assert opp["removal_played"] is None  # opponent row never got the columns
    assert opp["counters_landed"] is None  # player spells_countered is NULL

    splits = detail["mode_splits"]
    standard = splits["standard"]
    # Fixture Play games: 1-1 unranked Bo1; Ladder adds a ranked Bo1 win;
    # Constructed_BestOf3 adds an unranked Bo3 loss. Draft contributes nothing.
    assert standard["ranked"]["matches"] == 1 and standard["ranked"]["wins"] == 1
    assert standard["unranked"]["matches"] == 3
    assert standard["unranked"]["wins"] == 1 and standard["unranked"]["losses"] == 2
    assert standard["bo1"]["matches"] == 3 and standard["bo1"]["wins"] == 2
    assert standard["bo3"]["matches"] == 1 and standard["bo3"]["losses"] == 1
    brawl = splits["brawl"]
    assert brawl["competitive"]["matches"] == 1 and brawl["competitive"]["wins"] == 1
    assert brawl["casual"] is None


def test_deck_detail_mode_splits_absent_for_nonstandard_decks(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        # Re-point the deck's only matches at a draft queue.
        conn.execute(
            "update matches set format = 'PremierDraft_MSH_20260623', "
            "queue = 'PremierDraft_MSH_20260623' where id = 'match-1'"
        )

    detail = deck_detail(db_path, "Boros Mouse")
    assert detail["mode_splits"] is None
    assert detail["interaction_profile"] is None  # fixture rows have NULL interaction stats


def test_deck_detail_turn_timing_and_draw_quality_averages(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    detail = deck_detail(db_path, "Boros Mouse")

    timing = detail["turn_timing"]
    # Fixture turns: player seat 1 -> 40+20 (game-1) + 25 (game-2) = 85 over 3
    # turns in 2 games; opponent seat 2 -> 30 + 45+35 = 110 over 3 turns.
    assert timing["player"]["turns_timed"] == 3
    assert timing["player"]["avg_total_seconds"] == 42.5
    assert timing["player"]["avg_turn_seconds"] == 28.3
    assert timing["opponent"]["avg_total_seconds"] == 55.0

    profile = detail["land_profile"]
    assert profile["avg_cards_seen"] is not None
    assert profile["classified_games"] >= 1


def test_deck_detail_played_mana_inputs(tmp_path):
    """played_mana ships per-seat play totals + turns for the UI's mana math."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 11, "Mouse Mentor (Creature 2/1)", "Creature", 2),
                ("game-2", "player-2", 11, "Mouse Mentor (Creature 2/1)", "Creature", 1),
                ("game-1", "player-1", 12, "Mountain (Land)", "Land", 3),
                ("game-1", "opponent-1", 21, "Duress", "Sorcery", 2),
                ("game-2", "player-2", 13, "Shock", "Instant", 0),  # never played
            ],
        )

    detail = deck_detail(db_path, "Boros Mouse")

    played = detail["played_mana"]
    # Each seat took 4 turns in game-1 and 5 in game-2.
    assert played["player"]["turns"] == 9
    assert played["opponent"]["turns"] == 9
    player_cards = {row["display_name"]: row for row in played["player"]["cards"]}
    # "(Creature 2/1)"-style suffixes are cleaned and copies merged across games.
    assert player_cards["Mouse Mentor"]["times_played"] == 3
    assert player_cards["Mouse Mentor"]["type_category"] == "Creature"
    assert player_cards["Mountain"]["times_played"] == 3
    assert "Shock" not in player_cards
    opponent_cards = {row["display_name"]: row for row in played["opponent"]["cards"]}
    assert opponent_cards["Duress"]["times_played"] == 2


def test_deck_and_game_payloads_ship_arena_mana_costs(tmp_path):
    """card_mana maps display names to Arena-derived costs from the cards table."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", 11, "Mouse Mentor (Creature 2/1)", "Creature", 2),
                ("game-1", "opponent-1", 21, "Duress", "Sorcery", 1),
            ],
        )
        conn.executemany(
            "insert into cards (name, first_seen_at, mana_cost, mana_value) "
            "values (?, '2026-08-01T00:00:00', ?, ?)",
            [
                ("Mouse Mentor", "{R}{W}", 2.0),
                ("Duress", "{B}", 1.0),
                ("Swamp", "", 0.0),  # lands carry an empty (not NULL) cost
            ],
        )

    detail = deck_detail(db_path, "Boros Mouse")
    assert detail["card_mana"]["Mouse Mentor"] == {"mana_cost": "{R}{W}", "mana_value": 2.0}

    game = game_detail(db_path, "game-1")
    assert game["card_mana"]["Mouse Mentor"] == {"mana_cost": "{R}{W}", "mana_value": 2.0}
    assert game["card_mana"]["Duress"] == {"mana_cost": "{B}", "mana_value": 1.0}


def test_deck_colors_come_from_newest_decklist_casting_costs(tmp_path):
    """Deck colors use mana costs (not identity) from the latest decklist."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into cards (name, first_seen_at, mana_cost, color_identity) values (?, ?, ?, ?)",
            [
                ("Mountain", "2026-06-01T00:00:00", "", "R"),
                ("Mouse Mentor", "2026-06-01T00:00:00", "{R}{W}", "RW"),
                # Costs only {R}, but a {U} ability gives it UR identity —
                # identity must NOT leak blue into the deck's colors.
                ("Shock", "2026-06-01T00:00:00", "{R}", "UR"),
                ("Sheltered by Ghosts", "2026-06-01T00:00:00", "{1}{W}", "W"),
            ],
        )
        card_ids = {
            name: card_id
            for card_id, name in conn.execute("select id, name from cards")
        }
        for name, card_id in card_ids.items():
            conn.execute(
                "update game_deck_cards set card_id = ? where display_name = ?",
                (card_id, name),
            )

    snapshot = dashboard_snapshot(db_path)
    deck_row = next(row for row in snapshot["decks"] if row["deck_name"] == "Boros Mouse")
    assert deck_row["colors"] == "WR"

    detail = deck_detail(db_path, "Boros Mouse")
    assert detail["deck_colors"] == "WR"


def test_card_detail_opponent_playable_counts_color_covered_games(tmp_path):
    """'Could have played it' = games whose revealed opponent colors cover the cost."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into cards (name, first_seen_at, mana_cost, color_identity) values (?, ?, ?, ?)",
            [
                ("Duress", "2026-06-01T00:00:00", "{B}", "B"),
                ("Swamp", "2026-06-01T00:00:00", "", "B"),
                ("Shock", "2026-06-01T00:00:00", "{R}", "R"),
            ],
        )
        card_ids = {
            name: card_id for card_id, name in conn.execute("select id, name from cards")
        }
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                # game-1 opponent showed black mana and cast Duress.
                ("game-1", "opponent-1", card_ids["Swamp"], "Swamp", "Land", 3),
                ("game-1", "opponent-1", card_ids["Duress"], "Duress", "Sorcery", 1),
                # game-2 opponent was mono-red: Duress was never castable there.
                ("game-2", "opponent-2", card_ids["Shock"], "Shock", "Instant", 2),
            ],
        )

    detail = card_detail(db_path, "Duress")

    playable = detail["opponent_playable"]
    assert playable["required_colors"] == "B"
    assert playable["games_possible"] == 1  # game-2's red opponent excluded
    assert playable["games_played"] == 1
    assert playable["pct"] == 100.0


def test_card_detail_opponent_playable_hybrid_costs(tmp_path):
    """A hybrid pip is castable off EITHER of its colors: Boros Reckoner
    ({R/W}{R/W}{R/W}) counts for white opponents, red opponents, and both —
    and it is NOT 'no colored mana needed'."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into cards (name, first_seen_at, mana_cost, color_identity) values (?, ?, ?, ?)",
            [
                ("Boros Reckoner", "2026-06-01T00:00:00", "{R/W}{R/W}{R/W}", "WR"),
                ("Plains", "2026-06-01T00:00:00", "", "W"),
                ("Shock", "2026-06-01T00:00:00", "{R}", "R"),
                ("Duress", "2026-06-01T00:00:00", "{B}", "B"),
            ],
        )
        card_ids = {
            name: card_id for card_id, name in conn.execute("select id, name from cards")
        }
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                # game-1 opponent showed white and cast the Reckoner.
                ("game-1", "opponent-1", card_ids["Plains"], "Plains", "Land", 3),
                ("game-1", "opponent-1", card_ids["Boros Reckoner"], "Boros Reckoner", "Creature", 1),
                # game-2 opponent showed only red — {R/W} pips still payable.
                ("game-2", "opponent-2", card_ids["Shock"], "Shock", "Instant", 2),
            ],
        )

    playable = card_detail(db_path, "Boros Reckoner")["opponent_playable"]
    # Both colors of the hybrid pips are reported, so the UI never claims
    # the card needs no colored mana.
    assert playable["required_colors"] == "WR"
    assert playable["games_possible"] == 2  # white-only AND red-only both count

    # A mono-black opponent could not cast it: rewrite game-2 to black. If
    # hybrids were treated as "no colored mana", this game would still count.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "update game_card_summary set card_id = ?, display_name = 'Duress' "
            "where game_id = 'game-2'",
            (card_ids["Duress"],),
        )
    playable = card_detail(db_path, "Boros Reckoner")["opponent_playable"]
    assert playable["games_possible"] == 1


def test_deck_color_scoring_rules():
    """Lands lead; hybrids never force a color; single-card colors drop."""
    from mtga_tracker.dashboard import _score_deck_colors

    rows = [
        ("Land", "", "B", 22),  # 22 Swamps -> B score 44
        ("Creature", "{1}{B}", "B", 4),
        # Hybrid blue-or-black: castable off Swamps alone, adds NO blue.
        ("Creature", "{1}{U/B}", "UB", 4),
        # One off-color splash card: a single card never adds a color.
        ("Sorcery", "{2}{G}", "G", 1),
    ]
    assert _score_deck_colors(rows) == "B"

    # Two green cards but no green sources still stay off (score 2 < 3);
    # add a couple of dual lands and green becomes real.
    rows_with_duals = rows + [
        ("Sorcery", "{2}{G}", "G", 2),
        ("Land", "", "BG", 2),
    ]
    assert _score_deck_colors(rows_with_duals) == "BG"


def test_deck_colors_fall_back_to_observed_cards(tmp_path):
    """Decks tracked before decklist capture still get colors from play."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into cards (name, first_seen_at, mana_cost, color_identity) values (?, ?, ?, ?)",
            [
                ("Mountain", "2026-06-01T00:00:00", "", "R"),
                ("Mouse Mentor", "2026-06-01T00:00:00", "{R}{W}", "RW"),
            ],
        )
        card_ids = {
            name: card_id for card_id, name in conn.execute("select id, name from cards")
        }
        # No submitted decklist at all for this deck...
        conn.execute("delete from game_deck_cards")
        # ...but the tracker saw it play Mountains and Mouse Mentors.
        conn.executemany(
            """
            insert into game_card_summary (
                game_id, participant_id, card_id, display_name, type_category, played_count
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("game-1", "player-1", card_ids["Mountain"], "Mountain", "Land", 6),
                ("game-1", "player-1", card_ids["Mouse Mentor"], "Mouse Mentor", "Creature", 3),
            ],
        )

    snapshot = dashboard_snapshot(db_path)
    deck_row = next(row for row in snapshot["decks"] if row["deck_name"] == "Boros Mouse")
    assert deck_row["colors"] == "WR"


def test_deck_and_game_detail_carry_brawl_commanders(tmp_path):
    """Brawl: the deck page gets its commander(s) + record vs each opponent
    commander; the game page gets both seats' commanders with colors."""
    db_path = tmp_path / "analytics.sqlite3"
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('s1', '2026-08-12T10:00:00')"
        )
        conn.execute(
            "INSERT INTO cards (name, color_identity, first_seen_at) "
            "VALUES ('Belladonna Took', 'WB', '2026-08-12T10:00:00')"
        )
        for n, (outcome, theirs) in enumerate(
            (("win", "The Unbeatable Squirrel Girl"), ("loss", "Kaalia of the Vast")), start=1
        ):
            conn.execute(
                "INSERT INTO matches (id, session_id, format) VALUES (?, 's1', 'Historic Brawl')",
                (f"m{n}",),
            )
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, started_at, ended_at, outcome) "
                "VALUES (?, 's1', ?, ?, '2026-08-12T10:10:00', ?)",
                (f"g{n}", f"m{n}", f"2026-08-12T10:0{n}:00", outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name, deck_name) "
                "VALUES (?, ?, 'player', 'Tapps', 'MWM Bella')",
                (f"g{n}:p", f"g{n}"),
            )
            conn.execute(
                "INSERT INTO participant_commanders (participant_id, card_name) "
                "VALUES (?, 'Belladonna Took')",
                (f"g{n}:p",),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name) "
                "VALUES (?, ?, 'opponent', 'them')",
                (f"g{n}:o", f"g{n}"),
            )
            conn.execute(
                "INSERT INTO participant_commanders (participant_id, card_name) VALUES (?, ?)",
                (f"g{n}:o", theirs),
            )
    conn.close()

    detail = deck_detail(db_path, "MWM Bella")
    assert detail["commanders"] == [{"card_name": "Belladonna Took", "colors": "WB"}]
    faced = {row["commander"]: (row["wins"], row["losses"]) for row in detail["faced_commanders"]}
    assert faced == {"The Unbeatable Squirrel Girl": (1, 0), "Kaalia of the Vast": (0, 1)}

    game = game_detail(db_path, "g1")
    assert game["player"]["commanders"] == [{"card_name": "Belladonna Took", "colors": "WB"}]
    assert game["opponent"]["commanders"] == [
        {"card_name": "The Unbeatable Squirrel Girl", "colors": ""}
    ]


def test_export_text_gains_commander_block_for_brawl():
    from mtga_tracker.dashboard import _with_commander_block

    text = "About\nName MWM Bella\n\nDeck\n40 Plains\n49 Hare Apparent"
    patched = _with_commander_block(text, [{"card_name": "Belladonna Took", "colors": "WB"}])
    assert patched == (
        "About\nName MWM Bella\n\nCommander\n1 Belladonna Took\n\nDeck\n40 Plains\n49 Hare Apparent"
    )
    # Idempotent, and untouched for non-Brawl decks.
    assert _with_commander_block(patched, [{"card_name": "Belladonna Took", "colors": "WB"}]) == patched
    assert _with_commander_block(text, []) == text
    assert _with_commander_block(None, [{"card_name": "X", "colors": ""}]) is None


def test_opponents_count_bo3_matches_once(tmp_path):
    """A Bo3 is one pairing: opponent lists count it as one match decided by
    its games, and the opponent page carries match rollup fields."""
    from mtga_tracker.dashboard import opponents_list

    db_path = tmp_path / "analytics.sqlite3"
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('s1', '2026-08-12T10:00:00')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format, best_of) VALUES ('m1', 's1', 'Play', 3)"
        )
        for n, outcome in enumerate(("win", "loss", "win"), start=1):
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, game_number, started_at, ended_at, outcome) "
                "VALUES (?, 's1', 'm1', ?, ?, ?, ?)",
                (f"g{n}", n, f"2026-08-12T10:0{n}:00", f"2026-08-12T10:0{n}:30", outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name, deck_name) "
                "VALUES (?, ?, 'player', 'Tapps', 'Deck')",
                (f"g{n}:p", f"g{n}"),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name) "
                "VALUES (?, ?, 'opponent', 'IvanRehder')",
                (f"g{n}:o", f"g{n}"),
            )
    conn.close()

    listing = opponents_list(db_path)
    row = listing["opponents"][0]
    assert row["opponent_name"] == "IvanRehder"
    assert (row["games"], row["wins"], row["losses"], row["win_rate"]) == (1, 1, 0, 100.0)

    snapshot = dashboard_snapshot(db_path)
    top = snapshot["top_opponents"][0]
    assert (top["games"], top["wins"], top["losses"]) == (1, 1, 0)

    detail = opponent_detail(db_path, "IvanRehder")
    assert detail["summary"]["games"] == 3
    assert detail["summary"]["matches"] == 1
    assert detail["summary"]["match_wins"] == 1
    assert detail["summary"]["match_losses"] == 0
    assert all(game["match_id"] == "m1" for game in detail["games"])
    assert detail["games"][0]["match_wins"] == 2
    assert detail["games"][0]["match_losses"] == 1


def test_game_detail_expected_lands_borrow_nearest_decklist(tmp_path):
    """A game with no captured decklist uses the same deck's nearest submitted
    decklist for Expected Lands instead of the generic 40% heuristic."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("delete from game_deck_cards where game_id = 'game-1'")
        conn.execute(
            "update game_deck_cards set quantity = 22 "
            "where game_id = 'game-2' and display_name = 'Mountain'"
        )

    quality = game_detail(db_path, "game-1")["draw_quality"]
    # game-2's decklist: 22 lands / 58 cards.
    assert quality["expected_land_rate"] == 37.9
    assert quality["land_rate_source"] == "deck_history"

    # A deck with no decklist anywhere still falls back to the estimate.
    with sqlite3.connect(db_path) as conn:
        conn.execute("delete from game_deck_cards")
    quality = game_detail(db_path, "game-1")["draw_quality"]
    assert quality["expected_land_rate"] == 40.0
    assert quality["land_rate_source"] == "estimate"


def test_deck_land_profile_expected_lands_from_newest_decklist(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "update game_deck_cards set quantity = 22 "
            "where game_id = 'game-2' and display_name = 'Mountain'"
        )

    profile = deck_detail(db_path, "Boros Mouse")["land_profile"]
    assert profile["deck_size"] == 58
    assert profile["lands"] == 22
    assert profile["expected_land_pct"] == 37.9
    assert profile["avg_lands_seen"] is not None
    assert profile["avg_lands_drawn"] is not None
    assert profile["expected_lands_seen"] == round(
        profile["avg_cards_seen"] * 37.9 / 100.0, 1
    )


def test_draw_quality_batch_matches_per_game_helper(tmp_path):
    """The set-based batch must agree with the per-game helper it replaces,
    including the nearest-decklist fallback and the estimate fallback."""
    from mtga_tracker.dashboard import _draw_quality_batch, _game_draw_quality

    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        # game-1 loses its decklist -> borrows game-2's (22 lands / 58).
        conn.execute("delete from game_deck_cards where game_id = 'game-1'")
        conn.execute(
            "update game_deck_cards set quantity = 22 "
            "where game_id = 'game-2' and display_name = 'Mountain'"
        )
        rows = conn.execute(
            "select game_id, id, deck_size from participants where role = 'player'"
        ).fetchall()
        batch = _draw_quality_batch(conn, [(pid, size) for _, pid, size in rows])
        for game_id, pid, size in rows:
            single = _game_draw_quality(conn, game_id, pid, size)
            assert batch[pid] == single, game_id
        assert batch["player-1"]["land_rate_source"] == "deck_history"
        assert batch["player-1"]["expected_land_rate"] == 37.9

        conn.execute("delete from game_deck_cards")
        batch = _draw_quality_batch(conn, [(pid, size) for _, pid, size in rows])
        assert batch["player-1"]["land_rate_source"] == "estimate"
        assert _draw_quality_batch(conn, []) == {}


def test_split_card_index_resolves_faces(tmp_path):
    from mtga_tracker.dashboard import _arena_export_card_name, _split_card_index

    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into cards (name, primary_type, first_seen_at) "
            "values ('Fire // Ice', 'Instant', '2026-06-01')"
        )
        index = _split_card_index(conn)
        assert index["Fire"] == "Fire // Ice"
        assert index["Ice"] == "Fire // Ice"
        assert _arena_export_card_name(conn, "Fire (Instant)", index) == "Fire // Ice"
        assert _arena_export_card_name(conn, "Fire // Ice", index) == "Fire // Ice"
        assert _arena_export_card_name(conn, "Mountain (Land)", index) == "Mountain"
        # Without a prebuilt index it builds its own.
        assert _arena_export_card_name(conn, "Ice") == "Fire // Ice"


def test_response_cache_serves_until_analytics_change(tmp_path):
    from mtga_tracker import dashboard as dash

    db_path = _sample_dashboard_db(tmp_path)
    dash.clear_response_cache()
    calls = []

    def compute():
        calls.append(1)
        return b'{"n": %d}' % len(calls)

    first = dash.cached_response(db_path, "/api/snapshot", "", compute)
    again = dash.cached_response(db_path, "/api/snapshot", "", compute)
    assert first == again == b'{"n": 1}'
    assert len(calls) == 1
    # A different query string is a different entry.
    assert dash.cached_response(db_path, "/api/snapshot", "days=30", compute) == b'{"n": 2}'

    # A finished game (new games row) moves the fingerprint -> recompute.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
            "values ('game-9', 'session-1', 'match-1', 3, '2026-06-05T00:00:00', 'win')"
        )
    assert dash.cached_response(db_path, "/api/snapshot", "", compute) == b'{"n": 3}'

    # So does a late AI archetype landing on an opponent row.
    with sqlite3.connect(db_path) as conn:
        conn.execute("update participants set deck_archetype = 'Izzet Prowess' where id = 'opponent-1'")
    assert dash.cached_response(db_path, "/api/snapshot", "", compute) == b'{"n": 4}'

    # And an explicit clear (every POST does this).
    dash.clear_response_cache()
    assert dash.cached_response(db_path, "/api/snapshot", "", compute) == b'{"n": 5}'

    # A database with no fingerprint tables bypasses the cache entirely.
    empty = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty).close()
    assert dash.cached_response(empty, "/api/snapshot", "", compute) == b'{"n": 6}'
    assert dash.cached_response(empty, "/api/snapshot", "", compute) == b'{"n": 7}'
