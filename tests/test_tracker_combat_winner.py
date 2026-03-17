"""Regression tests for winner parsing and combat events in tracker."""

import json
import re
from datetime import datetime

from mtga_tracker.tracker import CardTracker, GameState


class DummyParser:
    """Minimal parser stub for tracker unit tests."""

    log_path = "/tmp/Player.log"

    @staticmethod
    def parse_json_from_line(line: str):
        match = re.search(r"\{.*\}", line)
        if not match:
            return None
        return json.loads(match.group(0))


class DummyCardDB:
    """Simple card DB stub that returns deterministic names."""

    def __init__(self):
        self.cache = {}
        self.log_cache = {}

    def _save_cache(self):
        return None

    @staticmethod
    def get_card_name(grp_id: int) -> str:
        return f"Card{grp_id}"


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
    tracker.session_unknown = 0
    tracker._session_stats_recorded_this_game = False
    tracker._deck_candidates = {}
    tracker._metadata_backfilled = False
    tracker.use_colors = False
    tracker._ansi_styles = {}
    tracker._ansi_reset = ""
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
                                {"blockerInstanceId": 30, "attackerInstanceIds": [40, 41], "maxAttackers": 1}
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


def test_session_stats_record_once_per_game():
    tracker = make_tracker()

    tracker._record_session_outcome("win")
    tracker._record_session_outcome("win")
    assert tracker.session_games_played == 1
    assert tracker.session_wins == 1
    assert tracker.session_losses == 0

    tracker._session_stats_recorded_this_game = False
    tracker._record_session_outcome("loss")
    assert tracker.session_games_played == 2
    assert tracker.session_wins == 1
    assert tracker.session_losses == 1


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

    seatless_concede_line = json.dumps({"clientToGreMessage": {"type": "ClientMessageType_ConcedeReq"}})
    tracker._check_game_end(seatless_concede_line)

    assert tracker.game_state.winner_seat == 1


def test_seatless_concede_req_does_not_assume_player_loss():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    seatless_concede_line = json.dumps({"clientToGreMessage": {"type": "ClientMessageType_ConcedeReq"}})
    tracker._check_game_end(seatless_concede_line)

    assert tracker.game_state.winner_seat is None
    assert tracker.game_state.match_complete is False


