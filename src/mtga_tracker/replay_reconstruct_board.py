"""Board model for the replay reconstructor: objects, zones and the stack.

``ReconstructionBoard`` owns the synthetic ``r:<n>`` objects, per-seat zone
lists, library counts, the card registry lookups and the stack items, plus
the opening setup (``game_start``, opening hands, commanders, mulligans).
``replay_reconstruct.Reconstructor`` adds the per-row grammar handlers.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .replay_reconstruct_grammar import (
    GRAVEYARD_CAST_KEYWORDS,
    _ARTIFACT_TOKENS,
    _BRACKET_RE,
    _PLAYER_TARGETS,
    _TRIGGER_HINT_RE,
    _to_int,
    parse_bracket,
)
from .replay_stream import (
    FIDELITY_RECONSTRUCTED,
    ZONES,
    CardRegistry,
    EventLog,
    is_unknown_card_name,
    primary_type_from_text,
    stream_header,
)


class _Obj:
    __slots__ = ("oid", "owner", "controller", "zone", "name", "aliases", "token", "card", "pt")

    def __init__(self, oid: str, owner: int, zone: str, name: Optional[str], token: bool) -> None:
        self.oid = oid
        self.owner = owner
        self.controller = owner
        self.zone = zone
        self.name = name
        self.aliases: Set[str] = set()
        self.token = token
        self.card: Optional[str] = None
        self.pt: Optional[Tuple[str, str]] = None
        if name:
            self.add_alias(name)

    def add_alias(self, name: str) -> None:
        self.aliases.add(name)
        if " // " in name:
            self.aliases.update(part.strip() for part in name.split(" // ") if part.strip())


class _StackItem:
    __slots__ = ("sid", "oid", "name", "ability", "types", "seat", "open", "creates")

    def __init__(self, sid, oid, name, ability, types, seat) -> None:
        self.sid = sid
        self.oid = oid
        self.name = name
        self.ability = ability
        self.types = types
        self.seat = seat
        self.open = True
        #: Tokens the ability's text creates on resolution (grammar.created_tokens).
        self.creates: List[Tuple[str, int, Optional[str], Optional[str], List[str]]] = []


class ReconstructionBoard:
    """Board state shared by the reconstructor's row handlers."""

    def __init__(self, rows: Dict[str, Any]) -> None:
        self.rows = rows
        self.stream = stream_header(rows, FIDELITY_RECONSTRUCTED)
        self.player_seat: int = self.stream["player_seat"]
        self.opponent_seat: int = next(
            int(seat) for seat in self.stream["seats"] if int(seat) != self.player_seat
        )
        self.seats = (self.player_seat, self.opponent_seat)
        self.log = EventLog()
        self.cards = CardRegistry()
        self.objs: Dict[str, _Obj] = {}
        self.zones: Dict[int, Dict[str, List[str]]] = {
            seat: {zone: [] for zone in ZONES} for seat in self.seats
        }
        self.library_count: Dict[int, int] = {seat: 0 for seat in self.seats}
        self.pool: Dict[int, Counter] = {seat: Counter() for seat in self.seats}
        self.deck_names: Dict[int, Set[str]] = {seat: set() for seat in self.seats}
        self.life: Dict[int, int] = {
            int(seat): int(info.get("starting_life") or 20)
            for seat, info in self.stream["seats"].items()
        }
        self.attacking: Set[str] = set()
        self.blocks: Set[Tuple[str, str]] = set()
        self.items: Dict[int, _StackItem] = {}
        self.open_items: List[_StackItem] = []
        self._next_obj = 0
        self._next_stack = 0
        self._phase_seen: Optional[str] = None
        self._pending_close: Optional[_StackItem] = None
        self.participants = {str(row.get("role")): row for row in rows.get("participants") or []}
        self._index_cards()
        #: Arena card facts by casefolded name (CardDatabase.replay_card_facts).
        self.card_facts: Dict[str, Dict[str, Any]] = rows.get("card_facts") or {}

    # -- card metadata ---------------------------------------------------

    def _index_cards(self) -> None:
        self.card_rows: Dict[str, Dict[str, Any]] = {}
        for row in self.rows.get("cards") or []:
            name = row.get("name")
            if not name:
                continue
            self.card_rows.setdefault(str(name), row)
            if " // " in str(name):
                for part in str(name).split(" // "):
                    self.card_rows.setdefault(part.strip(), row)
        self.deck_info: Dict[str, Dict[str, Any]] = {}
        player_id = (self.participants.get("player") or {}).get("id")
        for row in self.rows.get("game_deck_cards") or []:
            name = row.get("display_name")
            if not name:
                continue
            self.deck_info.setdefault(str(name), row)
            if row.get("participant_id") == player_id and row.get("deck_zone") == "deck":
                self.deck_names[self.player_seat].add(str(name))

    def _card(
        self,
        name: Optional[str],
        types: Sequence[str] = (),
        power: Optional[str] = None,
        toughness: Optional[str] = None,
        token: bool = False,
    ) -> str:
        if is_unknown_card_name(name):
            return self.cards.add(None)
        row = self.card_rows.get(str(name)) or {}
        deck = self.deck_info.get(str(name)) or {}
        # Arena's card DB describes a real card the game's rows never did.
        fact = {} if token else self._fact(name)
        arena_id = row.get("arena_id") or deck.get("arena_id")
        bracket_type = ", ".join(types) if types else None
        return self.cards.add(
            name,
            arena_id,
            type_line=row.get("type_line") or fact.get("type_line"),
            primary_type=row.get("primary_type")
            or (deck.get("type_category") if deck.get("type_category") != "Other" else None)
            or primary_type_from_text(fact.get("type_line"))
            or primary_type_from_text(bracket_type),
            power=next(
                (v for v in (row.get("power"), fact.get("power"), power) if v not in (None, "")),
                None,
            ),
            toughness=next(
                (
                    v
                    for v in (row.get("toughness"), fact.get("toughness"), toughness)
                    if v not in (None, "")
                ),
                None,
            ),
            mana_cost=row.get("mana_cost"),
            color_identity=row.get("color_identity"),
            is_token=token,
        )

    def _fact(self, name: Optional[str]) -> Dict[str, Any]:
        return self.card_facts.get(str(name or "").casefold()) or {}

    def _alternate_source(self, seat: int, name: str) -> Optional[_Obj]:
        """A card cast from where its own keyword allows, before the hidden hand:
        the graveyard for flashback and kin, exile once plotted. A copy known
        to be in the hand still wins."""
        keywords = set(self._fact(name).get("keywords") or ())
        zones = []
        if keywords & GRAVEYARD_CAST_KEYWORDS:
            zones.append("graveyard")
        if "plot" in keywords:
            zones.append("exile")
        if not zones or self._find(name, [seat], ["hand"]) is not None:
            return None
        return self._find(name, [seat], zones)

    def _transform_source(self, seat: int, name: str) -> Optional[_Obj]:
        """The front face a back face named ``name`` came from (Esper Origins
        exiled, then put onto the battlefield as Summon: Esper Maduin)."""
        front = self._fact(name).get("front")
        if not front:
            return None
        return self._find(front, [seat], ["exile", "stack", "graveyard", "battlefield", "hand"])

    def _known_card_name(self, seat: int, name: str) -> bool:
        """True when ``name`` is a real card (not a token) for this seat, as far as we know."""
        if seat == self.player_seat and self.deck_names[seat]:
            return name in self.deck_names[seat]
        # Arena's card DB lists every real (non-token) card name.
        return name in self.card_rows or name in self.deck_info or bool(self._fact(name))

    # -- object helpers --------------------------------------------------

    def _seat_for(self, actor: Optional[str], row: Dict[str, Any]) -> Optional[int]:
        if actor == "You":
            return self.player_seat
        if actor == "Opponent":
            return self.opponent_seat
        role = row.get("actor_role")
        if role == "player":
            return self.player_seat
        if role == "opponent":
            return self.opponent_seat
        return None

    def _other(self, seat: int) -> int:
        return self.opponent_seat if seat == self.player_seat else self.player_seat

    def _new(self, seat: int, zone: str, name: Optional[str], token: bool = False) -> _Obj:
        self._next_obj += 1
        obj = _Obj(f"r:{self._next_obj}", seat, zone, name, token)
        if name:
            obj.card = self._card(name, token=token)
        self.objs[obj.oid] = obj
        self.zones[seat][zone].append(obj.oid)
        return obj

    def _find(
        self,
        name: str,
        seats: Sequence[int],
        zones: Sequence[str],
        exclude: Optional[Set[str]] = None,
    ) -> Optional[_Obj]:
        for zone in zones:
            for seat in seats:
                for oid in self.zones[seat][zone]:
                    obj = self.objs[oid]
                    if name in obj.aliases and (not exclude or oid not in exclude):
                        return obj
        return None

    def _reveal(self, obj: _Obj, name: Optional[str], types: Sequence[str] = ()) -> None:
        if not name:
            return
        if obj.name is None:
            obj.name = name
            obj.add_alias(name)
            if obj.owner == self.player_seat and self.pool[obj.owner][name] > 0:
                self.pool[obj.owner][name] -= 1
        if obj.card is None or types:
            obj.card = self._card(obj.name, types, token=obj.token)

    def _move(
        self,
        obj: _Obj,
        dest: str,
        reason: str,
        inferred: bool = False,
        seat: Optional[int] = None,
        chosen: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = obj.zone
        holder = obj.controller
        if obj.oid in self.zones[holder][source]:
            self.zones[holder][source].remove(obj.oid)
        if source == "library":
            self.library_count[obj.owner] -= 1
        if dest == "library":
            self.library_count[obj.owner] += 1
        if dest == "battlefield" and seat is not None:
            obj.controller = seat
        elif dest != "battlefield" and dest != "stack":
            obj.controller = obj.owner
        obj.zone = dest
        self.zones[obj.controller][dest].append(obj.oid)
        if dest != "battlefield":
            self.attacking.discard(obj.oid)
        event = self.log.emit(
            "move",
            obj=obj.oid,
            card=obj.card,
            **{"from": source, "to": dest},
            owner=obj.owner,
            controller=obj.controller,
            reason=reason,
            inferred=inferred,
            index=None,
            chosen=chosen,
        )
        if obj.token and dest in ("graveyard", "exile", "hand", "library"):
            self._move(obj, "limbo", "token_cease")
        return event

    def _limbo(self, seat: int, name: Optional[str], token: bool = False) -> _Obj:
        """An object the text never showed arriving: created in limbo, inferred."""
        return self._new(seat, "limbo", name, token=token)

    def _from_hand(
        self, seat: int, name: Optional[str], types: Sequence[str] = ()
    ) -> Optional[_Obj]:
        hand = self.zones[seat]["hand"]
        if name:
            obj = self._find(name, [seat], ["hand"])
            if obj is not None:
                self._reveal(obj, name, types)
                return obj
        for oid in hand:
            obj = self.objs[oid]
            if obj.name is None:
                self._reveal(obj, name, types)
                return obj
        return None

    def _from_library(self, seat: int, name: Optional[str]) -> Optional[_Obj]:
        if name:
            obj = self._find(name, [seat], ["library"])
            if obj is not None:
                return obj
        if self.library_count[seat] - len(self.zones[seat]["library"]) <= 0:
            return None
        if name and seat == self.player_seat and self.pool[seat][name] > 0:
            self.pool[seat][name] -= 1
        obj = self._new(seat, "library", name)
        return obj

    def _ensure_battlefield(
        self,
        seat: int,
        name: str,
        types: Sequence[str] = (),
        exclude: Optional[Set[str]] = None,
        search_other: bool = True,
    ) -> _Obj:
        seats = [seat, self._other(seat)] if search_other else [seat]
        obj = self._find(name, seats, ["battlefield"], exclude)
        if obj is not None:
            return obj
        token = not self._known_card_name(seat, name)
        obj = self._limbo(seat, name, token=token)
        if not types and token:
            types = ["Artifact"] if name in _ARTIFACT_TOKENS else ["Creature"]
        if types:
            obj.card = self._card(name, types, token=token)
        self._move(obj, "battlefield", "token_create" if token else "put", inferred=True, seat=seat)
        return obj

    def _update_pt(self, obj: _Obj, power: Optional[str], toughness: Optional[str]) -> None:
        if obj.zone != "battlefield" or power is None or toughness is None:
            return
        if not (power.lstrip("-").isdigit() and toughness.lstrip("-").isdigit()):
            return
        value = (power, toughness)
        if obj.pt == value:
            return
        if obj.pt is None and obj.card:
            card = self.cards.cards.get(obj.card) or {}
            if (str(card.get("power")), str(card.get("toughness"))) == value:
                obj.pt = value
                return
        obj.pt = value
        self.log.emit("pt", obj=obj.oid, power=int(power), toughness=int(toughness))

    def _targets(self, text: str, caster: int) -> List[str]:
        targets: List[str] = []
        for content in _BRACKET_RE.findall(text):
            name = parse_bracket(content)[0]
            if name.casefold() in _PLAYER_TARGETS or name.startswith("ID:"):
                continue
            obj = self._find(
                name,
                [self._other(caster), caster],
                ["battlefield", "stack", "graveyard", "exile"],
                exclude=set(targets),
            )
            if obj is not None:
                targets.append(obj.oid)
        return targets

    # -- stack -----------------------------------------------------------

    def _push(
        self,
        row_index: int,
        seat: int,
        obj: Optional[_Obj],
        name: str,
        ability: bool,
        types: Sequence[str],
        text: str,
        targets: List[str],
    ) -> Dict[str, Any]:
        self._next_stack += 1
        item = _StackItem(
            f"s{self._next_stack}", obj.oid if obj else None, name, ability, list(types), seat
        )
        self.items[row_index] = item
        self.open_items.append(item)
        if ability:
            stack_kind = (
                "trigger" if _TRIGGER_HINT_RE.search(text) or ":" not in text else "activated"
            )
            card = obj.card if obj and obj.card else self._card(name)
        else:
            stack_kind = "spell"
            card = obj.card if obj else None
        return self.log.emit(
            "stack_push",
            stack_id=item.sid,
            obj=item.oid,
            card=card,
            stack_kind=stack_kind,
            controller=seat,
            text=text,
            targets=targets,
        )

    def _close(self, item: _StackItem, kind: str, types: Sequence[str] = ()) -> Dict[str, Any]:
        item.open = False
        if item in self.open_items:
            self.open_items.remove(item)
        event = self.log.emit(kind, stack_id=item.sid)
        obj = self.objs.get(item.oid) if item.oid else None
        if item.ability and kind == "stack_resolve":
            for name, count, power, toughness, types in item.creates:
                if not types:
                    types = ["Artifact"] if name in _ARTIFACT_TOKENS else ["Creature"]
                for _ in range(count):
                    token = self._limbo(item.seat, name, token=True)
                    token.card = self._card(name, types, power, toughness, token=True)
                    self._move(token, "battlefield", "token_create", seat=item.seat)
        if item.ability or obj is None or obj.zone != "stack":
            return event
        if kind == "stack_resolve":
            card_types = list(types) or item.types
            primary = primary_type_from_text(", ".join(card_types)) if card_types else None
            if primary is None and obj.card:
                primary = (self.cards.cards.get(obj.card) or {}).get("primary_type")
            dest = "graveyard" if primary in ("Instant", "Sorcery") else "battlefield"
            self._move(obj, dest, "resolve", seat=item.seat)
        else:
            self._move(obj, "graveyard", "counter" if kind == "stack_countered" else "unknown")
        return event

    def _close_all_open(self) -> None:
        for item in list(reversed(self.open_items)):
            self._close(item, "stack_resolve")

    # -- setup -----------------------------------------------------------

    def _setup(self) -> None:
        rows = self.rows
        player = self.participants.get("player") or {}
        opponent = self.participants.get("opponent") or {}
        commanders: Dict[int, List[str]] = {seat: [] for seat in self.seats}
        for seat_key, info in self.stream["seats"].items():
            commanders[int(seat_key)] = list(info.get("commanders") or [])
        fmt = str(self.stream["game"].get("format") or "")

        hand_names = [
            str(row.get("display_name"))
            for row in sorted(
                (
                    row
                    for row in rows.get("game_opening_hand_cards") or []
                    if row.get("participant_id") == player.get("id")
                ),
                key=lambda row: (row.get("hand_position") or 0, row.get("copy_number") or 0),
            )
            if row.get("display_name")
        ]
        player_mulligans = _to_int(player.get("mulligans")) or 0
        opponent_mulligans = _to_int(opponent.get("mulligans")) or 0
        if hand_names:
            player_hand: List[Optional[str]] = list(hand_names)
        else:
            size = _to_int(player.get("opening_hand_size")) or max(0, 7 - player_mulligans)
            player_hand = [None] * size
        opponent_hand: List[Optional[str]] = [None] * max(0, 7 - opponent_mulligans)

        deck_total = 0
        for row in rows.get("game_deck_cards") or []:
            if row.get("participant_id") == player.get("id") and row.get("deck_zone") == "deck":
                quantity = _to_int(row.get("quantity")) or 0
                deck_total += quantity
                self.pool[self.player_seat][str(row.get("display_name"))] += quantity
        if deck_total <= 0:
            deck_total = self._deck_size(player, commanders[self.player_seat], fmt)
        opponent_total = self._deck_size(opponent, commanders[self.opponent_seat], fmt)
        for name in player_hand:
            if name and self.pool[self.player_seat][name] > 0:
                self.pool[self.player_seat][name] -= 1

        hands = {self.player_seat: player_hand, self.opponent_seat: opponent_hand}
        self.library_count = {
            self.player_seat: max(0, deck_total - len(player_hand)),
            self.opponent_seat: max(0, opponent_total - len(opponent_hand)),
        }
        self.log.emit(
            "game_start",
            seats_hand_sizes={str(seat): len(hands[seat]) for seat in sorted(self.seats)},
            library_sizes={str(seat): self.library_count[seat] for seat in sorted(self.seats)},
        )
        # Opening hand: library -> hand draws. game_start's library sizes
        # already exclude these cards, so they do not touch library_count.
        for seat in sorted(self.seats):
            for name in hands[seat]:
                obj = self._new(seat, "library", name)
                self.zones[seat]["library"].remove(obj.oid)
                obj.zone = "hand"
                self.zones[seat]["hand"].append(obj.oid)
                self.log.emit(
                    "move",
                    obj=obj.oid,
                    card=obj.card,
                    **{"from": "library", "to": "hand"},
                    owner=seat,
                    controller=seat,
                    reason="draw",
                    inferred=False,
                    index=None,
                )
        for seat in sorted(self.seats):
            for name in commanders[seat]:
                obj = self._limbo(seat, name)
                self._move(obj, "command", "put")
        mulligan_sizes = {
            self.player_seat: player_mulligans,
            self.opponent_seat: opponent_mulligans,
        }
        for seat in sorted(self.seats):
            if mulligan_sizes[seat] > 0:
                self.log.emit(
                    "mulligan",
                    seat=seat,
                    from_size=7,
                    to_size=len(hands[seat]),
                    bottomed=[],
                )

    @staticmethod
    def _deck_size(participant: Dict[str, Any], commanders: List[str], fmt: str) -> int:
        size = _to_int(participant.get("deck_size"))
        if not size:
            size = 100 if "Brawl" in fmt and "Standard" not in fmt else 60
        if commanders and size in (60, 100):
            size -= len(commanders)
        return size
