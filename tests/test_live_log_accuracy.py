"""Live-log accuracy regressions found by replaying a real game.

Each test builds the minimal Arena messages behind one wrong console line:
an activated ability printed twice, combat damage without its source, an
attacked planeswalker shown as an instance id, a card "tapping itself", an
unreplaced CARDNAME, and a fizzled spell reported turns later.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tracker_combat_winner import DummyCardDB, make_tracker  # noqa: E402

from mtga_tracker.card_database import CardDatabase  # noqa: E402

STATION = 373
SUSUR = 96833
SACKVILLE = 103459


class ActivatedAwareCardDB(DummyCardDB):
    def __init__(self, activated=()):
        super().__init__()
        self.activated = set(activated)

    def is_activated_ability(self, ability_grp_id):
        return ability_grp_id in self.activated


def _tracker(turn=3, active=2):
    tracker = make_tracker()
    tracker.card_db = ActivatedAwareCardDB(activated={STATION})
    state = tracker.game_state
    state.in_match = True
    state.player_seat_id = 1
    state.opponent_seat_id = 2
    state.turn_number = turn
    state.active_player = active
    state.last_turn_announced = turn
    state.last_opponent_turn_number = turn
    state.last_player_turn_number = turn
    return tracker


def _game_state(gsid, annotations, objects=(), zones=(), **extra):
    data = {
        "gameStateId": gsid,
        "annotations": list(annotations),
        "gameObjects": list(objects),
        "zones": list(zones),
    }
    data.update(extra)
    return {"type": "game_state", "data": data}


def _station_messages():
    """Arena's two messages for one Station activation (from a real log)."""
    land = {
        "instanceId": 304,
        "grpId": SUSUR,
        "type": "GameObjectType_Card",
        "zoneId": 28,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Land"],
    }
    creature = {
        "instanceId": 310,
        "grpId": SACKVILLE,
        "type": "GameObjectType_Card",
        "zoneId": 28,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 2},
        "toughness": {"value": 2},
    }
    ability = {
        "instanceId": 314,
        "grpId": STATION,
        "type": "GameObjectType_Ability",
        "zoneId": 27,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "objectSourceGrpId": SUSUR,
        "parentId": 304,
    }
    # QueuedGameStateMessage: the ability is on the stack, cost not yet paid.
    created = _game_state(
        50,
        [
            {
                "id": 178,
                "affectorId": 304,
                "affectedIds": [314],
                "type": ["AnnotationType_AbilityInstanceCreated"],
            }
        ],
        objects=[land, creature, ability],
    )
    # Next message: the tapped creature (the cost) and the activation itself.
    activated = _game_state(
        51,
        [
            {
                "id": 179,
                "affectorId": 314,
                "affectedIds": [310],
                "type": ["AnnotationType_TappedUntappedPermanent"],
                "details": [{"key": "tapped", "valueInt32": [1]}],
            },
            {
                "id": 180,
                "affectorId": 2,
                "affectedIds": [314],
                "type": ["AnnotationType_UserActionTaken"],
                "details": [
                    {"key": "actionType", "valueInt32": [2]},
                    {"key": "abilityGrpId", "valueInt32": [STATION]},
                ],
            },
        ],
        objects=[dict(creature, isTapped=True)],
    )
    return created, activated


def test_activated_ability_split_across_messages_prints_once(capsys):
    tracker = _tracker()
    tracker.card_db.names[SUSUR] = "Susur Secundi, Void Altar"
    tracker.card_db.names[SACKVILLE] = "The Sackville-Bagginses"
    tracker.card_db.ability_texts[(SUSUR, STATION)] = "Station"

    for event in _station_messages():
        tracker._handle_event(event)
    out = capsys.readouterr().out

    assert out.count("[Susur Secundi, Void Altar] - Station") == 1
    assert "[Susur Secundi, Void Altar] tapped [The Sackville-Bagginses (2/2)]" in out


