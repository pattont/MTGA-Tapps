"""Replay capture: structured ``game_events`` facts for ``replay_version = 1``.

The tracker mixins that already understand an event build a :class:`ReplayFact`
and hand it to ``_print_event`` (printed rows) or ``_record_silent_event``
(replay-only rows the console never shows). This module owns the fact type,
zone/reason normalization, per-game capture state (stack ids, tapped set, P/T,
counter totals) and the per-message row buffer: every row written while a GRE
message is processed goes to SQLite in ONE transaction at the end of it.

Contract: docs/REPLAY_FORMAT.md section 1. Nothing here parses a message a
second time; callers pass what they already have in hand.
"""

from __future__ import annotations

import functools
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar

REPLAY_VERSION = 1

_F = TypeVar("_F", bound=Callable[..., Any])


def replay_safe(default: Any = None) -> Callable[[_F], _F]:
    """Make a capture hook exception-safe: replay must never break tracking.

    A failing hook returns ``default`` and leaves one diagnostic line per hook
    name and session in the unhandled-annotation text log.
    """

    def decorate(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - capture is best effort
                _report_capture_failure(self, func.__name__, exc)
                return default

        return wrapper  # type: ignore[return-value]

    return decorate


def _report_capture_failure(tracker: Any, hook: str, exc: BaseException) -> None:
    try:
        reported = tracker.__dict__.setdefault("_replay_failures_reported", set())
        if hook in reported:
            return
        reported.add(hook)
        path = getattr(tracker, "_diagnostic_text_path", None)
        if path is None:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                f"{datetime.now().isoformat()} Replay capture: {hook} failed: "
                f"{type(exc).__name__}: {str(exc)[:300]}\n"
            )
    except Exception:  # noqa: BLE001 - diagnostics are best effort too
        return


_ZONE_NAMES = {
    "ZoneType_Library": "library",
    "ZoneType_Hand": "hand",
    "ZoneType_Battlefield": "battlefield",
    "ZoneType_Graveyard": "graveyard",
    "ZoneType_Exile": "exile",
    "ZoneType_Stack": "stack",
    "ZoneType_Command": "command",
}

# Arena's fixed zone ids, used only when a message does not describe a zone
# the tracker has never seen described (Arena keeps these ids stable).
_DEFAULT_ZONE_IDS = {
    26: "command",
    27: "stack",
    28: "battlefield",
    29: "exile",
}

_REASON_BY_CATEGORY = {
    "Draw": "draw",
    "PlayLand": "play_land",
    "CastSpell": "cast",
    "PlaySpell": "cast",
    "Resolve": "resolve",
    "Destroy": "destroy",
    "Exile": "exile",
    "Sacrifice": "sacrifice",
    "Discard": "discard",
    "Mill": "mill",
    "Put": "put",
    "Countered": "counter",
}

# Moves that are a card's own action, or a state-based death the viewer
# attributes from the damage that caused it: no ``by`` source is recorded.
_UNSOURCED_MOVES = frozenset({"draw", "play_land", "cast", "resolve", "sba"})

# Printed styles a zone-transfer line may carry for each move reason. The move
# fact attaches to the first matching printed row its handler wrote; turn
# headers or flushed cast lines written inside the same handler never match.
_ACCEPT_STYLES = {
    "draw": ("draw",),
    "play_land": ("land",),
    "resolve": ("cast",),
    "destroy": ("zone",),
    "exile": ("zone",),
    "sacrifice": ("zone",),
    "discard": ("zone",),
    "mill": ("zone",),
    "bounce": ("zone",),
    "put": ("zone", "attack"),
    "counter": ("counter",),
    "sba": ("zone",),
}

COUNTER_TYPE_NAMES = {1: "+1/+1", 2: "-1/-1", 7: "loyalty"}

