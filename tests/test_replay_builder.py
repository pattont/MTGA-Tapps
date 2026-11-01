"""Replay builder for games captured with structured rows (replay_version >= 1)."""

import json

from mtga_tracker.replay_builder import (
    LOST_ARRIVAL_LIMITATION,
    attach_card_facts,
    attach_image_urls,
    build_recorded,
    build_stream,
)
from mtga_tracker.replay_capture import REPLAY_VERSION
from mtga_tracker.replay_sickness import SICKNESS_ESTIMATE_LIMITATION
from mtga_tracker.replay_stream import validate_stream

PLAYER, OPPONENT = 2, 1


class _Rows:
    """Builds game_events rows in capture order (docs/REPLAY_FORMAT.md §1)."""

    def __init__(self):
        self.rows = []
        self.turn = 0

    def add(self, kind, text=None, visible=None, payload=None, event_type=None, **columns):
        """Rows without text are silent (visible = 0), like the capture writes them."""
        if visible is None:
            visible = 0 if text is None else 1
        index = len(self.rows)
        row = {
            "id": index + 1,
            "event_time": f"2026-06-04T00:10:{index:02d}",
            "elapsed_seconds": index,
            "turn_number": columns.pop("turn_number", self.turn),
            "phase": columns.pop("phase", "Phase_Main1"),
            "step": columns.pop("step", None),
            "event_type": event_type or ("silent" if not visible else kind),
            "event_subtype": kind,
            "text": text if text is not None else f"{kind} (silent)",
            "visible": visible,
            "payload_json": json.dumps(payload) if payload is not None else None,
            "player_life": columns.pop("player_life", None),
            "opponent_life": columns.pop("opponent_life", None),
        }
        for name in (
            "seat_id",
            "actor_role",
            "object_id",
            "target_object_id",
            "arena_id",
            "controller_seat",
            "zone_from",
            "zone_to",
            "amount",
        ):
            row[name] = columns.pop(name, None)
        assert not columns, columns
        self.rows.append(row)
        return row

    def turn_row(self, turn, seat):
        self.turn = turn
        label = "YOUR TURN" if seat == PLAYER else "OPPONENT'S TURN"
        return self.add(
            "turn",
            f"Turn {turn} - {label}",
            event_type="turn",
            seat_id=seat,
            payload={"active_seat": seat},
        )

    def move(
        self,
        obj,
        source,
        dest,
        reason,
        seat,
        arena_id=None,
        name=None,
        visible=0,
        text=None,
        **payload,
    ):
        body = {"reason": reason}
        if name:
            body["name"] = name
        body.update(payload)
        return self.add(
            "move",
            text,
            visible=visible,
            payload=body,
            object_id=obj,
            arena_id=arena_id,
            seat_id=seat,
            controller_seat=seat,
            zone_from=source,
            zone_to=dest,
        )


def _game_rows(events, replay_version=REPLAY_VERSION):
    return {
        "games": [
            {
                "id": "g1",
                "outcome": "win",
                "winner_participant_id": "p-me",
                "game_number": 1,
                "replay_version": replay_version,
                "outcome_reason": "Opponent conceded",
            }
        ],
        "matches": [{"format": "Ladder", "best_of": 1}],
        "participants": [
            {
                "id": "p-me",
                "role": "player",
                "seat_id": PLAYER,
                "deck_size": 40,
                "starting_life": 20,
                "ending_life": 20,
                "mulligans": 1,
                "display_name": "Me",
            },
            {
                "id": "p-opp",
                "role": "opponent",
                "seat_id": OPPONENT,
                "deck_size": 60,
                "starting_life": 20,
                "ending_life": 18,
                "mulligans": 0,
                "display_name": "Them",
            },
        ],
        "participant_commanders": [],
        "game_events": events,
        "game_opening_hand_cards": [
            {"participant_id": "p-me", "display_name": "Forest", "hand_position": 1},
            {"participant_id": "p-me", "display_name": "Island", "hand_position": 2},
        ],
        "game_mulligan_hands": [],
        "game_drawn_cards": [],
        "game_deck_cards": [
            {
                "participant_id": "p-me",
                "display_name": "Forest",
                "arena_id": 9002,
                "deck_zone": "deck",
                "quantity": 20,
                "type_category": "Land",
            },
            {
                "participant_id": "p-me",
                "display_name": "Grizzly Bears",
                "arena_id": 9001,
                "deck_zone": "deck",
                "quantity": 20,
                "type_category": "Creature",
            },
        ],
        "game_turns": [
            {
                "turn_number": 1,
                "seat_id": PLAYER,
                "started_at": "2026-06-04T00:10:01",
                "duration_seconds": 12,
            }
        ],
        "cards": [
            {
                "id": 1,
                "arena_id": 9001,
                "name": "Grizzly Bears",
                "primary_type": "Creature",
                "power": "2",
                "toughness": "2",
                "color_identity": "G",
                "mana_cost": "{1}{G}",
            },
            {
                "id": 2,
                "arena_id": 9002,
                "name": "Forest",
                "primary_type": "Land",
                "color_identity": "G",
            },
            {
                "id": 3,
                "arena_id": 9101,
                "name": "Lightning Bolt",
                "primary_type": "Instant",
                "color_identity": "R",
            },
        ],
    }


