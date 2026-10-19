"""Grammar of the tracker's console lines, for the replay reconstructor.

The tracker generated every line it printed, so older games' text follows a
small regular grammar anchored on ``[Name (Type P/T)]`` brackets
(``docs/REPLAY_FORMAT.md`` section 4). This module holds the regex table, the
bracket and actor parsers and the linear stack-pairing pre-pass; it has no
board state.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

_TS_RE = re.compile(r"^\s*\[\d+:\d{2}(?::\d{2})?\]\s*")
_ACTOR_RE = re.compile(r"^(You|Opponent|Unknown):\s*")
_BRACKET_RE = re.compile(r"\[([^\]\n]+)\]")
_SUFFIX_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
_PT_RE = re.compile(r"(-?\d+|\?|\*)/(-?\d+|\?|\*)$")

_TURN_RE = re.compile(r"^Turn (\d+) - (YOUR TURN|OPPONENT'S TURN)")
_DRAW_RE = re.compile(r"^drew (?:a card|\[([^\]]+)\])$")
# A land that chose a basic land type ends "as a Mountain".
_LAND_RE = re.compile(r"^played \[([^\]]+)\](?: as an? ([A-Za-z ]+))?$")
_CAST_RE = re.compile(r"^cast \[([^\]]+)\](.*)$", re.S)
_BECAME_RE = re.compile(r"^\[([^\]]+)\] became \[([^\]]+)\](?: \(([^()]*)\))?\s*$")
_TAPPED_RE = re.compile(r"^\[([^\]]+)\] tapped \[([^\]]+)\]$")
_ABILITY_RE = re.compile(r"^\[([^\]]+)\] - (.*)$", re.S)
_STACK_RE = re.compile(r"^Stack: \[([^\]]+)\](.*)$", re.S)
_COUNTERED_RE = re.compile(r"^\[([^\]]+)\] was countered$")
_ATTACK_RE = re.compile(r"^(You|Opponent) attacking \[([^\]]+)\] with \[([^\]]+)\]\s*$")
_SWAP_RE = re.compile(
    r"^Combat swap: returned \[([^\]]+)\] and put \[([^\]]+)\] onto battlefield attacking"
)
_DEALT_RE = re.compile(
    r"^Combat: \[([^\]]+)\] dealt (\d+) damage to \[([^\]]+)\] \((your|opponent's)\)$"
)
_TOOK_RE = re.compile(r"^(?:Combat: )?\[([^\]]+)\] \((your|opponent's)\) took (\d+) damage$")
_ARROW_RE = re.compile(r"^(.+?) → (.+?) \((your|opponent's)\): (\d+) damage$")
_LIFE_RE = re.compile(r"^(gained|lost) (\d+) life(?: \[([^\]]+)\])? \(now (-?\d+)\)$")
_SCRY_RE = re.compile(r"^scried (\d+)(?: — (.*))?$", re.S)

_DESTROYED_RE = re.compile(r"^\[([^\]]+)\] was destroyed$")
#: Keywords (CardDatabase.REPLAY_KEYWORD_BASE_IDS) that cast a card from its
#: owner's graveyard.
GRAVEYARD_CAST_KEYWORDS = frozenset({"flashback", "escape", "disturb", "harmonize"})

_EXILED_RE = re.compile(r"^\[([^\]]+)\] was exiled( as cost)?$")
_SACRIFICED_RE = re.compile(r"^\[([^\]]+)\] was sacrificed( as cost)?$")
_DISCARDED_RE = re.compile(r"^\[([^\]]+)\] was discarded( as cost)?$")
_SBA_RE = re.compile(r"^\[([^\]]+)\] was put into graveyard \(([^()]+)\)$")
_MILLED_RE = re.compile(r"^milled (?:a card|\[([^\]]+)\])$")
_RETURNED_RE = re.compile(r"^returned \[([^\]]+)\] to hand(?: as cost for \[([^\]]+)\])?$")
_SOURCE_RETURNED_RE = re.compile(r"^\[([^\]]+)\] returned \[([^\]]+)\] to (your|opponent's) hand$")
_RETURNED_BATTLEFIELD_RE = re.compile(r"^(?:\[([^\]]+)\] )?returned \[([^\]]+)\] to battlefield$")
#: An ability that returns its target to the battlefield ("return up to one
#: target enchantment card from your graveyard to the battlefield"). Before the
#: tracker printed "returned [X] to battlefield", such a return was printed as
#: "returned [X] to hand".
_RETURN_TO_BATTLEFIELD_TEXT_RE = re.compile(r"\breturn\b.*\bto the battlefield\b", re.IGNORECASE)
#: One unconditional token-making sentence of an ability ("Create three 2/2
#: white Knight creature tokens."). Sentences that do not start with Create
#: ("If you do, create ...") and counts that depend on the board are skipped.
_CREATE_TOKENS_RE = re.compile(
    r"^Create (a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+) "
    r"(?:tapped )?(?:(\d+)/(\d+) )?(.+?) tokens?\b(.*)$"
)
_COUNT_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_TOKEN_DESCRIPTORS = {
    "white",
    "blue",
    "black",
    "red",
    "green",
    "colorless",
    "and",
    "legendary",
    "snow",
    "creature",
    "artifact",
    "enchantment",
}


def created_tokens(text: str):
    """(name, count, power, toughness, types) for each unconditional "Create ..."
    sentence of an ability's text; empty when there is none."""
    out = []
    for sentence in re.split(r"(?<=\.)\s+", text.strip()):
        match = _CREATE_TOKENS_RE.match(sentence.strip())
        if not match:
            continue
        count_text, power, toughness, words, rest = match.groups()
        if "for each" in rest or "equal to" in rest:
            continue
        count = _COUNT_WORDS.get(count_text.lower()) or (
            int(count_text) if count_text.isdigit() else 0
        )
        parts = words.split()
        types = [
            w.capitalize() for w in parts if w.lower() in ("creature", "artifact", "enchantment")
        ]
        name = " ".join(w for w in parts if w.lower() not in _TOKEN_DESCRIPTORS)
        if not count or not name or count > 20:
            continue
        if power is not None and "Creature" not in types:
            types.append("Creature")
        out.append((name, count, power, toughness, types))
    return out


