"""Regression tests for winner parsing and combat events in tracker."""

import json
import re
import sqlite3
from datetime import datetime

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.tracker import CardEvent, CardTracker, GameState


class DummyParser:
    """Minimal parser stub for tracker unit tests."""

    log_path = "/tmp/Player.log"

    @staticmethod
    def parse_json_from_line(line: str):
        match = re.search(r"\{.*\}", line)
        if not match:
            return None
        return json.loads(match.group(0))

    @staticmethod
    def extract_game_state_events(line: str):
        data = DummyParser.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []
        if "gameStateMessage" in data and isinstance(data["gameStateMessage"], dict):
            return [{"type": "game_state", "data": data["gameStateMessage"]}]
        if "greToClientEvent" in data and isinstance(data["greToClientEvent"], dict):
            out = []
            for message in data["greToClientEvent"].get("greToClientMessages", []) or []:
                if not isinstance(message, dict):
                    continue
                if message.get("type") != "GREMessageType_GameStateMessage":
                    continue
                game_state = message.get("gameStateMessage")
                if isinstance(game_state, dict):
                    out.append({"type": "game_state", "data": game_state})
            return out
        return []

    @staticmethod
    def extract_client_gre_payloads(line: str):
        data = DummyParser.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []
        direct = data.get("clientToGreMessage")
        if isinstance(direct, dict):
            payload = direct.get("payload")
            if isinstance(payload, dict):
                return [{"type": "client_gre_message", "data": payload}]
            if direct.get("type"):
                return [{"type": "client_gre_message", "data": direct}]
        if data.get(
            "clientToMatchServiceMessageType"
        ) == "ClientToMatchServiceMessageType_ClientToGREMessage" and isinstance(
            data.get("payload"), dict
        ):
            return [{"type": "client_gre_message", "data": data["payload"]}]
        return []

    @staticmethod
    def extract_card_events(line: str):
        events = DummyParser.extract_game_state_events(line)
        return events[0] if events else None


class DummyCardDB:
    """Simple card DB stub that returns deterministic names."""

    def __init__(self):
        self.cache = {}
        self.log_cache = {}
        self.names = {}
        self.ability_texts = {}

    def _save_cache(self):
        return None

    def get_card_name(self, grp_id: int) -> str:
        return self.names.get(grp_id, f"Card{grp_id}")

    def get_card_ability_text(self, grp_id: int, ability_grp_id: int):
        return self.ability_texts.get((grp_id, ability_grp_id))

    def get_ability_text(self, ability_grp_id: int):
        return self.ability_texts.get(ability_grp_id)


def make_tracker() -> CardTracker:
    """Create tracker instance without heavy constructor dependencies."""
    tracker = CardTracker.__new__(CardTracker)
    tracker.parser = DummyParser()
    tracker.card_db = DummyCardDB()
    tracker.game_state = GameState()
    tracker.player_cards = []
    tracker.opponent_cards = []
    tracker.running = False
    tracker.match_games = []
    tracker.waiting_for_next_game = False
    tracker._pending_game_summary = False
    tracker.session_start_time = datetime.now()
    tracker.session_games_played = 0
    tracker.session_wins = 0
    tracker.session_losses = 0
    tracker.session_draws = 0
    tracker.session_unknown = 0
    tracker.session_player_cards_played = 0
    tracker.session_opponent_cards_played = 0
    tracker.session_total_mulligans = 0
    tracker.session_game_runtime_seconds = 0
    tracker.session_player_went_first = 0
    tracker.session_opponent_went_first = 0
    tracker.session_first_unknown = 0
    tracker.session_id = "test-session"
    tracker._session_stats_recorded_this_game = False
    tracker._deck_candidates = {}
    tracker._active_deck_candidate_key = None
    tracker._metadata_backfilled = False
    tracker._format_from_backfill = False
    tracker._parsing_backfilled_metadata = False
    tracker._require_explicit_game_start = False
    tracker.use_colors = False
    tracker._ansi_styles = {}
    tracker._ansi_reset = ""
    tracker._console_db_path = None
    tracker._diagnostic_text_path = None
    return tracker


def test_check_game_end_parses_structured_result_winner():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "results": [
                                    {
                                        "scope": "MatchScope_Game",
                                        "result": "ResultType_WinLoss",
                                        "winningTeamId": 2,
                                        "reason": "ResultReason_Concede",
                                    }
                                ],
                            }
                        },
                    }
                ]
            }
        }
    )

    tracker._check_game_end(line)

    assert tracker.game_state.winner_seat == 2
    assert tracker.game_state.match_complete is True
    assert tracker._pending_game_summary is True


def test_winner_parsing_uses_latest_game_scope_result_in_bo3():
    tracker = make_tracker()

    winner = tracker._try_parse_winner_from_json(
        {
            "gameInfo": {
                "results": [
                    {
                        "scope": "MatchScope_Game",
                        "result": "ResultType_WinLoss",
                        "winningTeamId": 1,
                    },
                    {
                        "scope": "MatchScope_Game",
                        "result": "ResultType_WinLoss",
                        "winningTeamId": 2,
                    },
                    {
                        "scope": "MatchScope_Game",
                        "result": "ResultType_WinLoss",
                        "winningTeamId": 1,
                    },
                    {
                        "scope": "MatchScope_Match",
                        "result": "ResultType_WinLoss",
                        "winningTeamId": 1,
                    },
                ]
            }
        }
    )

    assert winner == 1


def test_winner_parsing_game_scope_beats_stale_nested_winner_key():
    tracker = make_tracker()

    winner = tracker._try_parse_winner_from_json(
        {
            "winningTeamId": 1,
            "gameInfo": {
                "results": [
                    {"scope": "MatchScope_Game", "result": "ResultType_WinLoss", "winningTeamId": 2}
                ]
            },
        }
    )

    assert winner == 2


def test_winner_parsing_match_scope_is_only_fallback():
    tracker = make_tracker()

    winner = tracker._try_parse_winner_from_json(
        {
            "finalMatchResult": {
                "resultList": [
                    {
                        "scope": "MatchScope_Match",
                        "result": "ResultType_WinLoss",
                        "winningTeamId": 2,
                    }
                ]
            }
        }
    )

    assert winner == 2


def test_check_game_end_handles_forced_draw_result():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.game_start_time = datetime(2026, 5, 9, 23, 7, 40)

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "matchState": "MatchState_MatchComplete",
                                "results": [
                                    {
                                        "scope": "MatchScope_Match",
                                        "result": "ResultType_Draw",
                                        "reason": "ResultReason_Force",
                                    }
                                ],
                            }
                        },
                    },
                    {
                        "type": "GREMessageType_IntermissionReq",
                        "intermissionReq": {
                            "result": {
                                "scope": "MatchScope_Match",
                                "result": "ResultType_Draw",
                                "reason": "ResultReason_Force",
                            }
                        },
                    },
                ]
            }
        }
    )

    tracker._check_game_end(line)

    assert tracker.game_state.match_complete is True
    assert tracker.game_state.winner_seat is None
    assert tracker.game_state.result_type == "ResultType_Draw"
    assert tracker._resolve_game_outcome() == ("draw", "Match ended in a forced draw")


def test_final_match_result_draw_marks_match_complete():
    tracker = make_tracker()
    tracker.game_state.in_match = True

    line = json.dumps(
        {
            "matchGameRoomStateChangedEvent": {
                "gameRoomInfo": {
                    "stateType": "MatchGameRoomStateType_MatchCompleted",
                    "finalMatchResult": {
                        "resultList": [
                            {
                                "scope": "MatchScope_Match",
                                "result": "ResultType_Draw",
                                "reason": "ResultReason_Force",
                            }
                        ]
                    },
                }
            }
        }
    )

    tracker._check_game_end(line)

    assert tracker.game_state.match_complete is True
    assert tracker._resolve_game_outcome()[0] == "draw"


def test_record_session_outcome_counts_draws_separately():
    tracker = make_tracker()

    tracker._record_session_outcome("draw")

    assert tracker.session_games_played == 1
    assert tracker.session_draws == 1
    assert tracker.session_unknown == 0
    assert "D:1" in tracker._session_stats_line()


def test_process_line_records_explicit_mulligan_response():
    tracker = make_tracker()

    tracker._process_line(
        json.dumps(
            {
                "clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage",
                "payload": {
                    "type": "ClientMessageType_MulliganResp",
                    "mulliganResp": {"decision": "MulliganOption_Mulligan"},
                },
            }
        )
    )

    assert tracker.game_state.explicit_mulligan_count == 1
    assert tracker.game_state.opening_mulligan_prompt_seen is True


def test_capture_opening_hand_uses_explicit_mulligan_response_count():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.explicit_mulligan_count = 1
    tracker.game_state.opening_mulligan_prompt_seen = True

    data = {
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [11, 12, 13, 14, 15, 16],
            }
        ],
        "gameObjects": [
            {"instanceId": 11, "grpId": 101},
            {"instanceId": 12, "grpId": 102},
            {"instanceId": 13, "grpId": 103},
            {"instanceId": 14, "grpId": 104},
            {"instanceId": 15, "grpId": 105},
            {"instanceId": 16, "grpId": 106},
        ],
        "turnInfo": {"turnNumber": 1},
    }

    tracker._capture_opening_hand(data)

    assert tracker.game_state.mulligan_count == 1
    assert len(tracker.game_state.starting_hand) == 6


def test_process_line_records_opening_selectn_response():
    tracker = make_tracker()
    tracker.game_state.opening_keep_confirmed = True

    tracker._process_line(
        json.dumps(
            {
                "clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage",
                "payload": {
                    "type": "ClientMessageType_SelectNResp",
                    "selectNResp": {"ids": [444, 445]},
                },
            }
        )
    )

    assert tracker.game_state.opening_select_n_ids == [444, 445]


def test_check_game_end_infers_winner_from_pending_loss_status():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    line = json.dumps(
        {
            "gameStateMessage": {
                "gameInfo": {
                    "stage": "GameStage_GameOver",
                    "matchState": "MatchState_GameComplete",
                },
                "players": [
                    {"systemSeatNumber": 1, "status": "PlayerStatus_InGame"},
                    {"systemSeatNumber": 2, "status": "PlayerStatus_PendingLoss"},
                ],
            }
        }
    )

    tracker._check_game_end(line)

    assert tracker.game_state.winner_seat == 1
    assert tracker.game_state.match_complete is True


def test_check_game_end_ignores_match_complete_without_game_complete():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_MatchComplete",
                                "results": [
                                    {
                                        "scope": "MatchScope_Match",
                                        "result": "ResultType_WinLoss",
                                        "winningTeamId": 2,
                                        "reason": "ResultReason_Concede",
                                    }
                                ],
                            }
                        },
                    }
                ]
            }
        }
    )

    tracker._check_game_end(line)

    assert tracker.game_state.winner_seat == 2
    assert tracker.game_state.match_complete is False
    assert tracker._pending_game_summary is False


def test_check_game_start_ignores_game_over_payload_with_mulligan_type(capsys):
    tracker = make_tracker()

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "mulliganType": "MulliganType_London",
                            }
                        },
                    }
                ]
            }
        }
    )

    tracker._check_game_start(line)

    assert tracker.game_state.in_match is False
    assert capsys.readouterr().out == ""


def test_check_game_start_waiting_for_next_game_ignores_game_over_mulligan_payload(capsys):
    tracker = make_tracker()
    tracker.waiting_for_next_game = True

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_MatchComplete",
                                "mulliganType": "MulliganType_London",
                            }
                        },
                    }
                ]
            }
        }
    )

    tracker._check_game_start(line)

    assert tracker.waiting_for_next_game is True
    assert tracker.game_state.in_match is False
    assert capsys.readouterr().out == ""


def test_attack_state_events_are_announced_once(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    data = {
        "gameObjects": [
            {
                "instanceId": 9001,
                "grpId": 101,
                "ownerSeatId": 2,
                "power": {"value": 2},
                "toughness": {"value": 2},
                "attackState": "AttackState_Attacking",
                "attackInfo": {"targetId": 1},
            }
        ]
    }

    tracker._process_game_events(data)
    first_output = capsys.readouterr().out
    assert "attacking [you] with [Card101 (2/2)]" in first_output

    tracker._process_game_events(data)
    second_output = capsys.readouterr().out
    assert second_output == ""


def test_attack_state_dedupe_survives_combat_cache_reset(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 3
    tracker.game_state.active_player = 2
    tracker.game_state.last_opponent_turn_number = 3

    data = {
        "gameObjects": [
            {
                "instanceId": 9001,
                "grpId": 101,
                "ownerSeatId": 2,
                "power": {"value": 2},
                "toughness": {"value": 2},
                "attackState": "AttackState_Attacking",
                "attackInfo": {"targetId": 1},
            }
        ]
    }

    tracker._process_game_events(data)
    first = capsys.readouterr().out
    assert "attacking [you] with [Card101 (2/2)]" in first

    # Simulate transient combat cache reset from later out-of-order phase packets.
    tracker.game_state.attackers = []
    tracker.game_state.current_combat_attackers = {}

    tracker._process_game_events(data)
    second = capsys.readouterr().out
    assert second == ""


def test_declare_blockers_req_only_updates_snapshots_no_block_output(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 5

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameObjects": [
                                {
                                    "instanceId": 30,
                                    "grpId": 303,
                                    "ownerSeatId": 1,
                                    "power": {"value": 1},
                                    "toughness": {"value": 3},
                                },
                                {"instanceId": 40, "grpId": 404, "ownerSeatId": 2},
                            ]
                        },
                    },
                    {
                        "type": "GREMessageType_DeclareBlockersReq",
                        "declareBlockersReq": {
                            "blockers": [
                                {
                                    "blockerInstanceId": 30,
                                    "attackerInstanceIds": [40, 41],
                                    "maxAttackers": 1,
                                }
                            ]
                        },
                    },
                ]
            }
        }
    )

    tracker._process_blocker_requests_from_line(line)
    out = capsys.readouterr().out
    assert out == ""
    assert 30 in tracker.game_state.object_snapshots
    assert 40 in tracker.game_state.object_snapshots


def test_user_action_taken_logs_db_backed_ability_text(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 8
    tracker.game_state.active_player = 1
    tracker.game_state.last_player_turn_number = 8
    tracker.card_db.names[100546] = "Cool but Rude"
    tracker.card_db.ability_texts[(100546, 143758)] = "{o1oR}: Level 2"

    game_objects = [{"instanceId": 328, "grpId": 100546, "ownerSeatId": 1, "controllerSeatId": 1}]
    create_annotation = {
        "affectorId": 328,
        "affectedIds": [337],
        "type": ["AnnotationType_AbilityInstanceCreated"],
    }
    action_annotation = {
        "affectorId": 1,
        "affectedIds": [337],
        "type": ["AnnotationType_UserActionTaken"],
        "details": [
            {"key": "actionType", "valueInt32": [4]},
            {"key": "abilityGrpId", "valueInt32": [143758]},
        ],
    }

    tracker._process_annotation(create_annotation, game_objects)
    tracker._process_annotation(action_annotation, game_objects)
    out = capsys.readouterr().out

    assert "[0:00] You: [Cool but Rude] - 1R: Level 2" in out


def test_ability_text_formats_tap_and_mana_symbols_for_display():
    assert (
        CardTracker._normalize_ability_text(
            "{1}, {T}, Sacrifice this token: Target creature you control explores."
        )
        == "1, tap, Sacrifice this token: Target creature you control explores."
    )


def test_target_spec_adds_target_to_triggered_ability_resolution(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 8
    tracker.game_state.last_player_turn_number = 7
    tracker.card_db.names[100510] = "Sewer-veillance Cam"
    tracker.card_db.names[92134] = "The Mindskinner"
    tracker.card_db.ability_texts[(100510, 203096)] = (
        "When this artifact enters or leaves the battlefield, you may tap or untap target creature."
    )

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {"instanceId": 325, "grpId": 100510, "ownerSeatId": 1, "controllerSeatId": 1},
                    {"instanceId": 331, "grpId": 203096, "ownerSeatId": 1, "controllerSeatId": 1},
                ],
                "annotations": [
                    {
                        "affectorId": 325,
                        "affectedIds": [331],
                        "type": ["AnnotationType_AbilityInstanceCreated"],
                    },
                    {
                        "affectorId": 1,
                        "affectedIds": [331],
                        "type": ["AnnotationType_PlayerSelectingTargets"],
                    },
                ],
            },
        }
    )
    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {
                        "instanceId": 314,
                        "grpId": 92134,
                        "ownerSeatId": 2,
                        "controllerSeatId": 2,
                        "cardTypes": ["CardType_Creature"],
                        "power": {"value": 10},
                        "toughness": {"value": 1},
                    }
                ],
                "persistentAnnotations": [
                    {
                        "affectorId": 331,
                        "affectedIds": [314],
                        "type": ["AnnotationType_TargetSpec"],
                        "details": [{"key": "promptParameters", "valueInt32": [331]}],
                    }
                ],
                "annotations": [
                    {
                        "affectorId": 331,
                        "affectedIds": [331],
                        "type": ["AnnotationType_ResolutionStart"],
                        "details": [{"key": "grpid", "valueInt32": [203096]}],
                    }
                ],
            },
        }
    )
    out = capsys.readouterr().out

    assert (
        "[Sewer-veillance Cam] - When this artifact enters or leaves the battlefield, you may tap or untap target creature. -> [The Mindskinner (10/1)]"
        in out
    )


def test_non_mana_tap_result_logs_source_and_target(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 8
    tracker.card_db.names[100510] = "Sewer-veillance Cam"
    tracker.card_db.names[92134] = "The Mindskinner"
    tracker.card_db.ability_texts[(100510, 203096)] = "Tap or untap target creature."
    tracker.game_state.ability_instance_sources[331] = 325
    tracker.game_state.object_snapshots[325] = {
        "instanceId": 325,
        "grpId": 100510,
        "ownerSeatId": 1,
    }
    tracker.game_state.object_snapshots[331] = {
        "instanceId": 331,
        "grpId": 203096,
        "ownerSeatId": 1,
    }

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {
                        "instanceId": 314,
                        "grpId": 92134,
                        "ownerSeatId": 2,
                        "cardTypes": ["CardType_Creature"],
                        "power": {"value": 10},
                        "toughness": {"value": 1},
                    }
                ],
                "annotations": [
                    {
                        "affectorId": 331,
                        "affectedIds": [314],
                        "type": ["AnnotationType_TappedUntappedPermanent"],
                        "details": [{"key": "tapped", "valueInt32": [1]}],
                    }
                ],
            },
        }
    )
    out = capsys.readouterr().out

    assert "You: [Sewer-veillance Cam] tapped [The Mindskinner (10/1)]" in out


