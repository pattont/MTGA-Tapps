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
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

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
_HOISTABLE_KINDS = ("untap", "tap", "phase", "pt", "counter")


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
            if obj not in self.zone_of and source not in CREATING_ZONES:
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
        self.stream["events"] = self.log.events
        self.stream["turns"] = build_turns(self.log.events, self.rows.get("game_turns") or [])
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


def _scryfall_cache_path() -> Path:
    from .paths import DATA_DIR

    return DATA_DIR / "scryfall_id_cache.json"


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
        if _image_state["index"] is None:
            try:
                from .card_database import CardDatabase

                _image_state["index"] = CardDatabase().export_index_by_arena_id() or {}
            except Exception:  # noqa: BLE001 - a missing Arena install is normal
                _image_state["index"] = {}
        entry = _image_state["index"].get(int(arena_id))
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


def attach_image_urls(stream: Dict[str, Any], resolver: Optional[ImageResolver] = None) -> None:
    resolve = resolver or image_resolver_override or default_image_url
    for entry in (stream.get("cards") or {}).values():
        arena_id = entry.get("arena_id")
        if not arena_id or entry.get("image_url"):
            continue
        try:
            url = resolve(int(arena_id))
        except Exception:  # noqa: BLE001 - images are best effort
            url = None
        # A back face shares its front's set and number; Scryfall serves it under /back/.
        if url and entry.get("back_face"):
            url = url.replace("/front/", "/back/")
        entry["image_url"] = url


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
    """Sets each card entry's ``keywords`` and ``back_face`` from Arena's card DB."""
    for entry in (stream.get("cards") or {}).values():
        fact = facts.get(str(entry.get("name") or "").casefold())
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
    attach_image_urls(stream)
    return stream
