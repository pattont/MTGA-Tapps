#!/usr/bin/env python3
"""Delete games recorded without combat telemetry (early tracker versions).

Games saved before the tracker recorded game_participant_stats have no
damage/attack/draw aggregates, so they appear in game counts (How Games End)
but not in combat tables (Wins vs Losses), making the totals look wrong.
This removes those games entirely so every table counts the same history.

Quit the tracker before running this. Dry run by default:

    python3 scripts/delete_untelemetered_games.py            # list what would go
    python3 scripts/delete_untelemetered_games.py --yes      # actually delete
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtga_tracker.analytics import AnalyticsStore  # noqa: E402
from mtga_tracker.paths import DATA_DIR  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db",
        type=Path,
        default=DATA_DIR / "mtga_tracker.sqlite3",
        help="Analytics DB (default: the tracker's own DB)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete (without this flag, just list the games)",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            """
            SELECT g.id, COALESCE(g.started_at, g.ended_at, '?') AS started, g.outcome
            FROM games g
            WHERE NOT EXISTS (
              SELECT 1
              FROM game_participant_stats s
              JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
              WHERE s.game_id = g.id
            )
            ORDER BY started
            """
        ).fetchall()
        if not rows:
            print("Every game has combat telemetry — nothing to delete.")
            return 0

        wins = sum(1 for row in rows if row[2] == "win")
        losses = sum(1 for row in rows if row[2] == "loss")
        other = len(rows) - wins - losses
        print(f"Games without combat telemetry: {len(rows)} ({wins} wins, {losses} losses, {other} other)")
        for game_id, started, outcome in rows:
            print(f"  {started}  {outcome or 'unknown':8}  {game_id}")

        if not args.yes:
            print("\nDry run — re-run with --yes to delete these games.")
            return 0

        AnalyticsStore._delete_games_and_recompute_sessions(
            conn, [str(row[0]) for row in rows]
        )
        conn.commit()
        print(f"\nDeleted {len(rows)} game(s); emptied matches dropped and session totals recomputed.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
