"""A deck renamed in Arena keeps its id: the game played after the rename must
carry the new name, not the one the deck was saved under first."""

import json

from tests.test_tracker_combat_winner import make_tracker

DECK_ID = "3fc1f77e-4183-57b4-bed2-81be89ffcc34"
# Arena's own two spellings of a deck's LastUpdated, as logged on 2026-11-10:
# the create is UTC with a five-digit fraction, the rename local and JSON-quoted.
CREATED = "2026-11-10T23:58:30.66246Z"
RENAMED = '"2026-11-10T18:59:01.246381-05:00"'


def _summary(name, last_updated):
    return {
        "DeckId": DECK_ID,
        "Name": name,
        "Attributes": [
            {"name": "Format", "value": "Standard"},
            {"name": "LastUpdated", "value": last_updated},
        ],
    }


def _deck_request(kind, name, last_updated, **extra):
    request = {
        "Summary": _summary(name, last_updated),
        "Deck": {"MainDeck": [{"cardId": 100500, "quantity": 4}], "CommandZone": []},
        **extra,
    }
    return f"[UnityCrossThreadLogger]==> {kind} " + json.dumps(
        {"id": "abc", "request": json.dumps(request)}
    )


def _courses(name, last_updated):
    return json.dumps(
        {
            "Courses": [
                {
                    "InternalEventName": "Ladder",
                    "CurrentModule": "CreateMatch",
                    "CourseDeckSummary": _summary(name, last_updated),
                }
            ]
        }
    )


def test_game_after_a_rename_takes_the_new_name():
    tracker = make_tracker()
    # Deck Finder adds the deck under the video's title; it is renamed a
    # minute later, then queued.
    tracker._parse_match_metadata(_deck_request("DeckUpsertDeckV3", "Video Title (HGG)", CREATED))
    assert tracker.game_state.player_deck_name == "Video Title (HGG)"

    tracker._parse_match_metadata(_deck_request("DeckUpsertDeckV3", "Selesnya (HGG)", RENAMED))
    tracker._parse_match_metadata(
        _deck_request("EventSetDeckV3", "Selesnya (HGG)", RENAMED, EventName="Play")
    )

    assert tracker.game_state.player_deck_name == "Selesnya (HGG)"
    assert tracker.game_state.player_deck_id == DECK_ID


def test_an_older_summary_never_brings_the_old_name_back():
    tracker = make_tracker()
    tracker._parse_match_metadata(
        _deck_request("EventSetDeckV3", "Selesnya (HGG)", RENAMED, EventName="Play")
    )
    # Another event's course still shows the deck as it was submitted there.
    tracker._parse_match_metadata(_courses("Video Title (HGG)", CREATED))
    # A summary with no date says nothing about which name is newer.
    tracker._parse_match_metadata(_courses("Undated", "0001-01-01T00:00:00"))

    assert tracker._deck_candidates[DECK_ID]["deck_name"] == "Selesnya (HGG)"
    assert tracker.game_state.player_deck_name == "Selesnya (HGG)"


def test_a_real_name_still_replaces_a_localization_placeholder():
    tracker = make_tracker()
    tracker._parse_match_metadata(_courses("?=?Loc/Decks/Precon/CC_ANB_W", CREATED))
    tracker._parse_match_metadata(_courses("White Starter", CREATED))
    tracker._parse_match_metadata(_courses("?=?Loc/Decks/Precon/CC_ANB_W", RENAMED))

    assert tracker._deck_candidates[DECK_ID]["deck_name"] == "White Starter"
