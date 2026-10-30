"""Reconstruct a replay stream from the console text of older games.

Games recorded before structured capture (``games.replay_version IS NULL``)
only kept their printed lines in ``game_events``. The tracker generated that
text, so it follows a small regular grammar anchored on ``[Name (Type P/T)]``
brackets (``docs/REPLAY_FORMAT.md`` section 4). This module turns those rows,
plus the opening hand, mulligan, decklist and turn tables, into the same
stream the builder produces, with ``fidelity: reconstructed``.

Pure and deterministic: rows in, stream out, one pass over the events after a
linear stack-pairing pre-pass. Lines the grammar does not recognise become
``note`` events instead of failing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .replay_reconstruct_board import ReconstructionBoard, _Obj
from .replay_reconstruct_grammar import (
    _ABILITY_RE,
    _ARROW_RE,
    _ATTACK_RE,
    _BECAME_RE,
    _BRACKET_RE,
    _bracket_names,
    _CAST_RE,
    _close_status,
    _COUNTERED_RE,
    _DEALT_RE,
    _DESTROYED_RE,
    _DISCARDED_RE,
    _DRAW_RE,
    _EXILED_RE,
    _LAND_RE,
    _LIFE_RE,
    _MILLED_RE,
    _PLAYER_TARGETS,
    _PUT_BATTLEFIELD_RE,
    _PUT_HAND_RE,
    _RETURN_TO_BATTLEFIELD_TEXT_RE,
    _RETURNED_BATTLEFIELD_RE,
    _RETURNED_RE,
    _SACRIFICED_RE,
    _SBA_RE,
    _SCRY_RE,
    _SOURCE_RETURNED_RE,
    _split_actor,
    _STACK_RE,
    _SWAP_RE,
    _TAPPED_RE,
    _TOOK_RE,
    _to_int,
    _TS_RE,
    _TURN_RE,
    created_tokens,
    pair_stack_rows,
    parse_bracket,
)
from .replay_sickness import SICKNESS_ESTIMATE_LIMITATION, estimate_summoning_sickness
from .replay_stream import attach_log, build_turns, finalize_logs, seat_colors

__all__ = ["Reconstructor", "pair_stack_rows", "parse_bracket", "reconstruct"]


class Reconstructor(ReconstructionBoard):
    """Single-use: ``Reconstructor(rows).run()`` returns the stream."""

    # -- row handlers ----------------------------------------------------

    def run(self) -> Dict[str, Any]:
        # Printed history only: a game without replay_version has no silent
        # (visible = 0) rows unless its game row was rebuilt by an audit repair.
        events = [
            row
            for row in self.rows.get("game_events") or []
            if row.get("visible", 1) not in (0, "0", False)
        ]
        events.sort(key=lambda row: (str(row.get("event_time") or ""), row.get("id") or 0))
        #: Names an ability is returning to the battlefield this turn (see _RETURNED_RE).
        self._returning_to_battlefield: Set[str] = set()
        self._row_elapsed: Any = None
        self._row_stamp: Optional[str] = None
        self._damage_moment: Tuple[Any, Set[str]] = (None, set())
        pairs = pair_stack_rows(events)
        self.closed_by: Dict[int, int] = pairs
        self.paired_pushes = set(pairs.values())
        self._setup()
        for index, row in enumerate(events):
            self._row(index, row)
        self._finish()
        return self.stream

    def _row(self, index: int, row: Dict[str, Any]) -> None:
        event_type = str(row.get("event_type") or "")
        phase = row.get("phase")
        self.log.row_id = _to_int(row.get("id"))
        self.log.at(row.get("elapsed_seconds"), row.get("turn_number"), phase, None)
        if event_type != "turn" and phase and phase != self._phase_seen:
            self.log.emit("phase", phase=phase, step=None)
            self._phase_seen = phase
        text = str(row.get("text") or "")
        self._row_elapsed = row.get("elapsed_seconds")
        stamp = _TS_RE.match(text)
        self._row_stamp = stamp.group(0).strip() if stamp else None
        handler = getattr(self, f"_on_{event_type}", None)
        primary = handler(index, row, text) if handler is not None else None
        if primary is None:
            primary = self.log.emit("note")
        attach_log(primary, text)
        # A push whose resolution the text never shows (single-item resolves
        # are not printed) resolves right after its own line.
        pending, self._pending_close = self._pending_close, None
        if pending is not None and pending.open:
            self._close(pending, "stack_resolve")
        if event_type == "turn":
            self._phase_seen = phase
        self._sync_life(row)

    def _sync_life(self, row: Dict[str, Any]) -> None:
        for seat, column in (
            (self.player_seat, "player_life"),
            (self.opponent_seat, "opponent_life"),
        ):
            value = _to_int(row.get(column))
            if value is not None and value != self.life[seat]:
                self.log.emit(
                    "life", seat=seat, life=value, delta=value - self.life[seat], source_obj=None
                )
                self.life[seat] = value

    def _on_turn(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        match = _TURN_RE.match(text.strip())
        if not match:
            return None
        self._close_all_open()
        turn = int(match.group(1))
        active = self.player_seat if match.group(2) == "YOUR TURN" else self.opponent_seat
        self.attacking.clear()
        self.blocks.clear()
        self.log.turn = turn
        self._returning_to_battlefield.clear()
        return self.log.emit("turn", turn=turn, active_seat=active)

    def _on_draw(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        match = _DRAW_RE.match(body)
        if seat is None or not match:
            return None
        name = parse_bracket(match.group(1))[0] if match.group(1) else None
        obj = self._from_library(seat, name)
        inferred = obj is None
        if obj is None:
            obj = self._limbo(seat, name)
        if name:
            obj.card = self._card(name, token=obj.token)
        return self._move(obj, "hand", "draw", inferred=inferred)

    def _from_hand_or_elsewhere(
        self, seat: int, name: str, types: Sequence[str], extra_zones: Sequence[str]
    ) -> Tuple[_Obj, bool]:
        obj = self._find(name, [seat], ["hand"])
        if obj is None and "command" in extra_zones:
            obj = self._find(name, [seat], ["command"])
        if obj is None:
            obj = self._from_hand(seat, name, types)
        if obj is None:
            obj = self._find(name, [seat], [z for z in extra_zones if z != "command"])
        if obj is not None:
            self._reveal(obj, name, types)
            if types:
                obj.card = self._card(obj.name, types, token=obj.token)
            return obj, False
        obj = self._limbo(seat, name)
        obj.card = self._card(name, types)
        return obj, True

    def _on_land(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        match = _LAND_RE.match(body)
        if seat is None or not match:
            return None
        name, types, _p, _t = parse_bracket(match.group(1))
        obj, inferred = self._from_hand_or_elsewhere(
            seat, name, types or ["Land"], ["graveyard", "exile"]
        )
        return self._move(
            obj, "battlefield", "play_land", inferred=inferred, seat=seat, chosen=match.group(2)
        )

    def _on_cast(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        match = _CAST_RE.match(body)
        if seat is None or not match:
            return None
        name, types, power, toughness = parse_bracket(match.group(1))
        rest = match.group(2)
        targets = self._targets(rest.split("->", 1)[1], seat) if "->" in rest else []
        obj = self._alternate_source(seat, name)
        inferred = False
        if obj is not None:
            if types:
                obj.card = self._card(obj.name, types, token=obj.token)
        else:
            obj, inferred = self._from_hand_or_elsewhere(
                seat, name, types, ["command", "graveyard", "exile"]
            )
        self._move(obj, "stack", "cast", inferred=inferred, seat=seat)
        event = self._push(index, seat, obj, name, False, types, "", targets)
        if index not in self.paired_pushes:
            self._pending_close = self.items[index]
        return event

    def _on_stack(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        if _CAST_RE.match(body):
            return self._on_cast(index, row, text)
        return self._on_ability(index, row, text)

    def _on_ability(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        if seat is None:
            return None
        became = _BECAME_RE.match(body)
        if became:
            return self._identity(seat, became)
        if _TAPPED_RE.match(body) or body.startswith("chose modes for") or body == "scried":
            return None
        match = _ABILITY_RE.match(body)
        if not match:
            return None
        name = parse_bracket(match.group(1))[0]
        ability_text = re.sub(r"\s*\(triggered, on stack\)\s*$", "", match.group(2).strip())
        targets: List[str] = []
        if " -> [" in ability_text:
            ability_text, target_text = ability_text.split(" -> [", 1)
            targets = self._targets("[" + target_text, seat)
        source = self._find(
            name,
            [seat],
            ["battlefield", "stack", "graveyard", "exile", "hand", "command"],
        ) or self._find(name, [self._other(seat)], ["battlefield"])
        event = self._push(index, seat, source, name, True, (), ability_text.strip(), targets)
        self.items[index].creates = created_tokens(ability_text)
        if " -> [" in match.group(2) and _RETURN_TO_BATTLEFIELD_TEXT_RE.search(ability_text):
            target_text = match.group(2).split(" -> [", 1)[1]
            for content in _BRACKET_RE.findall("[" + target_text):
                self._returning_to_battlefield.add(parse_bracket(content)[0])
        if index not in self.paired_pushes:
            self._pending_close = self.items[index]
        return event

    def _identity(self, seat: int, match: "re.Match[str]") -> Optional[Dict[str, Any]]:
        old_name = parse_bracket(match.group(1))[0]
        new_name = parse_bracket(match.group(2))[0]
        obj = self._find(old_name, [seat, self._other(seat)], ["battlefield"]) or self._find(
            old_name, [seat, self._other(seat)], ["stack", "graveyard", "exile", "hand", "command"]
        )
        if obj is None:
            return None
        obj.add_alias(new_name)
        obj.name = new_name
        obj.card = self._card(new_name, token=obj.token)
        event = self.log.emit("identity", obj=obj.oid, card=obj.card, face_down=False)
        pt = match.group(3)
        if pt and "/" in pt:
            power, toughness = pt.split("/", 1)
            obj.pt = None
            self._update_pt(obj, power.strip(), toughness.strip())
        return event

    def _on_stack_resolve(
        self, index: int, row: Dict[str, Any], text: str
    ) -> Optional[Dict[str, Any]]:
        return self._stack_close_row(index, text)

    def _on_stack_fail(
        self, index: int, row: Dict[str, Any], text: str
    ) -> Optional[Dict[str, Any]]:
        return self._stack_close_row(index, text)

    def _stack_close_row(self, index: int, text: str) -> Optional[Dict[str, Any]]:
        _actor, body = _split_actor(text)
        match = _STACK_RE.match(body)
        if not match:
            return None
        kind, _rest = _close_status(match.group(2))
        push_index = self.closed_by.get(index)
        item = self.items.get(push_index) if push_index is not None else None
        if kind is None or item is None or not item.open:
            return None
        types = parse_bracket(match.group(1))[1]
        return self._close(item, kind, types)

    def _on_counter(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        match = _COUNTERED_RE.match(body)
        if not match:
            return None
        push_index = self.closed_by.get(index)
        item = self.items.get(push_index) if push_index is not None else None
        if item is not None and item.open:
            return self._close(item, "stack_countered")
        name = parse_bracket(match.group(1))[0]
        seats = [seat, self._other(seat)] if seat is not None else list(self.seats)
        obj = self._find(name, seats, ["stack"])
        if obj is None:
            return None
        return self._move(obj, "graveyard", "counter")

    def _on_zone(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        if seat is None:
            return None
        both = [seat, self._other(seat)]

        match = _DESTROYED_RE.match(body) or _SACRIFICED_RE.match(body)
        if match:
            name = parse_bracket(match.group(1))[0]
            reason = "destroy" if body.endswith("destroyed") else "sacrifice"
            obj = self._find(name, both, ["battlefield", "stack"]) or self._find(
                name, [seat], ["hand"]
            )
            if obj is None:
                obj = self._ensure_battlefield(seat, name)
            return self._move(obj, "graveyard", reason)

        match = _SBA_RE.match(body)
        if match:
            name = parse_bracket(match.group(1))[0]
            obj = self._find(name, both, ["battlefield", "stack"])
            if obj is None:
                obj = self._ensure_battlefield(seat, name)
            return self._move(obj, "graveyard", "sba")

        match = _EXILED_RE.match(body)
        if match:
            name = parse_bracket(match.group(1))[0]
            if match.group(2):
                order = ["graveyard", "hand", "battlefield", "stack"]
            else:
                order = ["battlefield", "stack", "hand", "graveyard"]
            obj = self._find(name, both, order)
            inferred = False
            if obj is None and (
                match.group(2) or "plot" in (self._fact(name).get("keywords") or ())
            ):
                # Plotting exiles the card from its owner's hand.
                obj = self._from_hand(seat, name)
            if obj is None:
                obj, inferred = self._limbo(seat, name), True
            return self._move(obj, "exile", "exile", inferred=inferred)

        match = _DISCARDED_RE.match(body)
        if match:
            name = parse_bracket(match.group(1))[0]
            obj = self._from_hand(seat, name)
            inferred = obj is None
            if obj is None:
                obj = self._limbo(seat, name)
            return self._move(obj, "graveyard", "discard", inferred=inferred)

        match = _MILLED_RE.match(body)
        if match:
            name = parse_bracket(match.group(1))[0] if match.group(1) else None
            obj = self._from_library(seat, name)
            inferred = obj is None
            if obj is None:
                obj = self._limbo(seat, name)
            if name:
                obj.card = self._card(name, token=obj.token)
            return self._move(obj, "graveyard", "mill", inferred=inferred)

        match = _RETURNED_BATTLEFIELD_RE.match(body)
        if match:
            return self._return_to_battlefield(seat, parse_bracket(match.group(2))[0])

        match = _RETURNED_RE.match(body)
        if match and parse_bracket(match.group(1))[0] in self._returning_to_battlefield:
            return self._return_to_battlefield(seat, parse_bracket(match.group(1))[0])
        if match:
            name = parse_bracket(match.group(1))[0]
            obj = self._find(name, both, ["battlefield", "graveyard", "exile", "stack"])
            if obj is None:
                obj = self._ensure_battlefield(seat, name)
            return self._move(obj, "hand", "bounce")

        match = _SOURCE_RETURNED_RE.match(body)
        if match and parse_bracket(match.group(2))[0] in self._returning_to_battlefield:
            return self._return_to_battlefield(seat, parse_bracket(match.group(2))[0])
        if match:
            name = parse_bracket(match.group(2))[0]
            owner = self.player_seat if match.group(3) == "your" else self.opponent_seat
            obj = self._find(
                name, [owner, self._other(owner)], ["battlefield", "graveyard", "exile", "stack"]
            )
            if obj is None:
                obj = self._ensure_battlefield(owner, name)
            return self._move(obj, "hand", "bounce")

        match = _PUT_BATTLEFIELD_RE.match(body)
        if match:
            name, types, _p, _t = parse_bracket(match.group(1))
            return self._put_onto_battlefield(seat, name, types)

        match = _PUT_HAND_RE.match(body)
        if match:
            name = parse_bracket(match.group(2))[0]
            owner = self.player_seat if match.group(3) == "your" else self.opponent_seat
            obj = self._find(name, [owner], ["graveyard", "exile"])
            inferred = False
            if obj is None:
                obj = self._from_library(owner, name)
            if obj is None:
                obj, inferred = self._limbo(owner, name), True
            obj.card = self._card(name, token=obj.token)
            return self._move(obj, "hand", "put", inferred=inferred)
        return None

    def _put_onto_battlefield(
        self, seat: int, name: str, types: Sequence[str] = ()
    ) -> Dict[str, Any]:
        """Source zone for "put [X] onto battlefield".

        Exile first (flicker), then: lands come from the library (fetches and
        ramp far outnumber land recursion), other cards from the graveyard
        (reanimation) or the hand before the library.
        """
        front = self._transform_source(seat, name)
        if front is not None:
            self._transform(front, name, types)
            return self._move(front, "battlefield", "put", seat=seat)
        known = self._known_card_name(seat, name)
        is_land = "Land" in types or self._primary_type(name) == "Land"
        obj = self._find(name, [seat], ["exile", "command"])
        if obj is None and is_land and known:
            obj = self._from_library(seat, name)
        if obj is None:
            obj = self._find(name, [seat], ["graveyard", "hand"])
        if obj is None and known and not is_land:
            obj = self._from_library(seat, name)
        inferred = False
        reason = "put"
        if obj is None:
            token = not known
            obj, inferred = self._limbo(seat, name, token=token), True
            reason = "token_create" if token else "put"
        if types:
            obj.card = self._card(name, types, token=obj.token)
        return self._move(obj, "battlefield", reason, inferred=inferred, seat=seat)

    def _return_to_battlefield(self, seat: int, name: str) -> Dict[str, Any]:
        """A card returned to the battlefield (from the graveyard, usually). The
        text shows it arriving, so it is not inferred even when the replay never
        saw it reach the graveyard (an unlogged surveil or mill)."""
        self._returning_to_battlefield.discard(name)
        both = [seat, self._other(seat)]
        obj = self._find(name, both, ["graveyard", "exile", "hand", "stack", "command"])
        if obj is None:
            obj = self._find(name, both, ["battlefield"])
            if obj is not None:
                return self.log.emit("note")
            obj = self._limbo(seat, name, token=not self._known_card_name(seat, name))
            obj.card = self._card(name, token=obj.token)
        return self._move(obj, "battlefield", "put", seat=obj.owner)

    def _transform(self, obj: _Obj, name: str, types: Sequence[str] = ()) -> None:
        """Turns ``obj`` to its other face ``name`` (the same card, never a token)."""
        obj.add_alias(name)
        obj.name = name
        obj.card = self._card(name, types, token=obj.token)
        self.log.emit("identity", obj=obj.oid, card=obj.card, face_down=False)

    def _primary_type(self, name: str) -> Optional[str]:
        row = self.card_rows.get(name) or {}
        deck = self.deck_info.get(name) or {}
        return row.get("primary_type") or deck.get("type_category")

    def _on_attack(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        swap = _SWAP_RE.match(body)
        if swap:
            seat = self._seat_for(actor, row)
            if seat is None:
                return None
            returned = parse_bracket(swap.group(1))[0]
            obj = self._find(returned, [seat], ["battlefield"])
            if obj is not None:
                self._move(obj, "hand", "bounce")
            put_name = parse_bracket(swap.group(2))[0]
            entering, inferred = self._from_hand_or_elsewhere(seat, put_name, (), ["graveyard"])
            self._move(entering, "battlefield", "put", inferred=inferred, seat=seat)
            self.attacking.add(entering.oid)
            return self.log.emit(
                "attack",
                seat=seat,
                objs=[entering.oid],
                target_seat=self._other(seat),
                target_obj=None,
            )
        match = _ATTACK_RE.match(body)
        if not match:
            return None
        seat = self.player_seat if match.group(1) == "You" else self.opponent_seat
        defender = self._other(seat)
        target_name = parse_bracket(match.group(2))[0]
        target_obj = None
        if target_name.casefold() not in _PLAYER_TARGETS:
            found = self._find(target_name, [defender], ["battlefield"])
            target_obj = found.oid if found else None
        name, types, power, toughness = parse_bracket(match.group(3))
        attacker = self._find(name, [seat], ["battlefield"], exclude=self.attacking)
        if attacker is None:
            token = not self._known_card_name(seat, name)
            attacker = self._limbo(seat, name, token=token)
            attacker.card = self._card(name, types or ["Creature"], power, toughness, token=token)
            self._move(
                attacker,
                "battlefield",
                "token_create" if token else "put",
                inferred=True,
                seat=seat,
            )
        self._update_pt(attacker, power, toughness)
        self.attacking.add(attacker.oid)
        return self.log.emit(
            "attack",
            seat=seat,
            objs=[attacker.oid],
            target_seat=None if target_obj else defender,
            target_obj=target_obj,
        )

    def _combat_pair(
        self, source_content: str, target_content: str, side: str, amount: int, combat: bool
    ) -> Dict[str, Any]:
        target_seat = self.player_seat if side == "your" else self.opponent_seat
        source_name, _st, source_power, source_toughness = parse_bracket(source_content)
        target_name, _tt, target_power, target_toughness = parse_bracket(target_content)
        target = self._ensure_battlefield(target_seat, target_name, search_other=False)
        source = self._find(source_name, [self._other(target_seat), target_seat], ["battlefield"])
        if source is None:
            source = self._ensure_battlefield(self._other(target_seat), source_name)
        self._update_pt(source, source_power, source_toughness)
        self._update_pt(target, target_power, target_toughness)
        if combat and source.controller != target.controller:
            self._infer_block(source, target)
        return self.log.emit(
            "damage",
            source=source.oid,
            target_obj=target.oid,
            target_seat=None,
            amount=amount,
            combat=combat,
        )

    def _infer_block(self, source: _Obj, target: _Obj) -> None:
        if source.oid in self.attacking and target.oid not in self.attacking:
            blocker, attacker = target, source
        elif target.oid in self.attacking and source.oid not in self.attacking:
            blocker, attacker = source, target
        else:
            return
        if (blocker.oid, attacker.oid) in self.blocks:
            return
        self.blocks.add((blocker.oid, attacker.oid))
        self.log.emit(
            "block",
            seat=blocker.controller,
            pairs=[{"blocker": blocker.oid, "attacker": attacker.oid}],
        )

    def _on_combat_damage(
        self, index: int, row: Dict[str, Any], text: str
    ) -> Optional[Dict[str, Any]]:
        body = _TS_RE.sub("", text, count=1).strip()
        match = _DEALT_RE.match(body)
        if match:
            return self._combat_pair(
                match.group(1), match.group(3), match.group(4), int(match.group(2)), True
            )
        match = _ARROW_RE.match(body)
        if match:
            source = match.group(1).strip().strip("[]")
            target = match.group(2).strip().strip("[]")
            return self._combat_pair(source, target, match.group(3), int(match.group(4)), True)
        return self._took_damage(body, combat=True)

    def _on_damage(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        body = _TS_RE.sub("", text, count=1).strip()
        return self._took_damage(body, combat=False)

    def _took_damage(self, body: str, combat: bool) -> Optional[Dict[str, Any]]:
        match = _TOOK_RE.match(body)
        if not match:
            return None
        seat = self.player_seat if match.group(2) == "your" else self.opponent_seat
        name, _types, power, toughness = parse_bracket(match.group(1))
        # Several same-named permanents hit at once (three Knight tokens) take one line each.
        moment = (self.log.turn, self._row_stamp or self._row_elapsed)
        if self._damage_moment[0] != moment:
            self._damage_moment = (moment, set())
        hit = self._damage_moment[1]
        target = self._find(name, [seat], ["battlefield"], exclude=hit)
        if target is None:
            target = self._ensure_battlefield(seat, name, search_other=False)
        hit.add(target.oid)
        self._update_pt(target, power, toughness)
        return self.log.emit(
            "damage",
            source=None,
            target_obj=target.oid,
            target_seat=None,
            amount=int(match.group(3)),
            combat=combat,
        )

    def _on_life(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        match = _LIFE_RE.match(body)
        if seat is None or not match:
            return None
        amount = int(match.group(2)) * (1 if match.group(1) == "gained" else -1)
        column = "player_life" if seat == self.player_seat else "opponent_life"
        total = _to_int(row.get(column))
        if total is None:
            total = int(match.group(4))
        source_obj = None
        if match.group(3):
            found = self._find(parse_bracket(match.group(3))[0], list(self.seats), ["battlefield"])
            source_obj = found.oid if found else None
        self.life[seat] = total
        return self.log.emit("life", seat=seat, life=total, delta=amount, source_obj=source_obj)

    _on_life_gain = _on_life
    _on_life_loss = _on_life

    def _on_scry(self, index: int, row: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        actor, body = _split_actor(text)
        seat = self._seat_for(actor, row)
        match = _SCRY_RE.match(body)
        if seat is None or not match:
            return None
        looked = int(match.group(1))
        detail = match.group(2) or ""
        top: List[str] = []
        bottom: List[str] = []
        if seat == self.player_seat:
            used: Set[str] = set()
            for clause in re.split(r",\s*(?=kept|bottomed)", detail):
                names = _bracket_names(clause)
                target = top if clause.strip().startswith("kept") else bottom
                for name in names:
                    obj = self._find(name, [seat], ["library"], exclude=used)
                    if obj is None and self.pool[seat][name] > 0:
                        obj = self._from_library(seat, name)
                    if obj is not None:
                        used.add(obj.oid)
                        target.append(obj.oid)
        return self.log.emit("scry", seat=seat, top=top, bottom=bottom, looked=looked)

    # -- finish ----------------------------------------------------------

    def _finish(self) -> None:
        self.log.row_id = None
        self._close_all_open()
        for seat_key, participant in self.participants.items():
            seat = self.player_seat if seat_key == "player" else self.opponent_seat
            ending = _to_int(participant.get("ending_life"))
            if ending is not None and ending != self.life.get(seat):
                self.log.emit(
                    "life",
                    seat=seat,
                    life=ending,
                    delta=ending - self.life.get(seat, 0),
                    source_obj=None,
                )
                self.life[seat] = ending
        game = self.stream["game"]
        self.log.emit(
            "game_end", winner_seat=game.get("winner_seat"), reason=game.get("outcome_reason")
        )
        finalize_logs(self.log.events, self.cards)
        events = estimate_summoning_sickness(
            self.log.events, self.cards.cards, self.rows.get("card_facts")
        )
        if events is not self.log.events:
            self.stream["limitations"].append(SICKNESS_ESTIMATE_LIMITATION)
        self.stream["events"] = events
        self.stream["turns"] = build_turns(events, self.rows.get("game_turns") or [])
        self.stream["cards"] = self.cards.cards
        self._seat_colors()

    def _seat_colors(self) -> None:
        for seat_key, info in self.stream["seats"].items():
            seat = int(seat_key)
            names: List[str] = list(info.get("commanders") or [])
            if not names:
                if seat == self.player_seat and self.deck_names[seat]:
                    names = sorted(self.deck_names[seat])
                else:
                    names = sorted(
                        {obj.name for obj in self.objs.values() if obj.owner == seat and obj.name}
                    )
            info["colors"] = seat_colors(self.card_rows.get(name) for name in names)


def reconstruct(rows: Dict[str, Any]) -> Dict[str, Any]:
    """Build a ``fidelity: reconstructed`` stream from one game's rows."""
    return Reconstructor(rows).run()
