"""Replay capture: structured ``game_events`` rows (replay_version = 1).

Minimal GameStateMessage payloads in the style of
tests/test_tracker_combat_winner.py, plus one scripted synthetic game that is
replayed end to end for the console-identity snapshot, the storage budget and
the per-message timing bound. Contract: docs/REPLAY_FORMAT.md section 1.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tracker_combat_winner import make_tracker  # noqa: E402

from mtga_tracker.replay_capture import INSERT_EVENT_SQL, REPLAY_VERSION  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
BASELINE_PATH = FIXTURE_DIR / "replay_capture_baseline.json"

# The local player sits in seat 2 on purpose: seats are never assumed.
P, O = 2, 1
HAND = {O: 31, P: 35}
LIB = {O: 32, P: 36}
GY = {O: 33, P: 37}
REVEALED = {O: 18, P: 19}
STACK, BF, EXILE, LIMBO = 27, 28, 29, 30

NAMES = {
    1001: "Forest",
    1002: "Llanowar Elves",
    1003: "Giant Growth",
    1004: "Grizzly Bears",
    1005: "Rancor",
    1006: "Ajani's Pridemate",
    1008: "Island",
    2001: "Mountain",
    2002: "Shock",
    2003: "Goblin Guide",
    2004: "Krenko's Command",
    2100: "Goblin",
}
TYPES = {
    1001: ["CardType_Land"],
    1008: ["CardType_Land"],
    2001: ["CardType_Land"],
    1002: ["CardType_Creature"],
    1004: ["CardType_Creature"],
    1006: ["CardType_Creature"],
    2003: ["CardType_Creature"],
    2100: ["CardType_Creature"],
    1003: ["CardType_Instant"],
    2002: ["CardType_Instant"],
    2004: ["CardType_Sorcery"],
    1005: ["CardType_Enchantment"],
}
PT = {1002: (1, 1), 1004: (2, 2), 1006: (2, 2), 2003: (2, 2), 2100: (1, 1)}


def _zone_defs() -> Dict[int, Dict[str, Any]]:
    zones = {
        STACK: {"zoneId": STACK, "type": "ZoneType_Stack"},
        BF: {"zoneId": BF, "type": "ZoneType_Battlefield"},
        EXILE: {"zoneId": EXILE, "type": "ZoneType_Exile"},
        LIMBO: {"zoneId": LIMBO, "type": "ZoneType_Limbo"},
    }
    for seat in (O, P):
        zones[HAND[seat]] = {"zoneId": HAND[seat], "type": "ZoneType_Hand", "ownerSeatId": seat}
        zones[LIB[seat]] = {"zoneId": LIB[seat], "type": "ZoneType_Library", "ownerSeatId": seat}
        zones[GY[seat]] = {"zoneId": GY[seat], "type": "ZoneType_Graveyard", "ownerSeatId": seat}
        zones[REVEALED[seat]] = {
            "zoneId": REVEALED[seat],
            "type": "ZoneType_Revealed",
            "ownerSeatId": seat,
        }
    return zones


class GameSim:
    """Tiny GRE simulator: keeps zones and objects consistent across diffs."""

    def __init__(self, start: datetime):
        self.zone_meta = _zone_defs()
        self.contents: Dict[int, List[int]] = {zone_id: [] for zone_id in self.zone_meta}
        self.objects: Dict[int, Dict[str, Any]] = {}
        self.lines: List[Tuple[str, datetime]] = []
        self.clock = start
        self.gsid = 0
        self.turn: Optional[int] = None
        self.active: Optional[int] = None
        self.phase: Optional[str] = None
        self.step: Optional[str] = None
        self.life = {O: 20, P: 20}

    # -- objects ---------------------------------------------------------
    def card(self, iid: int, grp: Optional[int], owner: int, zone: int, **extra) -> int:
        obj: Dict[str, Any] = {
            "instanceId": iid,
            "type": extra.pop("obj_type", "GameObjectType_Card"),
            "zoneId": zone,
            "visibility": "Visibility_Public" if grp else "Visibility_Private",
            "ownerSeatId": owner,
            "controllerSeatId": owner,
        }
        if grp:
            obj["grpId"] = grp
            obj["cardTypes"] = list(TYPES.get(grp, []))
            if grp in PT:
                obj["power"] = {"value": PT[grp][0]}
                obj["toughness"] = {"value": PT[grp][1]}
        obj.update(extra)
        self.objects[iid] = obj
        self.contents[zone].append(iid)
        return iid

    def move(self, iid: int, new_iid: int, dest: int, grp: Optional[int] = None) -> Dict[str, Any]:
        obj = self.objects.pop(iid)
        self.contents[obj["zoneId"]].remove(iid)
        obj = dict(obj)
        obj["instanceId"] = new_iid
        obj["zoneId"] = dest
        obj.pop("isTapped", None)
        obj.pop("attackState", None)
        obj.pop("attackInfo", None)
        obj.pop("blockState", None)
        if grp:
            obj["grpId"] = grp
            obj["visibility"] = "Visibility_Public"
            obj["cardTypes"] = list(TYPES.get(grp, []))
            if grp in PT:
                obj["power"] = {"value": PT[grp][0]}
                obj["toughness"] = {"value": PT[grp][1]}
        self.objects[new_iid] = obj
        self.contents[dest].append(new_iid)
        return obj

    def set(self, iid: int, **fields) -> None:
        obj = self.objects[iid]
        for key, value in fields.items():
            if value is None:
                obj.pop(key, None)
            else:
                obj[key] = value

    # -- messages --------------------------------------------------------
    def emit(
        self,
        changed: Tuple[int, ...] = (),
        annotations: Tuple[Dict[str, Any], ...] = (),
        *,
        players: Optional[List[Dict[str, Any]]] = None,
        persistent: Tuple[Dict[str, Any], ...] = (),
        deleted: Tuple[int, ...] = (),
        game_info: Optional[Dict[str, Any]] = None,
        seconds: int = 3,
    ) -> None:
        self.gsid += 1
        self.clock += timedelta(seconds=seconds)
        payload: Dict[str, Any] = {"gameStateId": self.gsid, "type": "GameStateType_Diff"}
        turn_info: Dict[str, Any] = {}
        if self.turn is not None:
            turn_info["turnNumber"] = self.turn
        if self.active is not None:
            turn_info["activePlayer"] = self.active
        if self.phase:
            turn_info["phase"] = self.phase
        if self.step:
            turn_info["step"] = self.step
        if turn_info:
            payload["turnInfo"] = turn_info
        zones = []
        for zone_id, meta in self.zone_meta.items():
            zone = dict(meta)
            zone["objectInstanceIds"] = list(self.contents[zone_id])
            zones.append(zone)
        payload["zones"] = zones
        visible = [
            copy.deepcopy(self.objects[iid])
            for iid in changed
            if iid in self.objects and self.objects[iid].get("grpId")
        ]
        if visible:
            payload["gameObjects"] = visible
        if annotations:
            payload["annotations"] = [
                dict(ann, id=self.gsid * 100 + i) for i, ann in enumerate(annotations)
            ]
        if persistent:
            payload["persistentAnnotations"] = list(persistent)
        if players is not None:
            payload["players"] = players
        if deleted:
            payload["diffDeletedInstanceIds"] = list(deleted)
        if game_info is not None:
            payload["gameInfo"] = game_info
        self.lines.append((json.dumps({"gameStateMessage": payload}), self.clock))

    def turn_to(self, turn: int, active: int) -> None:
        self.turn, self.active = turn, active
        self.phase, self.step = "Phase_Beginning", "Step_Upkeep"

    def phase_to(self, phase: str, step: Optional[str] = None) -> None:
        self.phase, self.step = phase, step

    def players(self, **mulligans) -> List[Dict[str, Any]]:
        out = []
        for seat in (O, P):
            entry: Dict[str, Any] = {"systemSeatNumber": seat, "lifeTotal": self.life[seat]}
            count = mulligans.get(f"seat{seat}")
            if count:
                entry["mulliganCount"] = count
            out.append(entry)
        return out


def zt(iid: int, src: int, dst: int, category: str, affector: Optional[int] = None):
    ann: Dict[str, Any] = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [iid],
        "details": [
            {"key": "zone_src", "valueInt32": [src]},
            {"key": "zone_dest", "valueInt32": [dst]},
            {"key": "category", "valueString": [category]},
        ],
    }
    if affector is not None:
        ann["affectorId"] = affector
    return ann


def oic(orig: int, new: int, affector: Optional[int] = None):
    ann: Dict[str, Any] = {
        "type": ["AnnotationType_ObjectIdChanged"],
        "affectedIds": [orig],
        "details": [
            {"key": "orig_id", "valueInt32": [orig]},
            {"key": "new_id", "valueInt32": [new]},
        ],
    }
    if affector is not None:
        ann["affectorId"] = affector
    return ann


def ann(kind: str, affected: List[int], affector: Optional[int] = None, **details):
    out: Dict[str, Any] = {"type": [f"AnnotationType_{kind}"], "affectedIds": list(affected)}
    if affector is not None:
        out["affectorId"] = affector
    if details:
        out["details"] = [
            {"key": key, "valueInt32": value if isinstance(value, list) else [value]}
            for key, value in details.items()
        ]
    return out


def build_synthetic_game(start: Optional[datetime] = None) -> List[Tuple[str, datetime]]:
    """An eight-turn game with every replay event kind; the local player is seat 2."""
    g = GameSim(start or datetime(2026, 10, 1, 20, 0, 0))
    # Libraries: hidden ids. Hands: hand A (mulliganed), opponent hidden.
    for i in range(53):
        g.card(300 + i, None, P, LIB[P])
        g.card(400 + i, None, O, LIB[O])
    hand_a = [1001, 1001, 1001, 1001, 1001, 1008, 1008]
    for i, grp in enumerate(hand_a):
        g.card(201 + i, grp, P, HAND[P])
    for i in range(7):
        g.card(101 + i, None, O, HAND[O])
    mull = [
        {"systemSeatNumber": O, "pendingMessageType": "ClientMessageType_MulliganResp"},
        {"systemSeatNumber": P, "pendingMessageType": "ClientMessageType_MulliganResp"},
    ]
    g.emit(tuple(range(201, 208)), players=mull)
    # Mulligan both: new hands (new ids), both seats report mulliganCount 1.
    for i in range(7):
        g.objects.pop(201 + i)
        g.contents[HAND[P]].remove(201 + i)
        g.objects.pop(101 + i)
        g.contents[HAND[O]].remove(101 + i)
    hand_b = [1001, 1002, 1001, 1004, 1006, 1005, 1008]
    for i, grp in enumerate(hand_b):
        g.card(211 + i, grp, P, HAND[P])
    for i in range(7):
        g.card(111 + i, None, O, HAND[O])
    mull2 = [dict(mull[0], mulliganCount=1), dict(mull[1], mulliganCount=1)]
    g.emit(tuple(range(211, 218)), players=mull2)
    # Bottom one card each; turn 1 begins (opponent on the play).
    g.move(217, 290, LIB[P])
    g.objects.pop(117)
    g.contents[HAND[O]].remove(117)
    g.card(190, None, O, LIB[O])
    g.turn_to(1, O)
    g.emit(tuple(range(211, 217)), players=g.players(seat1=1, seat2=1))

    # Turn 1 (opponent): land.
    g.phase_to("Phase_Main1")
    g.move(111, 120, BF, grp=2001)
    g.emit((120,), (oic(111, 120), zt(120, HAND[O], BF, "PlayLand")))
    g.phase_to("Phase_Ending", "Step_End")
    g.emit()

    # Turn 2 (you): draw, land, Llanowar Elves (resolves silently).
    g.turn_to(2, P)
    g.emit()
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(300, 230, HAND[P], grp=1001)
    g.emit((230,), (oic(300, 230), zt(230, LIB[P], HAND[P], "Draw")))
    g.phase_to("Phase_Main1")
    g.move(230, 231, BF)
    g.emit((231,), (oic(230, 231), zt(231, HAND[P], BF, "PlayLand")))
    g.move(212, 232, STACK)
    g.set(231, isTapped=True)
    g.emit((232, 231), (oic(212, 232), zt(232, HAND[P], STACK, "CastSpell")))
    g.move(232, 232, BF)
    g.set(232, hasSummoningSickness=True)
    g.emit(
        (232,),
        (
            ann("ResolutionStart", [232], 232, grpid=1002),
            zt(232, STACK, BF, "Resolve"),
            ann("ResolutionComplete", [232], 232, grpid=1002),
        ),
    )
    g.phase_to("Phase_Ending", "Step_End")
    g.emit()

    # Turn 3 (opponent): hidden draw, land, Goblin Guide, attack for 2.
    g.turn_to(3, O)
    g.emit()
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(400, 133, HAND[O])
    g.emit((), (oic(400, 133), zt(133, LIB[O], HAND[O], "Draw")))
    g.phase_to("Phase_Main1")
    g.move(133, 134, BF, grp=2001)
    g.emit((134,), (oic(133, 134), zt(134, HAND[O], BF, "PlayLand")))
    g.move(112, 135, STACK, grp=2003)
    g.set(120, isTapped=True)
    g.emit((135, 120), (oic(112, 135), zt(135, HAND[O], STACK, "CastSpell")))
    g.move(135, 135, BF)
    g.emit((135,), (ann("ResolutionStart", [135], 135, grpid=2003), zt(135, STACK, BF, "Resolve")))
    g.phase_to("Phase_Combat", "Step_DeclareAttack")
    g.set(135, isTapped=True, attackState="AttackState_Declared", attackInfo={"targetId": P})
    g.emit((135,))
    g.phase_to("Phase_Combat", "Step_CombatDamage")
    g.life[P] = 18
    g.emit((), (ann("DamageDealt", [P], 135, damage=2),), players=g.players())
    g.phase_to("Phase_Ending", "Step_End")
    g.set(135, attackState=None, attackInfo=None)
    g.emit((135,))

    # Turn 4 (you): untap, draw, land, Grizzly Bears; Shock in response kills the Elves.
    g.turn_to(4, P)
    g.set(231, isTapped=None)
    g.set(232, hasSummoningSickness=None)
    g.emit((231, 232))
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(301, 240, HAND[P], grp=1001)
    g.emit((240,), (oic(301, 240), zt(240, LIB[P], HAND[P], "Draw")))
    g.phase_to("Phase_Main1")
    g.move(240, 241, BF)
    g.emit((241,), (oic(240, 241), zt(241, HAND[P], BF, "PlayLand")))
    g.move(214, 242, STACK)
    g.set(231, isTapped=True)
    g.set(241, isTapped=True)
    g.emit((242, 231, 241), (oic(214, 242), zt(242, HAND[P], STACK, "CastSpell")))
    g.move(113, 243, STACK, grp=2002)
    g.set(134, isTapped=True)
    g.emit(
        (243, 134),
        (oic(113, 243), zt(243, HAND[O], STACK, "CastSpell")),
        persistent=(
            {
                "type": ["AnnotationType_TargetSpec"],
                "affectorId": 243,
                "affectedIds": [232],
                "id": 9001,
            },
        ),
    )
    g.move(243, 243, GY[O])
    g.move(232, 244, GY[P])
    g.emit(
        (243, 244),
        (
            ann("ResolutionStart", [243], 243, grpid=2002),
            ann("DamageDealt", [232], 243, damage=2),
            zt(243, STACK, GY[O], "Resolve"),
            oic(232, 244),
            zt(244, BF, GY[P], "SBA_Damage"),
        ),
        deleted=(232,),
    )
    g.move(242, 242, BF)
    g.emit((242,), (ann("ResolutionStart", [242], 242, grpid=1004), zt(242, STACK, BF, "Resolve")))
    g.phase_to("Phase_Ending", "Step_End")
    g.emit()

    # Turn 5 (opponent): Krenko's Command makes two Goblins; Guide attacks into Bears.
    g.turn_to(5, O)
    g.set(120, isTapped=None)
    g.set(134, isTapped=None)
    g.set(135, isTapped=None)
    g.emit((120, 134, 135))
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(401, 150, HAND[O])
    g.emit((), (oic(401, 150), zt(150, LIB[O], HAND[O], "Draw")))
    g.phase_to("Phase_Main1")
    g.move(150, 151, STACK, grp=2004)
    g.set(120, isTapped=True)
    g.set(134, isTapped=True)
    g.emit((151, 120, 134), (oic(150, 151), zt(151, HAND[O], STACK, "CastSpell")))
    g.card(152, 2100, O, BF, obj_type="GameObjectType_Token")
    g.card(153, 2100, O, BF, obj_type="GameObjectType_Token")
    g.move(151, 151, GY[O])
    g.emit(
        (152, 153, 151),
        (
            ann("ResolutionStart", [151], 151, grpid=2004),
            ann("TokenCreated", [152], 151),
            ann("TokenCreated", [153], 151),
            zt(151, STACK, GY[O], "Resolve"),
        ),
    )
    g.phase_to("Phase_Combat", "Step_DeclareAttack")
    g.set(135, isTapped=True, attackState="AttackState_Declared", attackInfo={"targetId": P})
    g.emit((135,))
    g.phase_to("Phase_Combat", "Step_DeclareBlock")
    g.set(242, blockState="BlockState_Blocking")
    g.emit((242,), (ann("BlockerDeclared", [242], 242, attacker_id=135),))
    g.phase_to("Phase_Combat", "Step_CombatDamage")
    g.set(135, damage=2)
    g.set(242, damage=2)
    g.emit(
        (135, 242),
        (
            ann("DamageDealt", [135], 242, damage=2),
            ann("DamageDealt", [242], 135, damage=2),
        ),
    )
    g.move(135, 160, GY[O])
    g.move(242, 161, GY[P])
    g.emit(
        (160, 161),
        (
            oic(135, 160),
            zt(160, BF, GY[O], "SBA_Damage"),
            oic(242, 161),
            zt(161, BF, GY[P], "SBA_Damage"),
        ),
        deleted=(135, 242),
    )
    g.phase_to("Phase_Ending", "Step_End")
    g.emit()

    # Turn 6 (you): Ajani's Pridemate, Rancor on it, life gain + counter, attack for 5.
    g.turn_to(6, P)
    g.set(231, isTapped=None)
    g.set(241, isTapped=None)
    g.emit((231, 241))
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(302, 170, HAND[P], grp=1003)
    g.emit((170,), (oic(302, 170), zt(170, LIB[P], HAND[P], "Draw")))
    g.phase_to("Phase_Main1")
    g.move(215, 171, STACK)
    g.set(231, isTapped=True)
    g.set(241, isTapped=True)
    g.emit((171, 231, 241), (oic(215, 171), zt(171, HAND[P], STACK, "CastSpell")))
    g.move(171, 171, BF)
    g.emit((171,), (ann("ResolutionStart", [171], 171, grpid=1006), zt(171, STACK, BF, "Resolve")))
    g.move(216, 172, STACK)
    g.emit(
        (172,),
        (oic(216, 172), zt(172, HAND[P], STACK, "CastSpell")),
        persistent=(
            {
                "type": ["AnnotationType_TargetSpec"],
                "affectorId": 172,
                "affectedIds": [171],
                "id": 9002,
            },
        ),
    )
    g.move(172, 172, BF)
    g.set(171, power={"value": 4})
    g.emit(
        (172, 171),
        (
            ann("ResolutionStart", [172], 172, grpid=1005),
            zt(172, STACK, BF, "Resolve"),
            ann("AttachmentCreated", [171], 172),
            ann("PowerToughnessModCreated", [171], 172, power=2, toughness=0),
        ),
    )
    g.life[P] = 19
    g.set(171, power={"value": 5}, toughness={"value": 3})
    g.emit(
        (171,),
        (
            ann("ModifiedLife", [P], 171, life=1),
            ann("CounterAdded", [171], 171, counter_type=1, transaction_amount=1),
        ),
        players=g.players(),
    )
    g.phase_to("Phase_Combat", "Step_DeclareAttack")
    g.set(171, isTapped=True, attackState="AttackState_Declared", attackInfo={"targetId": O})
    g.emit((171,))
    g.phase_to("Phase_Combat", "Step_CombatDamage")
    g.life[O] = 15
    g.emit((), (ann("DamageDealt", [O], 171, damage=5),), players=g.players())
    g.phase_to("Phase_Ending", "Step_End")
    g.set(171, attackState=None, attackInfo=None)
    g.emit((171,))

    # Turn 7 (opponent): sacrifice a Goblin, shuffle, reveal; Pridemate loses its counter.
    g.turn_to(7, O)
    g.set(120, isTapped=None)
    g.set(134, isTapped=None)
    g.emit((120, 134))
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(402, 180, HAND[O])
    g.emit((), (oic(402, 180), zt(180, LIB[O], HAND[O], "Draw")))
    g.phase_to("Phase_Main1")
    g.move(152, 152, GY[O])
    old_ids = list(g.contents[LIB[O]])
    new_ids = [600 + i for i in range(len(old_ids))]
    for old, new in zip(old_ids, new_ids):
        g.move(old, new, LIB[O])
    g.card(181, 2001, O, REVEALED[O], obj_type="GameObjectType_RevealedCard")
    g.emit(
        (152, 181),
        (
            zt(152, BF, GY[O], "Sacrifice", affector=153),
            ann("TokenDeleted", [152], 152),
            {
                "type": ["AnnotationType_Shuffle"],
                "affectedIds": [O],
                "affectorId": 153,
                "details": [
                    {"key": "OldIds", "valueInt32": old_ids},
                    {"key": "NewIds", "valueInt32": new_ids},
                ],
            },
            ann("RevealedCardCreated", [181], 181),
        ),
        deleted=(152,),
    )
    g.set(171, power={"value": 4}, toughness={"value": 2})
    g.set(241, grpId=1008)
    g.emit(
        (171, 241),
        (ann("CounterRemoved", [171], 153, counter_type=1, transaction_amount=1),),
    )
    g.phase_to("Phase_Ending", "Step_End")
    g.emit()

    # Turn 8 (you): untap, draw, attack for 4; the opponent concedes.
    g.turn_to(8, P)
    g.set(231, isTapped=None)
    g.set(241, isTapped=None)
    g.set(171, isTapped=None)
    g.emit((231, 241, 171))
    g.phase_to("Phase_Beginning", "Step_Draw")
    g.move(303, 190, HAND[P], grp=1001)
    g.emit((190,), (oic(303, 190), zt(190, LIB[P], HAND[P], "Draw")))
    g.phase_to("Phase_Combat", "Step_DeclareAttack")
    g.set(171, isTapped=True, attackState="AttackState_Declared", attackInfo={"targetId": O})
    g.emit((171,))
    g.phase_to("Phase_Combat", "Step_CombatDamage")
    g.life[O] = 11
    g.emit((), (ann("DamageDealt", [O], 171, damage=4),), players=g.players())
    g.emit(
        game_info={
            "stage": "GameStage_GameOver",
            "matchState": "MatchState_GameComplete",
            "results": [
                {
                    "scope": "MatchScope_Game",
                    "result": "ResultType_WinLoss",
                    "winningTeamId": P,
                    "reason": "ResultReason_Concede",
                }
            ],
        }
    )
    return g.lines


def synthetic_tracker(tmp_path: Path):
    tracker = make_tracker()
    tracker.card_db.names.update(NAMES)
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker._start_opponent_archetype_lookup = lambda game_id: None
    return tracker


def run_synthetic_game(tracker, lines) -> None:
    for line, stamp in lines:
        tracker._process_line(line, timestamp=stamp)
    if tracker.game_state.match_complete and tracker._pending_game_summary:
        tracker._print_game_summary()
        tracker._pending_game_summary = False


PRINTED_COLUMNS = (
    "event_time, elapsed_seconds, turn_number, phase, step, participant_id, seat_id, "
    "actor_role, event_type, text, player_life, opponent_life"
)


def printed_rows(db_path: Path) -> List[List[Any]]:
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(game_events)")}
        where = "WHERE visible = 1 " if "visible" in columns else ""
        return [
            list(row)
            for row in conn.execute(f"SELECT {PRINTED_COLUMNS} FROM game_events {where}ORDER BY id")
        ]


ROW_COLUMNS = (
    "id, visible, turn_number, phase, step, participant_id, seat_id, actor_role, event_type, "
    "event_subtype, object_id, target_object_id, arena_id, controller_seat, zone_from, zone_to, "
    "amount, payload_json, text, session_id, match_id, game_id"
)


def event_rows(db_path: Path, where: str = "1 = 1", params: tuple = ()) -> List[Dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        out = []
        for row in conn.execute(
            f"SELECT {ROW_COLUMNS} FROM game_events WHERE {where} ORDER BY id", params
        ):
            item = dict(row)
            item["payload"] = json.loads(item["payload_json"]) if item["payload_json"] else None
            out.append(item)
        return out


def kinds(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["event_subtype"] for row in rows]


def _played(tmp_path: Path):
    tracker = synthetic_tracker(tmp_path)
    run_synthetic_game(tracker, build_synthetic_game())
    return tracker, tmp_path / "analytics.sqlite3"


# -- synthetic game: one assertion group per contract kind -----------------


def test_console_and_printed_rows_match_the_pre_replay_baseline(tmp_path, capsys):
    """Byte-identical console; printed rows identical except seat_id, which a
    fact may fill only where the old text-based inference found no actor."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    tracker, db = _played(tmp_path)
    console = capsys.readouterr().out.splitlines()
    # The analytics store's own VACUUM notice goes to stdout, not the tracker.
    console = [line for line in console if "VACUUM" not in line and "compacted" not in line]
    assert console == baseline["console"]
    rows = printed_rows(db)
    assert len(rows) == len(baseline["rows"])
    seat = PRINTED_COLUMNS.split(", ").index("seat_id")
    for old, new in zip(baseline["rows"], rows):
        if old[seat] is None:
            new = list(new)
            new[seat] = None
        assert list(new) == old