def _scenario():
    r = _Rows()
    r.add("mulligan", seat_id=PLAYER, amount=6, payload={"from_size": 7, "to_size": 6})
    r.turn_row(1, PLAYER)
    r.add("phase", phase="Phase_Main1", step="Step_None")
    r.move(
        101,
        "library",
        "hand",
        "draw",
        PLAYER,
        9001,
        "Grizzly Bears",
        visible=1,
        text="[0:10] You: drew [Grizzly Bears]",
    )
    r.move(
        102,
        "hand",
        "battlefield",
        "play_land",
        PLAYER,
        9002,
        "Forest",
        visible=1,
        text="[0:11] You: played [Forest (Land)]",
    )
    r.add(
        "stack_push",
        "[0:12] You: cast [Grizzly Bears (Creature 2/2)]",
        event_type="cast",
        object_id=101,
        arena_id=9001,
        seat_id=PLAYER,
        zone_from="hand",
        payload={"stack_id": "s1", "stack_kind": "spell", "name": "Grizzly Bears"},
    )
    r.move(101, "stack", "battlefield", "resolve", PLAYER, 9001, "Grizzly Bears")
    r.add(
        "stack_push",
        "[0:13] You: [Grizzly Bears] - When this creature enters, scry 1.",
        event_type="ability",
        object_id=101,
        arena_id=9001,
        seat_id=PLAYER,
        payload={
            "stack_id": "s2",
            "kind": "trigger",
            "name": "Grizzly Bears",
            "text": "When this creature enters, scry 1.",
        },
    )
    r.add("tap", seat_id=PLAYER, payload={"object_ids": [102]})
    r.add(
        "scry",
        "[0:14] You: scried 1 — kept [Forest] on top",
        event_type="scry",
        seat_id=PLAYER,
        amount=1,
        payload={"top": [301], "bottom": [], "top_names": ["Forest"]},
    )

    r.turn_row(2, OPPONENT)
    # Hidden opponent draw: the instance id is known, the card is not.
    r.move(201, "library", "hand", "draw", OPPONENT, visible=1, text="[0:20] Opponent: drew a card")
    r.move(201, "hand", "stack", "cast", OPPONENT, 9101, "Lightning Bolt")
    r.add(
        "stack_push",
        "[0:21] Opponent: cast [Lightning Bolt (Instant)] -> [Grizzly Bears (2/2)]",
        event_type="cast",
        object_id=201,
        arena_id=9101,
        seat_id=OPPONENT,
        zone_from="hand",
        payload={
            "stack_id": "s3",
            "stack_kind": "spell",
            "name": "Lightning Bolt",
            "targets": [101],
        },
    )
    r.add(
        "stack_resolve",
        "\t[0:22] Stack: [Lightning Bolt (Instant)] [resolved]",
        event_type="stack_resolve",
        payload={"stack_id": "s3"},
    )
    r.move(201, "stack", "graveyard", "resolve", OPPONENT, 9101, "Lightning Bolt")
    r.add(
        "damage",
        "[0:22] [Grizzly Bears] (your) took 3 damage",
        event_type="damage",
        object_id=201,
        target_object_id=101,
        amount=3,
        payload={"combat": False},
    )
    r.move(
        101,
        "battlefield",
        "graveyard",
        "sba",
        PLAYER,
        9001,
        "Grizzly Bears",
        visible=1,
        text="[0:22] You: [Grizzly Bears] was put into graveyard (lethal damage)",
    )
    r.move(
        202,
        "library",
        "battlefield",
        "put",
        OPPONENT,
        9102,
        "Wall of Omens",
        visible=1,
        text="[0:23] Opponent: put [Wall of Omens] onto battlefield",
        type="Creature",
    )
    # Batched untap: one row per untap step, ids in the payload; 103 was never
    # seen before and must be introduced first.
    r.add("untap", seat_id=PLAYER, payload={"object_ids": [102, 103]})

    r.turn_row(3, PLAYER)
    r.move(
        105,
        "limbo",
        "battlefield",
        "token_create",
        PLAYER,
        9500,
        "Soldier",
        token=True,
        type="Creature",
    )
    r.add(
        "attack",
        "[0:30] You attacking [opponent] with [Soldier (1/1)]",
        event_type="attack",
        seat_id=PLAYER,
        payload={"object_ids": [105], "target_seat": OPPONENT},
    )
    r.add("block", seat_id=OPPONENT, payload={"pairs": [{"blocker": 202, "attacker": 105}]})
    r.add(
        "damage",
        "\t[0:31] Combat: [Soldier] dealt 1 damage to [Wall of Omens] (opponent's)",
        event_type="combat_damage",
        object_id=105,
        target_object_id=202,
        amount=1,
        payload={"combat": True},
    )
    r.add(
        "life",
        "[0:32] Opponent: lost 2 life (now 18)",
        event_type="life_loss",
        seat_id=OPPONENT,
        amount=-2,
        player_life=20,
        opponent_life=18,
        payload={"source_object_id": 105},
    )
    r.add("counter", object_id=202, amount=1, payload={"type": "+1/+1", "total": 1})
    r.add("pt", object_id=202, payload={"power": 1, "toughness": 5})
    r.add("attach", object_id=105, target_object_id=202)
    r.add("attach", object_id=105)
    r.add(
        "identity",
        "[0:33] Opponent: [Wall of Omens] became [Big Wall]",
        event_type="ability",
        object_id=202,
        arena_id=9103,
        payload={
            "name": "Big Wall",
            "type": "Creature",
            "power": 3,
            "toughness": 6,
            "face_down": False,
        },
    )
    r.add(
        "reveal",
        seat_id=OPPONENT,
        object_id=204,
        arena_id=9104,
        payload={"name": "Counterspell", "type": "Instant"},
    )
    r.add(
        "stack_push",
        "[0:34] Opponent: cast [Counterspell (Instant)]",
        event_type="cast",
        object_id=204,
        arena_id=9104,
        seat_id=OPPONENT,
        zone_from="hand",
        payload={"stack_id": "s4", "stack_kind": "spell", "name": "Counterspell"},
    )
    r.add(
        "stack_countered",
        "\t[0:35] Stack: [Counterspell (Instant)] [countered]",
        event_type="stack_fail",
        payload={"stack_id": "s4"},
    )
    r.move(204, "stack", "graveyard", "counter", OPPONENT, 9104, "Counterspell")
    r.add("shuffle", seat_id=PLAYER)
    r.add("note", "Session: W:1 L:0 | Games:1", event_type="turn")
    r.add("game_end", seat_id=PLAYER, payload={"reason": "Opponent conceded"})
    return r.rows


def _build():
    stream = build_recorded(_game_rows(_scenario()))
    assert validate_stream(stream) == []
    return stream


def _by_log(stream, fragment):
    return next(e for e in stream["events"] if e["log"] and fragment in e["log"]["text"])


def _next(stream, event, offset=1):
    return stream["events"][event["seq"] + offset]


def test_build_stream_dispatches_recorded_games_to_the_builder():
    stream = build_stream(_game_rows(_scenario()))
    assert stream["fidelity"] == "recorded"
    assert stream["replay_version"] == REPLAY_VERSION
    assert stream["limitations"] == []


def test_setup_synthesizes_opening_hands_with_root_ids():
    stream = _build()
    events = stream["events"]
    assert events[0]["kind"] == "game_start"
    assert events[0]["seats_hand_sizes"] == {"1": 7, "2": 2}
    assert events[0]["library_sizes"] == {"1": 53, "2": 38}
    opening = events[1:10]
    assert all(e["kind"] == "move" and (e["from"], e["to"]) == ("library", "hand") for e in opening)
    player = [e for e in opening if e["owner"] == PLAYER]
    # Forest was first seen leaving the hand, so the opening move uses its
    # real instance id; the Island never left the hand and gets a stand-in.
    assert ("102", "a9002") in [(e["obj"], e["card"]) for e in player]
    assert any(e["card"] == "n:Island" and e["obj"].startswith("h2-") for e in player)
    opponent = [e for e in opening if e["owner"] == OPPONENT]
    assert [e["card"] for e in opponent] == [None] * 7
    assert "204" in [e["obj"] for e in opponent]  # hindsight: same id is cast later
    mulligan = events[10]
    assert mulligan["kind"] == "mulligan" and (mulligan["from_size"], mulligan["to_size"]) == (7, 6)


