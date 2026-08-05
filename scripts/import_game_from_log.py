#!/usr/bin/env python3
"""Import games from a Player.log (or an extracted slice of one) into the DB.

For games played while the tracker was off: extract the relevant lines from
Arena's Player.log (or pass the whole file) and run this natively on the
machine with Arena installed, so card names resolve during the replay:

    python3 scripts/import_game_from_log.py path/to/missed_game.log

The script replays the log through the normal tracker pipeline into the
default analytics DB (or --db PATH). Timestamps come from the log lines, so
games land with their real play times. Two guards prevent double-imports:
any Arena match UUID in the log that already exists in the DB aborts the
run, as does any already-recorded game with the same start time.
"""

from __future__ import annotations

import argparse
import io
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtga_tracker.analytics import AnalyticsStore  # noqa: E402
from mtga_tracker.log_parser import MTGALogParser  # noqa: E402
from mtga_tracker.paths import DATA_DIR  # noqa: E402
from mtga_tracker.tracker import CardTracker  # noqa: E402

_MATCH_ID_RE = re.compile(r'"matchId"\s*:\s*"([0-9a-f-]{36})"')
_EPOCH_MS_RE = re.compile(r'"timestamp"\s*:\s*"(\d{13})"')


def _scan_log(log_path: Path) -> tuple[list[str], datetime | None]:
    """Return (arena match UUIDs, first event time) found in the log."""
    match_ids: list[str] = []
    first_time: datetime | None = None
    with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            for match_id in _MATCH_ID_RE.findall(line):
                if match_id not in match_ids:
                    match_ids.append(match_id)
            if first_time is None:
                stamp = _EPOCH_MS_RE.search(line)
                if stamp:
                    first_time = datetime.fromtimestamp(int(stamp.group(1)) / 1000.0)
    return match_ids, first_time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log_file", type=Path, help="Player.log or an extracted slice of it")
    parser.add_argument(
        "--db",
        type=Path,
        default=DATA_DIR / "mtga_tracker.sqlite3",
        help="Analytics DB to import into (default: the tracker's own DB)",
    )
    args = parser.parse_args()

    if not args.log_file.is_file():
        print(f"Log file not found: {args.log_file}", file=sys.stderr)
        return 1

    match_ids, first_time = _scan_log(args.log_file)
    print(f"Log contains {len(match_ids)} Arena match(es).")

    # Guard 1: refuse when any of the log's Arena match UUIDs already exist.
    if args.db.is_file() and match_ids:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" for _ in match_ids)
            existing = [
                row[0]
                for row in conn.execute(
                    f"SELECT raw_match_id FROM matches WHERE raw_match_id IN ({placeholders})",
                    match_ids,
                )
            ]
        except sqlite3.Error:
            existing = []
        finally:
            conn.close()
        if existing:
            print(
                "Refusing to import: these matches are already in the DB:\n  "
                + "\n  ".join(existing),
                file=sys.stderr,
            )
            return 1

    quiet = io.StringIO()
    log_parser = MTGALogParser(log_path=str(args.log_file))
    tracker = CardTracker(log_parser=log_parser, output_stream=quiet)
    tracker._console_db_path = args.db
    tracker.analytics.close()
    tracker.analytics = AnalyticsStore(args.db)

    # The recovered session is stamped with the log's own start time so the
    # Sessions page shows when the games were played, not when imported.
    if first_time is not None:
        tracker.session_start_time = first_time
        tracker.session_id = first_time.strftime("%Y%m%dT%H%M%S%f")

    # Guard 2: refuse when a game with the log's start time is already saved
    # (covers rows written before raw_match_id existed).
    session_prefix = tracker.session_id

    log_parser.last_position = 0
    previous = -1
    while log_parser.last_position != previous:
        previous = log_parser.last_position
        tracker._process_new_events()
    tracker.analytics.close()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT g.id, g.started_at, g.outcome,
                   (SELECT display_name FROM participants p
                     WHERE p.game_id = g.id AND p.role = 'opponent') AS opponent,
                   (SELECT deck_name FROM participants p
                     WHERE p.game_id = g.id AND p.role = 'player') AS deck
            FROM games g
            WHERE g.id LIKE ?
            ORDER BY g.started_at
            """,
            (f"{session_prefix}%",),
        ).fetchall()
        duplicates = conn.execute(
            """
            SELECT started_at, COUNT(*) FROM games
            GROUP BY started_at HAVING COUNT(*) > 1
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No completed games were found in this log slice — nothing imported.")
        return 1
    print(f"Imported {len(rows)} game(s):")
    for game_id, started_at, outcome, opponent, deck in rows:
        print(f"  {started_at}  {outcome or '?':7s} vs {opponent or '?'}  ({deck or 'unknown deck'})")
    if duplicates:
        print(
            "WARNING: duplicate start times detected — a game may have been "
            "imported twice:",
            file=sys.stderr,
        )
        for started_at, count in duplicates:
            print(f"  {started_at} x{count}", file=sys.stderr)
    print("Done. Restart the tracker (or refresh the dashboard) to see it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