def test_target_selecting_spell_defers_cast_until_target_spec(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 9
    tracker.game_state.last_opponent_turn_number = 9
    tracker.card_db.names[91001] = "Fell"
    tracker.card_db.names[91002] = "Synthesizer Labship"

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {
                        "instanceId": 369,
                        "grpId": 91001,
                        "ownerSeatId": 2,
                        "controllerSeatId": 2,
                        "cardTypes": ["CardType_Sorcery"],
                    },
                    {
                        "instanceId": 452,
                        "grpId": 91002,
                        "ownerSeatId": 1,
                        "controllerSeatId": 1,
                        "cardTypes": ["CardType_Artifact"],
                    },
                ],
                "annotations": [
                    {
                        "affectorId": 369,
                        "affectedIds": [369],
                        "type": ["AnnotationType_ZoneTransfer"],
                        "details": [{"key": "category", "valueString": ["CastSpell"]}],
                    },
                    {
                        "affectorId": 2,
                        "affectedIds": [369],
                        "type": ["AnnotationType_PlayerSelectingTargets"],
                    },
                ],
            },
        }
    )
    first = capsys.readouterr().out
    assert "cast [Fell" not in first

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {
                        "instanceId": 369,
                        "grpId": 91001,
                        "ownerSeatId": 2,
                        "controllerSeatId": 2,
                        "cardTypes": ["CardType_Sorcery"],
                    },
                    {
                        "instanceId": 452,
                        "grpId": 91002,
                        "ownerSeatId": 1,
                        "controllerSeatId": 1,
                        "cardTypes": ["CardType_Artifact"],
                    },
                ],
                "persistentAnnotations": [
                    {
                        "affectorId": 369,
                        "affectedIds": [452],
                        "type": ["AnnotationType_TargetSpec"],
                        "details": [{"key": "promptParameters", "valueInt32": [369]}],
                    }
                ],
                "annotations": [
                    {
                        "affectorId": 2,
                        "affectedIds": [369],
                        "type": ["AnnotationType_UserActionTaken"],
                        "details": [{"key": "actionType", "valueInt32": [1]}],
                    }
                ],
            },
        }
    )
    second = capsys.readouterr().out

    assert "Opponent: cast [Fell (Sorcery)] -> [Synthesizer Labship]" in second


def test_modified_life_logs_source_card_when_available(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.player_life = 19
    tracker.game_state.turn_number = 9
    tracker.card_db.names[95000] = "Starting Town"
    tracker.game_state.ability_instance_sources[384] = 320
    tracker.game_state.object_snapshots[320] = {"instanceId": 320, "grpId": 95000, "ownerSeatId": 1}

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "annotations": [
                    {
                        "affectorId": 384,
                        "affectedIds": [1],
                        "type": ["AnnotationType_ModifiedLife"],
                        "details": [{"key": "life", "valueInt32": [-1]}],
                    }
                ]
            },
        }
    )
    out = capsys.readouterr().out

    assert "You: lost 1 life [Starting Town] (now 18)" in out


def test_return_zone_transfer_logs_source_spell_and_sneak_cost(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 12
    tracker.game_state.last_player_turn_number = 11
    tracker.game_state.last_opponent_turn_number = 12
    tracker.game_state.combat_phase_active = True
    tracker.card_db.names[94027] = "Unsummon"
    tracker.card_db.names[94851] = "Memory Guardian"
    tracker.card_db.names[100496] = "Donatello's Technique"
    tracker.card_db.names[92142] = "Silent Hallcreeper"
    tracker.game_state.object_snapshots[369] = {
        "instanceId": 369,
        "grpId": 94027,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
    }
    tracker.game_state.object_snapshots[321] = {
        "instanceId": 321,
        "grpId": 94851,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
    }
    tracker.game_state.object_snapshots[421] = {
        "instanceId": 421,
        "grpId": 100496,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
    }
    tracker.game_state.object_snapshots[397] = {
        "instanceId": 397,
        "grpId": 92142,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
    }
    tracker.game_state.stack_items[421] = {
        "seat": 2,
        "label": "[Donatello's Technique]",
        "kind": "spell",
        "status": "pending",
    }

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "annotations": [
                    {
                        "affectedIds": [321],
                        "type": ["AnnotationType_ObjectIdChanged"],
                        "details": [
                            {"key": "orig_id", "valueInt32": [321]},
                            {"key": "new_id", "valueInt32": [370]},
                        ],
                    },
                    {
                        "affectorId": 369,
                        "affectedIds": [370],
                        "type": ["AnnotationType_ZoneTransfer"],
                        "details": [
                            {"key": "zone_src", "valueInt32": [28]},
                            {"key": "zone_dest", "valueInt32": [31]},
                            {"key": "category", "valueString": ["Return"]},
                        ],
                    },
                    {
                        "affectedIds": [397],
                        "type": ["AnnotationType_ObjectIdChanged"],
                        "details": [
                            {"key": "orig_id", "valueInt32": [397]},
                            {"key": "new_id", "valueInt32": [423]},
                        ],
                    },
                    {
                        "affectorId": 421,
                        "affectedIds": [423],
                        "type": ["AnnotationType_ZoneTransfer"],
                        "details": [
                            {"key": "zone_src", "valueInt32": [28]},
                            {"key": "zone_dest", "valueInt32": [35]},
                            {"key": "category", "valueString": ["Return"]},
                        ],
                    },
                ]
            },
        }
    )
    out = capsys.readouterr().out

    assert "Opponent: [Unsummon] returned [Memory Guardian] to your hand" in out
    assert (
        "Opponent: returned [Silent Hallcreeper] to hand as cost for [Donatello's Technique]" in out
    )


def test_targeted_equip_action_logs_once_with_target(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 13
    tracker.card_db.names[100520] = "Improvised Arsenal"
    tracker.card_db.names[94851] = "Memory Guardian"
    tracker.card_db.ability_texts[(100520, 203146)] = "Equip {R}"

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {"instanceId": 406, "grpId": 100520, "ownerSeatId": 1, "controllerSeatId": 1},
                    {"instanceId": 451, "grpId": 203146, "ownerSeatId": 1, "controllerSeatId": 1},
                ],
                "annotations": [
                    {
                        "affectorId": 406,
                        "affectedIds": [451],
                        "type": ["AnnotationType_AbilityInstanceCreated"],
                    },
                    {
                        "affectorId": 1,
                        "affectedIds": [451],
                        "type": ["AnnotationType_PlayerSelectingTargets"],
                    },
                ],
            },
        }
    )
    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "gameObjects": [
                    {
                        "instanceId": 405,
                        "grpId": 94851,
                        "ownerSeatId": 1,
                        "cardTypes": ["CardType_Creature"],
                        "power": {"value": 3},
                        "toughness": {"value": 4},
                    }
                ],
                "persistentAnnotations": [
                    {
                        "affectorId": 451,
                        "affectedIds": [405],
                        "type": ["AnnotationType_TargetSpec"],
                        "details": [{"key": "promptParameters", "valueInt32": [451]}],
                    }
                ],
                "annotations": [
                    {
                        "affectorId": 1,
                        "affectedIds": [451],
                        "type": ["AnnotationType_UserActionTaken"],
                        "details": [
                            {"key": "actionType", "valueInt32": [2]},
                            {"key": "abilityGrpId", "valueInt32": [203146]},
                        ],
                    }
                ],
            },
        }
    )
    out = capsys.readouterr().out

    assert out.count("[Improvised Arsenal] - Equip R") == 1
    assert "[Improvised Arsenal] - Equip R -> [Memory Guardian (3/4)]" in out


def test_resolution_start_logs_hidden_ability_text_for_source_card(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 8
    tracker.game_state.active_player = 1
    tracker.game_state.last_player_turn_number = 8
    tracker.card_db.names[100546] = "Cool but Rude"
    tracker.card_db.ability_texts[(100546, 203139)] = (
        "Whenever you discard a card, this Class deals 2 damage to each opponent."
    )

    game_objects = [{"instanceId": 328, "grpId": 100546, "ownerSeatId": 1, "controllerSeatId": 1}]
    create_annotation = {
        "affectorId": 328,
        "affectedIds": [337],
        "type": ["AnnotationType_AbilityInstanceCreated"],
    }
    resolution_annotation = {
        "affectorId": 337,
        "affectedIds": [337],
        "type": ["AnnotationType_ResolutionStart"],
        "details": [{"key": "grpid", "valueInt32": [203139]}],
    }

    tracker._process_annotation(create_annotation, game_objects)
    tracker._process_annotation(resolution_annotation, game_objects)
    out = capsys.readouterr().out

    assert (
        "You: [Cool but Rude] - Whenever you discard a card, this Class deals 2 damage to each opponent."
        in out
    )


def test_process_game_events_orders_activated_ability_before_discard_cost(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 10
    tracker.game_state.active_player = 2
    tracker.game_state.last_player_turn_number = 9
    tracker.card_db.names[1001] = "Iron-Shield Elf"
    tracker.card_db.names[1002] = "Watery Grave"
    tracker.card_db.ability_texts[(1001, 152701)] = (
        "Discard a card: This creature gains indestructible until end of turn. Tap it."
    )

    data = {
        "gameObjects": [
            {"instanceId": 332, "grpId": 1001, "ownerSeatId": 1, "controllerSeatId": 1},
            {"instanceId": 362, "grpId": 1002, "ownerSeatId": 1, "controllerSeatId": 1},
        ],
        "annotations": [
            {
                "affectorId": 361,
                "affectedIds": [362],
                "type": ["AnnotationType_ZoneTransfer"],
                "details": [{"key": "category", "valueString": ["Discard"]}],
            },
            {
                "affectorId": 332,
                "affectedIds": [361],
                "type": ["AnnotationType_AbilityInstanceCreated"],
            },
            {
                "affectorId": 1,
                "affectedIds": [361],
                "type": ["AnnotationType_UserActionTaken"],
                "details": [{"key": "abilityGrpId", "valueInt32": [152701]}],
            },
        ],
    }

    tracker._process_game_events(data)
    out = capsys.readouterr().out

    ability_idx = out.index("[Iron-Shield Elf] - Discard a card")
    discard_idx = out.index("[Watery Grave] was discarded")
    assert ability_idx < discard_idx


def test_game_over_modified_life_annotation_records_final_life_loss(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.player_life = 14
    tracker.game_state.opponent_life = 3
    tracker.game_state.turn_number = 10
    tracker.game_state.active_player = 2
    tracker.game_state.last_player_turn_number = 9
    tracker.card_db.names[95039] = "Monument to Endurance"
    tracker.card_db.ability_texts[(95039, 176655)] = "Each opponent loses 3 life."
    tracker.game_state.object_snapshots[304] = {
        "instanceId": 304,
        "grpId": 95039,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Artifact"],
    }
    tracker.game_state.ability_instance_sources[365] = 304

    tracker._handle_event(
        {
            "type": "game_state",
            "data": {
                "players": [
                    {"systemSeatNumber": 1, "lifeTotal": 14},
                    {"systemSeatNumber": 2, "status": "PlayerStatus_PendingLoss"},
                ],
                "diffDeletedInstanceIds": [365],
                "annotations": [
                    {
                        "affectorId": 365,
                        "affectedIds": [365],
                        "type": ["AnnotationType_ResolutionStart"],
                        "details": [{"key": "grpid", "valueInt32": [176655]}],
                    },
                    {
                        "affectorId": 365,
                        "affectedIds": [2],
                        "type": ["AnnotationType_ModifiedLife"],
                        "details": [{"key": "life", "valueInt32": [-3]}],
                    },
                    {
                        "affectorId": 304,
                        "affectedIds": [365],
                        "type": ["AnnotationType_AbilityInstanceDeleted"],
                    },
                ],
            },
        }
    )
    out = capsys.readouterr().out

    assert "You: [Monument to Endurance] - Each opponent loses 3 life." in out
    assert "Opponent: lost 3 life [Monument to Endurance] (now 0)" in out
    assert tracker.game_state.opponent_life == 0
    assert tracker.game_state.match_stats[1]["total_damage"] == 3
    assert tracker._resolve_game_outcome() == ("win", "Opponent reached 0 life")


def test_resolution_start_skips_duplicate_text_when_user_action_already_logged(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 10
    tracker.game_state.active_player = 1
    tracker.game_state.last_player_turn_number = 10
    tracker.card_db.names[100546] = "Cool but Rude"
    tracker.card_db.ability_texts[(100546, 143758)] = "{o1oR}: Level 2"

    game_objects = [
        {
            "instanceId": 328,
            "grpId": 100546,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "cardTypes": ["CardType_Enchantment"],
        }
    ]
    tracker._process_annotation(
        {
            "affectorId": 328,
            "affectedIds": [337],
            "type": ["AnnotationType_AbilityInstanceCreated"],
        },
        game_objects,
    )
    tracker._process_annotation(
        {
            "affectorId": 1,
            "affectedIds": [337],
            "type": ["AnnotationType_UserActionTaken"],
            "details": [{"key": "abilityGrpId", "valueInt32": [143758]}],
        },
        game_objects,
    )
    tracker._process_annotation(
        {
            "affectorId": 337,
            "affectedIds": [337],
            "type": ["AnnotationType_ResolutionStart"],
            "details": [{"key": "grpid", "valueInt32": [143758]}],
        },
        game_objects,
    )
    out = capsys.readouterr().out

    assert "[Cool but Rude] - 1R: Level 2" in out
    assert "Stack: [Cool but Rude] - 1R: Level 2 [resolved]" not in out


def test_user_action_taken_skips_land_mana_ability_text(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 10
    tracker.game_state.active_player = 1
    tracker.game_state.last_player_turn_number = 10
    tracker.card_db.names[9001] = "Blood Crypt"
    tracker.card_db.ability_texts[(9001, 1001)] = "{oT}: Add {oB}."

    game_objects = [
        {
            "instanceId": 77,
            "grpId": 9001,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "cardTypes": ["CardType_Land"],
        }
    ]
    tracker._process_annotation(
        {"affectorId": 77, "affectedIds": [88], "type": ["AnnotationType_AbilityInstanceCreated"]},
        game_objects,
    )
    tracker._process_annotation(
        {
            "affectorId": 1,
            "affectedIds": [88],
            "type": ["AnnotationType_UserActionTaken"],
            "details": [{"key": "abilityGrpId", "valueInt32": [1001]}],
        },
        game_objects,
    )
    out = capsys.readouterr().out

    assert "Blood Crypt" not in out


def test_session_stats_record_once_per_game():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.first_player_seat = 1

    tracker._record_session_outcome("win")
    tracker._record_session_outcome("win")
    assert tracker.session_games_played == 1
    assert tracker.session_wins == 1
    assert tracker.session_losses == 0
    assert tracker.session_player_went_first == 1
    assert tracker.session_opponent_went_first == 0

    tracker._session_stats_recorded_this_game = False
    tracker.game_state.first_player_seat = 2
    tracker._record_session_outcome("loss")
    assert tracker.session_games_played == 2
    assert tracker.session_wins == 1
    assert tracker.session_losses == 1
    assert tracker.session_player_went_first == 1
    assert tracker.session_opponent_went_first == 1


def test_session_first_split_formats_counts_and_percentages():
    tracker = make_tracker()
    tracker.session_player_went_first = 4
    tracker.session_opponent_went_first = 7

    assert (
        tracker._session_first_split_line() == "Went First: You 4/11 (36.4%), Opponent 7/11 (63.6%)"
    )
    assert "First: You 36.4% / Opp 63.6%" in tracker._session_stats_line()


def test_session_runtime_counts_completed_game_time_not_tracker_uptime():
    tracker = make_tracker()
    tracker.session_start_time = datetime(2026, 5, 7, 8, 0, 0)
    tracker.game_state.game_start_time = datetime(2026, 5, 7, 20, 0, 0)
    tracker.game_state.game_end_time = datetime(2026, 5, 7, 20, 7, 30)

    tracker._record_session_outcome("win")

    assert tracker._session_runtime_str() == "7:30"
    assert "Play Time:7:30" in tracker._session_stats_line()


def test_session_runtime_includes_active_game_time_only():
    tracker = make_tracker()
    tracker.session_game_runtime_seconds = 450
    tracker.game_state.in_match = True
    tracker.game_state.match_complete = False
    tracker.game_state.game_start_time = datetime.now()
    tracker.game_state.game_end_time = None

    assert tracker._session_play_runtime_seconds() >= 450
    assert tracker._session_play_runtime_seconds() < 455


def test_turn_timing_tracks_each_turn_and_closes_final_turn():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._current_event_time = datetime(2026, 7, 19, 20, 0, 0)
    tracker._update_game_state({"turnInfo": {"turnNumber": 1, "activePlayer": 1}})
    tracker._current_event_time = datetime(2026, 7, 19, 20, 0, 42)
    tracker._update_game_state({"turnInfo": {"turnNumber": 2, "activePlayer": 2}})
    tracker._current_event_time = datetime(2026, 7, 19, 20, 1, 0)
    tracker._update_game_state({"turnInfo": {"turnNumber": 3, "activePlayer": 1}})
    tracker.game_state.game_end_time = datetime(2026, 7, 19, 20, 1, 15)
    tracker._finalize_turn_timing()

    assert tracker.game_state.turn_time_seconds_by_seat == {1: 57, 2: 18}
    assert [turn["duration_seconds"] for turn in tracker.game_state.completed_turns] == [42, 18, 15]
    assert [turn["seat_id"] for turn in tracker.game_state.completed_turns] == [1, 2, 1]


def test_repeated_turn_one_state_does_not_split_turn_timing():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._current_event_time = datetime(2026, 7, 23, 20, 0, 0)
    tracker._update_game_state({"turnInfo": {"turnNumber": 1, "activePlayer": 1}})
    tracker._current_event_time = datetime(2026, 7, 23, 20, 0, 10)
    tracker._update_game_state({"turnInfo": {"turnNumber": 1, "activePlayer": 1}})
    tracker._current_event_time = datetime(2026, 7, 23, 20, 0, 30)
    tracker._update_game_state({"turnInfo": {"turnNumber": 2, "activePlayer": 2}})

    assert len(tracker.game_state.completed_turns) == 1
    assert tracker.game_state.completed_turns[0]["turn_number"] == 1
    assert tracker.game_state.completed_turns[0]["duration_seconds"] == 30


def test_turn_timing_persistence_coalesces_duplicate_turn_segments(tmp_path):
    tracker = make_tracker()
    tracker.game_state.completed_turns = [
        {
            "turn_number": 1,
            "seat_id": 1,
            "started_at": datetime(2026, 7, 23, 20, 0, 0),
            "ended_at": datetime(2026, 7, 23, 20, 0, 10),
            "duration_seconds": 10,
        },
        {
            "turn_number": 1,
            "seat_id": 1,
            "started_at": datetime(2026, 7, 23, 20, 0, 10),
            "ended_at": datetime(2026, 7, 23, 20, 0, 30),
            "duration_seconds": 20,
        },
    ]
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        tracker._persist_turn_timings(conn, "game-1")
        rows = conn.execute(
            """
            SELECT turn_number, seat_id, started_at, ended_at, duration_seconds
            FROM game_turns
            """
        ).fetchall()

    assert rows == [
        (
            1,
            1,
            "2026-07-23T20:00:00",
            "2026-07-23T20:00:30",
            30,
        )
    ]


def test_turn_header_shows_the_previous_turn_duration(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._current_event_time = datetime(2026, 7, 19, 20, 0, 0)
    tracker._update_game_state({"turnInfo": {"turnNumber": 1, "activePlayer": 1}})
    tracker._current_event_time = datetime(2026, 7, 19, 20, 0, 42)
    tracker._update_game_state({"turnInfo": {"turnNumber": 2, "activePlayer": 2}})
    tracker._current_event_time = datetime(2026, 7, 19, 20, 1, 0)
    tracker._update_game_state({"turnInfo": {"turnNumber": 3, "activePlayer": 1}})
    capsys.readouterr()

    tracker._flush_pending_player_turn_header()
    out = capsys.readouterr().out

    assert "Turn 3 - YOUR TURN" in out
    assert "Previous Turn (Opponent): 18s" in out


def test_turn_header_duration_uses_compact_minutes_and_seconds():
    tracker = make_tracker()

    assert tracker._format_turn_header_duration(42) == "42s"
    assert tracker._format_turn_header_duration(209) == "3m 29s"


def test_session_deck_records_track_each_deck_and_render_at_game_end(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.player_deck_id = "deck-a"
    tracker.game_state.player_deck_name = "Azorius Control"

    tracker._record_session_outcome("win")
    tracker._session_stats_recorded_this_game = False
    tracker.game_state.player_deck_id = "deck-b"
    tracker.game_state.player_deck_name = "Mono-Red Aggro"
    tracker._record_session_outcome("loss")

    tracker._print_result_summary("loss", "Test result", "3:00")
    out = capsys.readouterr().out

    assert "Deck Session: Azorius Control: 1-0 (100.0%)" in out
    assert "Deck Session: Mono-Red Aggro: 0-1 (0.0%)" in out


def test_print_summary_uses_session_totals_not_last_game_state(capsys):
    tracker = make_tracker()
    tracker.session_games_played = 6
    tracker.session_wins = 3
    tracker.session_losses = 3
    tracker.session_player_went_first = 2
    tracker.session_opponent_went_first = 4
    tracker.session_player_cards_played = 42
    tracker.session_opponent_cards_played = 37
    tracker.session_total_mulligans = 5
    tracker.game_state.player_life = 25
    tracker.game_state.opponent_life = 25
    tracker.game_state.turn_number = 1
    tracker.game_state.first_player_seat = 2
    tracker.game_state.player_seat_id = 1

    tracker._print_summary()
    out = capsys.readouterr().out

    assert "Games Played: 6" in out
    assert "Wins: 3" in out
    assert "Losses: 3" in out
    assert "Win Rate: 50.0%" in out
    assert "Went First: You 2/6 (33.3%), Opponent 4/6 (66.7%)" in out
    assert "Total Mulligans: 5" in out
    assert "Total Cards Played: 42" in out
    assert "Total Opponent Cards Played: 37" in out
    assert "Final Life:" not in out
    assert "Turns Played:" not in out


def test_game_summary_prints_first_player_and_session_split(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.first_player_seat = 2
    tracker.game_state.player_life = 0
    tracker.game_state.opponent_life = 10
    tracker.game_state.game_start_time = datetime(2026, 6, 11, 20, 0, 0)
    tracker.game_state.game_end_time = datetime(2026, 6, 11, 20, 5, 0)
    tracker.game_state.winner_seat = 2
    tracker.game_state.completed_turns = [
        {"turn_number": 1, "seat_id": 1, "duration_seconds": 90},
        {"turn_number": 2, "seat_id": 2, "duration_seconds": 60},
    ]
    tracker.game_state.turn_time_seconds_by_seat = {1: 90, 2: 60}
    tracker.session_player_went_first = 4
    tracker.session_opponent_went_first = 6

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "Went First This Game: Opponent" in out
    assert "Went First: You 4/11 (36.4%), Opponent 7/11 (63.6%)" in out
    assert "Turn Time: You 1:30 across 1 turn(s) (1:30 avg), Opponent 1:00 across 1 turn(s) (1:00 avg)" in out


def test_seatless_concede_req_does_not_override_structured_winner():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    game_over_line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "results": [
                                    {
                                        "scope": "MatchScope_Game",
                                        "result": "ResultType_WinLoss",
                                        "winningTeamId": 1,
                                        "reason": "ResultReason_Concede",
                                    }
                                ],
                            }
                        },
                    }
                ]
            }
        }
    )

    tracker._check_game_end(game_over_line)
    assert tracker.game_state.winner_seat == 1

    seatless_concede_line = json.dumps(
        {"clientToGreMessage": {"type": "ClientMessageType_ConcedeReq"}}
    )
    tracker._check_game_end(seatless_concede_line)

    assert tracker.game_state.winner_seat == 1


def test_seatless_concede_req_counts_as_local_player_loss():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    seatless_concede_line = json.dumps(
        {"clientToGreMessage": {"type": "ClientMessageType_ConcedeReq"}}
    )
    tracker._check_game_end(seatless_concede_line)

    assert tracker.game_state.winner_seat == 2
    assert tracker.game_state.winner_reason == "concede_req:local_player_conceded"
    assert tracker.game_state.match_complete is True


def test_opponent_disconnect_text_does_not_override_local_concede():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._check_game_end(
        json.dumps({"clientToGreMessage": {"type": "ClientMessageType_ConcedeReq"}})
    )
    tracker._check_game_end("Opponent disconnected from match service")

    assert tracker.game_state.winner_seat == 2
    assert tracker.game_state.winner_reason == "concede_req:local_player_conceded"


def test_format_actor_event_has_consistent_prefix():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.last_player_turn_number = 18
    tracker.game_state.last_turn_announced = 18

    line = tracker._format_actor_event("📥", 1, "drew a card")
    assert line == "[0:00] You: drew a card"


def test_return_then_put_attacking_reports_combat_swap(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.last_player_turn_number = 6
    tracker.game_state.last_turn_announced = 6
    tracker.game_state.combat_phase_active = True

    return_annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [101],
        "details": [{"key": "category", "valueString": ["Return"]}],
    }
    return_objects = [
        {"instanceId": 101, "grpId": 111, "ownerSeatId": 1, "controllerSeatId": 1, "zoneId": 31}
    ]
    tracker._process_annotation(return_annotation, return_objects)

    put_annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [202],
        "details": [{"key": "category", "valueString": ["Put"]}],
    }
    put_objects = [
        {
            "instanceId": 202,
            "grpId": 222,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "zoneId": 31,
            "attackState": "AttackState_Attacking",
            "attackInfo": {"targetId": 2},
        }
    ]
    tracker._process_annotation(put_annotation, put_objects)

    out = capsys.readouterr().out
    assert "[0:00] You: returned [Card111] to hand" in out
    assert "Combat swap: returned [Card111] and put [Card222] onto battlefield attacking" in out
    assert "possible Ninjutsu/Sneak" in out


