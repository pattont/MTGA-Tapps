"""Replay stream contract: event vocabulary, stream assembly, JSON encoding.

The replay page consumes one versioned JSON document per game (see
``docs/REPLAY_FORMAT.md`` section 2). Two producers build it: the builder for
games recorded with structured rows (``replay_builder``) and the text
reconstructor for older games (``replay_reconstruct``). Both go through the
helpers here so the shape stays identical.

Dependency-free (standard library plus pure package helpers) and Python 3.9
compatible.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # Python 3.8+: TypedDict lives in typing.
    from typing import TypedDict
except ImportError:  # pragma: no cover - documentation-only fallback
    TypedDict = dict  # type: ignore[misc,assignment]

STREAM_VERSION = 1
FIDELITY_RECORDED = "recorded"
FIDELITY_RECONSTRUCTED = "reconstructed"

ZONES = ("library", "hand", "battlefield", "graveyard", "exile", "stack", "command", "limbo")
#: Zones a ``move`` may name as ``from`` for an object it creates on first reference.
CREATING_ZONES = ("limbo", "library", "hand")
MOVE_REASONS = (
    "draw",
    "play_land",
    "cast",
    "resolve",
    "destroy",
    "exile",
    "sacrifice",
    "discard",
    "mill",
    "bounce",
    "counter",
    "sba",
    "put",
    "token_create",
    "token_cease",
    "shuffle_in",
    "unknown",
)
STACK_KINDS = ("spell", "trigger", "activated")
STACK_CLOSE_KINDS = ("stack_resolve", "stack_fizzle", "stack_countered")

#: Kind-specific fields every event of that kind carries (besides the common
#: ``seq``, ``t``, ``turn``, ``phase``, ``step``, ``kind``, ``log``).
EVENT_FIELDS: Dict[str, Tuple[str, ...]] = {
    "game_start": ("seats_hand_sizes", "library_sizes"),
    "turn": ("turn", "active_seat"),
    "phase": ("phase", "step"),
    "life": ("seat", "life", "delta", "source_obj"),
    "mulligan": ("seat", "from_size", "to_size", "bottomed"),
    "move": (
        "obj",
        "card",
        "from",
        "to",
        "owner",
        "controller",
        "reason",
        "inferred",
        "index",
        "with",
        "by",
        "chosen",
    ),
    "tap": ("objs",),
    "untap": ("objs",),
    "counter": ("obj", "type", "delta", "total"),
    "pt": ("obj", "power", "toughness"),
    "attach": ("obj", "to"),
    "identity": ("obj", "card", "face_down"),
    # The contract's stack item "kind" (spell/trigger/activated) cannot share
    # the event's own "kind" key, so it travels as "stack_kind".
    "stack_push": ("stack_id", "obj", "card", "stack_kind", "controller", "text", "targets"),
    "stack_resolve": ("stack_id",),
    "stack_fizzle": ("stack_id",),
    "stack_countered": ("stack_id",),
    "attack": ("seat", "objs", "target_seat", "target_obj"),
    "block": ("seat", "pairs"),
    "damage": ("source", "target_obj", "target_seat", "amount", "combat"),
    "reveal": ("obj", "card"),
    "scry": ("seat", "top", "bottom", "looked"),
    "shuffle": ("seat",),
    "game_end": ("winner_seat", "reason"),
    "note": (),
}
EVENT_KINDS = tuple(EVENT_FIELDS)

RECONSTRUCTED_LIMITATIONS = [
    "Blocks are inferred from combat damage; blocks that dealt no damage are missing.",
    "Tapped and untapped state was not recorded.",
    "Counters (+1/+1, loyalty and others) and attachments were not recorded.",
    "Tokens appear when they are first mentioned (attacking, dealing or taking damage, "
    "leaving play), not when they were created.",
    "The opponent's hand contents are hidden; its size is estimated from draws and plays.",
    "Permanents entering on resolution and instants or sorceries reaching the graveyard "
    "are inferred.",
    "Same-named copies cannot be told apart; the replay picks one.",
]


class ReplayCard(TypedDict, total=False):
    name: str
    arena_id: Optional[int]
    type_line: Optional[str]
    primary_type: Optional[str]
    power: Optional[str]
    toughness: Optional[str]
    mana_cost: Optional[str]
    color_identity: Optional[str]
    is_token: bool
    image_url: Optional[str]
    faces: List[Dict[str, Optional[str]]]
    keywords: List[str]
    back_face: bool


class ReplayTurn(TypedDict):
    turn: int
    seat: Optional[int]
    first_seq: int
    last_seq: int
    started_at: Optional[str]
    duration_seconds: Optional[float]


class ReplayAvailability(TypedDict):
    state: str
    reason: Optional[str]


class ReplayUnavailable(Exception):
    """The game exists but has nothing a replay can be built from."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_CARD_NUMBER_RE = re.compile(r"^Card #\d+$")


