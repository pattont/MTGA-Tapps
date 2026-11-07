"""Repair of log timestamps stored with month and day swapped.

Arena writes ambiguous slash dates (11/4/2026), and trackers that read them in
the wrong field order stored 4 November as 11 April. Every row belongs to a
tracker session whose id is minted from the system clock (never from the
log), so that id anchors reality: a timestamp far from its session whose
month/day swap lands next to the session was mis-read. Conservative on
purpose: anything ambiguous is left alone, and a repaired row sits next to
its session, so running the repair again changes nothing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence, Tuple

#: (table, timestamp columns, SQL producing "<rowid>, <session id>,
#: <session started_at>, <columns...>") for every log-derived timestamp.
SWAPPED_DATE_TARGETS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    (
        "tracker_sessions",
        ("started_at", "ended_at"),
        "SELECT s.id, s.id, NULL, s.started_at, s.ended_at FROM tracker_sessions s",
    ),
    (
        "matches",
        ("started_at", "ended_at"),
        "SELECT m.id, s.id, s.started_at, m.started_at, m.ended_at FROM matches m "
        "JOIN tracker_sessions s ON s.id = m.session_id",
    ),
    (
        "games",
        ("started_at", "ended_at"),
        "SELECT g.id, s.id, s.started_at, g.started_at, g.ended_at FROM games g "
        "JOIN tracker_sessions s ON s.id = g.session_id",
    ),
    (
        "game_turns",
        ("started_at", "ended_at"),
        "SELECT t.id, s.id, s.started_at, t.started_at, t.ended_at FROM game_turns t "
        "JOIN games g ON g.id = t.game_id "
        "JOIN tracker_sessions s ON s.id = g.session_id",
    ),
    (
        "game_events",
        ("event_time",),
        "SELECT e.id, s.id, s.started_at, e.event_time FROM game_events e "
        "JOIN tracker_sessions s ON s.id = e.session_id",
    ),
    (
        "console_logs",
        ("created_at",),
        "SELECT c.id, s.id, s.started_at, c.created_at FROM console_logs c "
        "JOIN tracker_sessions s ON s.id = c.session_id",
    ),
    (
        "rank_snapshots",
        ("captured_at",),
        "SELECT r.id, s.id, s.started_at, r.captured_at FROM rank_snapshots r "
        "JOIN tracker_sessions s ON s.id = r.session_id",
    ),
    (
        "raw_game_payloads",
        ("created_at",),
        "SELECT p.id, s.id, s.started_at, p.created_at FROM raw_game_payloads p "
        "JOIN tracker_sessions s ON s.id = p.session_id",
    ),
)

# A legitimate timestamp sits this close to its session's start...
_NEAR_SESSION = timedelta(days=5)
# ...and a swapped one is repaired only when the swap lands in this window:
# the previous day (log lines read at startup) through a multi-day session.
_SWAP_BEFORE = timedelta(days=2)
_SWAP_AFTER = timedelta(days=3)


def session_clock_time(session_id: object) -> Optional[datetime]:
    """The system-clock time a session id was minted at (`%Y%m%dT%H%M%S%f`)."""
    text = str(session_id or "")
    if len(text) < 15 or text[8:9] != "T":
        return None
    try:
        return datetime.strptime(text[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def session_anchor(session_id: object, started_at: object) -> Optional[datetime]:
    """The trustworthy start of a session.

    The id comes from the system clock. started_at is only a fallback (for
    ids in another shape): a session that began after a break takes its
    started_at from log time, which may itself be swapped.
    """
    anchor = session_clock_time(session_id)
    if anchor is not None:
        return anchor
    try:
        return datetime.fromisoformat(str(started_at))
    except (TypeError, ValueError):
        return None


def swapped_date_repair(value: object, session_start: datetime) -> Optional[str]:
    """Return the month/day-swapped timestamp when that is clearly the truth."""
    text = str(value or "")
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is not None:
        return None  # tracker timestamps are naive local time
    if abs(stamp - session_start) <= _NEAR_SESSION:
        return None  # close enough to the session to be legitimate
    if stamp.day > 12 or stamp.day == stamp.month:
        return None  # swapping would produce month > 12, or change nothing
    try:
        swapped = stamp.replace(month=stamp.day, day=stamp.month)
    except ValueError:
        return None
    if -_SWAP_BEFORE <= swapped - session_start <= _SWAP_AFTER:
        return swapped.isoformat()
    return None


def repair_swapped_log_dates(
    conn: sqlite3.Connection,
    *,
    session_ids: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> int:
    """Repair (or with `dry_run`, count) rows with month/day-swapped dates.

    `session_ids` limits the repair to those sessions (rows just merged in
    from a backup). Returns the number of rows changed or needing a change.
    Runs inside the caller's transaction; it never commits.
    """
    only: Optional[set] = None if session_ids is None else {str(s) for s in session_ids}
    if only is not None and not only:
        return 0
    tables = {
        str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    repaired = 0
    for table, columns, query in SWAPPED_DATE_TARGETS:
        if table not in tables:
            continue
        for row in conn.execute(query).fetchall():
            row_id, session_id, session_started = row[0], row[1], row[2]
            if only is not None and str(session_id) not in only:
                continue
            anchor = session_anchor(session_id, session_started)
            if anchor is None:
                continue
            updates = _row_updates(columns, row[3:], anchor)
            if not updates:
                continue
            repaired += 1
            if dry_run:
                continue
            assignments = ", ".join(f"{column} = ?" for column in updates)
            conn.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                tuple(updates.values()) + (row_id,),
            )
    return repaired


def _row_updates(
    columns: Sequence[str], values: Sequence[object], anchor: datetime
) -> "dict[str, str]":
    updates = {}
    for column, value in zip(columns, values):
        fixed = swapped_date_repair(value, anchor)
        if fixed is not None:
            updates[column] = fixed
    return updates
