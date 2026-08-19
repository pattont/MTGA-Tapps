#!/usr/bin/env python3
"""Probe Arena's local Raw_CardDatabase for the mana-cost column and format.

Run this on a machine with MTG Arena installed to verify the tracker's
mana-cost extraction (CardDatabase.mana_cost_index_by_name):

    venv/bin/python scripts/probe_mtga_card_db.py

Prints the Cards table schema, which cost column the tracker would pick, raw
sample values with their parsed Scryfall-notation results (including hybrid
costs when present), and a parse-success rate over the whole table. No
tracker data is touched — the Arena DB is opened read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mtga_tracker.card_database import CardDatabase  # noqa: E402


def main() -> int:
    card_db = CardDatabase()
    db_path = card_db._resolve_mtga_db_path()
    if not db_path:
        print("✗ Arena card database not found (is MTGA installed?)")
        return 1
    print(f"Arena card DB: {db_path}\n")

    conn = card_db._connect_mtga_db(db_path)
    cur = conn.cursor()
    cur.execute('PRAGMA table_info("Cards")')
    columns = [str(row[1]) for row in cur.fetchall()]
    print(f"Cards table columns ({len(columns)}):")
    print("  " + ", ".join(columns) + "\n")

    cost_column = next(
        (c for c in CardDatabase._MANA_COST_COLUMN_CANDIDATES if c in columns), None
    )
    if cost_column is None:
        cost_column = next(
            (
                c
                for c in sorted(columns)
                if "manatext" in c.lower() or "castingcost" in c.lower()
            ),
            None,
        )
    if cost_column is None:
        print("✗ No cost-like column found — paste the column list above into the issue.")
        return 1
    print(f"Chosen cost column: {cost_column}\n")

    cur.execute(
        f'SELECT l."loc", c."{cost_column}" FROM "Cards" c '
        'JOIN "Localizations_enUS" l ON c."TitleId" = l."LocId" '
        f'WHERE c."{cost_column}" IS NOT NULL AND TRIM(c."{cost_column}") != \'\''
    )
    rows = cur.fetchall()
    conn.close()

    parsed_ok = 0
    failures = []
    hybrids = []
    samples = []
    for name, raw in rows:
        result = CardDatabase.parse_arena_mana_cost(raw)
        if result is None:
            if len(failures) < 10:
                failures.append((name, raw))
            continue
        parsed_ok += 1
        if len(samples) < 8:
            samples.append((name, raw, result))
        if "/" in result[0] and len(hybrids) < 8:
            hybrids.append((name, raw, result))

    print(f"Parsed {parsed_ok}/{len(rows)} non-empty costs "
          f"({100.0 * parsed_ok / max(1, len(rows)):.1f}%)\n")
    print("Samples (name | raw | parsed cost | mana value):")
    for name, raw, (cost, value) in samples:
        print(f"  {name!r} | {raw!r} | {cost} | {value:g}")
    if hybrids:
        print("\nHybrid samples:")
        for name, raw, (cost, value) in hybrids:
            print(f"  {name!r} | {raw!r} | {cost} | {value:g}")
    if failures:
        print("\n⚠ Unparsed samples (paste these back if the rate is low):")
        for name, raw in failures:
            print(f"  {name!r} | {raw!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
