"""Replay stream for games captured with structured rows, plus serving glue.

``build_recorded`` turns the ``game_events`` rows of a ``replay_version = 1``
game (``docs/REPLAY_FORMAT.md`` section 1) into the stream of section 2.
``load_replay_rows`` reads everything one game needs in a handful of
queries, ``build_stream`` picks the builder or the text reconstructor, and
``replay_for_game`` is what ``GET /api/replay`` and ``replay_dump`` call.

The builder never queries per event. It is defensive about capture gaps so
the reducer's guarantees hold even when a row is missing: an object first
seen outside a creating zone is introduced from ``limbo`` (``inferred``), a
spell's ``stack_push`` gets its ``hand → stack`` move if the capture did not
write one, and stack items whose resolution was never printed are closed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from .replay_sickness import (
    SICKNESS_CAPTURE_VERSION,
    SICKNESS_ESTIMATE_LIMITATION,
    card_fact,
    estimate_summoning_sickness,
)
from .replay_stream import (
    CREATING_ZONES,
    FIDELITY_RECORDED,
    MOVE_REASONS,
    STACK_CLOSE_KINDS,
    STACK_KINDS,
    ZONES,
    CardRegistry,
    EventLog,
    ReplayUnavailable,
    attach_log,
    build_turns,
    finalize_logs,
    is_unknown_card_name,
    primary_type_from_text,
    seat_colors,
    stream_header,
)

# --- loading --------------------------------------------------------------

_PER_GAME_TABLES = (
    ("game_opening_hand_cards", "hand_position, copy_number, id"),
    ("game_mulligan_hands", "hand_number, hand_position, id"),
    ("game_drawn_cards", "participant_id, draw_position"),
    ("game_deck_cards", "participant_id, deck_zone, id"),
    ("game_turns", "turn_number, id"),
    ("game_library_events", "id"),
)


def _rows(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _chunked(values: List[Any], size: int = 500) -> Iterable[List[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def load_replay_rows(conn: sqlite3.Connection, game_id: str) -> Optional[Dict[str, Any]]:
    """Every row one game's replay needs, keyed by table name; None if unknown.

    The same shape is written by ``scripts/export_replay_fixture.py``, so
    tests feed fixtures straight into ``build_stream``.
    """
    games = _rows(conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)))
    if not games:
        return None
    rows: Dict[str, Any] = {"games": games}
    rows["matches"] = _rows(
        conn.execute("SELECT * FROM matches WHERE id = ?", (games[0].get("match_id"),))
    )
    rows["participants"] = _rows(
        conn.execute("SELECT * FROM participants WHERE game_id = ? ORDER BY role DESC", (game_id,))
    )
    participant_ids = [row["id"] for row in rows["participants"]]
    rows["participant_commanders"] = []
    if participant_ids and _table_exists(conn, "participant_commanders"):
        marks = ",".join("?" * len(participant_ids))
        rows["participant_commanders"] = _rows(
            conn.execute(
                f"SELECT * FROM participant_commanders WHERE participant_id IN ({marks}) "
                "ORDER BY participant_id, card_name",
                participant_ids,
            )
        )
    rows["game_events"] = _rows(
        conn.execute(
            "SELECT * FROM game_events WHERE game_id = ? ORDER BY event_time, id", (game_id,)
        )
    )
    for table, order in _PER_GAME_TABLES:
        rows[table] = (
            _rows(
                conn.execute(
                    f"SELECT * FROM {table} WHERE game_id = ? ORDER BY {order}", (game_id,)
                )
            )
            if _table_exists(conn, table)
            else []
        )
    rows["cards"] = _load_cards(conn, rows)
    return rows


def _load_cards(conn: sqlite3.Connection, rows: Dict[str, Any]) -> List[Dict[str, Any]]:
    """``cards`` rows for every name, id or Arena id the game mentions."""
    from .replay_reconstruct_grammar import _bracket_names

    names: Set[str] = set()
    card_ids: Set[int] = set()
    arena_ids: Set[int] = set()
    for table in ("game_opening_hand_cards", "game_mulligan_hands", "game_drawn_cards"):
        for row in rows.get(table) or []:
            if row.get("display_name"):
                names.add(str(row["display_name"]))
            if row.get("card_id"):
                card_ids.add(int(row["card_id"]))
    for row in rows.get("game_deck_cards") or []:
        if row.get("display_name"):
            names.add(str(row["display_name"]))
        if row.get("arena_id"):
            arena_ids.add(int(row["arena_id"]))
    for row in rows.get("participant_commanders") or []:
        names.add(str(row.get("card_name") or ""))
    for row in rows.get("game_events") or []:
        names.update(_bracket_names(str(row.get("text") or "")))
        if row.get("arena_id"):
            arena_ids.add(int(row["arena_id"]))
        payload = _payload(row)
        if payload.get("name"):
            names.add(str(payload["name"]))
    names.discard("")
    found: Dict[int, Dict[str, Any]] = {}
    for column, values in (
        ("name", sorted(names)),
        ("id", sorted(card_ids)),
        ("arena_id", sorted(arena_ids)),
    ):
        for chunk in _chunked(list(values)):
            marks = ",".join("?" * len(chunk))
            for row in _rows(
                conn.execute(f"SELECT * FROM cards WHERE {column} IN ({marks})", chunk)
            ):
                found[int(row["id"])] = row
    return [found[key] for key in sorted(found)]


# --- recorded builder -----------------------------------------------------


def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("payload_json")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _obj(value: Any) -> Optional[str]:
    number = _int(value)
    return str(number) if number is not None else None


def _zone(value: Any) -> str:
    zone = str(value or "").strip().lower()
    return zone if zone in ZONES else "limbo"


#: Silent state rows of a turn's beginning; moves (opening hands) never move.
_HOISTABLE_KINDS = ("untap", "tap", "unsick", "sick", "phase", "pt", "counter")


def _hoist_turn_headers(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Move each ``turn`` row before the silent state rows of that same turn.

    The console prints a turn header lazily, at the turn's first printed
    action, so the untap step's silent rows (stamped with the new turn
    number) precede it. In the stream they belong to the new turn.
    """
    out: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("event_subtype") == "turn" and row.get("turn_number") is not None:
            turn = row.get("turn_number")
            index = len(out)
            while (
                index > 0
                and out[index - 1].get("visible", 1) in (0, "0", False)
                and out[index - 1].get("turn_number") == turn
                and out[index - 1].get("event_subtype") in _HOISTABLE_KINDS
            ):
                index -= 1
            out.insert(index, row)
        else:
            out.append(row)
    return out


def _row_objects(row: Dict[str, Any]) -> Set[str]:
    """Every object id a row names."""
    payload = _payload(row)
    values = [
        row.get("object_id"),
        row.get("target_object_id"),
        payload.get("target_object_id"),
        payload.get("source_object_id"),
        *(payload.get("object_ids") or []),
    ]
    return {obj for obj in (_obj(value) for value in values) if obj is not None}