def test_turns_phases_and_silent_rows_have_no_log():
    stream = _build()
    turns = [e for e in stream["events"] if e["kind"] == "turn"]
    assert [(e["turn"], e["active_seat"]) for e in turns] == [
        (1, PLAYER),
        (2, OPPONENT),
        (3, PLAYER),
    ]
    assert stream["turns"][0]["duration_seconds"] == 12.0
    phase = next(e for e in stream["events"] if e["kind"] == "phase")
    assert (phase["phase"], phase["step"], phase["log"]) == ("Phase_Main1", "Step_None", None)
    assert all(e["log"] is None for e in stream["events"] if e["kind"] in ("tap", "untap", "block"))
    draw = _by_log(stream, "drew [Grizzly Bears]")
    assert draw["log"]["segments"]
    assert any(seg.get("card_name") == "Grizzly Bears" for seg in draw["log"]["segments"])


def test_cast_synthesizes_the_move_and_resolution_closes_the_item():
    stream = _build()
    push = _by_log(stream, "cast [Grizzly Bears")
    move = _next(stream, push, -1)
    assert move["kind"] == "move" and (move["from"], move["to"], move["reason"]) == (
        "hand",
        "stack",
        "cast",
    )
    assert push["stack_kind"] == "spell" and push["stack_id"] == "s1" and push["obj"] == "101"
    resolve, enter = _next(stream, push), _next(stream, push, 2)
    assert resolve["kind"] == "stack_resolve" and resolve["stack_id"] == "s1"
    assert (enter["from"], enter["to"]) == ("stack", "battlefield")


def test_trigger_without_printed_resolution_resolves_immediately():
    stream = _build()
    trigger = _by_log(stream, "When this creature enters, scry 1.")
    assert (
        trigger["stack_kind"] == "trigger"
        and trigger["text"] == "When this creature enters, scry 1."
    )
    assert _next(stream, trigger)["kind"] == "stack_resolve"
    assert _next(stream, trigger)["stack_id"] == "s2"


def test_hidden_opponent_draw_keeps_its_id_for_hindsight():
    stream = _build()
    draw = _by_log(stream, "Opponent: drew a card")
    assert (draw["obj"], draw["card"]) == ("201", None)
    push = _by_log(stream, "cast [Lightning Bolt")
    moves = [e for e in stream["events"] if e["kind"] == "move" and e["obj"] == "201"]
    assert [(m["from"], m["to"]) for m in moves] == [
        ("library", "hand"),
        ("hand", "stack"),
        ("stack", "graveyard"),
    ]
    assert moves[1]["card"] == "a9101" and push["targets"] == ["101"]
    resolved = _by_log(stream, "Stack: [Lightning Bolt")
    assert resolved["kind"] == "stack_resolve" and _next(stream, resolved)["to"] == "graveyard"


def test_damage_tap_and_batched_untap():
    stream = _build()
    damage = _by_log(stream, "took 3 damage")
    assert (damage["source"], damage["target_obj"], damage["amount"], damage["combat"]) == (
        "201",
        "101",
        3,
        False,
    )
    tap = next(e for e in stream["events"] if e["kind"] == "tap")
    assert tap["objs"] == ["102"]
    untap = next(e for e in stream["events"] if e["kind"] == "untap")
    assert untap["objs"] == ["102", "103"]
    introduced = _next(stream, untap, -1)
    assert introduced["obj"] == "103" and introduced["from"] == "limbo" and introduced["inferred"]


def test_token_attack_block_combat_damage_and_life():
    stream = _build()
    token = next(
        e for e in stream["events"] if e["kind"] == "move" and e["reason"] == "token_create"
    )
    assert (token["obj"], token["from"], token["to"]) == ("105", "limbo", "battlefield")
    assert stream["cards"][token["card"]]["is_token"] is True
    attack = _by_log(stream, "attacking [opponent]")
    assert (attack["seat"], attack["objs"], attack["target_seat"], attack["target_obj"]) == (
        PLAYER,
        ["105"],
        OPPONENT,
        None,
    )
    block = next(e for e in stream["events"] if e["kind"] == "block")
    assert block["seat"] == OPPONENT and block["pairs"] == [{"blocker": "202", "attacker": "105"}]
    combat = _by_log(stream, "Combat: [Soldier]")
    assert combat["combat"] is True and combat["target_obj"] == "202"
    life = _by_log(stream, "lost 2 life")
    assert (life["seat"], life["life"], life["delta"], life["source_obj"]) == (
        OPPONENT,
        18,
        -2,
        "105",
    )


def test_counter_pt_attach_identity_and_reveal():
    stream = _build()
    counter = next(e for e in stream["events"] if e["kind"] == "counter")
    assert (counter["obj"], counter["type"], counter["delta"], counter["total"]) == (
        "202",
        "+1/+1",
        1,
        1,
    )
    pt = next(e for e in stream["events"] if e["kind"] == "pt")
    assert (pt["obj"], pt["power"], pt["toughness"]) == ("202", 1, 5)
    attaches = [e for e in stream["events"] if e["kind"] == "attach"]
    assert [(a["obj"], a["to"]) for a in attaches] == [("105", "202"), ("105", None)]
    identity = _by_log(stream, "became [Big Wall]")
    assert identity["kind"] == "identity" and identity["card"] == "a9103"
    assert stream["cards"]["a9103"]["name"] == "Big Wall"
    assert stream["cards"]["a9103"]["power"] == "3"
    reveal = next(e for e in stream["events"] if e["kind"] == "reveal")
    assert (reveal["obj"], reveal["card"]) == ("204", "a9104")


def test_countered_spell_scry_shuffle_note_and_game_end():
    stream = _build()
    push = _by_log(stream, "cast [Counterspell")
    assert _next(stream, push, -1)["from"] == "hand"  # the opening-hand object
    countered = _by_log(stream, "[countered]")
    assert countered["kind"] == "stack_countered" and countered["stack_id"] == "s4"
    assert _next(stream, countered)["reason"] == "counter"
    scry = _by_log(stream, "scried 1")
    assert (scry["seat"], scry["top"], scry["bottom"], scry["looked"]) == (PLAYER, ["301"], [], 1)
    assert any(e["kind"] == "shuffle" and e["seat"] == PLAYER for e in stream["events"])
    assert _by_log(stream, "Session:")["kind"] == "note"
    last = stream["events"][-1]
    assert last["kind"] == "game_end" and last["winner_seat"] == PLAYER
    assert last["reason"] == "Opponent conceded"
    assert sum(1 for e in stream["events"] if e["kind"] == "game_end") == 1