_EVENT_COLUMNS = (
    "session_id, match_id, game_id, event_time, elapsed_seconds, turn_number, phase, step, "
    "participant_id, seat_id, actor_role, event_type, event_subtype, text, amount, zone_from, "
    "zone_to, player_life, opponent_life, payload_json, object_id, target_object_id, arena_id, "
    "controller_seat, visible"
)
INSERT_EVENT_SQL = (
    f"INSERT INTO game_events ({_EVENT_COLUMNS}) VALUES (" + ", ".join("?" for _ in range(25)) + ")"
)


class ReplayFact:
    """One replay fact: the structured columns of a ``game_events`` row."""

    __slots__ = (
        "kind",
        "object_id",
        "target_object_id",
        "arena_id",
        "controller_seat",
        "seat_id",
        "zone_from",
        "zone_to",
        "amount",
        "payload",
    )

    def __init__(
        self,
        kind: str,
        *,
        object_id: Optional[int] = None,
        target_object_id: Optional[int] = None,
        arena_id: Optional[int] = None,
        controller_seat: Optional[int] = None,
        seat_id: Optional[int] = None,
        zone_from: Optional[str] = None,
        zone_to: Optional[str] = None,
        amount: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        self.kind = kind
        self.object_id = object_id
        self.target_object_id = target_object_id
        self.arena_id = arena_id
        self.controller_seat = controller_seat
        self.seat_id = seat_id
        self.zone_from = zone_from
        self.zone_to = zone_to
        self.amount = amount
        self.payload = payload

    def machine_text(self) -> str:
        """Short text for a silent row (never a console sentence)."""
        if self.object_id is not None:
            return f"{self.kind} {self.object_id}"
        if self.seat_id is not None:
            return f"{self.kind} seat {self.seat_id}"
        return self.kind

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        fields = ", ".join(
            f"{name}={getattr(self, name)!r}"
            for name in self.__slots__
            if getattr(self, name) is not None
        )
        return f"ReplayFact({fields})"


class PendingEventRow:
    """A ``game_events`` row waiting in the per-message buffer."""

    __slots__ = ("base", "text", "style", "fact", "visible", "inferred_seat")

    def __init__(
        self,
        base: tuple,
        text: str,
        style: Optional[str],
        fact: Optional[ReplayFact],
        visible: int,
        inferred_seat: Optional[int],
    ):
        # base: session_id, match_id, game_id, event_time, elapsed_seconds,
        # turn_number, phase, step, participant_id, actor_role,
        # player_life, opponent_life
        self.base = base
        self.text = text
        self.style = style
        self.fact = fact
        self.visible = visible
        self.inferred_seat = inferred_seat

    def values(self) -> tuple:
        (
            session_id,
            match_id,
            game_id,
            event_time,
            elapsed_seconds,
            turn_number,
            phase,
            step,
            participant_id,
            actor_role,
            player_life,
            opponent_life,
        ) = self.base
        fact = self.fact
        if fact is None:
            return (
                session_id,
                match_id,
                game_id,
                event_time,
                elapsed_seconds,
                turn_number,
                phase,
                step,
                participant_id,
                self.inferred_seat,
                actor_role,
                self.style,
                "note" if self.visible else None,
                self.text,
                None,
                None,
                None,
                player_life,
                opponent_life,
                None,
                None,
                None,
                None,
                None,
                self.visible,
            )
        payload = fact.payload
        seat_id = fact.seat_id
        if self.inferred_seat is not None:
            # Printed rows keep the seat their text names (unchanged history).
            # A moved card's owner can differ ("[Source] returned [X] to
            # opponent's hand" names the source's seat): keep it in the payload.
            seat_id = self.inferred_seat
            if fact.kind == "move" and fact.seat_id is not None and fact.seat_id != seat_id:
                payload = dict(payload or {}, owner=fact.seat_id)
        return (
            session_id,
            match_id,
            game_id,
            event_time,
            elapsed_seconds,
            turn_number,
            phase,
            step,
            participant_id,
            seat_id,
            actor_role,
            self.style,
            fact.kind,
            self.text,
            fact.amount,
            fact.zone_from,
            fact.zone_to,
            player_life,
            opponent_life,
            (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) if payload else None),
            fact.object_id,
            fact.target_object_id,
            fact.arena_id,
            fact.controller_seat,
            self.visible,
        )


