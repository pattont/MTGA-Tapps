"""Text reconstructor for games recorded before structured capture."""

import copy
import json
import time
from pathlib import Path

import pytest

from mtga_tracker.replay_reconstruct import pair_stack_rows, parse_bracket, reconstruct
from mtga_tracker.replay_stream import validate_stream

FIXTURES = Path(__file__).parent / "fixtures" / "replay"
FIXTURE_NAMES = ["short_game", "brawl_tokens_commanders", "mulligan_counter_unknown"]

PLAYER, OPPONENT = 2, 1  # the local player is deliberately not seat 1


def _rows(
    events,
    *,
    hand=("Forest", "Grizzly Bears", "Shock", "Forest", "Forest", "Island", "Island"),
    deck=None,
    player_mulligans=0,
    opponent_mulligans=0,
    ending=(None, None),
    commanders=(),
    fmt="Play",
    deck_size=60,
    opponent_deck_size=None,
):
    """Minimal game rows; each event is (event_type, text[, turn[, lives]])."""
    deck = deck or {"Forest": 20, "Island": 20, "Grizzly Bears": 10, "Shock": 10}
    game_events = []
    lives = (20, 20)
    turn = 0
    for index, event in enumerate(events):
        event_type, text = event[0], event[1]
        if event_type == "turn" and text.startswith("Turn "):
            turn = int(text.split()[1])
        if len(event) > 2 and event[2] is not None:
            turn = event[2]
        if len(event) > 3:
            lives = event[3]
        game_events.append(
            {
                "id": index + 1,
                "event_time": f"2026-06-04T00:{index // 60:02d}:{index % 60:02d}",
                "elapsed_seconds": index,
                "turn_number": turn,
                "phase": "Phase_Main1",
                "step": None,
                "seat_id": None,
                "actor_role": None,
                "event_type": event_type,
                "text": text,
                "player_life": lives[0],
                "opponent_life": lives[1],
            }
        )
    return {
        "games": [
            {
                "id": "g",
                "outcome": "win",
                "winner_participant_id": "p-me",
                "game_number": 1,
                "outcome_reason": "Opponent conceded",
            }
        ],
        "matches": [{"format": fmt, "best_of": 1}],
        "participants": [
            {
                "id": "p-me",
                "role": "player",
                "seat_id": PLAYER,
                "deck_size": deck_size,
                "mulligans": player_mulligans,
                "starting_life": 20,
                "ending_life": ending[0],
            },
            {
                "id": "p-opp",
                "role": "opponent",
                "seat_id": OPPONENT,
                "deck_size": opponent_deck_size,
                "mulligans": opponent_mulligans,
                "starting_life": 20,
                "ending_life": ending[1],
            },
        ],
        "participant_commanders": [
            {"participant_id": pid, "card_name": name} for pid, name in commanders
        ],
        "game_events": game_events,
        "game_opening_hand_cards": [
            {
                "participant_id": "p-me",
                "display_name": name,
                "hand_position": i + 1,
                "copy_number": 1,
            }
            for i, name in enumerate(hand)
        ],
        "game_mulligan_hands": [],
        "game_drawn_cards": [],
        "game_deck_cards": [
            {
                "participant_id": "p-me",
                "display_name": name,
                "deck_zone": "deck",
                "quantity": qty,
                "type_category": "Land" if name in ("Forest", "Island", "Plains") else None,
            }
            for name, qty in deck.items()
        ],
        "game_turns": [],
        "cards": [
            {
                "id": 1,
                "name": "Grizzly Bears",
                "arena_id": 101,
                "primary_type": "Creature",
                "power": "2",
                "toughness": "2",
                "color_identity": "G",
            },
            {
                "id": 2,
                "name": "Shock",
                "arena_id": 102,
                "primary_type": "Instant",
                "color_identity": "R",
            },
        ],
    }


def _stream(events, **kwargs):
    stream = reconstruct(_rows(events, **kwargs))
    assert validate_stream(stream) == []
    return stream


def _logged(stream, fragment):
    return next(e for e in stream["events"] if e["log"] and fragment in e["log"]["text"])


def _after(stream, event):
    return stream["events"][event["seq"] + 1 :]


T1 = ("turn", "Turn 1 - YOUR TURN")


# --- grammar pieces -------------------------------------------------------


def test_parse_bracket_shapes():
    assert parse_bracket("Llanowar Elves (Creature 1/1)") == (
        "Llanowar Elves",
        ["Creature"],
        "1",
        "1",
    )
    assert parse_bracket("Forest (Land)") == ("Forest", ["Land"], None, None)
    assert parse_bracket("Ox (Creature, Artifact 2/2)") == (
        "Ox",
        ["Creature", "Artifact"],
        "2",
        "2",
    )
    assert parse_bracket("Unstoppable Slasher (?/1)") == ("Unstoppable Slasher", [], "?", "1")
    assert parse_bracket("Unholy Annex // Ritual Chamber") == (
        "Unholy Annex // Ritual Chamber",
        [],
        None,
        None,
    )