def test_every_spell_push_follows_its_move_to_the_stack():
    stream = _build()
    for event in stream["events"]:
        if event["kind"] == "stack_push" and event["stack_kind"] == "spell":
            move = _next(stream, event, -1)
            assert move["kind"] == "move" and move["to"] == "stack" and move["obj"] == event["obj"]


def test_seat_colors_and_images_from_local_resolver():
    stream = _build()
    assert stream["seats"][str(PLAYER)]["colors"] == "G"
    attach_image_urls(stream, resolver=lambda arena_id: f"https://cards.scryfall.io/{arena_id}.jpg")
    assert stream["cards"]["a9001"]["image_url"] == "https://cards.scryfall.io/9001.jpg"
    assert stream["cards"]["n:Island"]["image_url"] is None


def test_builder_is_robust_to_a_move_from_an_unknown_zone_object():
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(
        900,
        "battlefield",
        "graveyard",
        "destroy",
        OPPONENT,
        9001,
        "Grizzly Bears",
        visible=1,
        text="[0:01] Opponent: [Grizzly Bears] was destroyed",
    )
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    introduced, destroyed = [
        e for e in stream["events"] if e["kind"] == "move" and e["obj"] == "900"
    ]
    assert (introduced["from"], introduced["to"], introduced["inferred"]) == (
        "limbo",
        "battlefield",
        True,
    )
    assert destroyed["reason"] == "destroy"


def test_exile_move_carries_the_host_that_exiled_it():
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(318, "limbo", "battlefield", "put", OPPONENT, 2003, "Deep-Cavern Bat")
    r.move(
        280,
        "hand",
        "exile",
        "exile",
        PLAYER,
        1008,
        "Island",
        visible=1,
        text="[0:01] You: [Island] was exiled",
        **{"with": 318},
    )
    r.move(281, "battlefield", "exile", "exile", PLAYER, 1001, "Forest")
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    exiles = [e for e in stream["events"] if e["kind"] == "move" and e["to"] == "exile"]
    assert [(e["obj"], e["with"]) for e in exiles] == [("280", "318"), ("281", None)]
    put = next(e for e in stream["events"] if e["kind"] == "move" and e["obj"] == "318")
    assert put["with"] is None


def test_move_carries_the_source_that_moved_it():
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(401, "limbo", "battlefield", "put", OPPONENT, 1001, "Forest")
    r.move(401, "battlefield", "graveyard", "destroy", OPPONENT, 1001, "Forest", by=400)
    r.move(402, "limbo", "battlefield", "put", OPPONENT, 1001, "Forest")
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    moves = [(e["obj"], e["reason"], e["by"]) for e in stream["events"] if e["kind"] == "move"]
    assert ("401", "destroy", "400") in moves
    assert ("402", "put", None) in moves


def test_land_play_carries_the_chosen_land_type():
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(
        403,
        "hand",
        "battlefield",
        "play_land",
        PLAYER,
        97998,
        "Multiversal Passage",
        chosen="Mountain",
    )
    r.move(404, "hand", "battlefield", "play_land", PLAYER, 1001, "Forest")
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    chosen = {e["obj"]: e["chosen"] for e in stream["events"] if e["kind"] == "move"}
    assert chosen["403"] == "Mountain" and chosen["404"] is None


def test_stack_push_payload_accepts_stack_kind_and_legacy_kind():
    stream = _build()
    pushes = {e["stack_id"]: e["stack_kind"] for e in stream["events"] if e["kind"] == "stack_push"}
    # s1/s3/s4 use "stack_kind"; s2 still uses the legacy payload key "kind".
    assert pushes == {"s1": "spell", "s2": "trigger", "s3": "spell", "s4": "spell"}


def test_printed_move_uses_the_owner_from_the_payload_not_the_text_actor():
    """ "[Source] returned [X] to opponent's hand" names the source's seat."""
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(900, "limbo", "battlefield", "put", OPPONENT, 9001, "Grizzly Bears")
    r.move(
        900,
        "battlefield",
        "hand",
        "bounce",
        PLAYER,
        9001,
        "Grizzly Bears",
        visible=1,
        text="[0:01] You: [Unsummon] returned [Grizzly Bears] to opponent's hand",
        owner=OPPONENT,
    )
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    bounce = _by_log(stream, "returned [Grizzly Bears]")
    assert (bounce["owner"], bounce["to"]) == (OPPONENT, "hand")


def test_reveal_of_an_object_no_row_placed_creates_nothing():
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.add("reveal", seat_id=OPPONENT, object_id=181, arena_id=9101, payload={"name": "Bolt"})
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    assert not [e for e in stream["events"] if e.get("obj") == "181"]


def test_untap_rows_before_a_lazy_turn_header_belong_to_the_new_turn():
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(101, "hand", "battlefield", "play_land", PLAYER, 9002, "Forest")
    r.add("tap", seat_id=PLAYER, payload={"object_ids": [101]})
    r.turn = 2
    r.add("untap", seat_id=OPPONENT, payload={"object_ids": [101]})
    r.turn_row(2, OPPONENT)
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    kinds = [e["kind"] for e in stream["events"] if e["kind"] in ("turn", "tap", "untap")]
    assert kinds == ["turn", "tap", "turn", "untap"]
    turn_two = stream["turns"][1]
    untap = next(e for e in stream["events"] if e["kind"] == "untap")
    assert turn_two["first_seq"] < untap["seq"] <= turn_two["last_seq"]


def test_creature_stats_on_a_move_seed_the_cards_printed_stats():
    """A 0/2 whose cards-table row never learned its stats: the capture stamps
    the current stats on the row, and the stream's card entry keeps them."""
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(
        500,
        "stack",
        "battlefield",
        "resolve",
        PLAYER,
        9005,
        "Exhibition Tidecaller",
        type="Creature",
        power=0,
        toughness=2,
    )
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    card = stream["cards"]["a9005"]
    assert (card["power"], card["toughness"]) == ("0", "2")


def test_card_facts_mark_keywords_and_back_faces_and_back_images():
    stream = {
        "cards": {
            "a:1": {
                "name": "Esper Origins",
                "arena_id": 1,
                "image_url": None,
                "keywords": [],
                "back_face": False,
            },
            "a:2": {
                "name": "Summon: Esper Maduin",
                "arena_id": 2,
                "image_url": None,
                "keywords": [],
                "back_face": False,
            },
            "n:Bear": {
                "name": "Bear",
                "arena_id": None,
                "image_url": None,
                "keywords": [],
                "back_face": False,
            },
        }
    }
    facts = {
        "esper origins": {"keywords": ["flashback"], "back_face": False, "front": None},
        "summon: esper maduin": {"keywords": [], "back_face": True, "front": "Esper Origins"},
    }
    attach_card_facts(stream, facts)
    attach_image_urls(
        stream,
        resolver=lambda arena_id: f"https://cards.scryfall.io/normal/front/a/b/{arena_id}.jpg",
    )
    cards = stream["cards"]
    assert cards["a:1"]["keywords"] == ["flashback"]
    assert cards["a:1"]["image_url"].endswith("/front/a/b/1.jpg")
    assert cards["a:2"]["back_face"] is True
    assert cards["a:2"]["image_url"] == "https://cards.scryfall.io/normal/back/a/b/2.jpg"
    assert cards["n:Bear"]["keywords"] == [] and cards["n:Bear"]["back_face"] is False