def is_unknown_card_name(name: Optional[str]) -> bool:
    """True for the tracker's placeholder names (``Card #123``) and blanks."""
    return not name or bool(_CARD_NUMBER_RE.match(str(name).strip()))


def card_key(arena_id: Optional[int], name: Optional[str]) -> str:
    """``a<arena_id>`` when the Arena id is known, else ``n:<name>``, else ``unknown``."""
    if arena_id:
        try:
            return f"a{int(arena_id)}"
        except (TypeError, ValueError):
            pass
    if name and not is_unknown_card_name(name):
        return f"n:{name}"
    return "unknown"


def _primary_type(types: Sequence[str]) -> Optional[str]:
    for wanted in ("Creature", "Planeswalker", "Battle", "Land", "Artifact", "Enchantment"):
        if wanted in types:
            return wanted
    for wanted in ("Instant", "Sorcery"):
        if wanted in types:
            return wanted
    return types[0] if types else None


def primary_type_from_text(type_text: Optional[str]) -> Optional[str]:
    """``"Creature, Artifact"`` / ``"Legendary Creature — Elf"`` → ``"Creature"``."""
    if not type_text:
        return None
    head = str(type_text).split("—")[0]
    types = [word for word in re.split(r"[\s,]+", head) if word]
    return _primary_type(types)


class CardRegistry:
    """Builds the stream's ``cards`` map; one entry per card key."""

    def __init__(self) -> None:
        self.cards: Dict[str, Dict[str, Any]] = {}

    def add(
        self,
        name: Optional[str],
        arena_id: Optional[int] = None,
        **meta: Any,
    ) -> str:
        key = card_key(arena_id, name)
        entry = self.cards.get(key)
        if entry is None:
            display = "Unknown card" if is_unknown_card_name(name) and not arena_id else name
            entry = {
                "name": display or "Unknown card",
                "arena_id": int(arena_id) if arena_id else None,
                "type_line": None,
                "primary_type": None,
                "power": None,
                "toughness": None,
                "mana_cost": None,
                "color_identity": None,
                "is_token": False,
                "image_url": None,
                "faces": _faces(display),
                "keywords": [],
                "back_face": False,
            }
            self.cards[key] = entry
        elif (
            entry.get("name") in (None, "Unknown card") and name and not is_unknown_card_name(name)
        ):
            entry["name"] = name
            entry["faces"] = _faces(name)
        for field, value in meta.items():
            if value is None or field not in entry:
                continue
            if field == "is_token":
                entry["is_token"] = bool(entry["is_token"] or value)
            elif entry.get(field) in (None, ""):
                entry[field] = str(value) if field in ("power", "toughness") else value
        if entry.get("primary_type") is None and entry.get("type_line"):
            entry["primary_type"] = primary_type_from_text(entry["type_line"])
        return key

    def names_by_type(self) -> Dict[str, Optional[str]]:
        """Card name → primary type, for the Game Detail timeline segmenter."""
        out: Dict[str, Optional[str]] = {}
        for entry in self.cards.values():
            name = entry.get("name")
            if not name or name == "Unknown card":
                continue
            out.setdefault(str(name), entry.get("primary_type"))
            for face in entry.get("faces") or []:
                face_name = face.get("name")
                if face_name:
                    out.setdefault(str(face_name), entry.get("primary_type"))
        return out


def _faces(name: Optional[str]) -> List[Dict[str, Optional[str]]]:
    if not name or " // " not in name:
        return []
    return [{"name": part.strip(), "type_line": None} for part in name.split(" // ") if part]