def test_every_row_of_a_recorded_game_is_classified(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    assert rows and all(row["event_subtype"] for row in rows)
    printed = [row for row in rows if row["visible"] == 1]
    silent = [row for row in rows if row["visible"] == 0]
    assert printed and silent
    for row in silent:
        assert row["participant_id"] is None
        assert row["event_type"] is None
        # Silent rows key on game_id only (session_id is the NOT NULL column's "").
        assert row["game_id"] and row["session_id"] == "" and row["match_id"] is None
        assert len(row["text"]) <= 24
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT replay_version FROM games").fetchall() == [(REPLAY_VERSION,)]


def test_mulligans_and_opening_hands_by_instance_id(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    mulligans = [row for row in rows if row["event_subtype"] == "mulligan"]
    assert {row["seat_id"] for row in mulligans} == {O, P}
    assert all(row["payload"] == {"from_size": 7, "to_size": 6} for row in mulligans)
    assert all(row["amount"] == 6 for row in mulligans)
    opening = [row for row in rows if (row["payload"] or {}).get("opening")]
    mine = [row for row in opening if row["seat_id"] == P]
    theirs = [row for row in opening if row["seat_id"] == O]
    assert [row["object_id"] for row in mine] == [211, 212, 213, 214, 215, 216]
    assert mine[1]["arena_id"] == 1002 and mine[1]["payload"]["name"] == "Llanowar Elves"
    assert [row["object_id"] for row in theirs] == [111, 112, 113, 114, 115, 116]
    assert all(row["arena_id"] is None and "name" not in row["payload"] for row in theirs)
    assert all((row["zone_from"], row["zone_to"]) == ("library", "hand") for row in opening)
    first_turn = next(row["id"] for row in rows if row["event_subtype"] == "turn")
    assert max(row["id"] for row in opening) < first_turn


def test_turn_and_lazy_phase_rows(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    turns = [row for row in rows if row["event_subtype"] == "turn"]
    assert [row["payload"]["active_seat"] for row in turns] == [O, P, O, P, O, P, O, P]
    assert all(
        row["visible"] == 1 and row["seat_id"] == row["payload"]["active_seat"] for row in turns
    )
    phases = [row for row in rows if row["event_subtype"] == "phase"]
    assert phases and all(row["visible"] == 0 for row in phases)
    combat = [row for row in phases if row["phase"] == "Phase_Combat"]
    assert combat and combat[0]["step"] == "Step_DeclareAttack"
    # A phase row is written only when something happens in that phase:
    # every phase row is followed by a non-phase row of the same turn.
    for row in phases:
        following = next(r for r in rows if r["id"] > row["id"])
        assert following["event_subtype"] != "phase"
        assert following["turn_number"] == row["turn_number"]
    # Main 1 of turn 1 carries no stale step from the pre-game turnInfo.
    assert phases[0]["phase"] == "Phase_Main1" and phases[0]["step"] is None


def test_land_and_draws_named_and_hidden(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    lands = [row for row in rows if row["event_type"] == "land"]
    assert lands[0]["event_subtype"] == "move"
    assert (lands[0]["zone_from"], lands[0]["zone_to"]) == ("hand", "battlefield")
    assert lands[0]["payload"]["reason"] == "play_land" and lands[0]["object_id"] == 111
    draws = [row for row in rows if row["event_type"] == "draw"]
    mine = next(row for row in draws if row["seat_id"] == P)
    assert mine["payload"] == {"reason": "draw", "name": "Forest", "type": "Land"}
    assert (mine["object_id"], mine["arena_id"]) == (300, 1001)
    theirs = next(row for row in draws if row["seat_id"] == O)
    assert theirs["object_id"] == 400 and theirs["arena_id"] is None
    assert theirs["payload"] == {"reason": "draw"}
    # The hidden card keeps its root id when it is played from hand.
    assert lands[2]["object_id"] == 400 and lands[2]["arena_id"] == 2001


def test_cast_pushes_stack_item_and_resolves_to_battlefield_or_graveyard(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    pushes = {
        row["payload"]["stack_id"]: row for row in rows if row["event_subtype"] == "stack_push"
    }
    elves = pushes["s1"]
    assert elves["visible"] == 1 and elves["event_type"] == "cast"
    assert (elves["object_id"], elves["arena_id"], elves["seat_id"]) == (212, 1002, P)
    assert (elves["zone_from"], elves["zone_to"]) == ("hand", "stack")
    assert (
        elves["payload"]["stack_kind"] == "spell" and elves["payload"]["name"] == "Llanowar Elves"
    )
    # The opponent's spell is named from the stack object, not the hidden hand card.
    assert pushes["s2"]["arena_id"] == 2003 and pushes["s2"]["object_id"] == 112
    # No separate hand->stack move is written: stack_push carries zone_from.
    assert not [
        row
        for row in rows
        if row["event_subtype"] == "move" and (row["payload"] or {}).get("reason") == "cast"
    ]
    # Silent resolve, then the silent move to the battlefield.
    resolve = next(
        r
        for r in rows
        if r["event_subtype"] == "stack_resolve" and r["payload"]["stack_id"] == "s1"
    )
    assert resolve["visible"] == 0
    move = next(r for r in rows if r["id"] > resolve["id"] and r["event_subtype"] == "move")
    assert (move["object_id"], move["zone_from"], move["zone_to"]) == (212, "stack", "battlefield")
    assert move["payload"]["reason"] == "resolve" and move["visible"] == 0
    # Shock (instant, printed lifecycle line) resolves to the graveyard.
    shock = pushes["s4"]
    assert shock["payload"]["targets"] == [212] and shock["target_object_id"] == 212
    shock_resolve = next(
        r
        for r in rows
        if r["event_subtype"] == "stack_resolve" and r["payload"]["stack_id"] == "s4"
    )
    assert shock_resolve["visible"] == 1 and shock_resolve["event_type"] == "stack_resolve"
    shock_move = next(
        r
        for r in rows
        if r["event_subtype"] == "move" and r["object_id"] == 113 and r["zone_from"] == "stack"
    )
    assert shock_move["zone_to"] == "graveyard" and shock_move["id"] > shock_resolve["id"]
    # Krenko's Command (sorcery) also lands in the graveyard.
    assert any(
        r["object_id"] == 401 and r["zone_from"] == "stack" and r["zone_to"] == "graveyard"
        for r in rows
        if r["event_subtype"] == "move"
    )


def test_root_ids_survive_object_id_changes(tmp_path):
    """Llanowar Elves is 212 in hand, 232 on stack/battlefield, 244 in the
    graveyard: every row names root 212."""
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    elves = [r for r in rows if r["object_id"] == 212 or r["target_object_id"] == 212]
    assert {r["event_subtype"] for r in elves} >= {"move", "stack_push", "damage"}
    death = next(r for r in elves if (r["payload"] or {}).get("reason") == "sba")
    assert (death["zone_from"], death["zone_to"], death["visible"]) == (
        "battlefield",
        "graveyard",
        1,
    )
    assert not [r for r in rows if r["object_id"] in (232, 244)]


def test_taps_and_untaps_are_batched_per_message(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    taps = [r for r in rows if r["event_subtype"] == "tap"]
    untaps = [r for r in rows if r["event_subtype"] == "untap"]
    assert {"object_ids": [300, 301]} in [r["payload"] for r in taps]
    assert all(r["seat_id"] == r["controller_seat"] for r in taps + untaps)
    # One row per untap step, never one per permanent.
    turn8 = [r for r in untaps if r["turn_number"] == 8]
    assert len(turn8) == 1 and turn8[0]["payload"] == {"object_ids": [300, 301, 215]}
    assert turn8[0]["amount"] == 3 and turn8[0]["text"] == "untap seat 2"


def test_summoning_sickness_follows_arenas_flag(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    sick = [r for r in rows if r["event_subtype"] in ("sick", "unsick")]
    assert [(r["event_subtype"], r["turn_number"], r["payload"]) for r in sick] == [
        ("sick", 2, {"object_ids": [212]}),
        ("unsick", 4, {"object_ids": [212]}),
    ]
    assert all(r["visible"] == 0 and r["seat_id"] == P for r in sick)
    # Keyed by the Elves' root id, after the move that put them onto the battlefield.
    entry = next(
        r
        for r in rows
        if r["event_subtype"] == "move" and r["object_id"] == 212 and r["zone_to"] == "battlefield"
    )
    assert entry["id"] < sick[0]["id"]


def test_counters_pt_tokens_attach_identity_reveal_shuffle(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    counters = [r for r in rows if r["event_subtype"] == "counter"]
    assert [(r["object_id"], r["amount"], r["payload"]) for r in counters] == [
        (215, 1, {"type": "+1/+1", "total": 1}),
        (215, -1, {"type": "+1/+1", "total": 0}),
    ]
    pts = [(r["object_id"], r["payload"]) for r in rows if r["event_subtype"] == "pt"]
    assert pts == [
        (215, {"power": 4, "toughness": 2}),
        (215, {"power": 5, "toughness": 3}),
        (215, {"power": 4, "toughness": 2}),
    ]
    tokens = [r for r in rows if (r["payload"] or {}).get("reason") == "token_create"]
    assert [r["object_id"] for r in tokens] == [152, 153]
    assert tokens[0]["zone_from"] == "limbo" and tokens[0]["zone_to"] == "battlefield"
    assert tokens[0]["payload"]["token"] is True and tokens[0]["payload"]["power"] == 1
    cease = next(r for r in rows if (r["payload"] or {}).get("reason") == "token_cease")
    assert (cease["object_id"], cease["zone_from"], cease["zone_to"]) == (152, "graveyard", "limbo")
    attach = next(r for r in rows if r["event_subtype"] == "attach")
    assert (attach["object_id"], attach["target_object_id"]) == (216, 215)
    identity = next(r for r in rows if r["event_subtype"] == "identity")
    assert identity["visible"] == 1 and identity["object_id"] == 301
    assert identity["arena_id"] == 1008 and identity["payload"]["name"] == "Island"
    reveal = next(r for r in rows if r["event_subtype"] == "reveal")
    assert (reveal["object_id"], reveal["arena_id"], reveal["seat_id"]) == (181, 2001, O)
    shuffles = [r for r in rows if r["event_subtype"] == "shuffle"]
    assert [r["seat_id"] for r in shuffles] == [O]


def test_attacks_blocks_damage_and_life(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    attack = next(r for r in rows if r["event_subtype"] == "attack")
    assert attack["payload"] == {"object_ids": [112], "target_seat": P}
    assert attack["seat_id"] == O and attack["visible"] == 1
    block = next(r for r in rows if r["event_subtype"] == "block")
    assert block["payload"] == {"pairs": [{"blocker": 214, "attacker": 112}]}
    assert block["seat_id"] == P and block["visible"] == 1
    assert len([r for r in rows if r["event_subtype"] == "block"]) == 1
    damage = [r for r in rows if r["event_subtype"] == "damage"]
    to_player = next(r for r in damage if (r["payload"] or {}).get("target_seat") == P)
    assert to_player["visible"] == 0 and to_player["object_id"] == 112
    assert to_player["amount"] == 2 and to_player["payload"]["combat"] is True
    burn = next(r for r in damage if r["object_id"] == 113)
    assert burn["target_object_id"] == 212 and burn["payload"] == {"combat": False}
    fight = [r for r in damage if r["visible"] == 1 and r["event_type"] == "combat_damage"]
    assert {(r["object_id"], r["target_object_id"]) for r in fight} == {(214, 112), (112, 214)}
    lives = [r for r in rows if r["event_subtype"] == "life"]
    assert [(r["seat_id"], r["amount"]) for r in lives] == [(P, -2), (P, 1), (O, -5), (O, -4)]
    with sqlite3.connect(db) as conn:
        totals = conn.execute(
            "SELECT player_life, opponent_life FROM game_events WHERE event_subtype = 'life' ORDER BY id"
        ).fetchall()
    assert totals[-1] == (19, 11)
    # The combat summary re-prints are notes, never a second damage fact.
    notes = [r for r in rows if r["event_subtype"] == "note"]
    assert notes and all(r["event_type"] == "combat_damage" for r in notes)


def test_game_end_row_and_replay_version(tmp_path):
    _tracker, db = _played(tmp_path)
    rows = event_rows(db)
    assert rows[-1]["event_subtype"] == "game_end"
    assert rows[-1]["seat_id"] == P and rows[-1]["payload"] == {"reason": "Opponent conceded"}


# -- minimal payloads ------------------------------------------------------


def started_tracker(tmp_path: Path, *, player: int = P):
    tracker = synthetic_tracker(tmp_path)
    opponent = 1 if player == 2 else 2
    g = tracker.game_state
    g.in_match = True
    g.game_start_time = datetime(2026, 10, 1, 21, 0, 0)
    g.player_seat_id = player
    g.opponent_seat_id = opponent
    g.turn_number = 3
    g.active_player = player
    g.last_turn_announced = 3
    g.last_player_turn_number = 3
    g.phase = "Phase_Main1"
    g.opening_hand_capture_closed = True
    g.battlefield_zone_id = BF
    return tracker


def message(*annotations, objects=(), zones=True, **extra):
    payload: Dict[str, Any] = {"annotations": list(annotations), "gameObjects": list(objects)}
    if zones:
        payload["zones"] = [
            zone for zone in _zone_defs().values() if zone["type"] not in ("ZoneType_Hand",)
        ]
    payload.update(extra)
    return {"type": "game_state", "data": payload}


def obj(iid: int, grp: int, owner: int, zone: int, **extra):
    out = {
        "instanceId": iid,
        "grpId": grp,
        "type": "GameObjectType_Card",
        "ownerSeatId": owner,
        "controllerSeatId": owner,
        "zoneId": zone,
        "visibility": "Visibility_Public",
        "cardTypes": TYPES.get(grp, []),
    }
    if grp in PT:
        out["power"] = {"value": PT[grp][0]}
        out["toughness"] = {"value": PT[grp][1]}
    out.update(extra)
    return out


def test_countered_spell_records_stack_countered_then_graveyard_move(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker._handle_event(
        message(
            oic(220, 230), zt(230, HAND[P], STACK, "CastSpell"), objects=[obj(230, 1004, P, STACK)]
        )
    )
    tracker._handle_event(
        message(
            oic(120, 131), zt(131, HAND[O], STACK, "CastSpell"), objects=[obj(131, 2002, O, STACK)]
        )
    )
    tracker._handle_event(
        message(
            ann("ResolutionStart", [131], 131, grpid=2002),
            zt(230, STACK, GY[P], "Countered", affector=131),
            zt(131, STACK, GY[O], "Resolve"),
            objects=[obj(230, 1004, P, GY[P]), obj(131, 2002, O, GY[O])],
        )
    )
    rows = event_rows(tmp_path / "analytics.sqlite3")
    countered = next(r for r in rows if r["event_subtype"] == "stack_countered")
    assert countered["visible"] == 1 and countered["payload"] == {"stack_id": "s1"}
    move = next(r for r in rows if r["id"] > countered["id"] and r["object_id"] == 220)
    assert (move["event_subtype"], move["zone_from"], move["zone_to"]) == (
        "move",
        "stack",
        "graveyard",
    )
    assert move["payload"]["reason"] == "counter"


def test_untracked_match_writes_no_silent_rows(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker.game_state.format_str = "Jump_In_2026"
    tracker._handle_event(
        message(
            ann("CounterAdded", [500], 500, counter_type=1, transaction_amount=1),
            ann("Shuffle", [P], 500),
            objects=[obj(500, 1002, P, BF, isTapped=True)],
        )
    )
    db = tmp_path / "analytics.sqlite3"
    if db.exists():
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0] == 0


def test_mid_game_attach_writes_nothing(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker.game_state.mid_game_attach = True
    tracker._handle_event(
        message(ann("Shuffle", [P], 500), objects=[obj(500, 1002, P, BF, isTapped=True)])
    )
    db = tmp_path / "analytics.sqlite3"
    if db.exists():
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0] == 0


def test_ghost_purge_removes_silent_rows(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker._handle_event(message(ann("Shuffle", [P], 500)))
    db = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM game_events WHERE visible = 0").fetchone()[0] == 1
    tracker._purge_ghost_game_breadcrumbs()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0] == 0


def test_handled_annotations_no_longer_reach_the_diagnostics_log(tmp_path):
    tracker = started_tracker(tmp_path)
    logged = []
    tracker._log_unhandled_annotation = lambda annotation, **kwargs: logged.append(annotation)
    tracker._handle_event(
        message(
            ann("CounterAdded", [500], 501, counter_type=7, transaction_amount=3),
            ann("CounterRemoved", [500], 501, counter_type=7, transaction_amount=1),
            ann("TokenCreated", [502], 501),
            ann("TokenDeleted", [502], 502),
            ann("PowerToughnessModCreated", [500], 501, power=1, toughness=1),
            ann("PlayerSubmittedTargets", [503], P),
            ann("NewTurnStarted", [P], P),
            ann("Shuffle", [P], 501),
            ann("RevealedCardCreated", [504], 504),
            ann("RevealedCardDeleted", [504], 504),
            ann("AttachmentCreated", [500], 505),
            ann("TappedUntappedPermanent", [500], 501, tapped=1),
            objects=[
                obj(500, 1006, P, BF),
                obj(502, 2100, P, BF, type="GameObjectType_Token"),
                obj(504, 2001, O, REVEALED[O]),
                obj(505, 1005, P, BF),
            ],
        )
    )
    assert logged == []
    rows = event_rows(tmp_path / "analytics.sqlite3")
    counters = [r for r in rows if r["event_subtype"] == "counter"]
    assert [(r["amount"], r["payload"]) for r in counters] == [
        (3, {"type": "loyalty", "total": 3}),
        (-1, {"type": "loyalty", "total": 2}),
    ]


def test_hidden_hand_growth_without_draw_annotation_records_hidden_moves(tmp_path):
    tracker = started_tracker(tmp_path)
    hand = {"zoneId": HAND[O], "type": "ZoneType_Hand", "ownerSeatId": O}
    first = message(zones=False)
    first["data"]["zones"] = [dict(hand, objectInstanceIds=[140, 141])]
    tracker._handle_event(first)
    second = message(zones=False)
    second["data"]["zones"] = [dict(hand, objectInstanceIds=[140, 141, 160])]
    tracker._handle_event(second)
    rows = event_rows(tmp_path / "analytics.sqlite3", "event_subtype = 'move'")
    assert [
        (r["object_id"], r["seat_id"], r["arena_id"], r["zone_from"], r["zone_to"]) for r in rows
    ] == [(160, O, None, "library", "hand")]
    assert rows[0]["visible"] == 0 and rows[0]["payload"] == {"reason": "draw"}


def test_blocks_reported_only_on_objects_are_captured(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker._handle_event(
        message(
            objects=[
                obj(
                    600,
                    2003,
                    O,
                    BF,
                    attackState="AttackState_Attacking",
                    attackInfo={"targetId": P},
                ),
                obj(
                    601,
                    1004,
                    P,
                    BF,
                    blockState="BlockState_Blocking",
                    blockInfo={"attackerIds": [600]},
                ),
            ]
        )
    )
    rows = event_rows(tmp_path / "analytics.sqlite3", "event_subtype = 'block'")
    assert len(rows) == 1 and rows[0]["visible"] == 0
    assert rows[0]["seat_id"] == P
    assert rows[0]["payload"] == {"pairs": [{"blocker": 601, "attacker": 600}]}


def test_ability_stack_push_is_activated_or_trigger(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker.card_db.ability_texts[(1006, 9001)] = "Draw a card."
    tracker.card_db.ability_texts[(1006, 9002)] = "Scry 1."
    source = obj(700, 1006, P, BF)
    activated = {
        "instanceId": 701,
        "grpId": 9001,
        "type": "GameObjectType_Ability",
        "ownerSeatId": P,
        "controllerSeatId": P,
        "zoneId": STACK,
    }
    trigger = {
        "instanceId": 702,
        "grpId": 9002,
        "type": "GameObjectType_Ability",
        "ownerSeatId": P,
        "controllerSeatId": P,
        "zoneId": STACK,
    }
    tracker._handle_event(
        message(
            ann("AbilityInstanceCreated", [701], 700),
            ann("UserActionTaken", [701], P, abilityGrpId=9001),
            objects=[source, activated],
        )
    )
    tracker._handle_event(
        message(ann("AbilityInstanceCreated", [702], 700), objects=[source, trigger])
    )
    rows = event_rows(tmp_path / "analytics.sqlite3", "event_subtype = 'stack_push'")
    assert [
        (r["visible"], r["object_id"], r["arena_id"], r["payload"]["stack_kind"]) for r in rows
    ] == [
        (1, 700, 1006, "activated"),
        (1, 700, 1006, "trigger"),
    ]
    assert rows[0]["payload"]["text"] == "Draw a card." and rows[0]["zone_from"] is None


def test_exile_by_a_permanents_ability_records_the_host(tmp_path):
    """Deep-Cavern Bat: its trigger (an ability whose parentId is the Bat) exiles a
    card from the opponent's hand. The move carries ``with`` = the Bat's root so the
    viewer tucks the card under it; a spell or a source off the battlefield does not."""
    tracker = started_tracker(tmp_path)
    bat = obj(318, 2003, O, BF)
    trigger = {
        "instanceId": 322,
        "grpId": 9001,
        "type": "GameObjectType_Ability",
        "ownerSeatId": O,
        "controllerSeatId": O,
        "zoneId": STACK,
        "parentId": 318,
    }
    taken = obj(323, 1008, P, EXILE)
    tracker._handle_event(
        message(
            oic(280, 323, 322),
            zt(323, HAND[P], EXILE, "Exile", 322),
            objects=[bat, trigger, taken],
        )
    )
    # Pinnacle Starcage style: the permanent itself is the affector.
    cage = obj(312, 1005, P, BF)
    swept = obj(315, 2001, O, EXILE)
    tracker._handle_event(message(zt(315, BF, EXILE, "Exile", 312), objects=[cage, swept]))
    # A sorcery on the stack exiling a card links nothing.
    spell = obj(400, 2004, O, STACK)
    gone = obj(401, 1001, P, EXILE)
    tracker._handle_event(message(zt(401, BF, EXILE, "Exile", 400), objects=[spell, gone]))
    rows = event_rows(tmp_path / "analytics.sqlite3", "zone_to = 'exile'")
    assert [(r["object_id"], r["payload"].get("with")) for r in rows] == [
        (280, 318),
        (315, 312),
        (401, None),
    ]


def test_exile_by_an_ability_arena_already_deleted_still_records_the_host(tmp_path):
    """Perilous Snare: Arena deletes the trigger in the same message that exiles
    the card, so neither the message nor the snapshots hold the ability. The
    source recorded when the trigger went on the stack names the host."""
    tracker = started_tracker(tmp_path)
    snare = obj(233, 2003, P, BF)
    tracker.game_state.ability_instance_sources[384] = 233
    caught = obj(286, 1008, O, EXILE)
    tracker._handle_event(message(zt(286, BF, EXILE, "Exile", 384), objects=[snare, caught]))
    rows = event_rows(tmp_path / "analytics.sqlite3", "zone_to = 'exile'")
    assert [(r["object_id"], r["payload"].get("with"), r["payload"].get("by")) for r in rows] == [
        (286, 233, 233)
    ]


def test_removal_records_the_source_that_moved_it(tmp_path):
    """A removal carries ``by``: the root of the spell or of the ability's source
    permanent (Arena's affector), so the viewer draws it from there. A card that
    moves itself (a cost it paid) and a state-based death record none."""
    tracker = started_tracker(tmp_path)
    murder = obj(400, 2004, O, STACK)
    victim = obj(401, 1001, P, GY[P])
    tracker._handle_event(message(zt(401, BF, GY[P], "Destroy", 400), objects=[murder, victim]))
    bat = obj(318, 2003, O, BF)
    trigger = {
        "instanceId": 322,
        "grpId": 9001,
        "type": "GameObjectType_Ability",
        "ownerSeatId": O,
        "controllerSeatId": O,
        "zoneId": STACK,
        "parentId": 318,
    }
    taken = obj(323, 1008, P, GY[P])
    tracker._handle_event(
        message(zt(323, HAND[P], GY[P], "Discard", 322), objects=[bat, trigger, taken])
    )
    food = obj(500, 1002, P, GY[P])
    tracker._handle_event(message(zt(500, BF, GY[P], "Sacrifice", 500), objects=[food]))
    dead = obj(501, 1003, P, GY[P])
    tracker._handle_event(message(zt(501, BF, GY[P], "SBA_Damage", 400), objects=[murder, dead]))
    rows = event_rows(
        tmp_path / "analytics.sqlite3", "event_subtype = 'move' AND zone_to = 'graveyard'"
    )
    assert [(r["object_id"], r["payload"]["reason"], r["payload"].get("by")) for r in rows] == [
        (401, "destroy", 400),
        (323, "discard", 318),
        (500, "sacrifice", None),
        (501, "sba", None),
    ]


def test_land_that_chose_a_basic_land_type_names_it(tmp_path):
    """Multiversal Passage (shape from a live log): Arena logs ChoiceResult from
    the entering land in the basic-land-type domain (9), then the land play,
    with the chosen type as the object's subtype. A land that made no choice
    (a printed Forest) gets no suffix."""
    tracker = started_tracker(tmp_path)
    tracker._handle_event(message(ann("ChoiceResult", [P], 291, Choice_Value=49, Choice_Domain=9)))
    passage = obj(291, 1008, P, BF, subtypes=["SubType_Mountain"], isTapped=True)
    tracker._handle_event(
        message(oic(169, 291), zt(291, HAND[P], BF, "PlayLand"), objects=[passage])
    )
    forest = obj(292, 1001, P, BF, subtypes=["SubType_Forest"])
    tracker._handle_event(message(zt(292, HAND[P], BF, "PlayLand"), objects=[forest]))
    lands = event_rows(tmp_path / "analytics.sqlite3", "event_type = 'land'")
    assert lands[0]["text"].endswith("(Land)] as a Mountain")
    assert lands[0]["payload"]["chosen"] == "Mountain"
    assert lands[1]["text"].endswith("(Land)]")
    assert "chosen" not in lands[1]["payload"]


def test_one_message_is_one_transaction(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker._handle_event(message())  # create the schema
    conn = tracker._analytics_connect()
    statements: List[str] = []
    conn.set_trace_callback(statements.append)
    try:
        tracker._handle_event(
            message(
                zt(230, LIB[P], HAND[P], "Draw"),
                ann("CounterAdded", [500], 500, counter_type=1, transaction_amount=1),
                ann("Shuffle", [P], 500),
                objects=[obj(230, 1001, P, HAND[P]), obj(500, 1002, P, BF, isTapped=True)],
            )
        )
    finally:
        conn.set_trace_callback(None)
    inserts = [i for i, sql in enumerate(statements) if "INSERT INTO game_events" in sql]
    assert len(inserts) >= 4  # draw (printed), counter, shuffle, tap
    begins = [i for i, sql in enumerate(statements) if sql.strip().upper().startswith("BEGIN")]
    commits = [i for i, sql in enumerate(statements) if sql.strip().upper() == "COMMIT"]
    # Every game_events insert sits inside the same BEGIN ... COMMIT.
    begin = max(i for i in begins if i < inserts[0])
    commit = min(i for i in commits if i > inserts[0])
    assert all(begin < i < commit for i in inserts)
    assert INSERT_EVENT_SQL.startswith("INSERT INTO game_events")


def test_replay_link_printed_only_with_a_dashboard(tmp_path, capsys):
    tracker, _db = _played(tmp_path)
    assert "Replay:" not in capsys.readouterr().out

    tracker2 = synthetic_tracker(tmp_path / "with_dashboard")
    (tmp_path / "with_dashboard").mkdir()
    tracker2.dashboard_url_provider = lambda: "http://127.0.0.1:8765"
    run_synthetic_game(tracker2, build_synthetic_game())
    out = capsys.readouterr().out
    assert "Replay: http://127.0.0.1:8765/#/replay/test-session:match:1:game:1" in out
    assert out.rstrip().endswith(
        "Replay: http://127.0.0.1:8765/#/replay/test-session:match:1:game:1"
    )


def test_unified_launcher_hands_the_dashboard_url_to_the_tracker(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace

    from mtga_tracker.app import UnifiedLauncher

    tracker = synthetic_tracker(tmp_path)
    tracker.analytics = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr("mtga_tracker.app.MTGALogParser", lambda: object())
    monkeypatch.setattr("mtga_tracker.app.CardTracker", lambda *args, **kwargs: tracker)
    launcher = UnifiedLauncher(db_path=tmp_path / "db.sqlite3", output_stream=io.StringIO())
    built = launcher._build_tracker()
    assert built is tracker
    assert tracker.dashboard_url_provider() is None
    assert tracker._replay_link("g1") is None
    launcher.dashboard_server = SimpleNamespace(server_address=("127.0.0.1", 9911))
    assert tracker._replay_link("g1") == "http://127.0.0.1:9911/#/replay/g1"


def test_events_backfill_ignores_silent_rows(tmp_path):
    from mtga_tracker.events_backfill import compute_game_stats_from_events

    _tracker, db = _played(tmp_path)
    with sqlite3.connect(db) as conn:
        game_id = conn.execute("SELECT id FROM games").fetchone()[0]
        with_silent = compute_game_stats_from_events(conn, game_id, {})
        conn.execute("DELETE FROM game_events WHERE visible = 0")
        printed_only = compute_game_stats_from_events(conn, game_id, {})
    assert with_silent == printed_only


def test_audit_reassignment_keeps_silent_participant_null(tmp_path):
    from mtga_tracker.db_audit import _repair_game_event_assignments

    _tracker, db = _played(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE game_events SET game_id = 'test-session:match:9:game:1'")
        assert _repair_game_event_assignments(conn) > 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM game_events WHERE visible = 0 AND participant_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM game_events WHERE game_id = 'test-session:match:9:game:1'"
            ).fetchone()[0]
            == 0
        )


# -- budgets -----------------------------------------------------------------


def test_storage_per_synthetic_game_stays_small(tmp_path):
    """Silent rows stay lean. Reports bytes per row kind (pytest -s)."""
    _tracker, db = _played(tmp_path)
    with sqlite3.connect(db) as conn:
        silent = conn.execute(
            """
            SELECT COUNT(*),
                   SUM(LENGTH(session_id) + COALESCE(LENGTH(match_id), 0) + LENGTH(game_id)
                       + LENGTH(event_time) + LENGTH(text) + COALESCE(LENGTH(payload_json), 0)
                       + 24)
            FROM game_events WHERE visible = 0
            """
        ).fetchone()
        extra_printed = conn.execute(
            """
            SELECT SUM(COALESCE(LENGTH(payload_json), 0) + LENGTH(event_subtype) + 8)
            FROM game_events WHERE visible = 1
            """
        ).fetchone()[0]
    rows, silent_bytes = silent
    print(
        f"\nsilent rows: {rows}, ~{silent_bytes} bytes; printed-row additions ~{extra_printed} bytes"
    )
    assert rows < 110
    assert silent_bytes / rows < 150  # row payload before index entries
    assert silent_bytes + extra_printed < 25_000


def test_per_message_overhead_is_small(tmp_path):
    """Capture adds well under 1 ms per message (generous, non-flaky bound)."""
    import time

    lines = build_synthetic_game()

    def run(capture: bool) -> float:
        tracker = synthetic_tracker(tmp_path / ("on" if capture else "off"))
        (tmp_path / ("on" if capture else "off")).mkdir(exist_ok=True)
        tracker._console_db_path = None  # measure the tracker, not SQLite
        if not capture:
            tracker._replay_capturing = lambda: False
        start = time.perf_counter()
        for _ in range(5):
            for line, stamp in lines:
                tracker._process_line(line, timestamp=stamp)
        return time.perf_counter() - start

    run(True)  # warm-up
    off = min(run(False) for _ in range(2))
    on = min(run(True) for _ in range(2))
    per_message = (on - off) / (5 * len(lines))
    assert per_message < 0.001


# -- robustness ----------------------------------------------------------------


def test_a_failing_capture_hook_never_breaks_tracking(tmp_path, capsys):
    """Hooks are exception-safe: the line prints, its row persists without
    replay columns, and one diagnostic line names the failing hook."""
    tracker = started_tracker(tmp_path)
    tracker._diagnostic_text_path = tmp_path / "diagnostics.log"

    def boom(*_args, **_kwargs):
        raise RuntimeError("capture bug")

    tracker._replay_card_payload = boom
    for iid in (230, 231):
        tracker._handle_event(
            message(zt(iid, LIB[P], HAND[P], "Draw"), objects=[obj(iid, 1001, P, HAND[P])])
        )
    assert capsys.readouterr().out.count("drew [Forest]") == 2
    draws = event_rows(tmp_path / "analytics.sqlite3", "event_type = 'draw'")
    assert len(draws) == 2 and all(row["object_id"] is None for row in draws)
    log = (tmp_path / "diagnostics.log").read_text()
    assert log.count("Replay capture: _replay_move_fact failed: RuntimeError") == 1


def test_printed_rows_survive_when_a_silent_row_of_the_batch_fails(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker._handle_event(message())  # create the schema
    conn = tracker._analytics_connect()
    conn.execute(
        "CREATE TRIGGER reject_silent BEFORE INSERT ON game_events WHEN NEW.visible = 0 "
        "BEGIN SELECT RAISE(ABORT, 'silent row rejected'); END"
    )
    tracker._handle_event(
        message(
            zt(230, LIB[P], HAND[P], "Draw"),
            ann("Shuffle", [P], 500),
            ann("CounterAdded", [500], 500, counter_type=1, transaction_amount=1),
            objects=[obj(230, 1001, P, HAND[P]), obj(500, 1002, P, BF)],
        )
    )
    rows = event_rows(tmp_path / "analytics.sqlite3")
    assert [(row["visible"], row["event_type"], row["event_subtype"]) for row in rows] == [
        (1, "draw", "move")
    ]
    assert rows[0]["object_id"] == 230 and rows[0]["payload"]["reason"] == "draw"


def test_a_printed_row_whose_fact_cannot_be_encoded_is_kept_plain(tmp_path):
    from mtga_tracker.replay_capture import ReplayFact

    tracker = started_tracker(tmp_path)
    tracker._replay_begin()
    tracker._record_game_event(
        "[0:01] You: odd line", "zone", ReplayFact("move", payload={"bad": object()})
    )
    tracker._record_silent_event(ReplayFact("shuffle", seat_id=P))
    tracker._replay_end()
    rows = event_rows(tmp_path / "analytics.sqlite3")
    assert [(row["visible"], row["event_subtype"], row["text"]) for row in rows] == [
        (1, "note", "[0:01] You: odd line"),
        (0, "shuffle", f"shuffle seat {P}"),
    ]


def test_bounce_by_the_other_seat_keeps_the_text_seat_and_records_the_owner(tmp_path):
    """ "You: [X] returned [Their card] to opponent's hand": the printed seat
    stays the player's (unchanged history); the owner rides in the payload
    and the builder puts the card in the opponent's hand."""
    from mtga_tracker.replay_builder import RecordedBuilder

    tracker = started_tracker(tmp_path)
    tracker._handle_event({"type": "game_state", "data": {"zones": list(_zone_defs().values())}})
    tracker._handle_event(
        message(
            zt(120, BF, HAND[O], "Return", affector=600),
            objects=[obj(600, 1006, P, BF), obj(120, 2003, O, HAND[O])],
        )
    )
    row = event_rows(tmp_path / "analytics.sqlite3", "event_type = 'zone'")[0]
    assert "returned [Goblin Guide] to opponent's hand" in row["text"]
    assert (row["seat_id"], row["zone_from"], row["zone_to"]) == (P, "battlefield", "hand")
    assert row["payload"]["owner"] == O and row["payload"]["reason"] == "bounce"
    builder = RecordedBuilder({"participants": [], "game_events": []})
    assert builder._seat(row) == O


def test_zone_types_are_remembered_from_earlier_messages(tmp_path):
    tracker = started_tracker(tmp_path)
    tracker._handle_event({"type": "game_state", "data": {"zones": list(_zone_defs().values())}})
    tracker._handle_event(
        message(zt(230, LIB[O], HAND[O], "Draw"), objects=[obj(230, 2001, O, HAND[O])])
    )
    row = event_rows(tmp_path / "analytics.sqlite3", "event_type = 'draw'")[0]
    assert (row["zone_from"], row["zone_to"], row["seat_id"]) == ("library", "hand", O)


def test_creature_rows_carry_current_stats_including_zero_power(tmp_path):
    """Arena drops zero-valued fields, so a 0/2 arrives as ``"power": {}``. Every
    structured row for a creature carries its stats (the stream's card entry is
    seeded from the first one), and a hidden opponent card reveals nothing."""
    tracker = started_tracker(tmp_path)
    tidecaller = obj(500, 1004, P, BF, power={}, toughness={"value": 2})
    tracker._handle_event(message(zt(500, STACK, BF, "Resolve"), objects=[tidecaller]))
    hidden = obj(501, 2003, O, HAND[O], visibility="Visibility_Private")
    tracker._handle_event(message(zt(501, LIB[O], HAND[O], "Draw"), objects=[hidden]))
    rows = event_rows(tmp_path / "analytics.sqlite3", "event_subtype = 'move'")
    landed = next(r for r in rows if r["object_id"] == 500)
    assert (landed["payload"]["power"], landed["payload"]["toughness"]) == (0, 2)
    drawn = next(r for r in rows if r["object_id"] == 501)
    assert not {"name", "type", "power", "toughness"} & set(drawn["payload"])


def test_commander_cast_from_and_returned_to_the_command_zone(tmp_path):
    """Brawl: the commander is cast out of the command zone (zone 26) like a spell
    from hand, resolves to the battlefield, and after dying goes back to the
    command zone. Every leg is an ordinary zone transfer the capture names."""
    tracker = started_tracker(tmp_path)
    COMMAND = 26
    zone = {"zoneId": COMMAND, "type": "ZoneType_Command", "ownerSeatId": P}

    def msg(*annotations, objects):
        out = message(*annotations, objects=objects)
        out["data"]["zones"].append(zone)
        return out

    tracker._handle_event(msg(objects=[obj(600, 1004, P, COMMAND)]))
    tracker._handle_event(
        msg(oic(600, 601), zt(601, COMMAND, STACK, "CastSpell"), objects=[obj(601, 1004, P, STACK)])
    )
    tracker._handle_event(msg(zt(601, STACK, BF, "Resolve"), objects=[obj(601, 1004, P, BF)]))
    tracker._handle_event(msg(zt(601, BF, GY[P], "SBA_Damage"), objects=[obj(601, 1004, P, GY[P])]))
    tracker._handle_event(
        msg(zt(601, GY[P], COMMAND, "Return"), objects=[obj(601, 1004, P, COMMAND)])
    )
    rows = event_rows(tmp_path / "analytics.sqlite3", "object_id = 600")
    push = next(r for r in rows if r["event_subtype"] == "stack_push")
    assert push["zone_from"] == "command" and push["payload"]["name"] == "Grizzly Bears"
    moves = [
        (r["zone_from"], r["zone_to"], r["payload"]["reason"])
        for r in rows
        if r["event_subtype"] == "move"
    ]
    assert moves == [
        ("stack", "battlefield", "resolve"),
        ("battlefield", "graveyard", "sba"),
        ("graveyard", "command", "put"),
    ]