def test_card_facts_look_tokens_up_by_arena_id_before_name():
    def token(arena_id):
        return {"name": "Bird", "arena_id": arena_id, "is_token": True, "keywords": []}

    stream = {"cards": {"a7": token(7), "a8": token(8), "n:Bird": token(None)}}
    facts = {"#7": {"keywords": ["flying"]}, "bird": {"keywords": ["flashback"]}}
    attach_card_facts(stream, facts)
    cards = stream["cards"]
    assert cards["a7"]["keywords"] == ["flying"]
    assert cards["a8"]["keywords"] == ["flashback"]
    assert cards["n:Bird"]["keywords"] == ["flashback"]


def test_a_token_copy_of_a_real_card_shows_the_card_itself():
    """A token copy of Emrakul carries Emrakul's own Arena id, which the real
    card shares: the entry is the card, never the token printing (Cadet)."""
    stream = {
        "cards": {
            "a106225": {"name": "Emrakul, the Exigent Doom", "arena_id": 106225, "is_token": True},
            "a106554": {"name": "Illusion", "arena_id": 106554, "is_token": True},
        }
    }
    facts = {"emrakul, the exigent doom": {"keywords": [], "grp_ids": [106225]}}
    attach_card_facts(stream, facts)
    attach_image_urls(stream, resolver=lambda arena_id: f"img/{arena_id}", token_printer=str)
    emrakul, illusion = stream["cards"]["a106225"], stream["cards"]["a106554"]
    assert (emrakul["is_token"], emrakul["image_url"]) == (False, "img/106225")
    assert (illusion["is_token"], illusion.get("image_url"), illusion["token_print"]) == (
        True,
        None,
        "106554",
    )


def test_tokens_created_attacking_appear_before_their_attack():
    """Mobilize: Arena creates the Warriors and declares them attackers in one
    message, and the printed attack lines are written before the silent
    creation rows. The stream must create each token first, not invent an
    inferred card that attacks from nowhere."""
    r = _Rows()
    r.turn_row(6, PLAYER)
    for obj in (310, 311):
        r.add(
            "attack",
            "[1:34] You attacking [opponent] with [Warrior (1/1)]",
            event_type="attack",
            seat_id=PLAYER,
            object_id=obj,
            payload={"object_ids": [obj], "target_seat": OPPONENT},
        )
    for obj in (310, 311):
        r.move(obj, "limbo", "battlefield", "token_create", PLAYER, 95832, "Warrior", token=True)
    stream = build_stream(_game_rows(r.rows))

    kinds = [(e["kind"], e.get("obj") or e.get("objs")) for e in stream["events"]]
    assert kinds.index(("move", "310")) < kinds.index(("attack", ["310"]))
    assert kinds.index(("move", "311")) < kinds.index(("attack", ["311"]))
    assert not any(e["kind"] == "move" and e["inferred"] for e in stream["events"])


def test_tokens_get_their_token_printing_never_the_card_sets_image():
    stream = {
        "cards": {
            "a95832": {"name": "Warrior", "arena_id": 95832, "is_token": True, "image_url": None},
            "a95549": {"name": "Voice of Victory", "arena_id": 95549, "is_token": False},
        }
    }
    attach_image_urls(
        stream,
        resolver=lambda arena_id: f"https://cards.scryfall.io/{arena_id}.jpg",
        token_printer=lambda arena_id: "ttdm/13",
    )
    warrior = stream["cards"]["a95832"]
    assert warrior["image_url"] is None
    assert warrior["token_print"] == "ttdm/13"
    assert stream["cards"]["a95549"]["image_url"] == "https://cards.scryfall.io/95549.jpg"


def test_token_print_is_the_scryfall_token_set(monkeypatch):
    from mtga_tracker import replay_builder

    monkeypatch.setitem(
        replay_builder._image_state, "index", {95832: ("Warrior", "TDM", "13"), 1: ("X", "", "")}
    )
    assert replay_builder.default_token_print(95832) == "ttdm/13"
    assert replay_builder.default_token_print(1) is None
    assert replay_builder.default_token_print(2) is None


def test_a_card_without_a_cached_image_names_its_printing():
    """Scryfall learns a new set's Arena ids late, so a card the image cache
    does not know names its set and number for the page to look up."""
    stream = {
        "cards": {
            "a106248": {"name": "Unflinching Hortimancer", "arena_id": 106248},
            "a91556": {"name": "Lifecreed Duo", "arena_id": 91556},
        }
    }
    cached = {91556: "https://cards.scryfall.io/normal/front/c/a/ca.jpg"}
    attach_image_urls(stream, resolver=cached.get, token_printer=str, printer=lambda a: f"x/{a}")
    hortimancer, duo = stream["cards"]["a106248"], stream["cards"]["a91556"]
    assert (hortimancer["image_url"], hortimancer["print"]) == (None, "x/106248")
    assert duo["image_url"] == cached[91556] and "print" not in duo


def test_print_is_the_scryfall_set_and_number(monkeypatch):
    from mtga_tracker import replay_builder

    monkeypatch.setitem(replay_builder._image_state, "index", {106248: ("U", "FRA", "23")})
    assert replay_builder.default_print(106248) == "fra/23"
    assert replay_builder.default_print(2) is None


def test_counters_recorded_by_number_get_arena_names():
    from mtga_tracker.replay_builder import attach_counter_names

    stream = {
        "events": [
            {"kind": "counter", "type": "counter_211", "obj": "1", "delta": 1, "total": 1},
            {"kind": "counter", "type": "counter_999", "obj": "1", "delta": 1, "total": 1},
            {"kind": "counter", "type": "+1/+1", "obj": "2", "delta": 1, "total": 1},
        ]
    }
    attach_counter_names(stream, {"#counter:211": {"counter": "plan"}})
    assert [event["type"] for event in stream["events"]] == ["plan", "counter_999", "+1/+1"]


