"""Draw-quality analytics over captured opening hands and visible draws."""

from __future__ import annotations

import argparse
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .analytics import AnalyticsStore
from .analytics_persistence import analytics_card_base_name

DEFAULT_DB_PATH = Path("data/mtga_tracker.sqlite3")


@dataclass(frozen=True)
class DrawQualityGame:
    """Per-game draw quality summary."""

    game_id: str
    started_at: Optional[str]
    deck_name: Optional[str]
    outcome: Optional[str]
    deck_size: int
    opening_cards: int
    known_draws: int
    cards_seen: int
    lands_seen: int
    land_rate_seen: float
    flood_probability: Optional[float]
    screw_probability: Optional[float]
    target_card: Optional[str] = None
    target_card_seen: int = 0
    target_card_probability: Optional[float] = None


@dataclass(frozen=True)
class DrawQualityResult:
    """Aggregate result for recent games."""

    total_games: int
    games: List[DrawQualityGame]


def _hypergeom_pmf(
    successes_seen: int,
    *,
    population_size: int,
    success_count: int,
    draw_count: int,
) -> float:
    """Return P(X = successes_seen) for a hypergeometric draw."""
    if population_size <= 0 or draw_count < 0 or success_count < 0:
        return 0.0
    if success_count > population_size or draw_count > population_size:
        return 0.0
    failures = population_size - success_count
    if successes_seen < 0 or successes_seen > success_count:
        return 0.0
    if draw_count - successes_seen < 0 or draw_count - successes_seen > failures:
        return 0.0
    return (
        math.comb(success_count, successes_seen)
        * math.comb(failures, draw_count - successes_seen)
        / math.comb(population_size, draw_count)
    )


def hypergeom_tail_at_least(
    successes_seen: int,
    *,
    population_size: int,
    success_count: int,
    draw_count: int,
) -> float:
    """Return P(X >= successes_seen) for a hypergeometric draw."""
    if draw_count <= 0:
        return 1.0 if successes_seen <= 0 else 0.0
    max_successes = min(success_count, draw_count)
    return sum(
        _hypergeom_pmf(
            value,
            population_size=population_size,
            success_count=success_count,
            draw_count=draw_count,
        )
        for value in range(max(0, successes_seen), max_successes + 1)
    )


def hypergeom_tail_at_most(
    successes_seen: int,
    *,
    population_size: int,
    success_count: int,
    draw_count: int,
) -> float:
    """Return P(X <= successes_seen) for a hypergeometric draw."""
    if draw_count <= 0:
        return 1.0 if successes_seen >= 0 else 0.0
    max_successes = min(success_count, draw_count, successes_seen)
    return sum(
        _hypergeom_pmf(
            value,
            population_size=population_size,
            success_count=success_count,
            draw_count=draw_count,
        )
        for value in range(0, max_successes + 1)
    )


def _rows(conn: sqlite3.Connection, query: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(query, tuple(params)).fetchall())


def _is_land(row: sqlite3.Row) -> bool:
    type_category = str(row["type_category"] or "")
    display_name = str(row["display_name"] or "")
    return type_category == "Land" or display_name.endswith("(Land)")


def _count_target(rows: Iterable[sqlite3.Row], target_card: Optional[str]) -> int:
    target_base = analytics_card_base_name(target_card or "").casefold()
    if not target_base:
        return 0
    return sum(
        1
        for row in rows
        if analytics_card_base_name(str(row["display_name"] or "")).casefold() == target_base
    )


