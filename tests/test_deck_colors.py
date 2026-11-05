import json

import pytest

from mtga_tracker import deck_colors as dc
from mtga_tracker import deck_manager as dm
from mtga_tracker import deck_manager_api as api
from mtga_tracker import deck_native_api as native

BY_ID = {
    101: ("Land", "", "R"),
    102: (None, "{R}", "R"),
    103: (None, "{1}{W}{W}", "W"),
    104: ("Land", "", "WR"),
}
BY_NAME = {"Lightning Bolt": BY_ID[102], "Brave the Elements": BY_ID[103]}


@pytest.fixture(autouse=True)
def index(monkeypatch):
    monkeypatch.setattr(dc, "_INDEX", (BY_ID, BY_NAME))
    monkeypatch.setattr(dc, "_BUILT", float("inf"))


def card(name, quantity, section="Deck", arena_id=None):
    return {"name": name, "quantity": quantity, "section": section, "arena_id": arena_id}


def test_scores_lands_and_pips_like_the_overview():
    cards = [
        card("Mountain", 20),
        card("Lightning Bolt", 4),
        card("Sacred Foundry", 1, arena_id=104),
    ]
    # One stray dual land (score 2) does not add white.
    assert dc.deck_colors(cards) == "R"
    assert dc.deck_colors(cards + [card("Brave the Elements", 4)]) == "WR"


def test_sideboard_is_ignored_and_names_match_front_faces():
    cards = [
        card("Lightning Bolt // Other Side", 4),
        card("Brave the Elements", 4, section="Sideboard"),
    ]
    assert dc.deck_colors(cards) == "R"


def test_unknown_cards_give_no_colors():
    assert dc.deck_colors([card("Card #999", 4, arena_id=999)]) == ""


def test_saved_list_and_detail_include_colors(tmp_path):
    path = tmp_path / "library.db"
    with dm.library_connection(path) as conn:
        saved = dm.save_deck(conn, dm.parse_import("Deck\n20 Mountain\n4 Lightning Bolt"))
    status, body = api.handle_get("/api/deck-manager", {}, path)
    assert status == 200
    assert [d["colors"] for d in body["decks"]] == ["R"]
    status, detail = api.handle_get("/api/deck-manager/deck", {"id": [saved["id"]]}, path)
    assert status == 200 and detail["colors"] == "R"


def test_arena_roster_includes_colors_from_main_and_command_zone():
    report = {
        "pile_names": {"1": "Main", "2": "Sideboard", "3": "CommandZone"},
        "limit": 100,
        "limit_reached": False,
        "deck_screen_open": True,
        "roster_refreshed": True,
        "decks": [
            {
                "arena_id": "8d2e1e0e-0000-4000-8000-000000000001",
                "name": "Boros",
                "is_net_deck": False,
                "summary": {"Attributes": [{"key": "Format", "value": "Standard"}]},
                "piles": [
                    {"pile": 1, "entries": [{"id": 101, "quantity": 20}]},
                    {"pile": 2, "entries": [{"id": 102, "quantity": 4}]},
                    {"pile": 3, "entries": [{"id": 103, "quantity": 4}]},
                ],
            }
        ],
    }
    roster = native._public_roster(json.loads(json.dumps(report)))
    # The sideboard's Lightning Bolt is ignored; the command zone counts.
    assert roster["decks"][0]["colors"] == "WR"


def test_an_expired_index_is_served_while_it_rebuilds_in_the_background(monkeypatch):
    import threading
    import time

    fresh = ({999: (None, "{G}", "G")}, {})
    release = threading.Event()

    def slow_build():
        release.wait(5)
        return fresh

    monkeypatch.setattr(dc, "_build", slow_build)
    monkeypatch.setattr(dc, "_BUILT", 0.0)
    monkeypatch.setattr(dc, "_REFRESHING", False)

    # An Arena deck read never waits on the rebuild: it gets the current index.
    assert dc._index() == (BY_ID, BY_NAME)
    assert dc._index() == (BY_ID, BY_NAME)  # one rebuild at a time
    release.set()
    deadline = time.monotonic() + 5
    while dc._index() is not fresh and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dc._index() is fresh