def test_a_prepared_spell_copy_cast_from_exile_appears_on_the_stack():
    """Arena makes the copy in exile and casts it at once: no inferred card in exile first."""
    r = _Rows()
    r.turn_row(3, OPPONENT)
    r.add(
        "stack_push",
        "[0:49] Opponent: cast [Rampant Growth (Sorcery)]",
        event_type="cast",
        seat_id=OPPONENT,
        object_id=296,
        arena_id=104085,
        zone_from="exile",
        zone_to="stack",
        payload={
            "stack_id": "s3",
            "stack_kind": "spell",
            "name": "Rampant Growth",
            "type": "Sorcery",
        },
    )
    stream = build_stream(_game_rows(r.rows))
    moves = [e for e in stream["events"] if e["kind"] == "move" and e["obj"] == "296"]
    assert [(m["from"], m["to"], m["inferred"]) for m in moves] == [("limbo", "stack", False)]


def test_a_ninjutsu_attacker_is_the_card_put_onto_the_battlefield():
    """Kaito's attack line names its new instance id (501) before the move
    that puts Kaito (317) onto the battlefield; the echoed trigger line for
    the same ninjutsu is dropped."""
    r = _Rows()
    r.turn_row(9, PLAYER)
    r.move(
        317,
        "library",
        "hand",
        "draw",
        PLAYER,
        92314,
        "Kaito, Bane of Nightmares",
        visible=1,
        text="drew",
    )
    ninjutsu = {
        "stack_kind": "trigger",
        "name": "Kaito, Bane of Nightmares",
        "text": "Ninjutsu 1UB",
    }
    r.add(
        "stack_push",
        "[4:54] Kaito - Ninjutsu",
        seat_id=PLAYER,
        object_id=317,
        arena_id=92314,
        payload={**ninjutsu, "stack_id": "s23"},
    )
    r.add(
        "stack_push",
        "[4:56] Kaito - Ninjutsu",
        seat_id=PLAYER,
        object_id=317,
        arena_id=92314,
        payload={**ninjutsu, "stack_id": "s24", "stack_kind": "activated"},
    )
    r.add(
        "attack",
        "[4:56] You attacking [opponent] with [Kaito, Bane of Nightmares (3/4)]",
        event_type="attack",
        seat_id=PLAYER,
        object_id=501,
        payload={"object_ids": [501], "target_seat": OPPONENT},
    )
    r.add("stack_resolve", "resolved", seat_id=PLAYER, payload={"stack_id": "s24"})
    r.move(
        317,
        "hand",
        "battlefield",
        "put",
        PLAYER,
        92314,
        "Kaito, Bane of Nightmares",
        visible=1,
        text="put",
    )
    stream = build_stream(_game_rows(r.rows))
    events = stream["events"]
    assert not any(e["kind"] == "move" and e["inferred"] for e in events)
    attack = next(e for e in events if e["kind"] == "attack")
    assert attack["objs"] == ["317"]
    put = next(
        e for e in events if e["kind"] == "move" and e["obj"] == "317" and e["to"] == "battlefield"
    )
    assert put["seq"] < attack["seq"]
    assert [e["stack_id"] for e in events if e["kind"] == "stack_push"] == ["s24"]


def test_a_card_exiled_until_its_host_leaves_is_tucked_under_it():
    """Rows recorded before the capture could find a deleted ability's source:
    the exile names only the ability (no other row knows it). Right after a
    trigger that exiles "until ... leaves the battlefield", the card goes under
    that trigger's source; any other exile stays in the pile."""
    snare = "When this artifact enters, exile target nonland permanent an opponent controls until this artifact leaves the battlefield."
    r = _Rows()
    r.turn_row(4, PLAYER)
    r.move(
        233, "library", "battlefield", "put", PLAYER, 94825, "Perilous Snare", visible=1, text="put"
    )
    r.move(
        286,
        "limbo",
        "battlefield",
        "put",
        OPPONENT,
        86690,
        "Cheeky House-Mouse",
        visible=1,
        text="put",
    )
    r.move(
        287, "limbo", "battlefield", "put", OPPONENT, 86691, "Other Mouse", visible=1, text="put"
    )
    r.add(
        "stack_push",
        "[1:48] Snare trigger",
        seat_id=PLAYER,
        object_id=233,
        arena_id=94825,
        payload={
            "stack_id": "s11",
            "stack_kind": "trigger",
            "name": "Perilous Snare",
            "text": snare,
        },
    )
    r.add("stack_resolve", "resolved", seat_id=PLAYER, payload={"stack_id": "s11"})
    r.move(
        286,
        "battlefield",
        "exile",
        "exile",
        OPPONENT,
        86690,
        "Cheeky House-Mouse",
        visible=1,
        text="exiled",
        by=384,
    )
    r.add(
        "stack_push",
        "[1:52] Banish",
        seat_id=PLAYER,
        object_id=233,
        arena_id=94825,
        payload={
            "stack_id": "s12",
            "stack_kind": "activated",
            "name": "Perilous Snare",
            "text": "Exile target creature.",
        },
    )
    r.add("stack_resolve", "resolved", seat_id=PLAYER, payload={"stack_id": "s12"})
    r.move(
        287,
        "battlefield",
        "exile",
        "exile",
        OPPONENT,
        86691,
        "Other Mouse",
        visible=1,
        text="exiled",
        by=385,
    )
    stream = build_stream(_game_rows(r.rows))
    exiles = {e["obj"]: e for e in stream["events"] if e["kind"] == "move" and e["to"] == "exile"}
    assert (exiles["286"]["with"], exiles["286"]["by"]) == ("233", "233")
    assert exiles["287"]["with"] is None


def test_an_until_leaves_card_whose_trigger_was_never_printed_still_tucks():
    """Sheltered by Ghosts resolves as an Aura and its trigger line never reaches
    the rows: the card facts (Arena's abilities) say it exiles until it leaves."""

    def rows(facts):
        r = _Rows()
        r.turn_row(5, PLAYER)
        r.move(500, "limbo", "battlefield", "put", OPPONENT, 700, "Bear", visible=1, text="put")
        r.add(
            "stack_push",
            "[2:00] You: cast [Sheltered by Ghosts (Enchantment)]",
            seat_id=PLAYER,
            object_id=410,
            arena_id=90410,
            zone_from="hand",
            zone_to="stack",
            payload={"stack_id": "s9", "stack_kind": "spell", "name": "Sheltered by Ghosts"},
        )
        r.add("stack_resolve", "resolved", seat_id=PLAYER, payload={"stack_id": "s9"})
        r.move(410, "stack", "battlefield", "resolve", PLAYER, 90410, "Sheltered by Ghosts")
        r.move(
            500,
            "battlefield",
            "exile",
            "exile",
            OPPONENT,
            700,
            "Bear",
            visible=1,
            text="exiled",
            by=999,
        )
        data = _game_rows(r.rows)
        data["card_facts"] = facts
        exile = next(
            e for e in build_stream(data)["events"] if e["kind"] == "move" and e["to"] == "exile"
        )
        return exile["with"]

    assert rows({"sheltered by ghosts": {"exiles_until_leaves": True}}) == "410"
    assert rows({}) is None


