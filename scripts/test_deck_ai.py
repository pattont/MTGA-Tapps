#!/usr/bin/env python3
"""Test AI deck identification against your recent games' opponents.

Uses the provider and API key from config.py (project root) exactly as the
tracker does, and prints the top-3 archetype candidates per game. One API
call per game.

    python3 scripts/test_deck_ai.py           # last 5 games
    python3 scripts/test_deck_ai.py --games 10
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtga_tracker.deck_llm import diagnose, identify_deck_candidates  # noqa: E402
from mtga_tracker.paths import DATA_DIR  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--db", type=Path, default=DATA_DIR / "mtga_tracker.sqlite3")
    args = parser.parse_args()

    status = diagnose()
    print(f"Provider: {status['provider']} | enabled: {status['enabled']} | key: {status['has_api_key']}")
    if not (status["enabled"] and status["has_api_key"]):
        print("Deck AI is not configured — set DECK_LLM_ENABLED and an API key in config.py")
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    games = conn.execute(
        """
        SELECT g.id, g.started_at,
               (SELECT display_name FROM participants p
                 WHERE p.game_id = g.id AND p.role = 'opponent')
        FROM games g ORDER BY g.started_at DESC LIMIT ?
        """,
        (args.games,),
    ).fetchall()

    for game_id, started_at, opponent in games:
        cards = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT s.display_name
                FROM game_card_summary s
                JOIN participants p ON p.id = s.participant_id AND p.role = 'opponent'
                WHERE s.game_id = ?
                """,
                (game_id,),
            )
        ]
        print(f"\n{started_at} vs {opponent or '?'} — {len(cards)} cards seen")
        if len(cards) < 3:
            print("  (too few cards seen to guess)")
            continue
        candidates = identify_deck_candidates(cards)
        if candidates:
            for rank, name in enumerate(candidates, 1):
                print(f"  {rank}. {name}")
        else:
            print("  (no guess — check key, model, or rate limits)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
