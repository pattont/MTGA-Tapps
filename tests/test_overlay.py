"""In-game overlay: library state math, the tracker's library bookkeeping,
and the /api/overlay endpoint the Tauri overlay polls."""

import json
import sqlite3
from datetime import datetime, timedelta
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


def test_build_overlay_state_counts_cards_that_left_unseen():
    """Half the library milled in a message Arena only summarized: the
    tracker saw nothing leave, the library is 10 cards short."""
    deck = ["Plains"] * 8 + ["Caves of Koilos"] * 4 + ["Skeleton Crew"] * 4 + ["Fell"] * 4
    state = build_overlay_state(
        deck=deck, departures={}, returns={}, library_size=10, card_info=_info, game_active=True
    )
    assert state["library_size"] == 10 and state["unseen"] == 10 and state["draw_pool"] == 20
    by_name = {card["name"]: card for card in state["cards"]}
    # Each count is a ceiling; the odds are over all 20 cards not seen to
    # leave, which the 10 left are a random half of: 4 in 20, not 4 in 10.
    assert by_name["Skeleton Crew"]["left"] == 4
    assert by_name["Skeleton Crew"]["odds"]["1"] == 20.0
    assert by_name["Skeleton Crew"]["odds"]["2"] == round(100 * odds_within(4, 20, 2), 1)
    assert state["lands_left"] == 12 and state["land_odds"]["1"] == 60.0

    # Never more draws than the library holds.
    last = build_overlay_state(
        deck=deck, departures={}, returns={}, library_size=1, card_info=_info, game_active=True
    )
    assert last["land_odds"]["3"] == last["land_odds"]["1"] == 60.0

    # Nothing unseen: the odds stay over the reported library.
    exact = build_overlay_state(
        deck=deck,
        departures={"Plains": 10},
        returns={},
        library_size=12,
        card_info=_info,
        game_active=True,
    )
    assert exact["unseen"] == 0 and exact["draw_pool"] == 12 and exact["log_gap"] is False

    # Before the hand is kept the library is short by the cards being dealt.
    dealing = build_overlay_state(
        deck=deck,
        departures={},
        returns={},
        library_size=13,
        card_info=_info,
        game_active=True,
        count_unseen=False,
    )
    assert dealing["unseen"] == 0 and dealing["draw_pool"] == 13 and dealing["unaccounted"] == -7


def _library_game(tracker, library_ids):
    g = tracker.game_state
    g.in_match = True
    g.game_start_time = datetime(2026, 11, 16, 23, 23)
    g.player_seat_id = 1
    g.opponent_seat_id = 2
    g.turn_number = 11
    g.opening_hand_capture_closed = True
    g.submitted_deck_cards = [900] * 4 + [901] * 4
    g.starting_hand = ["Card901"]
    tracker._observe_library_sizes(
        {
            "zones": [
                {"zoneId": 10, "type": "ZoneType_Library", "ownerSeatId": 1, "objectInstanceIds": library_ids},
                {"zoneId": 20, "type": "ZoneType_Library", "ownerSeatId": 2, "objectInstanceIds": [70, 71]},
            ]
        }
    )
    return g


def _overlay(tracker):
    return json.loads(tracker._overlay_state_json(in_game=True, format_label=None, on_play=None))


def test_a_library_search_resyncs_the_overlay_after_an_unseen_mill():
    """The opponent milled half the library in a message Arena logged only
    as a summary, so no card was seen to leave; the search later that turn
    showed the player every card left (a real game, 2026-11-16)."""
    tracker = make_tracker()
    g = _library_game(tracker, [462, 463, 464])
    # 8 cards, 1 in the kept hand, nothing seen to leave: 7 placed, 3 there.
    before = _overlay(tracker)
    assert before["library_size"] == 3 and before["unseen"] == 4
    assert {c["name"]: c["left"] for c in before["cards"]} == {"Card900": 4, "Card901": 3}

    def shown(instance_id, grp_id, zone_id=10):
        return {"instanceId": instance_id, "grpId": grp_id, "zoneId": zone_id, "ownerSeatId": 1}

    # A look at part of the library (scry, top two) is not the library.
    tracker._observe_library_reveal([shown(462, 900), shown(463, 901)])
    assert g.library_snapshot is None
    # Nor are the opponent's cards, or cards in another zone.
    tracker._observe_library_reveal([shown(70, 900, 20), shown(71, 900, 20)])
    assert g.library_snapshot is None

    tracker._live_status_dirty = False
    tracker._observe_library_reveal([shown(462, 900), shown(463, 901), shown(464, 901)])
    assert g.library_snapshot == {"Card900": 1, "Card901": 2}
    assert tracker._live_status_dirty is True
    after = _overlay(tracker)
    assert after["unseen"] == 0 and after["unaccounted"] == 0 and after["draw_pool"] == 3
    assert {c["name"]: c["left"] for c in after["cards"]} == {"Card900": 1, "Card901": 2}

    # The search takes one; moves after the snapshot count from it.
    tracker._observe_library_zone_transfer({"instanceId": 464, "grpId": 901}, {"id": 9}, _zones(), 10, 11)
    tracker._observe_library_sizes(
        {"zones": [{"zoneId": 10, "type": "ZoneType_Library", "ownerSeatId": 1, "objectInstanceIds": [561, 562]}]}
    )
    final = _overlay(tracker)
    assert final["library_size"] == 2 and final["unseen"] == 0
    assert {c["name"]: c["left"] for c in final["cards"]} == {"Card900": 1, "Card901": 1}