def test_put_before_first_turn_is_suppressed(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    put_annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [303],
        "details": [{"key": "category", "valueString": ["Put"]}],
    }
    put_objects = [
        {
            "instanceId": 303,
            "grpId": 333,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
        }
    ]
    tracker._process_annotation(put_annotation, put_objects)
    out = capsys.readouterr().out

    assert out == ""


def test_put_into_hand_uses_destination_zone_and_source_spell(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 2
    tracker.game_state.opponent_seat_id = 1
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 3
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 3
    tracker.game_state.last_player_turn_number = 3
    tracker.card_db.names[96625] = "Consult the Star Charts"
    tracker.card_db.names[98527] = "Ashling's Command"

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectorId": 292,
        "affectedIds": [295],
        "details": [
            {"key": "zone_src", "valueInt32": [36]},
            {"key": "zone_dest", "valueInt32": [35]},
            {"key": "category", "valueString": ["Put"]},
        ],
    }
    game_objects = [
        {
            "instanceId": 292,
            "grpId": 96625,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
        },
        {
            "instanceId": 295,
            "grpId": 98527,
            "zoneId": 35,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
        },
    ]
    zones_by_id = {
        35: {"zoneId": 35, "type": "ZoneType_Hand", "ownerSeatId": 2},
        36: {"zoneId": 36, "type": "ZoneType_Library", "ownerSeatId": 2},
    }

    tracker._process_annotation(annotation, game_objects, zones_by_id=zones_by_id)
    out = capsys.readouterr().out

    assert "You: [Consult the Star Charts] put [Ashling's Command] into your hand" in out
    assert "onto battlefield" not in out


def test_cast_spell_uses_snapshot_when_gameobjects_diff_omits_spell(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 5
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 5
    tracker.game_state.last_opponent_turn_number = 5
    tracker.game_state.object_snapshots[700] = {
        "instanceId": 700,
        "grpId": 1700,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Instant"],
    }

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [700],
        "details": [{"key": "category", "valueString": ["CastSpell"]}],
    }
    resolve_annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [700],
        "details": [{"key": "category", "valueString": ["Resolve"]}],
    }

    tracker._process_annotation(annotation, [])
    first = capsys.readouterr().out
    assert "[0:00] Opponent: cast [Card1700 (Instant)]" in first

    tracker._process_annotation(resolve_annotation, [])
    out = capsys.readouterr().out
    assert "cast [Card1700 (Instant)]" not in out
    assert 700 in tracker.game_state.seen_instance_ids
    assert len(tracker.opponent_cards) == 1


def test_cast_spell_not_marked_seen_until_card_object_available(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 6
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 6
    tracker.game_state.last_opponent_turn_number = 6

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [701],
        "details": [{"key": "category", "valueString": ["CastSpell"]}],
    }
    resolve_annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [701],
        "details": [{"key": "category", "valueString": ["Resolve"]}],
    }

    tracker._process_annotation(annotation, [])
    first = capsys.readouterr().out
    assert first == ""
    assert 701 not in tracker.game_state.seen_instance_ids

    tracker._process_annotation(
        resolve_annotation,
        [
            {
                "instanceId": 701,
                "grpId": 1701,
                "ownerSeatId": 2,
                "controllerSeatId": 2,
                "cardTypes": ["CardType_Sorcery"],
            }
        ],
    )
    second = capsys.readouterr().out

    assert "[0:00] Opponent: cast [Card1701 (Sorcery)]" in second
    assert 701 in tracker.game_state.seen_instance_ids
    assert len(tracker.opponent_cards) == 1


def test_resolve_zone_transfer_falls_back_to_cast_logging(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 7
    tracker.game_state.last_opponent_turn_number = 7

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [702],
        "details": [{"key": "category", "valueString": ["Resolve"]}],
    }
    game_objects = [
        {
            "instanceId": 702,
            "grpId": 1702,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
            "cardTypes": ["CardType_Instant"],
        }
    ]

    tracker._process_annotation(annotation, game_objects)
    out = capsys.readouterr().out

    assert "[0:00] Opponent: cast [Card1702 (Instant)]" in out
    assert 702 in tracker.game_state.seen_instance_ids
    assert len(tracker.opponent_cards) == 1


def test_pending_instant_cast_flushes_before_noncombat_damage_during_combat(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 12
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 12
    tracker.game_state.last_player_turn_number = 11
    tracker.game_state.last_opponent_turn_number = 12
    tracker.game_state.combat_phase_active = True
    tracker.game_state.object_snapshots[9100] = {
        "instanceId": 9100,
        "grpId": 2000,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Instant"],
    }

    cast_annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [9100],
        "details": [{"key": "category", "valueString": ["CastSpell"]}],
    }
    damage_annotation = {
        "type": ["AnnotationType_Damage"],
        "affectedIds": [9200],
        "details": [
            {"key": "amount", "valueInt32": [2]},
            {"key": "source", "valueInt32": [9100]},
        ],
    }
    game_objects = [
        {
            "instanceId": 9100,
            "grpId": 2000,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "cardTypes": ["CardType_Instant"],
        },
        {
            "instanceId": 9200,
            "grpId": 3000,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
            "cardTypes": ["CardType_Creature"],
        },
    ]

    tracker._process_annotation(cast_annotation, game_objects)
    cast_out = capsys.readouterr().out
    assert "[0:00] You: cast [Card2000 (Instant)]" in cast_out

    tracker._process_annotation(damage_annotation, game_objects)
    out = capsys.readouterr().out

    assert "cast [Card2000 (Instant)]" not in out
    assert "[0:00] [Card3000] (opponent's) took 2 damage" in out
    assert "Combat:" not in out


def test_destroy_from_spell_affector_flushes_pending_cast_first(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 5
    tracker.game_state.active_player = 1
    tracker.game_state.last_player_turn_number = 5
    tracker.game_state.last_turn_announced = 5

    game_objects = [
        {
            "instanceId": 9100,
            "grpId": 2000,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "cardTypes": ["CardType_Instant"],
        },
        {
            "instanceId": 9200,
            "grpId": 3000,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
            "cardTypes": ["CardType_Creature"],
        },
    ]

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [9100],
            "details": [{"key": "category", "valueString": ["CastSpell"]}],
        },
        game_objects,
    )
    cast_out = capsys.readouterr().out
    assert "[0:00] You: cast [Card2000 (Instant)]" in cast_out

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectorId": 9100,
            "affectedIds": [9200],
            "details": [{"key": "category", "valueString": ["Destroy"]}],
        },
        game_objects,
    )
    out = capsys.readouterr().out

    assert "cast [Card2000 (Instant)]" not in out
    assert "[0:00] Opponent: [Card3000] was destroyed" in out


def test_cast_and_resolve_with_object_id_change_logs_once(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 7
    tracker.game_state.last_player_turn_number = 7

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ObjectIdChanged"],
            "affectedIds": [802],
            "details": [
                {"key": "orig_id", "valueInt32": [801]},
                {"key": "new_id", "valueInt32": [802]},
            ],
        },
        [],
    )
    assert capsys.readouterr().out == ""

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [802],
            "details": [{"key": "category", "valueString": ["CastSpell"]}],
        },
        [
            {
                "instanceId": 802,
                "grpId": 1802,
                "ownerSeatId": 1,
                "controllerSeatId": 1,
                "cardTypes": ["CardType_Sorcery"],
            }
        ],
    )
    cast_out = capsys.readouterr().out
    assert cast_out.count("cast [Card1802 (Sorcery)]") == 1

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ResolutionStart"],
            "affectedIds": [801],
            "details": [{"key": "grpid", "valueInt32": [1802]}],
        },
        [
            {
                "instanceId": 801,
                "grpId": 1802,
                "ownerSeatId": 1,
                "controllerSeatId": 1,
                "cardTypes": ["CardType_Sorcery"],
            }
        ],
    )
    out = capsys.readouterr().out

    assert "Stack: [Card1802 (Sorcery)] [resolved]" not in out
    assert 801 in tracker.game_state.seen_instance_ids


def test_countered_spell_marks_stack_item_countered(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 7
    tracker.game_state.last_player_turn_number = 7

    game_objects = [
        {
            "instanceId": 810,
            "grpId": 1810,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "cardTypes": ["CardType_Instant"],
        }
    ]

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [810],
            "details": [{"key": "category", "valueString": ["CastSpell"]}],
        },
        game_objects,
    )
    capsys.readouterr()

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [810],
            "details": [{"key": "category", "valueString": ["Countered"]}],
        },
        game_objects,
    )
    out = capsys.readouterr().out

    assert "\t[0:00] Stack: [Card1810 (Instant)] [countered]" in out
    assert tracker.game_state.stack_stats[1]["put_on_stack"] == 1
    assert tracker.game_state.stack_stats[1]["countered"] == 1


def test_nested_stack_item_prints_bracketed_resolved_status(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 7
    tracker.game_state.last_player_turn_number = 7

    tracker._register_stack_item(
        811,
        seat_id=1,
        label="[Original Spell]",
        kind="spell",
        turn_override=7,
    )
    tracker._register_stack_item(
        812,
        seat_id=2,
        label="[Response Spell]",
        kind="spell",
        turn_override=7,
    )
    capsys.readouterr()

    tracker._emit_stack_item_status(812, "resolved")
    out = capsys.readouterr().out

    assert "\t[0:00] Stack: [Response Spell] [resolved]" in out
    assert tracker.game_state.stack_stats[2]["resolved"] == 1


def test_deleted_pending_stack_item_is_reported_as_unresolved(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 7
    tracker.game_state.last_player_turn_number = 7

    tracker._register_stack_item(
        811,
        seat_id=1,
        label="[Card1811 (Instant)]",
        kind="spell",
        turn_override=7,
    )

    tracker._reconcile_deleted_stack_items([811])
    out = capsys.readouterr().out

    assert "\t[0:00] Stack: [Card1811 (Instant)] [left stack without resolving - inferred]" in out
    assert tracker.game_state.stack_stats[1]["fizzled"] == 1


def test_deleted_mana_ability_stack_item_is_silently_cleared(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 7
    tracker.game_state.last_opponent_turn_number = 7

    tracker._register_stack_item(
        811,
        seat_id=2,
        label="[Hedron Archive] - {T}: Add {C}{C}.",
        kind="ability",
        turn_override=7,
    )

    tracker._reconcile_deleted_stack_items([811])
    out = capsys.readouterr().out

    assert "left stack without resolving" not in out
    assert "Hedron Archive" not in out
    assert tracker.game_state.stack_stats[2]["fizzled"] == 0


def test_artifact_mana_ability_text_is_not_logged_or_stacked(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 12
    tracker.game_state.last_turn_announced = 12
    tracker.game_state.last_opponent_turn_number = 12
    tracker.card_db.names[91783] = "Patchwork Banner"
    tracker.card_db.ability_texts[(91783, 1055)] = "{T}: Add one mana of any color."

    game_objects_by_id = {
        431: {
            "instanceId": 431,
            "grpId": 91783,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
            "cardTypes": ["CardType_Artifact"],
        },
        566: {
            "instanceId": 566,
            "grpId": 1055,
            "objectSourceGrpId": 91783,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
        },
    }

    tracker._handle_ability_instance_created([566], 431, game_objects_by_id, set())
    out = capsys.readouterr().out

    assert "Patchwork Banner" not in out
    assert 566 not in tracker.game_state.stack_items


def test_casting_time_modal_response_logs_selected_modes(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 13
    tracker.game_state.last_turn_announced = 13
    tracker.game_state.last_player_turn_number = 13
    tracker.card_db.names[86798] = "Rankle's Prank"
    tracker.card_db.ability_texts[143323] = "Each player discards two cards."
    tracker.card_db.ability_texts[168819] = "Each player loses 4 life."

    tracker._capture_casting_time_options_requests(
        {
            "type": "GREMessageType_CastingTimeOptionsReq",
            "gameStateId": 269,
            "castingTimeOptionsReq": {
                "castingTimeOptionReq": [
                    {
                        "ctoId": 4,
                        "castingTimeOptionType": "CastingTimeOptionType_Modal",
                        "affectedId": 572,
                        "grpId": 86798,
                        "playerIdToPrompt": 1,
                        "modalReq": {
                            "abilityGrpId": 168820,
                            "modalOptions": [
                                {"grpId": 143323},
                                {"grpId": 168819},
                                {"grpId": 2260},
                            ],
                        },
                    }
                ]
            },
        }
    )
    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_CastingTimeOptionsResp",
                "gameStateId": 269,
                "castingTimeOptionsResp": {
                    "castingTimeOptionResp": {
                        "ctoId": 4,
                        "castingTimeOptionType": "CastingTimeOptionType_Modal",
                        "chooseModalResp": {"grpIds": [168819, 143323]},
                    }
                },
            }
        }
    )
    out = capsys.readouterr().out

    assert (
        "You: chose modes for [Rankle's Prank]: Each player loses 4 life.; Each player discards two cards."
        in out
    )


def test_destroy_event_uses_current_turn_not_card_owner_last_turn(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 1
    tracker.game_state.last_player_turn_number = 7
    tracker.game_state.last_opponent_turn_number = 6
    tracker.game_state.last_turn_announced = 7

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [9001],
            "details": [{"key": "category", "valueString": ["Destroy"]}],
        },
        [{"instanceId": 9001, "grpId": 1901, "ownerSeatId": 2, "controllerSeatId": 2}],
    )
    out = capsys.readouterr().out

    assert "[0:00] Opponent: [Card1901] was destroyed" in out
    assert "[Turn " not in out


def test_state_based_zero_toughness_prints_zone_event(capsys, tmp_path):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 7
    tracker._diagnostic_text_path = tmp_path / "unhandled.log"

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [9001],
            "details": [
                {"key": "zone_src", "valueInt32": [28]},
                {"key": "zone_dest", "valueInt32": [37]},
                {"key": "category", "valueString": ["SBA_ZeroToughness"]},
            ],
        },
        [
            {
                "instanceId": 9001,
                "grpId": 1901,
                "ownerSeatId": 2,
                "controllerSeatId": 2,
                "cardTypes": ["CardType_Creature"],
            }
        ],
    )
    out = capsys.readouterr().out

    assert "[0:00] Opponent: [Card1901] was put into graveyard (0 toughness)" in out
    assert not tracker._diagnostic_text_path.exists()


