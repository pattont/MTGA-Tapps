#!/usr/bin/env python3
"""Delete one match (and all of its games' data) from the analytics DB.

For surgically removing a corrupted match before re-importing it with
scripts/import_game_from_log.py. Quit the tracker before running this.

    python3 scripts/delete_match.py "20260807T000026964924:match:4"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtga_tracker.paths import DATA_DIR  # noqa: E402

CHILD_TABLES = (
    "game_card_summary",
    "game_deck_cards",
    "game_opening_hand_cards",
    "game_mulligan_hands",
    "game_drawn_cards",
    "game_events",
    "game_turns",
    "game_participant_stats",
    "game_annotations",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("match_id", help="Tracker match id, e.g. <session>:match:4")
    parser.add_argument(
        "--db",
        type=Path,
        default=DATA_DIR / "mtga_tracker.sqlite3",
        help="Analytics DB (default: the tracker's own DB)",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    try:
        games = [
            str(row[0])
            for row in conn.execute("SELECT id FROM games WHERE match_id = ?", (args.match_id,))
        ]
        match_row = conn.execute(
            "SELECT raw_match_id FROM matches WHERE id = ?", (args.match_id,)
        ).fetchone()
        if not games and match_row is None:
            print(f"No match found with id: {args.match_id}", file=sys.stderr)
            return 1
        print(f"Match {args.match_id} (arena {match_row[0] if match_row else '?'}):")
        for game_id in games:
            print(f"  deleting game {game_id}")
        with conn:
            for game_id in games:
                conn.execute(
                    "DELETE FROM participant_commanders WHERE participant_id IN "
                    "(SELECT id FROM participants WHERE game_id = ?)",
                    (game_id,),
                )
                for table_name in CHILD_TABLES:
                    conn.execute(f"DELETE FROM {table_name} WHERE game_id = ?", (game_id,))
                conn.execute("DELETE FROM participants WHERE game_id = ?", (game_id,))
                conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
            conn.execute("DELETE FROM matches WHERE id = ?", (args.match_id,))
        print("Done. Re-import the real games with scripts/import_game_from_log.py.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
