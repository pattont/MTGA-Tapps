#!/usr/bin/env python3
"""Test AI deck identification against your recent games' opponents.

Uses the provider and API key exactly as the tracker does (settings.json,
then config.py, then env) and prints the single best archetype guess per
game. One API call per game.

    python3 scripts/test_deck_ai.py           # last 5 games
    python3 scripts/test_deck_ai.py --games 10
    python3 scripts/test_deck_ai.py --game "<game id>"

Each card's color identity comes from the cards table, as the tracker sends
it; a reply naming a color no card had is dropped, like the tracker does.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mtga_tracker.colors import BASIC_LAND_COLORS  # noqa: E402
from mtga_tracker.deck_llm import (  # noqa: E402
    _build_prompt,
    _complete_raw,
    _parse_reply,
    diagnose,
    fits_seen_colors,
    last_error,
)
from mtga_tracker.paths import DATA_DIR  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--game", help="one game id instead of the latest games")
    parser.add_argument("--db", type=Path, default=DATA_DIR / "mtga_tracker.sqlite3")
    args = parser.parse_args()

    status = diagnose()
    print(
        f"Provider: {status['provider']} | model: {status['model']} | "
        f"enabled: {status['enabled']} | key: {status['has_api_key']} | "
        f"settings.json: {status['settings_file']}"
    )
    if not (status["enabled"] and status["has_api_key"]):
        print("Deck AI is not configured — use the Settings menu or config.py")
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    select = """
        SELECT g.id, g.started_at,
               (SELECT display_name FROM participants p
                 WHERE p.game_id = g.id AND p.role = 'opponent')
        FROM games g
    """
    if args.game:
        games = conn.execute(select + " WHERE g.id = ?", (args.game,)).fetchall()
    else:
        games = conn.execute(
            select + " ORDER BY g.started_at DESC LIMIT ?", (args.games,)
        ).fetchall()

    for game_id, started_at, opponent in games:
        colors = {}
        for name, identity in conn.execute(
            """
            SELECT DISTINCT s.display_name, c.color_identity
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id AND p.role = 'opponent'
            LEFT JOIN cards c ON c.id = s.card_id
            WHERE s.game_id = ?
            """,
            (game_id,),
        ):
            colors[name] = BASIC_LAND_COLORS.get(name.split(" (")[0], identity)
        cards = list(colors)
        print(f"\n{started_at} vs {opponent or '?'} — {len(cards)} cards seen")
        if len(cards) < 3:
            print("  (too few cards seen to guess)")
            continue
        known = {name: value for name, value in colors.items() if value is not None}
        raw = _complete_raw(_build_prompt(cards, known))
        guess = _parse_reply(raw)
        if guess and not fits_seen_colors(guess, colors):
            print(f"  (dropped {guess!r}: names a color no card had)")
        elif guess:
            print(f"  → {guess}")
        else:
            print(f"  (no guess) error: {last_error() or 'none reported'}")
            if raw:
                print(f"  raw reply: {raw[:300]}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