def _safe_row_values(row: PendingEventRow) -> Optional[tuple]:
    """``row.values()``; a printed row whose fact cannot be encoded is kept
    without its replay columns, a broken silent row is dropped."""
    try:
        return row.values()
    except Exception:  # noqa: BLE001 - e.g. a payload json cannot encode
        if not row.visible:
            return None
        row.fact = None
        try:
            return row.values()
        except Exception:  # noqa: BLE001
            return None


class ReplayCaptureState:
    """Per-game capture bookkeeping; reset whenever a new game starts."""

    __slots__ = (
        "game_key",
        "stack_counter",
        "stack_ids",
        "tapped",
        "pt",
        "counters",
        "zone_names",
        "zone_of",
        "hand_ids",
        "hand_arrivals",
        "opening_emitted",
        "mulligans",
        "pending_taps",
        "pending_untaps",
        "pending_pt",
        "user_action_ids",
        "blocks",
        "ambient",
        "latest",
        "pending_phase",
        "observed",
    )

    def __init__(self, game_key: Any):
        self.game_key = game_key
        self.stack_counter = 0
        self.stack_ids: Dict[int, str] = {}
        self.tapped: set = set()
        self.pt: Dict[int, Tuple[int, int]] = {}
        self.counters: Dict[Tuple[int, str], int] = {}
        self.zone_names: Dict[int, str] = {}
        self.zone_of: Dict[int, str] = {}
        self.hand_ids: Dict[int, List[int]] = {}
        self.hand_arrivals: set = set()
        self.opening_emitted = False
        self.mulligans: Dict[int, int] = {}
        self.pending_taps: Dict[int, List[int]] = {}
        self.pending_untaps: Dict[int, List[int]] = {}
        self.pending_pt: Dict[int, Tuple[int, int]] = {}
        self.user_action_ids: set = set()
        self.blocks: set = set()
        self.ambient: Optional[ReplayFact] = None
        # root id -> newest instance id seen (the object's current snapshot)
        self.latest: Dict[int, int] = {}
        # A phase row waits here until something happens in that phase.
        self.pending_phase: Optional["PendingEventRow"] = None
        # (instance id, gameObject) seen this message; diffed at its end.
        self.observed: List[Tuple[int, Dict[str, Any]]] = []

    def allocate_stack_id(self, stack_key: int) -> str:
        self.stack_counter += 1
        stack_id = f"s{self.stack_counter}"
        self.stack_ids[int(stack_key)] = stack_id
        return stack_id


def zone_name_for_type(zone_type: Any) -> str:
    """Normalize an Arena ``ZoneType_*`` to the replay zone vocabulary."""
    return _ZONE_NAMES.get(str(zone_type or ""), "limbo")


def move_reason(category: Optional[str], zone_from: Optional[str]) -> str:
    """Replay move reason for an Arena zone-transfer category."""
    text = str(category or "")
    if text == "Return":
        return "bounce" if zone_from == "battlefield" else "put"
    if text.startswith("SBA_"):
        return "sba"
    return _REASON_BY_CATEGORY.get(text, "unknown")


def counter_type_name(counter_type: Any) -> str:
    """Readable counter type for Arena's numeric ``counter_type``."""
    try:
        number = int(counter_type)
    except (TypeError, ValueError):
        return "counter"
    return COUNTER_TYPE_NAMES.get(number, f"counter_{number}")


def stat_value(obj: Dict[str, Any], key: str) -> Optional[int]:
    """Power/toughness as an int: Arena omits ``value`` when it is 0."""
    raw = obj.get(key)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, dict):
        value = raw.get("value", 0)
        return value if isinstance(value, int) else None
    return None


