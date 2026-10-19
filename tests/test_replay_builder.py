"""Replay builder for games captured with structured rows (replay_version = 1)."""

import json

from mtga_tracker.replay_builder import (
    attach_card_facts,
    attach_image_urls,
    build_recorded,
    build_stream,
)
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


def _game_rows(events):
    return {
        "games": [
            {
                "id": "g1",
                "outcome": "win",
                "winner_participant_id": "p-me",
                "game_number": 1,
                "replay_version": 1,
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
    assert stream["replay_version"] == 1
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