def test_a_summarized_message_flags_the_library_until_arena_lists_it_again():
    tracker = make_tracker()
    g = _library_game(tracker, list(range(47)))
    assert _overlay(tracker)["log_gap"] is False
    tracker._live_status_dirty = False
    tracker._process_line(
        "[UnityCrossThreadLogger]11/16/2026 11:26:07 PM: Match to X: GreToClientEvent\n"
        "[Message summarized because one or more GameStateMessages exceeded the 50 GameObject "
        "or 50 Annotation limit.]"
    )
    assert g.library_log_gap is True and tracker._live_status_dirty is True
    assert _overlay(tracker)["log_gap"] is True

    # The opponent's library alone says nothing about the player's.
    tracker._observe_library_sizes(
        {"zones": [{"zoneId": 20, "type": "ZoneType_Library", "ownerSeatId": 2, "objectInstanceIds": [70]}]}
    )
    assert g.library_log_gap is True
    # The next draw lists the library: the gap becomes a count of cards.
    tracker._observe_library_sizes(
        {"zones": [{"zoneId": 10, "type": "ZoneType_Library", "ownerSeatId": 1, "objectInstanceIds": list(range(21))}]}
    )
    state = _overlay(tracker)
    assert state["log_gap"] is False and state["library_size"] == 21

    # Outside a game a summary means nothing to the overlay.
    idle = make_tracker()
    idle._process_line("[Message summarized because one or more GameStateMessages exceeded the limit.]")
    assert idle.game_state.library_log_gap is False


def test_overlay_does_not_count_the_dealt_hand_as_unseen():
    tracker = make_tracker()
    g = _library_game(tracker, [1, 2, 3, 4, 5])
    g.starting_hand = []
    g.opening_hand_capture_closed = False
    g.turn_number = 0
    assert _overlay(tracker)["unseen"] == 0


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


def _today(clock="10:00:00"):
    return datetime.now().strftime(f"%Y-%m-%dT{clock}")


def _yesterday(clock="23:59:00"):
    return (datetime.now() - timedelta(days=1)).strftime(f"%Y-%m-%dT{clock}")


def test_overlay_payload_carries_todays_record_with_play_draw_split(tmp_path):
    state = idle_overlay_state(game_active=False)
    db_path = _store_with_live(tmp_path, state, in_game=0)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('m1', 'S1')")
        # (game, outcome, went_first): unknown turn order and draws stay out of the split.
        for game_id, outcome, went_first in [
            ("g1", "win", 1),
            ("g2", "loss", 1),
            ("g3", "win", 0),
            ("g4", "win", None),
            ("g5", "draw", 0),
        ]:
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, started_at, outcome) "
                "VALUES (?, 'S1', 'm1', ?, ?)",
                (game_id, _today(), outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, went_first) VALUES (?, ?, 'player', ?)",
                (f"{game_id}-p", game_id, went_first),
            )
        # Yesterday's game never counts, even one from the same tracker session.
        conn.execute(
            "INSERT INTO games (id, session_id, match_id, started_at, outcome) "
            "VALUES ('g0', 'S1', 'm1', ?, 'loss')",
            (_yesterday(),),
        )
        conn.execute(
            "INSERT INTO participants (id, game_id, role, went_first) VALUES ('g0-p', 'g0', 'player', 0)"
        )
    payload = live_api.build_overlay_payload(db_path)
    assert "session" not in payload
    assert payload["today"] == {
        "games": 5,
        "wins": 3,
        "losses": 1,
        "draws": 1,
        "win_rate": 75.0,
        "play": {"wins": 1, "losses": 1},
        "draw": {"wins": 1, "losses": 0},
        # No game on screen: no ladder to show and no deck to count.
        "rank": None,
        "deck": None,
    }