def test_does_not_warn_when_first_observed_turn_is_two(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    tracker._update_game_state(
        {"turnInfo": {"turnNumber": 2, "activePlayer": 1, "phase": "Phase_Main1"}}
    )
    out = capsys.readouterr().out

    assert "First observed turn is" not in out
    assert out == ""


def test_warns_when_first_observed_turn_is_three(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    tracker._update_game_state(
        {"turnInfo": {"turnNumber": 3, "activePlayer": 1, "phase": "Phase_Main1"}}
    )
    out = capsys.readouterr().out

    assert "First observed turn is 3" in out
    assert "earlier turn(s) (1, 2)" in out
    assert "Turn 3 - YOUR TURN" not in out


def test_player_turn_header_flushes_on_first_player_event(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    tracker._update_game_state(
        {"turnInfo": {"turnNumber": 2, "activePlayer": 1, "phase": "Phase_Main1"}}
    )
    assert capsys.readouterr().out == ""

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [101],
        "details": [{"key": "category", "valueString": ["Draw"]}],
    }
    game_objects = [{"instanceId": 101, "ownerSeatId": 1}]
    tracker._process_annotation(annotation, game_objects)
    out = capsys.readouterr().out

    assert "Turn 2 - YOUR TURN" in out
    assert "[0:00] You: drew a card" in out


def test_off_turn_land_is_assigned_to_previous_turn(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 2
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 2
    tracker.game_state.last_player_turn_number = 2

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [3001],
        "details": [{"key": "category", "valueString": ["PlayLand"]}],
    }
    game_objects = [
        {
            "instanceId": 3001,
            "grpId": 999,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
            "cardTypes": ["CardType_Land"],
        }
    ]

    tracker._process_annotation(annotation, game_objects)
    out = capsys.readouterr().out
    assert "[0:00] Opponent: played [Card999 (Land)]" in out


def test_life_loss_on_opponent_turn_uses_current_turn(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 5
    tracker.game_state.active_player = 2
    tracker.game_state.last_player_turn_number = 4
    tracker.game_state.player_life = 20

    tracker._update_game_state({"players": [{"systemSeatNumber": 1, "lifeTotal": 19}]})
    out = capsys.readouterr().out

    assert "[0:00] You: lost 1 life (now 19)" in out
    assert "[Turn " not in out


def test_late_combat_life_change_on_turn_increment_stays_on_previous_turn(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 5
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 5
    tracker.game_state.last_player_turn_number = 5
    tracker.game_state.pending_opponent_turn_header = (6, 2)
    tracker.game_state.opponent_life = 20

    tracker._update_game_state(
        {
            "turnInfo": {"turnNumber": 6, "activePlayer": 2, "phase": "Phase_Main1"},
            "annotations": [
                {"type": ["AnnotationType_Damage"], "affectedIds": [901], "details": []}
            ],
            "players": [{"systemSeatNumber": 2, "lifeTotal": 15}],
        }
    )
    out = capsys.readouterr().out

    assert "[0:00] Opponent: lost 5 life (now 15)" in out
    assert "Turn 6 - OPPONENT'S TURN" not in out


def test_late_combat_life_loss_updates_damage_stats_without_damage_annotation(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 5
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 5
    tracker.game_state.last_player_turn_number = 5
    tracker.game_state.current_combat_attackers = {
        901: {
            "card_name": "Card901",
            "power": 4,
            "toughness": 4,
            "owner_seat": 1,
            "target": "opponent",
            "target_id": 2,
        }
    }
    tracker.game_state.opponent_life = 20

    tracker._update_game_state(
        {
            "turnInfo": {"turnNumber": 6, "activePlayer": 2, "phase": "Phase_Main1"},
            "players": [{"systemSeatNumber": 2, "lifeTotal": 16}],
        }
    )
    capsys.readouterr()

    assert tracker.game_state.match_stats[1]["total_damage"] == 4
    assert tracker.game_state.match_stats[2]["life_lost"] == 4


def test_opponent_life_trigger_flushes_pending_opponent_header(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 7
    tracker.game_state.pending_opponent_turn_header = (7, 2)
    tracker.game_state.opponent_life = 20

    tracker._update_game_state({"players": [{"systemSeatNumber": 2, "lifeTotal": 21}]})
    out = capsys.readouterr().out

    assert "Turn 7 - OPPONENT'S TURN" in out
    assert "[0:00] Opponent: gained 1 life (now 21)" in out


def test_turn_header_uses_life_totals_from_turn_start(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 13
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 13
    tracker.game_state.last_player_turn_number = 13
    tracker.game_state.player_life = 16
    tracker.game_state.opponent_life = 4

    tracker._update_game_state(
        {
            "turnInfo": {"turnNumber": 14, "activePlayer": 2, "phase": "Phase_Main1"},
            "players": [{"systemSeatNumber": 2, "lifeTotal": 2}],
        }
    )
    out = capsys.readouterr().out

    assert "Turn 14 - OPPONENT'S TURN" in out
    assert "Life: You 16 - 4 Opponent" in out
    assert "[0:00] Opponent: lost 2 life (now 2)" in out


def test_triggered_ability_on_new_active_turn_flushes_active_header(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 14
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 13
    tracker.game_state.last_player_turn_number = 13
    tracker.game_state.player_life = 16
    tracker.game_state.opponent_life = 4
    tracker.game_state.pending_opponent_turn_header = (14, 2, 16, 4)
    tracker.card_db.names[200] = "Bandit's Talent"
    tracker.card_db.ability_texts[(200, 900)] = (
        "At the beginning of each opponent's upkeep, if that player has one or fewer cards in hand, they lose 2 life."
    )
    game_objects_by_id = {
        100: {"instanceId": 100, "grpId": 200, "ownerSeatId": 1, "controllerSeatId": 1},
        500: {
            "instanceId": 500,
            "grpId": 900,
            "objectSourceGrpId": 200,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
        },
    }

    tracker._handle_ability_instance_created([500], 100, game_objects_by_id, set())
    out = capsys.readouterr().out

    assert "Turn 14 - OPPONENT'S TURN" in out
    assert "Life: You 16 - 4 Opponent" in out
    assert "You: [Bandit's Talent] - At the beginning of each opponent's upkeep" in out
    assert out.index("Turn 14 - OPPONENT'S TURN") < out.index("You: [Bandit's Talent]")
    assert tracker.game_state.stack_items[500]["turn"] == 14


def test_resolution_annotations_print_before_same_payload_life_change(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 14
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 14
    tracker.game_state.last_opponent_turn_number = 14
    tracker.game_state.player_life = 16
    tracker.game_state.opponent_life = 4
    tracker.card_db.names[200] = "Bandit's Talent"
    tracker.card_db.ability_texts[(200, 900)] = (
        "At the beginning of each opponent's upkeep, if that player has one or fewer cards in hand, they lose 2 life."
    )
    tracker.game_state.ability_instance_sources[500] = 100
    tracker._register_stack_item(
        500,
        seat_id=1,
        label="[Bandit's Talent] - At the beginning of each opponent's upkeep, if that player has one or fewer cards in hand, they lose 2 life.",
        kind="ability",
        turn_override=14,
    )
    tracker.game_state.stack_items[500]["show_lifecycle"] = True

    data = {
        "players": [{"systemSeatNumber": 2, "lifeTotal": 2}],
        "gameObjects": [{"instanceId": 100, "grpId": 200, "ownerSeatId": 1, "controllerSeatId": 1}],
        "annotations": [
            {
                "type": ["AnnotationType_ResolutionStart"],
                "affectedIds": [500],
                "details": [{"key": "grpid", "valueInt32": [900]}],
            }
        ],
    }

    tracker._update_game_state(data)
    tracker._process_game_events(data)
    out = capsys.readouterr().out

    assert "Stack: [Bandit's Talent]" in out
    assert "Opponent: lost 2 life (now 2)" in out
    assert out.index("Stack: [Bandit's Talent]") < out.index("Opponent: lost 2 life (now 2)")


def test_turn_header_life_line_aligns_without_icon(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.pending_player_turn_header = (1, 1)

    tracker._flush_pending_player_turn_header()
    out = capsys.readouterr().out

    assert "Life: You 20 - 20 Opponent" in out


def test_first_event_can_emit_missing_turn_one_banner(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 2
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 0
    tracker.game_state.last_opponent_turn_number = 0

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [3001],
        "details": [{"key": "category", "valueString": ["PlayLand"]}],
    }
    game_objects = [
        {
            "instanceId": 3001,
            "grpId": 999,
            "ownerSeatId": 2,
            "controllerSeatId": 2,
            "cardTypes": ["CardType_Land"],
        }
    ]

    tracker._process_annotation(annotation, game_objects)
    out = capsys.readouterr().out

    assert "Turn 1 - OPPONENT'S TURN" in out
    assert "[0:00] Opponent: played [Card999 (Land)]" in out


def test_process_annotation_counts_hidden_discard_from_zone_owner(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [901],
        "details": [
            {"key": "category", "valueString": ["Discard"]},
            {"key": "zone_src", "valueInt32": [11]},
            {"key": "zone_dest", "valueInt32": [12]},
        ],
    }
    zones_by_id = {
        11: {"zoneId": 11, "type": "ZoneType_Hand", "ownerSeatId": 2},
        12: {"zoneId": 12, "type": "ZoneType_Graveyard", "ownerSeatId": 2},
    }

    tracker._process_annotation(annotation, [], zones_by_id=zones_by_id)
    capsys.readouterr()

    assert tracker.game_state.match_stats[2]["cards_discarded"] == 1


def test_process_annotation_counts_hidden_mill_from_zone_owner(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [902],
        "details": [
            {"key": "category", "valueString": ["Mill"]},
            {"key": "zone_src", "valueInt32": [21]},
            {"key": "zone_dest", "valueInt32": [22]},
        ],
    }
    zones_by_id = {
        21: {"zoneId": 21, "type": "ZoneType_Library", "ownerSeatId": 2},
        22: {"zoneId": 22, "type": "ZoneType_Graveyard", "ownerSeatId": 2},
    }

    tracker._process_annotation(annotation, [], zones_by_id=zones_by_id)
    capsys.readouterr()

    assert tracker.game_state.match_stats[2]["cards_milled"] == 1


def test_console_output_is_persisted_to_sqlite(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "console.sqlite3"
    tracker.game_state.game_start_time = datetime.now()
    tracker.game_state.turn_number = 4
    tracker.game_state.active_player = 1
    tracker.game_state.player_life = 18
    tracker.game_state.opponent_life = 10

    tracker._print_event("[1:23] You: cast [Likeness Looter (Creature 1/1)]", "cast")
    out = capsys.readouterr().out

    assert "[1:23] You: cast [Likeness Looter (Creature 1/1)]" in out
    with sqlite3.connect(tracker._console_db_path) as conn:
        rows = conn.execute(
            """
            SELECT session_id, turn_number, active_player, style, text, player_life, opponent_life
            FROM console_logs
            """
        ).fetchall()

    assert rows == [
        (
            "test-session",
            4,
            1,
            "cast",
            "[1:23] You: cast [Likeness Looter (Creature 1/1)]",
            18,
            10,
        )
    ]


def test_unhandled_zone_transfer_category_logs_once_to_text(capsys, tmp_path):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker._diagnostic_text_path = tmp_path / "unhandled.log"

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [903],
        "details": [{"key": "category", "valueString": ["Prepare"]}],
    }
    game_objects = [{"instanceId": 903, "grpId": 7001, "ownerSeatId": 1, "controllerSeatId": 1}]

    tracker._process_annotation(annotation, game_objects)
    first = capsys.readouterr().out
    tracker._process_annotation(annotation, game_objects)
    second = capsys.readouterr().out

    assert first == ""
    assert second == ""

    text = tracker._diagnostic_text_path.read_text()
    assert text.count("Tracker: unhandled annotation") == 1
    assert (
        "AnnotationType_ZoneTransfer | category=Prepare | keys=category | affected=[Card7001]"
        in text
    )
    assert '"valueString": ["Prepare"]' in text


def test_routine_annotations_do_not_write_unhandled_diagnostics(capsys, tmp_path):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker._diagnostic_text_path = tmp_path / "unhandled.log"

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ManaPaid"],
            "affectedIds": [1001],
            "details": [
                {"key": "id", "valueInt32": [1]},
                {"key": "color", "valueInt32": [3]},
            ],
        },
        [{"instanceId": 1001, "grpId": 1001, "ownerSeatId": 1, "controllerSeatId": 1}],
    )
    out = capsys.readouterr().out

    assert out == ""
    assert not tracker._diagnostic_text_path.exists()


def test_reconcile_hidden_turn_draw_from_hand_size_after_play():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 3
    tracker.game_state.opening_hand_capture_closed = True
    tracker.game_state.last_hand_size_by_seat = {2: 3}

    tracker._process_game_events(
        {
            "zones": [
                {
                    "zoneId": 21,
                    "type": "ZoneType_Hand",
                    "ownerSeatId": 2,
                    "objectInstanceIds": [201, 202, 203],
                },
            ],
            "gameObjects": [
                {
                    "instanceId": 777,
                    "grpId": 777,
                    "ownerSeatId": 2,
                    "controllerSeatId": 2,
                    "cardTypes": ["CardType_Land"],
                },
            ],
            "annotations": [
                {
                    "type": ["AnnotationType_ZoneTransfer"],
                    "affectedIds": [777],
                    "details": [{"key": "category", "valueString": ["PlayLand"]}],
                }
            ],
        }
    )

    assert tracker.game_state.match_stats[2]["cards_drawn"] == 1


def test_known_hand_delta_ignores_unresolved_seat_when_opponent_unknown():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = None

    deltas = tracker._known_hand_delta_by_seat(
        {
            "zones": [
                {"zoneId": 10, "type": "ZoneType_Hand", "objectInstanceIds": [101, 102]},
                {"zoneId": 11, "type": "ZoneType_Battlefield", "objectInstanceIds": [777]},
            ],
            "annotations": [
                {
                    "type": ["AnnotationType_ZoneTransfer"],
                    "affectedIds": [777],
                    "details": [
                        {"key": "category", "valueString": ["CastSpell"]},
                        {"key": "zone_src", "valueInt32": [10]},
                        {"key": "zone_dest", "valueInt32": [11]},
                    ],
                }
            ],
        },
        {777: {"instanceId": 777, "grpId": 777, "ownerSeatId": None, "controllerSeatId": None}},
        {
            10: {"zoneId": 10, "type": "ZoneType_Hand", "ownerSeatId": None},
            11: {"zoneId": 11, "type": "ZoneType_Battlefield", "ownerSeatId": None},
        },
    )

    assert deltas == {}


def test_first_event_without_turninfo_uses_turn_one_banner(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.last_turn_announced = 0
    tracker.game_state.last_player_turn_number = 0
    tracker.game_state.last_opponent_turn_number = 0

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [1001],
        "details": [{"key": "category", "valueString": ["PlayLand"]}],
    }
    game_objects = [
        {
            "instanceId": 1001,
            "grpId": 1010,
            "ownerSeatId": 1,
            "controllerSeatId": 1,
            "cardTypes": ["CardType_Land"],
        }
    ]

    tracker._process_annotation(annotation, game_objects)
    out = capsys.readouterr().out

    assert "Turn 1 - YOUR TURN" in out
    assert "[0:00] You: played [Card1010 (Land)]" in out


def test_turn_headers_wait_until_seats_known(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True

    # Turn info arrives before we know player/opponent seats.
    tracker._update_game_state(
        {"turnInfo": {"turnNumber": 1, "activePlayer": 2, "phase": "Phase_Main1"}}
    )
    early_out = capsys.readouterr().out
    assert early_out == ""
    assert tracker.game_state.last_turn_announced == 0

    # Seats become known, next turn is the first one we can safely label.
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker._update_game_state(
        {"turnInfo": {"turnNumber": 2, "activePlayer": 1, "phase": "Phase_Main1"}}
    )
    out = capsys.readouterr().out

    assert "First observed turn is" not in out
    assert out == ""


def test_block_is_not_reported_twice_across_block_sources(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 7

    game_objects_by_id = {
        30: {
            "instanceId": 30,
            "grpId": 303,
            "ownerSeatId": 1,
            "power": {"value": 1},
            "toughness": {"value": 3},
        },
        40: {"instanceId": 40, "grpId": 404, "ownerSeatId": 2},
    }

    tracker._handle_blockers_request(
        [{"blockerInstanceId": 30, "attackerInstanceIds": [40]}],
        game_objects_by_id,
    )
    first = capsys.readouterr().out
    assert "blocking [Card404] with [Card303 (1/3)]" in first

    annotation = {"details": [{"key": "attacker_id", "valueInt32": [40]}]}
    tracker._handle_blocker_declared([30], annotation, list(game_objects_by_id.values()))
    second = capsys.readouterr().out
    assert second == ""


def test_blockers_request_uses_object_snapshot_fallback(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 8

    tracker.game_state.object_snapshots[30] = {
        "instanceId": 30,
        "grpId": 303,
        "ownerSeatId": 1,
        "power": {"value": 2},
        "toughness": {"value": 2},
    }
    tracker.game_state.object_snapshots[40] = {"instanceId": 40, "grpId": 404, "ownerSeatId": 2}

    tracker._handle_blockers_request(
        [{"blockerInstanceId": 30, "attackerInstanceIds": [40]}],
        {},
    )
    out = capsys.readouterr().out
    assert "blocking [Card404] with [Card303 (2/2)]" in out


def test_snapshot_logs_identity_change_for_copy_state(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.last_turn_announced = 5
    tracker.game_state.last_player_turn_number = 5
    tracker.card_db.names.update(
        {
            6001: "Likeness Looter",
            6002: "Abhorrent Oculus",
        }
    )
    tracker.game_state.object_snapshots[55] = {
        "instanceId": 55,
        "grpId": 6001,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Artifact", "CardType_Creature"],
        "power": {"value": 1},
        "toughness": {"value": 1},
    }

    tracker._snapshot_game_objects(
        [
            {
                "instanceId": 55,
                "grpId": 6002,
                "ownerSeatId": 1,
                "controllerSeatId": 1,
                "cardTypes": ["CardType_Creature"],
                "power": {"value": 5},
                "toughness": {"value": 5},
            }
        ]
    )
    out = capsys.readouterr().out

    assert "[0:00] You: [Likeness Looter] became [Abhorrent Oculus] (5/5)" in out


def test_highest_known_creature_snapshot_reads_large_stats():
    tracker = make_tracker()
    tracker.game_state.object_snapshots[382] = {
        "instanceId": 382,
        "grpId": 93820,
        "ownerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 56},
        "toughness": {"value": 56},
    }

    top = tracker._highest_known_creature_snapshot()
    assert top is not None
    assert top["name"] == "Card93820"
    assert top["power"] == 56
    assert top["toughness"] == 56


def test_highest_known_creature_snapshot_can_filter_by_seat():
    tracker = make_tracker()
    tracker.game_state.object_snapshots[100] = {
        "instanceId": 100,
        "grpId": 111,
        "ownerSeatId": 1,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 10},
        "toughness": {"value": 10},
    }
    tracker.game_state.object_snapshots[200] = {
        "instanceId": 200,
        "grpId": 222,
        "ownerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 56},
        "toughness": {"value": 56},
    }

    top_player = tracker._highest_known_creature_snapshot(1)
    top_opponent = tracker._highest_known_creature_snapshot(2)

    assert top_player is not None
    assert top_player["name"] == "Card111"
    assert top_player["power"] == 10
    assert top_opponent is not None
    assert top_opponent["name"] == "Card222"
    assert top_opponent["power"] == 56


def test_parse_match_metadata_does_not_pick_deck_without_format_hint():
    tracker = make_tracker()
    line = json.dumps(
        {
            "InventoryInfo": {
                "Courses": [
                    {
                        "InternalEventName": "Play",
                        "CurrentModule": "Complete",
                        "CourseDeckSummary": {
                            "DeckId": "old-deck",
                            "Name": "?=?Loc/Decks/Precon/CC_ANB_W",
                            "Attributes": [{"name": "Format", "value": "Standard"}],
                        },
                    },
                    {
                        "InternalEventName": "MWM_3Sets_20260310",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "mwm-deck",
                            "Name": "MWM Landfall",
                            "Attributes": [
                                {"name": "Format", "value": "3Sets"},
                                {
                                    "name": "LastPlayed",
                                    "value": '"2026-03-10T22:39:18.07558-04:00"',
                                },
                            ],
                        },
                    },
                ]
            }
        }
    )

    tracker._parse_match_metadata(line)

    assert tracker.game_state.player_deck_name is None
    assert tracker.game_state.player_deck_id is None


def test_parse_match_metadata_tolerates_mixed_last_played_timezone_offsets():
    tracker = make_tracker()
    line = json.dumps(
        {
            "InventoryInfo": {
                "Courses": [
                    {
                        "InternalEventName": "Play",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "deck-1",
                            "Name": "Current Deck",
                            "Attributes": [
                                {"name": "Format", "value": "Standard"},
                                {"name": "LastPlayed", "value": '"2026-03-10T22:39:18"'},
                            ],
                        },
                    },
                    {
                        "InternalEventName": "Play",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "deck-1",
                            "Name": "Current Deck",
                            "Attributes": [
                                {"name": "Format", "value": "Standard"},
                                {
                                    "name": "LastPlayed",
                                    "value": '"2026-03-10T22:40:18.07558-04:00"',
                                },
                            ],
                        },
                    },
                ]
            }
        }
    )

    tracker._parse_match_metadata(line)

    assert tracker._deck_candidates["deck-1"]["last_played"].tzinfo is None


def test_candidate_score_ignores_ancient_last_played_sentinel():
    tracker = make_tracker()
    candidate = {
        "deck_name": "Current Deck",
        "last_played": datetime.min,
        "last_seen": datetime.min,
    }

    assert tracker._candidate_score(candidate, "Standard") == (3, 0.0, 0.0)


def test_parse_attr_timestamp_ignores_ancient_last_played_sentinel():
    assert CardTracker._parse_attr_timestamp('"0001-01-01T00:00:00"') is None


def test_parse_match_metadata_uses_format_hint_to_pick_matching_deck():
    tracker = make_tracker()
    courses_line = json.dumps(
        {
            "InventoryInfo": {
                "Courses": [
                    {
                        "InternalEventName": "Play",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "play-deck",
                            "Name": "Mono-Black Demons",
                            "Attributes": [{"name": "Format", "value": "Standard"}],
                        },
                    },
                    {
                        "InternalEventName": "MWM_3Sets_20260310",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "mwm-deck",
                            "Name": "MWM Landfall",
                            "Attributes": [{"name": "Format", "value": "3Sets"}],
                        },
                    },
                ]
            }
        }
    )
    tracker._parse_match_metadata(courses_line)
    assert tracker.game_state.player_deck_name is None

    format_line = json.dumps(
        {
            "matchGameRoomStateChangedEvent": {
                "gameRoomInfo": {"gameRoomConfig": {"eventType": "MWM_3Sets_20260310"}}
            }
        }
    )
    tracker._parse_match_metadata(format_line)

    assert tracker.game_state.format_str == "MWM_3Sets_20260310"
    assert tracker.game_state.player_deck_name == "MWM Landfall"
    assert tracker.game_state.player_deck_id == "mwm-deck"


def test_match_room_reserved_player_event_id_replaces_stale_brawl_format():
    tracker = make_tracker()
    tracker.game_state.format_str = "HistoricBrawl"
    tracker.game_state.match_type = "best_of_1"
    tracker.game_state.player_seat_id = 1

    tracker._parse_match_metadata(
        json.dumps(
            {
                "matchGameRoomStateChangedEvent": {
                    "gameRoomInfo": {
                        "gameRoomConfig": {
                            "matchId": "active-match",
                            "reservedPlayers": [
                                {
                                    "systemSeatId": 1,
                                    "playerName": "Tapps",
                                    "eventId": "MWM_StarStandard_20260512",
                                },
                                {
                                    "systemSeatId": 2,
                                    "playerName": "Opponent",
                                    "eventId": "MWM_StarStandard_20260512",
                                },
                            ],
                        }
                    }
                }
            }
        )
    )

    assert tracker.game_state.format_str == "MWM_StarStandard_20260512"
    assert tracker._friendly_format_label() == "Midweek Magic - Star Standard"
    assert not tracker._is_brawl_format()


def test_match_room_reserved_players_resolve_seats_from_local_player_name_with_unicode_opponent():
    tracker = make_tracker()
    tracker.game_state.player_display_name = "Tapps"

    tracker._parse_match_metadata(
        json.dumps(
            {
                "matchGameRoomStateChangedEvent": {
                    "gameRoomInfo": {
                        "gameRoomConfig": {
                            "matchId": "active-match",
                            "reservedPlayers": [
                                {
                                    "systemSeatId": 1,
                                    "playerName": "みんと",
                                    "eventId": "Play",
                                },
                                {
                                    "systemSeatId": 2,
                                    "playerName": "Tapps",
                                    "eventId": "Play",
                                },
                            ],
                        }
                    }
                }
            }
        )
    )

    assert tracker.game_state.player_seat_id == 2
    assert tracker.game_state.opponent_seat_id == 1
    assert tracker.game_state.player_display_name == "Tapps"
    assert tracker.game_state.opponent_display_name == "みんと"


def test_match_room_reserved_players_correct_stale_seat_assignment():
    tracker = make_tracker()
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "PreviousOpponent"
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._parse_match_metadata(
        json.dumps(
            {
                "matchGameRoomStateChangedEvent": {
                    "gameRoomInfo": {
                        "gameRoomConfig": {
                            "matchId": "active-match",
                            "reservedPlayers": [
                                {
                                    "systemSeatId": 1,
                                    "playerName": "Raveneye4599",
                                    "eventId": "Play",
                                },
                                {
                                    "systemSeatId": 2,
                                    "playerName": "Tapps",
                                    "eventId": "Play",
                                },
                            ],
                        }
                    }
                }
            }
        )
    )

    assert tracker.game_state.player_seat_id == 2
    assert tracker.game_state.opponent_seat_id == 1
    assert tracker.game_state.player_display_name == "Tapps"
    assert tracker.game_state.opponent_display_name == "Raveneye4599"


def test_match_room_traditional_standard_sets_best_of_three_format():
    tracker = make_tracker()
    tracker._parse_match_metadata(
        json.dumps(
            {
                "matchGameRoomStateChangedEvent": {
                    "gameRoomInfo": {"gameRoomConfig": {"eventType": "TraditionalStandard"}}
                }
            }
        )
    )

    assert tracker.game_state.format_str == "TraditionalStandard"
    assert tracker.game_state.match_type == "best_of_3"
    assert tracker._friendly_format_label() == "Standard Best-of-3 (Unranked)"


def test_game_start_does_not_use_stale_backfilled_traditional_format(tmp_path, capsys):
    tracker = make_tracker()
    log_path = tmp_path / "Player.log"
    tracker.parser.log_path = str(log_path)
    log_path.write_text(
        "\n".join(
            [
                json.dumps({"gameInfo": {"matchState": "MatchState_GameComplete"}}),
                json.dumps(
                    {
                        "matchGameRoomStateChangedEvent": {
                            "gameRoomInfo": {
                                "gameRoomConfig": {
                                    "eventType": "TraditionalStandard",
                                    "reservedPlayers": [],
                                }
                            }
                        }
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    tracker._backfill_recent_match_metadata()
    assert tracker.game_state.match_type == "best_of_3"

    tracker._check_game_start(json.dumps({"gameInfo": {"mulliganType": "MulliganType_London"}}))

    out = capsys.readouterr().out
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker.game_state.format_str == "Unknown"
    assert "Format: Unknown" in out
    assert "Format: Standard Best-of-3" not in out


def test_game_started_banner_uses_friendly_midweek_format(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 6, 16, 19, 31, 0)
    tracker.game_state.format_str = "MWM_SOS_Sealed_20260616"
    tracker.game_state.match_type = "best_of_1"

    tracker._print_game_started_banner(verbose=False)
    out = capsys.readouterr().out

    assert "GAME STARTED - Midweek Magic - SOS Sealed" in out
    assert "Format: Midweek Magic - SOS Sealed" in out
    assert "Standard Best-of-1" not in out


def test_premier_draft_format_gets_friendly_label():
    tracker = make_tracker()
    tracker.game_state.format_str = "PremierDraft_MSH_20260623"

    assert tracker._friendly_format_label() == "Premier Draft - MSH"


def test_result_summary_prints_format_above_duration(capsys):
    tracker = make_tracker()
    tracker.game_state.format_str = "PremierDraft_MSH_20260623"

    tracker._print_result_summary("win", "Opponent reached 0 life", "12m 13s")
    out = capsys.readouterr().out

    assert "Format: Premier Draft - MSH\nDuration: 12m 13s" in out


def test_deck_metadata_traditional_standard_does_not_set_match_best_of_three_without_live_format():
    tracker = make_tracker()
    tracker._parse_match_metadata(
        json.dumps(
            {
                "Courses": [
                    {
                        "InternalEventName": "Play",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "deck-1",
                            "Name": "Standard Deck",
                            "Attributes": [{"name": "Format", "value": "TraditionalStandard"}],
                        },
                        "CourseDeck": {
                            "MainDeck": [
                                {"cardId": 1001, "quantity": 4},
                                {"cardId": 1002, "quantity": 4},
                            ],
                            "CommandZone": [],
                        },
                    }
                ]
            }
        )
    )

    resolved = tracker._resolve_player_deck_from_hand_ids(
        [1001, 1002, 1003, 1004, 1005, 1006, 1007]
    )

    assert resolved is True
    assert tracker.game_state.player_deck_name == "Standard Deck"
    assert tracker.game_state.format_str == "Unknown"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker._friendly_format_label() == "Unknown"


def test_explicit_traditional_standard_deck_event_does_not_set_best_of_three_without_live_format():
    tracker = make_tracker()
    tracker._parse_match_metadata(
        "[UnityCrossThreadLogger]<== EventSetDeckV2 "
        '{"CourseId":"703c87ae","InternalEventName":"Play","CurrentModule":"CreateMatch",'
        '"CourseDeckSummary":{"DeckId":"deck-1","Name":"Standard Deck",'
        '"Attributes":[{"name":"Format","value":"TraditionalStandard"}]},'
        '"CourseDeck":{"MainDeck":[{"cardId":1001,"quantity":4}],"CommandZone":[]}}'
    )

    assert tracker.game_state.player_deck_name == "Standard Deck"
    assert tracker.game_state.format_str == "Unknown"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker._friendly_format_label() == "Unknown"


def test_parse_match_metadata_sets_player_commander_from_command_zone():
    tracker = make_tracker()
    line = json.dumps(
        {
            "InventoryInfo": {
                "Courses": [
                    {
                        "InternalEventName": "Historic_Brawl",
                        "CurrentModule": "CreateMatch",
                        "CourseDeckSummary": {
                            "DeckId": "brawl-deck",
                            "Name": "Brawl Deck",
                            "Attributes": [{"name": "Format", "value": "HistoricBrawl"}],
                        },
                        "CourseDeck": {
                            "MainDeck": [{"cardId": 2001, "quantity": 1}],
                            "CommandZone": [{"cardId": 7777, "quantity": 1}],
                        },
                    }
                ]
            }
        }
    )

    tracker._parse_match_metadata(line)
    tracker.game_state.format_str = "Historic_Brawl"
    tracker._resolve_player_deck_from_candidates()

    assert tracker.game_state.player_deck_name == "Brawl Deck"
    assert tracker.game_state.player_commanders == ["Card7777"]
    assert tracker.game_state.player_deck_total_cards == 2


def test_update_game_state_captures_observed_starting_deck_totals():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._update_game_state(
        {
            "zones": [
                {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": list(range(1, 8))},
                {
                    "type": "ZoneType_Library",
                    "ownerSeatId": 1,
                    "objectInstanceIds": list(range(100, 153)),
                },
                {
                    "type": "ZoneType_Hand",
                    "ownerSeatId": 2,
                    "objectInstanceIds": list(range(200, 207)),
                },
                {
                    "type": "ZoneType_Library",
                    "ownerSeatId": 2,
                    "objectInstanceIds": list(range(300, 353)),
                },
            ],
        }
    )

    assert tracker.game_state.observed_starting_deck_total_by_seat == {1: 60, 2: 60}


def test_match_started_block_hides_unknown_opponent_and_deck(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.player_deck_name = "MWM Landfall"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Players:" not in out
    assert "Deck Name:" not in out


def test_match_started_block_omits_seat_line_when_unknown(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Standard Best-of-1"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Seat:" not in out


def test_match_started_block_prints_players_when_opponent_known(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Rival123"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Players: Tapps vs Rival123" in out


def test_match_started_block_marks_sparky_games_not_saved(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 7, 4, 0, 28, 38)
    tracker.game_state.format_str = "AIBotMatch_Rebalanced"
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Sparky"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Players: Tapps vs Sparky (Log Not Saved to DB)" in out


def test_match_started_block_marks_momir_games_not_saved(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 7, 15, 22, 51, 32)
    tracker.game_state.format_str = "MWM_Momir"
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Rival123"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Format: Midweek Magic - Momir" in out
    assert "Players: Tapps vs Rival123 (Log Not Saved to DB)" in out


def test_active_momir_match_room_survives_game_start_reset(tmp_path):
    tracker = make_tracker()
    log_path = tmp_path / "Player.log"
    tracker.parser.log_path = str(log_path)
    room_line = json.dumps(
        {
            "matchGameRoomStateChangedEvent": {
                "gameRoomInfo": {
                    "stateType": "MatchGameRoomStateType_Playing",
                    "gameRoomConfig": {
                        "matchId": "momir-match",
                        "reservedPlayers": [
                            {"systemSeatId": 1, "eventId": "MWM_Momir"},
                            {"systemSeatId": 2, "eventId": "MWM_Momir"},
                        ],
                    },
                }
            }
        }
    )
    log_path.write_text(room_line, encoding="utf-8")

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)

    assert tracker.game_state.format_str == "MWM_Momir"
    assert tracker._is_untracked_match()


def test_live_queue_format_wins_over_stale_backfilled_momir_context(tmp_path):
    tracker = make_tracker()
    log_path = tmp_path / "Player.log"
    tracker.parser.log_path = str(log_path)
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "fromSceneName": "Home",
                        "toSceneName": "EventLanding",
                        "context": "MWM_Momir",
                    }
                ),
                json.dumps(
                    {
                        "matchGameRoomStateChangedEvent": {
                            "gameRoomInfo": {
                                "stateType": "MatchGameRoomStateType_Playing",
                                "gameRoomConfig": {
                                    "matchId": "play-match",
                                    "reservedPlayers": [
                                        {"systemSeatId": 1, "eventId": "Play"},
                                        {"systemSeatId": 2, "eventId": "Play"},
                                    ],
                                },
                            }
                        }
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    tracker._pending_event_format = "MWM_Momir"

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)

    assert tracker.game_state.format_str == "Play"
    assert not tracker._is_untracked_match()


def test_each_game_rechecks_latest_active_match_room(tmp_path):
    tracker = make_tracker()
    log_path = tmp_path / "Player.log"
    tracker.parser.log_path = str(log_path)

    def room_line(state_type, match_id, event_id):
        return json.dumps(
            {
                "matchGameRoomStateChangedEvent": {
                    "gameRoomInfo": {
                        "stateType": state_type,
                        "gameRoomConfig": {
                            "matchId": match_id,
                            "reservedPlayers": [
                                {"systemSeatId": 1, "eventId": event_id},
                                {"systemSeatId": 2, "eventId": event_id},
                            ],
                        },
                    }
                }
            }
        )

    log_path.write_text(
        room_line("MatchGameRoomStateType_Playing", "first-match", "MWM_Momir"),
        encoding="utf-8",
    )
    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)
    assert tracker.game_state.format_str == "MWM_Momir"

    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            "\n"
            + room_line(
                "MatchGameRoomStateType_MatchCompleted", "first-match", "MWM_Momir"
            )
        )
        f.write("\n" + room_line("MatchGameRoomStateType_Playing", "second-match", "Play"))

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)
    assert tracker.game_state.format_str == "Play"


def test_returning_home_clears_stale_midweek_event_format(tmp_path):
    tracker = make_tracker()
    log_path = tmp_path / "Player.log"
    tracker.parser.log_path = str(log_path)
    scene_lines = [
        json.dumps(
            {
                "fromSceneName": "Home",
                "toSceneName": "EventLanding",
                "context": "MWM_BrawlBuilder",
            }
        ),
        json.dumps(
            {
                "fromSceneName": "EventLanding",
                "toSceneName": "Home",
                "context": "Landing Page 'Home'",
            }
        ),
    ]
    log_path.write_text("\n".join(scene_lines), encoding="utf-8")

    for scene_line in scene_lines:
        tracker._parse_match_metadata(scene_line)
    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)

    assert tracker.game_state.format_str == "Unknown"
    assert tracker._friendly_format_label() == "Unknown"
    assert tracker._pending_event_format is None


def test_momir_game_summary_is_not_persisted_or_counted(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 7, 15, 22, 43, 18)
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.game_start_time = datetime(2026, 7, 15, 22, 51, 32)
    tracker.game_state.game_end_time = datetime(2026, 7, 15, 23, 0, 24)
    tracker.game_state.winner_seat = 2
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Rival123"
    tracker.game_state.format_str = "MWM_Momir"

    tracker._print_game_summary()
    capsys.readouterr()

    assert tracker.session_games_played == 0
    assert tracker.session_losses == 0
    assert not tracker._console_db_path.exists()


def test_match_started_block_prints_commanders_when_known(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Historic Brawl"
    tracker.game_state.player_commanders = ["Card100471"]
    tracker.game_state.opponent_commanders = ["Card100610"]

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Your Commander: Card100471" in out
    assert "Opponent Commander: Card100610" in out


def test_match_started_block_formats_historic_brawl_label(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "HistoricBrawl"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Format: Historic Brawl" in out


def test_game_state_reset_clears_previous_deck_name():
    state = GameState()
    state.player_deck_name = "MWM Landfall"
    state.player_deck_id = "old-id"
    state.format_str = "Historic Brawl"
    state.reset()

    assert state.player_deck_name is None
    assert state.player_deck_id is None
    assert state.format_str == "Unknown"


def test_resolve_player_deck_fallback_uses_best_available_candidate():
    tracker = make_tracker()
    tracker._deck_candidates = {
        "candidate-a": {
            "deck_id": "old",
            "deck_name": "Old Deck",
            "current_module": "Collection",
            "internal_event_name": "Play",
        },
        "candidate-b": {
            "deck_id": "mwm",
            "deck_name": "MWM Landfall",
            "current_module": "CreateMatch",
            "internal_event_name": "Play",
        },
    }

    changed = tracker._resolve_player_deck_fallback()

    assert changed is True
    assert tracker.game_state.player_deck_name == "MWM Landfall"
    assert tracker.game_state.player_deck_id == "mwm"


def test_exile_counter_tracks_player_cards_exiled_by_opponent(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.active_player = 2

    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [901],
        "details": [{"key": "category", "valueString": ["Exile"]}],
    }
    game_objects = [{"instanceId": 901, "grpId": 500, "ownerSeatId": 1}]

    tracker._process_annotation(annotation, game_objects)
    out = capsys.readouterr().out

    assert "[Card500] was exiled" in out
    assert tracker.game_state.player_cards_exiled == 1
    assert tracker.game_state.player_cards_exiled_by_opponent == 1


def test_summary_includes_mulligan_and_exile_totals(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_deck_name = "Izzet Artifacts (Carlo TMNT)"
    tracker.game_state.mulligan_count = 2
    tracker.game_state.starting_hand = [
        "Island",
        "Mountain",
        "Lightning Strike",
        "Steam Vents",
        "Opt",
    ]
    tracker.game_state.starting_hand_events = [
        CardEvent("Island", "player", card_type_category="Land"),
        CardEvent("Mountain", "player", card_type_category="Land"),
        CardEvent("Lightning Strike", "player", card_type_category="Instant"),
        CardEvent("Steam Vents", "player", card_type_category="Land"),
        CardEvent("Opt", "player", card_type_category="Instant"),
    ]
    tracker.game_state.player_cards_exiled = 3
    tracker.game_state.player_cards_exiled_by_opponent = 2
    tracker.game_state.opponent_cards_exiled_by_player = 4

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "STARTING HAND (5 CARDS - AFTER 2 MULLIGAN(S))" in out
    assert "• [Lightning Strike]" in out
    assert "Your Deck: Izzet Artifacts (Carlo TMNT)" in out
    assert "Mulligans: 2" in out
    assert "CARDS EXILED" in out
    assert "By Me: 4" in out
    assert "By Opponent: 2" in out


def test_summary_includes_commanders(capsys):
    tracker = make_tracker()
    tracker.game_state.format_str = "Historic Brawl"
    tracker.game_state.player_commanders = ["Card100471"]
    tracker.game_state.opponent_commanders = ["Card100610"]

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "Your Commander: Card100471" in out
    assert "Opponent Commander: Card100610" in out


def test_summary_refreshes_fallback_card_ids_from_local_db(capsys):
    tracker = make_tracker()
    tracker.game_state.format_str = "Historic Brawl"
    tracker.game_state.player_deck_name = "Tifa - MWM"
    tracker.game_state.player_seat_id = 2
    tracker.game_state.opponent_seat_id = 1
    tracker.game_state.player_commanders = ["Card #96074"]
    tracker.game_state.opponent_commanders = ["Card #93935"]
    tracker.card_db.names.update(
        {
            82394: "Forest",
            54163: "Elvish Mystic",
            93935: "Ghalta, Primal Hunger",
            96074: "Tifa Lockhart",
        }
    )
    tracker.player_cards = [
        CardEvent("Card #82394 (Land)", "you", card_type_category="lands"),
        CardEvent("Card #54163 (Creature 1/1)", "you", card_type_category="creatures"),
    ]
    tracker.opponent_cards = [
        CardEvent("Card #93935 (Creature 12/12)", "opponent", card_type_category="creatures"),
    ]
    tracker.game_state.object_snapshots = {
        9001: {
            "instanceId": 9001,
            "grpId": 93935,
            "cardTypes": ["CardType_Creature"],
            "power": {"value": 12},
            "toughness": {"value": 12},
            "ownerSeatId": 1,
        }
    }

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "Your Commander: Tifa Lockhart" in out
    assert "Opponent Commander: Ghalta, Primal Hunger" in out
    assert "• [Forest (Land)]" in out
    assert "• [Elvish Mystic (Creature 1/1)]" in out
    assert "Biggest Creature: [Ghalta, Primal Hunger] reached 12/12" in out


def test_match_started_block_hides_commanders_for_standard_even_if_stale(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_commanders = ["Card2"]
    tracker.game_state.opponent_commanders = ["Card2"]

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Your Commander:" not in out
    assert "Opponent Commander:" not in out


def test_highest_observed_creature_uses_battlefield_stats_not_library_printed_stats():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1

    tracker._update_game_state(
        {
            "zones": [
                {
                    "zoneId": 28,
                    "type": "ZoneType_Battlefield",
                    "objectInstanceIds": [373],
                },
                {
                    "zoneId": 32,
                    "type": "ZoneType_Library",
                    "ownerSeatId": 1,
                    "objectInstanceIds": [240],
                },
            ],
            "gameObjects": [
                {
                    "instanceId": 240,
                    "grpId": 98430,
                    "zoneId": 32,
                    "ownerSeatId": 1,
                    "cardTypes": ["CardType_Creature"],
                    "power": {"value": 7},
                    "toughness": {"value": 7},
                },
                {
                    "instanceId": 373,
                    "grpId": 98430,
                    "zoneId": 28,
                    "ownerSeatId": 1,
                    "cardTypes": ["CardType_Creature"],
                    "power": {"value": 3},
                    "toughness": {"value": 3},
                },
            ],
        }
    )

    best = tracker._highest_known_creature_snapshot(1)

    assert best is not None
    assert best["name"] == "Card98430"
    assert best["power"] == 3
    assert best["toughness"] == 3


def test_biggest_creature_summary_uses_large_attack_state_stats(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.active_player = 1
    tracker.game_state.turn_number = 4
    tracker.card_db.names[1001] = "Mossborn Hydra"
    tracker.player_cards = [CardEvent("Mossborn Hydra", "you", card_type_category="creatures")]
    tracker.game_state.highest_creature_by_seat[1] = {
        "instance_id": 700,
        "name": "Mossborn Hydra",
        "power": 10,
        "toughness": 10,
        "owner_seat": 1,
        "score": 10,
    }

    tracker._handle_attack_state_objects(
        [
            {
                "instanceId": 700,
                "grpId": 1001,
                "ownerSeatId": 1,
                "cardTypes": ["CardType_Creature"],
                "attackState": "AttackState_Attacking",
                "power": {"value": 46},
                "toughness": {"value": 46},
                "attackInfo": {"targetId": 2},
            }
        ]
    )
    tracker._print_card_collection_summary(
        tracker.player_cards, heading="Your Cards", seat_id=tracker.game_state.player_seat_id
    )
    out = capsys.readouterr().out

    assert "You attacking [opponent] with [Mossborn Hydra (46/46)]" in out
    assert "Biggest Creature: [Mossborn Hydra] reached 46/46" in out
    assert "Highest observed creature:" not in out


def test_summary_hides_commanders_for_standard_even_if_stale(capsys):
    tracker = make_tracker()
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_commanders = ["Nahiri, Storm of Stone"]
    tracker.game_state.opponent_commanders = ["Card2"]

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "Your Commander:" not in out
    assert "Opponent Commander:" not in out


def test_emit_life_change_suppresses_consecutive_duplicates(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 4

    tracker._emit_life_change(2, -2, 18)
    tracker._emit_life_change(2, -2, 18)
    tracker._emit_life_change(1, 4, 22)

    out = capsys.readouterr().out

    assert out.count("[0:00] Opponent: lost 2 life (now 18)") == 1
    assert out.count("[0:00] You: gained 4 life (now 22)") == 1


def test_capture_opening_hand_detects_mulligan_when_seat_unknown():
    tracker = make_tracker()
    tracker.game_state.in_match = True

    data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 2},
        "players": [{"systemSeatNumber": 1}, {"systemSeatNumber": 2}],
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [11, 12, 13, 14, 15, 16],
            },
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 2,
                "objectInstanceIds": [21, 22, 23, 24, 25, 26, 27],
            },
        ],
        "gameObjects": [
            {"instanceId": 11, "grpId": 1001},
            {"instanceId": 12, "grpId": 1002},
            {"instanceId": 13, "grpId": 1003},
            {"instanceId": 14, "grpId": 1004},
            {"instanceId": 15, "grpId": 1005},
            {"instanceId": 16, "grpId": 1006},
        ],
    }

    tracker._capture_opening_hand(data)

    assert tracker.game_state.player_seat_id == 1
    assert tracker.game_state.opponent_seat_id == 2
    assert tracker.game_state.mulligan_count == 1
    assert len(tracker.game_state.starting_hand) == 6


def test_capture_opening_hand_prints_seat_line_when_detected(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)

    data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 2},
        "players": [{"systemSeatNumber": 1}, {"systemSeatNumber": 2}],
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [11, 12, 13, 14, 15, 16],
            },
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 2,
                "objectInstanceIds": [21, 22, 23, 24, 25, 26, 27],
            },
        ],
        "gameObjects": [
            {"instanceId": 11, "grpId": 1001},
            {"instanceId": 12, "grpId": 1002},
            {"instanceId": 13, "grpId": 1003},
            {"instanceId": 14, "grpId": 1004},
            {"instanceId": 15, "grpId": 1005},
            {"instanceId": 16, "grpId": 1006},
        ],
    }

    tracker._capture_opening_hand(data)
    first = capsys.readouterr().out
    tracker._capture_opening_hand(data)
    second = capsys.readouterr().out

    assert "Seat: 1" in first
    assert "Seat: 1" not in second


def test_check_game_start_requires_fresh_turn_one_after_previous_summary():
    tracker = make_tracker()
    tracker._require_explicit_game_start = True

    tracker._check_game_start(
        json.dumps({"gameStateMessage": {"turnInfo": {"turnNumber": 2, "activePlayer": 1}}})
    )

    assert tracker.game_state.in_match is False


def test_backfill_recent_match_metadata_ignores_lines_before_last_match_end(tmp_path):
    tracker = make_tracker()
    tracker.parser.log_path = str(tmp_path / "Player.log")
    tracker.game_state.player_display_name = "Tapps"
    tracker._metadata_backfilled = False

    tracker.parser.log_path and (tmp_path / "Player.log").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "matchGameRoomStateChangedEvent": {
                            "gameRoomInfo": {
                                "gameRoomConfig": {
                                    "eventType": "HistoricBrawl",
                                    "reservedPlayers": [],
                                }
                            }
                        }
                    }
                ),
                json.dumps(
                    {
                        "Courses": [
                            {
                                "InternalEventName": "HistoricBrawl",
                                "CurrentModule": "CreateMatch",
                                "CourseDeckSummary": {
                                    "DeckId": "old-brawl",
                                    "Name": "achievement deck",
                                    "Attributes": [{"name": "Format", "value": "HistoricBrawl"}],
                                },
                                "CourseDeck": {"CommandZone": [{"cardId": 7777}]},
                            }
                        ]
                    }
                ),
                json.dumps({"gameInfo": {"matchState": "MatchState_GameComplete"}}),
                json.dumps(
                    {
                        "matchGameRoomStateChangedEvent": {
                            "gameRoomInfo": {
                                "gameRoomConfig": {
                                    "eventType": "Standard",
                                    "reservedPlayers": [],
                                }
                            }
                        }
                    }
                ),
                json.dumps(
                    {
                        "Courses": [
                            {
                                "InternalEventName": "Play",
                                "CurrentModule": "CreateMatch",
                                "CourseDeckSummary": {
                                    "DeckId": "std-1",
                                    "Name": "Niv-Mizzet (Malone)",
                                    "Attributes": [{"name": "Format", "value": "Standard"}],
                                },
                            }
                        ]
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    tracker._backfill_recent_match_metadata(force=True)
    tracker._resolve_player_deck_from_candidates()

    assert tracker.game_state.format_str == "Standard"
    assert tracker.game_state.player_deck_name == "Niv-Mizzet (Malone)"


def test_parse_match_metadata_prefers_explicit_set_deck_event():
    tracker = make_tracker()
    tracker.game_state.player_commanders = ["Nahiri, Storm of Stone"]
    tracker._parse_match_metadata(
        '[UnityCrossThreadLogger]<== EventSetDeckV2 {"CourseId":"703c87ae","InternalEventName":"Play","CurrentModule":"CreateMatch","CourseDeckSummary":{"DeckId":"16225358-69d8-45c8-875a-726e19b02004","Name":"Niv-Mizzet (Malone)","Attributes":[{"name":"Format","value":"Standard"}]},"CourseDeck":{"MainDeck":[{"cardId":87237,"quantity":4},{"cardId":100546,"quantity":4}],"CommandZone":[]}}'
    )

    assert tracker.game_state.player_deck_name == "Niv-Mizzet (Malone)"
    assert tracker.game_state.player_deck_id == "16225358-69d8-45c8-875a-726e19b02004"
    assert tracker.game_state.player_commanders == []


def test_parse_match_metadata_prefers_explicit_set_deck_v3_event():
    tracker = make_tracker()
    tracker.game_state.format_str = "MWM_SlowStart_20260602"
    request = {
        "EventName": "Play",
        "Summary": {
            "DeckId": "3c24e959-f8ef-405a-9a27-21b7ff080540",
            "Name": "Izzet Affinity (Temur Arne)",
            "Attributes": [{"name": "Format", "value": "Standard"}],
        },
        "Deck": {
            "MainDeck": [
                {"cardId": 100500, "quantity": 4},
                {"cardId": 100629, "quantity": 3},
            ],
            "CommandZone": [],
        },
    }
    line = "[UnityCrossThreadLogger]==> EventSetDeckV3 " + json.dumps(
        {"id": "abc", "request": json.dumps(request)}
    )

    tracker._parse_match_metadata(line)

    assert tracker.game_state.player_deck_name == "Izzet Affinity (Temur Arne)"
    assert tracker.game_state.player_deck_id == "3c24e959-f8ef-405a-9a27-21b7ff080540"
    assert tracker.game_state.player_deck_total_cards == 7
    assert tracker._active_deck_candidate_key == "3c24e959-f8ef-405a-9a27-21b7ff080540"
    assert tracker.game_state.format_str == "Play"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker._friendly_format_label() == "Standard Best-of-1 (Unranked)"


def test_new_game_tracking_clears_stale_midweek_format():
    tracker = make_tracker()
    tracker.game_state.format_str = "MWM_SlowStart_20260602"
    tracker.game_state.match_type = "best_of_1"
    tracker.game_state.player_deck_event_name = "MWM_SlowStart_20260602"

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)

    assert tracker.game_state.format_str == "Unknown"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker.game_state.player_deck_event_name is None


def test_new_game_tracking_clears_stale_opponent_identity(tmp_path):
    tracker = make_tracker()
    log_path = tmp_path / "Player.log"
    log_path.write_text("", encoding="utf-8")
    tracker.parser.log_path = str(log_path)
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "PreviousOpponent"
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=False)

    assert tracker.game_state.player_display_name == "Tapps"
    assert tracker.game_state.opponent_display_name is None
    assert tracker.game_state.player_seat_id is None
    assert tracker.game_state.opponent_seat_id is None


def test_parse_match_metadata_event_set_deck_v3_midweek_sets_event_format():
    tracker = make_tracker()
    request = {
        "EventName": "MWM_SlowStart_20260602",
        "Summary": {
            "DeckId": "129f5a6c-a2c3-4a50-b14e-59b5afc6c06f",
            "Name": "Golgari Annex (magic.gg)",
            "Attributes": [{"name": "Format", "value": "TraditionalStandard"}],
        },
        "Deck": {
            "MainDeck": [
                {"cardId": 95070, "quantity": 4},
                {"cardId": 90613, "quantity": 4},
            ],
            "CommandZone": [],
        },
    }
    line = "[UnityCrossThreadLogger]==> EventSetDeckV3 " + json.dumps(
        {"id": "abc", "request": json.dumps(request)}
    )

    tracker._parse_match_metadata(line)

    assert tracker.game_state.format_str == "MWM_SlowStart_20260602"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker._friendly_format_label() == "Midweek Magic - Slow Start"


def test_parse_match_metadata_event_set_deck_v3_premier_draft_sets_event_format():
    tracker = make_tracker()
    request = {
        "EventName": "PremierDraft_MSH_20260623",
        "Summary": {
            "DeckId": "draft-deck",
            "Name": "Draft Deck",
            "Attributes": [{"name": "Format", "value": "Draft"}],
        },
        "Deck": {
            "MainDeck": [{"cardId": 105071, "quantity": 1}],
            "Sideboard": [{"cardId": 105057, "quantity": 2}],
            "CommandZone": [],
        },
    }
    line = "[UnityCrossThreadLogger]==> EventSetDeckV3 " + json.dumps(
        {"id": "abc", "request": json.dumps(request)}
    )

    tracker._parsing_backfilled_metadata = True
    try:
        tracker._parse_match_metadata(line, from_backfill=True)
    finally:
        tracker._parsing_backfilled_metadata = False

    assert tracker.game_state.format_str == "PremierDraft_MSH_20260623"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker._friendly_format_label() == "Premier Draft - MSH"


def test_midweek_brawl_event_set_deck_v3_keeps_midweek_brawl_format():
    tracker = make_tracker()
    request = {
        "EventName": "MWM_Brawl_20260623",
        "Summary": {
            "DeckId": "eb229407-184c-443e-9ec8-572e8ad7296d",
            "Name": "Tifa - MWM",
            "Attributes": [{"name": "Format", "value": "HistoricBrawl"}],
        },
        "Deck": {
            "MainDeck": [{"cardId": 82394, "quantity": 36}],
            "CommandZone": [{"cardId": 96074, "quantity": 1}],
        },
    }
    line = "[UnityCrossThreadLogger]==> EventSetDeckV3 " + json.dumps(
        {"id": "abc", "request": json.dumps(request)}
    )

    tracker._parsing_backfilled_metadata = True
    try:
        tracker._parse_match_metadata(line, from_backfill=True)
    finally:
        tracker._parsing_backfilled_metadata = False

    assert tracker.game_state.format_str == "MWM_Brawl_20260623"
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker._friendly_format_label() == "Midweek Magic - Brawl"


def test_midweek_command_zone_payload_does_not_infer_historic_brawl():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.format_str = "MWM_SlowStart_20260602"
    tracker.game_state.player_deck_event_name = "MWM_SlowStart_20260602"

    tracker._update_format_from_game_state(
        {
            "zones": [
                {"type": "ZoneType_Command", "objectInstanceIds": [801]},
            ],
            "gameObjects": [
                {
                    "instanceId": 801,
                    "grpId": 100610,
                    "type": "GameObjectType_Card",
                    "ownerSeatId": 1,
                },
            ],
        }
    )

    assert tracker.game_state.format_str == "MWM_SlowStart_20260602"
    assert not tracker._is_brawl_format()
    assert tracker._friendly_format_label() == "Midweek Magic - Slow Start"


def test_explicit_active_standard_deck_is_not_overridden_by_stale_brawl_courses():
    tracker = make_tracker()
    tracker.game_state.player_commanders = ["Nahiri, Storm of Stone"]
    tracker._parse_match_metadata(
        '[UnityCrossThreadLogger]<== EventSetDeckV2 {"CourseId":"703c87ae","InternalEventName":"Play","CurrentModule":"CreateMatch","CourseDeckSummary":{"DeckId":"16225358-69d8-45c8-875a-726e19b02004","Name":"Niv-Mizzet (Malone)","Attributes":[{"name":"Format","value":"Standard"}]},"CourseDeck":{"MainDeck":[{"cardId":87237,"quantity":4},{"cardId":100546,"quantity":4}],"CommandZone":[]}}'
    )
    tracker._parse_match_metadata(
        json.dumps(
            {
                "Courses": [
                    {
                        "InternalEventName": "Play_Brawl_Historic",
                        "CurrentModule": "Complete",
                        "CourseDeckSummary": {
                            "DeckId": "156c02e3-3968-4d79-9fc7-a3ac28954542",
                            "Name": "achievement deck",
                            "Attributes": [{"name": "Format", "value": "HistoricBrawl"}],
                        },
                        "CourseDeck": {
                            "MainDeck": [{"cardId": 82393, "quantity": 40}],
                            "CommandZone": [{"cardId": 69684, "quantity": 1}],
                        },
                    }
                ]
            }
        )
    )

    assert tracker.game_state.player_deck_name == "Niv-Mizzet (Malone)"
    assert tracker.game_state.player_deck_id == "16225358-69d8-45c8-875a-726e19b02004"
    assert tracker.game_state.format_str == "Standard"
    assert tracker.game_state.player_commanders == []


def test_game_start_clears_stale_locked_brawl_candidate():
    tracker = make_tracker()
    tracker._active_deck_candidate_key = "156c02e3-3968-4d79-9fc7-a3ac28954542"
    tracker._process_line(json.dumps({"gameInfo": {"mulliganType": "MulliganType_London"}}))

    tracker._process_line(
        json.dumps(
            {
                "Courses": [
                    {
                        "InternalEventName": "Play_Brawl_Historic",
                        "CurrentModule": "Complete",
                        "CourseDeckSummary": {
                            "DeckId": "156c02e3-3968-4d79-9fc7-a3ac28954542",
                            "Name": "achievement deck",
                            "Attributes": [{"name": "Format", "value": "HistoricBrawl"}],
                        },
                        "CourseDeck": {"CommandZone": [{"cardId": 69684, "quantity": 1}]},
                    },
                    {
                        "InternalEventName": "Play",
                        "CurrentModule": "Complete",
                        "CourseDeckSummary": {
                            "DeckId": "2750dcd2-4ca1-4731-ae79-3b394befe7f4",
                            "Name": "Mono-Black Demons (TMNT Ash)",
                            "Attributes": [
                                {"name": "Format", "value": "TraditionalStandard"},
                                {
                                    "name": "LastPlayed",
                                    "value": '"2026-03-23T23:28:24.034312-04:00"',
                                },
                            ],
                        },
                        "CourseDeck": {"CommandZone": []},
                    },
                ]
            }
        )
    )

    assert tracker._active_deck_candidate_key is None
    assert tracker.game_state.player_deck_name is None
    assert tracker.game_state.player_commanders == []


def test_game_summary_prints_match_stats_section(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 9
    tracker.game_state.turns_taken_by_seat = {1: {1, 3, 5, 7, 9}, 2: {2, 4, 6, 8}}
    tracker.game_state.player_deck_total_cards = 60
    tracker.game_state.observed_starting_deck_total_by_seat = {1: 60, 2: 60}
    tracker.game_state.match_stats[1].update(
        {
            "attacks": 3,
            "attacking_creatures": 5,
            "attackers_lost": 1,
            "blocking_creatures": 2,
            "blockers_lost": 1,
            "total_damage": 14,
            "life_lost": 9,
            "life_gain": 4,
            "self_damage": 2,
            "cards_drawn": 3,
            "cards_discarded": 1,
            "cards_milled": 4,
            "cards_exiled": 2,
        }
    )
    tracker.game_state.match_stats[2].update(
        {
            "attacks": 2,
            "attacking_creatures": 3,
            "attackers_lost": 2,
            "blocking_creatures": 1,
            "blockers_lost": 1,
            "total_damage": 9,
            "life_lost": 14,
            "life_gain": 1,
            "self_damage": 0,
            "cards_drawn": 2,
            "cards_discarded": 2,
            "cards_milled": 6,
            "cards_exiled": 1,
        }
    )

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "MATCH STATS" in out
    assert "Total Turns: 9" in out
    assert "Turns: You 5, Opponent 4" in out
    assert "Your deck total: 60" in out
    assert "Opponent deck total (estimated): 60" in out
    assert "Combat: 3 attack step(s), 5 attacking creature(s), 1 attacker(s) lost" in out
    assert "Defense: 2 blocker(s), 1 blocker(s) lost" in out
    assert "Damage/Life: 14 damage dealt, 9 life lost, 2 self-damage, 4 life gained" in out
    assert "Cards: 0 played, 3 drawn, 1 discarded, 4 milled, 2 exiled" in out


def test_game_summary_persists_normalized_sqlite_analytics(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 4, 20, 12, 0, 0)
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.first_player_seat = 1
    tracker.game_state.turn_number = 8
    tracker.game_state.turns_taken_by_seat = {1: {1, 3, 5, 7}, 2: {2, 4, 6, 8}}
    tracker.game_state.player_life = 12
    tracker.game_state.opponent_life = 0
    tracker.game_state.game_start_time = datetime(2026, 4, 22, 12, 0, 0)
    tracker.game_state.game_end_time = datetime(2026, 4, 22, 12, 7, 30)
    tracker.game_state.winner_seat = 1
    tracker.game_state.completed_turns = [
        {
            "turn_number": 1,
            "seat_id": 1,
            "started_at": datetime(2026, 4, 22, 12, 0, 0),
            "ended_at": datetime(2026, 4, 22, 12, 0, 45),
            "duration_seconds": 45,
        },
        {
            "turn_number": 2,
            "seat_id": 2,
            "started_at": datetime(2026, 4, 22, 12, 0, 45),
            "ended_at": datetime(2026, 4, 22, 12, 1, 15),
            "duration_seconds": 30,
        },
    ]
    tracker.game_state.turn_time_seconds_by_seat = {1: 45, 2: 30}
    tracker.game_state.player_display_name = "Tester"
    tracker.game_state.opponent_display_name = "Arena Opponent"
    tracker.game_state.player_deck_name = "Dimir Tests"
    tracker.game_state.player_deck_id = "deck-123"
    tracker.game_state.player_deck_total_cards = 60
    tracker.game_state.starting_hand = [
        "Restless Reef",
        "Likeness Looter",
        "Darkslick Shores",
        "Swamp",
        "Torch the Tower",
        "Island",
        "Island",
    ]
    tracker.game_state.starting_hand_events = [
        CardEvent("Restless Reef", "player", card_type_category="Land"),
        CardEvent("Likeness Looter", "player", card_type_category="Creature"),
        CardEvent("Darkslick Shores", "player", card_type_category="Land"),
        CardEvent("Swamp", "player", card_type_category="Land"),
        CardEvent("Torch the Tower", "player", card_type_category="Instant"),
        CardEvent("Island", "player", card_type_category="Land"),
        CardEvent("Island", "player", card_type_category="Land"),
    ]
    tracker.game_state.observed_starting_deck_total_by_seat = {1: 60, 2: 60}
    tracker.game_state.match_stats[1].update(
        {
            "attacks": 2,
            "attacking_creatures": 5,
            "total_damage": 20,
            "cards_drawn": 4,
            "cards_discarded": 1,
            "cards_milled": 0,
        }
    )
    tracker.game_state.match_stats[2].update(
        {
            "life_lost": 20,
            "life_gain": 6,
            "cards_drawn": 8,
            "cards_discarded": 2,
            "cards_milled": 8,
        }
    )
    tracker.player_cards = [
        CardEvent("Restless Reef (Land)", "player", card_type_category="Land"),
        CardEvent("Restless Reef (Land)", "player", card_type_category="Land"),
        CardEvent("Likeness Looter (Creature 1/1)", "player", card_type_category="Creature"),
    ]
    tracker.opponent_cards = [
        CardEvent("Dreadwing Scavenger (Creature 2/2)", "opponent", card_type_category="Creature")
    ]

    tracker._print_game_summary()
    capsys.readouterr()

    with sqlite3.connect(tracker._console_db_path) as conn:
        game = conn.execute(
            "SELECT outcome, outcome_reason, duration_seconds, total_turns, player_turns, opponent_turns FROM games"
        ).fetchone()
        participants = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT role, display_name, deck_name, deck_size, deck_size_source, ending_life, went_first
                FROM participants
                """
            ).fetchall()
        }
        stats = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT p.role, s.damage_dealt, s.damage_taken, s.life_gained, s.cards_played,
                       s.cards_drawn, s.cards_discarded, s.cards_milled
                FROM game_participant_stats s
                JOIN participants p ON p.id = s.participant_id
                """
            ).fetchall()
        }
        cards = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT display_name, played_count FROM game_card_summary"
            ).fetchall()
        }
        opening_hand = conn.execute(
            """
            SELECT display_name, hand_position, copy_number
            FROM game_opening_hand_cards
            ORDER BY hand_position
            """
        ).fetchall()
        opening_meta = conn.execute(
            """
            SELECT opening_hand_size, mulligans
            FROM participants
            WHERE role = 'player'
            """
        ).fetchone()
        session = conn.execute(
            "SELECT games_played, wins, losses, runtime_seconds FROM tracker_sessions WHERE id = ?",
            ("test-session",),
        ).fetchone()
        console_rows = conn.execute("SELECT COUNT(*) FROM console_logs").fetchone()[0]
        turn_timings = conn.execute(
            "SELECT turn_number, seat_id, duration_seconds FROM game_turns ORDER BY turn_number"
        ).fetchall()

    assert game == ("win", "Opponent reached 0 life", 450, 8, 4, 4)
    assert participants["player"] == ("Tester", "Dimir Tests", 60, "metadata", 12, 1)
    assert participants["opponent"] == ("Arena Opponent", None, 60, "observed", 0, 0)
    assert stats["player"] == (20, 0, 0, 3, 4, 1, 0)
    assert stats["opponent"] == (0, 20, 6, 1, 8, 2, 8)
    assert cards["Restless Reef (Land)"] == 2
    assert cards["Likeness Looter (Creature 1/1)"] == 1
    assert cards["Dreadwing Scavenger (Creature 2/2)"] == 1
    assert opening_meta == (7, 0)
    assert opening_hand[0] == ("Restless Reef", 1, 1)
    assert opening_hand[-1] == ("Island", 7, 2)
    assert session == (1, 1, 0, 450)
    assert console_rows > 0
    assert turn_timings == [(1, 1, 45), (2, 2, 30)]


