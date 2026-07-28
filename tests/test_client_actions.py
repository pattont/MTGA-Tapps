import json
import sys
from pathlib import Path

from mtga_tracker.client_actions import parse_client_action

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tracker_combat_winner import make_tracker


def test_parse_mulligan_keep_from_object_payload():
    action = parse_client_action(
        {
            "clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage",
            "payload": {
                "type": "ClientMessageType_MulliganResp",
                "mulliganResp": {"decision": "MulliganOption_AcceptHand"},
            },
        }
    )

    assert action["type"] == "mulligan_resp"
    assert action["decision"] == "keep"


def test_parse_mulligan_from_stringified_payload():
    action = parse_client_action(
        {
            "clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage",
            "payload": json.dumps(
                {
                    "type": "ClientMessageType_MulliganResp",
                    "mulliganResp": {"decision": "MulliganOption_Mulligan"},
                }
            ),
        }
    )

    assert action["type"] == "mulligan_resp"
    assert action["decision"] == "mulligan"


def test_parse_select_n_response_selected_objects_and_options():
    action = parse_client_action(
        {
            "payload": {
                "type": "ClientMessageType_SelectNResp",
                "selectNResp": {
                    "selectedObjectIds": [101, "102"],
                    "selectedOptionIds": [7],
                },
            }
        }
    )

    assert action["selected_object_ids"] == [101, 102]
    assert action["selected_option_ids"] == [7]


def test_parse_submit_deck_response():
    action = parse_client_action(
        {
            "payload": {
                "type": "ClientMessageType_SubmitDeckResp",
                "submitDeckResp": {
                    "deck": {
                        "deckCards": [1, "2"],
                        "sideboardCards": [3],
                    }
                },
            }
        }
    )

    assert action["type"] == "submit_deck_resp"
    assert action["deck_cards"] == [1, 2]
    assert action["sideboard_cards"] == [3]


def test_parse_client_ui_message_claimed_as_noise():
    action = parse_client_action({"clientToMatchServiceMessageType": "ClientToGREUIMessage"})

    assert action["type"] == "client_ui_message"


def test_tracker_uses_normalized_select_ids_for_opening_hand_bottoming():
    tracker = make_tracker()
    tracker.game_state.opening_keep_confirmed = True
    tracker.game_state.opening_hand_capture_closed = False

    tracker._handle_client_gre_payload(
        {
            "data": {"type": "ClientMessageType_SelectNResp", "selectNResp": {}},
            "normalized": {"type": "select_n_resp", "selected_object_ids": [101, 102]},
        }
    )

    assert tracker.game_state.opening_select_n_ids == [101, 102]


def test_tracker_stores_submit_deck_response_for_sideboarding():
    tracker = make_tracker()

    tracker._handle_client_gre_payload(
        {
            "data": {"type": "ClientMessageType_SubmitDeckResp", "submitDeckResp": {}},
            "normalized": {
                "type": "submit_deck_resp",
                "deck_cards": [1, 2],
                "sideboard_cards": [3],
            },
        }
    )

    assert tracker.game_state.submitted_deck_cards == [1, 2]
    assert tracker.game_state.submitted_sideboard_cards == [3]


def test_tracker_captures_connect_response_deck_for_next_game():
    tracker = make_tracker()

    tracker._capture_submitted_deck_message(
        {
            "type": "GREMessageType_ConnectResp",
            "connectResp": {
                "deckMessage": {
                    "deckCards": [10, 10, 20],
                    "sideboardCards": [30],
                }
            },
        }
    )

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)

    assert tracker.game_state.submitted_deck_cards == [10, 10, 20]
    assert tracker.game_state.submitted_sideboard_cards == [30]