def test_trigger_is_still_printed_when_its_creation_has_no_user_action(capsys):
    tracker = _tracker()
    tracker.card_db.names[SACKVILLE] = "The Sackville-Bagginses"
    tracker.card_db.ability_texts[(SACKVILLE, 205151)] = (
        "When The Sackville-Bagginses enter, you may sacrifice another creature or artifact."
    )
    tracker._handle_event(
        _game_state(
            47,
            [
                {
                    "id": 173,
                    "affectorId": 310,
                    "affectedIds": [313],
                    "type": ["AnnotationType_AbilityInstanceCreated"],
                }
            ],
            objects=[
                {
                    "instanceId": 310,
                    "grpId": SACKVILLE,
                    "ownerSeatId": 2,
                    "controllerSeatId": 2,
                    "cardTypes": ["CardType_Creature"],
                },
                {
                    "instanceId": 313,
                    "grpId": 205151,
                    "type": "GameObjectType_Ability",
                    "ownerSeatId": 2,
                    "controllerSeatId": 2,
                    "objectSourceGrpId": SACKVILLE,
                    "parentId": 310,
                },
            ],
        )
    )
    out = capsys.readouterr().out

    assert "[The Sackville-Bagginses] - When The Sackville-Bagginses enter" in out


def test_tap_cost_on_the_source_itself_is_not_printed(capsys):
    tracker = _tracker(turn=10, active=1)
    tracker.card_db.names[90001] = "Soul-Guide Lantern"
    tracker.card_db.ability_texts[(90001, 90002)] = (
        "{T}, Sacrifice this artifact: Exile each opponent's graveyard."
    )
    lantern = {
        "instanceId": 400,
        "grpId": 90001,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Artifact"],
    }
    ability = {
        "instanceId": 401,
        "grpId": 90002,
        "type": "GameObjectType_Ability",
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "objectSourceGrpId": 90001,
    }
    tracker.game_state.ability_instance_sources[401] = 400
    objects = {400: lantern, 401: ability}
    tap = {
        "affectorId": 401,
        "affectedIds": [400],
        "type": ["AnnotationType_TappedUntappedPermanent"],
        "details": [{"key": "tapped", "valueInt32": [1]}],
    }

    tracker._handle_tapped_untapped_permanent([400], tap, objects)
    out = capsys.readouterr().out

    assert "tapped" not in out


def test_combat_damage_names_attacker_missing_from_the_damage_message(capsys):
    tracker = _tracker(turn=11, active=2)
    tracker.game_state.combat_phase_active = True
    tracker.card_db.names[105191] = "Villain"
    tracker.card_db.names[106489] = "Chandra, Torch of Defiance"
    # The attacker was seen when it attacked; the damage message only has Chandra.
    tracker.game_state.object_snapshots[457] = {
        "instanceId": 457,
        "grpId": 105191,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 3},
        "toughness": {"value": 1},
    }
    chandra = {
        "instanceId": 406,
        "grpId": 106489,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Planeswalker"],
    }

    tracker._handle_damage(
        [406],
        {
            "type": ["AnnotationType_DamageDealt"],
            "affectorId": 457,
            "details": [
                {"key": "damage", "valueInt32": [3]},
                {"key": "type", "valueInt32": [1]},
            ],
        },
        [chandra],
    )
    out = capsys.readouterr().out

    assert "Combat: [Villain (3/1)] dealt 3 damage to [Chandra, Torch of Defiance] (your)" in out
    assert "took 3 damage" not in out


def test_attack_on_planeswalker_names_it_from_its_snapshot(capsys):
    tracker = _tracker(turn=11, active=2)
    tracker.card_db.names[105191] = "Villain"
    tracker.card_db.names[106489] = "Chandra, Torch of Defiance"
    tracker.game_state.object_snapshots[406] = {
        "instanceId": 406,
        "grpId": 106489,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Planeswalker"],
    }
    attacker = {
        "instanceId": 457,
        "grpId": 105191,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "power": {"value": 3},
        "toughness": {"value": 1},
        "attackState": "AttackState_Attacking",
        "attackInfo": {"targetId": 406},
    }

    tracker._handle_attack_state_objects([attacker])
    out = capsys.readouterr().out

    assert "attacking [Chandra, Torch of Defiance (your)] with [Villain (3/1)]" in out
    assert "ID 406" not in out


