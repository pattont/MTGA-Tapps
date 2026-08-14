#!/usr/bin/env python3
"""Backfill removal/wipe/bounce/counter played+drawn stats for old games.

Games tracked before the removal/counter features have NULL role-based
columns (removal_played, wipes_played, bounces_played, counters_played and
the matching *_drawn columns).  Each game's per-card play/draw counts are
already stored in game_card_summary and game_drawn_cards, so those columns
can be recomputed by classifying each card's Arena rules text — exactly the
classification live tracking uses.

Requires the Arena card database on this machine (same requirement as live
classification).  Only NULL columns are filled; live-tracked games are never
overwritten.  The behavioral stats (creatures/non-creatures removed and
bounced, lands, spells countered) are backfilled automatically by schema
migration v19 — this script covers only the text-classification half.

Quit the tracker before running this. Dry run by default:

    python3 scripts/backfill_card_role_stats.py          # report what would change
    python3 scripts/backfill_card_role_stats.py --yes    # actually write
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtga_tracker.card_database import CardDatabase  # noqa: E402
from mtga_tracker.paths import DATA_DIR  # noqa: E402
from mtga_tracker.removal_classifier import (  # noqa: E402
    ROLE_BOUNCE,
    ROLE_COUNTER,
    ROLE_REMOVAL,
    ROLE_WIPE,
    RemovalClassifier,
)

#: role -> (played column, drawn column)
_ROLE_COLUMNS = {
    ROLE_REMOVAL: ("removal_played", "removal_drawn"),
    ROLE_WIPE: ("wipes_played", "wipes_drawn"),
    ROLE_BOUNCE: ("bounces_played", "bounces_drawn"),
    ROLE_COUNTER: ("counters_played", "counters_drawn"),
}
_ALL_COLUMNS = tuple(col for pair in _ROLE_COLUMNS.values() for col in pair)


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
        help="Actually write (without this flag, just report)",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    classifier = RemovalClassifier(CardDatabase())
    conn = sqlite3.connect(args.db)
    try:
        arena_id_by_card = {
            int(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT id, arena_id FROM cards WHERE arena_id IS NOT NULL"
            )
        }

        # Candidate rows: any participant stats row with a NULL role column.
        candidates = conn.execute(
            "SELECT s.game_id, s.participant_id, p.role FROM game_participant_stats s "
            "JOIN participants p ON p.id = s.participant_id "
            "WHERE " + " OR ".join(f"s.{col} IS NULL" for col in _ALL_COLUMNS)
        ).fetchall()
        if not candidates:
            print("No NULL role-stat columns found — nothing to backfill.")
            return 0

        classified_any = False
        updated = 0
        for game_id, participant_id, role in candidates:
            played = defaultdict(int)
            drawn = defaultdict(int)
            for card_id, played_count, drawn_count in conn.execute(
                "SELECT card_id, played_count, drawn_count FROM game_card_summary "
                "WHERE game_id = ? AND participant_id = ?",
                (game_id, participant_id),
            ):
                arena_id = arena_id_by_card.get(card_id) if card_id is not None else None
                if arena_id is None:
                    continue
                roles = classifier.roles_for(arena_id)
                if roles:
                    classified_any = True
                for card_role in roles:
                    played[card_role] += int(played_count or 0)
                    drawn[card_role] += int(drawn_count or 0)

            values = {}
            for card_role, (played_col, drawn_col) in _ROLE_COLUMNS.items():
                values[played_col] = played.get(card_role, 0)
                # Opponent draws are hidden information — never fill their
                # drawn columns (matches live tracking).
                if role == "player":
                    values[drawn_col] = drawn.get(card_role, 0)

            if args.yes:
                assignments = ", ".join(
                    f"{col} = COALESCE({col}, ?)" for col in values
                )
                conn.execute(
                    f"UPDATE game_participant_stats SET {assignments} "
                    "WHERE game_id = ? AND participant_id = ?",
                    tuple(values.values()) + (game_id, participant_id),
                )
            updated += 1

        if not classified_any:
            print(
                "⚠️  No card classified into any role — the Arena card database "
                "was probably not found. Nothing useful would be written; aborting."
            )
            conn.rollback()
            return 1

        if args.yes:
            conn.commit()
            print(f"Backfilled role stats for {updated} participant row(s).")
        else:
            print(
                f"Would backfill role stats for {updated} participant row(s). "
                "Re-run with --yes to write."
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
