import json
from datetime import datetime, timedelta

from mtga_tracker.analytics import AnalyticsStore, SessionSnapshot
from mtga_tracker import live_api


def _store(tmp_path):
    store = AnalyticsStore(tmp_path / "tracker.sqlite3")
    store.connect()
    return store


def _session(session_id="S1", games=3, wins=2, losses=1):
    return SessionSnapshot(
        session_id=session_id,
        started_at=datetime(2026, 8, 23, 10, 0, 0),
        games_played=games,
        wins=wins,
        losses=losses,
        draws=0,
        unknown_results=0,
        runtime_seconds=1200,
    )


def _log_line(store, text, style=None, turn=None, lives=(20, 20), live=None, at=None):
    store.record_console_log(
        _session(),
        created_at=at or datetime.now(),
        match_started_at=None,
        elapsed_seconds=None,
        turn_number=turn,
        active_player=None,
        style=style,
        text=text,
        player_life=lives[0],
        opponent_life=lives[1],
        live=live,
    )


def _game_event(store, game_id, text, event_type=None, turn=None, actor=None, lives=(20, 20)):
    conn = store.connect()
    with conn:
        conn.execute(
            """
            INSERT INTO game_events (
                session_id, match_id, game_id, event_time, elapsed_seconds,
                turn_number, phase, step, participant_id, seat_id, actor_role,
                event_type, text, player_life, opponent_life
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "S1",
                "M1",
                game_id,
                datetime.now().isoformat(),
                30,
                turn,
                None,
                None,
                None,
                None,
                actor,
                event_type,
                text,
                lives[0],
                lives[1],
            ),
        )


def _live(now=None, **overrides):
    payload = {
        "session_id": "S1",
        "updated_at": (now or datetime.now()).isoformat(),
        "in_game": 1,
        "game_id": "G1",
        "match_id": "M1",
        "format": "Standard Brawl",
        "match_type": "best_of_1",
        "game_number": 1,
        "player_name": "Travis",
        "opponent_name": "Villain#12345",
        "deck_name": "Skellies",
        "turn_number": 7,
        "active_role": "opponent",
        "on_play": 1,
        "player_life": 18,
        "opponent_life": 11,
        "mulligans": 1,
        "game_started_at": datetime.now().isoformat(),
        "player_commanders": json.dumps(["Wilhelt, the Rotcleaver"]),
        "opponent_commanders": json.dumps(["Atraxa, Praetors' Voice"]),
    }
    payload.update(overrides)
    return payload


def test_live_payload_snapshot_session_and_events(tmp_path):
    store = _store(tmp_path)
    _log_line(store, "any console line", live=_live())
    # The feed serves game_events — the same rows the /game Timeline shows.
    _game_event(store, "G1", "Opponent: Casts [Atraxa, Praetors' Voice]", "cast", turn=7, actor="opponent", lives=(18, 11))
    _game_event(store, "G2", "a different game's event", "cast", turn=2)
    store.close()

    payload = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert payload["tracker"]["state"] == "live"
    assert payload["now"]["opponent_name"] == "Villain#12345"
    assert payload["now"]["player_commanders"] == ["Wilhelt, the Rotcleaver"]
    assert payload["now"]["opponent_commanders"] == ["Atraxa, Praetors' Voice"]
    assert payload["session"]["wins"] == 2 and payload["session"]["win_rate"] == 66.7
    # Only the current game's (G1) events; timeline-shaped rows.
    assert [event["text"] for event in payload["events"]] == [
        "Opponent: Casts [Atraxa, Praetors' Voice]"
    ]
    event = payload["events"][0]
    assert event["event_type"] == "cast"
    assert event["actor_role"] == "opponent"
    assert event["turn_number"] == 7
    assert isinstance(event["text_segments"], list) and event["text_segments"]
    assert payload["seq"] == event["id"]

    # Delta: nothing new after seq — only the refresh tail (already-sent
    # rows re-served so in-place corrections propagate; client merges by id).
    delta = live_api.build_live_payload(tmp_path / "tracker.sqlite3", since=payload["seq"])
    assert [event["text"] for event in delta["events"]] == [
        "Opponent: Casts [Atraxa, Praetors' Voice]"
    ]
    assert delta["seq"] == payload["seq"]


def test_feed_tail_and_colors_survive_game_end(tmp_path):
    """Arena flushes the endgame log lines in the same burst that completes
    the match, and the tracker's final live_status write clears game_id —
    the feed must still serve those trailing events, and the previous-game
    scoreboard must pick up colors from the persisted summary."""
    store = _store(tmp_path)
    _log_line(store, "mid game", live=_live())
    _game_event(store, "G1", "You: Casts [Llanowar Elves]", "cast", turn=7, actor="player")
    mid = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert len(mid["events"]) == 1

    # Game over: endgame events land, then live_status loses its game_id.
    _game_event(store, "G1", "Opponent: lost 4 life (now 0)", "life_loss", turn=9, actor="opponent", lives=(13, 0))
    _log_line(
        store,
        "match complete",
        live=_live(in_game=0, game_id=None, match_id=None, player_life=None, opponent_life=None),
    )
    # The persisted game summary knows each side's colors.
    conn = store.connect()
    with conn:
        conn.execute(
            "INSERT INTO participants (id, game_id, role) VALUES ('P1', 'G1', 'player'), ('P2', 'G1', 'opponent')"
        )
        conn.execute(
            "INSERT INTO cards (name, color_identity, first_seen_at) VALUES ('Llanowar Elves', 'G', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO cards (name, color_identity, first_seen_at) VALUES ('Lightning Helix', 'WR', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO game_card_summary (game_id, participant_id, card_id, display_name, played_count) "
            "SELECT 'G1', 'P1', id, name, 1 FROM cards WHERE name = 'Llanowar Elves'"
        )
        conn.execute(
            "INSERT INTO game_card_summary (game_id, participant_id, card_id, display_name, played_count) "
            "SELECT 'G1', 'P2', id, name, 2 FROM cards WHERE name = 'Lightning Helix'"
        )
    store.close()

    after = live_api.build_live_payload(tmp_path / "tracker.sqlite3", since=mid["seq"])
    assert after["tracker"]["state"] == "idle"
    # The tail event still arrives, under the finished game's id.
    assert "Opponent: lost 4 life (now 0)" in [event["text"] for event in after["events"]]
    assert after["now"]["game_id"] == "G1"
    # Colors fall back to the persisted summary once live_status goes blank.
    assert after["now"]["player_colors"] == "G"
    assert after["now"]["opponent_colors"] == "WR"


def test_seat_colors_reports_colorless_deck(tmp_path):
    """An opponent whose every known card is colorless shows "C" (the
    colorless diamond), not blank — colorless is a real identity."""
    store = _store(tmp_path)
    _log_line(store, "any", live=_live())
    conn = store.connect()
    with conn:
        conn.execute(
            "INSERT INTO participants (id, game_id, role) VALUES ('P1', 'G1', 'player'), ('P2', 'G1', 'opponent')"
        )
        conn.execute(
            "INSERT INTO cards (name, color_identity, first_seen_at) VALUES "
            "('Mind Stone', '', '2026-01-01'), ('Forsaken Monument', '', '2026-01-01'), ('Llanowar Elves', 'G', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO game_card_summary (game_id, participant_id, card_id, display_name, played_count) "
            "SELECT 'G1', 'P2', id, name, 1 FROM cards WHERE color_identity = ''"
        )
        conn.execute(
            "INSERT INTO game_card_summary (game_id, participant_id, card_id, display_name, played_count) "
            "SELECT 'G1', 'P1', id, name, 1 FROM cards WHERE name = 'Llanowar Elves'"
        )
        # Clear live colors so the payload uses the summary fallback.
        conn.execute("UPDATE live_status SET player_colors = NULL, opponent_colors = NULL")
    store.close()

    payload = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert payload["now"]["player_colors"] == "G"
    assert payload["now"]["opponent_colors"] == "C"


def test_patched_event_text_reaches_delta_polls(tmp_path):
    """A target printed as "[ID: N]" (hidden object) gets patched in place
    once the object reveals — and the correction must reach a live page
    that already received the stale line (the delta re-serves a short tail
    the client merges by id)."""
    store = _store(tmp_path)
    _log_line(store, "any", live=_live())
    _game_event(store, "G1", "Opponent: cast [Flashback (Instant)] -> [ID: 301]", "cast", turn=9, actor="opponent")
    first = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert "[ID: 301]" in first["events"][0]["text"]

    store.patch_event_texts(
        session_id="S1", game_id="G1", needle="[ID: 301]", replacement="[Boros Charm]"
    )
    store.close()

    # The already-sent row comes back corrected on the next delta poll.
    delta = live_api.build_live_payload(tmp_path / "tracker.sqlite3", since=first["seq"])
    texts = [event["text"] for event in delta["events"]]
    assert "Opponent: cast [Flashback (Instant)] -> [Boros Charm]" in texts
    assert not any("[ID: 301]" in text for text in texts)


def test_unresolved_target_patches_on_reveal(tmp_path):
    """Tracker side: a snapshot carrying the hidden object's identity
    rewrites the recorded line and any pending stack label."""
    from mtga_tracker.state import GameState
    from mtga_tracker.tracker_state_lookup import TrackerStateLookupMixin

    store = _store(tmp_path)
    _log_line(store, "any", live=_live())
    _game_event(store, "G1", "Opponent: cast [Flashback (Instant)] -> [ID: 301]", "cast", turn=9, actor="opponent")

    class FakeCardDb:
        def get_card_name(self, grp_id):
            return "Boros Charm" if grp_id == 94149 else f"Card #{grp_id}"

    class Stub(TrackerStateLookupMixin):
        def __init__(self):
            self.game_state = GameState()
            self.game_state.in_match = True
            self.game_state.game_start_time = object()
            self.game_state.stack_items[448] = {"label": "[Flashback (Instant)] -> [ID: 301]"}
            self.card_db = FakeCardDb()
            self.session_id = "S1"

        def _lookup_object(self, instance_id, game_objects_by_id=None):
            return self.game_state.object_snapshots.get(instance_id) or {}

        def _refresh_fallback_name_text(self, name):
            return name

        def _current_game_id(self):
            return "G1"

        def _analytics_store(self):
            return store

    stub = Stub()
    assert stub._register_unresolved_target(301) == "ID: 301"
    # Snapshot arrives with the reveal; the placeholder resolves everywhere.
    stub._snapshot_game_objects(
        [{"instanceId": 301, "grpId": 94149, "cardTypes": ["CardType_Instant"]}]
    )
    assert stub.game_state.unresolved_target_ids == {}
    assert stub.game_state.stack_items[448]["label"] == "[Flashback (Instant)] -> [Boros Charm]"
    row = store.connect().execute("SELECT text FROM game_events WHERE game_id = 'G1'").fetchone()
    store.close()
    assert row[0] == "Opponent: cast [Flashback (Instant)] -> [Boros Charm]"


def test_live_color_index_survives_missing_arena_color_column():
    """The live pips must not go blank when Arena's schema hides its color
    column: mana costs and the analytics DB's own cards table fill in."""
    import sqlite3

    from mtga_tracker.state import CardEvent
    from mtga_tracker.tracker_analytics import TrackerAnalyticsMixin

    class FakeCardDb:
        def mana_cost_index_by_name(self):
            return {"Lightning Helix": ("{R}{W}", 2.0), "Mind Stone": ("{2}", 2.0)}

        def color_identity_index_by_name(self):
            return {}  # Arena schema without a usable color column

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE cards (name TEXT, color_identity TEXT)")
    conn.execute("INSERT INTO cards VALUES ('Llanowar Elves', 'G'), ('Mind Stone', '')")

    stub = TrackerAnalyticsMixin.__new__(TrackerAnalyticsMixin)
    stub.card_db = FakeCardDb()
    stub._analytics_connect = lambda: conn  # type: ignore[method-assign]

    colors = stub._live_colors_for(
        [CardEvent("Llanowar Elves", "you"), CardEvent("Lightning Helix", "you")]
    )
    assert colors == "WRG"
    # All known cards colorless -> "C" (a real color identity in MTG);
    # unknown names alone contribute nothing.
    assert stub._live_colors_for([CardEvent("Mind Stone", "you"), CardEvent("Mystery", "you")]) == "C"
    assert stub._live_colors_for([CardEvent("Mystery", "you")]) == ""
    # A colorless card next to colored ones never repaints the side.
    assert stub._live_colors_for([CardEvent("Mind Stone", "you"), CardEvent("Llanowar Elves", "you")]) == "G"


def test_offline_and_idle_states(tmp_path):
    store = _store(tmp_path)
    stale = datetime.now() - timedelta(minutes=5)
    _log_line(store, "old line", live=_live(now=stale, in_game=0))
    store.close()
    payload = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert payload["tracker"]["state"] == "offline"

    store = _store(tmp_path)
    store.touch_live_status("S1", datetime.now())
    store.close()
    payload = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert payload["tracker"]["state"] == "idle"


def test_handle_get_routes_and_parses_since(tmp_path):
    store = _store(tmp_path)
    _log_line(store, "hello", live=_live())
    _game_event(store, "G1", "You: Casts [Llanowar Elves]", "cast", turn=1, actor="player")
    store.close()
    db = tmp_path / "tracker.sqlite3"

    assert live_api.handle_get("/api/other", {}, db) is None
    status, body = live_api.handle_get("/api/live", {"since": ["not-a-number"]}, db)
    assert status == 200
    assert [event["text"] for event in body["events"]] == ["You: Casts [Llanowar Elves]"]


def test_settings_tracker_info_reads_live_status_paths(tmp_path):
    from pathlib import Path

    from mtga_tracker import settings_api

    store = _store(tmp_path)
    home = str(Path.home())
    _log_line(
        store,
        "startup",
        live=_live(
            in_game=0,
            log_path=f"{home}/Library/Logs/Wizards Of The Coast/MTGA/Player.log",
            card_db_path=f"{home}/MTGA/Raw_CardDatabase_abc.mtga",
            db_path=str(tmp_path / "tracker.sqlite3"),
            tracker_version="9.9.9",
        ),
    )
    store.close()

    status, body = settings_api.handle_get("/api/settings", tmp_path / "tracker.sqlite3")
    assert status == 200
    info = body["tracker"]
    assert info["monitoring"] == "~/Library/Logs/Wizards Of The Coast/MTGA/Player.log"
    assert info["card_db"] == "~/MTGA/Raw_CardDatabase_abc.mtga"
    assert info["version"] == "9.9.9"
    assert isinstance(info["deck_ai"], str) and info["deck_ai"]


def test_missing_live_status_table_is_offline(tmp_path):
    # A database that never saw the new tracker: build one and drop the table.
    store = _store(tmp_path)
    _log_line(store, "line")
    conn = store.connect()
    conn.execute("DROP TABLE live_status")
    conn.commit()
    store.close()
    payload = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert payload["tracker"]["state"] == "offline"
    assert payload["now"] is None
