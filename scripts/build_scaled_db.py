#!/usr/bin/env python3
"""Build a larger copy of a tracker database for scale tests.

    venv/bin/python scripts/build_scaled_db.py --factor 10 --out /tmp/scaled-10x.sqlite3
    venv/bin/python scripts/build_scaled_db.py --factor 30 --out /tmp/scaled-30x.sqlite3 --events

The output holds the source's history ``factor`` times: the original games
plus ``factor - 1`` replicas, each shifted a whole number of days further
into the past so the original stays the newest history. Replicas get their
own session, match, game and participant ids (a session id that is a
timestamp is shifted with its dates, so game ids still start with their
session's id) and their own opponent names, because a real long history
meets new opponents rather than the same ones again.

The source is opened read-only (``mode=ro`` URI plus ``query_only``) and
copied with SQLite's online backup, so it is safe while the tracker is live.

Not replicated, on purpose:

- ``console_logs`` and ``raw_game_payloads``: rolling 30-day windows that do
  not grow with the history.
- ``rank_snapshots``: a season's window comes from its snapshots' dates, so
  shifted copies would stretch every season across the whole history.
- ``game_events`` unless ``--events`` is given: it is most of the file, and
  the Overview, All Games and deck pages only ask whether a game has events.
  Without it replica games report no replay.
- Everything not keyed by a session, game or participant (``cards``, the Deck
  Manager library, settings rows).

The result is a test artifact with real deck and opponent names in it. Keep
it out of git.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "mtga_tracker.sqlite3"

#: Tables whose ``id`` is one of the ids replicas must not share.
CORE_TABLES = ("tracker_sessions", "matches", "games", "participants")
#: Columns holding one of those ids, in any table.
ID_COLUMNS = {
    "session_id",
    "match_id",
    "game_id",
    "participant_id",
    "winner_participant_id",
}
#: Never replicated; see the module docstring.
SKIPPED_TABLES = {"console_logs", "raw_game_payloads", "rank_snapshots", "live_status"}
EVENTS_TABLE = "game_events"
SESSION_ID_FORMAT = "%Y%m%dT%H%M%S%f"


def _columns(conn: sqlite3.Connection, table: str) -> List[Tuple[str, str, bool]]:
    """(name, declared type, is the integer primary key) per column."""
    rows = conn.execute(f'PRAGMA main.table_info("{table}")').fetchall()
    single_pk = sum(1 for row in rows if row[5]) == 1
    return [
        (
            str(row[1]),
            str(row[2] or ""),
            bool(row[5]) and single_pk and str(row[2] or "").upper() == "INTEGER",
        )
        for row in rows
    ]


def _is_date_column(name: str) -> bool:
    return name.endswith("_at") or name == "event_time"


def _replicated_tables(conn: sqlite3.Connection, events: bool) -> List[str]:
    """Core tables first (parents before children), then every other table
    keyed by a session, game or participant."""
    names = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    tables = [name for name in CORE_TABLES if name in names]
    for name in names:
        if name in CORE_TABLES or name in SKIPPED_TABLES:
            continue
        if name == EVENTS_TABLE and not events:
            continue
        if ID_COLUMNS & {column for column, _, _ in _columns(conn, name)}:
            tables.append(name)
    return tables


def _shift_timestamp(value: Optional[str], delta: timedelta) -> Optional[str]:
    """An ISO timestamp moved back by ``delta``, keeping its precision."""
    if not isinstance(value, str) or not value:
        return value
    try:
        moved = datetime.fromisoformat(value) - delta
    except ValueError:
        return value
    return moved.isoformat(timespec="microseconds" if "." in value else "seconds")


def _session_id_map(session_ids: List[str], replica: int, delta: timedelta) -> Dict[str, str]:
    """Each session id's replica id: the timestamp ids the tracker mints are
    shifted with the dates, anything else gets a ``~<replica>`` suffix."""
    mapping: Dict[str, str] = {}
    taken = set(session_ids)
    for session_id in session_ids:
        try:
            moved = datetime.strptime(session_id, SESSION_ID_FORMAT) - delta
            candidate = moved.strftime(SESSION_ID_FORMAT)
        except ValueError:
            candidate = f"{session_id}~{replica}"
        if candidate in taken:
            candidate = f"{session_id}~{replica}"
        taken.add(candidate)
        mapping[session_id] = candidate
    return mapping


def _id_remapper(
    sessions: Dict[str, str], replica: int
) -> Callable[[Optional[str]], Optional[str]]:
    """Tracker ids are ``<session id>:match:1:game:1...``; swap the session
    part. An id that does not start with a known session id is suffixed."""

    def remap(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value)
        head, separator, rest = text.partition(":")
        new_head = sessions.get(head)
        if new_head is None:
            return f"{text}~{replica}"
        return f"{new_head}{separator}{rest}"

    return remap


def scale_database(
    source: Path,
    out: Path,
    factor: int,
    *,
    events: bool = False,
    report: Optional[Callable[[str], None]] = None,
) -> Dict[str, int]:
    """Write ``out`` holding ``factor`` times the history of ``source``.
    Returns the game count and file size of the result."""
    if factor < 1:
        raise ValueError("factor must be at least 1")
    source = Path(source).expanduser().resolve()
    out = Path(out).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source database not found: {source}")
    if out == source:
        raise ValueError("The output must not be the source database")
    say = report or (lambda _message: None)
    for leftover in (out, Path(f"{out}-wal"), Path(f"{out}-shm"), Path(f"{out}-journal")):
        if leftover.exists():
            leftover.unlink()

    source_conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    try:
        source_conn.execute("PRAGMA query_only = ON")
        conn = sqlite3.connect(out.as_uri(), uri=True)
        source_conn.backup(conn)
    finally:
        source_conn.close()
    try:
        # A throwaway file: trade crash safety for build speed.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("ATTACH DATABASE ? AS src", (source.as_uri() + "?mode=ro",))
        session_ids = [str(row[0]) for row in conn.execute("SELECT id FROM src.tracker_sessions")]
        first, last = conn.execute(
            "SELECT MIN(COALESCE(started_at, ended_at)), MAX(COALESCE(started_at, ended_at)) "
            "FROM src.games"
        ).fetchone()
        try:
            span_days = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days + 1
        except (TypeError, ValueError):
            span_days = 365
        tables = _replicated_tables(conn, events)
        for replica in range(1, factor):
            delta = timedelta(days=span_days * replica)
            conn.create_function(
                "replica_id", 1, _id_remapper(_session_id_map(session_ids, replica, delta), replica)
            )
            conn.create_function(
                "replica_time", 1, lambda value, delta=delta: _shift_timestamp(value, delta)
            )
            conn.execute("BEGIN")
            for table in tables:
                names: List[str] = []
                selects: List[str] = []
                for name, _declared, integer_pk in _columns(conn, table):
                    if integer_pk:
                        continue  # SQLite assigns a new rowid
                    names.append(f'"{name}"')
                    if name in ID_COLUMNS or (name == "id" and table in CORE_TABLES):
                        selects.append(f'replica_id(s."{name}")')
                    elif _is_date_column(name):
                        selects.append(f'replica_time(s."{name}")')
                    elif name == "raw_match_id":
                        selects.append(f"s.\"{name}\" || '~{replica}'")
                    elif table == "participants" and name == "display_name":
                        selects.append(
                            f"CASE WHEN s.role = 'opponent' AND s.\"{name}\" IS NOT NULL "
                            f'THEN s."{name}" || \'~{replica}\' ELSE s."{name}" END'
                        )
                    else:
                        selects.append(f's."{name}"')
                conn.execute(
                    f'INSERT INTO main."{table}" ({", ".join(names)}) '
                    f'SELECT {", ".join(selects)} FROM src."{table}" s'
                )
            conn.execute("COMMIT")
            say(f"replica {replica} of {factor - 1} written")
        conn.execute("DETACH DATABASE src")
        # The app refreshes planner statistics at each launch (PRAGMA optimize);
        # a database that grew this large in real use would have current ones.
        conn.execute("ANALYZE")
        games = int(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    finally:
        conn.close()
    return {"games": games, "bytes": out.stat().st_size}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_DB, help="database to copy")
    parser.add_argument("--out", type=Path, required=True, help="file to write (replaced)")
    parser.add_argument("--factor", type=int, required=True, help="how many times the history")
    parser.add_argument(
        "--events", action="store_true", help="also replicate game_events (large, slow)"
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        result = scale_database(
            args.source, args.out, args.factor, events=args.events, report=print
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"{result['games']:,} games, {result['bytes'] / 1e6:.0f} MB, "
        f"{time.monotonic() - started:.1f} s: {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