def _hoist_token_creations(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Move each token's creation before the first row of its turn that names it.

    Arena can create tokens and declare them attackers in one message (Mobilize),
    and the printed attack lines are written before the silent creation rows.
    Read in order, the attackers would appear from nowhere as inferred cards.
    """
    out = list(rows)
    creations = [
        row
        for row in rows
        if row.get("event_subtype") == "move" and _payload(row).get("reason") == "token_create"
    ]
    for row in creations:
        obj = _obj(row.get("object_id"))
        if obj is None:
            continue
        at = next(index for index, other in enumerate(out) if other is row)
        first = next((index for index in range(at) if obj in _row_objects(out[index])), None)
        if first is None or out[first].get("turn_number") != row.get("turn_number"):
            continue
        out.insert(first, out.pop(at))
    return out


def _hoist_battlefield_entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Move a permanent's entry before its own rows logged at that same moment.

    Arena can put a card onto the battlefield and its enters triggers on the stack
    in one message, and the trigger lines can print before the move (Repurposing
    Bay fetching Pinnacle Starcage). Read in order, the card would appear from
    nowhere as an inferred card. Only rows the card itself is the source of move
    it, and never past a resolution or an earlier move of the card.
    """
    out = list(rows)
    entries = [
        row
        for row in rows
        if row.get("event_subtype") == "move"
        and row.get("zone_to") == "battlefield"
        and row.get("zone_from") not in (None, "", "battlefield", "stack")
    ]
    for row in entries:
        obj = _obj(row.get("object_id"))
        if obj is None:
            continue
        at = next(index for index, other in enumerate(out) if other is row)
        first = None
        for index in range(at - 1, -1, -1):
            other = out[index]
            if other.get("event_time") != row.get("event_time"):
                break
            kind = other.get("event_subtype")
            if kind in STACK_CLOSE_KINDS or (
                kind == "move" and _obj(other.get("object_id")) == obj
            ):
                break
            if kind != "move" and _obj(other.get("object_id")) == obj:
                first = index
        if first is not None:
            out.insert(first, out.pop(at))
    return out


_ATTACKER_NAME = re.compile(r"with \[(.+?)(?: \([^()]*\))?\]\s*$")


def _link_renamed_attackers(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Point an attack at the permanent it really is when Arena renamed it.

    A creature put onto the battlefield attacking (ninjutsu: Kaito, Bane of
    Nightmares) gets a new instance id, and the attack line can be written,
    under that new id, before the move that puts the card there. An attacker
    id that no other row names is linked to the next card of the same name
    entering the battlefield that turn, and that move is moved ahead of the
    attack, so the card is there when it attacks.
    """
    out = list(rows)
    seen: Dict[str, int] = {}
    for row in rows:
        for obj in _row_objects(row):
            seen[obj] = seen.get(obj, 0) + 1
    for row in [r for r in rows if r.get("event_subtype") == "attack"]:
        payload = _payload(row)
        ids = [_obj(v) for v in payload.get("object_ids") or [row.get("object_id")]]
        lonely = [obj for obj in ids if obj is not None and seen.get(obj, 0) == 1]
        match = _ATTACKER_NAME.search(str(row.get("text") or ""))
        if len(lonely) != 1 or len(ids) != 1 or not match:
            continue
        at = next(index for index, other in enumerate(out) if other is row)
        entry = next(
            (
                other
                for other in out[at + 1 :]
                if other.get("turn_number") == row.get("turn_number")
                and other.get("event_subtype") == "move"
                and _zone(other.get("zone_to")) == "battlefield"
                and _payload(other).get("name") == match.group(1)
            ),
            None,
        )
        real = _obj(entry.get("object_id")) if entry else None
        if entry is None or real is None:
            continue
        fixed = dict(row)
        fixed["object_id"] = int(real)
        fixed["payload_json"] = json.dumps({**payload, "object_ids": [int(real)]})
        out[at] = fixed
        out.remove(entry)
        out.insert(at, entry)
    return out


def _drop_echoed_activations(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop a trigger line that only echoes the activated ability right after it.

    Arena can announce an ability activated from the hand (ninjutsu) twice:
    once read as a trigger, then as the activated ability itself, with the same
    source and text. The trigger never resolves on its own, so it is dropped.
    """
    closed = {
        str(_payload(row).get("stack_id"))
        for row in rows
        if row.get("event_subtype") in STACK_CLOSE_KINDS and _payload(row).get("stack_id")
    }
    drop = set()
    for index, row in enumerate(rows):
        payload = _payload(row)
        if row.get("event_subtype") != "stack_push" or payload.get("stack_kind") != "trigger":
            continue
        if str(payload.get("stack_id")) in closed:
            continue
        for other in rows[index + 1 : index + 5]:
            later = _payload(other)
            if (
                other.get("event_subtype") == "stack_push"
                and later.get("stack_kind") == "activated"
                and other.get("object_id") == row.get("object_id")
                and later.get("text") == payload.get("text")
            ):
                drop.add(id(row))
                break
    return [row for row in rows if id(row) not in drop]


def _drop_repeated_moves(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop a silent move that repeats the card's previous move exactly.

    Arena can send a land play's zone transfer again in a later message, and
    capture records it a second time. Replayed, the land would move from the
    battlefield to the battlefield.
    """
    last: Dict[str, Tuple[Any, Any, Any]] = {}
    out = []
    for row in rows:
        obj = _obj(row.get("object_id"))
        if row.get("event_subtype") == "move" and obj is not None:
            move = (row.get("zone_from"), row.get("zone_to"), _payload(row).get("reason"))
            if row.get("visible", 1) in (0, "0", False) and last.get(obj) == move:
                continue
            last[obj] = move
        out.append(row)
    return out


_DRAW_ACTOR = re.compile(r"^(\[[^\]]*\]\s*)?(You|Opponent)(: drew\b)")


def _hand_seat(row: Dict[str, Any]) -> Optional[int]:
    """The seat whose hand a move row's card is in: its owner, else its controller."""
    return _int(_payload(row).get("owner")) or _int(row.get("controller_seat"))


def _reassign_misread_draws(rows: List[Dict[str, Any]], player_seat: int) -> List[Dict[str, Any]]:
    """Give a draw back to the seat whose hand the card actually went to.

    Arena can reuse an instance id it never deleted (an ability whose activation
    was undone) for the next card drawn. Trackers before 0.7.5 kept the old
    object's seat for it, so an opponent's hidden draw was saved as yours. A card
    only ever leaves its owner's hand, so when the drawn card's next move takes it
    out of the other seat's hand, the draw was that seat's.
    """
    out = list(rows)
    for index, row in enumerate(out):
        obj = _obj(row.get("object_id"))
        if (
            obj is None
            or row.get("event_subtype") != "move"
            or _zone(row.get("zone_from")) != "library"
            or _zone(row.get("zone_to")) != "hand"
        ):
            continue
        drawn_by = _hand_seat(row) or _int(row.get("seat_id"))
        later = next(
            (
                other
                for other in out[index + 1 :]
                if other.get("event_subtype") == "move" and _obj(other.get("object_id")) == obj
            ),
            None,
        )
        if later is None or _zone(later.get("zone_from")) != "hand":
            continue
        holder = _hand_seat(later)
        if holder is None or drawn_by is None or holder == drawn_by:
            continue
        if "owner" not in _payload(later) and _int(later.get("seat_id")) not in (None, holder):
            # Seat and controller disagree with no owner stated: not sure whose hand.
            continue
        fixed = dict(row)
        fixed["seat_id"] = holder
        fixed["controller_seat"] = holder
        fixed["actor_role"] = "player" if holder == player_seat else "opponent"
        # The id's old object named some other card; the draw itself was hidden.
        fixed["arena_id"] = None
        payload = _payload(row)
        if "owner" in payload:
            fixed["payload_json"] = json.dumps({**payload, "owner": holder})
        if isinstance(row.get("text"), str):
            label = "You" if holder == player_seat else "Opponent"
            fixed["text"] = _DRAW_ACTOR.sub(
                lambda match: f"{match.group(1) or ''}{label}{match.group(3)}", row["text"], 1
            )
        out[index] = fixed
    return out


_UNTIL_LEAVES = re.compile(r"\buntil\b.*\bleaves the battlefield\b", re.IGNORECASE)


def _tuck_orphan_exiles(
    rows: List[Dict[str, Any]], facts: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Name the host of a card exiled "until this leaves the battlefield".

    When Arena deleted the exiling ability in the same message (the usual case),
    the capture could not find its source: the exile row's ``by`` is the
    ability's own id, which no other row names, and it has no ``with``. Such an
    exile belongs under the source of the item that resolved just before it in
    the same turn, when that card exiles "until ... leaves the battlefield":
    by the ability's printed text, or by the card's Arena abilities
    (``exiles_until_leaves`` in the card facts) when the trigger was never
    printed and the card itself resolved last (Sheltered by Ghosts, Deep-Cavern
    Bat, Banishing Light).
    """
    facts = facts or {}

    def exiles_until_leaves(push: Dict[str, Any]) -> bool:
        payload = _payload(push)
        if _UNTIL_LEAVES.search(str(payload.get("text") or "")):
            return True
        name = str(payload.get("name") or "").casefold()
        return bool((facts.get(name) or {}).get("exiles_until_leaves"))

    known: Set[str] = set()
    for row in rows:
        for column in ("object_id", "target_object_id"):
            obj = _obj(row.get(column))
            if obj is not None:
                known.add(obj)
    pushes: Dict[str, Dict[str, Any]] = {}
    resolved: Optional[Dict[str, Any]] = None
    out: List[Dict[str, Any]] = []
    for row in rows:
        kind = row.get("event_subtype")
        payload = _payload(row)
        if kind == "stack_push" and payload.get("stack_id"):
            pushes[str(payload["stack_id"])] = row
        elif kind == "stack_resolve" and payload.get("stack_id"):
            resolved = pushes.get(str(payload["stack_id"]))
        elif kind == "turn":
            resolved = None
        elif (
            kind == "move"
            and _zone(row.get("zone_to")) == "exile"
            and "with" not in payload
            and payload.get("by") is not None
            and _obj(payload.get("by")) not in known
            and resolved is not None
            and resolved.get("turn_number") == row.get("turn_number")
            and _obj(resolved.get("object_id")) is not None
            and exiles_until_leaves(resolved)
        ):
            host = int(resolved["object_id"])
            row = dict(row)
            row["payload_json"] = json.dumps({**payload, "with": host, "by": host})
        out.append(row)
    return out


#: Row kinds that can only name a permanent already on the battlefield (as their source).
_ON_BATTLEFIELD_KINDS = frozenset(
    ("attack", "block", "tap", "untap", "sick", "unsick", "damage", "counter", "pt", "attach")
)

#: Added to ``limitations`` when the builder reconnects a card Arena's log lost track of.
LOST_ARRIVAL_LIMITATION = (
    "Arena's log left out the details of some very large updates; a card that "
    "arrived during one is shown arriving just before it is first used."
)


def _named_objects(row: Dict[str, Any]) -> List[str]:
    """Every object id a row names, in any column or payload field."""
    payload = _payload(row)
    values: List[Any] = [
        row.get("object_id"),
        row.get("target_object_id"),
        payload.get("target_object_id"),
        payload.get("source_object_id"),
        payload.get("by"),
        payload.get("with"),
        *(payload.get("object_ids") or []),
        *(payload.get("targets") or []),
    ]
    for pair in payload.get("pairs") or []:
        if isinstance(pair, dict):
            values.extend((pair.get("blocker"), pair.get("attacker")))
    return [obj for obj in (_obj(value) for value in values) if obj is not None]


def _renamed(row: Dict[str, Any], old: str, new: str) -> Dict[str, Any]:
    """``row`` with object id ``old`` replaced by ``new`` everywhere it appears."""

    def swap(value: Any) -> Any:
        return int(new) if _obj(value) == old else value

    out = dict(row)
    for column in ("object_id", "target_object_id"):
        out[column] = swap(row.get(column))
    payload = _payload(row)
    if payload:
        fixed = dict(payload)
        for key in ("target_object_id", "source_object_id", "by", "with"):
            if key in fixed:
                fixed[key] = swap(fixed[key])
        for key in ("object_ids", "targets"):
            if isinstance(fixed.get(key), list):
                fixed[key] = [swap(value) for value in fixed[key]]
        if isinstance(fixed.get("pairs"), list):
            fixed["pairs"] = [
                (
                    {
                        **pair,
                        "blocker": swap(pair.get("blocker")),
                        "attacker": swap(pair.get("attacker")),
                    }
                    if isinstance(pair, dict)
                    else pair
                )
                for pair in fixed["pairs"]
            ]
        out["payload_json"] = json.dumps(fixed)
    return out


def _lost_arrivals(rows: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int, Dict[str, Any]]]:
    """Objects first named on the battlefield, never seen arriving there.

    Maps each to ``(first index naming it, its Arena id, the first row it is the
    source of)``. The Arena id is the one on that row: a row's ``arena_id`` describes
    its ``object_id``. Objects with an ``identity`` row (face-down, transformed)
    are left out: their first Arena id may not be what was showing.
    """
    first: Dict[str, int] = {}
    moved: Set[str] = set()
    source: Dict[str, Dict[str, Any]] = {}
    hidden: Set[str] = set()
    for index, row in enumerate(rows):
        kind = row.get("event_subtype")
        for obj in _named_objects(row):
            first.setdefault(obj, index)
        obj = _obj(row.get("object_id"))
        if obj is None:
            continue
        if kind == "identity":
            hidden.add(obj)
        if kind == "move" and obj not in source:
            moved.add(obj)
        if obj not in source and row.get("arena_id") and obj not in moved:
            source[obj] = row
    out: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}
    for obj, row in source.items():
        if obj in hidden or row.get("event_subtype") not in _ON_BATTLEFIELD_KINDS | {"stack_push"}:
            continue
        if row.get("event_subtype") == "stack_push" and _payload(row).get("stack_kind") == "spell":
            continue
        out[obj] = (first[obj], int(row["arena_id"]), row)
    return out


def _reconnect_lost_arrivals(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """Bring back a card whose return to the battlefield Arena's log left out.

    Arena logs a message with more than 50 objects or annotations only as a
    summary ("Message summarized because ..."), so a card cast in one (Emrakul,
    the Exigent Doom cast from exile) turns up later under a new instance id no
    row ever moved, and the card it was stays in exile. When exactly one card
    with that Arena id sits in the same seat's exile (put there with no host)
    and no row names it again, the new id is that card: its rows are renamed and
    a silent ``exile → battlefield`` move goes before its first row,
    with Arena's ``sick`` flag when the first sickness row for it says so. The
    move is not marked inferred: the card and where it went are known, only the
    moment is not, and later rows place it.
    Returns the rows and whether anything was reconnected.
    """
    lost = _lost_arrivals(rows)
    if not lost:
        return rows, False
    named_at: Dict[str, List[int]] = {}
    exiled: Dict[str, Tuple[int, Dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        for obj in set(_named_objects(row)):
            named_at.setdefault(obj, []).append(index)
        obj = _obj(row.get("object_id"))
        if row.get("event_subtype") == "move" and obj is not None:
            exiled[obj] = (index, row)
    out = list(rows)
    changed = False
    for new, (start, arena_id, source) in sorted(lost.items(), key=lambda item: -item[1][0]):
        seat = _int(source.get("controller_seat")) or _int(source.get("seat_id"))
        candidates = []
        for old, (index, move) in exiled.items():
            payload = _payload(move)
            if (
                old != new
                and index < start
                and _zone(move.get("zone_to")) == "exile"
                and _int(move.get("arena_id")) == arena_id
                and not payload.get("token")
                and payload.get("with") is None
                and all(at <= index for at in named_at.get(old, []))
                and seat in (None, _int(move.get("controller_seat")) or _int(move.get("seat_id")))
            ):
                candidates.append((old, move))
        if len(candidates) != 1:
            continue
        old, move = candidates[0]
        anchor = out[start]
        arrival = {
            **{key: anchor.get(key) for key in ("event_time", "elapsed_seconds", "turn_number")},
            **{
                key: anchor.get(key)
                for key in ("phase", "step", "session_id", "match_id", "game_id")
            },
            "id": None,
            "visible": 0,
            "event_type": None,
            "event_subtype": "move",
            "object_id": int(old),
            "target_object_id": None,
            "arena_id": arena_id,
            "zone_from": "exile",
            "zone_to": "battlefield",
            "seat_id": move.get("seat_id"),
            "controller_seat": move.get("controller_seat"),
            "actor_role": move.get("actor_role"),
            "text": f"move {old}",
            "payload_json": json.dumps(
                {
                    **{
                        k: v
                        for k, v in _payload(move).items()
                        if k in ("name", "type", "power", "toughness")
                    },
                    "reason": "unknown",
                }
            ),
        }
        tail = [
            _renamed(row, new, old) if new in _named_objects(row) else row for row in out[start:]
        ]
        added = [arrival]
        for index, row in enumerate(tail):
            kind = row.get("event_subtype")
            ids = [_obj(value) for value in _payload(row).get("object_ids") or []]
            if kind in ("sick", "unsick") and old in ids:
                if kind == "sick":
                    # Sick from the moment it arrived: the flag moves up with it.
                    rest = [int(value) for value in ids if value != old and value is not None]
                    added.append(
                        {
                            **arrival,
                            "event_subtype": "sick",
                            "object_id": None,
                            "arena_id": None,
                            "zone_from": None,
                            "zone_to": None,
                            "text": row.get("text"),
                            "payload_json": json.dumps({"object_ids": [int(old)]}),
                        }
                    )
                    if rest:
                        tail[index] = dict(row, payload_json=json.dumps({"object_ids": rest}))
                    else:
                        tail[index] = None  # type: ignore[call-overload]
                break
        out = out[:start] + added + [row for row in tail if row is not None]
        changed = True
    return out, changed


class RecordedBuilder:
    """Single-use: ``RecordedBuilder(rows).run()`` returns the stream."""

    def __init__(self, rows: Dict[str, Any]) -> None:
        self.rows = rows
        self.stream = stream_header(rows, FIDELITY_RECORDED)
        self.player_seat: int = self.stream["player_seat"]
        self.opponent_seat: int = next(
            int(seat) for seat in self.stream["seats"] if int(seat) != self.player_seat
        )
        self.seats = (self.player_seat, self.opponent_seat)
        self.log = EventLog()
        self.cards = CardRegistry()
        self.zone_of: Dict[str, str] = {}
        self.owner_of: Dict[str, int] = {}
        self.card_of: Dict[str, Optional[str]] = {}
        self.open_stack: Dict[str, Dict[str, Any]] = {}
        self.closed_stack: Set[str] = set()
        self.life: Dict[int, int] = {
            int(seat): int(info.get("starting_life") or 20)
            for seat, info in self.stream["seats"].items()
        }
        self.participants = {str(row.get("role")): row for row in rows.get("participants") or []}
        self.card_rows_by_arena: Dict[int, Dict[str, Any]] = {}
        self.card_rows_by_name: Dict[str, Dict[str, Any]] = {}
        for row in rows.get("cards") or []:
            if row.get("arena_id"):
                self.card_rows_by_arena.setdefault(int(row["arena_id"]), row)
            if row.get("name"):
                self.card_rows_by_name.setdefault(str(row["name"]), row)
        self.deck_by_arena: Dict[int, Dict[str, Any]] = {}
        for row in rows.get("game_deck_cards") or []:
            if row.get("arena_id"):
                self.deck_by_arena.setdefault(int(row["arena_id"]), row)
        self._synthetic = 0
        self.reconnected = False
        self.learned_arena: Dict[str, int] = {}
        self._pending_ability: Optional[str] = None
        self.explicit_close: Dict[str, Any] = {}

    # -- helpers ---------------------------------------------------------

    def _card(
        self, arena_id: Any, name: Optional[str], payload: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        payload = payload or {}
        arena = _int(arena_id)
        row = (self.card_rows_by_arena.get(arena) if arena else None) or {}
        deck = (self.deck_by_arena.get(arena) if arena else None) or {}
        name = name or payload.get("name") or row.get("name") or deck.get("display_name")
        if not arena and (not name or is_unknown_card_name(name)):
            return None
        if not row and name:
            row = self.card_rows_by_name.get(str(name)) or {}
        return self.cards.add(
            name,
            arena,
            type_line=row.get("type_line"),
            primary_type=payload.get("type")
            or row.get("primary_type")
            or deck.get("type_category"),
            power=payload.get("power", row.get("power")),
            toughness=payload.get("toughness", row.get("toughness")),
            mana_cost=row.get("mana_cost"),
            color_identity=row.get("color_identity"),
            is_token=bool(payload.get("token")),
        )

    def _new_synthetic(self, prefix: str) -> str:
        self._synthetic += 1
        return f"{prefix}{self._synthetic}"

    def _emit_move(
        self,
        obj: str,
        card: Optional[str],
        source: str,
        dest: str,
        owner: int,
        controller: Optional[int],
        reason: str,
        inferred: bool = False,
        index: Optional[int] = None,
        exiled_with: Optional[str] = None,
        moved_by: Optional[str] = None,
        chosen: Optional[str] = None,
    ) -> Dict[str, Any]:
        if card is not None:
            self.card_of[obj] = card
        self.zone_of[obj] = dest
        self.owner_of.setdefault(obj, owner)
        return self.log.emit(
            "move",
            obj=obj,
            card=card if card is not None else self.card_of.get(obj),
            **{"from": source, "to": dest, "with": exiled_with, "by": moved_by},
            chosen=chosen,
            owner=owner,
            controller=controller if controller is not None else owner,
            reason=reason if reason in MOVE_REASONS else "unknown",
            inferred=inferred,
            index=index,
        )

    def _ensure(
        self, obj: Optional[str], zone: str, seat: Optional[int], card: Optional[str] = None
    ) -> None:
        """Introduce an object the rows reference before ever creating it."""
        if obj is None or obj in self.zone_of:
            return
        if card is None and obj in self.learned_arena:
            # Its later rows say what it is (a card cast while Arena's log only summarized).
            card = self._card(self.learned_arena[obj], None)
        owner = seat if seat is not None else self.player_seat
        self._emit_move(obj, card, "limbo", zone, owner, owner, "unknown", inferred=True)

    def _seat(self, row: Dict[str, Any], fallback: Optional[int] = None) -> Optional[int]:
        if row.get("event_subtype") == "move":
            # A printed move row keeps the seat its text names; capture stores
            # the card's owner in the payload when the two differ.
            owner = _int(_payload(row).get("owner"))
            if owner in self.seats:
                return owner
        seat = _int(row.get("seat_id"))
        if seat in self.seats:
            return seat
        role = row.get("actor_role")
        if role == "player":
            return self.player_seat
        if role == "opponent":
            return self.opponent_seat
        return fallback

    # -- setup -----------------------------------------------------------

    def _opening(self, rows: List[Dict[str, Any]]) -> Set[int]:
        """Emit game_start, opening hands, commanders and mulligans.

        Returns the ids of rows already consumed here.
        """
        consumed: Set[int] = set()
        first_turn = next(
            (i for i, row in enumerate(rows) if row.get("event_subtype") == "turn"), len(rows)
        )
        opening_rows: Dict[int, List[Dict[str, Any]]] = {seat: [] for seat in self.seats}
        mulligan_rows: List[Dict[str, Any]] = []
        for row in rows[:first_turn]:
            kind = row.get("event_subtype")
            if (
                kind == "move"
                and _zone(row.get("zone_from")) == "library"
                and _zone(row.get("zone_to")) == "hand"
            ):
                seat = self._seat(row, self.player_seat)
                opening_rows.setdefault(seat, []).append(row)
                consumed.add(id(row))
            elif kind == "mulligan":
                mulligan_rows.append(row)
                consumed.add(id(row))
        self._add_bottomed(rows, first_turn, opening_rows, mulligan_rows)

        player = self.participants.get("player") or {}
        opponent = self.participants.get("opponent") or {}
        hands: Dict[int, List[Tuple[str, Optional[str]]]] = {}
        if any(opening_rows.values()):
            for seat in self.seats:
                hands[seat] = [
                    (
                        _obj(row.get("object_id")) or self._new_synthetic(f"h{seat}-"),
                        (
                            self._card(row.get("arena_id"), None, _payload(row))
                            if seat == self.player_seat or row.get("arena_id")
                            else None
                        ),
                    )
                    for row in opening_rows.get(seat, [])
                ]
        else:
            hands = self._synthesize_hands(rows, player, opponent)

        library = {
            self.player_seat: self._library_size(player, self.player_seat, hands),
            self.opponent_seat: self._library_size(opponent, self.opponent_seat, hands),
        }
        self.log.emit(
            "game_start",
            seats_hand_sizes={str(seat): len(hands.get(seat, [])) for seat in sorted(self.seats)},
            library_sizes={str(seat): library[seat] for seat in sorted(self.seats)},
        )
        for seat in sorted(self.seats):
            for obj, card in hands.get(seat, []):
                self._emit_move(obj, card, "library", "hand", seat, seat, "draw")
        self._commanders(rows)
        if mulligan_rows:
            for row in mulligan_rows:
                payload = _payload(row)
                self.log.emit(
                    "mulligan",
                    seat=self._seat(row, self.player_seat),
                    from_size=_int(payload.get("from_size")) or 7,
                    to_size=_int(payload.get("to_size")) or _int(row.get("amount")) or 0,
                    bottomed=[
                        str(value)
                        for value in payload.get("bottomed") or []
                        if self.zone_of.get(str(value)) == "hand"
                    ],
                )
        else:
            for seat, participant in ((self.player_seat, player), (self.opponent_seat, opponent)):
                mulligans = _int(participant.get("mulligans")) or 0
                if mulligans > 0:
                    self.log.emit(
                        "mulligan",
                        seat=seat,
                        from_size=7,
                        to_size=len(hands.get(seat, [])),
                        bottomed=[],
                    )
        return consumed

    def _add_bottomed(
        self,
        rows: List[Dict[str, Any]],
        first_turn: int,
        opening_rows: Dict[int, List[Dict[str, Any]]],
        mulligan_rows: List[Dict[str, Any]],
    ) -> None:
        """Put the cards a mulligan bottoms back into the opening hand.

        Capture records only the cards kept, then the bottoming as a move from
        hand to library once turn 1 has begun. Without the bottomed card in the
        hand that move leaves the hand one card short for the rest of the game.
        """
        to_bottom: Dict[int, int] = {}
        for row in mulligan_rows:
            payload = _payload(row)
            drop = (_int(payload.get("from_size")) or 7) - (_int(payload.get("to_size")) or 7)
            seat = self._seat(row, self.player_seat)
            if drop > 0 and seat is not None:
                to_bottom[seat] = max(to_bottom.get(seat, 0), drop)
        if not to_bottom:
            return
        dealt = {
            _obj(row.get("object_id")) for seat_rows in opening_rows.values() for row in seat_rows
        }
        end = next(
            (
                i
                for i, row in enumerate(rows)
                if i > first_turn and row.get("event_subtype") == "turn"
            ),
            len(rows),
        )
        seen: Set[str] = set()
        for row in rows[:end]:
            obj = _obj(row.get("object_id"))
            if obj is None or obj in seen or obj in dealt:
                continue
            seen.add(obj)
            seat = self._seat(row, self.player_seat)
            if (
                row.get("event_subtype") == "move"
                and _zone(row.get("zone_from")) == "hand"
                and _zone(row.get("zone_to")) == "library"
                and to_bottom.get(seat, 0) > 0
                and 0 < len(opening_rows.get(seat, [])) < 7
            ):
                opening_rows.setdefault(seat, []).append(row)
                to_bottom[seat] -= 1

    def _synthesize_hands(
        self, rows: List[Dict[str, Any]], player: Dict[str, Any], opponent: Dict[str, Any]
    ) -> Dict[int, List[Tuple[str, Optional[str]]]]:
        """Opening hands from the tables plus each object's first reference.

        An object whose first appearance leaves the hand (cast, land play,
        discard) without a recorded draw was in the opening hand.
        """
        hand_names = [
            str(row.get("display_name"))
            for row in self.rows.get("game_opening_hand_cards") or []
            if row.get("participant_id") == player.get("id") and row.get("display_name")
        ]
        sizes = {
            self.player_seat: len(hand_names)
            or _int(player.get("opening_hand_size"))
            or max(0, 7 - (_int(player.get("mulligans")) or 0)),
            self.opponent_seat: max(0, 7 - (_int(opponent.get("mulligans")) or 0)),
        }
        seen: Set[str] = set()
        candidates: Dict[int, List[Tuple[str, Optional[str], Optional[str]]]] = {
            seat: [] for seat in self.seats
        }
        for row in rows:
            kind = row.get("event_subtype")
            obj = _obj(row.get("object_id"))
            # Only zone changes say where an object started; a reveal or an
            # identity row can precede the first move of a card in hand.
            if obj is None or obj in seen or kind not in ("move", "stack_push"):
                continue
            seen.add(obj)
            if _zone(row.get("zone_from")) != "hand":
                continue
            seat = self._seat(row)
            if seat is None or len(candidates[seat]) >= sizes[seat]:
                continue
            payload = _payload(row)
            name = payload.get("name")
            candidates[seat].append((obj, self._card(row.get("arena_id"), name, payload), name))
        hands: Dict[int, List[Tuple[str, Optional[str]]]] = {}
        remaining = list(hand_names)
        player_hand: List[Tuple[str, Optional[str]]] = []
        for obj, card, name in candidates[self.player_seat]:
            entry_name = (self.cards.cards.get(card) or {}).get("name") if card else name
            if entry_name in remaining:
                remaining.remove(entry_name)
            player_hand.append((obj, card))
        for name in remaining[: max(0, sizes[self.player_seat] - len(player_hand))]:
            player_hand.append(
                (self._new_synthetic(f"h{self.player_seat}-"), self._card(None, name))
            )
        while len(player_hand) < sizes[self.player_seat]:
            player_hand.append((self._new_synthetic(f"h{self.player_seat}-"), None))
        hands[self.player_seat] = player_hand
        # The opponent's opening cards are hidden at deal time; hindsight comes
        # from the same object id being revealed later.
        opponent_hand = [(obj, None) for obj, _card, _name in candidates[self.opponent_seat]]
        while len(opponent_hand) < sizes[self.opponent_seat]:
            opponent_hand.append((self._new_synthetic(f"h{self.opponent_seat}-"), None))
        hands[self.opponent_seat] = opponent_hand
        return hands

    def _library_size(
        self, participant: Dict[str, Any], seat: int, hands: Dict[int, List[Any]]
    ) -> int:
        total = 0
        if seat == self.player_seat:
            total = sum(
                _int(row.get("quantity")) or 0
                for row in self.rows.get("game_deck_cards") or []
                if row.get("participant_id") == participant.get("id")
                and row.get("deck_zone") == "deck"
            )
        commanders = self.stream["seats"][str(seat)].get("commanders") or []
        if total <= 0:
            total = _int(participant.get("deck_size")) or 0
            if not total:
                fmt = str(self.stream["game"].get("format") or "")
                total = 100 if "Brawl" in fmt and "Standard" not in fmt else 60
            if commanders and total in (60, 100):
                total -= len(commanders)
        return max(0, total - len(hands.get(seat, [])))

    def _commanders(self, rows: List[Dict[str, Any]]) -> None:
        """Commanders start in the command zone (no capture row puts them there)."""
        for seat in sorted(self.seats):
            for name in self.stream["seats"][str(seat)].get("commanders") or []:
                obj = None
                card = None
                for row in rows:
                    payload = _payload(row)
                    if (
                        row.get("event_subtype") in ("move", "stack_push")
                        and _zone(row.get("zone_from")) == "command"
                        and payload.get("name") == name
                    ):
                        obj = _obj(row.get("object_id"))
                        card = self._card(row.get("arena_id"), name, payload)
                        break
                obj = obj or self._new_synthetic(f"c{seat}-")
                if obj in self.zone_of:
                    continue
                self._emit_move(
                    obj, card or self._card(None, name), "limbo", "command", seat, seat, "put"
                )

    # -- rows ------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        rows = list(self.rows.get("game_events") or [])
        rows.sort(key=lambda row: (str(row.get("event_time") or ""), row.get("id") or 0))
        rows = _hoist_turn_headers(rows)
        rows = _hoist_token_creations(rows)
        rows = _hoist_battlefield_entries(rows)
        rows = _link_renamed_attackers(rows)
        rows = _drop_echoed_activations(rows)
        rows = _drop_repeated_moves(rows)
        rows = _reassign_misread_draws(rows, self.player_seat)
        rows = _tuck_orphan_exiles(rows, self.rows.get("card_facts"))
        rows, self.reconnected = _reconnect_lost_arrivals(rows)
        self.learned_arena = {obj: arena for obj, (_, arena, _) in _lost_arrivals(rows).items()}
        self.explicit_close = {
            str(_payload(row).get("stack_id")): row.get("event_subtype")
            for row in rows
            if row.get("event_subtype") in STACK_CLOSE_KINDS and _payload(row).get("stack_id")
        }
        consumed = self._opening(rows)
        has_game_end = False
        for row in rows:
            if id(row) in consumed:
                continue
            has_game_end = self._row(row) or has_game_end
        self._finish(has_game_end)
        return self.stream

    def _row(self, row: Dict[str, Any]) -> bool:
        kind = str(row.get("event_subtype") or "note")
        self.log.row_id = _int(row.get("id"))
        visible = row.get("visible", 1) not in (0, "0", False)
        self.log.at(
            row.get("elapsed_seconds"), row.get("turn_number"), row.get("phase"), row.get("step")
        )
        handler = getattr(self, f"_on_{kind}", None)
        self._pending_ability = None
        primary = handler(row, _payload(row)) if handler is not None else None
        if primary is None and visible:
            primary = self.log.emit("note")
        if visible:
            attach_log(primary, row.get("text"))
        # Abilities whose resolution was never captured resolve right after
        # their own line, so the stack does not fill up with stale items.
        pending, self._pending_ability = self._pending_ability, None
        if pending and pending in self.open_stack:
            self._close_item(pending, "stack_resolve")
        return kind == "game_end"

    def _on_turn(self, row, payload):
        for stack_id in list(self.open_stack):
            self._close_item(stack_id, "stack_resolve")
        turn = _int(row.get("turn_number")) or self.log.turn
        self.log.turn = turn
        active = _int(payload.get("active_seat")) or self._seat(row) or self.player_seat
        return self.log.emit("turn", turn=turn, active_seat=active)

    def _on_phase(self, row, payload):
        return self.log.emit("phase", phase=row.get("phase"), step=row.get("step"))

    def _on_life(self, row, payload):
        seat = self._seat(row)
        if seat is None:
            return None
        column = "player_life" if seat == self.player_seat else "opponent_life"
        total = _int(row.get(column))
        delta = _int(row.get("amount"))
        if total is None:
            total = self.life[seat] + (delta or 0)
        if delta is None:
            delta = total - self.life[seat]
        self.life[seat] = total
        return self.log.emit(
            "life",
            seat=seat,
            life=total,
            delta=delta,
            source_obj=_obj(payload.get("source_object_id")),
        )

    def _on_mulligan(self, row, payload):
        return self.log.emit(
            "mulligan",
            seat=self._seat(row, self.player_seat),
            from_size=_int(payload.get("from_size")) or 7,
            to_size=_int(payload.get("to_size")) or _int(row.get("amount")) or 0,
            bottomed=[],
        )

    def _on_move(self, row, payload):
        obj = _obj(row.get("object_id"))
        if obj is None:
            return None
        source, dest = _zone(row.get("zone_from")), _zone(row.get("zone_to"))
        owner = self._seat(row, self.player_seat)
        controller = _int(row.get("controller_seat")) or owner
        card = self._card(row.get("arena_id"), None, payload)
        if obj not in self.zone_of and source not in CREATING_ZONES:
            self._ensure(obj, source, owner, card)
        elif obj in self.zone_of and self.zone_of[obj] != source:
            # Trust the row's source over our own tracking only when they
            # disagree; the reducer follows the move's ``from``.
            source = self.zone_of[obj]
        if source == "stack":
            self._close_for_object(obj, payload.get("reason"))
        return self._emit_move(
            obj,
            card,
            source,
            dest,
            owner,
            controller,
            str(payload.get("reason") or "unknown"),
            inferred=bool(payload.get("inferred")),
            index=_int(payload.get("index")),
            exiled_with=_obj(payload.get("with")) if dest == "exile" else None,
            moved_by=_obj(payload.get("by")),
            chosen=payload.get("chosen") if isinstance(payload.get("chosen"), str) else None,
        )

    def _on_tap(self, row, payload, kind="tap"):
        objs = [str(value) for value in payload.get("object_ids") or [] if _int(value) is not None]
        seat = self._seat(row)
        for obj in objs:
            self._ensure(obj, "battlefield", seat)
        return self.log.emit(kind, objs=objs)

    def _on_untap(self, row, payload):
        return self._on_tap(row, payload, kind="untap")

    def _on_sick(self, row, payload):
        return self._on_tap(row, payload, kind="sick")

    def _on_unsick(self, row, payload):
        return self._on_tap(row, payload, kind="unsick")

    def _on_counter(self, row, payload):
        obj = _obj(row.get("object_id"))
        if obj is None:
            return None
        self._ensure(obj, "battlefield", self._seat(row))
        return self.log.emit(
            "counter",
            obj=obj,
            type=payload.get("type"),
            delta=_int(row.get("amount")),
            total=_int(payload.get("total")),
        )

    def _on_pt(self, row, payload):
        obj = _obj(row.get("object_id"))
        if obj is None:
            return None
        self._ensure(obj, "battlefield", self._seat(row))
        return self.log.emit(
            "pt",
            obj=obj,
            power=_int(payload.get("power")),
            toughness=_int(payload.get("toughness")),
        )

    def _on_attach(self, row, payload):
        obj = _obj(row.get("object_id"))
        if obj is None:
            return None
        self._ensure(obj, "battlefield", self._seat(row))
        target = _obj(row.get("target_object_id"))
        self._ensure(target, "battlefield", None)
        return self.log.emit("attach", obj=obj, to=target)

    def _on_identity(self, row, payload):
        obj = _obj(row.get("object_id"))
        card = self._card(row.get("arena_id"), payload.get("name"), payload)
        if obj is None or card is None:
            return None
        self._ensure(obj, "battlefield", self._seat(row))
        self.card_of[obj] = card
        return self.log.emit(
            "identity", obj=obj, card=card, face_down=bool(payload.get("face_down"))
        )

    def _on_stack_push(self, row, payload):
        stack_id = str(payload.get("stack_id") or self._new_synthetic("s-auto-"))
        obj = _obj(row.get("object_id"))
        seat = self._seat(row, self.player_seat)
        controller = _int(row.get("controller_seat")) or seat
        # Payload key is "stack_kind"; tolerate the legacy "kind" spelling.
        raw_kind = payload.get("stack_kind") or payload.get("kind")
        stack_kind = raw_kind if raw_kind in STACK_KINDS else "trigger"
        card = self._card(row.get("arena_id"), payload.get("name"), payload)
        if stack_kind == "spell" and obj is not None and self.zone_of.get(obj) != "stack":
            source = _zone(row.get("zone_from") or "hand")
            if obj not in self.zone_of and source == "exile":
                # A copy Arena makes in exile and casts at once (a prepared
                # spell's copy, Studious First-Year's Rampant Growth): it
                # appears on the stack, not as an inferred card in exile first.
                source = "limbo"
            elif obj not in self.zone_of and source not in CREATING_ZONES:
                self._ensure(obj, source, seat, card)
            source = self.zone_of.get(obj, source)
            self._emit_move(obj, card, source, "stack", seat, controller, "cast")
        elif stack_kind != "spell":
            self._ensure(obj, "battlefield", seat, card)
        targets = [str(value) for value in payload.get("targets") or [] if _int(value) is not None]
        targets = [target for target in targets if target in self.zone_of]
        if stack_id in self.open_stack or stack_id in self.closed_stack:
            stack_id = self._new_synthetic(f"{stack_id}-dup")
        event = self.log.emit(
            "stack_push",
            stack_id=stack_id,
            obj=obj,
            card=card,
            stack_kind=stack_kind,
            controller=controller,
            text=str(payload.get("text") or ""),
            targets=targets,
        )
        self.open_stack[stack_id] = {"obj": obj, "spell": stack_kind == "spell"}
        if stack_kind != "spell" and stack_id not in self.explicit_close:
            # Abilities whose resolution was never printed resolve at once.
            self._pending_ability = stack_id
        return event

    def _on_stack_close(self, row, payload, kind):
        stack_id = str(payload.get("stack_id") or "")
        if stack_id not in self.open_stack:
            return None
        return self._close_item(stack_id, kind)

    def _on_stack_resolve(self, row, payload):
        return self._on_stack_close(row, payload, "stack_resolve")

    def _on_stack_fizzle(self, row, payload):
        return self._on_stack_close(row, payload, "stack_fizzle")

    def _on_stack_countered(self, row, payload):
        return self._on_stack_close(row, payload, "stack_countered")

    def _close_item(self, stack_id: str, kind: str) -> Dict[str, Any]:
        self.open_stack.pop(stack_id, None)
        self.closed_stack.add(stack_id)
        return self.log.emit(kind, stack_id=stack_id)

    def _close_for_object(self, obj: str, reason: Any) -> None:
        """A spell leaving the stack closes its item first (rule 3)."""
        for stack_id, item in list(self.open_stack.items()):
            if item["obj"] == obj and item["spell"]:
                kind = self.explicit_close.get(stack_id) or (
                    "stack_countered" if reason == "counter" else "stack_resolve"
                )
                self._close_item(stack_id, kind)

    def _on_attack(self, row, payload):
        seat = self._seat(row, self.player_seat)
        objs = [str(value) for value in payload.get("object_ids") or [] if _int(value) is not None]
        if not objs and _obj(row.get("object_id")):
            objs = [_obj(row.get("object_id"))]
        for obj in objs:
            self._ensure(obj, "battlefield", seat)
        target_obj = _obj(payload.get("target_object_id"))
        target_seat = _int(payload.get("target_seat"))
        if target_obj is not None:
            self._ensure(target_obj, "battlefield", None)
        elif target_seat is None:
            target_seat = self.opponent_seat if seat == self.player_seat else self.player_seat
        return self.log.emit(
            "attack", seat=seat, objs=objs, target_seat=target_seat, target_obj=target_obj
        )

    def _on_block(self, row, payload):
        seat = self._seat(row, self.player_seat)
        pairs = []
        for pair in payload.get("pairs") or []:
            blocker, attacker = _obj(pair.get("blocker")), _obj(pair.get("attacker"))
            if blocker is None or attacker is None:
                continue
            self._ensure(blocker, "battlefield", seat)
            self._ensure(attacker, "battlefield", None)
            pairs.append({"blocker": blocker, "attacker": attacker})
        return self.log.emit("block", seat=seat, pairs=pairs)

    def _on_damage(self, row, payload):
        source = _obj(row.get("object_id"))
        target_obj = _obj(row.get("target_object_id"))
        target_seat = _int(payload.get("target_seat"))
        if target_obj is None and target_seat is None:
            target_seat = self._seat(row)
        if source is not None and source not in self.zone_of:
            self._ensure(source, "battlefield", None)
        if target_obj is not None:
            self._ensure(target_obj, "battlefield", None)
        return self.log.emit(
            "damage",
            source=source,
            target_obj=target_obj,
            target_seat=None if target_obj else target_seat,
            amount=_int(row.get("amount")) or 0,
            combat=bool(payload.get("combat")),
        )

    def _on_reveal(self, row, payload):
        obj = _obj(row.get("object_id"))
        card = self._card(row.get("arena_id"), payload.get("name"), payload)
        if obj is None or card is None:
            return None
        if obj not in self.zone_of:
            # Arena reveals through proxy objects (GameObjectType_RevealedCard)
            # that never enter a zone the board shows; a reveal of an object
            # no row ever placed would only plant a phantom card.
            return None
        self.card_of[obj] = card
        return self.log.emit("reveal", obj=obj, card=card)

    def _on_scry(self, row, payload):
        seat = self._seat(row, self.player_seat)
        return self.log.emit(
            "scry",
            seat=seat,
            top=[str(value) for value in payload.get("top") or []],
            bottom=[str(value) for value in payload.get("bottom") or []],
            looked=_int(row.get("amount")) or 0,
        )

    def _on_shuffle(self, row, payload):
        return self.log.emit("shuffle", seat=self._seat(row, self.player_seat))

    def _on_game_end(self, row, payload):
        self._close_open()
        self._correct_life()
        return self.log.emit(
            "game_end",
            winner_seat=_int(row.get("seat_id")),
            reason=payload.get("reason") or self.stream["game"].get("outcome_reason"),
        )

    def _on_note(self, row, payload):
        return None

    # -- finish ----------------------------------------------------------

    def _close_open(self) -> None:
        for stack_id in list(reversed(list(self.open_stack))):
            self._close_item(stack_id, "stack_resolve")

    def _correct_life(self) -> None:
        for role, participant in self.participants.items():
            seat = self.player_seat if role == "player" else self.opponent_seat
            ending = _int(participant.get("ending_life"))
            if ending is not None and ending != self.life.get(seat):
                self.log.emit(
                    "life", seat=seat, life=ending, delta=ending - self.life[seat], source_obj=None
                )
                self.life[seat] = ending

    def _finish(self, has_game_end: bool) -> None:
        self.log.row_id = None
        if not has_game_end:
            self._close_open()
            self._correct_life()
            game = self.stream["game"]
            self.log.emit(
                "game_end", winner_seat=game.get("winner_seat"), reason=game.get("outcome_reason")
            )
        finalize_logs(self.log.events, self.cards)
        events = self.log.events
        if self.reconnected:
            self.stream["limitations"].append(LOST_ARRIVAL_LIMITATION)
        version = _int(self.stream.get("replay_version")) or 0
        if version < SICKNESS_CAPTURE_VERSION:
            estimated = estimate_summoning_sickness(
                events, self.cards.cards, self.rows.get("card_facts")
            )
            if estimated is not events:
                events = estimated
                self.stream["limitations"].append(SICKNESS_ESTIMATE_LIMITATION)
        self.stream["events"] = events
        self.stream["turns"] = build_turns(events, self.rows.get("game_turns") or [])
        self.stream["cards"] = self.cards.cards
        for seat_key, info in self.stream["seats"].items():
            seat = int(seat_key)
            keys = {
                card
                for obj, card in self.card_of.items()
                if card and self.owner_of.get(obj) == seat
            }
            info["colors"] = seat_colors(self.cards.cards.get(key) for key in sorted(keys))


def build_recorded(rows: Dict[str, Any]) -> Dict[str, Any]:
    """Stream for a ``replay_version = 1`` game (``fidelity: recorded``)."""
    return RecordedBuilder(rows).run()


# --- dispatch, images, serving -------------------------------------------


def build_stream(rows: Dict[str, Any]) -> Dict[str, Any]:
    """Builder for recorded games, reconstructor otherwise (contract §2)."""
    game = (rows.get("games") or [{}])[0]
    if not rows.get("game_events"):
        raise ReplayUnavailable("no events")
    if game.get("replay_version") is not None:
        return build_recorded(rows)
    from .replay_reconstruct import reconstruct

    return reconstruct(rows)


ImageResolver = Callable[[int], Optional[str]]
_image_lock = threading.Lock()
_image_state: Dict[str, Any] = {"cache_mtime": None, "cache": {}, "index": None}
#: Tests (or callers without an Arena install) may replace this.
image_resolver_override: Optional[ImageResolver] = None
#: Same, for a token's Scryfall ``set/number`` (``default_token_print``).
token_print_override: Optional[ImageResolver] = None
#: Same, for a card's Scryfall ``set/number`` (``default_print``).
print_override: Optional[ImageResolver] = None


def _scryfall_cache_path() -> Path:
    from .paths import DATA_DIR

    return DATA_DIR / "scryfall_id_cache.json"


def _arena_printing(arena_id: int) -> Optional[Tuple[str, str, str]]:
    """(name, set, collector number) from Arena's card DB; call under ``_image_lock``."""
    if _image_state["index"] is None:
        try:
            from .card_database import CardDatabase

            _image_state["index"] = CardDatabase().export_index_by_arena_id() or {}
        except Exception:  # noqa: BLE001 - a missing Arena install is normal
            _image_state["index"] = {}
    return _image_state["index"].get(int(arena_id))


def default_print(arena_id: int) -> Optional[str]:
    """A card's Scryfall ``set/number`` (``fra/23``), from Arena's card DB; None when unknown.

    Scryfall knows a new set's cards by set and number before it learns their
    Arena ids, and that lookup is not held to the 2 per second of its name search.
    """
    with _image_lock:
        entry = _arena_printing(arena_id)
    if not entry:
        return None
    _name, set_code, collector = entry
    if not set_code or not collector:
        return None
    return f"{set_code.lower()}/{collector}"


def default_token_print(arena_id: int) -> Optional[str]:
    """A token's Scryfall ``set/number``, from Arena's card DB; None when unknown.

    Arena files a token under its card set's code with the token's own number
    (the Mobilize Warrior is TDM 13), and Scryfall numbers that set's tokens
    the same way under the set code with a leading "t": ``ttdm/13``.
    """
    card_print = default_print(arena_id)
    return f"t{card_print}" if card_print else None


def default_image_url(arena_id: int) -> Optional[str]:
    """Direct Scryfall CDN URL from local data only; None when unresolvable.

    Arena id → (set, collector) from Arena's card DB, then the collection
    exporter's ``set|collector`` → Scryfall id cache. No network calls.
    """
    with _image_lock:
        path = _scryfall_cache_path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != _image_state["cache_mtime"]:
            cache: Dict[str, str] = {}
            if mtime is not None:
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict):
                        cache = {str(k): str(v) for k, v in loaded.items() if v}
                except (OSError, ValueError):
                    cache = {}
            _image_state["cache"] = cache
            _image_state["cache_mtime"] = mtime
        cache = _image_state["cache"]
        if not cache:
            return None
        entry = _arena_printing(arena_id)
    if not entry:
        return None
    _name, set_code, collector = entry
    if not set_code or not collector:
        return None
    scryfall_id = cache.get(f"{set_code.lower()}|{collector}")
    if not scryfall_id or len(scryfall_id) < 2:
        return None
    return (
        "https://cards.scryfall.io/normal/front/"
        f"{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"
    )


def attach_image_urls(
    stream: Dict[str, Any],
    resolver: Optional[ImageResolver] = None,
    token_printer: Optional[ImageResolver] = None,
    printer: Optional[ImageResolver] = None,
) -> None:
    resolve = resolver or image_resolver_override or default_image_url
    token_print = token_printer or token_print_override or default_token_print
    card_print = printer or print_override or default_print
    for entry in (stream.get("cards") or {}).values():
        arena_id = entry.get("arena_id")
        if not arena_id or entry.get("image_url"):
            continue
        if entry.get("is_token"):
            # Never the set/number cache: a token's number names a different
            # card in the card set (Warrior TDM 13 is Furious Forebear). The
            # page loads the token printing by ``token_print`` instead.
            if not entry.get("token_print"):
                try:
                    entry["token_print"] = token_print(int(arena_id))
                except Exception:  # noqa: BLE001 - images are best effort
                    entry["token_print"] = None
            continue
        try:
            url = resolve(int(arena_id))
        except Exception:  # noqa: BLE001 - images are best effort
            url = None
        # A back face shares its front's set and number; Scryfall serves it under /back/.
        if url and entry.get("back_face"):
            url = url.replace("/front/", "/back/")
        entry["image_url"] = url
        if not url and not entry.get("print"):
            # The page looks the printing up instead (a new set's cards are not cached yet).
            try:
                entry["print"] = card_print(int(arena_id))
            except Exception:  # noqa: BLE001 - images are best effort
                entry["print"] = None


CardFactsLoader = Callable[[], Dict[str, Dict[str, Any]]]
#: Tests (or callers without an Arena install) may replace this.
card_facts_override: Optional[CardFactsLoader] = None
_facts_lock = threading.Lock()
_facts_state: Dict[str, Any] = {"facts": None}


def default_card_facts() -> Dict[str, Dict[str, Any]]:
    """CardDatabase.replay_card_facts, loaded once per process."""
    with _facts_lock:
        if _facts_state["facts"] is None:
            try:
                from .card_database import CardDatabase

                _facts_state["facts"] = CardDatabase().replay_card_facts() or {}
            except Exception:  # noqa: BLE001 - a missing Arena install is normal
                _facts_state["facts"] = {}
        return _facts_state["facts"]


def load_card_facts() -> Dict[str, Dict[str, Any]]:
    try:
        return (card_facts_override or default_card_facts)() or {}
    except Exception:  # noqa: BLE001 - facts only refine the replay
        return {}


def attach_card_facts(stream: Dict[str, Any], facts: Dict[str, Dict[str, Any]]) -> None:
    """Sets each card entry's ``keywords`` and ``back_face`` from Arena's card DB.

    A token is looked up by its Arena id (``#<grpId>``) before its name. A
    "token" whose Arena id is a real card's is a token copy of that card (Arena
    gives the copy the card's own id), and that id names the real card too: it
    is not a token, so it shows the card's own printing.
    """
    for entry in (stream.get("cards") or {}).values():
        real = facts.get(str(entry.get("name") or "").casefold()) or {}
        if entry.get("is_token") and _int(entry.get("arena_id")) in (real.get("grp_ids") or ()):
            entry["is_token"] = False
        fact = card_fact(entry, facts)
        if not fact:
            continue
        entry["keywords"] = list(fact.get("keywords") or [])
        entry["back_face"] = bool(fact.get("back_face"))
        if entry.get("is_token"):
            continue
        # Fill what the game's rows never said (an opponent card seen only by name).
        if not entry.get("type_line") and fact.get("type_line"):
            entry["type_line"] = fact["type_line"]
            if not entry.get("primary_type"):
                entry["primary_type"] = primary_type_from_text(fact["type_line"])
        for field in ("power", "toughness"):
            if entry.get(field) in (None, "") and fact.get(field) not in (None, ""):
                entry[field] = str(fact[field])


_UNNAMED_COUNTER = re.compile(r"^counter_(\d+)$")


def attach_counter_names(stream: Dict[str, Any], facts: Dict[str, Dict[str, Any]]) -> None:
    """Names counters recorded as ``counter_<n>`` (Arena's CounterType) from the card facts."""
    for event in stream.get("events") or []:
        if event.get("kind") != "counter":
            continue
        match = _UNNAMED_COUNTER.match(str(event.get("type") or ""))
        name = match and (facts.get(f"#counter:{match.group(1)}") or {}).get("counter")
        if name:
            event["type"] = name


def replay_for_game(db_path: Path, game_id: str) -> Dict[str, Any]:
    """Load, build and enrich one game's stream from a read-only connection.

    Raises FileNotFoundError (no DB), LookupError (unknown game) or
    ReplayUnavailable (no events).
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = load_replay_rows(conn, game_id)
    finally:
        conn.close()
    if rows is None:
        raise LookupError(f"No recorded game for id: {game_id}")
    facts = load_card_facts()
    rows["card_facts"] = facts
    stream = build_stream(rows)
    attach_card_facts(stream, facts)
    attach_counter_names(stream, facts)
    attach_image_urls(stream)
    return stream