def test_game_core_persists_when_optional_detail_write_fails(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.game_start_time = datetime(2026, 7, 22, 12, 0, 0)
    tracker.game_state.game_end_time = datetime(2026, 7, 22, 12, 3, 0)

    def fail_detail(*_args):
        raise sqlite3.IntegrityError("invalid optional detail")

    tracker._persist_game_detail_analytics = fail_detail
    tracker._persist_game_analytics("win", "Opponent conceded")

    with sqlite3.connect(tracker._console_db_path) as conn:
        game = conn.execute("SELECT outcome, outcome_reason FROM games").fetchone()
        participants = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]

    assert game == ("win", "Opponent conceded")
    assert participants == 2
    assert "could not save game details" in capsys.readouterr().out


def test_sparky_game_summary_is_not_persisted_to_sqlite(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 7, 4, 0, 0, 0)
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.game_start_time = datetime(2026, 7, 4, 0, 28, 38)
    tracker.game_state.game_end_time = datetime(2026, 7, 4, 0, 31, 16)
    tracker.game_state.winner_seat = 1
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Sparky"
    tracker.game_state.format_str = "AIBotMatch_Rebalanced"

    tracker._print_game_summary()
    capsys.readouterr()

    with sqlite3.connect(tracker._console_db_path) as conn:
        def table_count(table_name):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            if not exists:
                return 0
            return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

        game_count = table_count("games")
        match_count = table_count("matches")
        participant_count = table_count("participants")
        console_count = table_count("console_logs")

    assert game_count == 0
    assert match_count == 0
    assert participant_count == 0
    assert console_count == 0