def _today_with_deck_games(db_path):
    """Today at 3-1: 2-1 with Skellies, 1-0 with another deck, and a
    Skellies loss yesterday; Platinum 2 on the constructed ladder."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('S0', '2026-09-03T00:00:00')"
        )
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('m1', 'S1')")
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('m0', 'S0')")
        for game_id, started, outcome, deck in [
            ("g1", _today("00:00:00"), "win", "Skellies"),
            ("g2", _today(), "loss", "Skellies"),
            ("g3", _today(), "win", "Skellies"),
            ("g4", _today(), "win", "Other Deck"),
            ("g0", _yesterday(), "loss", "Skellies"),
        ]:
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, started_at, outcome) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    game_id,
                    "S0" if game_id == "g0" else "S1",
                    "m0" if game_id == "g0" else "m1",
                    started,
                    outcome,
                ),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, deck_name) VALUES (?, ?, 'player', ?)",
                (f"{game_id}-p", game_id, deck),
            )
        conn.execute(
            "INSERT INTO rank_snapshots (session_id, captured_at, season_ordinal, rank_format, "
            "rank_class, rank_level, rank_step, rank_steps) "
            "VALUES ('S1', '2026-09-04T01:00:00', 1, 'constructed', 'Platinum', 2, 3, 6)"
        )


def test_overlay_today_carries_rank_and_the_decks_record_today(tmp_path):
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state)
    _today_with_deck_games(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET format = 'Standard (Ranked)', deck_name = 'Skellies' WHERE id = 1"
        )
    session = live_api.build_overlay_payload(db_path)["today"]
    assert session["wins"] == 3 and session["losses"] == 1
    # Today's games with this deck only.
    assert session["deck"] == {"wins": 2, "losses": 1}
    assert session["rank"]["rank_class"] == "Platinum"
    assert (session["rank"]["rank_level"], session["rank"]["rank_step"]) == (2, 3)

    # An unranked queue shows no rank, and still the deck's record.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE live_status SET format = 'Standard (Unranked)' WHERE id = 1")
    session = live_api.build_overlay_payload(db_path)["today"]
    assert session["rank"] is None
    assert session["deck"] == {"wins": 2, "losses": 1}

    # A deck with no result today has no record to show.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE live_status SET deck_name = 'Brand New' WHERE id = 1")
    assert live_api.build_overlay_payload(db_path)["today"]["deck"] is None


def test_overlay_today_reads_the_frozen_game_between_games(tmp_path):
    state = idle_overlay_state(game_active=False)
    db_path = _store_with_live(tmp_path, state, in_game=0)
    _today_with_deck_games(db_path)
    frozen = {"session_id": "S1", "format": "Standard (Ranked)", "deck_name": "Skellies"}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET format = NULL, deck_name = NULL, last_game_json = ? WHERE id = 1",
            (json.dumps(frozen),),
        )
    session = live_api.build_overlay_payload(db_path)["today"]
    assert session["deck"] == {"wins": 2, "losses": 1}
    assert session["rank"]["rank_class"] == "Platinum"

    # Another tracker session's frozen game is not on screen (a restart
    # must not bring it back).
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET last_game_json = ? WHERE id = 1",
            (json.dumps({**frozen, "session_id": "S0"}),),
        )
    session = live_api.build_overlay_payload(db_path)["today"]
    assert session["rank"] is None and session["deck"] is None


def test_overlay_etag_follows_a_rank_change(tmp_path):
    """Arena reports the new rank after the game's result: the footer's chip
    must not wait for the next game to show it."""
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state)
    _today_with_deck_games(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET format = 'Standard (Ranked)', deck_name = 'Skellies' WHERE id = 1"
        )
    live_api.reset_poll_connections()
    payload_1, etag_1 = live_api.overlay_response(db_path)
    assert json.loads(payload_1)["today"]["rank"]["rank_step"] == 3
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO rank_snapshots (session_id, captured_at, season_ordinal, rank_format, "
            "rank_class, rank_level, rank_step, rank_steps) "
            "VALUES ('S1', '2026-09-04T02:00:00', 1, 'constructed', 'Platinum', 2, 4, 6)"
        )
    payload_2, etag_2 = live_api.overlay_response(db_path)
    assert etag_2 != etag_1
    assert json.loads(payload_2)["today"]["rank"]["rank_step"] == 4


def test_overlay_payload_carries_the_flood_meter(tmp_path):
    """The flood meter reads the tracker's own draw_quality (the Stream Kit
    Lands widget's numbers): the live row's during a game, the frozen game's
    between games, and a change to it changes the ETag."""
    quality = {
        "lands_seen": 3,
        "total_cards_seen": 9,
        "expected_lands_seen": 3.6,
        "is_flood": False,
    }
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET session_id = 'S1', draw_quality = ? WHERE id = 1",
            (json.dumps(quality),),
        )
    assert live_api.build_overlay_payload(db_path)["draw_quality"] == quality

    live_api.reset_poll_connections()
    _, etag_1 = live_api.overlay_response(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET draw_quality = ? WHERE id = 1",
            (json.dumps({**quality, "lands_seen": 4, "total_cards_seen": 10}),),
        )
    payload, etag_2 = live_api.overlay_response(db_path)
    assert etag_2 != etag_1
    assert json.loads(payload)["draw_quality"]["lands_seen"] == 4

    # Between games: the frozen game's numbers, not the idle row's.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE live_status SET in_game = 0, draw_quality = NULL, last_game_json = ? WHERE id = 1",
            (json.dumps({"session_id": "S1", "draw_quality": json.dumps(quality)}),),
        )
    assert live_api.build_overlay_payload(db_path)["draw_quality"] == quality


def test_overlay_payload_drops_state_when_tracker_offline(tmp_path):
    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state, updated_at=datetime(2026, 1, 1))
    payload = live_api.build_overlay_payload(db_path)
    assert payload["tracker"]["state"] == "offline"
    assert payload["state"] is None
    assert payload["today"] is None
    assert payload["draw_quality"] is None


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


def test_overlay_response_memo_follows_the_live_row(tmp_path):
    """The encoded answer is reused while the live row is unchanged and
    rebuilt the moment it moves (a new console line, a new state)."""
    from mtga_tracker import live_api

    state = idle_overlay_state(game_active=True, deck_name="Skellies")
    db_path = _store_with_live(tmp_path, state)
    first, etag_first = live_api.overlay_response(db_path)
    again, etag_again = live_api.overlay_response(db_path)
    assert again is first and etag_again == etag_first

    changed = dict(state, deck_name="Rats")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE live_status SET overlay_json = ?, updated_at = ? WHERE id = 1",
        (json.dumps(changed), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    third, etag_third = live_api.overlay_response(db_path)
    assert etag_third != etag_first
    assert json.loads(third)["state"]["deck_name"] == "Rats"


def test_untracked_match_still_feeds_the_overlay_through_the_live_row(tmp_path):
    """A practice game against Sparky is not history, but the overlay and the
    Live Scoreboard read the live row, and that row carries the overlay's
    library state — so it keeps being written while nothing else is."""
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 9, 10, 20, 0, 0)
    tracker.game_state.game_start_time = datetime(2026, 9, 10, 20, 5, 0)
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Sparky"
    tracker.game_state.player_deck_name = "Starter Deck"
    tracker.game_state.format_str = "AIBotMatch"
    assert tracker._is_untracked_match()

    tracker._print_event("[0:10] You: played [Plains]", "land")

    conn = sqlite3.connect(tracker._console_db_path)
    live = conn.execute("SELECT in_game, opponent_name, deck_name, overlay_json FROM live_status WHERE id = 1").fetchone()
    assert live is not None
    assert live[0] == 1 and live[1] == "Sparky" and live[2] == "Starter Deck"
    assert live[3] and json.loads(live[3])["game_active"] is True
    # ...and nothing became history.
    assert conn.execute("SELECT COUNT(*) FROM console_logs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0] == 0
    conn.close()


def test_overlay_etag_survives_the_heartbeat_and_follows_todays_record(tmp_path):
    """A heartbeat (updated_at only) must not change the overlay's ETag — every
    poller would download and redraw an unchanged panel every 5 s — while a
    finished game (today's totals) must."""
    state = idle_overlay_state(game_active=False)
    db_path = _store_with_live(tmp_path, state, in_game=0)
    live_api.reset_poll_connections()

    payload_1, etag_1 = live_api.overlay_response(db_path)
    store = AnalyticsStore(db_path)
    store.touch_live_status("S1", datetime.now())
    store.close()
    payload_2, etag_2 = live_api.overlay_response(db_path)
    assert etag_2 == etag_1 and payload_2 == payload_1

    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('m1', 'S1')")
        conn.execute(
            "INSERT INTO games (id, session_id, match_id, started_at, outcome) "
            "VALUES ('g1', 'S1', 'm1', ?, 'win')",
            (_today(),),
        )
    payload_3, etag_3 = live_api.overlay_response(db_path)
    assert etag_3 != etag_1
    assert json.loads(payload_3)["today"]["wins"] == 1

    # A live row that stops being refreshed goes offline on time, memo or not.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE live_status SET updated_at = '2020-01-01T00:00:00' WHERE id = 1")
    payload_4, etag_4 = live_api.overlay_response(db_path)
    assert etag_4 != etag_3
    assert json.loads(payload_4)["tracker"]["state"] == "offline"
    live_api.reset_poll_connections()


# --------------------------------------------------------------------------
# The opponent panel's block
# --------------------------------------------------------------------------


def _seen(*cards):
    return json.dumps(
        [
            {"name": name, "type": kind, "mana_cost": cost, "mana_value": value, "count": count}
            for name, kind, cost, value, count in cards
        ]
    )


def _set_live(db_path, **fields):
    columns = ", ".join(f"{name} = ?" for name in fields)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"UPDATE live_status SET {columns} WHERE id = 1", tuple(fields.values()))