class EventLog:
    """Accumulates stream events with monotonic ``seq`` and ``t``."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self._t = 0.0
        self.turn = 0
        self.phase: Optional[str] = None
        self.step: Optional[str] = None
        #: ``game_events.id`` of the row being turned into events; None for
        #: synthesized setup and finish events.
        self.row_id: Optional[int] = None

    def at(
        self,
        elapsed: Any = None,
        turn: Any = None,
        phase: Optional[str] = None,
        step: Optional[str] = None,
    ) -> None:
        """Move the clock/context forward for the events that follow."""
        if elapsed is not None:
            try:
                self._t = max(self._t, float(elapsed))
            except (TypeError, ValueError):
                pass
        if turn is not None:
            try:
                self.turn = max(0, int(turn))
            except (TypeError, ValueError):
                pass
        if phase is not None:
            self.phase = phase
        self.step = step

    def emit(
        self, kind: str, log: Optional[Dict[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        if kind not in EVENT_FIELDS:
            raise ValueError(f"unknown replay event kind: {kind}")
        event: Dict[str, Any] = {
            "seq": len(self.events),
            "t": round(self._t, 3),
            "turn": self.turn,
            "phase": self.phase,
            "step": self.step,
            "kind": kind,
            "log": log,
            "row_id": self.row_id,
        }
        for name in EVENT_FIELDS[kind]:
            event[name] = fields.pop(name, None)
        if fields:
            raise ValueError(f"unexpected fields for {kind}: {sorted(fields)}")
        self.events.append(event)
        return event

    @property
    def last(self) -> Optional[Dict[str, Any]]:
        return self.events[-1] if self.events else None


def attach_log(event: Optional[Dict[str, Any]], text: Optional[str]) -> None:
    """Attach a printed line to an event (segments are added by ``finalize_logs``)."""
    if event is None or text is None:
        return
    event["log"] = {"text": str(text).strip("\r\n").lstrip()}


def finalize_logs(events: List[Dict[str, Any]], cards: CardRegistry) -> None:
    """Add Game Detail style ``segments`` to every log, linking stream cards."""
    from .dashboard import _timeline_text_segments  # lazy: dashboard is heavy

    linkable = cards.names_by_type()
    for event in events:
        log = event.get("log")
        if isinstance(log, dict) and "segments" not in log:
            log["segments"] = _timeline_text_segments(str(log.get("text") or ""), linkable)


def build_turns(
    events: List[Dict[str, Any]], timings: Iterable[Dict[str, Any]] = ()
) -> List[Dict[str, Any]]:
    """One entry per ``turn`` event; ``first_seq``/``last_seq`` inclusive."""
    by_turn: Dict[int, Dict[str, Any]] = {}
    for row in timings:
        try:
            by_turn.setdefault(int(row.get("turn_number")), row)
        except (TypeError, ValueError):
            continue
    starts = [event for event in events if event["kind"] == "turn"]
    turns: List[Dict[str, Any]] = []
    for index, event in enumerate(starts):
        next_seq = starts[index + 1]["seq"] if index + 1 < len(starts) else len(events)
        timing = by_turn.get(int(event.get("turn") or 0)) or {}
        duration = timing.get("duration_seconds")
        turns.append(
            {
                "turn": event.get("turn"),
                "seat": event.get("active_seat"),
                "first_seq": event["seq"],
                "last_seq": max(event["seq"], next_seq - 1),
                "started_at": timing.get("started_at"),
                "duration_seconds": float(duration) if duration is not None else None,
            }
        )
    return turns


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def seat_layout(participants: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
    """(player_seat, opponent_seat), falling back to 1/2 when unknown."""
    player = next((row for row in participants if row.get("role") == "player"), {}) or {}
    opponent = next((row for row in participants if row.get("role") == "opponent"), {}) or {}
    player_seat = _int_or_none(player.get("seat_id"))
    opponent_seat = _int_or_none(opponent.get("seat_id"))
    if player_seat is None and opponent_seat is None:
        return 1, 2
    if player_seat is None:
        player_seat = 1 if opponent_seat != 1 else 2
    if opponent_seat is None or opponent_seat == player_seat:
        opponent_seat = 1 if player_seat != 1 else 2
    return player_seat, opponent_seat


def stream_header(rows: Dict[str, Any], fidelity: str) -> Dict[str, Any]:
    """``game``, ``player_seat`` and ``seats`` sections from the game's rows.

    ``seats[*].colors`` is left empty for the producer to fill once it knows
    which cards each seat showed.
    """
    from .format_normalizer import normalize_match_format

    game = (rows.get("games") or [{}])[0]
    match = (rows.get("matches") or [{}])[0]
    participants = rows.get("participants") or []
    player_seat, opponent_seat = seat_layout(participants)
    best_of = _int_or_none(match.get("best_of")) or 1
    normalized = normalize_match_format(match.get("format"), default_best_of=best_of)
    winner_seat = None
    winner_id = game.get("winner_participant_id")
    for row in participants:
        if winner_id and row.get("id") == winner_id:
            winner_seat = _int_or_none(row.get("seat_id"))
    outcome = str(game.get("outcome") or "unknown").lower()
    if outcome not in ("win", "loss", "draw"):
        outcome = "unknown"
    if winner_seat is None and outcome == "win":
        winner_seat = player_seat
    elif winner_seat is None and outcome == "loss":
        winner_seat = opponent_seat

    commanders: Dict[str, List[str]] = {}
    for row in rows.get("participant_commanders") or []:
        name = row.get("card_name")
        if name:
            commanders.setdefault(str(row.get("participant_id")), []).append(str(name))

    seats: Dict[str, Dict[str, Any]] = {}
    for role, seat in (("player", player_seat), ("opponent", opponent_seat)):
        row = next((p for p in participants if p.get("role") == role), {}) or {}
        name = "You" if role == "player" else (row.get("display_name") or "Opponent")
        seats[str(seat)] = {
            "role": role,
            "name": name,
            "deck_name": row.get("deck_name") if role == "player" else row.get("deck_archetype"),
            "starting_life": _int_or_none(row.get("starting_life")) or 20,
            "went_first": None if row.get("went_first") is None else bool(row.get("went_first")),
            "commanders": sorted(commanders.get(str(row.get("id")), [])),
            "deck_size": _int_or_none(row.get("deck_size")),
            "colors": "",
        }
    duration = game.get("duration_seconds")
    return {
        "version": STREAM_VERSION,
        "fidelity": fidelity,
        "replay_version": _int_or_none(game.get("replay_version")),
        "limitations": (
            list(RECONSTRUCTED_LIMITATIONS) if fidelity == FIDELITY_RECONSTRUCTED else []
        ),
        "game": {
            "id": game.get("id"),
            "started_at": game.get("started_at"),
            "ended_at": game.get("ended_at"),
            "format": normalized.label,
            "best_of": 3 if normalized.best_of == 3 else 1,
            "game_number": _int_or_none(game.get("game_number")) or 1,
            "outcome": outcome,
            "outcome_reason": game.get("outcome_reason"),
            "winner_seat": winner_seat,
            "total_turns": _int_or_none(game.get("total_turns")),
            "duration_seconds": _int_or_none(duration),
        },
        "player_seat": player_seat,
        "seats": seats,
        "cards": {},
        "turns": [],
        "events": [],
    }


def seat_colors(card_entries: Iterable[Optional[Dict[str, Any]]]) -> str:
    """WUBRG letters from the color identities of the given cards."""
    from .colors import normalize_colors

    letters = "".join(str(entry.get("color_identity") or "") for entry in card_entries if entry)
    return normalize_colors(letters)


def encode_stream(stream: Dict[str, Any]) -> bytes:
    """Compact UTF-8 JSON for the API response."""
    return json.dumps(stream, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def validate_stream(stream: Dict[str, Any]) -> List[str]:
    """Check the producer guarantees with a minimal reducer; returns problems.

    Covers: event shape, strictly increasing ``seq``, non-decreasing ``t``,
    ``game_start`` first, moves referencing known objects (or creating them
    from limbo/library/hand), objects leaving the zone they are in, stack
    closes naming a pushed and still open ``stack_id``, hand and library
    counts never negative, and ``turns`` covering every ``turn`` event.
    """
    problems: List[str] = []
    events = stream.get("events") or []
    if not events or events[0].get("kind") != "game_start":
        return ["first event is not game_start"]
    library = {str(k): int(v) for k, v in (events[0].get("library_sizes") or {}).items()}
    hand: Dict[str, int] = {}
    zone_of: Dict[str, str] = {}
    open_stack: Dict[str, Dict[str, Any]] = {}
    seen_stack: set = set()
    first_turn_seq = next((e["seq"] for e in events if e["kind"] == "turn"), len(events))
    last_seq = -1
    last_t = 0.0
    cards = stream.get("cards") or {}

    def known(obj: Any, where: str, seq: int) -> None:
        if obj is not None and obj not in zone_of:
            problems.append(f"seq {seq}: {where} references unknown object {obj}")

    for event in events:
        seq = event.get("seq")
        kind = event.get("kind")
        if kind not in EVENT_FIELDS:
            problems.append(f"seq {seq}: unknown kind {kind}")
            continue
        for name in ("seq", "t", "turn", "phase", "step", "kind", "log") + EVENT_FIELDS[kind]:
            if name not in event:
                problems.append(f"seq {seq}: {kind} lacks {name}")
        if not isinstance(seq, int) or seq <= last_seq:
            problems.append(f"seq {seq}: not strictly increasing")
        last_seq = seq if isinstance(seq, int) else last_seq
        if float(event.get("t") or 0.0) < last_t:
            problems.append(f"seq {seq}: t decreased")
        last_t = max(last_t, float(event.get("t") or 0.0))
        card = event.get("card")
        if card is not None and kind in ("move", "identity", "stack_push", "reveal"):
            if card not in cards:
                problems.append(f"seq {seq}: card {card} missing from cards")
        if kind == "move":
            obj, src, dst = event["obj"], event["from"], event["to"]
            owner = str(event.get("owner"))
            if src not in ZONES or dst not in ZONES:
                problems.append(f"seq {seq}: bad zone {src}->{dst}")
            if event.get("reason") not in MOVE_REASONS:
                problems.append(f"seq {seq}: bad reason {event.get('reason')}")
            if obj not in zone_of:
                if src not in CREATING_ZONES:
                    problems.append(f"seq {seq}: move creates {obj} from {src}")
            elif zone_of[obj] != src:
                problems.append(f"seq {seq}: {obj} moves from {src} but is in {zone_of[obj]}")
            # game_start library sizes already exclude the opening hand, so
            # only moves after the setup block (first turn event) count.
            if src == "library" and seq > first_turn_seq:
                library[owner] = library.get(owner, 0) - 1
            if dst == "library":
                library[owner] = library.get(owner, 0) + 1
            if src == "hand":
                hand[owner] = hand.get(owner, 0) - 1
            if dst == "hand":
                hand[owner] = hand.get(owner, 0) + 1
            if library.get(owner, 0) < 0:
                problems.append(f"seq {seq}: library of seat {owner} negative")
            if hand.get(owner, 0) < 0:
                problems.append(f"seq {seq}: hand of seat {owner} negative")
            zone_of[obj] = dst
        elif kind == "stack_push":
            stack_id = event["stack_id"]
            if stack_id in seen_stack:
                problems.append(f"seq {seq}: stack id {stack_id} reused")
            seen_stack.add(stack_id)
            open_stack[stack_id] = event
            known(event.get("obj"), "stack_push", seq)
        elif kind in STACK_CLOSE_KINDS:
            if open_stack.pop(event["stack_id"], None) is None:
                problems.append(f"seq {seq}: {kind} for unknown/closed {event['stack_id']}")
        elif kind in ("tap", "untap", "attack"):
            for obj in event.get("objs") or []:
                known(obj, kind, seq)
        elif kind in ("counter", "pt", "identity", "reveal", "attach"):
            known(event.get("obj"), kind, seq)
        elif kind == "block":
            for pair in event.get("pairs") or []:
                known(pair.get("blocker"), "block", seq)
                known(pair.get("attacker"), "block", seq)
        elif kind == "damage":
            known(event.get("source"), "damage source", seq)
            known(event.get("target_obj"), "damage target", seq)
    turn_seqs = {event["seq"] for event in events if event["kind"] == "turn"}
    covered = {turn.get("first_seq") for turn in stream.get("turns") or []}
    if turn_seqs != covered:
        problems.append("turns do not cover every turn event")
    for turn in stream.get("turns") or []:
        if turn.get("last_seq", -1) < turn.get("first_seq", 0):
            problems.append(f"turn {turn.get('turn')}: last_seq before first_seq")
    return problems
