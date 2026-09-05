"""In-game overlay: library state math, the tracker's library bookkeeping,
and the /api/overlay endpoint the Tauri overlay polls."""

import json
import sqlite3
from datetime import datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from mtga_tracker import live_api
from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.dashboard import DashboardHandler
from mtga_tracker.overlay_state import (
    build_overlay_state,
    idle_overlay_state,
    odds_within,
)
from mtga_tracker.state import CardEvent

from test_tracker_combat_winner import make_tracker


# --------------------------------------------------------------------------
# Pure math
# --------------------------------------------------------------------------


def test_odds_within_matches_hypergeometric_by_hand():
    # 3 copies in a 41-card library: next draw 3/41, within 2 = 1 - C(38,2)/C(41,2)
    assert odds_within(3, 41, 1) == pytest.approx(3 / 41)
    assert odds_within(3, 41, 2) == pytest.approx(1 - (703 / 820))
    assert odds_within(3, 41, 3) == pytest.approx(1 - (8436 / 10660))
    # Edge cases: nothing left, empty library, more copies than cards, more draws than cards.
    assert odds_within(0, 41, 1) == 0.0
    assert odds_within(2, 0, 1) == 0.0
    assert odds_within(5, 3, 1) == 1.0
    assert odds_within(1, 2, 5) == 1.0


def _info(name):
    table = {
        "Plains": ("Land", None, 0.0),
        "Caves of Koilos": ("Land", None, 0.0),
        "Skeleton Crew": ("Creature", "{1}{B}", 2.0),
        "Fell": ("Instant", "{1}{B}", 2.0),
    }
    return table.get(name, (None, None, None))


def test_build_overlay_state_counts_and_odds():
    deck = ["Plains"] * 8 + ["Caves of Koilos"] * 4 + ["Skeleton Crew"] * 4 + ["Fell"] * 4
    state = build_overlay_state(
        deck=deck,
        departures={"Plains": 2, "Skeleton Crew": 1, "Fell": 4},  # 7 gone
        returns={"Fell": 1},  # one Fell shuffled back
        library_size=14,  # 20 - 7 + 1
        card_info=_info,
        game_active=True,
        deck_name="Orzhov Skellies",
        format_label="Standard BO1 (Ranked)",
        opponent_name="ropeez",
        turn_number=7,
        on_play=True,
    )
    by_name = {card["name"]: card for card in state["cards"]}
    assert state["deck_size"] == 20 and state["library_size"] == 14
    assert state["unaccounted"] == 0
    assert by_name["Plains"]["left"] == 6 and by_name["Plains"]["basic"] is True
    assert by_name["Caves of Koilos"]["left"] == 4 and by_name["Caves of Koilos"]["basic"] is False
    assert by_name["Skeleton Crew"]["left"] == 3
    assert by_name["Fell"]["left"] == 1 and by_name["Fell"]["mana_cost"] == "{1}{B}"
    assert state["lands_left"] == 10 and state["lands_total"] == 12
    assert state["land_odds"]["1"] == pytest.approx(round(100 * 10 / 14, 1))
    assert by_name["Fell"]["odds"]["1"] == pytest.approx(round(100 * 1 / 14, 1))
    assert by_name["Fell"]["odds"]["3"] == pytest.approx(round(100 * odds_within(1, 14, 3), 1))
    assert state["on_play"] is True and state["turn_number"] == 7


def test_build_overlay_state_clamps_and_reports_unaccounted():
    deck = ["Plains"] * 2
    # More departures than copies (a log hiccup) never goes negative;
    # a library larger than what is accounted for shows the gap.
    state = build_overlay_state(
        deck=deck,
        departures={"Plains": 5},
        returns={},
        library_size=3,
        card_info=_info,
        game_active=True,
    )
    assert state["cards"][0]["left"] == 0
    assert state["unaccounted"] == 3
    # No reported library size -> the accounted count is the library.
    state = build_overlay_state(
        deck=deck, departures={}, returns={}, library_size=None, card_info=_info, game_active=True
    )
    assert state["library_size"] == 2 and state["unaccounted"] == 0


def test_idle_state_shape():
    idle = idle_overlay_state(game_active=False, updated_at="2026-09-04T00:00:00")
    assert idle["cards"] == [] and idle["library_size"] == 0
    assert idle["game_active"] is False and idle["mid_game_attach"] is False
    attached = idle_overlay_state(game_active=True, mid_game_attach=True, deck_name="X")
    assert attached["mid_game_attach"] is True and attached["deck_name"] == "X"