def _labelled_history(db_path):
    """Three earlier games against Deck AI-labelled opponents, with the cards
    each opponent played."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO matches (id, session_id) VALUES ('m1', 'S1')")
        for game_id, archetype, outcome, cards in (
            ("a1", "Rakdos Midrange", "loss", ["Bloodtithe Harvester", "Fable of the Mirror-Breaker"]),
            ("a2", "Rakdos Midrange", "win", ["Bloodtithe Harvester", "Fable of the Mirror-Breaker"]),
            ("a3", "Mono-Red Aggro", "win", ["Monastery Swiftspear", "Fable of the Mirror-Breaker"]),
        ):
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, started_at, outcome) VALUES (?, 'S1', 'm1', '2026-08-01T10:00:00', ?)",
                (game_id, outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name, deck_archetype) VALUES (?, ?, 'opponent', 'foe', ?)",
                (f"{game_id}-o", game_id, archetype),
            )
            for name in cards:
                conn.execute(
                    "INSERT INTO game_card_summary (game_id, participant_id, display_name, played_count) VALUES (?, ?, ?, 1)",
                    (game_id, f"{game_id}-o", name),
                )


def test_overlay_opponent_block_names_the_deck_from_history(tmp_path):
    db_path = _store_with_live(tmp_path, idle_overlay_state(game_active=True))
    _labelled_history(db_path)
    _set_live(
        db_path,
        opponent_colors="BR",
        opponent_lands=3,
        opponent_cards=json.dumps(["Bloodtithe Harvester", "Fable of the Mirror-Breaker", "Swamp"]),
        opponent_seen=_seen(
            ("Bloodtithe Harvester", "Creature", "{B}{R}", 2, 1),
            ("Fable of the Mirror-Breaker", "Enchantment", "{2}{R}", 3, 1),
            ("Swamp", "Land", None, 0, 2),
        ),
    )
    live_api.reset_poll_connections()
    opponent = live_api.build_overlay_payload(db_path)["opponent"]
    assert opponent["colors"] == "BR"
    assert opponent["lands"] == 3
    assert opponent["deck"] == {"label": "Rakdos Midrange", "source": "history", "matched_cards": 2}
    assert opponent["record"] == {"wins": 1, "losses": 1}
    assert [card["name"] for card in opponent["seen"]] == [
        "Bloodtithe Harvester",
        "Fable of the Mirror-Breaker",
        "Swamp",
    ]


def test_overlay_opponent_block_falls_back_to_colors_then_nothing(tmp_path):
    db_path = _store_with_live(tmp_path, idle_overlay_state(game_active=True))
    _set_live(db_path, opponent_colors="WU", opponent_seen=_seen(("Opt", "Instant", "{U}", 1, 1)))
    opponent = live_api.build_overlay_payload(db_path)["opponent"]
    assert opponent["deck"] == {"label": "Azorius", "source": "colors", "matched_cards": None}
    assert opponent["record"] is None

    _set_live(db_path, opponent_colors=None, opponent_seen=None)
    opponent = live_api.build_overlay_payload(db_path)["opponent"]
    assert opponent["deck"] == {"label": None, "source": "none", "matched_cards": None}
    assert opponent["seen"] == [] and opponent["lands"] == 0


def test_overlay_opponent_block_names_the_commander_in_brawl(tmp_path):
    db_path = _store_with_live(tmp_path, idle_overlay_state(game_active=True))
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('m1', 'S1')")
        conn.execute(
            "INSERT INTO games (id, session_id, match_id, started_at, outcome) VALUES ('b1', 'S1', 'm1', '2026-08-01T10:00:00', 'win')"
        )
        conn.execute(
            "INSERT INTO participants (id, game_id, role, display_name) VALUES ('b1-o', 'b1', 'opponent', 'foe')"
        )
        conn.execute(
            "INSERT INTO participant_commanders (participant_id, card_name) VALUES ('b1-o', 'Kenrith, the Returned King')"
        )
    _set_live(
        db_path,
        opponent_colors="WUBRG",
        opponent_commanders=json.dumps(["Kenrith, the Returned King"]),
    )
    opponent = live_api.build_overlay_payload(db_path)["opponent"]
    assert opponent["deck"]["label"] == "Kenrith, the Returned King"
    assert opponent["deck"]["source"] == "commander"
    assert opponent["record"] == {"wins": 1, "losses": 0}


def test_overlay_opponent_block_only_while_a_game_is_on_screen(tmp_path):
    # Between games (no game on screen): nothing, so the window hides.
    db_path = _store_with_live(tmp_path, idle_overlay_state(game_active=False), in_game=0)
    assert live_api.build_overlay_payload(db_path)["opponent"] is None

    # The results screen: the frozen game's cards stay up.
    frozen = {
        "session_id": "S1",
        "game_id": "G1",
        "opponent_colors": "G",
        "opponent_seen": _seen(("Llanowar Elves", "Creature", "{G}", 1, 2)),
    }
    _set_live(
        db_path,
        overlay_json=json.dumps({**idle_overlay_state(game_active=False), "game_over": True}),
        last_game_json=json.dumps(frozen),
    )
    opponent = live_api.build_overlay_payload(db_path)["opponent"]
    assert opponent["colors"] == "G"
    assert opponent["seen"][0]["count"] == 2

    # A stale row (tracker gone) shows nothing.
    _set_live(db_path, updated_at="2020-01-01T00:00:00")
    assert live_api.build_overlay_payload(db_path)["opponent"] is None


def test_overlay_etag_follows_the_opponents_cards(tmp_path):
    db_path = _store_with_live(tmp_path, idle_overlay_state(game_active=True))
    live_api.reset_poll_connections()
    _set_live(db_path, opponent_seen=_seen(("Opt", "Instant", "{U}", 1, 1)))
    _payload_1, etag_1 = live_api.overlay_response(db_path)
    _set_live(
        db_path,
        opponent_seen=_seen(("Opt", "Instant", "{U}", 1, 1), ("Consider", "Instant", "{U}", 1, 1)),
    )
    payload_2, etag_2 = live_api.overlay_response(db_path)
    assert etag_2 != etag_1
    assert len(json.loads(payload_2)["opponent"]["seen"]) == 2
    live_api.reset_poll_connections()


def test_cached_archetype_guess_matches_the_uncached_one(tmp_path):
    """The overlay's guess reads a kept index of the history; it must give
    /api/live's answer, and a labelled current game never counts for itself."""
    db_path = _store_with_live(tmp_path, idle_overlay_state(game_active=True))
    _labelled_history(db_path)
    live_api.reset_poll_connections()
    cards = json.dumps(["Bloodtithe Harvester", "Fable of the Mirror-Breaker"])
    with sqlite3.connect(db_path) as conn:
        for current in (None, "a1", "a3"):
            plain = live_api._archetype_guess(conn, cards, current, "BR")
            kept = live_api._archetype_guess(conn, cards, current, "BR", cache_scope="scope")
            assert kept == plain, current
        # a1 (a Rakdos loss) is the game on screen: its own cards and result are out.
        assert live_api._archetype_guess(conn, cards, "a1", "BR", cache_scope="scope") == {
            "archetype": "Rakdos Midrange",
            "matched_cards": 2,
            "wins": 1,
            "losses": 0,
        }
    live_api.reset_poll_connections()
