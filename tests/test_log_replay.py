import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_support import replay_lines
from test_tracker_combat_winner import make_tracker


def _game_state_line(payload):
    return json.dumps({"gameStateMessage": payload})


def test_replay_persists_opening_hand_without_keep_response(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"

    opening_hand_line = _game_state_line(
        {
            "gameStateId": 2,
            "turnInfo": {"activePlayer": 1, "decisionPlayer": 1},
            "players": [
                {"systemSeatNumber": 1, "pendingMessageType": "ClientMessageType_MulliganResp"},
                {"systemSeatNumber": 2, "pendingMessageType": "ClientMessageType_MulliganResp"},
            ],
            "zones": [
                {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [101, 102, 103, 104, 105, 106, 107]},
                {"type": "ZoneType_Hand", "ownerSeatId": 2, "objectInstanceIds": [201, 202, 203, 204, 205, 206, 207]},
            ],
            "gameObjects": [
                {"instanceId": 101, "grpId": 9001, "cardTypes": ["CardType_Land"]},
                {"instanceId": 102, "grpId": 9002, "cardTypes": ["CardType_Creature"]},
                {"instanceId": 103, "grpId": 9003, "cardTypes": ["CardType_Instant"]},
                {"instanceId": 104, "grpId": 9004, "cardTypes": ["CardType_Land"]},
                {"instanceId": 105, "grpId": 9005, "cardTypes": ["CardType_Sorcery"]},
                {"instanceId": 106, "grpId": 9006, "cardTypes": ["CardType_Land"]},
                {"instanceId": 107, "grpId": 9007, "cardTypes": ["CardType_Creature"]},
            ],
        }
    )
    first_gameplay_line = _game_state_line(
        {
            "gameStateId": 3,
            "turnInfo": {"turnNumber": 1, "activePlayer": 1},
            "zones": [
                {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [101, 102, 103, 104, 105, 106]},
            ],
            "gameObjects": [
                {"instanceId": 101, "grpId": 9001, "cardTypes": ["CardType_Land"]},
                {"instanceId": 102, "grpId": 9002, "cardTypes": ["CardType_Creature"]},
                {"instanceId": 103, "grpId": 9003, "cardTypes": ["CardType_Instant"]},
                {"instanceId": 104, "grpId": 9004, "cardTypes": ["CardType_Land"]},
                {"instanceId": 105, "grpId": 9005, "cardTypes": ["CardType_Sorcery"]},
                {"instanceId": 106, "grpId": 9006, "cardTypes": ["CardType_Land"]},
                {"instanceId": 999, "grpId": 9010, "cardTypes": ["CardType_Land"]},
            ],
            "annotations": [
                {
                    "type": ["AnnotationType_ZoneTransfer"],
                    "affectedIds": [999],
                    "details": [{"key": "category", "valueString": ["PlayLand"]}],
                }
            ],
        }
    )
    game_over_line = _game_state_line(
        {
            "gameInfo": {
                "stage": "GameStage_GameOver",
                "matchState": "MatchState_GameComplete",
                "results": [
                    {
                        "scope": "MatchScope_Game",
                        "result": "ResultType_WinLoss",
                        "winningTeamId": 1,
                        "reason": "ResultReason_OpponentConcede",
                    }
                ],
            }
        }
    )

    replay_lines(tracker, [opening_hand_line, first_gameplay_line, game_over_line])
    capsys.readouterr()

    with sqlite3.connect(tracker._console_db_path) as conn:
        participant = conn.execute(
            "select id, opening_hand_size, mulligans from participants where role = 'player'"
        ).fetchone()
        hand_rows = conn.execute(
            """
            select display_name, type_category, hand_position
            from game_opening_hand_cards
            order by hand_position
            """
        ).fetchall()
        game = conn.execute("select outcome from games").fetchone()

    assert participant[1:] == (7, 0)
    assert len(hand_rows) == 7
    assert hand_rows[0] == ("Card9001", "Land", 1)
    assert hand_rows[-1] == ("Card9007", "Creature", 7)
    assert game == ("win",)


def test_replay_uses_source_timestamps_for_elapsed_output(capsys):
    tracker = make_tracker()

    start_line = _game_state_line(
        {
            "gameStateId": 1,
            "turnInfo": {"turnNumber": 1, "activePlayer": 1},
            "zones": [
                {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [101]},
                {"type": "ZoneType_Hand", "ownerSeatId": 2, "objectInstanceIds": [201]},
            ],
            "gameObjects": [{"instanceId": 101, "grpId": 9001, "cardTypes": ["CardType_Land"]}],
        }
    )
    draw_line = _game_state_line(
        {
            "gameStateId": 2,
            "turnInfo": {"turnNumber": 1, "activePlayer": 1},
            "annotations": [
                {
                    "type": ["AnnotationType_ZoneTransfer"],
                    "affectedIds": [102],
                    "details": [
                        {"key": "zone_src", "valueInt32": [11]},
                        {"key": "zone_dest", "valueInt32": [12]},
                        {"key": "category", "valueString": ["Draw"]},
                    ],
                }
            ],
            "zones": [{"zoneId": 12, "type": "ZoneType_Hand", "ownerSeatId": 1}],
            "gameObjects": [
                {
                    "instanceId": 102,
                    "grpId": 9002,
                    "ownerSeatId": 1,
                    "cardTypes": ["CardType_Land"],
                }
            ],
        }
    )

    tracker._process_line(start_line, timestamp=datetime(2026, 5, 8, 22, 15, 0))
    tracker._process_line(draw_line, timestamp=datetime(2026, 5, 8, 22, 15, 7))

    out = capsys.readouterr().out
    assert "[0:07] You: drew a card" in out