def test_modal_choice_replaces_cardname_placeholder(capsys):
    tracker = _tracker(turn=6, active=1)
    tracker.card_db.names[105019] = "Avengers Disassembled"
    tracker.card_db.ability_texts[87926] = "CARDNAME deals 3 damage to each creature."
    tracker._capture_casting_time_options_requests(
        {
            "type": "GREMessageType_CastingTimeOptionsReq",
            "gameStateId": 122,
            "castingTimeOptionsReq": {
                "castingTimeOptionReq": [
                    {
                        "ctoId": 2,
                        "castingTimeOptionType": "CastingTimeOptionType_Modal",
                        "affectedId": 329,
                        "grpId": 105019,
                        "playerIdToPrompt": 1,
                        "modalReq": {"modalOptions": [{"grpId": 87926}]},
                    }
                ]
            },
        }
    )
    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_CastingTimeOptionsResp",
                "gameStateId": 122,
                "castingTimeOptionsResp": {
                    "castingTimeOptionResp": {
                        "ctoId": 2,
                        "castingTimeOptionType": "CastingTimeOptionType_Modal",
                        "chooseModalResp": {"grpIds": [87926]},
                    }
                },
            }
        }
    )
    out = capsys.readouterr().out

    assert "Avengers Disassembled deals 3 damage to each creature." in out
    assert "CARDNAME" not in out


def test_spell_moved_off_stack_without_category_fizzles_at_once(capsys):
    tracker = _tracker(turn=10, active=1)
    tracker.card_db.names[102778] = "Bitter Triumph"
    tracker.card_db.names[90430] = "Corrupted Conviction"
    stack, graveyard = 27, 37
    zones = [
        {"zoneId": stack, "type": "ZoneType_Stack"},
        {"zoneId": graveyard, "type": "ZoneType_Graveyard", "ownerSeatId": 1},
    ]
    tracker._register_stack_item(435, seat_id=1, label="[Bitter Triumph (Instant)]", kind="spell")
    # Another spell above it keeps the stack's lifecycle lines visible.
    tracker._register_stack_item(
        438, seat_id=2, label="[Corrupted Conviction (Instant)]", kind="spell"
    )
    capsys.readouterr()

    bitter_triumph = {
        "instanceId": 458,
        "grpId": 102778,
        "zoneId": graveyard,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "cardTypes": ["CardType_Instant"],
    }
    tracker._handle_event(
        _game_state(
            260,
            [
                {
                    "id": 749,
                    "affectedIds": [435],
                    "type": ["AnnotationType_ObjectIdChanged"],
                    "details": [
                        {"key": "orig_id", "valueInt32": [435]},
                        {"key": "new_id", "valueInt32": [458]},
                    ],
                },
                {
                    "id": 750,
                    "affectedIds": [458],
                    "type": ["AnnotationType_ZoneTransfer"],
                    "details": [
                        {"key": "zone_src", "valueInt32": [stack]},
                        {"key": "zone_dest", "valueInt32": [graveyard]},
                        {"key": "category", "valueString": ["nil"]},
                    ],
                },
            ],
            objects=[dict(bitter_triumph, instanceId=435, zoneId=30), bitter_triumph],
            zones=zones,
        )
    )
    # Arena's later cleanup must not report it again as an inferred exit.
    tracker._handle_event(_game_state(400, [], diffDeletedInstanceIds=[435]))
    out = capsys.readouterr().out

    assert "Stack: [Bitter Triumph (Instant)] [fizzled]" in out
    assert "inferred" not in out
    assert tracker.game_state.stack_items[435]["status"] == "fizzled"


def test_card_database_reads_activated_ability_category(tmp_path):
    db_path = tmp_path / "Raw_CardDatabase_test.mtga"
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE "Abilities" ("Id" INTEGER, "Category" INTEGER)')
    conn.executemany('INSERT INTO "Abilities" VALUES (?, ?)', [(373, 1), (205151, 2), (142, 3)])
    conn.commit()
    conn.close()

    card_db = CardDatabase.__new__(CardDatabase)
    card_db._activated_ability_ids = None
    card_db._resolve_mtga_db_path = lambda: db_path

    assert card_db.is_activated_ability(373) is True
    assert card_db.is_activated_ability(205151) is False
    assert card_db.is_activated_ability(None) is None


def test_card_database_without_category_column_answers_unknown(tmp_path):
    db_path = tmp_path / "Raw_CardDatabase_old.mtga"
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE "Abilities" ("Id" INTEGER)')
    conn.commit()
    conn.close()

    card_db = CardDatabase.__new__(CardDatabase)
    card_db._activated_ability_ids = None
    card_db._resolve_mtga_db_path = lambda: db_path

    assert card_db.is_activated_ability(373) is None