# --------------------------------------------------------------------------
# Tracker bookkeeping
# --------------------------------------------------------------------------


def _zones():
    return {
        10: {"zoneId": 10, "type": "ZoneType_Library", "ownerSeatId": 1},
        11: {"zoneId": 11, "type": "ZoneType_Hand", "ownerSeatId": 1},
        12: {"zoneId": 12, "type": "ZoneType_Graveyard", "ownerSeatId": 1},
        20: {"zoneId": 20, "type": "ZoneType_Library", "ownerSeatId": 2},
        21: {"zoneId": 21, "type": "ZoneType_Hand", "ownerSeatId": 2},
    }


def test_library_zone_transfers_are_counted_for_the_player_only():
    tracker = make_tracker()
    g = tracker.game_state
    g.player_seat_id = 1
    g.opponent_seat_id = 2
    g.opening_hand_capture_closed = True
    g.turn_number = 3
    zones = _zones()
    card = {"instanceId": 500, "grpId": 900}

    # Library -> hand (a draw): departure.
    tracker._observe_library_zone_transfer(card, {"id": 1}, zones, 10, 11)
    # Same annotation replayed in the next diff: not counted twice.
    tracker._observe_library_zone_transfer(card, {"id": 1}, zones, 10, 11)
    # Library -> graveyard (a mill): departure.
    tracker._observe_library_zone_transfer({"instanceId": 501, "grpId": 900}, {"id": 2}, zones, 10, 12)
    # Hand -> library (a bounce or Brainstorm put-back): return.
    tracker._observe_library_zone_transfer({"instanceId": 502, "grpId": 900}, {"id": 3}, zones, 11, 10)
    # Opponent's draw: nothing.
    tracker._observe_library_zone_transfer({"instanceId": 600, "grpId": 900}, {"id": 4}, zones, 20, 21)
    # Library -> library (a shuffle annotation): nothing.
    tracker._observe_library_zone_transfer({"instanceId": 503, "grpId": 900}, {"id": 5}, zones, 10, 10)

    assert g.library_departures == {"Card900": 2}
    assert g.library_returns == {"Card900": 1}


def test_library_zone_transfers_ignored_before_turn_one():
    """The London-mulligan bottom is a Put into the library after the kept
    hand is finalized; the kept hand already excludes it."""
    tracker = make_tracker()
    g = tracker.game_state
    g.player_seat_id = 1
    g.opening_hand_capture_closed = True
    g.turn_number = 0
    tracker._observe_library_zone_transfer({"instanceId": 1, "grpId": 900}, {"id": 1}, _zones(), 11, 10)
    assert g.library_returns == {}
    g.opening_hand_capture_closed = False
    g.turn_number = 2
    tracker._observe_library_zone_transfer({"instanceId": 2, "grpId": 900}, {"id": 2}, _zones(), 10, 11)
    assert g.library_departures == {}


