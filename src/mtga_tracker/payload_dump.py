"""Dump raw payload archive rows as readable JSON.

The archive is stored zlib-compressed (see payload_codec), so browsing
raw_game_payloads with plain SQL shows binary blobs. This utility decodes
rows for inspection:

    venv/bin/python -m mtga_tracker.payload_dump <game_id>
    venv/bin/python -m mtga_tracker.payload_dump <game_id> --db path/to.sqlite3
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .paths import DATA_DIR
from .payload_codec import decode_payload

DEFAULT_DB_PATH = DATA_DIR / "mtga_tracker.sqlite3"


def dump_payloads(db_path: Path, game_id: str) -> int:
    """Print every archived payload for one game; returns the row count."""
    uri = db_path.expanduser().resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, payload_type, payload_json
            FROM raw_game_payloads
            WHERE game_id = ?
            ORDER BY id
            """,
            (game_id,),
        ).fetchall()
    finally:
        conn.close()
    for row_id, created_at, payload_type, payload in rows:
        print(f"--- payload {row_id} · {created_at} · {payload_type or 'unknown'} ---")
        print(decode_payload(payload))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_id", help="games.id whose payloads to dump")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path.")
    args = parser.parse_args(argv)
    count = dump_payloads(args.db, args.game_id)
    if not count:
        print(f"No archived payloads for game {args.game_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