_PUT_BATTLEFIELD_RE = re.compile(r"^put \[([^\]]+)\] onto battlefield( attacking)?$")
_PUT_HAND_RE = re.compile(r"^(?:\[([^\]]+)\] )?put \[([^\]]+)\] into (your|opponent's) hand$")

_STATUS_SUFFIXES = (
    ("[left stack without resolving - inferred]", "stack_fizzle"),
    ("[countered]", "stack_countered"),
    ("[resolved]", "stack_resolve"),
    ("resolved", "stack_resolve"),
)
_TRIGGER_HINT_RE = re.compile(r"(^|— )(When|Whenever|At)\b")
_PLAYER_TARGETS = {"you", "opponent"}
#: Common noncreature token names, so an inferred token gets the right type.
_ARTIFACT_TOKENS = {
    "Blood",
    "Clue",
    "Food",
    "Gold",
    "Incubator",
    "Junk",
    "Lander",
    "Map",
    "Powerstone",
    "Shard",
    "Treasure",
}


def parse_bracket(content: str) -> Tuple[str, List[str], Optional[str], Optional[str]]:
    """``"Name (Creature, Artifact 2/2)"`` → (name, types, power, toughness)."""
    content = content.strip()
    match = _SUFFIX_RE.search(content)
    if not match or match.start() == 0:
        return content, [], None, None
    name = content[: match.start()].strip()
    inner = match.group(1).strip()
    power = toughness = None
    pt = _PT_RE.search(inner)
    if pt:
        power, toughness = pt.group(1), pt.group(2)
        inner = inner[: pt.start()].strip()
    types = [part.strip() for part in inner.split(",") if part.strip()]
    return name, types, power, toughness


def _bracket_names(text: str) -> List[str]:
    return [parse_bracket(content)[0] for content in _BRACKET_RE.findall(text or "")]


def _split_actor(text: str) -> Tuple[Optional[str], str]:
    body = _TS_RE.sub("", text or "", count=1)
    match = _ACTOR_RE.match(body)
    if not match:
        return None, body.strip()
    return match.group(1), body[match.end() :].strip()


def _norm_ability_text(text: str) -> str:
    text = re.sub(r"\(triggered, on stack\)\s*$", "", text.strip())
    text = re.sub(r"\s*->\s*\[.*$", "", text, flags=re.S)
    return " ".join(text.split())[:60].casefold()


def _close_status(rest: str) -> Tuple[Optional[str], str]:
    stripped = rest.rstrip()
    for suffix, kind in _STATUS_SUFFIXES:
        if stripped.endswith(suffix):
            return kind, stripped[: -len(suffix)].rstrip()
    return None, stripped


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _stack_signature(row: Dict[str, Any]) -> Optional[Tuple[str, str, bool, str, str]]:
    """(role, name, is_ability, ability_text, close_kind) for stack pairing.

    role is ``push`` (cast, ability trigger/activation) or ``close``.
    """
    event_type = row.get("event_type")
    text = str(row.get("text") or "")
    _actor, body = _split_actor(text)
    if event_type in ("cast", "stack"):
        match = _CAST_RE.match(body)
        if match:
            return ("push", parse_bracket(match.group(1))[0], False, "", "")
    if event_type in ("ability", "stack"):
        if _BECAME_RE.match(body) or _TAPPED_RE.match(body):
            return None
        match = _ABILITY_RE.match(body)
        if match:
            name = parse_bracket(match.group(1))[0]
            return ("push", name, True, _norm_ability_text(match.group(2)), "")
    if event_type in ("stack_resolve", "stack_fail"):
        match = _STACK_RE.match(body)
        if match:
            kind, rest = _close_status(match.group(2))
            if kind:
                is_ability = rest.startswith(" - ") or rest.startswith("- ")
                ability_text = _norm_ability_text(rest.lstrip(" -")) if is_ability else ""
                name = parse_bracket(match.group(1))[0]
                return ("close", name, is_ability, ability_text, kind)
    if event_type == "counter":
        match = _COUNTERED_RE.match(body)
        if match:
            return ("close", parse_bracket(match.group(1))[0], False, "", "stack_countered")
    return None


def pair_stack_rows(rows: Sequence[Dict[str, Any]]) -> Dict[int, int]:
    """Map each explicit close row index to the push row index it closes.

    LIFO within a turn by (name, spell-or-ability), preferring an ability
    whose text matches. Linear in the number of rows for realistic stacks.
    """
    pairs: Dict[int, int] = {}
    open_pushes: List[Tuple[int, Tuple[str, str, bool, str, str]]] = []
    for index, row in enumerate(rows):
        if row.get("event_type") == "turn":
            open_pushes.clear()
            continue
        signature = _stack_signature(row)
        if signature is None:
            continue
        role, name, is_ability, ability_text, _kind = signature
        if role == "push":
            open_pushes.append((index, signature))
            continue
        chosen = None
        for position in range(len(open_pushes) - 1, -1, -1):
            push_signature = open_pushes[position][1]
            if push_signature[1] != name or push_signature[2] != is_ability:
                continue
            if chosen is None:
                chosen = position
            if not is_ability or push_signature[3] == ability_text:
                chosen = position
                break
        if chosen is not None:
            pairs[index] = open_pushes.pop(chosen)[0]
    return pairs