def test_pair_stack_rows_matches_lifo_by_name_and_ability_within_a_turn():
    rows = _rows(
        [
            T1,
            ("cast", "[0:01] You: cast [Shock (Instant)]"),
            ("ability", "[0:01] You: [Forest] - tap: Add G."),
            (
                "stack_fail",
                "\t[0:01] Stack: [Forest] - tap: Add G. [left stack without resolving - inferred]",
            ),
            ("stack_resolve", "\t[0:02] Stack: [Shock (Instant)] [resolved]"),
            ("turn", "Turn 2 - OPPONENT'S TURN"),
            ("stack_resolve", "\t[0:03] Stack: [Shock (Instant)] [resolved]"),
        ]
    )["game_events"]
    assert pair_stack_rows(rows) == {3: 2, 4: 1}


def test_setup_seeds_hands_libraries_and_opening_moves():
    stream = _stream([T1], opponent_mulligans=1, player_mulligans=0)
    start = stream["events"][0]
    assert start["kind"] == "game_start"
    assert start["seats_hand_sizes"] == {"1": 6, "2": 7}
    assert start["library_sizes"] == {"1": 54, "2": 53}
    opening = [e for e in stream["events"] if e["kind"] == "move" and e["seq"] < 14]
    assert all(
        e["from"] == "library" and e["to"] == "hand" and e["reason"] == "draw" for e in opening
    )
    assert [e["card"] for e in opening if e["owner"] == OPPONENT] == [None] * 6
    player_cards = [e["card"] for e in opening if e["owner"] == PLAYER]
    assert "a101" in player_cards and "n:Forest" in player_cards
    mulligan = next(e for e in stream["events"] if e["kind"] == "mulligan")
    assert mulligan["seat"] == OPPONENT and (mulligan["from_size"], mulligan["to_size"]) == (7, 6)


def test_turn_rows_name_the_active_seat():
    stream = _stream([T1, ("turn", "Turn 2 - OPPONENT'S TURN")])
    turns = [e for e in stream["events"] if e["kind"] == "turn"]
    assert [(e["turn"], e["active_seat"]) for e in turns] == [(1, PLAYER), (2, OPPONENT)]
    assert [t["first_seq"] for t in stream["turns"]] == [e["seq"] for e in turns]


def test_land_play_moves_the_opening_hand_object():
    stream = _stream([T1, ("land", "[0:05] You: played [Forest (Land)]")])
    opening_forest = next(
        e for e in stream["events"] if e["kind"] == "move" and e["card"] == "n:Forest"
    )
    play = _logged(stream, "played [Forest")
    assert play["kind"] == "move" and play["reason"] == "play_land"
    assert (play["from"], play["to"], play["obj"]) == ("hand", "battlefield", opening_forest["obj"])


def test_land_play_reads_the_chosen_land_type():
    stream = _stream([T1, ("land", "[0:05] You: played [Multiversal Passage (Land)] as an Island")])
    play = _logged(stream, "played [Multiversal Passage")
    assert play["reason"] == "play_land" and play["to"] == "battlefield"
    assert play["chosen"] == "Island" and play["card"] == "n:Multiversal Passage"


def test_cast_without_printed_resolution_resolves_right_after_its_line():
    stream = _stream([T1, ("cast", "[0:05] You: cast [Grizzly Bears (Creature 2/2)]")])
    push = _logged(stream, "cast [Grizzly Bears")
    before = stream["events"][push["seq"] - 1]
    assert before["kind"] == "move" and (before["from"], before["to"]) == ("hand", "stack")
    assert before["reason"] == "cast"
    assert push["kind"] == "stack_push" and push["stack_kind"] == "spell"
    assert push["obj"] == before["obj"] and push["card"] == "a101"
    resolve, enter = _after(stream, push)[:2]
    assert resolve["kind"] == "stack_resolve" and resolve["stack_id"] == push["stack_id"]
    assert enter["kind"] == "move" and (enter["from"], enter["to"]) == ("stack", "battlefield")
    assert enter["reason"] == "resolve" and resolve["log"] is None