def test_game_summary_persists_brawl_starting_life(capsys, tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 6, 23, 20, 0, 0)
    tracker.game_state.player_seat_id = 2
    tracker.game_state.opponent_seat_id = 1
    tracker.game_state.format_str = "MWM_Brawl_20260623"
    tracker.game_state.player_life = 15
    tracker.game_state.opponent_life = 20
    tracker.game_state.game_start_time = datetime(2026, 6, 23, 20, 40, 0)
    tracker.game_state.game_end_time = datetime(2026, 6, 23, 20, 45, 0)
    tracker.game_state.winner_seat = 1

    tracker._print_game_summary()
    capsys.readouterr()

    with sqlite3.connect(tracker._console_db_path) as conn:
        rows = conn.execute(
            "SELECT role, starting_life FROM participants ORDER BY role"
        ).fetchall()

    assert rows == [("opponent", 25), ("player", 25)]


def test_combat_damage_labels_include_power_toughness_in_log_and_summary(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 6
    tracker.game_state.active_player = 2
    tracker.game_state.last_turn_announced = 6
    tracker.game_state.last_opponent_turn_number = 6
    tracker.game_state.combat_phase_active = True
    tracker.card_db.names[1001] = "Devoted Duelist"
    tracker.card_db.names[1002] = "Keen-Eyed Curator"
    attacker = {
        "instanceId": 501,
        "grpId": 1001,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 2},
        "toughness": {"value": 1},
        "attackState": "AttackState_Attacking",
        "attackInfo": {"targetId": 1},
    }
    blocker = {
        "instanceId": 601,
        "grpId": 1002,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 3},
        "toughness": {"value": 3},
    }
    tracker.game_state.current_combat_attackers[501] = {
        "card_name": "Devoted Duelist",
        "power": 2,
        "toughness": 1,
        "owner_seat": 2,
        "target_id": 1,
    }

    tracker._handle_damage(
        [601],
        {
            "type": ["AnnotationType_Damage"],
            "affectorId": 501,
            "details": [{"key": "damage", "valueInt32": [4]}],
        },
        [attacker, blocker],
    )
    tracker._display_combat_summary()
    out = capsys.readouterr().out

    assert (
        "Combat: [Devoted Duelist (2/1)] dealt 4 damage to [Keen-Eyed Curator (3/3)] (your)" in out
    )
    assert "[Devoted Duelist (2/1)] → [Keen-Eyed Curator (3/3)] (your): 4 damage" in out