def test_damage_arena_marks_noncombat_is_not_combat_during_combat(capsys):
    tracker = _tracker(turn=11, active=2)
    tracker.game_state.combat_phase_active = True
    tracker.card_db.names[105191] = "Villain"
    tracker.card_db.names[1002] = "Keen-Eyed Curator"
    attacker = {
        "instanceId": 457,
        "grpId": 105191,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
        "attackInfo": {"targetId": 1},
    }
    tracker.game_state.current_combat_attackers[457] = {"card_name": "Villain", "owner_seat": 2}
    blocker = {"instanceId": 601, "grpId": 1002, "ownerSeatId": 1, "controllerSeatId": 1}

    tracker._handle_damage(
        [601],
        {
            "type": ["AnnotationType_DamageDealt"],
            "affectorId": 457,
            "details": [
                {"key": "damage", "valueInt32": [1]},
                {"key": "type", "valueInt32": [2]},
            ],
        },
        [attacker, blocker],
    )
    out = capsys.readouterr().out

    assert "Combat:" not in out
    assert "[Keen-Eyed Curator] (your) took 1 damage" in out


def test_spell_resolving_without_resolution_start_closes_on_its_resolve_move(capsys):
    tracker = _tracker(turn=10, active=2)
    tracker.card_db.names[105072] = "Mole Man, Moloid Master"
    stack, battlefield = 27, 28
    tracker._register_stack_item(
        538, seat_id=2, label="[Mole Man, Moloid Master (Creature 1/1)]", kind="spell"
    )
    mole_man = {
        "instanceId": 538,
        "grpId": 105072,
        "zoneId": battlefield,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "cardTypes": ["CardType_Creature"],
    }
    # Arena sent ResolutionComplete and the Resolve move, but no ResolutionStart.
    tracker._handle_event(
        _game_state(
            258,
            [
                {
                    "id": 641,
                    "affectorId": 538,
                    "affectedIds": [538],
                    "type": ["AnnotationType_ResolutionComplete"],
                    "details": [{"key": "grpid", "valueInt32": [105072]}],
                },
                {
                    "id": 642,
                    "affectorId": 2,
                    "affectedIds": [538],
                    "type": ["AnnotationType_ZoneTransfer"],
                    "details": [
                        {"key": "zone_src", "valueInt32": [stack]},
                        {"key": "zone_dest", "valueInt32": [battlefield]},
                        {"key": "category", "valueString": ["Resolve"]},
                    ],
                },
            ],
            objects=[mole_man],
            zones=[
                {"zoneId": stack, "type": "ZoneType_Stack"},
                {"zoneId": battlefield, "type": "ZoneType_Battlefield"},
            ],
        )
    )
    tracker._handle_event(_game_state(300, [], diffDeletedInstanceIds=[538]))
    out = capsys.readouterr().out

    assert tracker.game_state.stack_items[538]["status"] == "resolved"
    assert "inferred" not in out


def test_modal_trigger_choice_names_the_card_not_the_ability(capsys):
    tracker = _tracker(turn=4, active=1)
    tracker.card_db.names[95000] = "Treasure Maker"
    tracker.card_db.ability_texts[205190] = "Create a Treasure token."
    # The trigger's ability object, seen in an earlier game-state message.
    tracker.game_state.object_snapshots[612] = {
        "instanceId": 612,
        "grpId": 205191,
        "type": "GameObjectType_Ability",
        "objectSourceGrpId": 95000,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
    }
    tracker._capture_casting_time_options_requests(
        {
            "type": "GREMessageType_CastingTimeOptionsReq",
            "gameStateId": 90,
            "castingTimeOptionsReq": {
                "castingTimeOptionReq": [
                    {
                        "ctoId": 1,
                        "castingTimeOptionType": "CastingTimeOptionType_Modal",
                        "affectedId": 612,
                        "grpId": 205191,
                        "playerIdToPrompt": 1,
                        "modalReq": {"modalOptions": [{"grpId": 205190}, {"grpId": 138314}]},
                    }
                ]
            },
        }
    )
    tracker._handle_client_gre_payload(
        {
            "data": {
                "type": "ClientMessageType_CastingTimeOptionsResp",
                "gameStateId": 90,
                "castingTimeOptionsResp": {
                    "castingTimeOptionResp": {
                        "ctoId": 1,
                        "castingTimeOptionType": "CastingTimeOptionType_Modal",
                        "chooseModalResp": {"grpIds": [205190]},
                    }
                },
            }
        }
    )
    out = capsys.readouterr().out

    assert "chose modes for [Treasure Maker]: Create a Treasure token." in out
    assert "Card #" not in out