def analyze_draw_quality(
    db_path: Path | str = DEFAULT_DB_PATH,
    *,
    target_card: Optional[str] = None,
    expected_land_rate: float = 0.37,
    target_card_copies: int = 4,
    limit: int = 25,
) -> DrawQualityResult:
    """Analyze recent games using captured opening hand cards plus visible drawn cards."""
    db_path = Path(db_path)
    games: List[DrawQualityGame] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        AnalyticsStore.ensure_schema(conn)
        game_rows = _rows(
            conn,
            """
            SELECT
                g.id AS game_id,
                g.started_at,
                g.outcome,
                p.id AS participant_id,
                p.deck_name,
                COALESCE(p.deck_size, 60) AS deck_size
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        for game_row in game_rows:
            participant_id = game_row["participant_id"]
            opening_rows = _rows(
                conn,
                """
                SELECT display_name, type_category
                FROM game_opening_hand_cards
                WHERE participant_id = ?
                ORDER BY hand_position
                """,
                (participant_id,),
            )
            draw_rows = _rows(
                conn,
                """
                SELECT display_name, type_category
                FROM game_drawn_cards
                WHERE participant_id = ?
                ORDER BY draw_position
                """,
                (participant_id,),
            )
            seen_rows = opening_rows + draw_rows
            deck_size = int(game_row["deck_size"] or 60)
            cards_seen = len(seen_rows)
            lands_seen = sum(1 for row in seen_rows if _is_land(row))
            expected_lands = max(0, min(deck_size, round(deck_size * expected_land_rate)))
            flood_probability = None
            screw_probability = None
            if cards_seen:
                flood_probability = hypergeom_tail_at_least(
                    lands_seen,
                    population_size=deck_size,
                    success_count=expected_lands,
                    draw_count=cards_seen,
                )
                screw_probability = hypergeom_tail_at_most(
                    lands_seen,
                    population_size=deck_size,
                    success_count=expected_lands,
                    draw_count=cards_seen,
                )

            target_seen = _count_target(seen_rows, target_card)
            target_probability = None
            if target_card and cards_seen:
                target_probability = hypergeom_tail_at_least(
                    target_seen,
                    population_size=deck_size,
                    success_count=max(0, min(deck_size, target_card_copies)),
                    draw_count=cards_seen,
                )

            games.append(
                DrawQualityGame(
                    game_id=str(game_row["game_id"]),
                    started_at=game_row["started_at"],
                    deck_name=game_row["deck_name"],
                    outcome=game_row["outcome"],
                    deck_size=deck_size,
                    opening_cards=len(opening_rows),
                    known_draws=len(draw_rows),
                    cards_seen=cards_seen,
                    lands_seen=lands_seen,
                    land_rate_seen=(lands_seen / cards_seen) if cards_seen else 0.0,
                    flood_probability=flood_probability,
                    screw_probability=screw_probability,
                    target_card=target_card,
                    target_card_seen=target_seen,
                    target_card_probability=target_probability,
                )
            )
    return DrawQualityResult(total_games=len(games), games=games)


def _fmt_probability(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100.0:.2f}%"


def format_draw_quality_report(result: DrawQualityResult) -> str:
    """Return a terminal-friendly draw-quality report."""
    lines = ["DRAW QUALITY AUDIT", f"Games analyzed: {result.total_games}"]
    for game in result.games:
        lines.append("")
        lines.append(
            f"{game.started_at or 'unknown time'} | {game.deck_name or 'Unknown Deck'} | "
            f"{game.outcome or 'unknown'}"
        )
        lines.append(
            f"  Seen: {game.cards_seen} cards ({game.opening_cards} opening, "
            f"{game.known_draws} known draws)"
        )
        lines.append(
            f"  Lands: {game.lands_seen}/{game.cards_seen} ({game.land_rate_seen * 100.0:.1f}%) | "
            f"flood tail P>=: {_fmt_probability(game.flood_probability)} | "
            f"screw tail P<=: {_fmt_probability(game.screw_probability)}"
        )
        if game.target_card:
            lines.append(
                f"  {game.target_card}: {game.target_card_seen} seen | "
                f"P>=: {_fmt_probability(game.target_card_probability)}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit MTGA draw quality from tracker SQLite data."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to mtga_tracker.sqlite3")
    parser.add_argument("--card", help="Optional card name to audit, e.g. Llanowar Elves")
    parser.add_argument("--land-rate", type=float, default=0.37, help="Expected deck land rate")
    parser.add_argument(
        "--card-copies", type=int, default=4, help="Expected copies of --card in deck"
    )
    parser.add_argument("--limit", type=int, default=25, help="Recent games to analyze")
    args = parser.parse_args()

    result = analyze_draw_quality(
        args.db,
        target_card=args.card,
        expected_land_rate=args.land_rate,
        target_card_copies=args.card_copies,
        limit=args.limit,
    )
    print(format_draw_quality_report(result))


if __name__ == "__main__":
    main()