def test_instant_with_targets_resolves_to_graveyard_on_its_printed_line():
    stream = _stream(
        [
            T1,
            ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"),
            ("cast", "[0:02] You: cast [Shock (Instant)] -> [Grizzly Bears (2/2)], [you]"),
            (
                "ability",
                "[0:02] You: [Grizzly Bears] - Whenever this creature becomes the target of a spell, draw a card.",
            ),
            (
                "stack_resolve",
                "\t[0:02] Stack: [Grizzly Bears] - Whenever this creature becomes the target of a spell, draw a card. [resolved]",
            ),
            (
                "stack_resolve",
                "\t[0:03] Stack: [Shock (Instant)] -> [Grizzly Bears (2/2)] [resolved]",
            ),
        ]
    )
    bears = _logged(stream, "cast [Grizzly Bears")
    shock = _logged(stream, "cast [Shock")
    assert shock["targets"] == [bears["obj"]]
    assert _after(stream, shock)[0]["kind"] == "stack_push"  # not resolved early
    trigger = _logged(stream, "] - Whenever this creature becomes")
    assert trigger["stack_kind"] == "trigger" and trigger["obj"] == bears["obj"]
    resolved = _logged(stream, "Stack: [Shock (Instant)]")
    assert resolved["kind"] == "stack_resolve" and resolved["stack_id"] == shock["stack_id"]
    to_graveyard = _after(stream, resolved)[0]
    assert (to_graveyard["from"], to_graveyard["to"]) == ("stack", "graveyard")


def test_draws_named_hidden_and_opponent_hindsight_object():
    stream = _stream(
        [
            T1,
            ("draw", "[0:01] You: drew [Island]"),
            ("draw", "[0:02] You: drew a card"),
            ("turn", "Turn 2 - OPPONENT'S TURN"),
            ("draw", "[0:03] Opponent: drew a card"),
            ("cast", "[0:04] Opponent: cast [Lightning Bolt (Instant)] -> [you]"),
        ]
    )
    named = _logged(stream, "drew [Island]")
    hidden = _logged(stream, "You: drew a card")
    assert named["card"] == "n:Island" and hidden["card"] is None
    assert (named["from"], named["to"], named["reason"]) == ("library", "hand", "draw")
    opp_draw = _logged(stream, "Opponent: drew a card")
    assert opp_draw["card"] is None and opp_draw["owner"] == OPPONENT
    cast_move = stream["events"][_logged(stream, "cast [Lightning Bolt")["seq"] - 1]
    assert cast_move["from"] == "hand" and cast_move["card"] == "n:Lightning Bolt"


def test_mana_ability_fizzle_and_countered_spell():
    stream = _stream(
        [
            T1,
            ("turn", "Turn 2 - OPPONENT'S TURN"),
            ("ability", "[0:01] Opponent: [Island] - tap: Add U."),
            ("cast", "[0:01] Opponent: cast [Opt (Instant)]"),
            (
                "stack_fail",
                "\t[0:01] Stack: [Island] - tap: Add U. [left stack without resolving - inferred]",
            ),
            ("cast", "[0:02] You: cast [Shock (Instant)] -> [Opt]"),
            ("stack_resolve", "\t[0:03] Stack: [Shock (Instant)] -> [Opt] [resolved]"),
            ("stack_fail", "\t[0:03] Stack: [Opt (Instant)] [countered]"),
            ("counter", "[0:03] Opponent: [Opt] was countered"),
        ]
    )
    mana = _logged(stream, "] - tap: Add U.")
    assert mana["stack_kind"] == "activated"
    fizzle = _logged(stream, "[left stack without resolving")
    assert fizzle["kind"] == "stack_fizzle" and fizzle["stack_id"] == mana["stack_id"]
    # Abilities never move their source.
    assert all(e.get("obj") != mana["obj"] for e in _after(stream, fizzle) if e["kind"] == "move")
    opt = _logged(stream, "cast [Opt")
    countered = _logged(stream, "[Opt (Instant)] [countered]")
    assert countered["kind"] == "stack_countered" and countered["stack_id"] == opt["stack_id"]
    gone = _after(stream, countered)[0]
    assert (gone["from"], gone["to"], gone["reason"]) == ("stack", "graveyard", "counter")
    assert _logged(stream, "was countered")["kind"] == "note"  # already handled


def test_was_countered_row_closes_an_open_spell():
    stream = _stream(
        [
            T1,
            ("cast", "[0:01] You: cast [Shock (Instant)]"),
            ("stack_resolve", "\t[0:02] Stack: [Shock (Instant)] [resolved]"),
            ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"),
            ("counter", "[0:03] You: [Grizzly Bears] was countered"),
        ]
    )
    countered = _logged(stream, "was countered")
    assert countered["kind"] == "stack_countered"
    assert _after(stream, countered)[0]["to"] == "graveyard"


def test_identity_change_and_power_toughness():
    stream = _stream(
        [
            T1,
            ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"),
            ("ability", "[0:02] You: [Grizzly Bears] became [Grizzly Bears Rampaging] (4/4)"),
            ("zone", "[0:03] You: [Grizzly Bears Rampaging] was destroyed"),
        ]
    )
    identity = _logged(stream, "became")
    assert identity["kind"] == "identity" and identity["card"] == "n:Grizzly Bears Rampaging"
    pt = _after(stream, identity)[0]
    assert pt["kind"] == "pt" and (pt["power"], pt["toughness"]) == (4, 4)
    destroyed = _logged(stream, "was destroyed")
    assert destroyed["obj"] == identity["obj"] and destroyed["reason"] == "destroy"


