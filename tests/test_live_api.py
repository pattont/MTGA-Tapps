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


def _live(now=None, **overrides):
    payload = {
        "session_id": "S1",
        "updated_at": (now or datetime.now()).isoformat(),
        "in_game": 1,
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
    _log_line(store, "Turn 7 - Opponent", style="turn", turn=7, live=_live())
    _log_line(store, "Opponent: Casts Atraxa", style="cast", turn=7, lives=(18, 11), live=_live())
    store.close()

    payload = live_api.build_live_payload(tmp_path / "tracker.sqlite3")
    assert payload["tracker"]["state"] == "live"
    assert payload["now"]["opponent_name"] == "Villain#12345"
    assert payload["now"]["player_commanders"] == ["Wilhelt, the Rotcleaver"]
    assert payload["now"]["opponent_commanders"] == ["Atraxa, Praetors' Voice"]
    assert payload["session"]["wins"] == 2 and payload["session"]["win_rate"] == 66.7
    texts = [event["text"] for event in payload["events"]]
    assert texts == ["Turn 7 - Opponent", "Opponent: Casts Atraxa"]
    assert payload["events"][1]["style"] == "cast"
    assert payload["seq"] == payload["events"][-1]["id"]

    # Delta: nothing new after seq.
    delta = live_api.build_live_payload(tmp_path / "tracker.sqlite3", since=payload["seq"])
    assert delta["events"] == []
    assert delta["seq"] == payload["seq"]


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
    _log_line(store, "hello", live=_live(in_game=0))
    store.close()
    db = tmp_path / "tracker.sqlite3"

    assert live_api.handle_get("/api/other", {}, db) is None
    status, body = live_api.handle_get("/api/live", {"since": ["not-a-number"]}, db)
    assert status == 200
    assert [event["text"] for event in body["events"]] == ["hello"]


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