def test_library_sizes_read_from_zone_list():
    tracker = make_tracker()
    tracker._observe_library_sizes(
        {
            "zones": [
                {"zoneId": 10, "type": "ZoneType_Library", "ownerSeatId": 1, "objectInstanceIds": list(range(47))},
                {"zoneId": 20, "type": "ZoneType_Library", "ownerSeatId": 2, "objectInstanceIds": list(range(31))},
                {"zoneId": 11, "type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [1, 2]},
            ]
        }
    )
    assert tracker.game_state.library_size_by_seat == {1: 47, 2: 31}


def test_overlay_state_json_from_tracker_state():
    tracker = make_tracker()
    g = tracker.game_state
    g.in_match = True
    g.game_start_time = datetime(2026, 9, 4, 20, 0)
    g.player_seat_id = 1
    g.opponent_seat_id = 2
    g.player_deck_name = "Skellies"
    g.opponent_display_name = "ropeez"
    g.turn_number = 5
    g.submitted_deck_cards = [900] * 4 + [901] * 3
    g.submitted_sideboard_cards = [902] * 2 + [903]
    g.starting_hand = ["Card900", "Card901"]
    g.library_departures = {"Card900": 1}
    g.library_returns = {}
    g.library_size_by_seat = {1: 4}
    g.opening_hand_capture_closed = True

    raw = tracker._overlay_state_json(in_game=True, format_label="Standard BO1", on_play=1)
    state = json.loads(raw)
    assert state["game_active"] is True and state["deck_name"] == "Skellies"
    assert state["opponent_name"] == "ropeez" and state["on_play"] is True
    assert state["deck_size"] == 7 and state["library_size"] == 4 and state["unaccounted"] == 0
    left = {card["name"]: card["left"] for card in state["cards"]}
    assert left == {"Card900": 2, "Card901": 2}
    assert [(c["name"], c["count"]) for c in state["sideboard"]] == [("Card902", 2), ("Card903", 1)]

    # The game ends: the final library stays, flagged game_over, so the
    # overlay keeps the cards through Arena's results screen...
    ended = json.loads(tracker._overlay_state_json(in_game=False, format_label=None, on_play=None))
    assert ended["game_active"] is False and ended["game_over"] is True
    assert {card["name"]: card["left"] for card in ended["cards"]} == {"Card900": 2, "Card901": 2}
    assert ended["deck_name"] == "Skellies"

    # ...until Arena changes scene (the results screen is gone), which
    # drops it and asks the heartbeat to write the idle row right away.
    tracker._parse_match_metadata(
        '[UnityCrossThreadLogger]Client.SceneChange {"fromSceneName":"None","toSceneName":"Home","initiator":"System"}'
    )
    assert tracker._live_status_dirty is True
    idle = json.loads(tracker._overlay_state_json(in_game=False, format_label=None, on_play=None))
    assert idle["game_active"] is False and idle["game_over"] is False and idle["cards"] == []


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def _store_with_live(tmp_path, overlay_state, *, in_game=1, updated_at=None):
    store = AnalyticsStore(tmp_path / "t.sqlite3")
    conn = store.connect()
    conn.execute(
        "INSERT OR IGNORE INTO tracker_sessions (id, started_at) VALUES ('S1', '2026-09-04T00:00:00')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO live_status (id, session_id, updated_at, in_game, game_id, opponent_name, overlay_json) "
        "VALUES (1, 'S1', ?, ?, 'G1', 'ropeez', ?)",
        ((updated_at or datetime.now()).isoformat(), in_game, json.dumps(overlay_state)),
    )
    conn.commit()
    store.close()
    return tmp_path / "t.sqlite3"


def test_overlay_payload_carries_state_and_head_to_head(tmp_path):
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('m1', 'S1')")
        conn.execute(
            "INSERT INTO games (id, session_id, match_id, started_at, outcome) VALUES ('h1', 'S1', 'm1', '2026-08-01T10:00:00', 'win')"
        )
        conn.execute(
            "INSERT INTO participants (id, game_id, role, display_name) VALUES ('h1-o', 'h1', 'opponent', 'ropeez')"
        )
    payload = live_api.build_overlay_payload(db_path)
    assert payload["tracker"]["state"] == "live"
    assert payload["state"]["deck_name"] == "Skellies"
    assert payload["head_to_head"] == {"wins": 1, "losses": 0}


def test_overlay_payload_drops_state_when_tracker_offline(tmp_path):
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state, updated_at=datetime(2026, 1, 1))
    payload = live_api.build_overlay_payload(db_path)
    assert payload["tracker"]["state"] == "offline"
    assert payload["state"] is None


def test_overlay_endpoint_etag_304_and_cors(tmp_path):
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state)

    class Handler(DashboardHandler):
        pass

    Handler.db_path = db_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/overlay")
        first = conn.getresponse()
        body = first.read()
        etag = first.getheader("ETag")
        assert first.status == 200 and etag
        assert first.getheader("Access-Control-Allow-Origin") == "*"
        assert first.getheader("Access-Control-Expose-Headers") == "ETag"
        assert json.loads(body)["state"]["deck_name"] == "Skellies"

        conn.request("GET", "/api/overlay", headers={"If-None-Match": etag})
        second = conn.getresponse()
        second.read()
        assert second.status == 304
        assert second.getheader("ETag") == etag

        conn.request("OPTIONS", "/api/overlay")
        preflight = conn.getresponse()
        preflight.read()
        assert preflight.status == 204
        assert "If-None-Match" in preflight.getheader("Access-Control-Allow-Headers")

        # Only the overlay endpoint is reachable cross-origin.
        conn.request("OPTIONS", "/api/snapshot")
        other = conn.getresponse()
        other.read()
        assert other.status == 404
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