def test_format_actor_event_has_consistent_prefix():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.last_player_turn_number = 18
    tracker.game_state.last_turn_announced = 18

    line = tracker._format_actor_event("📥", 1, "drew a card")
    assert line == "[Turn 18] 📥 You: drew a card"


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
    assert "[Turn 6] ↩️ You: returned [Card111] to hand" in out
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
    assert first == ""

    tracker._process_annotation(resolve_annotation, [])
    out = capsys.readouterr().out
    assert "[Turn 5] > Opponent: cast [Card1700 (Instant)]" in out
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

    assert "[Turn 6] > Opponent: cast [Card1701 (Sorcery)]" in second
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

    assert "[Turn 7] > Opponent: cast [Card1702 (Instant)]" in out
    assert 702 in tracker.game_state.seen_instance_ids
    assert len(tracker.opponent_cards) == 1


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
    assert capsys.readouterr().out == ""

    tracker._process_annotation(
        {
            "type": ["AnnotationType_ZoneTransfer"],
            "affectedIds": [801],
            "details": [{"key": "category", "valueString": ["Resolve"]}],
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

    assert out.count("cast [Card1802 (Sorcery)]") == 1
    assert 801 in tracker.game_state.seen_instance_ids


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

    assert "[Turn 7] 💥 Opponent: [Card1901] was destroyed" in out
    assert "[Turn 6] 💥 Opponent" not in out


def test_does_not_warn_when_first_observed_turn_is_two(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    tracker._update_game_state({"turnInfo": {"turnNumber": 2, "activePlayer": 1, "phase": "Phase_Main1"}})
    out = capsys.readouterr().out

    assert "First observed turn is" not in out
    assert out == ""


def test_warns_when_first_observed_turn_is_three(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    tracker._update_game_state({"turnInfo": {"turnNumber": 3, "activePlayer": 1, "phase": "Phase_Main1"}})
    out = capsys.readouterr().out

    assert "First observed turn is 3" in out
    assert "earlier turn(s) (1, 2)" in out
    assert "Turn 3 - YOUR TURN" not in out


def test_player_turn_header_flushes_on_first_player_event(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True

    tracker._update_game_state({"turnInfo": {"turnNumber": 2, "activePlayer": 1, "phase": "Phase_Main1"}})
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
    assert "[Turn 2] 📥 You: drew a card" in out


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
    assert "[Turn 1] ⛰️ Opponent: ⏪ played [Card999 (Land)]" in out


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

    assert "[Turn 5] 💔 You: lost 1 life (now 19)" in out
    assert "[Turn 4] 💔 You" not in out


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
            "annotations": [{"type": ["AnnotationType_Damage"], "affectedIds": [901], "details": []}],
            "players": [{"systemSeatNumber": 2, "lifeTotal": 15}],
        }
    )
    out = capsys.readouterr().out

    assert "[Turn 5] 💔 Opponent: lost 5 life (now 15)" in out
    assert "Turn 6 - OPPONENT'S TURN" not in out


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
    assert "[Turn 7] 💚 Opponent: gained 1 life (now 21)" in out


def test_turn_header_life_line_includes_heart_icon(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.pending_player_turn_header = (1, 1)

    tracker._flush_pending_player_turn_header()
    out = capsys.readouterr().out

    assert "❤️ Life: You 20 - 20 Opponent" in out


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
    assert "[Turn 1] ⛰️ Opponent: ⏪ played [Card999 (Land)]" in out


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
    assert "[Turn 1] ⛰️ You: played [Card1010 (Land)]" in out


def test_turn_headers_wait_until_seats_known(capsys):
    tracker = make_tracker()
    tracker.game_state.in_match = True

    # Turn info arrives before we know player/opponent seats.
    tracker._update_game_state({"turnInfo": {"turnNumber": 1, "activePlayer": 2, "phase": "Phase_Main1"}})
    early_out = capsys.readouterr().out
    assert early_out == ""
    assert tracker.game_state.last_turn_announced == 0

    # Seats become known, next turn is the first one we can safely label.
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker._update_game_state({"turnInfo": {"turnNumber": 2, "activePlayer": 1, "phase": "Phase_Main1"}})
    out = capsys.readouterr().out

    assert "First observed turn is" not in out
    assert out == ""


def test_block_is_not_reported_twice_across_block_sources(capsys):
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.turn_number = 7

    game_objects_by_id = {
        30: {"instanceId": 30, "grpId": 303, "ownerSeatId": 1, "power": {"value": 1}, "toughness": {"value": 3}},
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
                                {"name": "LastPlayed", "value": '"2026-03-10T22:39:18.07558-04:00"'},
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


def test_match_started_block_prints_players_when_opponent_known(capsys):
    tracker = make_tracker()
    tracker.game_state.game_start_time = datetime(2026, 3, 10, 21, 15, 0)
    tracker.game_state.format_str = "Standard Best-of-1"
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Rival123"

    tracker._print_match_started_block()
    out = capsys.readouterr().out

    assert "Players: Tapps vs Rival123" in out


def test_game_state_reset_clears_previous_deck_name():
    state = GameState()
    state.player_deck_name = "MWM Landfall"
    state.player_deck_id = "old-id"
    state.reset()

    assert state.player_deck_name is None
    assert state.player_deck_id is None


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
    tracker.game_state.player_cards_exiled = 3
    tracker.game_state.player_cards_exiled_by_opponent = 2
    tracker.game_state.opponent_cards_exiled_by_player = 4

    tracker._print_game_summary()
    out = capsys.readouterr().out

    assert "Your Deck: Izzet Artifacts (Carlo TMNT)" in out
    assert "Mulligans: 2" in out
    assert "Cards Exiled:" in out
    assert "By Me: 4" in out
    assert "By Opponent: 2" in out


def test_capture_opening_hand_detects_mulligan_when_seat_unknown():
    tracker = make_tracker()
    tracker.game_state.in_match = True

    data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 2},
        "players": [{"systemSeatNumber": 1}, {"systemSeatNumber": 2}],
        "zones": [
            {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [11, 12, 13, 14, 15, 16]},
            {"type": "ZoneType_Hand", "ownerSeatId": 2, "objectInstanceIds": [21, 22, 23, 24, 25, 26, 27]},
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


def test_capture_opening_hand_finalizes_keep_seven_on_turn_start():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    pre_turn = {
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37]}],
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
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [31, 32, 33, 34, 35, 36, 37]}],
        "gameObjects": pre_turn["gameObjects"],
    }
    tracker._capture_opening_hand(turn_one)

    assert len(tracker.game_state.starting_hand) == 7
    assert tracker.game_state.mulligan_count == 0


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
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [101, 102, 103, 104, 105, 106]}],
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
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [1, 2, 3, 4, 5, 6, 7]}],
        "gameObjects": [
            {"instanceId": 1, "grpId": 4001}, {"instanceId": 2, "grpId": 4002}, {"instanceId": 3, "grpId": 4003},
            {"instanceId": 4, "grpId": 4004}, {"instanceId": 5, "grpId": 4005}, {"instanceId": 6, "grpId": 4006},
            {"instanceId": 7, "grpId": 4007},
        ],
    }
    tracker._capture_opening_hand(first_seven)
    assert tracker.game_state.mulligan_count == 0
    assert tracker.game_state.starting_hand == []

    second_seven = {
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [11, 12, 13, 14, 15, 16, 17]}],
        "gameObjects": [
            {"instanceId": 11, "grpId": 4101}, {"instanceId": 12, "grpId": 4102}, {"instanceId": 13, "grpId": 4103},
            {"instanceId": 14, "grpId": 4104}, {"instanceId": 15, "grpId": 4105}, {"instanceId": 16, "grpId": 4106},
            {"instanceId": 17, "grpId": 4107},
        ],
    }
    tracker._capture_opening_hand(second_seven)
    assert tracker.game_state.mulligan_count == 1
    assert tracker.game_state.starting_hand == []

    keep_six = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 2},
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [11, 12, 13, 14, 15, 16]}],
        "gameObjects": [
            {"instanceId": 11, "grpId": 4101}, {"instanceId": 12, "grpId": 4102}, {"instanceId": 13, "grpId": 4103},
            {"instanceId": 14, "grpId": 4104}, {"instanceId": 15, "grpId": 4105}, {"instanceId": 16, "grpId": 4106},
        ],
    }
    tracker._capture_opening_hand(keep_six)

    assert len(tracker.game_state.starting_hand) == 6
    assert tracker.game_state.mulligan_count == 1


def test_capture_opening_hand_ignores_post_action_hand_six_without_mulligan_prompt():
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2

    post_land_data = {
        "turnInfo": {"turnNumber": 1, "activePlayer": 1, "phase": "Phase_Main1"},
        "zones": [{"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [71, 72, 73, 74, 75, 76]}],
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