def test_a_permanent_whose_enters_trigger_printed_first_enters_before_it():
    """Arena can put a card onto the battlefield and its enters trigger on the
    stack in one message, printing the trigger first (Repurposing Bay fetching
    Pinnacle Starcage). The card enters from the library, not from nowhere."""
    r = _Rows()
    r.turn_row(9, PLAYER)
    moment = "2026-06-04T00:11:00"
    rows = [
        r.add(
            "stack_push",
            "[3:46] Starcage trigger",
            seat_id=PLAYER,
            object_id=278,
            arena_id=96601,
            payload={"stack_id": "s22", "stack_kind": "trigger", "name": "Pinnacle Starcage"},
        ),
        r.move(
            278,
            "library",
            "battlefield",
            "put",
            PLAYER,
            96601,
            "Pinnacle Starcage",
            visible=1,
            text="put",
        ),
    ]
    for row in rows:
        row["event_time"] = moment
    stream = build_stream(_game_rows(r.rows))
    kinds = [(e["kind"], e.get("from"), e.get("inferred")) for e in stream["events"]]
    assert ("move", "library", False) in kinds
    assert kinds.index(("move", "library", False)) < kinds.index(("stack_push", None, None))
    assert not any(e.get("inferred") for e in stream["events"])


def test_a_trigger_from_an_earlier_moment_never_pulls_the_entry_back():
    """A cast card's trigger resolving before the card returns from the
    graveyard keeps its order: only rows of the entry's own moment move."""
    r = _Rows()
    r.turn_row(5, PLAYER)
    r.move(40, "library", "graveyard", "mill", PLAYER, 1, "Bear", visible=1, text="milled")
    r.add(
        "stack_push",
        "[2:00] Bear trigger",
        seat_id=PLAYER,
        object_id=40,
        arena_id=1,
        payload={"stack_id": "s3", "stack_kind": "trigger", "name": "Bear"},
    )
    r.add("stack_resolve", "resolved", seat_id=PLAYER, payload={"stack_id": "s3"})
    r.move(40, "graveyard", "battlefield", "put", PLAYER, 1, "Bear", visible=1, text="returned")
    stream = build_stream(_game_rows(r.rows))
    order = [
        (e["kind"], e.get("to"))
        for e in stream["events"]
        if e["kind"] in ("stack_push", "move") and e.get("obj") == "40"
    ]
    assert order == [("move", "graveyard"), ("stack_push", None), ("move", "battlefield")]


def test_a_repeated_silent_land_play_is_dropped():
    """Arena can send a land play's transfer again; the silent repeat would move
    the land from the battlefield to the battlefield."""
    r = _Rows()
    r.turn_row(8, PLAYER)
    r.move(
        162, "hand", "battlefield", "play_land", PLAYER, 5, "Realm of Koh", visible=1, text="played"
    )
    r.move(162, "hand", "battlefield", "play_land", PLAYER, 5, "Realm of Koh")
    stream = build_stream(_game_rows(r.rows))
    moves = [e for e in stream["events"] if e["kind"] == "move" and e["to"] == "battlefield"]
    assert [(m["obj"], m["from"]) for m in moves] == [("162", "hand")]


# -- summoning sickness ----------------------------------------------------


def _bears_cast_turn_one():
    """Grizzly Bears resolve on turn 1 (you), the opponent takes turn 2, you take turn 3."""
    r = _Rows()
    r.turn_row(1, PLAYER)
    r.move(101, "hand", "stack", "cast", PLAYER, 9001, "Grizzly Bears")
    r.add(
        "stack_push",
        "[0:12] You: cast [Grizzly Bears (Creature 2/2)]",
        event_type="cast",
        object_id=101,
        arena_id=9001,
        seat_id=PLAYER,
        zone_from="hand",
        payload={"stack_id": "s1", "stack_kind": "spell", "name": "Grizzly Bears"},
    )
    r.move(101, "stack", "battlefield", "resolve", PLAYER, 9001, "Grizzly Bears")
    return r


def _sickness(stream):
    return [
        (e["kind"], e["turn"], e["objs"])
        for e in stream["events"]
        if e["kind"] in ("sick", "unsick")
    ]


def test_recorded_sickness_rows_become_events_and_untap_with_the_turn():
    r = _bears_cast_turn_one()
    r.add("sick", seat_id=PLAYER, controller_seat=PLAYER, payload={"object_ids": [101]})
    r.turn_row(2, OPPONENT)
    r.add("phase", phase="Phase_Main1", step="Step_None")
    # The untap step's silent rows are captured before the lazily printed turn header.
    r.turn = 3
    r.add("untap", seat_id=PLAYER, payload={"object_ids": [101]}, turn_number=3)
    r.add("unsick", seat_id=PLAYER, payload={"object_ids": [101]}, turn_number=3)
    r.turn_row(3, PLAYER)
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    assert _sickness(stream) == [("sick", 1, ["101"]), ("unsick", 3, ["101"])]
    turn3 = next(e for e in stream["events"] if e["kind"] == "turn" and e["turn"] == 3)
    unsick = next(e for e in stream["events"] if e["kind"] == "unsick")
    assert unsick["seq"] > turn3["seq"]
    assert stream["limitations"] == []


def test_recorded_games_never_estimate_sickness_arena_did_not_report():
    """Arena leaves the flag off for haste, printed or granted: no rows, no badge."""
    r = _bears_cast_turn_one()
    r.turn_row(2, OPPONENT)
    stream = build_recorded(_game_rows(r.rows))
    assert _sickness(stream) == []
    assert stream["limitations"] == []


def test_games_recorded_before_the_flag_estimate_it_from_entries():
    r = _bears_cast_turn_one()
    r.turn_row(2, OPPONENT)
    r.turn_row(3, PLAYER)
    stream = build_recorded(_game_rows(r.rows, replay_version=1))
    assert validate_stream(stream) == []
    assert _sickness(stream) == [("sick", 1, ["101"]), ("unsick", 3, ["101"])]
    resolve = next(e for e in stream["events"] if e["kind"] == "move" and e["reason"] == "resolve")
    assert _next(stream, resolve)["kind"] == "sick"
    assert [e["seq"] for e in stream["events"]] == list(range(len(stream["events"])))
    turns = {t["turn"]: t for t in stream["turns"]}
    assert stream["events"][turns[3]["first_seq"]]["kind"] == "turn"
    assert stream["limitations"] == [SICKNESS_ESTIMATE_LIMITATION]


def test_sickness_estimate_skips_printed_haste_and_wakes_attackers():
    r = _bears_cast_turn_one()
    r.add(
        "attack",
        "[0:13] You attacking [Them] with [Grizzly Bears (2/2)]",
        event_type="attack",
        seat_id=PLAYER,
        payload={"object_ids": [101], "target_seat": OPPONENT},
    )
    rows = _game_rows(r.rows, replay_version=1)
    stream = build_recorded(rows)
    attack = next(e for e in stream["events"] if e["kind"] == "attack")
    assert stream["events"][attack["seq"] - 1]["kind"] == "unsick"
    rows["card_facts"] = {"grizzly bears": {"keywords": ["haste"]}}
    assert _sickness(build_recorded(rows)) == []