# -- second pass: gaps found by replaying 14 games against Arena's own events --

BATTLEFIELD, EXILE, STACK, HAND = 28, 29, 27, 31
LIBRARY, GRAVEYARD = 32, 33
OPP_LIBRARY, OPP_GRAVEYARD = 36, 37
ZONES = [
    {"zoneId": BATTLEFIELD, "type": "ZoneType_Battlefield"},
    {"zoneId": EXILE, "type": "ZoneType_Exile"},
    {"zoneId": STACK, "type": "ZoneType_Stack"},
    {"zoneId": HAND, "type": "ZoneType_Hand", "ownerSeatId": 1},
    {"zoneId": LIBRARY, "type": "ZoneType_Library", "ownerSeatId": 1},
    {"zoneId": GRAVEYARD, "type": "ZoneType_Graveyard", "ownerSeatId": 1},
    {"zoneId": OPP_LIBRARY, "type": "ZoneType_Library", "ownerSeatId": 2},
    {"zoneId": OPP_GRAVEYARD, "type": "ZoneType_Graveyard", "ownerSeatId": 2},
]


def _card(instance_id, grp_id, zone, seat=1, types=("CardType_Creature",), **extra):
    obj = {
        "instanceId": instance_id,
        "grpId": grp_id,
        "type": "GameObjectType_Card",
        "zoneId": zone,
        "ownerSeatId": seat,
        "controllerSeatId": seat,
        "cardTypes": list(types),
    }
    obj.update(extra)
    return obj


def _move(instance_id, src, dest, category, affector=None, ann_id=900):
    annotation = {
        "id": ann_id,
        "affectedIds": [instance_id],
        "type": ["AnnotationType_ZoneTransfer"],
        "details": [
            {"key": "zone_src", "valueInt32": [src]},
            {"key": "zone_dest", "valueInt32": [dest]},
            {"key": "category", "valueString": [category]},
        ],
    }
    if affector is not None:
        annotation["affectorId"] = affector
    return annotation


def _moved(tracker, obj, src, dest, category, affector=None, extra_objects=()):
    tracker._handle_event(
        _game_state(
            700,
            [_move(obj["instanceId"], src, dest, category, affector)],
            objects=[obj, *extra_objects],
            zones=ZONES,
        )
    )


def test_ability_missing_from_its_tokens_card_entry_still_prints(capsys):
    """Jace, a planeswalker token, activates abilities its card entry doesn't list."""
    tracker = _tracker(turn=13, active=2)
    tracker.card_db.names[106555] = "Jace"
    tracker.card_db.ability_texts[208343] = (
        "CARDNAME deals 1 damage to each opponent and you gain 1 life."
    )
    jace = _card(348, 106555, BATTLEFIELD, seat=2, types=("CardType_Planeswalker",))
    jace["type"] = "GameObjectType_Token"
    ability = {
        "instanceId": 456,
        "grpId": 208343,
        "type": "GameObjectType_Ability",
        "zoneId": STACK,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "objectSourceGrpId": 106555,
        "parentId": 348,
    }
    tracker._handle_event(
        _game_state(
            392,
            [
                {
                    "id": 1160,
                    "affectorId": 348,
                    "affectedIds": [456],
                    "type": ["AnnotationType_AbilityInstanceCreated"],
                },
                {
                    "id": 1161,
                    "affectorId": 2,
                    "affectedIds": [456],
                    "type": ["AnnotationType_UserActionTaken"],
                    "details": [
                        {"key": "actionType", "valueInt32": [2]},
                        {"key": "abilityGrpId", "valueInt32": [208343]},
                    ],
                },
            ],
            objects=[jace, ability],
        )
    )
    out = capsys.readouterr().out

    assert "Opponent: [Jace] - Jace deals 1 damage to each opponent and you gain 1 life." in out


def test_unnamed_source_gets_no_fallback_ability_text():
    tracker = _tracker()
    tracker.card_db.names[5] = "Card #5"
    tracker.card_db.ability_texts[300] = "Return that land to the battlefield tapped."

    assert tracker._ability_text_for(5, 300) is None
    assert tracker._ability_text_for(None, 300) is None