def test_life_change_from_previous_attack_stays_on_previous_turn(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 5
    tracker.game_state.active_player = 1
    tracker.game_state.last_turn_announced = 5
    tracker.game_state.last_player_turn_number = 5
    tracker.game_state.player_life = 20
    tracker.game_state.opponent_life = 20
    tracker.game_state.current_combat_attackers = {
        901: {
            "card_name": "Fear of Missing Out",
            "power": 2,
            "toughness": 3,
            "owner_seat": 1,
            "target": "opponent",
            "target_id": 2,
        }
    }

    tracker._update_game_state(
        {
            "turnInfo": {"turnNumber": 6, "activePlayer": 2},
            "players": [
                {"systemSeatNumber": 1, "lifeTotal": 20},
                {"systemSeatNumber": 2, "lifeTotal": 18},
            ],
        }
    )
    out = capsys.readouterr().out

    assert "[0:00] Opponent: lost 2 life (now 18)" in out
    assert "Turn 6 - OPPONENT'S TURN" not in out


def test_update_game_state_detects_brawl_commanders_and_infers_seat(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_commanders = ["Card100471"]
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)

    tracker._update_game_state(
        {
            "gameInfo": {"variant": "GameVariant_Brawl"},
            "deckConstraintInfo": {"minCommanderSize": 1},
            "zones": [
                {"type": "ZoneType_Command", "objectInstanceIds": [801, 802]},
            ],
            "gameObjects": [
                {
                    "instanceId": 801,
                    "grpId": 100610,
                    "type": "GameObjectType_Card",
                    "ownerSeatId": 1,
                },
                {
                    "instanceId": 802,
                    "grpId": 100471,
                    "type": "GameObjectType_Card",
                    "ownerSeatId": 2,
                },
            ],
        }
    )
    out = capsys.readouterr().out

    assert tracker.game_state.format_str == "Brawl"
    assert tracker.game_state.player_seat_id == 2
    assert tracker.game_state.opponent_seat_id == 1
    assert tracker.game_state.player_commanders == ["Card100471"]
    assert tracker.game_state.opponent_commanders == ["Card100610"]
    assert "Your Commander: Card100471" in out
    assert "Opponent Commander: Card100610" in out


def test_brawl_initial_life_totals_seed_without_life_gain(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.game_start_time = datetime(2026, 6, 23, 20, 40, 39)
    tracker.game_state.format_str = "MWM_Brawl_20260623"
    tracker.game_state.player_seat_id = 2
    tracker.game_state.opponent_seat_id = 1

    tracker._update_game_state(
        {
            "turnInfo": {"turnNumber": 1, "activePlayer": 1},
            "players": [
                {"systemSeatNumber": 1, "lifeTotal": 25},
                {"systemSeatNumber": 2, "lifeTotal": 25},
            ],
        }
    )
    tracker._flush_pending_opponent_turn_header()
    out = capsys.readouterr().out

    assert "Life: You 25 - 25 Opponent" in out
    assert "gained 5 life" not in out
    assert tracker.game_state.player_life == 25
    assert tracker.game_state.opponent_life == 25


def test_update_game_state_removes_deleted_instances_from_snapshots():
    tracker = make_tracker()
    tracker.game_state.object_snapshots = {
        100: {"instanceId": 100, "grpId": 500},
        101: {"instanceId": 101, "grpId": 501},
    }
    tracker.game_state.current_combat_attackers = {100: {"card_name": "Old"}}
    tracker.game_state.attackers = [100, 101]

    tracker._update_game_state(
        {
            "diffDeletedInstanceIds": [100],
            "gameObjects": [],
        }
    )

    assert 100 not in tracker.game_state.object_snapshots
    assert 100 not in tracker.game_state.current_combat_attackers
    assert 100 not in tracker.game_state.attackers


def test_process_line_handles_later_gre_turn_message_in_same_line(capsys):
    tracker = make_tracker()

    line = json.dumps(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameStateId": 7,
                            "gameInfo": {
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_MatchComplete",
                            },
                        },
                    },
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameStateId": 8,
                            "turnInfo": {"turnNumber": 1, "activePlayer": 1},
                        },
                    },
                ]
            }
        }
    )

    tracker._check_game_start(line)

    assert tracker.game_state.in_match is True
    assert tracker.game_state.game_start_time is not None


