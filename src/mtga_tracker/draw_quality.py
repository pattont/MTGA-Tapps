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
from .paths import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "mtga_tracker.sqlite3"

#: Fallback expected land rates when no submitted decklist is available.
DEFAULT_LAND_RATE_LARGE_DECK = 0.4
DEFAULT_LAND_RATE_SMALL_DECK = 0.425
LARGE_DECK_THRESHOLD = 50


def default_expected_land_rate(deck_size: int) -> float:
    """Heuristic land rate used when the actual decklist is unknown."""
    return (
        DEFAULT_LAND_RATE_LARGE_DECK
        if deck_size >= LARGE_DECK_THRESHOLD
        else DEFAULT_LAND_RATE_SMALL_DECK
    )


def deck_land_stats(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: Optional[str],
) -> Optional[tuple[int, int]]:
    """Return (deck_size, land_count) from the submitted decklist, or None."""
    if not participant_id:
        return None
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(quantity), 0) AS deck_size,
            COALESCE(SUM(CASE WHEN type_category = 'Land' THEN quantity ELSE 0 END), 0) AS lands
        FROM game_deck_cards
        WHERE game_id = ? AND participant_id = ? AND deck_zone = 'deck'
        """,
        (game_id, participant_id),
    ).fetchone()
    if row is None:
        return None
    deck_size = int(row[0] or 0)
    lands = int(row[1] or 0)
    if deck_size <= 0:
        return None
    return deck_size, lands


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


def is_land_row(row) -> bool:
    """Shared land check for dict-style card rows."""
    return (
        str(row.get("type_category") or "").casefold() == "land"
        or str(row.get("display_name") or "").rstrip().endswith("(Land)")
    )


def longest_land_run(flags) -> int:
    """Longest run of consecutive land draws."""
    longest = 0
    current = 0
    for is_land in flags:
        current = current + 1 if is_land else 0
        longest = max(longest, current)
    return longest


def max_lands_in_window(flags, window_size: int = 8) -> Optional[int]:
    """Most lands seen in any fixed-size draw window, or None for short games."""
    if len(flags) < window_size:
        return None
    return max(
        sum(flags[index : index + window_size])
        for index in range(len(flags) - window_size + 1)
    )


def longest_low_land_drought(flags, opening_lands: int, land_ceiling: int = 2):
    """Return the longest known nonland run while at most land_ceiling lands were seen."""
    lands_seen = opening_lands
    longest = 0
    longest_land_count = None
    current = 0
    for is_land in flags:
        if is_land is True:
            lands_seen += 1
            current = 0
        elif is_land is False and lands_seen <= land_ceiling:
            current += 1
            if current > longest:
                longest = current
                longest_land_count = lands_seen
        else:
            current = 0
    return longest, longest_land_count


def draw_quality_metrics(
    opening_hand,
    drawn,
    recorded_draws: int,
    deck_size: int,
    *,
    deck_lands: Optional[int] = None,
) -> dict:
    """Calculate the shared draw-quality and flood metrics for one game.

    When deck_lands is provided (from the submitted decklist) the expected land
    rate is exact; otherwise the shared heuristic rate is used.
    """
    total_draws = max(int(recorded_draws or 0), len(drawn))
    land_draws = sum(1 for row in drawn if is_land_row(row))
    land_draw_pct = round(100.0 * land_draws / total_draws, 1) if total_draws else None
    opening_lands = sum(1 for row in opening_hand if is_land_row(row))
    total_cards_seen = len(opening_hand) + total_draws
    lands_seen = opening_lands + land_draws
    land_seen_pct = (
        round(100.0 * lands_seen / total_cards_seen, 1) if total_cards_seen else None
    )
    if deck_lands is not None and deck_size > 0:
        expected_land_rate = deck_lands / deck_size
        land_rate_source = "decklist"
        expected_deck_lands = max(0, min(deck_size, int(deck_lands)))
    else:
        expected_land_rate = default_expected_land_rate(deck_size)
        land_rate_source = "estimate"
        expected_deck_lands = max(0, min(deck_size, round(deck_size * expected_land_rate)))
    expected_lands_seen = round(total_cards_seen * expected_land_rate, 1)
    flood_probability_pct = None
    screw_probability_pct = None
    if total_cards_seen:
        flood_probability_pct = round(
            100.0
            * hypergeom_tail_at_least(
                lands_seen,
                population_size=deck_size,
                success_count=expected_deck_lands,
                draw_count=min(total_cards_seen, deck_size),
            ),
            1,
        )
        if len(drawn) == total_draws:
            screw_probability_pct = round(
                100.0
                * hypergeom_tail_at_most(
                    lands_seen,
                    population_size=deck_size,
                    success_count=expected_deck_lands,
                    draw_count=min(total_cards_seen, deck_size),
                ),
                1,
            )

    land_by_position = {
        int(row.get("draw_position") or 0): is_land_row(row)
        for row in drawn
        if int(row.get("draw_position") or 0) > 0
    }
    draw_land_flags = [
        land_by_position.get(position, False) for position in range(1, total_draws + 1)
    ]
    known_draw_land_flags = [
        land_by_position.get(position) for position in range(1, total_draws + 1)
    ]
    longest_streak = longest_land_run(draw_land_flags)
    max_lands_eight = max_lands_in_window(draw_land_flags)
    drought, drought_lands = longest_low_land_drought(
        known_draw_land_flags,
        opening_lands,
    )
    flood_reasons = []
    # The percentage rule needs a real sample: "2 of 2 draws were lands" in a
    # short game is ordinary variance, not flood.
    if land_draw_pct is not None and land_draw_pct > 50.0 and total_draws >= 6:
        flood_reasons.append(f"{land_draws} of {total_draws} post-opening draws were lands")
    # Combined rule counting the opening hand: a 3-land keep followed by
    # land-heavy draws floods even when no single post-opening rule fires.
    # Requires being clearly above the deck's own expected land count so a
    # normal land share never triggers it.
    if (
        total_cards_seen >= 9
        and land_seen_pct is not None
        and land_seen_pct >= max(50.0, expected_land_rate * 100.0 + 12.0)
        and lands_seen - expected_lands_seen >= 1.2
    ):
        flood_reasons.append(
            f"{lands_seen} of {total_cards_seen} cards seen were lands "
            "(opening hand included)"
        )
    if flood_probability_pct is not None and flood_probability_pct <= 10.0:
        flood_reasons.append(
            f"Only a {flood_probability_pct:g}% chance of seeing at least {lands_seen} lands"
        )
    if longest_streak >= 4:
        flood_reasons.append(f"{longest_streak} consecutive land draws")
    if max_lands_eight is not None and max_lands_eight >= 6:
        flood_reasons.append(f"{max_lands_eight} lands in an 8-draw window")

    screw_reasons = []
    if drought >= 3 and drought_lands is not None:
        land_label = "land" if drought_lands == 1 else "lands"
        screw_reasons.append(
            f"{drought} consecutive nonland draws while stuck on "
            f"{drought_lands} {land_label}"
        )
    if screw_probability_pct is not None and screw_probability_pct <= 10.0:
        land_label = "land" if lands_seen == 1 else "lands"
        screw_reasons.append(
            f"Only a {screw_probability_pct:g}% chance of seeing at most "
            f"{lands_seen} {land_label}"
        )

    return {
        "total_draws": total_draws,
        "identified_draws": len(drawn),
        "land_draws": land_draws,
        "land_draw_pct": land_draw_pct,
        "total_cards_seen": total_cards_seen,
        "opening_lands": opening_lands,
        "lands_seen": lands_seen,
        "land_seen_pct": land_seen_pct,
        "expected_land_rate": round(expected_land_rate * 100.0, 1),
        "land_rate_source": land_rate_source,
        "deck_lands": deck_lands,
        "expected_lands_seen": expected_lands_seen,
        "flood_probability_pct": flood_probability_pct,
        "screw_probability_pct": screw_probability_pct,
        "longest_land_streak": longest_streak,
        "max_lands_in_eight": max_lands_eight,
        "longest_low_land_drought": drought,
        "low_land_drought_lands": drought_lands,
        "flood_reasons": flood_reasons,
        "is_flood": bool(flood_reasons),
        "screw_reasons": screw_reasons,
        "is_screw": bool(screw_reasons),
    }


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
    expected_land_rate: Optional[float] = None,
    target_card_copies: int = 4,
    limit: int = 25,
) -> DrawQualityResult:
    """Analyze recent games using captured opening hands plus visible drawn cards.

    When expected_land_rate is None (the default), each game uses its submitted
    decklist's actual land count when available and the shared heuristic rate
    otherwise. Passing an explicit rate forces that rate for every game.
    """
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
            decklist = deck_land_stats(conn, str(game_row["game_id"]), participant_id)
            game_land_rate = expected_land_rate
            if decklist is not None:
                deck_size = decklist[0]
                if game_land_rate is None:
                    game_land_rate = decklist[1] / decklist[0]
            if game_land_rate is None:
                game_land_rate = default_expected_land_rate(deck_size)
            cards_seen = len(seen_rows)
            lands_seen = sum(1 for row in seen_rows if _is_land(row))
            expected_lands = max(0, min(deck_size, round(deck_size * game_land_rate)))
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
    parser.add_argument(
        "--land-rate",
        type=float,
        default=None,
        help="Force an expected deck land rate (default: use each game's decklist)",
    )
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