def test_enters_trigger_prints_after_its_land(capsys):
    tracker = _tracker(turn=3, active=1)
    tracker.card_db.names[95100] = "Undercity Sewers"
    tracker.card_db.ability_texts[(95100, 95101)] = "When this land enters, surveil 1."
    land = _card(320, 95100, BATTLEFIELD, types=("CardType_Land",))
    trigger = {
        "instanceId": 321,
        "grpId": 95101,
        "type": "GameObjectType_Ability",
        "zoneId": STACK,
        "ownerSeatId": 1,
        "controllerSeatId": 1,
        "objectSourceGrpId": 95100,
        "parentId": 320,
    }
    tracker._handle_event(
        _game_state(
            40,
            [
                _move(320, HAND, BATTLEFIELD, "PlayLand", ann_id=458),
                {
                    "id": 459,
                    "affectorId": 320,
                    "affectedIds": [321],
                    "type": ["AnnotationType_AbilityInstanceCreated"],
                },
            ],
            objects=[land, trigger],
            zones=ZONES,
        )
    )
    out = capsys.readouterr().out

    played = out.index("played [Undercity Sewers")
    assert played < out.index("[Undercity Sewers] - When this land enters, surveil 1.")


def test_deathtouch_and_legend_rule_deaths_are_printed(capsys):
    tracker = _tracker(turn=12, active=1)
    tracker.card_db.names[80001] = "Screaming Nemesis"
    tracker.card_db.names[80002] = "Sarkhan, Dragon Ascendant"
    nemesis = _card(500, 80001, GRAVEYARD)
    sarkhan = _card(501, 80002, GRAVEYARD)
    _moved(tracker, nemesis, BATTLEFIELD, GRAVEYARD, "SBA_Deathtouch")
    _moved(tracker, sarkhan, BATTLEFIELD, GRAVEYARD, "SBA_LegendRule")
    out = capsys.readouterr().out

    assert "You: [Screaming Nemesis] was put into graveyard (deathtouch)" in out
    assert "You: [Sarkhan, Dragon Ascendant] was put into graveyard (legend rule)" in out


def test_surveil_warp_and_library_to_graveyard_moves_are_printed(capsys):
    tracker = _tracker(turn=13, active=2)
    tracker.card_db.names.update(
        {81001: "Blood Crypt", 81002: "Timeline Culler", 81003: "Bitter Triumph"}
    )
    _moved(
        tracker,
        _card(510, 81001, GRAVEYARD, types=("CardType_Land",)),
        LIBRARY,
        GRAVEYARD,
        "Surveil",
    )
    _moved(tracker, _card(511, 81002, EXILE, seat=2), BATTLEFIELD, EXILE, "Warp")
    _moved(
        tracker,
        _card(512, 81003, GRAVEYARD, types=("CardType_Instant",)),
        LIBRARY,
        GRAVEYARD,
        "Put",
    )
    out = capsys.readouterr().out

    assert "You: surveilled [Blood Crypt] into graveyard" in out
    assert "Opponent: [Timeline Culler] was exiled (warp)" in out
    assert "You: [Bitter Triumph] was put into graveyard from library" in out


def test_bottomed_mulligan_card_still_prints_nothing(capsys):
    tracker = _tracker(turn=1, active=1)
    tracker.card_db.names[81004] = "Swamp"
    _moved(tracker, _card(513, 81004, LIBRARY, types=("CardType_Land",)), HAND, LIBRARY, "Put")

    assert "Swamp" not in capsys.readouterr().out


def test_manifests_name_only_the_cards_you_can_see(capsys):
    tracker = _tracker(turn=13, active=2)
    tracker.card_db.names[81005] = "Dark Matter Manipulator"
    tracker.card_db.names[3] = "Card #3"
    _moved(tracker, _card(520, 81005, BATTLEFIELD), LIBRARY, BATTLEFIELD, "ManifestLike")
    _moved(tracker, _card(521, 3, BATTLEFIELD, seat=2), OPP_LIBRARY, BATTLEFIELD, "ManifestLike")
    out = capsys.readouterr().out

    assert "You: manifested [Dark Matter Manipulator]" in out
    assert "Opponent: manifested a face-down card" in out
    assert "Card #3" not in out