def test_check_game_start_after_completed_match_resets_for_next_opening_hand(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.match_complete = True
    tracker.game_state.starting_hand = ["Old Card"]
    tracker.game_state.opening_hand_capture_closed = True

    line = json.dumps(
        {
            "gameStateMessage": {
                "zones": [
                    {
                        "type": "ZoneType_Hand",
                        "ownerSeatId": 1,
                        "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37],
                    }
                ],
                "gameObjects": [
                    {"instanceId": 31, "grpId": 2001},
                    {"instanceId": 32, "grpId": 2002},
                    {"instanceId": 33, "grpId": 2003},
                    {"instanceId": 34, "grpId": 2004},
                    {"instanceId": 35, "grpId": 2005},
                    {"instanceId": 36, "grpId": 2006},
                    {"instanceId": 37, "grpId": 2007},
                ],
            }
        }
    )

    tracker._check_game_start(line)

    assert tracker.game_state.in_match is True
    assert tracker.game_state.match_complete is False
    assert tracker.game_state.match_type == "best_of_1"
    assert tracker.game_state.game_number == 1
    assert tracker.game_state.starting_hand == []
    assert len(tracker.game_state._hand_before_mulligan_ids) == 7


def test_update_game_state_ignores_command_zone_emblems(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Historic Brawl"
    tracker.game_state.player_seat_id = 2
    tracker.game_state.opponent_seat_id = 1
    tracker.card_db.names.update(
        {
            95526: "Elspeth, Sun's Champion",
            96074: "Tifa Lockhart",
        }
    )

    tracker._update_game_state(
        {
            "gameInfo": {"variant": "GameVariant_Brawl"},
            "deckConstraintInfo": {"minCommanderSize": 1},
            "zones": [
                {"type": "ZoneType_Command", "objectInstanceIds": [237, 238, 239, 240]},
            ],
            "gameObjects": [
                {
                    "instanceId": 237,
                    "grpId": 2,
                    "type": "GameObjectType_Emblem",
                    "ownerSeatId": 1,
                    "controllerSeatId": 1,
                    "objectSourceGrpId": 106961,
                    "overlayGrpId": 2,
                },
                {
                    "instanceId": 238,
                    "grpId": 95526,
                    "type": "GameObjectType_Card",
                    "ownerSeatId": 1,
                    "controllerSeatId": 1,
                },
                {
                    "instanceId": 239,
                    "grpId": 2,
                    "type": "GameObjectType_Emblem",
                    "ownerSeatId": 2,
                    "controllerSeatId": 2,
                    "objectSourceGrpId": 106961,
                    "overlayGrpId": 2,
                },
                {
                    "instanceId": 240,
                    "grpId": 96074,
                    "type": "GameObjectType_Card",
                    "ownerSeatId": 2,
                    "controllerSeatId": 2,
                },
            ],
        }
    )
    out = capsys.readouterr().out

    assert tracker.game_state.player_commanders == ["Tifa Lockhart"]
    assert tracker.game_state.opponent_commanders == ["Elspeth, Sun's Champion"]
    assert "Card #2" not in out
    assert "Your Commander: Tifa Lockhart" in out
    assert "Opponent Commander: Elspeth, Sun's Champion" in out


def test_update_game_state_does_not_infer_brawl_from_empty_command_zone():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_commanders = ["Card2"]
    tracker.game_state.opponent_commanders = ["Card2"]

    tracker._update_game_state(
        {
            "gameInfo": {
                "variant": "GameVariant_Normal",
                "deckConstraintInfo": {
                    "minDeckSize": 60,
                    "maxDeckSize": 250,
                    "maxSideboardSize": 15,
                },
            },
            "zones": [
                {"type": "ZoneType_Command", "objectInstanceIds": []},
            ],
            "gameObjects": [],
        }
    )

    assert tracker.game_state.format_str == "Standard Best-of-1"
    assert tracker.game_state.player_commanders == []
    assert tracker.game_state.opponent_commanders == []


def test_capture_opening_hand_finalizes_keep_seven_on_turn_start():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    pre_turn = {
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37],
            }
        ],
        "gameObjects": [
            {"instanceId": 31, "grpId": 2001},
            {"instanceId": 32, "grpId": 2002},
            {"instanceId": 33, "grpId": 2003},
            {"instanceId": 34, "grpId": 2004},
            {"instanceId": 35, "grpId": 2005},
            {"instanceId": 36, "grpId": 2006},
            {"instanceId": 37, "grpId": 2007},
        ],
    }
    tracker._capture_opening_hand(pre_turn)
    assert tracker.game_state.starting_hand == []

    turn_one = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 1},
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37],
            }
        ],
        "gameObjects": pre_turn["gameObjects"],
    }
    tracker._capture_opening_hand(turn_one)

    assert len(tracker.game_state.starting_hand) == 7
    assert tracker.game_state.mulligan_count == 0


def test_accept_hand_finalizes_cached_seven_card_mulligan_prompt_hand():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.opening_mulligan_prompt_seen = True

    prompt_data = {
        "turnInfo": {"activePlayer": 1, "decisionPlayer": 1},
        "players": [
            {"systemSeatNumber": 1, "pendingMessageType": "ClientMessageType_MulliganResp"},
            {"systemSeatNumber": 2, "pendingMessageType": "ClientMessageType_MulliganResp"},
        ],
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37],
            },
        ],
        "gameObjects": [
            {"instanceId": 31, "grpId": 2001},
            {"instanceId": 32, "grpId": 2002},
            {"instanceId": 33, "grpId": 2003},
            {"instanceId": 34, "grpId": 2004},
            {"instanceId": 35, "grpId": 2005},
            {"instanceId": 36, "grpId": 2006},
            {"instanceId": 37, "grpId": 2007},
        ],
        "annotations": [{"type": ["AnnotationType_NewTurnStarted"], "affectedIds": [1]}],
    }

    tracker._capture_opening_hand(prompt_data)
    assert tracker.game_state.starting_hand == []
    assert len(tracker.game_state._hand_before_mulligan_ids) == 7

    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_MulliganResp",
                "mulliganResp": {"decision": "MulliganOption_AcceptHand"},
            }
        }
    )

    assert len(tracker.game_state.starting_hand) == 7
    assert tracker.game_state.initial_hand_size == 7
    assert tracker.game_state.mulligan_count == 0
    assert tracker.game_state.opening_hand_capture_closed is True


def test_capture_opening_hand_finalizes_cached_seven_when_gameplay_starts_without_keep_response():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.opening_mulligan_prompt_seen = True

    prompt_data = {
        "turnInfo": {"activePlayer": 1, "decisionPlayer": 1},
        "players": [
            {"systemSeatNumber": 1, "pendingMessageType": "ClientMessageType_MulliganResp"},
            {"systemSeatNumber": 2, "pendingMessageType": "ClientMessageType_MulliganResp"},
        ],
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37],
            },
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 2,
                "objectInstanceIds": [41, 42, 43, 44, 45, 46, 47],
            },
        ],
        "gameObjects": [
            {"instanceId": 31, "grpId": 2001},
            {"instanceId": 32, "grpId": 2002},
            {"instanceId": 33, "grpId": 2003},
            {"instanceId": 34, "grpId": 2004},
            {"instanceId": 35, "grpId": 2005},
            {"instanceId": 36, "grpId": 2006},
            {"instanceId": 37, "grpId": 2007},
        ],
    }
    tracker._capture_opening_hand(prompt_data)

    assert tracker.game_state.starting_hand == []
    assert len(tracker.game_state._hand_before_mulligan_ids) == 7

    gameplay_data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 1},
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [31, 32, 33, 34, 35, 36],
            },
        ],
        "gameObjects": [
            {"instanceId": 31, "grpId": 2001},
            {"instanceId": 32, "grpId": 2002},
            {"instanceId": 33, "grpId": 2003},
            {"instanceId": 34, "grpId": 2004},
            {"instanceId": 35, "grpId": 2005},
            {"instanceId": 36, "grpId": 2006},
            {"instanceId": 999, "grpId": 2010},
        ],
        "annotations": [
            {
                "type": ["AnnotationType_ZoneTransfer"],
                "affectedIds": [999],
                "details": [{"key": "category", "valueString": ["PlayLand"]}],
            }
        ],
    }
    tracker._capture_opening_hand(gameplay_data)

    assert len(tracker.game_state.starting_hand) == 7
    assert tracker.game_state.initial_hand_size == 7
    assert tracker.game_state.mulligan_count == 0
    assert tracker.game_state.opening_hand_capture_closed is True


def test_reset_new_game_tracking_clears_previous_opening_hand_state():
    tracker = make_tracker()
    tracker.game_state.starting_hand = ["Old Card"]
    tracker.game_state.starting_hand_events = [CardEvent("Old Card", "player")]
    tracker.game_state.initial_hand_size = 7
    tracker.game_state.mulligan_count = 1
    tracker.game_state._hand_before_mulligan = ["Cached Old Card"]
    tracker.game_state._hand_before_mulligan_ids = [123]
    tracker.game_state._hand_before_mulligan_instance_ids = [456]
    tracker.game_state._hand_before_mulligan_events = [CardEvent("Cached Old Card", "player")]
    tracker.game_state.opening_hand_capture_closed = True
    tracker.game_state.opening_keep_confirmed = True
    tracker.game_state.opening_select_n_ids = [456]
    tracker.game_state.explicit_mulligan_count = 1

    tracker._reset_new_game_tracking(opening_mulligan_prompt_seen=True)

    assert tracker.game_state.starting_hand == []
    assert tracker.game_state.starting_hand_events == []
    assert tracker.game_state.initial_hand_size == 7
    assert tracker.game_state.mulligan_count == 0
    assert tracker.game_state._hand_before_mulligan == []
    assert tracker.game_state._hand_before_mulligan_ids == []
    assert tracker.game_state._hand_before_mulligan_instance_ids == []
    assert tracker.game_state._hand_before_mulligan_events == []
    assert tracker.game_state.opening_hand_capture_closed is False
    assert tracker.game_state.opening_keep_confirmed is False
    assert tracker.game_state.opening_select_n_ids == []
    assert tracker.game_state.explicit_mulligan_count == 0


def test_capture_opening_hand_corrects_stale_seat_from_visible_hand():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 1

    data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 1},
        "players": [{"systemSeatNumber": 1}, {"systemSeatNumber": 2}],
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [101, 102, 103, 104, 105, 106, 107],
            },
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 2,
                "objectInstanceIds": [201, 202, 203, 204, 205, 206, 207],
            },
        ],
        "gameObjects": [
            {"instanceId": 201, "grpId": 2201},
            {"instanceId": 202, "grpId": 2202},
            {"instanceId": 203, "grpId": 2203},
            {"instanceId": 204, "grpId": 2204},
            {"instanceId": 205, "grpId": 2205},
            {"instanceId": 206, "grpId": 2206},
            {"instanceId": 207, "grpId": 2207},
        ],
    }

    tracker._capture_opening_hand(data)

    assert tracker.game_state.player_seat_id == 2
    assert tracker.game_state.opponent_seat_id == 1
    assert len(tracker.game_state.starting_hand) == 7


def test_capture_opening_hand_uses_snapshot_fallback_for_partial_diff():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 1
    tracker.game_state.object_snapshots = {
        101: {"instanceId": 101, "grpId": 3001},
        102: {"instanceId": 102, "grpId": 3002},
        103: {"instanceId": 103, "grpId": 3003},
        104: {"instanceId": 104, "grpId": 3004},
        105: {"instanceId": 105, "grpId": 3005},
        106: {"instanceId": 106, "grpId": 3006},
    }

    # gameObjects diff only includes one hand object, but zone has all 6.
    data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 2},
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [101, 102, 103, 104, 105, 106],
            }
        ],
        "gameObjects": [{"instanceId": 101, "grpId": 3001}],
    }
    tracker._capture_opening_hand(data)

    assert len(tracker.game_state.starting_hand) == 6
    assert tracker.game_state.mulligan_count == 1


def test_capture_opening_hand_counts_one_london_mulligan_with_two_sevens_then_six():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    first_seven = {
        "zones": [
            {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [1, 2, 3, 4, 5, 6, 7]}
        ],
        "gameObjects": [
            {"instanceId": 1, "grpId": 4001},
            {"instanceId": 2, "grpId": 4002},
            {"instanceId": 3, "grpId": 4003},
            {"instanceId": 4, "grpId": 4004},
            {"instanceId": 5, "grpId": 4005},
            {"instanceId": 6, "grpId": 4006},
            {"instanceId": 7, "grpId": 4007},
        ],
    }
    tracker._capture_opening_hand(first_seven)
    assert tracker.game_state.mulligan_count == 0
    assert tracker.game_state.starting_hand == []

    second_seven = {
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [11, 12, 13, 14, 15, 16, 17],
            }
        ],
        "gameObjects": [
            {"instanceId": 11, "grpId": 4101},
            {"instanceId": 12, "grpId": 4102},
            {"instanceId": 13, "grpId": 4103},
            {"instanceId": 14, "grpId": 4104},
            {"instanceId": 15, "grpId": 4105},
            {"instanceId": 16, "grpId": 4106},
            {"instanceId": 17, "grpId": 4107},
        ],
    }
    tracker._capture_opening_hand(second_seven)
    assert tracker.game_state.mulligan_count == 1
    assert tracker.game_state.starting_hand == []

    keep_six = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 2},
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [11, 12, 13, 14, 15, 16],
            }
        ],
        "gameObjects": [
            {"instanceId": 11, "grpId": 4101},
            {"instanceId": 12, "grpId": 4102},
            {"instanceId": 13, "grpId": 4103},
            {"instanceId": 14, "grpId": 4104},
            {"instanceId": 15, "grpId": 4105},
            {"instanceId": 16, "grpId": 4106},
        ],
    }
    tracker._capture_opening_hand(keep_six)

    assert len(tracker.game_state.starting_hand) == 6
    assert tracker.game_state.mulligan_count == 1
    assert tracker.session_total_mulligans == 1


def test_london_mulligan_bottom_selection_finalizes_six_card_starting_hand():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.card_db.names.update(
        {
            6001: "Gloomlake Verge",
            6002: "Tinybones Joins Up",
            6003: "Kaito, Bane of Nightmares",
            6004: "Fear of Isolation",
            6005: "Stormchaser's Talent",
            6006: "Stormchaser's Talent",
            6007: "Gloomlake Verge",
        }
    )

    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_MulliganResp",
                "mulliganResp": {"decision": "MulliganOption_Mulligan"},
            }
        }
    )
    second_seven = {
        "players": [
            {"systemSeatNumber": 1, "pendingMessageType": "ClientMessageType_MulliganResp"}
        ],
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [101, 102, 103, 104, 105, 106, 107],
            }
        ],
        "gameObjects": [
            {"instanceId": 101, "grpId": 6001},
            {"instanceId": 102, "grpId": 6002},
            {"instanceId": 103, "grpId": 6003},
            {"instanceId": 104, "grpId": 6004},
            {"instanceId": 105, "grpId": 6005},
            {"instanceId": 106, "grpId": 6006},
            {"instanceId": 107, "grpId": 6007},
        ],
    }
    tracker._capture_opening_hand(second_seven)
    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_MulliganResp",
                "mulliganResp": {"decision": "MulliganOption_AcceptHand"},
            }
        }
    )

    assert tracker.game_state.starting_hand == []
    assert tracker.game_state.opening_hand_capture_closed is False

    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_SelectNResp",
                "selectNResp": {"selectedObjectIds": [103]},
            }
        }
    )

    assert tracker.game_state.starting_hand == [
        "Gloomlake Verge",
        "Tinybones Joins Up",
        "Fear of Isolation",
        "Stormchaser's Talent",
        "Stormchaser's Talent",
        "Gloomlake Verge",
    ]
    assert "Kaito, Bane of Nightmares" not in tracker.game_state.starting_hand
    assert tracker.game_state.initial_hand_size == 6
    assert tracker.game_state.mulligan_count == 1
    assert tracker.game_state.opening_hand_capture_closed is True


def test_capture_opening_hand_ignores_post_action_hand_six_without_mulligan_prompt():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    post_land_data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 1, "phase": "Phase_Main1"},
        "zones": [
            {
                "type": "ZoneType_Hand",
                "ownerSeatId": 1,
                "objectInstanceIds": [71, 72, 73, 74, 75, 76],
            }
        ],
        "gameObjects": [
            {"instanceId": 71, "grpId": 5001},
            {"instanceId": 72, "grpId": 5002},
            {"instanceId": 73, "grpId": 5003},
            {"instanceId": 74, "grpId": 5004},
            {"instanceId": 75, "grpId": 5005},
            {"instanceId": 76, "grpId": 5006},
        ],
        "annotations": [
            {
                "type": ["AnnotationType_ZoneTransfer"],
                "affectedIds": [999],
                "details": [{"key": "category", "valueString": ["PlayLand"]}],
            }
        ],
    }

    tracker._capture_opening_hand(post_land_data)

    assert tracker.game_state.starting_hand == []
    assert tracker.game_state.mulligan_count == 0
    assert tracker.game_state.opening_hand_capture_closed is True