class ReplayCaptureMixin:
    """Row buffer, silent rows and fact builders shared by the tracker mixins."""

    # -- state ------------------------------------------------------------
    def _replay_state(self) -> ReplayCaptureState:
        game_key = (self.game_state.game_start_time, getattr(self, "session_id", None))
        state = getattr(self, "_replay_capture_state", None)
        if state is None or state.game_key != game_key:
            state = ReplayCaptureState(game_key)
            self._replay_capture_state = state
        return state

    def _replay_capturing(self) -> bool:
        """True when rows for this game will be persisted (same gate as events)."""
        if self.game_state.game_start_time is None or self.game_state.mid_game_attach:
            return False
        return not self._is_untracked_match()

    def _replay_root(self, instance_id: Any) -> Optional[int]:
        if instance_id is None:
            return None
        try:
            return self._canonical_instance_id(int(instance_id))
        except (TypeError, ValueError):
            return None

    def _replay_zone_name(
        self,
        zone_id: Any,
        zones_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Optional[str]:
        if zone_id is None:
            return None
        try:
            key = int(zone_id)
        except (TypeError, ValueError):
            return None
        state = self._replay_state()
        zone = (zones_by_id or {}).get(key)
        if isinstance(zone, dict) and zone.get("type"):
            name = zone_name_for_type(zone.get("type"))
            state.zone_names[key] = name
            return name
        name = state.zone_names.get(key)
        if name is not None:
            return name
        if key == self.game_state.battlefield_zone_id:
            return "battlefield"
        return _DEFAULT_ZONE_IDS.get(key, "limbo")

    @replay_safe()
    def _replay_learn_zones(self, zones_by_id: Dict[int, Dict[str, Any]]) -> None:
        """Remember every described zone's type: a later diff may move a card
        into a zone it does not describe again (a hand, a library)."""
        if not zones_by_id:
            return
        names = self._replay_state().zone_names
        for key, zone in zones_by_id.items():
            if isinstance(zone, dict) and zone.get("type"):
                names[key] = zone_name_for_type(zone.get("type"))

    def _replay_card_payload(
        self, obj: Optional[Dict[str, Any]], payload: Dict[str, Any]
    ) -> Optional[int]:
        """Add name/type/token to a payload; return the visible grpId (or None)."""
        if not isinstance(obj, dict) or not obj:
            return None
        grp_id = obj.get("grpId")
        if obj.get("type") == "GameObjectType_Token":
            payload["token"] = True
        if not isinstance(grp_id, int) or grp_id <= 0:
            return None
        name = self.card_db.get_card_name(grp_id)
        if name and not str(name).startswith("Card #"):
            payload["name"] = str(name)
        card_type = self._get_card_type_category(obj.get("cardTypes") or [])
        if card_type != "Other":
            payload["type"] = card_type
        if "CardType_Creature" in (obj.get("cardTypes") or []):
            # The stream's card entry takes its printed stats from the first
            # row that names them, so the viewer never depends on the cards
            # table (a 0-power creature never earned a "(0/2)" label there).
            power = stat_value(obj, "power")
            toughness = stat_value(obj, "toughness")
            if power is not None and toughness is not None:
                payload["power"] = power
                payload["toughness"] = toughness
        return grp_id

    # -- buffer -----------------------------------------------------------
    def _replay_rows(self) -> List[PendingEventRow]:
        rows = getattr(self, "_replay_row_buffer", None)
        if rows is None:
            rows = []
            self._replay_row_buffer = rows
        return rows

    def _replay_begin(self) -> int:
        """Open a batching scope; returns the buffer position at entry."""
        self._replay_depth = getattr(self, "_replay_depth", 0) + 1
        return len(self._replay_rows())

    def _replay_end(self) -> None:
        depth = getattr(self, "_replay_depth", 1) - 1
        self._replay_depth = depth if depth > 0 else 0
        if depth <= 0:
            self._replay_flush()

    @replay_safe()
    def _replay_append(self, row: PendingEventRow) -> None:
        rows = self._replay_rows()
        state = getattr(self, "_replay_capture_state", None)
        if state is not None and state.pending_phase is not None:
            # Phases are written lazily: a phase in which nothing happened
            # (most Main 2 and End steps) costs no row. A turn header does
            # not release it: the header is printed late, at the turn's
            # first action, and the phase row belongs after it.
            if row.fact is None or row.fact.kind != "turn":
                pending = state.pending_phase
                state.pending_phase = None
                if pending.base[2] == row.base[2]:
                    rows.append(pending)
        rows.append(row)
        if getattr(self, "_replay_depth", 0) <= 0:
            self._replay_flush()

    @replay_safe()
    def _replay_drop_pending_phase(self) -> None:
        state = getattr(self, "_replay_capture_state", None)
        if state is not None:
            state.pending_phase = None

    def _replay_flush(self) -> None:
        """Write every buffered row in one transaction (best effort).

        Printed rows are history the console already showed, so a failing
        batch never takes them down with it: on a lock or I/O error they are
        retried once on their own; on a row-level error (a bad value, a
        constraint) each row is written separately and only the bad ones are
        lost. Never raises.
        """
        rows = getattr(self, "_replay_row_buffer", None)
        if not rows:
            return
        self._replay_row_buffer = []
        try:
            conn = self._analytics_connect()
        except Exception:  # noqa: BLE001 - never break live tracking
            return
        if conn is None:
            return
        values = [row_values for row_values in map(_safe_row_values, rows) if row_values]
        try:
            with conn:
                conn.executemany(INSERT_EVENT_SQL, values)
            return
        except sqlite3.OperationalError:
            # Locked or I/O: one more attempt for the printed rows only, so a
            # busy database costs at most one extra busy timeout.
            retry = [row_values for row_values in values if row_values[-1]]
            try:
                with conn:
                    conn.executemany(INSERT_EVENT_SQL, retry)
            except sqlite3.Error:
                return
        except sqlite3.Error:
            for row_values in values:
                try:
                    with conn:
                        conn.execute(INSERT_EVENT_SQL, row_values)
                except sqlite3.Error:
                    continue

    @replay_safe()
    def _replay_discard_game_rows(self, game_id: str) -> None:
        rows = getattr(self, "_replay_row_buffer", None)
        if rows:
            self._replay_row_buffer = [row for row in rows if row.base[2] != game_id]

    @replay_safe()
    def _replay_patch_buffered_text(self, needle: str, replacement: str) -> None:
        for row in getattr(self, "_replay_row_buffer", None) or []:
            if row.visible and needle in row.text:
                row.text = row.text.replace(needle, replacement)

    def _replay_row_base(
        self, participant_id: Optional[str], actor_role: Optional[str], *, silent: bool, at=None
    ) -> tuple:
        now = at or self._now()
        start = self.game_state.game_start_time
        # Silent rows key on game_id only: session_id is '' (the column is
        # NOT NULL; the session is the game id's prefix) and match_id NULL.
        # The session index is partial (visible = 1), so they cost no entry.
        return (
            "" if silent else self.session_id,
            None if silent else self._current_match_id(),
            self._current_game_id(),
            now.isoformat(),
            max(0, int((now - start).total_seconds())) if start else None,
            self.game_state.turn_number or None,
            None if silent else (self.game_state.phase or None),
            None if silent else (self.game_state.step or None),
            participant_id,
            actor_role,
            None if silent else self.game_state.player_life,
            None if silent else self.game_state.opponent_life,
        )

    def _replay_role_for_seat(self, seat_id: Optional[int]) -> Optional[str]:
        if seat_id is None:
            return None
        if seat_id == self.game_state.player_seat_id:
            return "player"
        if seat_id == self.game_state.opponent_seat_id:
            return "opponent"
        return None

    @replay_safe()
    def _record_silent_event(
        self,
        fact: ReplayFact,
        *,
        at=None,
        phase_row: Optional[Tuple[str, Optional[str]]] = None,
    ) -> None:
        """Replay-only row (visible = 0): NULL participant, short machine text.

        Silent rows leave phase, step and both life columns NULL to stay
        small; only ``phase`` rows (``phase_row=(phase, step)``) fill them."""
        if not self._replay_capturing():
            return
        base = self._replay_row_base(
            None, self._replay_role_for_seat(fact.seat_id), silent=True, at=at
        )
        row = PendingEventRow(base, fact.machine_text(), None, fact, 0, None)
        if phase_row is not None:
            row.base = base[:6] + phase_row + base[8:]
            self._replay_state().pending_phase = row
            return
        self._replay_append(row)

    def _replay_attach(
        self, fact: ReplayFact, start: int, styles: Iterable[str], *, last_only: bool = False
    ) -> bool:
        """Attach a fact to a printed row buffered since ``start``."""
        rows = getattr(self, "_replay_row_buffer", None) or []
        candidates = rows[-1:] if last_only else rows[start:]
        for row in candidates:
            if row.visible and row.fact is None and row.style in styles:
                row.fact = fact
                return True
        return False

    # -- zone transfers ---------------------------------------------------
    @replay_safe()
    def _replay_move_fact(
        self,
        category: Optional[str],
        instance_id: int,
        card_obj: Optional[Dict[str, Any]],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Any,
        zone_dest: Any,
    ) -> Optional[ReplayFact]:
        if not self._replay_capturing():
            return None
        zone_from = self._replay_zone_name(zone_src, zones_by_id)
        zone_to = self._replay_zone_name(zone_dest, zones_by_id)
        reason = move_reason(category, zone_from)
        owner = None
        controller = None
        if isinstance(card_obj, dict) and card_obj:
            owner = self._normalize_seat_id(card_obj.get("ownerSeatId"))
            controller = self._normalize_seat_id(card_obj.get("controllerSeatId"))
        if owner not in (1, 2):
            owner = self._resolve_zone_transfer_seat(
                card_obj=card_obj,
                annotation=annotation,
                game_objects_by_id=game_objects_by_id,
                zone_src=zone_src,
                zone_dest=zone_dest,
                zones_by_id=zones_by_id,
            )
        payload: Dict[str, Any] = {"reason": reason}
        grp_id = self._replay_card_payload(card_obj, payload)
        if zone_from in ("library", "hand") and grp_id is not None:
            # A card the local player cannot see stays hidden: Arena only
            # names the opponent's hidden cards when they become public.
            visibility = (card_obj or {}).get("visibility")
            if owner == self.game_state.opponent_seat_id and visibility == "Visibility_Private":
                grp_id = None
                for hidden in ("name", "type", "power", "toughness"):
                    payload.pop(hidden, None)
        root = self._replay_root(instance_id)
        if root is not None:
            self._replay_state().latest[root] = int(instance_id)
        if zone_to == "exile":
            host = self._replay_exile_host(annotation, instance_id, game_objects_by_id, zones_by_id)
            if host is not None:
                payload["with"] = host
        if zone_to == "battlefield":
            chosen = self._chosen_land_type(card_obj)
            if chosen:
                payload["chosen"] = chosen
        if reason not in _UNSOURCED_MOVES:
            by = self._replay_move_source(annotation, instance_id, game_objects_by_id)
            if by is not None:
                payload["by"] = by
        return ReplayFact(
            "move",
            object_id=root,
            arena_id=grp_id,
            controller_seat=controller if controller in (1, 2) else owner,
            seat_id=owner,
            zone_from=zone_from,
            zone_to=zone_to,
            payload=payload,
        )

    def _replay_move_source(
        self,
        annotation: Dict[str, Any],
        instance_id: int,
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> Optional[int]:
        """Root id of the object whose effect moved the card, if Arena named one.

        Arena's ``affectorId`` is the resolving spell, or an ability object
        whose ``parentId`` is its source permanent. The viewer draws the
        removal (destroy, exile, bounce, an edict, a forced discard) from that
        source instead of inferring it from the item that resolved last. A card
        moving itself (a cost it paid) gives None.
        """
        try:
            affector = int(annotation.get("affectorId"))
        except (TypeError, ValueError):
            return None
        snapshots = getattr(self.game_state, "object_snapshots", {}) or {}
        obj = game_objects_by_id.get(affector) or snapshots.get(affector) or {}
        source_id = affector
        if obj.get("type") == "GameObjectType_Ability" or obj.get("parentId") is not None:
            try:
                source_id = int(obj.get("parentId"))
            except (TypeError, ValueError):
                return None
        root = self._replay_root(source_id)
        if root is None or root == self._replay_root(instance_id):
            return None
        return root

    def _replay_exile_host(
        self,
        annotation: Dict[str, Any],
        instance_id: int,
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
    ) -> Optional[int]:
        """Root id of the battlefield permanent that exiled the card, if one did.

        Arena's ``affectorId`` on an exile transfer is the resolving ability
        object (whose ``parentId`` is its source permanent) or, for static and
        replacement effects, the permanent itself. Spells on the stack and
        sources no longer on the battlefield give None: the card just sits in
        exile. The viewer tucks a card under its host (Deep-Cavern Bat,
        Pinnacle Starcage) while the host stays on the battlefield.
        """
        try:
            affector = int(annotation.get("affectorId"))
        except (TypeError, ValueError):
            return None
        snapshots = getattr(self.game_state, "object_snapshots", {}) or {}
        obj = game_objects_by_id.get(affector) or snapshots.get(affector) or {}
        host_id = affector
        if obj.get("type") == "GameObjectType_Ability" or obj.get("parentId") is not None:
            try:
                host_id = int(obj.get("parentId"))
            except (TypeError, ValueError):
                return None
            obj = game_objects_by_id.get(host_id) or snapshots.get(host_id) or {}
        if not obj or obj.get("type") != "GameObjectType_Card":
            return None
        if self._replay_zone_name(obj.get("zoneId"), zones_by_id) != "battlefield":
            return None
        root = self._replay_root(host_id)
        if root is None or root == self._replay_root(instance_id):
            return None
        return root

    @replay_safe()
    def _replay_settle_move(self, fact: Optional[ReplayFact], start: int) -> None:
        """Attach a zone-transfer fact to its printed line, or write it silently."""
        state = self._replay_state()
        state.ambient = None
        if fact is None or fact.payload is None:
            return
        if fact.payload.pop("_consumed", False):
            self._replay_note_move(state, fact)
            return
        if (self.game_state.turn_number or 0) < 1:
            # Pre-game re-deals and London-mulligan bottoms: the opening hand
            # snapshot written when turn 1 starts already reflects them.
            return
        reason = fact.payload.get("reason")
        if not self._replay_attach(fact, start, _ACCEPT_STYLES.get(str(reason), ())):
            self._record_silent_event(fact)
        self._replay_note_move(state, fact)

    @staticmethod
    def _replay_note_move(state: ReplayCaptureState, fact: ReplayFact) -> None:
        if fact.object_id is None:
            return
        if fact.zone_to:
            state.zone_of[fact.object_id] = fact.zone_to
        if fact.zone_to == "hand":
            state.hand_arrivals.add(fact.object_id)
        if fact.zone_to != "battlefield":
            state.tapped.discard(fact.object_id)
            state.pt.pop(fact.object_id, None)

    # -- stack ------------------------------------------------------------
    @replay_safe()
    def _replay_stack_push(
        self,
        instance_id: Optional[int],
        stack_key: int,
        *,
        seat_id: Optional[int],
        kind: str,
    ) -> None:
        if not self._replay_capturing():
            return
        state = self._replay_state()
        stack_id = state.allocate_stack_id(stack_key)
        game_objects = None
        payload: Dict[str, Any] = {"stack_id": stack_id}
        zone_from = None
        zone_to = None
        if kind == "spell":
            object_id = int(stack_key)
            # The root id's own snapshot may be a hidden hand card; the newest
            # instance (the spell on the stack) carries the face.
            latest = state.latest.get(object_id)
            obj = (
                self.game_state.object_snapshots.get(latest) if latest is not None else None
            ) or self._lookup_object(instance_id, game_objects)
            payload["stack_kind"] = "spell"
            grp_id = self._replay_card_payload(obj, payload)
            payload.pop("token", None)
            ambient = state.ambient
            if (
                ambient is not None
                and ambient.object_id == object_id
                and ambient.payload is not None
                and ambient.payload.get("reason") == "cast"
            ):
                ambient.payload["_consumed"] = True
                zone_from = ambient.zone_from
                zone_to = ambient.zone_to or "stack"
                if grp_id is None and ambient.arena_id is not None:
                    # The cast's own object (already on the stack) is public.
                    grp_id = ambient.arena_id
                    for key in ("name", "type"):
                        if key in ambient.payload:
                            payload[key] = ambient.payload[key]
        else:
            ability_id = int(instance_id) if instance_id is not None else None
            source_id = (
                self.game_state.ability_instance_sources.get(ability_id)
                if ability_id is not None
                else None
            )
            source = self._lookup_object(source_id, game_objects) if source_id is not None else {}
            object_id = self._replay_root(source_id)
            payload["stack_kind"] = (
                "activated" if ability_id in state.user_action_ids else "trigger"
            )
            grp_id = self._replay_card_payload(source, payload)
            payload.pop("token", None)
            payload.pop("type", None)
            text = self.game_state.ability_instance_action_texts.get(ability_id)
            if text:
                payload["text"] = text
        targets: List[int] = []
        target_seats: List[int] = []
        target_ids = self._target_ids_for_instance(instance_id)
        if not target_ids and object_id is not None and kind == "spell":
            # TargetSpec names the spell's current (stack) instance id.
            target_ids = self._target_ids_for_instance(state.latest.get(object_id))
        for target in target_ids:
            if target in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                target_seats.append(int(target))
            else:
                root = self._replay_root(target)
                if root is not None and root not in targets:
                    targets.append(root)
        if targets:
            payload["targets"] = targets
        if target_seats:
            payload["target_seats"] = target_seats
        fact = ReplayFact(
            "stack_push",
            object_id=object_id,
            target_object_id=targets[0] if targets else None,
            arena_id=grp_id,
            controller_seat=seat_id,
            seat_id=seat_id,
            zone_from=zone_from,
            zone_to=zone_to,
            payload=payload,
        )
        if not self._replay_attach(fact, 0, ("cast", "ability", "stack"), last_only=True):
            self._record_silent_event(fact)

    @replay_safe()
    def _replay_stack_status_fact(
        self, stack_key: Optional[int], status: str
    ) -> Optional[ReplayFact]:
        if stack_key is None or not self._replay_capturing():
            return None
        stack_id = self._replay_state().stack_ids.get(int(stack_key))
        if stack_id is None:
            return None
        kind = {
            "resolved": "stack_resolve",
            "countered": "stack_countered",
            "fizzled": "stack_fizzle",
        }.get(status)
        if kind is None:
            return None
        return ReplayFact(kind, payload={"stack_id": stack_id})

    # -- console link -------------------------------------------------------
    def _replay_link(self, game_id: str) -> Optional[str]:
        """Dashboard replay URL, when the unified launcher told us the port."""
        provider = getattr(self, "dashboard_url_provider", None)
        base = None
        if callable(provider):
            try:
                base = provider()
            except Exception:
                base = None
        if not base:
            base = getattr(self, "dashboard_url", None)
        if not base:
            return None
        return f"{str(base).rstrip('/')}/#/replay/{game_id}"
