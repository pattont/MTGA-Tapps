"""GET /api/replay, replay availability on game rows, and visible-row filtering."""

import json
import sqlite3
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from mtga_tracker import live_api, replay_builder
from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.dashboard import (
    DashboardHandler,
    _replay_availability,
    _visible_events_clause,
    all_games,
    clear_response_cache,
    dashboard_snapshot,
    deck_detail,
    game_detail,
    opponent_detail,
)

SILENT_TEXT = "untap 2"


@pytest.fixture(autouse=True)
def _no_arena_lookups(monkeypatch):
    """Image URLs resolve from local data only; keep tests off the real Arena DB."""
    monkeypatch.setattr(replay_builder, "image_resolver_override", lambda arena_id: None)
    monkeypatch.setattr(replay_builder, "card_facts_override", lambda: {})
    clear_response_cache()
    yield
    clear_response_cache()


def _event(
    conn,
    game_id,
    text,
    event_type,
    turn,
    *,
    visible=1,
    subtype=None,
    payload=None,
    seat=None,
    object_id=None,
    zone=(None, None),
    lives=(20, 20),
    elapsed=0,
):
    conn.execute(
        """
        INSERT INTO game_events (
            session_id, match_id, game_id, event_time, elapsed_seconds, turn_number, phase,
            event_type, event_subtype, text, player_life, opponent_life, visible, seat_id,
            object_id, zone_from, zone_to, payload_json
        ) VALUES ('s1', 'm1', ?, ?, ?, ?, 'Phase_Main1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            f"2026-06-04T00:00:{elapsed:02d}",
            elapsed,
            turn,
            event_type,
            subtype,
            text,
            lives[0],
            lives[1],
            visible,
            seat,
            object_id,
            zone[0],
            zone[1],
            json.dumps(payload) if payload is not None else None,
        ),
    )


def _replay_db(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('s1', '2026-06-04T00:00:00')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format, queue, best_of) "
            "VALUES ('m1', 's1', 'Ladder', 'Ladder', 1)"
        )
        for number, (game_id, version) in enumerate(
            (("g-old", None), ("g-rec", 1), ("g-none", None)), start=1
        ):
            conn.execute(
                """
                INSERT INTO games (id, session_id, match_id, game_number, started_at, outcome,
                                   duration_seconds, total_turns, replay_version)
                VALUES (?, 's1', 'm1', ?, ?, 'win', 120, 2, ?)
                """,
                (game_id, number, f"2026-06-04T00:0{number}:00", version),
            )
            for role, seat, name in (("player", 1, "Tapps"), ("opponent", 2, "Rival")):
                conn.execute(
                    """
                    INSERT INTO participants (id, game_id, seat_id, role, display_name, deck_name,
                                              starting_life, ending_life, deck_size)
                    VALUES (?, ?, ?, ?, ?, 'Mono Green', 20, ?, 60)
                    """,
                    (
                        f"{game_id}-{role}",
                        game_id,
                        seat,
                        role,
                        name,
                        20 if role == "player" else 18,
                    ),
                )
        # A pre-replay game: printed text rows only.
        _event(conn, "g-old", "Turn 1 - YOUR TURN", "turn", 1)
        _event(conn, "g-old", "[0:01] You: played [Forest (Land)]", "land", 1, elapsed=1)
        _event(
            conn,
            "g-old",
            "[0:02] Opponent: lost 2 life (now 18)",
            "life_loss",
            1,
            lives=(20, 18),
            elapsed=2,
        )
        # A recorded game: printed rows with structure plus one silent row.
        _event(
            conn,
            "g-rec",
            "Turn 1 - YOUR TURN",
            "turn",
            1,
            subtype="turn",
            seat=1,
            payload={"active_seat": 1},
        )
        _event(
            conn,
            "g-rec",
            "[0:01] You: played [Forest (Land)]",
            "land",
            1,
            subtype="move",
            seat=1,
            object_id=7,
            zone=("hand", "battlefield"),
            payload={"reason": "play_land", "name": "Forest"},
            elapsed=1,
        )
        _event(
            conn,
            "g-rec",
            SILENT_TEXT,
            "silent",
            1,
            visible=0,
            subtype="untap",
            payload={"object_ids": [7]},
            elapsed=2,
        )
        _event(
            conn,
            "g-rec",
            "[0:03] Opponent: lost 2 life (now 18)",
            "life_loss",
            1,
            subtype="life",
            seat=2,
            lives=(20, 18),
            elapsed=3,
        )
    return db_path


def _serve(db_path, paths):
    class Handler(DashboardHandler):
        pass

    Handler.db_path = db_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = []
    conn = HTTPConnection("127.0.0.1", server.server_address[1])
    try:
        for path in paths:
            conn.request("GET", path)
            response = conn.getresponse()
            results.append((response.status, response.getheader("Content-Type"), response.read()))
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return results


def test_replay_endpoint_statuses_and_sources(tmp_path):
    db_path = _replay_db(tmp_path)
    missing, unknown, unavailable, old, recorded = _serve(
        db_path,
        [
            "/api/replay",
            "/api/replay?id=nope",
            "/api/replay?id=g-none",
            "/api/replay?id=g-old",
            "/api/replay?id=g-rec",
        ],
    )
    assert missing[0] == 400
    assert unknown[0] == 404 and json.loads(unknown[2])["error"] == "not_found"
    assert unavailable[0] == 404
    assert json.loads(unavailable[2]) == {"error": "replay_unavailable", "reason": "no events"}

    assert old[0] == 200 and old[1].startswith("application/json")
    old_stream = json.loads(old[2])
    assert old_stream["fidelity"] == "reconstructed" and old_stream["replay_version"] is None
    assert old_stream["version"] == 1 and old_stream["events"][0]["kind"] == "game_start"
    assert old_stream["game"]["format"] and old_stream["player_seat"] == 1

    assert recorded[0] == 200
    stream = json.loads(recorded[2])
    assert stream["fidelity"] == "recorded" and stream["replay_version"] == 1
    untap = next(e for e in stream["events"] if e["kind"] == "untap")
    assert untap["objs"] == ["7"] and untap["log"] is None
    assert all(SILENT_TEXT not in ((e["log"] or {}).get("text") or "") for e in stream["events"])


def test_replay_endpoint_is_cached_until_the_database_changes(tmp_path, monkeypatch):
    db_path = _replay_db(tmp_path)
    calls = []
    real = replay_builder.replay_for_game

    def counting(path, game_id):
        calls.append(game_id)
        return real(path, game_id)

    monkeypatch.setattr(replay_builder, "replay_for_game", counting)
    first, second = _serve(db_path, ["/api/replay?id=g-old", "/api/replay?id=g-old"])
    assert first[2] == second[2] and calls == ["g-old"]


def test_replay_availability_on_every_game_row_endpoint(tmp_path):
    db_path = _replay_db(tmp_path)
    expected = {
        "g-old": {"state": "reconstructed", "reason": None},
        "g-rec": {"state": "recorded", "reason": None},
        "g-none": {"state": "unavailable", "reason": "no events"},
    }
    detail = game_detail(db_path, "g-rec")
    assert detail["game"]["replay"] == expected["g-rec"]
    assert {row["game_id"]: row["replay"] for row in detail["match_games"]} == expected

    assert {row["game_id"]: row["replay"] for row in all_games(db_path)["games"]} == expected
    assert {
        row["game_id"]: row["replay"] for row in dashboard_snapshot(db_path)["recent"]
    } == expected
    assert {
        row["game_id"]: row["replay"] for row in deck_detail(db_path, "Mono Green")["recent"]
    } == expected
    assert {
        row["game_id"]: row["replay"] for row in opponent_detail(db_path, "Rival")["games"]
    } == expected

    with sqlite3.connect(db_path) as conn:
        live_rows = live_api._games_payload(conn, "s1")
    # The live rail lists today's/this session's games plus the latest one.
    assert live_rows
    assert all(row["replay"] == expected[row["id"]] for row in live_rows)


def test_silent_rows_never_reach_the_timeline_or_live_feed(tmp_path):
    db_path = _replay_db(tmp_path)
    detail = game_detail(db_path, "g-rec")
    texts = [row["text"] for row in detail["timeline"]]
    assert SILENT_TEXT not in texts and len(texts) == 3
    assert len(detail["life_curve"]) == 3
    with sqlite3.connect(db_path) as conn:
        events, seq = live_api._events_payload(conn, "g-rec", 0)
        delta, _ = live_api._events_payload(conn, "g-rec", 1)
    assert [e["text"] for e in events] == [t for t in texts]
    assert SILENT_TEXT not in [e["text"] for e in delta]
    assert seq == events[-1]["id"]


def test_availability_query_is_an_index_search_not_a_scan(tmp_path):
    db_path = _replay_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT DISTINCT game_id FROM game_events WHERE game_id IN (?, ?)",
            ("g-old", "g-rec"),
        ).fetchall()
        assert _replay_availability(conn, ["g-old", "g-old", None]) == {
            "g-old": {"state": "reconstructed", "reason": None}
        }
    details = " ".join(str(row[-1]) for row in plan)
    assert "SEARCH game_events USING COVERING INDEX" in details
    assert "SCAN game_events" not in details


def test_helpers_tolerate_databases_without_replay_columns(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.sqlite3")
    conn.execute("CREATE TABLE game_events (id INTEGER PRIMARY KEY, game_id TEXT, text TEXT)")
    conn.execute("CREATE TABLE games (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO games VALUES ('g')")
    conn.execute("INSERT INTO game_events (game_id, text) VALUES ('g', 'Turn 1 - YOUR TURN')")
    assert _visible_events_clause(conn) == ""
    assert _replay_availability(conn, ["g", "x"]) == {
        "g": {"state": "reconstructed", "reason": None},
        "x": {"state": "unavailable", "reason": "no events"},
    }
    conn.close()


def test_game_rows_carry_the_opponent_name(tmp_path):
    db_path = _replay_db(tmp_path)
    assert {row["game_id"]: row["opponent_name"] for row in all_games(db_path)["games"]} == {
        "g-old": "Rival",
        "g-rec": "Rival",
        "g-none": "Rival",
    }
    assert {row["opponent_name"] for row in dashboard_snapshot(db_path)["recent"]} == {"Rival"}


def test_timeline_rows_and_stream_events_name_their_game_events_row(tmp_path):
    db_path = _replay_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        printed_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM game_events WHERE game_id = 'g-rec' AND visible = 1 ORDER BY id"
            )
        ]
        silent_id = conn.execute(
            "SELECT id FROM game_events WHERE game_id = 'g-rec' AND visible = 0"
        ).fetchone()[0]
    detail = game_detail(db_path, "g-rec")
    assert [row["id"] for row in detail["timeline"]] == printed_ids

    for game_id in ("g-rec", "g-old"):
        stream = replay_builder.replay_for_game(db_path, game_id)
        events = stream["events"]
        assert all("row_id" in event for event in events)
        # Setup and finish events are synthesized; logged events point at their row.
        assert events[0]["kind"] == "game_start" and events[0]["row_id"] is None
        assert events[-1]["kind"] == "game_end" and events[-1]["row_id"] is None
        logged = [event["row_id"] for event in events if event["log"]]
        assert logged and all(isinstance(row_id, int) for row_id in logged)
    recorded = replay_builder.replay_for_game(db_path, "g-rec")
    assert {e["row_id"] for e in recorded["events"] if e["log"]} == set(printed_ids)
    untap = next(e for e in recorded["events"] if e["kind"] == "untap")
    assert untap["row_id"] == silent_id