def _emrakul_returns(*, second_copy_in_exile=False):
    """Emrakul exiles itself from the hand; Arena casts it from exile in a
    message its log only summarized, so it reappears as 555, never moved."""
    r = _Rows()
    r.turn_row(3, PLAYER)
    r.move(
        283, "library", "hand", "draw", PLAYER, arena_id=106225, name="Emrakul, the Exigent Doom"
    )
    r.move(283, "hand", "exile", "exile", PLAYER, arena_id=106225, name="Emrakul, the Exigent Doom")
    if second_copy_in_exile:
        r.move(
            284, "hand", "exile", "exile", PLAYER, arena_id=106225, name="Emrakul, the Exigent Doom"
        )
    r.move(289, "hand", "battlefield", "play_land", PLAYER, arena_id=106424, name="Hall of Echoes")
    r.turn_row(15, PLAYER)
    r.add(
        "stack_push",
        "[8:00] You: [Hall of Echoes] - 5: This land becomes a copy of target creature you control",
        event_type="ability",
        seat_id=PLAYER,
        controller_seat=PLAYER,
        object_id=289,
        target_object_id=555,
        arena_id=106424,
        payload={"stack_id": "s29", "stack_kind": "activated", "targets": [555]},
    )
    r.turn_row(16, OPPONENT)
    r.move(164, "limbo", "battlefield", "put", OPPONENT, arena_id=93636, name="Sanctifier")
    r.add(
        "block",
        seat_id=PLAYER,
        controller_seat=PLAYER,
        object_id=555,
        payload={"pairs": [{"blocker": 555, "attacker": 164}]},
    )
    r.add("sick", seat_id=PLAYER, controller_seat=PLAYER, payload={"object_ids": [555]})
    r.add(
        "damage",
        "[8:55] [Sanctifier] (opponent's) took 12 damage",
        event_type="damage",
        seat_id=PLAYER,
        controller_seat=PLAYER,
        object_id=555,
        target_object_id=164,
        arena_id=106225,
        amount=12,
    )
    rows = _game_rows(r.rows)
    rows["cards"].append(
        {
            "id": 9,
            "arena_id": 106225,
            "name": "Emrakul, the Exigent Doom",
            "primary_type": "Creature",
        }
    )
    return rows


def test_a_card_arenas_log_lost_track_of_returns_from_exile():
    stream = build_recorded(_emrakul_returns())
    assert validate_stream(stream) == []
    events = stream["events"]
    assert not any("555" in json.dumps({k: v for k, v in e.items() if k != "log"}) for e in events)
    back = next(e for e in events if e["kind"] == "move" and e["from"] == "exile")
    # The card and where it went are known, so it carries no "inferred" tag.
    assert (back["obj"], back["to"], back["inferred"], back["turn"]) == (
        "283",
        "battlefield",
        False,
        15,
    )
    # Arena's flag came with its first sighting: it was sick from its arrival.
    assert _next(stream, back)["kind"] == "sick" and _next(stream, back)["objs"] == ["283"]
    push = next(e for e in events if e["kind"] == "stack_push")
    assert push["seq"] > back["seq"] and push["targets"] == ["283"]
    block = next(e for e in events if e["kind"] == "block")
    assert block["pairs"] == [{"blocker": "283", "attacker": "164"}]
    assert [e["objs"] for e in events if e["kind"] == "sick"] == [["283"]]
    assert stream["limitations"] == [LOST_ARRIVAL_LIMITATION]


def test_an_ambiguous_lost_arrival_is_inferred_with_the_card_its_rows_name():
    """Two copies in exile: no guessing which one; the newcomer is still shown as Emrakul."""
    stream = build_recorded(_emrakul_returns(second_copy_in_exile=True))
    assert validate_stream(stream) == []
    arrival = next(e for e in stream["events"] if e["kind"] == "move" and e["obj"] == "555")
    assert (arrival["from"], arrival["inferred"], arrival["card"]) == ("limbo", True, "a106225")
    assert stream["limitations"] == []


def test_an_opponent_draw_saved_as_yours_goes_back_to_their_hand():
    """Arena reused an undone ability's id for the opponent's hidden draw; an
    older tracker kept the ability's seat, so the row says you drew it."""
    r = _Rows()
    r.turn_row(9, PLAYER)
    r.move(290, "library", "hand", "draw", PLAYER, arena_id=9001, name="Forest")
    r.turn_row(10, OPPONENT)
    r.move(
        404,
        "library",
        "hand",
        "draw",
        PLAYER,
        arena_id=76738,
        visible=1,
        text="[4:11] You: drew a card",
    )
    r.turn_row(16, OPPONENT)
    r.move(404, "hand", "stack", "cast", OPPONENT, arena_id=9101, name="Lightning Bolt")
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    draw = _by_log(stream, "drew a card")
    assert draw["log"]["text"] == "[4:11] Opponent: drew a card"
    assert (draw["obj"], draw["owner"], draw["card"]) == ("404", OPPONENT, None)
    assert "a76738" not in stream["cards"]
    # Your own draw, whose next move is from your hand, is left alone.
    forest = next(e for e in stream["events"] if e.get("obj") == "290")
    assert forest["owner"] == PLAYER


def test_a_card_bottomed_for_a_mulligan_starts_in_the_opening_hand():
    """Capture saves the kept cards as the opening hand, then the bottomed card
    leaving the hand once turn 1 has begun."""
    r = _Rows()
    r.add("mulligan", seat_id=PLAYER, amount=6, payload={"from_size": 7, "to_size": 6})
    for obj in range(281, 287):
        r.move(obj, "library", "hand", "draw", PLAYER, arena_id=9001, name="Forest", opening=True)
    r.turn_row(1, PLAYER)
    r.move(280, "hand", "library", "put", PLAYER, arena_id=9002, name="Island", by=PLAYER)
    r.move(281, "hand", "battlefield", "play_land", PLAYER, arena_id=9001, name="Forest")
    stream = build_recorded(_game_rows(r.rows))
    assert validate_stream(stream) == []
    start = stream["events"][0]
    assert start["seats_hand_sizes"][str(PLAYER)] == 7
    dealt = [e["obj"] for e in stream["events"] if e["kind"] == "move" and e["turn"] == 0]
    assert "280" in dealt
    bottom = next(e for e in stream["events"] if e.get("obj") == "280" and e["turn"] == 1)
    assert (bottom["from"], bottom["to"]) == ("hand", "library")