@pytest.mark.parametrize(
    "text,source,dest,reason",
    [
        ("[0:02] You: [Grizzly Bears] was destroyed", "battlefield", "graveyard", "destroy"),
        ("[0:02] You: [Grizzly Bears] was exiled", "battlefield", "exile", "exile"),
        (
            "\t[0:02] You: [Grizzly Bears] was sacrificed as cost",
            "battlefield",
            "graveyard",
            "sacrifice",
        ),
        (
            "[0:02] You: [Grizzly Bears] was put into graveyard (lethal damage)",
            "battlefield",
            "graveyard",
            "sba",
        ),
        (
            "[0:02] You: [Grizzly Bears] was put into graveyard (0 toughness)",
            "battlefield",
            "graveyard",
            "sba",
        ),
        ("[0:02] You: returned [Grizzly Bears] to hand", "battlefield", "hand", "bounce"),
        (
            "[0:02] Opponent: [Unsummon] returned [Grizzly Bears] to your hand",
            "battlefield",
            "hand",
            "bounce",
        ),
        ("[0:02] You: [Shock] was discarded", "hand", "graveyard", "discard"),
        ("[0:02] You: milled [Island]", "library", "graveyard", "mill"),
        # Lands come from the library (fetch/ramp), other cards from the hand.
        ("[0:02] You: put [Forest] onto battlefield", "library", "battlefield", "put"),
        ("[0:02] You: put [Shock] onto battlefield", "hand", "battlefield", "put"),
        ("[0:02] You: put [Island] onto battlefield", "library", "battlefield", "put"),
        ("[0:02] You: [Impulse] put [Island] into your hand", "library", "hand", "put"),
    ],
)
def test_zone_lines(text, source, dest, reason):
    stream = _stream(
        [T1, ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"), ("zone", text)],
        hand=("Forest", "Grizzly Bears", "Shock"),
    )
    event = _logged(stream, text.strip()[7:])
    assert event["kind"] == "move"
    assert (event["from"], event["to"], event["reason"]) == (source, dest, reason)
    assert event["owner"] == PLAYER


def test_exiled_as_cost_comes_from_the_graveyard():
    stream = _stream(
        [
            T1,
            ("zone", "[0:01] You: [Shock] was discarded"),
            ("zone", "\t[0:02] You: [Shock] was exiled as cost"),
        ]
    )
    exiled = _logged(stream, "exiled as cost")
    assert (exiled["from"], exiled["to"]) == ("graveyard", "exile")


def test_attacks_create_inferred_tokens_and_distinct_same_name_attackers():
    stream = _stream(
        [
            T1,
            ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"),
            ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"),
            ("turn", "Turn 3 - YOUR TURN"),
            ("attack", "[0:05] You attacking [opponent] with [Grizzly Bears (2/2)]"),
            ("attack", "[0:05] You attacking [opponent] with [Grizzly Bears (3/3)]"),
            ("attack", "[0:05] You attacking [opponent] with [Rabbit (1/1)]"),
        ],
        hand=("Grizzly Bears", "Grizzly Bears"),
    )
    attacks = [e for e in stream["events"] if e["kind"] == "attack"]
    assert len({a["objs"][0] for a in attacks}) == 3
    assert all(a["seat"] == PLAYER and a["target_seat"] == OPPONENT for a in attacks)
    pumped = stream["events"][attacks[1]["seq"] - 1]
    assert pumped["kind"] == "pt" and (pumped["power"], pumped["toughness"]) == (3, 3)
    token = stream["events"][attacks[2]["seq"] - 1]
    assert token["kind"] == "move" and token["reason"] == "token_create"
    assert (token["from"], token["inferred"]) == ("limbo", True)
    assert stream["cards"][token["card"]]["is_token"] is True
    assert stream["cards"][token["card"]]["primary_type"] == "Creature"


def test_combat_damage_infers_blocks_and_damage():
    stream = _stream(
        [
            T1,
            ("cast", "[0:01] You: cast [Grizzly Bears (Creature 2/2)]"),
            ("turn", "Turn 2 - OPPONENT'S TURN"),
            ("land", "[0:02] Opponent: played [Mountain (Land)]"),
            ("turn", "Turn 3 - YOUR TURN"),
            ("attack", "[0:05] You attacking [opponent] with [Grizzly Bears (2/2)]"),
            (
                "combat_damage",
                "\t[0:06] Combat: [Grizzly Bears] dealt 2 damage to [Goblin (1/1)] (opponent's)",
            ),
            ("combat_damage", "   [Goblin (1/1)] → [Grizzly Bears (2/2)] (your): 1 damage"),
            ("damage", "[0:06] [Grizzly Bears] (your) took 1 damage"),
            ("zone", "[0:06] Opponent: [Goblin] was put into graveyard (lethal damage)"),
        ]
    )
    block = next(e for e in stream["events"] if e["kind"] == "block")
    attack = next(e for e in stream["events"] if e["kind"] == "attack")
    assert block["seat"] == OPPONENT
    assert block["pairs"][0]["attacker"] == attack["objs"][0]
    dealt = _logged(stream, "dealt 2 damage")
    assert dealt["kind"] == "damage" and dealt["combat"] and dealt["amount"] == 2
    assert (
        dealt["source"] == attack["objs"][0] and dealt["target_obj"] == block["pairs"][0]["blocker"]
    )
    arrow = _logged(stream, "→ [Grizzly Bears")
    assert arrow["source"] == block["pairs"][0]["blocker"] and arrow["amount"] == 1
    took = _logged(stream, "(your) took 1 damage")
    assert took["target_obj"] == attack["objs"][0] and not took["combat"]
    goblin_dies = _logged(stream, "[Goblin] was put into graveyard")
    assert goblin_dies["obj"] == block["pairs"][0]["blocker"]
    cease = _after(stream, goblin_dies)[0]
    assert (cease["from"], cease["to"], cease["reason"]) == ("graveyard", "limbo", "token_cease")
    assert len([e for e in stream["events"] if e["kind"] == "block"]) == 1


def test_life_rows_carry_new_totals_and_final_life_matches_participants():
    stream = _stream(
        [
            T1,
            ("life_loss", "[0:01] Opponent: lost 3 life (now 17)", 1, (20, 17)),
            ("life_gain", "[0:02] You: gained 2 life (now 22)", 1, (22, 17)),
        ],
        ending=(22, 15),
    )
    lost = _logged(stream, "lost 3 life")
    assert (lost["kind"], lost["seat"], lost["life"], lost["delta"]) == ("life", OPPONENT, 17, -3)
    gained = _logged(stream, "gained 2 life")
    assert (gained["seat"], gained["life"], gained["delta"]) == (PLAYER, 22, 2)
    final = {}
    for event in stream["events"]:
        if event["kind"] == "life":
            final[event["seat"]] = event["life"]
    assert final == {PLAYER: 22, OPPONENT: 15}
    assert stream["events"][-1]["kind"] == "game_end"
    assert stream["events"][-1]["winner_seat"] == PLAYER


def test_scry_resolves_player_names_and_hides_opponent_cards():
    stream = _stream(
        [
            T1,
            ("scry", "[0:01] You: scried 2 — kept [Island] on top, bottomed [Shock]"),
            ("draw", "[0:02] You: drew [Island]"),
            ("scry", "[0:03] Opponent: scried 1 — bottomed it"),
        ]
    )
    scry = _logged(stream, "You: scried 2")
    assert scry["looked"] == 2 and len(scry["top"]) == 1 and len(scry["bottom"]) == 1
    assert _logged(stream, "drew [Island]")["obj"] == scry["top"][0]
    opp = _logged(stream, "Opponent: scried")
    assert (opp["seat"], opp["top"], opp["bottom"], opp["looked"]) == (OPPONENT, [], [], 1)


def test_unknown_lines_and_card_numbers():
    stream = _stream(
        [
            T1,
            ("ability", "[0:01] Opponent: [The Ooze] tapped [The Ooze]"),
            ("cast", "[0:02] Opponent: cast [Card #190883 (Sorcery)]"),
            ("turn", "Session: W:1 L:0 | Games:1 | WR:100.0% | Runtime:4:45"),
        ]
    )
    assert _logged(stream, "tapped [The Ooze]")["kind"] == "note"
    assert _logged(stream, "Session:")["kind"] == "note"
    cast = _logged(stream, "Card #190883")
    assert cast["card"] == "unknown" and stream["cards"]["unknown"]["name"] == "Unknown card"


def test_opponent_hand_never_goes_negative():
    plays = [("land", f"[0:{i:02d}] Opponent: played [Mountain (Land)]") for i in range(10)]
    stream = _stream([("turn", "Turn 1 - OPPONENT'S TURN")] + plays)
    moves = [e for e in stream["events"] if e["kind"] == "move" and e["reason"] == "play_land"]
    assert sum(1 for e in moves if e["from"] == "hand") == 7
    assert all(e["inferred"] for e in moves if e["from"] == "limbo")


def test_brawl_commanders_start_in_the_command_zone():
    stream = _stream(
        [
            T1,
            ("cast", "[0:01] You: cast [Belladonna Took (Creature 2/2)]"),
        ],
        commanders=[("p-me", "Belladonna Took"), ("p-opp", "Squirrel Girl")],
        fmt="Play_Brawl_Historic",
        deck_size=100,
        opponent_deck_size=99,
        deck={"Plains": 99},
        hand=("Plains",) * 7,
    )
    start = stream["events"][0]
    assert start["library_sizes"] == {"1": 92, "2": 92}
    setup = [e for e in stream["events"] if e["kind"] == "move" and e["to"] == "command"]
    assert {e["owner"] for e in setup} == {PLAYER, OPPONENT}
    cast_move = stream["events"][_logged(stream, "cast [Belladonna")["seq"] - 1]
    assert cast_move["from"] == "command"
    assert stream["seats"][str(PLAYER)]["commanders"] == ["Belladonna Took"]


def test_reconstruction_is_deterministic_and_linear():
    rows = _rows(
        [T1]
        + [
            row
            for turn in range(2, 400)
            for row in (
                ("turn", f"Turn {turn} - " + ("YOUR TURN" if turn % 2 else "OPPONENT'S TURN")),
                ("draw", f"[{turn}:00] {'You' if turn % 2 else 'Opponent'}: drew a card"),
                (
                    "land",
                    f"[{turn}:01] {'You' if turn % 2 else 'Opponent'}: played [Forest (Land)]",
                ),
                (
                    "attack",
                    f"[{turn}:02] {'You' if turn % 2 else 'Opponent'} attacking "
                    f"[{'opponent' if turn % 2 else 'you'}] with [Wolf (2/2)]",
                ),
            )
        ],
        deck_size=2000,
        opponent_deck_size=2000,
        deck={"Forest": 2000},
        hand=(),
    )
    started = time.perf_counter()
    first = reconstruct(copy.deepcopy(rows))
    elapsed = time.perf_counter() - started
    assert first == reconstruct(copy.deepcopy(rows))
    assert validate_stream(first) == []
    assert elapsed < 2.0  # ~1,600 rows; quadratic behaviour would blow this up


# --- whole fixtures exported from a real database ---------------------------


def _fixture(name):
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_streams_hold_every_invariant(name):
    rows = _fixture(name)
    stream = reconstruct(rows)
    assert stream["fidelity"] == "reconstructed" and stream["limitations"]
    assert validate_stream(stream) == []
    events = stream["events"]
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert all(a["t"] <= b["t"] for a, b in zip(events, events[1:]))
    turn_rows = [
        r
        for r in rows["game_events"]
        if r["event_type"] == "turn" and r["text"].startswith("Turn ")
    ]
    assert len(stream["turns"]) == len(turn_rows)
    # Every printed row is in the action log exactly once.
    assert sum(1 for e in events if e["log"]) == len(rows["game_events"])
    final = {}
    for event in events:
        if event["kind"] == "life":
            final[event["seat"]] = event["life"]
    for participant in rows["participants"]:
        if participant.get("ending_life") is not None:
            seat = participant["seat_id"]
            assert final.get(seat, participant["starting_life"]) == participant["ending_life"]
    # Hand and library counts (validate_stream also checks) and the stack
    # never keeps an item open at game end.
    pushed = {e["stack_id"] for e in events if e["kind"] == "stack_push"}
    closed = [
        e["stack_id"]
        for e in events
        if e["kind"] in ("stack_resolve", "stack_fizzle", "stack_countered")
    ]
    assert sorted(closed) == sorted(pushed)
    assert stream == reconstruct(_fixture(name))


def test_short_game_fixture_infers_treefolk_tokens_and_board():
    stream = reconstruct(_fixture("short_game"))
    tokens = [e for e in stream["events"] if e["kind"] == "move" and e["reason"] == "token_create"]
    assert tokens and all(stream["cards"][e["card"]]["is_token"] for e in tokens)
    battlefield = {}
    for event in stream["events"]:
        if event["kind"] == "move":
            battlefield[event["obj"]] = event["to"]
    lands = [obj for obj, zone in battlefield.items() if zone == "battlefield"]
    assert len(lands) >= 8


def test_brawl_fixture_uses_command_zone_tokens_and_blocks():
    stream = reconstruct(_fixture("brawl_tokens_commanders"))
    kinds = {e["kind"] for e in stream["events"]}
    assert {"block", "damage", "attack"} <= kinds
    assert any(e["kind"] == "move" and e["from"] == "command" for e in stream["events"])
    assert any(e["kind"] == "move" and e["reason"] == "token_create" for e in stream["events"])
    assert stream["seats"]["2"]["commanders"] and stream["seats"]["1"]["commanders"]
    assert stream["game"]["format"] == "Historic Brawl"


def test_mulligan_counter_fixture():
    stream = reconstruct(_fixture("mulligan_counter_unknown"))
    kinds = [e["kind"] for e in stream["events"]]
    assert "mulligan" in kinds and "stack_countered" in kinds and "identity" in kinds
    mulligan = next(e for e in stream["events"] if e["kind"] == "mulligan")
    assert mulligan["seat"] == stream["player_seat"] and mulligan["to_size"] == 6
    assert any("Card #" in (e["log"] or {}).get("text", "") for e in stream["events"])
    assert stream["seats"][str(stream["player_seat"])]["name"] == "You"


def test_events_carry_their_row_id_and_silent_rows_are_ignored():
    rows = _rows([T1, ("land", "[0:01] You: played [Forest (Land)]")])
    silent = dict(rows["game_events"][-1], id=99, visible=0, event_type=None, text="untap 5")
    rows["game_events"].append(silent)
    stream = reconstruct(rows)
    assert validate_stream(stream) == []
    assert all("untap 5" not in ((e["log"] or {}).get("text") or "") for e in stream["events"])
    assert 99 not in {e["row_id"] for e in stream["events"]}
    assert stream["events"][0]["row_id"] is None  # game_start is synthesized
    assert _logged(stream, "played [Forest")["row_id"] == 2
    assert stream["events"][-1]["kind"] == "game_end" and stream["events"][-1]["row_id"] is None


# --- Arena card facts: flashback, transform, plot -------------------------

ESPER_FACTS = {
    "esper origins": {"keywords": ["flashback"], "back_face": False, "front": None},
    "summon: esper maduin": {"keywords": [], "back_face": True, "front": "Esper Origins"},
    "slickshot show-off": {"keywords": ["plot"], "back_face": False, "front": None},
}


def _with_facts(events, facts=ESPER_FACTS, **kwargs):
    rows = _rows(events, **kwargs)
    rows["card_facts"] = facts
    stream = reconstruct(rows)
    assert validate_stream(stream) == []
    return stream


ESPER_GAME = [
    T1,
    ("turn", "Turn 2 - OPPONENT'S TURN"),
    ("draw", "[0:05] Opponent: drew a card"),
    ("cast", "[0:06] Opponent: cast [Esper Origins (Sorcery)]"),
    ("life_gain", "[0:08] Opponent: gained 2 life (now 22)", None, (20, 22)),
    ("turn", "Turn 3 - YOUR TURN"),
    ("turn", "Turn 4 - OPPONENT'S TURN"),
    ("draw", "[0:20] Opponent: drew a card"),
    ("cast", "[0:21] Opponent: cast [Esper Origins (Sorcery)]"),
    ("life_gain", "[0:24] Opponent: gained 2 life (now 24)", None, (20, 24)),
    ("zone", "[0:24] Opponent: [Esper Origins] was exiled"),
    ("zone", "[0:24] Opponent: put [Summon: Esper Maduin] onto battlefield"),
    ("turn", "Turn 5 - YOUR TURN"),
    ("turn", "Turn 6 - OPPONENT'S TURN"),
    ("attack", "[0:40] Opponent attacking [you] with [Summon: Esper Maduin (4/4)]"),
]


def _moves(stream, obj):
    return [e for e in stream["events"] if e["kind"] == "move" and e["obj"] == obj]


def test_flashback_casts_from_the_graveyard_and_the_back_face_is_the_same_card():
    stream = _with_facts(ESPER_GAME)
    casts = [e for e in stream["events"] if e["kind"] == "move" and e["reason"] == "cast"]
    first, second = casts[-2:]
    assert first["from"] == "hand"
    assert second["obj"] == first["obj"]
    assert second["from"] == "graveyard"
    esper = first["obj"]
    put = _logged(stream, "put [Summon: Esper Maduin] onto battlefield")
    assert (put["obj"], put["from"], put["to"], put["inferred"]) == (
        esper,
        "exile",
        "battlefield",
        False,
    )
    identity = next(e for e in stream["events"] if e["kind"] == "identity" and e["obj"] == esper)
    card = stream["cards"][identity["card"]]
    assert card["name"] == "Summon: Esper Maduin"
    assert card["is_token"] is False
    assert _logged(stream, "attacking [you]")["objs"] == [esper]
    assert not any(c["is_token"] for c in stream["cards"].values())


def test_without_card_facts_the_old_inference_still_runs():
    rows = _rows(ESPER_GAME)
    stream = reconstruct(rows)
    assert validate_stream(stream) == []
    put = _logged(stream, "put [Summon: Esper Maduin] onto battlefield")
    assert put["inferred"] is True


def test_plotted_card_leaves_the_hand_and_is_cast_from_exile():
    stream = _with_facts(
        [
            T1,
            ("turn", "Turn 2 - OPPONENT'S TURN"),
            ("draw", "[0:05] Opponent: drew a card"),
            ("zone", "[0:06] Opponent: [Slickshot Show-Off] was exiled"),
            ("turn", "Turn 3 - YOUR TURN"),
            ("turn", "Turn 4 - OPPONENT'S TURN"),
            ("cast", "[0:21] Opponent: cast [Slickshot Show-Off (Creature 1/2)]"),
        ]
    )
    plotted = _logged(stream, "[Slickshot Show-Off] was exiled")
    assert (plotted["from"], plotted["to"], plotted["inferred"]) == ("hand", "exile", False)
    cast = _logged(stream, "cast [Slickshot Show-Off")
    move = next(e for e in _moves(stream, plotted["obj"]) if e["reason"] == "cast")
    assert move["from"] == "exile"
    assert cast is not None


KNIGHTS_FACTS = {
    "summon: knights of round": {
        "keywords": [],
        "back_face": False,
        "front": None,
        "type_line": "Enchantment Creature",
        "power": "3",
        "toughness": "3",
    },
    "yuna, hope of spira": {
        "keywords": [],
        "back_face": False,
        "front": None,
        "type_line": "Creature",
        "power": "3",
        "toughness": "5",
    },
}

YUNA_TRIGGER = (
    "ability",
    "[0:10] Opponent: [Yuna, Hope of Spira] - At the beginning of your end step, return up to"
    " one target enchantment card from your graveyard to the battlefield with a finality"
    " counter on it. -> [Summon: Knights of Round (3/3)]",
)
KNIGHT_TOKENS = (
    "ability",
    "[0:10] Opponent: [Summon: Knights of Round] - Create three 2/2 white Knight creature tokens.",
)


def _knights_game(return_line):
    return _with_facts(
        [
            T1,
            ("turn", "Turn 2 - OPPONENT'S TURN"),
            ("cast", "[0:05] Opponent: cast [Yuna, Hope of Spira (Creature 3/5)]"),
            KNIGHT_TOKENS,
            YUNA_TRIGGER,
            ("zone", return_line),
            ("turn", "Turn 3 - YOUR TURN"),
            ("damage", "[0:20] [Summon: Knights of Round] (opponent's) took 6 damage"),
            ("damage", "[0:20] [Knight] (opponent's) took 6 damage"),
            ("damage", "[0:20] [Knight] (opponent's) took 6 damage"),
            ("damage", "[0:20] [Knight] (opponent's) took 6 damage"),
            ("zone", "[0:21] Opponent: [Knight] was put into graveyard (lethal damage)"),
        ],
        facts=KNIGHTS_FACTS,
    )


@pytest.mark.parametrize(
    "return_line",
    [
        # Older tracker text printed the recursion as a return to hand.
        "[0:10] Opponent: returned [Summon: Knights of Round] to hand",
        "[0:10] Opponent: [Yuna, Hope of Spira] returned [Summon: Knights of Round] to battlefield",
    ],
)
def test_returned_enchantment_creature_is_a_real_card_on_the_battlefield(return_line):
    stream = _knights_game(return_line)
    back = _logged(stream, "[Summon: Knights of Round] to")
    assert (back["kind"], back["to"], back["inferred"]) == ("move", "battlefield", False)
    card = stream["cards"][back["card"]]
    assert card["is_token"] is False
    assert (card["type_line"], card["primary_type"], card["power"]) == (
        "Enchantment Creature",
        "Creature",
        "3",
    )
    damaged = _logged(stream, "[Summon: Knights of Round] (opponent's) took 6 damage")
    assert damaged["target_obj"] == back["obj"]


def test_create_tokens_ability_makes_each_token_and_damage_spreads_over_them():
    stream = _knights_game("[0:10] Opponent: returned [Summon: Knights of Round] to hand")
    created = [
        e
        for e in stream["events"]
        if e["kind"] == "move"
        and e["reason"] == "token_create"
        and stream["cards"][e["card"]]["name"] == "Knight"
    ]
    assert len(created) == 3
    knight = stream["cards"][created[0]["card"]]
    assert (knight["is_token"], knight["power"], knight["toughness"]) == (True, "2", "2")
    hits = [
        e["target_obj"]
        for e in stream["events"]
        if e["kind"] == "damage" and e["log"] and "[Knight]" in e["log"]["text"]
    ]
    assert sorted(hits) == sorted(e["obj"] for e in created)
    died = _logged(stream, "[Knight] was put into graveyard")
    assert died["obj"] in hits


def test_conditional_and_counted_token_sentences_are_not_created():
    from mtga_tracker.replay_reconstruct_grammar import created_tokens

    text = (
        "Create a Treasure token. Then if you control four or more Treasures, sacrifice this"
        " Saga. If you do, create a 6/6 red Dragon creature token with flying."
    )
    assert created_tokens(text) == [("Treasure", 1, None, None, [])]
    assert created_tokens("Create a 1/1 white Soldier creature token for each creature.") == []
    assert created_tokens("Create a token that's a copy of target creature.") == []
