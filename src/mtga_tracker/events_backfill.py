"""Backfill behavioral combat stats from the game_events timeline.

Historical games were tracked before removal/bounce/land/counter stats
existed, but their structured timelines (game_events) already recorded the
underlying actions.  This module recomputes the stats that need no card-text
classification and fills ONLY NULL columns in game_participant_stats, so
live-tracked values are never overwritten.

Deliberate limitations (documented undercounts, matching what the timeline
can actually support):

- Lethal-damage deaths are skipped: after the fact, a burn kill cannot be
  told apart from a combat death.
- Forced sacrifices (edicts) are skipped: the timeline does not say who
  forced the sacrifice.
- Exiles and bounces only count for cards previously seen hitting the
  battlefield in the same game (Exile/Return also fire for impulse draws,
  graveyard recursion, and similar non-removal transfers).
- Rows are only UPDATEd, never INSERTed: a game without a stats row has no
  combat telemetry and should keep looking that way.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Dict, Iterable, Optional, Set

#: Stat columns this module can compute from the timeline.
BACKFILL_COLUMNS = (
    "creatures_removed",
    "noncreatures_removed",
    "creatures_bounced",
    "noncreatures_bounced",
    "lands_lost",
    "lands_replaced",
    "spells_countered",
)

_DESTROYED_RE = re.compile(r"\[([^\]]+)\] was destroyed\b")
_ZERO_TOUGHNESS_RE = re.compile(r"\[([^\]]+)\] was put into graveyard \(0 toughness\)")
#: Deaths that leave the battlefield WITHOUT counting as removal: combat /
#: lethal damage, sacrifices (forcer unknowable from text), aura/loyalty SBAs.
_LEAVES_BATTLEFIELD_RE = re.compile(
    r"\[([^\]]+)\] was (?:put into graveyard \((?!0 toughness)[^)]*\)|sacrificed)"
)
_EXILED_RE = re.compile(r"\[([^\]]+)\] was exiled\b")
_RETURN_OWNED_RE = re.compile(r"returned \[([^\]]+)\] to (your|opponent's) hand\b")
_RETURN_PLAIN_RE = re.compile(r"returned \[([^\]]+)\] to hand\b")
_CAST_OR_PLAYED_RE = re.compile(r"(?:cast|played) \[([^\]]+)\]")
_PUT_BATTLEFIELD_RE = re.compile(r"put \[([^\]]+)\] onto battlefield")
_STACK_COUNTERED_RE = re.compile(r"Stack: \[([^\]]+)\].*\[countered\]")
#: Trailing "(Creature 2/4)"-style display suffix on cast/played labels.
_LABEL_SUFFIX_RE = re.compile(r"\s*\([^()]*\)$")

#: primary_type values that can never be lost to removal or bounced.
_NON_PERMANENT_TYPES = {"Instant", "Sorcery"}

_ROLES = ("player", "opponent")


def _strip_label(label: str) -> str:
    """Drop the display-type suffix from a cast/played card label."""
    return _LABEL_SUFFIX_RE.sub("", str(label or "")).strip()


def _card_types(conn: sqlite3.Connection) -> Dict[str, Optional[str]]:
    """Map display name -> primary_type from the cards table."""
    return {
        str(row[0]): (str(row[1]) if row[1] is not None else None)
        for row in conn.execute("SELECT name, primary_type FROM cards")
    }


def _game_ids_with_events(conn: sqlite3.Connection) -> Iterable[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT game_id FROM game_events WHERE game_id IS NOT NULL"
        )
    ]


def compute_game_stats_from_events(
    conn: sqlite3.Connection,
    game_id: str,
    types_by_name: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Dict[str, int]]:
    """Recompute the BACKFILL_COLUMNS stats for one game from its timeline."""
    if types_by_name is None:
        types_by_name = _card_types(conn)
    counts: Dict[str, Dict[str, int]] = {role: defaultdict(int) for role in _ROLES}
    seen_on_battlefield: Dict[str, Set[str]] = {role: set() for role in _ROLES}
    pending_land: Dict[str, list] = {role: [] for role in _ROLES}
    last_caster_by_name: Dict[str, str] = {}

    rows = conn.execute(
        """
        SELECT turn_number, actor_role, event_type, text
        FROM game_events
        WHERE game_id = ?
        ORDER BY event_time, id
        """,
        (game_id,),
    )
    for turn_number, actor_role, event_type, text in rows:
        actor = str(actor_role) if actor_role in _ROLES else None
        event_kind = str(event_type or "")
        line = str(text or "")
        turn = int(turn_number) if turn_number is not None else 0

        if event_kind in ("cast", "land") and actor:
            match = _CAST_OR_PLAYED_RE.search(line)
            if match:
                name = _strip_label(match.group(1))
                seen_on_battlefield[actor].add(name)
                last_caster_by_name[name] = actor
            if event_kind == "land":
                # A land drop answers the oldest live destruction watch, and
                # expired watches stay unreplaced — mirrors live tracking.
                live = [d for d in pending_land[actor] if d >= turn]
                if live:
                    live.sort()
                    live.pop(0)
                    counts[actor]["lands_replaced"] += 1
                pending_land[actor] = live
            continue

        if event_kind == "stack_fail":
            match = _STACK_COUNTERED_RE.search(line)
            if match:
                name = _strip_label(match.group(1))
                caster = last_caster_by_name.get(name)
                if caster:
                    counts[caster]["spells_countered"] += 1
            continue

        if event_kind != "zone" or not actor:
            continue

        put_match = _PUT_BATTLEFIELD_RE.search(line)
        if put_match:
            seen_on_battlefield[actor].add(_strip_label(put_match.group(1)))
            continue

        is_cost = " as cost" in line

        # Any death-shaped event takes the card off the battlefield-seen set,
        # so later graveyard recursion ("returned [X] to hand", exiled from
        # graveyard) cannot be mistaken for battlefield removal or bounce.
        left = _LEAVES_BATTLEFIELD_RE.search(line)
        if left:
            seen_on_battlefield[actor].discard(left.group(1).strip())
            continue

        destroyed = None if is_cost else (
            _DESTROYED_RE.search(line) or _ZERO_TOUGHNESS_RE.search(line)
        )
        if destroyed:
            name = destroyed.group(1).strip()
            seen_on_battlefield[actor].discard(name)
            primary_type = types_by_name.get(name)
            if primary_type == "Land":
                counts[actor]["lands_lost"] += 1
                pending_land[actor].append(turn + 2)
            elif primary_type == "Creature":
                counts[actor]["creatures_removed"] += 1
            elif primary_type not in _NON_PERMANENT_TYPES:
                counts[actor]["noncreatures_removed"] += 1
            continue

        exiled = _EXILED_RE.search(line)
        if exiled:
            name = exiled.group(1).strip()
            was_on_battlefield = name in seen_on_battlefield[actor]
            seen_on_battlefield[actor].discard(name)
            primary_type = types_by_name.get(name)
            if (
                not is_cost
                and was_on_battlefield
                and primary_type not in _NON_PERMANENT_TYPES
                and primary_type != "Land"
            ):
                if primary_type == "Creature":
                    counts[actor]["creatures_removed"] += 1
                else:
                    counts[actor]["noncreatures_removed"] += 1
            continue

        owned_return = _RETURN_OWNED_RE.search(line)
        plain_return = None if owned_return else _RETURN_PLAIN_RE.search(line)
        if owned_return or plain_return:
            if owned_return:
                name = owned_return.group(1).strip()
                owner = "player" if owned_return.group(2) == "your" else "opponent"
            else:
                name = plain_return.group(1).strip()
                owner = actor
            was_on_battlefield = name in seen_on_battlefield[owner]
            seen_on_battlefield[owner].discard(name)
            primary_type = types_by_name.get(name)
            if (
                not is_cost
                and was_on_battlefield
                and primary_type not in _NON_PERMANENT_TYPES
            ):
                if primary_type == "Creature":
                    counts[owner]["creatures_bounced"] += 1
                else:
                    counts[owner]["noncreatures_bounced"] += 1

    return counts


def backfill_game_stats_from_events(
    conn: sqlite3.Connection,
    game_ids: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> int:
    """Fill NULL behavioral stat columns for games that have a timeline.

    Returns the number of game_participant_stats rows updated (or that WOULD
    be updated when dry_run is True).
    """
    types_by_name = _card_types(conn)
    targets = list(game_ids) if game_ids is not None else _game_ids_with_events(conn)
    assignments = ", ".join(
        f"{column} = COALESCE({column}, ?)" for column in BACKFILL_COLUMNS
    )
    updated = 0
    for game_id in targets:
        participant_by_role = {
            str(row[1]): str(row[0])
            for row in conn.execute(
                "SELECT id, role FROM participants WHERE game_id = ?", (game_id,)
            )
        }
        if not participant_by_role:
            continue
        counts = compute_game_stats_from_events(conn, game_id, types_by_name)
        for role, participant_id in participant_by_role.items():
            if role not in counts:
                continue
            needs_fill = conn.execute(
                "SELECT "
                + ", ".join(BACKFILL_COLUMNS)
                + " FROM game_participant_stats WHERE game_id = ? AND participant_id = ?",
                (game_id, participant_id),
            ).fetchone()
            if needs_fill is None or all(value is not None for value in needs_fill):
                continue
            if dry_run:
                updated += 1
                continue
            cursor = conn.execute(
                f"UPDATE game_participant_stats SET {assignments} "
                "WHERE game_id = ? AND participant_id = ?",
                tuple(counts[role].get(column, 0) for column in BACKFILL_COLUMNS)
                + (game_id, participant_id),
            )
            updated += cursor.rowcount
    return updated
