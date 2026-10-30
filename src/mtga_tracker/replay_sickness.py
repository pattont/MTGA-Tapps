"""Estimated summoning sickness for games recorded before Arena's flag was captured.

Games with ``replay_version >= 2`` carry Arena's own ``hasSummoningSickness``
flag as ``sick``/``unsick`` rows, which already account for haste from any
source. Older recorded games and reconstructed ones only know when a creature
entered, so this pass estimates it: a creature that really entered (not an
inferred arrival) without printed haste is sick until its controller's next
turn, and attacking proves it was not. Contract: docs/REPLAY_FORMAT.md.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

#: replay_version from which capture records summoning sickness itself.
SICKNESS_CAPTURE_VERSION = 2

SICKNESS_ESTIMATE_LIMITATION = (
    "Summoning sickness is estimated from when each creature entered; "
    "haste given by other cards is not seen."
)

_SICKNESS_KINDS = ("sick", "unsick")


def card_fact(entry: Mapping[str, Any], facts: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """A stream card entry's Arena facts: a token by its Arena id, else by name."""
    fact = None
    if entry.get("is_token") and entry.get("arena_id"):
        fact = facts.get(f"#{entry['arena_id']}")
    return fact or facts.get(str(entry.get("name") or "").casefold())


def _can_be_sick(entry: Optional[Mapping[str, Any]], facts: Mapping[str, Any]) -> bool:
    """A creature without printed haste."""
    if not entry:
        return False
    types = f"{entry.get('primary_type') or ''} {entry.get('type_line') or ''}".lower()
    if "creature" not in types:
        return False
    fact = card_fact(entry, facts) or {}
    return "haste" not in (fact.get("keywords") or ())


def _event(template: Dict[str, Any], kind: str, objs: List[str]) -> Dict[str, Any]:
    return {
        "seq": 0,
        "t": template.get("t", 0.0),
        "turn": template.get("turn", 0),
        "phase": template.get("phase"),
        "step": template.get("step"),
        "kind": kind,
        "log": None,
        "row_id": None,
        "objs": objs,
    }


def estimate_summoning_sickness(
    events: List[Dict[str, Any]],
    cards: Mapping[str, Mapping[str, Any]],
    facts: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """``events`` with estimated ``sick``/``unsick`` events added, ``seq`` renumbered.

    Returns ``events`` unchanged when it already has sickness events.
    """
    if any(event.get("kind") in _SICKNESS_KINDS for event in events):
        return events
    facts = facts or {}
    sick: Dict[str, Any] = {}  # obj -> controller seat
    out: List[Dict[str, Any]] = []
    for event in events:
        kind = event.get("kind")
        if kind == "attack":
            woke = [obj for obj in event.get("objs") or [] if obj in sick]
            for obj in woke:
                sick.pop(obj, None)
            if woke:
                out.append(_event(event, "unsick", woke))
        out.append(event)
        if kind == "move":
            obj = event.get("obj")
            source, dest = event.get("from"), event.get("to")
            if source == "battlefield" and dest != "battlefield":
                sick.pop(obj, None)
            elif (
                dest == "battlefield"
                and source != "battlefield"
                and not event.get("inferred")
                and _can_be_sick(cards.get(event.get("card") or ""), facts)
            ):
                sick[obj] = event.get("controller")
                out.append(_event(event, "sick", [obj]))
        elif kind == "turn":
            active = event.get("active_seat")
            woke = [obj for obj, seat in sick.items() if seat == active]
            for obj in woke:
                sick.pop(obj, None)
            if woke:
                out.append(_event(event, "unsick", woke))
    if len(out) == len(events):
        return events
    for seq, event in enumerate(out):
        event["seq"] = seq
    return out