def test_copied_spell_names_the_copy_and_its_source(capsys):
    tracker = _tracker(turn=13, active=2)
    tracker.card_db.names[106555] = "Jace"
    tracker.card_db.names[96662] = "Archenemy's Charm"
    delayed_trigger = {
        "instanceId": 462,
        "grpId": 208434,
        "type": "GameObjectType_Ability",
        "zoneId": STACK,
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "objectSourceGrpId": 106555,
        "parentId": 348,
    }
    copy = _card(464, 96662, STACK, seat=2, types=("CardType_Instant",), isCopy=True)
    _moved(tracker, copy, STACK, STACK, "Copy", affector=462, extra_objects=[delayed_trigger])

    assert "Opponent: [Jace] copied [Archenemy's Charm]" in capsys.readouterr().out


def test_room_entering_as_the_whole_card_is_not_a_change(capsys):
    tracker = _tracker(turn=4, active=1)
    tracker.card_db.names[82001] = "Unholy Annex"
    tracker.card_db.names[82002] = "Unholy Annex // Ritual Chamber"
    door = _card(530, 82001, BATTLEFIELD, types=("CardType_Enchantment",))
    room = dict(door, grpId=82002)
    tracker._maybe_log_identity_change(530, door, room)

    assert "became" not in capsys.readouterr().out


def test_mode_without_a_target_does_not_borrow_another_modes_target(capsys):
    tracker = _tracker(turn=9, active=2)
    tracker.card_db.names[83001] = "Craftwork Crusher"
    tracker.card_db.names[83002] = "Ral Zarek, Guest Lecturer"
    tracker.card_db.ability_texts[(83001, 83011)] = (
        "This creature deals 4 damage to target creature or planeswalker."
    )
    tracker.card_db.ability_texts[(83001, 83012)] = "Create a 2/2 colorless Wizard Soldier token."
    crusher = _card(540, 83001, BATTLEFIELD, seat=2)
    ral = _card(541, 83002, BATTLEFIELD, types=("CardType_Planeswalker",))
    tracker.game_state.ability_instance_sources[542] = 540
    tracker.game_state.ability_targets_by_instance = {542: [541]}
    tracker._target_ids_for_instance = lambda instance_id: [541] if instance_id == 542 else []
    for grp in (83011, 83012):
        tracker._handle_resolution_start(
            [542], [{"key": "grpid", "valueInt32": [grp]}], {540: crusher, 541: ral}
        )
    out = capsys.readouterr().out

    assert "deals 4 damage to target creature or planeswalker. -> [Ral Zarek" in out
    assert "Wizard Soldier token. ->" not in out


def test_multi_line_ability_text_prints_on_one_line():
    tracker = _tracker()
    text = "When this creature enters, choose two —\n•Deal 4 damage.\n•Create a token."

    assert tracker._normalize_ability_text(text) == (
        "When this creature enters, choose two — •Deal 4 damage. •Create a token."
    )


def _revealed(instance_id, grp_id, seat=2, zone=HAND + 4):
    return {
        "instanceId": instance_id,
        "grpId": grp_id,
        "type": "GameObjectType_RevealedCard",
        "zoneId": zone,
        "ownerSeatId": seat,
        "controllerSeatId": seat,
        "visibility": "Visibility_Private",
        "viewers": [1],
    }


def _reveal_annotation(instance_id):
    return {
        "id": 1000 + instance_id,
        "affectorId": instance_id,
        "affectedIds": [instance_id],
        "type": ["AnnotationType_RevealedCardCreated"],
    }


def test_opponents_revealed_hand_prints_once_on_one_line(capsys):
    tracker = _tracker(turn=14, active=1)
    tracker.card_db.names.update({84001: "Belladonna Took", 84002: "Ultima"})
    zones = ZONES + [{"zoneId": HAND + 4, "type": "ZoneType_Hand", "ownerSeatId": 2}]
    proxies = [_revealed(446, 84001), _revealed(447, 84002)]
    message = _game_state(
        297, [_reveal_annotation(446), _reveal_annotation(447)], objects=proxies, zones=zones
    )
    tracker._handle_event(message)
    tracker._handle_event(message)  # Arena re-sends; the same proxies print once.
    out = capsys.readouterr().out

    assert out.count("Opponent: revealed [Belladonna Took], [Ultima] from hand") == 1


def test_own_hand_revealed_without_names_prints_nothing(capsys):
    tracker = _tracker(turn=2, active=2)
    tracker._handle_event(_game_state(32, [_reveal_annotation(460)], zones=ZONES))

    assert "revealed" not in capsys.readouterr().out
