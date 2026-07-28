"""Dependency-free local dashboard for the MTGA tracker SQLite DB."""

from __future__ import annotations

import argparse
import html
import json
import math
import mimetypes
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

from .draw_quality import (
    deck_land_stats,
    draw_quality_metrics,
    hypergeom_tail_at_least,
    hypergeom_tail_at_most,
    is_land_row,
)
from .format_normalizer import format_label, normalize_match_format
from .paths import DATA_DIR


DEFAULT_DB_PATH = DATA_DIR / "mtga_tracker.sqlite3"
_CONSTRUCTED_RANK_ORDER = {
    "Bronze": 0,
    "Silver": 1,
    "Gold": 2,
    "Platinum": 3,
    "Diamond": 4,
    "Mythic": 5,
}


def _default_static_dir() -> Path:
    override = os.getenv("MTGA_TRACKER_UI_DIR")
    if override:
        return Path(override).expanduser()
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "ui" / "dist"
    return DATA_DIR.parent / "ui" / "dist"


DEFAULT_STATIC_DIR = _default_static_dir()


def _dict_rows(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


_TYPE_SUFFIX_RE = re.compile(r"\s*\([^()]*\)\s*$")
_BRACKET_CONTENT_RE = re.compile(r"\[([^\]\n]+)\]")


def _clean_card_name(display_name: Optional[str]) -> Optional[str]:
    """Strip the trailing '(Type)' suffix tracker display names carry."""
    if not display_name:
        return display_name
    cleaned = _TYPE_SUFFIX_RE.sub("", display_name).strip()
    return cleaned or display_name


def _card_name_aliases(display_name: Optional[str]) -> Set[str]:
    """Return a card name plus either face name for split/double-faced cards."""
    clean_name = _clean_card_name(display_name)
    if not clean_name:
        return set()
    aliases = {clean_name}
    if " // " in clean_name:
        aliases.update(part.strip() for part in clean_name.split(" // ") if part.strip())
    return aliases


def _timeline_text_segments(
    text: str, linkable_cards: Set[str] | Dict[str, Optional[str]]
) -> List[Dict[str, str]]:
    """Split timeline text into plain text and validated card-name segments."""
    linkable_card_names = (
        set(linkable_cards)
        if isinstance(linkable_cards, dict)
        else linkable_cards
    )
    segments: List[Dict[str, str]] = []
    cursor = 0
    for match in _BRACKET_CONTENT_RE.finditer(text):
        bracket_content = match.group(1)
        card_name = _clean_card_name(bracket_content)
        if not card_name or card_name not in linkable_card_names:
            continue
        card_offset = bracket_content.find(card_name)
        if card_offset < 0:
            continue
        card_start = match.start(1) + card_offset
        if card_start > cursor:
            segments.append({"kind": "text", "text": text[cursor:card_start]})
        card_segment = {"kind": "card", "text": card_name, "card_name": card_name}
        if isinstance(linkable_cards, dict) and linkable_cards.get(card_name):
            card_segment["card_type"] = str(linkable_cards[card_name])
        segments.append(card_segment)
        cursor = card_start + len(card_name)
    if cursor < len(text):
        segments.append({"kind": "text", "text": text[cursor:]})
    return segments or [{"kind": "text", "text": text}]


def _is_land_row(row: Dict[str, Any]) -> bool:
    return is_land_row(row)


def _draw_quality_metrics(
    opening_hand: List[Dict[str, Any]],
    drawn: List[Dict[str, Any]],
    recorded_draws: int,
    deck_size: int,
    deck_lands: Optional[int] = None,
) -> Dict[str, Any]:
    """Calculate the shared draw-quality and flood metrics for one game."""
    return draw_quality_metrics(
        opening_hand,
        drawn,
        recorded_draws,
        deck_size,
        deck_lands=deck_lands,
    )


def _game_draw_quality(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: Optional[str],
    deck_size: Optional[int],
) -> Dict[str, Any]:
    """Load one game's visible cards and calculate its shared flood metrics."""
    opening_hand = _dict_rows(
        conn.execute(
            """
            SELECT display_name, COALESCE(type_category, 'Other') AS type_category
            FROM game_opening_hand_cards
            WHERE game_id = ? AND participant_id = ?
            ORDER BY hand_position, copy_number
            """,
            (game_id, participant_id),
        )
    )
    drawn = _dict_rows(
        conn.execute(
            """
            SELECT display_name, COALESCE(type_category, 'Other') AS type_category, draw_position
            FROM game_drawn_cards
            WHERE game_id = ? AND participant_id = ?
            ORDER BY draw_position
            """,
            (game_id, participant_id),
        )
    )
    stats_drawn_row = conn.execute(
        """
        SELECT cards_drawn
        FROM game_participant_stats
        WHERE game_id = ? AND participant_id = ?
        """,
        (game_id, participant_id),
    ).fetchone()
    recorded_draws = int(stats_drawn_row[0] or 0) if stats_drawn_row else 0
    decklist = deck_land_stats(conn, game_id, participant_id)
    deck_lands = None
    if decklist is not None:
        deck_size, deck_lands = decklist
    return _draw_quality_metrics(
        opening_hand,
        drawn,
        recorded_draws,
        int(deck_size or 60),
        deck_lands,
    )


def _card_image_url(arena_id: Optional[int], card_name: Optional[str]) -> Optional[str]:
    """Best-effort Scryfall art-crop URL for a card; None when unresolvable."""
    if arena_id:
        return f"https://api.scryfall.com/cards/arena/{arena_id}?format=image&version=art_crop"
    if card_name:
        front_face = card_name.split(" // ")[0].strip()
        if front_face:
            return f"https://api.scryfall.com/cards/named?fuzzy={quote(front_face)}&format=image&version=art_crop"
    return None


def _deck_decklist_analysis(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Decklist-derived analytics for one deck's filtered games.

    Returns (composition_rows, version_rows, sideboard_summary):
    - composition: per card actually submitted in maindecks — copies, games in
      deck, seen/drawn counts, hypergeometric expected draws, and win rates
      when seen vs not seen (the dead-weight report).
    - versions: distinct submitted-decklist snapshots over time with W/L and
      the diff against the previous version.
    - sideboard: Bo3 game-1 vs post-board record plus most-boarded cards.
    """
    games = _dict_rows(
        conn.execute(
            f"""
            SELECT
              g.id AS game_id,
              COALESCE(g.started_at, g.ended_at) AS started_at,
              g.game_number,
              g.match_id,
              g.outcome,
              p.id AS participant_id
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE {where}
            ORDER BY COALESCE(g.started_at, g.ended_at), g.id
            """,
            params,
        )
    )
    if not games:
        return [], [], None
    participant_ids = {row["participant_id"] for row in games}
    game_by_participant = {row["participant_id"]: row for row in games}

    deck_rows_by_game: Dict[str, List[Dict[str, Any]]] = {}
    sideboard_by_game: Dict[str, Dict[str, int]] = {}
    placeholders = ",".join("?" for _ in participant_ids)
    for row in _dict_rows(
        conn.execute(
            f"""
            SELECT participant_id, display_name, type_category, deck_zone, quantity
            FROM game_deck_cards
            WHERE participant_id IN ({placeholders})
            """,
            list(participant_ids),
        )
    ):
        game = game_by_participant.get(row["participant_id"])
        if game is None:
            continue
        game_id = game["game_id"]
        if row["deck_zone"] == "deck":
            deck_rows_by_game.setdefault(game_id, []).append(row)
        else:
            sideboard_by_game.setdefault(game_id, {})[
                _clean_card_name(row["display_name"])
            ] = int(row["quantity"] or 0)

    seen_by_game: Dict[str, Dict[str, int]] = {}
    seen_totals_by_game: Dict[str, int] = {}
    for table in ("game_opening_hand_cards", "game_drawn_cards"):
        for row in _dict_rows(
            conn.execute(
                f"""
                SELECT participant_id, display_name, COUNT(*) AS copies
                FROM {table}
                WHERE participant_id IN ({placeholders})
                GROUP BY participant_id, display_name
                """,
                list(participant_ids),
            )
        ):
            game = game_by_participant.get(row["participant_id"])
            if game is None:
                continue
            game_id = game["game_id"]
            clean = _clean_card_name(row["display_name"])
            bucket = seen_by_game.setdefault(game_id, {})
            bucket[clean] = bucket.get(clean, 0) + int(row["copies"] or 0)
            seen_totals_by_game[game_id] = (
                seen_totals_by_game.get(game_id, 0) + int(row["copies"] or 0)
            )

    # --- Composition / dead-weight rows ---
    composition: Dict[str, Dict[str, Any]] = {}
    latest_game_with_deck = None
    for game in games:
        if deck_rows_by_game.get(game["game_id"]):
            latest_game_with_deck = game["game_id"]
    for game in games:
        game_id = game["game_id"]
        deck_cards = deck_rows_by_game.get(game_id)
        if not deck_cards:
            continue
        deck_size = sum(int(row["quantity"] or 0) for row in deck_cards)
        seen_cards = seen_by_game.get(game_id, {})
        seen_total = seen_totals_by_game.get(game_id, 0)
        outcome = game.get("outcome")
        for row in deck_cards:
            clean = _clean_card_name(row["display_name"])
            entry = composition.setdefault(
                clean,
                {
                    "display_name": clean,
                    "type_category": str(row.get("type_category") or "Other"),
                    "copies": 0,
                    "games_in_deck": 0,
                    "games_seen": 0,
                    "times_seen": 0,
                    "expected_seen": 0.0,
                    "wins_when_seen": 0,
                    "losses_when_seen": 0,
                    "wins_when_not_seen": 0,
                    "losses_when_not_seen": 0,
                },
            )
            quantity = int(row["quantity"] or 0)
            entry["games_in_deck"] += 1
            if game_id == latest_game_with_deck:
                entry["copies"] = quantity
            copies_seen = seen_cards.get(clean, 0)
            if deck_size:
                entry["expected_seen"] += seen_total * quantity / deck_size
            if copies_seen:
                entry["games_seen"] += 1
                entry["times_seen"] += copies_seen
                if outcome == "win":
                    entry["wins_when_seen"] += 1
                elif outcome == "loss":
                    entry["losses_when_seen"] += 1
            else:
                if outcome == "win":
                    entry["wins_when_not_seen"] += 1
                elif outcome == "loss":
                    entry["losses_when_not_seen"] += 1

    composition_rows: List[Dict[str, Any]] = []
    for entry in composition.values():
        if not entry["copies"]:
            # Card only in older versions; report the most common quantity seen.
            entry["copies"] = 0
        decided_seen = entry["wins_when_seen"] + entry["losses_when_seen"]
        decided_not = entry["wins_when_not_seen"] + entry["losses_when_not_seen"]
        entry["seen_pct"] = (
            round(100.0 * entry["games_seen"] / entry["games_in_deck"], 1)
            if entry["games_in_deck"]
            else None
        )
        entry["expected_seen"] = round(entry["expected_seen"], 1)
        entry["seen_delta"] = round(entry["times_seen"] - entry["expected_seen"], 1)
        entry["win_rate_when_seen"] = (
            round(100.0 * entry["wins_when_seen"] / decided_seen, 1) if decided_seen else None
        )
        entry["win_rate_when_not_seen"] = (
            round(100.0 * entry["wins_when_not_seen"] / decided_not, 1) if decided_not else None
        )
        composition_rows.append(entry)
    composition_rows.sort(
        key=lambda row: (-row["games_in_deck"], -row["times_seen"], row["display_name"].casefold())
    )

    # --- Deck versions ---
    signature_by_game: Dict[str, Tuple] = {}
    for game in games:
        deck_cards = deck_rows_by_game.get(game["game_id"])
        if not deck_cards:
            continue
        signature = tuple(
            sorted(
                (_clean_card_name(row["display_name"]), int(row["quantity"] or 0))
                for row in deck_cards
            )
        )
        signature_by_game[game["game_id"]] = signature

    version_rows: List[Dict[str, Any]] = []
    version_index: Dict[Tuple, Dict[str, Any]] = {}
    for game in games:
        signature = signature_by_game.get(game["game_id"])
        if signature is None:
            continue
        version = version_index.get(signature)
        if version is None:
            version = {
                "version": len(version_rows) + 1,
                "first_played": game.get("started_at"),
                "last_played": game.get("started_at"),
                "games": 0,
                "wins": 0,
                "losses": 0,
                "added": [],
                "removed": [],
                "_signature": signature,
            }
            previous = version_rows[-1] if version_rows else None
            if previous is not None:
                before = dict(previous["_signature"])
                after = dict(signature)
                for name in sorted(set(after) - set(before)):
                    version["added"].append(f"{after[name]}x {name}")
                for name in sorted(set(before) - set(after)):
                    version["removed"].append(f"{before[name]}x {name}")
                for name in sorted(set(before) & set(after)):
                    if after[name] != before[name]:
                        delta = after[name] - before[name]
                        target = version["added"] if delta > 0 else version["removed"]
                        target.append(f"{abs(delta)}x {name}")
            version_index[signature] = version
            version_rows.append(version)
        version["last_played"] = game.get("started_at")
        version["games"] += 1
        if game.get("outcome") == "win":
            version["wins"] += 1
        elif game.get("outcome") == "loss":
            version["losses"] += 1
    for version in version_rows:
        decided = version["wins"] + version["losses"]
        version["win_rate"] = round(100.0 * version["wins"] / decided, 1) if decided else None
        version.pop("_signature", None)

    # --- Bo3 sideboard summary ---
    matches: Dict[str, List[Dict[str, Any]]] = {}
    for game in games:
        matches.setdefault(str(game.get("match_id")), []).append(game)
    game_one = {"wins": 0, "losses": 0}
    post_board = {"wins": 0, "losses": 0}
    boarded_in: Dict[str, int] = {}
    multi_game_matches = 0
    for match_games in matches.values():
        if len(match_games) < 2:
            continue
        multi_game_matches += 1
        ordered = sorted(match_games, key=lambda row: (row.get("game_number") or 0))
        base_signature = signature_by_game.get(ordered[0]["game_id"])
        for index, game in enumerate(ordered):
            bucket = game_one if index == 0 else post_board
            if game.get("outcome") == "win":
                bucket["wins"] += 1
            elif game.get("outcome") == "loss":
                bucket["losses"] += 1
            if index > 0 and base_signature is not None:
                signature = signature_by_game.get(game["game_id"])
                if signature is not None:
                    before = dict(base_signature)
                    after = dict(signature)
                    for name, quantity in after.items():
                        delta = quantity - before.get(name, 0)
                        if delta > 0:
                            boarded_in[name] = boarded_in.get(name, 0) + delta
    sideboard_summary = None
    if multi_game_matches:
        decided_one = game_one["wins"] + game_one["losses"]
        decided_post = post_board["wins"] + post_board["losses"]
        sideboard_summary = {
            "matches": multi_game_matches,
            "game_one": {
                **game_one,
                "win_rate": round(100.0 * game_one["wins"] / decided_one, 1)
                if decided_one
                else None,
            },
            "post_board": {
                **post_board,
                "win_rate": round(100.0 * post_board["wins"] / decided_post, 1)
                if decided_post
                else None,
            },
            "boarded_in": [
                {"display_name": name, "copies": copies}
                for name, copies in sorted(
                    boarded_in.items(), key=lambda item: (-item[1], item[0].casefold())
                )[:15]
            ],
        }

    return composition_rows, version_rows, sideboard_summary


def _combat_deck_rows(conn: sqlite3.Connection, where: str, params: List[Any]) -> List[Dict[str, Any]]:
    """Per-deck combat/aggression profile from game_participant_stats."""
    rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              COALESCE(p.deck_name, '(unknown)') AS deck_name,
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate,
              ROUND(AVG(s.damage_dealt), 1) AS avg_damage_dealt,
              ROUND(AVG(s.damage_taken), 1) AS avg_damage_taken,
              ROUND(AVG(s.attack_steps), 1) AS avg_attack_steps,
              ROUND(1.0 * SUM(s.attacking_creatures) / NULLIF(SUM(s.attack_steps), 0), 2) AS attackers_per_attack,
              SUM(s.attackers_lost) AS attackers_lost,
              SUM(s.blockers_lost) AS blockers_lost,
              ROUND(AVG(s.life_gained), 1) AS avg_life_gained,
              ROUND(AVG(g.player_turns), 1) AS avg_player_turns
            FROM game_participant_stats s
            JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
            JOIN games g ON g.id = s.game_id
            WHERE {where}
            GROUP BY COALESCE(p.deck_name, '(unknown)')
            HAVING COUNT(*) > 0
            ORDER BY games DESC, deck_name COLLATE NOCASE
            LIMIT 40
            """,
            params,
        )
    )
    for row in rows:
        attacks = row.get("avg_attack_steps") or 0
        turns = row.get("avg_player_turns") or 0
        ratio = (attacks / turns) if turns else None
        if ratio is None:
            row["aggression_profile"] = None
        elif ratio >= 0.6 and turns <= 9:
            row["aggression_profile"] = "Aggro"
        elif ratio <= 0.35:
            row["aggression_profile"] = "Control"
        else:
            row["aggression_profile"] = "Midrange"
        attackers_lost = int(row.get("attackers_lost") or 0)
        blockers_lost = int(row.get("blockers_lost") or 0)
        row["trade_ratio"] = (
            round(blockers_lost / attackers_lost, 2) if attackers_lost else None
        )
    return rows


def _combat_split_rows(conn: sqlite3.Connection, where: str, params: List[Any]) -> List[Dict[str, Any]]:
    """Aggression aggregates split by game outcome (wins vs losses)."""
    return _dict_rows(
        conn.execute(
            f"""
            SELECT
              CASE WHEN g.outcome = 'win' THEN 'Wins' ELSE 'Losses' END AS split,
              COUNT(*) AS games,
              ROUND(AVG(s.damage_dealt), 1) AS avg_damage_dealt,
              ROUND(AVG(s.damage_taken), 1) AS avg_damage_taken,
              ROUND(AVG(s.attack_steps), 1) AS avg_attack_steps,
              ROUND(AVG(s.life_gained), 1) AS avg_life_gained,
              ROUND(AVG(s.cards_drawn), 1) AS avg_cards_drawn,
              ROUND(AVG(s.cards_discarded + s.cards_milled), 1) AS avg_cards_denied
            FROM game_participant_stats s
            JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
            JOIN games g ON g.id = s.game_id
            WHERE {where} AND g.outcome IN ('win', 'loss')
            GROUP BY split
            ORDER BY split = 'Wins' DESC
            """,
            params,
        )
    )


def _games_filter(
    deck: Optional[str], fmt: Optional[str], days: Optional[int]
) -> Tuple[str, List[Any]]:
    """WHERE fragment (referencing games alias `g`) plus bound params."""
    # Jump In games are intentionally untracked; hide them from every aggregate.
    clauses = [
        """NOT EXISTS (
          SELECT 1 FROM matches mj
          WHERE mj.id = g.match_id AND mj.format LIKE 'Jump!_In%' ESCAPE '!'
        )"""
    ]
    params: List[Any] = []
    if deck:
        clauses.append(
            """EXISTS (
              SELECT 1 FROM participants pf
              WHERE pf.game_id = g.id AND pf.role = 'player'
                AND COALESCE(pf.deck_name, '(unknown)') = ?
            )"""
        )
        params.append(deck)
    if fmt:
        clauses.append(
            """EXISTS (
              SELECT 1 FROM matches mf
              WHERE mf.id = g.match_id AND COALESCE(mf.format, '(unknown)') = ?
            )"""
        )
        params.append(fmt)
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        clauses.append("COALESCE(g.started_at, g.ended_at) >= ?")
        params.append(cutoff)
    return " AND ".join(clauses), params


def _win_rate(wins: int, losses: int) -> Optional[float]:
    decided = wins + losses
    return round(100.0 * wins / decided, 1) if decided else None


def _rank_score(rank_class: str, rank_level: int, rank_step: int, rank_steps: int) -> int:
    """Return a chartable score across Bronze through Mythic."""
    class_index = _CONSTRUCTED_RANK_ORDER.get(rank_class, 0)
    if rank_class == "Mythic":
        return class_index * 4 * rank_steps
    level_progress = max(0, min(3, 4 - rank_level))
    return class_index * 4 * rank_steps + level_progress * rank_steps + rank_step


def _grouped_format_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Format performance grouped by display label.

    Midweek Magic events are intentionally omitted because those rotating queues
    are not part of the tracker's supported format analytics. The second return
    value remains an empty compatibility field for older dashboard clients.
    """
    raw_rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              COALESCE(m.format, '(unknown)') AS raw_format,
              COALESCE(m.best_of, 1) AS best_of,
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses
            FROM games g
            JOIN matches m ON m.id = g.match_id
            WHERE {where}
            GROUP BY m.format, m.best_of
            """,
            params,
        )
    )
    top: Dict[str, Dict[str, Any]] = {}

    def _accumulate(bucket: Dict[str, Dict[str, Any]], label: str, row: Dict[str, Any]) -> None:
        entry = bucket.setdefault(
            label,
            {"format_label": label, "games": 0, "wins": 0, "losses": 0, "raw_formats": []},
        )
        entry["games"] += int(row["games"] or 0)
        entry["wins"] += int(row["wins"] or 0)
        entry["losses"] += int(row["losses"] or 0)
        if row["raw_format"] not in entry["raw_formats"]:
            entry["raw_formats"].append(row["raw_format"])

    for row in raw_rows:
        normalized = normalize_match_format(
            row["raw_format"], default_best_of=int(row["best_of"] or 1)
        )
        if normalized.is_midweek:
            continue
        _accumulate(top, normalized.label, row)

    def _finish(bucket: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for entry in bucket.values():
            entry["win_rate"] = _win_rate(entry["wins"], entry["losses"])
            entry["raw_formats"] = ", ".join(sorted(entry["raw_formats"]))
            rows.append(entry)
        rows.sort(key=lambda item: (-item["games"], item["format_label"]))
        return rows

    return _finish(top)[:20], []


def _deck_visuals(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    rows = _dict_rows(
        conn.execute(
            """
            WITH candidate_cards AS (
              SELECT
                COALESCE(p.deck_name, '(unknown)') AS deck_name,
                s.card_id,
                s.display_name,
                COALESCE(s.type_category, 'Other') AS type_category,
                SUM(COALESCE(s.played_count, 0)) AS activity_count,
                1 AS source_rank
              FROM participants p
              JOIN game_card_summary s ON s.participant_id = p.id
              WHERE p.role = 'player'
              GROUP BY p.deck_name, s.card_id, s.display_name, s.type_category
              UNION ALL
              SELECT
                COALESCE(p.deck_name, '(unknown)') AS deck_name,
                h.card_id,
                h.display_name,
                COALESCE(h.type_category, 'Other') AS type_category,
                COUNT(*) AS activity_count,
                2 AS source_rank
              FROM participants p
              JOIN game_opening_hand_cards h ON h.participant_id = p.id
              WHERE p.role = 'player'
              GROUP BY p.deck_name, h.card_id, h.display_name, h.type_category
              UNION ALL
              SELECT
                COALESCE(p.deck_name, '(unknown)') AS deck_name,
                d.card_id,
                d.display_name,
                COALESCE(d.type_category, 'Other') AS type_category,
                COUNT(*) AS activity_count,
                3 AS source_rank
              FROM participants p
              JOIN game_drawn_cards d ON d.participant_id = p.id
              WHERE p.role = 'player'
              GROUP BY p.deck_name, d.card_id, d.display_name, d.type_category
            ),
            ranked AS (
              SELECT
                deck_name,
                card_id,
                display_name,
                type_category,
                activity_count,
                ROW_NUMBER() OVER (
                  PARTITION BY deck_name
                  ORDER BY
                    CASE WHEN type_category = 'Land' THEN 1 ELSE 0 END,
                    source_rank,
                    activity_count DESC,
                    display_name,
                    type_category,
                    COALESCE(card_id, -1)
                ) AS rank
              FROM candidate_cards
              WHERE display_name IS NOT NULL AND TRIM(display_name) != ''
            )
            SELECT
              r.deck_name,
              r.card_id,
              r.display_name,
              r.type_category,
              c.name AS card_name,
              c.arena_id
            FROM ranked r
            LEFT JOIN cards c ON c.id = r.card_id
            WHERE r.rank = 1
            """
        )
    )
    visuals: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        deck_name = row["deck_name"]
        card_name = row.get("card_name") or _clean_card_name(row.get("display_name"))
        visuals[deck_name] = {
            "card_id": row.get("card_id"),
            "card_name": card_name,
            "type_category": row.get("type_category") or "Other",
            "image_url": _card_image_url(row.get("arena_id"), card_name),
            "source": "local_metadata",
        }
    return visuals


def _empty_deck_visual(deck_name: str) -> Dict[str, Any]:
    return {
        "card_id": None,
        "card_name": deck_name,
        "type_category": "Other",
        "image_url": None,
        "source": "deck_name",
    }


def _arena_export_card_name(conn: sqlite3.Connection, display_name: str) -> str:
    """Prefer the full split-card name already known to the card dimension."""
    clean_name = _clean_card_name(display_name) or display_name
    if " // " in clean_name:
        return clean_name
    row = conn.execute(
        """
        SELECT name
        FROM cards
        WHERE name LIKE ? OR name LIKE ?
        ORDER BY LENGTH(name) DESC
        LIMIT 1
        """,
        (f"{clean_name} // %", f"% // {clean_name}"),
    ).fetchone()
    return str(row[0]) if row else clean_name


def _deck_export_snapshot(
    conn: sqlite3.Connection,
    where: str,
    params: List[Any],
    deck_name: str,
) -> Dict[str, Any]:
    """Return an exact Arena export from the newest submitted deck snapshot."""
    unavailable = {
        "available": False,
        "source_game_id": None,
        "main_deck": [],
        "sideboard": [],
        "text": None,
    }
    if not _table_exists(conn, "game_deck_cards"):
        return unavailable
    source = conn.execute(
        f"""
        SELECT g.id
        FROM games g
        JOIN matches m ON m.id = g.match_id
        WHERE {where}
          AND EXISTS (
            SELECT 1
            FROM game_deck_cards dc
            JOIN participants dp ON dp.id = dc.participant_id AND dp.role = 'player'
            WHERE dc.game_id = g.id
          )
        ORDER BY
          COALESCE(m.started_at, g.started_at, g.ended_at) DESC,
          CASE WHEN g.game_number = 1 THEN 0 ELSE 1 END,
          COALESCE(g.started_at, g.ended_at) ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if source is None:
        return unavailable

    source_game_id = str(source[0])
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {"deck": {}, "sideboard": {}}
    for row in _dict_rows(
        conn.execute(
            """
            SELECT
              dc.deck_zone,
              dc.display_name,
              COALESCE(dc.type_category, 'Other') AS type_category,
              dc.quantity
            FROM game_deck_cards dc
            JOIN participants p ON p.id = dc.participant_id AND p.role = 'player'
            WHERE dc.game_id = ?
            ORDER BY dc.id
            """,
            (source_game_id,),
        )
    ):
        deck_zone = str(row.get("deck_zone") or "")
        if deck_zone not in grouped:
            continue
        card_name = _arena_export_card_name(conn, str(row["display_name"]))
        card = grouped[deck_zone].setdefault(
            card_name,
            {
                "quantity": 0,
                "type_category": str(row.get("type_category") or "Other"),
            },
        )
        card["quantity"] += int(row.get("quantity") or 0)

    main_deck = [
        {"display_name": name, **card}
        for name, card in grouped["deck"].items()
    ]
    sideboard = [
        {"display_name": name, **card}
        for name, card in grouped["sideboard"].items()
    ]
    if not main_deck:
        return unavailable

    lines = ["About", f"Name {deck_name}", "", "Deck"]
    lines.extend(f"{row['quantity']} {row['display_name']}" for row in main_deck)
    if sideboard:
        lines.extend(["", "Sideboard"])
        lines.extend(f"{row['quantity']} {row['display_name']}" for row in sideboard)
    return {
        "available": True,
        "source_game_id": source_game_id,
        "main_deck": main_deck,
        "sideboard": sideboard,
        "text": "\n".join(lines),
    }


def dashboard_snapshot(
    db_path: Path = DEFAULT_DB_PATH,
    deck: Optional[str] = None,
    fmt: Optional[str] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """Return dashboard-friendly aggregate data from SQLite.

    Optional filters narrow every aggregate: `deck` matches the player's deck
    name, `fmt` matches the raw queue/format string, and `days` keeps games
    started within the last N days.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    where, params = _games_filter(deck, fmt, days)
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        summary = conn.execute(
            f"""
            SELECT
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              SUM(g.outcome = 'draw') AS draws,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM games g
            WHERE {where}
            """,
            params,
        ).fetchone()
        deck_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                GROUP BY p.deck_name
                ORDER BY games DESC, win_rate DESC
                LIMIT 100
                """,
                params,
            )
        )
        format_rows, midweek_rows = _grouped_format_rows(conn, where, params)
        play_draw_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  CASE p.went_first WHEN 1 THEN 'On the play' WHEN 0 THEN 'On the draw' ELSE 'Unknown' END AS play_draw,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                GROUP BY p.went_first
                ORDER BY play_draw
                """,
                params,
            )
        )
        deck_play_draw_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  CASE p.went_first WHEN 1 THEN 'On the play' WHEN 0 THEN 'On the draw' ELSE 'Unknown' END AS play_draw,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                GROUP BY p.deck_name, p.went_first
                ORDER BY deck_name, play_draw
                LIMIT 40
                """,
                params,
            )
        )
        draw_quality_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  g.id AS game_id,
                  COALESCE(g.started_at, g.ended_at) AS started_at,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  g.outcome,
                  COUNT(seen.display_name) AS cards_seen,
                  COALESCE(SUM(CASE
                    WHEN seen.type_category = 'Land' OR seen.display_name LIKE '%(Land)' THEN 1
                    ELSE 0
                  END), 0) AS lands_seen,
                  ROUND(
                    100.0 * COALESCE(SUM(CASE
                      WHEN seen.type_category = 'Land' OR seen.display_name LIKE '%(Land)' THEN 1
                      ELSE 0
                    END), 0) / NULLIF(COUNT(seen.display_name), 0),
                    1
                  ) AS land_seen_pct,
                  COALESCE(SUM(CASE WHEN seen.source = 'opening' THEN 1 ELSE 0 END), 0) AS opening_cards,
                  COALESCE(SUM(CASE WHEN seen.source = 'draw' THEN 1 ELSE 0 END), 0) AS known_draws
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                LEFT JOIN (
                  SELECT game_id, participant_id, display_name, type_category, 'opening' AS source
                  FROM game_opening_hand_cards
                  UNION ALL
                  SELECT game_id, participant_id, display_name, type_category, 'draw' AS source
                  FROM game_drawn_cards
                ) seen ON seen.game_id = g.id AND seen.participant_id = p.id
                WHERE {where}
                GROUP BY g.id
                ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
                LIMIT 100
                """,
                params,
            )
        )
        drawn_card_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  d.display_name,
                  COALESCE(d.type_category, 'Other') AS type_category,
                  COUNT(*) AS times_drawn,
                  COUNT(DISTINCT d.game_id) AS games_seen
                FROM game_drawn_cards d
                JOIN participants p ON p.id = d.participant_id AND p.role = 'player'
                JOIN games g ON g.id = d.game_id
                WHERE {where}
                GROUP BY d.display_name, d.type_category
                ORDER BY times_drawn DESC, d.display_name
                LIMIT 25
                """,
                params,
            )
        )
        momentum_rows = _dict_rows(
            conn.execute(
                f"""
                WITH ordered_games AS (
                  SELECT
                    g.id,
                    g.outcome,
                    p.went_first,
                    p.mulligans,
                    LAG(g.outcome) OVER (
                      ORDER BY COALESCE(g.started_at, g.ended_at), g.id
                    ) AS previous_outcome
                  FROM games g
                  JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                  WHERE {where}
                )
                SELECT
                  CASE previous_outcome WHEN 'win' THEN 'After a win' WHEN 'loss' THEN 'After a loss' END AS split,
                  COUNT(*) AS games,
                  SUM(outcome = 'win') AS wins,
                  SUM(outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(outcome = 'win') / NULLIF(SUM(outcome IN ('win', 'loss')), 0), 1) AS win_rate,
                  ROUND(AVG(COALESCE(mulligans, 0)), 2) AS avg_mulligans,
                  ROUND(100.0 * SUM(went_first = 1) / NULLIF(SUM(went_first IN (0, 1)), 0), 1) AS on_play_pct
                FROM ordered_games
                WHERE previous_outcome IN ('win', 'loss')
                GROUP BY previous_outcome
                ORDER BY split
                """,
                params,
            )
        )
        recent_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  g.id AS game_id,
                  g.started_at,
                  g.outcome,
                  g.duration_seconds,
                  g.total_turns,
                  p.id AS player_participant_id,
                  p.deck_size,
                  m.format AS raw_format,
                  m.best_of,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  p.mulligans
                FROM games g
                JOIN matches m ON m.id = g.match_id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                ORDER BY g.started_at DESC
                LIMIT 25
                """,
                params,
            )
        )
        trend_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  g.id AS game_id,
                  COALESCE(g.started_at, g.ended_at) AS started_at,
                  g.outcome
                FROM games g
                WHERE {where} AND g.outcome IN ('win', 'loss')
                ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
                LIMIT 200
                """,
                params,
            )
        )
        trend_rows.reverse()
        rank_progress_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  r.id,
                  r.captured_at,
                  r.season_ordinal,
                  r.rank_class,
                  r.rank_level,
                  r.rank_step,
                  r.rank_steps,
                  r.raw_step,
                  r.matches_won,
                  r.matches_lost,
                  r.mythic_percentile,
                  r.mythic_rank,
                  r.game_id,
                  g.outcome,
                  m.best_of,
                  p.deck_name
                FROM rank_snapshots r
                LEFT JOIN games g ON g.id = r.game_id
                LEFT JOIN matches m ON m.id = r.match_id
                LEFT JOIN participants p ON p.game_id = r.game_id AND p.role = 'player'
                WHERE r.rank_format = 'constructed'
                  AND r.season_ordinal = (
                    SELECT MAX(season_ordinal)
                    FROM rank_snapshots
                    WHERE rank_format = 'constructed'
                  )
                ORDER BY r.captured_at, r.id
                """
            )
        )
        match_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  m.id AS match_id,
                  COALESCE(m.started_at, MIN(COALESCE(g.started_at, g.ended_at))) AS started_at,
                  m.format AS raw_format,
                  m.best_of,
                  COALESCE(MAX(p.deck_name), '(unknown)') AS deck_name,
                  COUNT(g.id) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  CASE
                    WHEN m.winner_participant_id IS NOT NULL
                      THEN CASE WHEN SUM(p.id = m.winner_participant_id) > 0 THEN 'win' ELSE 'loss' END
                    WHEN SUM(g.outcome = 'win') > SUM(g.outcome = 'loss') THEN 'win'
                    WHEN SUM(g.outcome = 'loss') > SUM(g.outcome = 'win') THEN 'loss'
                    WHEN SUM(g.outcome = 'draw') > 0 THEN 'draw'
                    ELSE NULL
                  END AS outcome
                FROM matches m
                JOIN games g ON g.match_id = m.id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where} AND COALESCE(m.best_of, 1) >= 3
                GROUP BY m.id
                ORDER BY COALESCE(m.started_at, MIN(COALESCE(g.started_at, g.ended_at))) DESC, m.id DESC
                LIMIT 25
                """,
                params,
            )
        )
        session_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  s.id AS session_id,
                  s.started_at,
                  s.ended_at,
                  s.runtime_seconds AS duration_seconds,
                  COUNT(g.id) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  SUM(g.outcome = 'draw') AS draws,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM tracker_sessions s
                JOIN games g ON g.session_id = s.id
                WHERE {where}
                GROUP BY s.id
                ORDER BY s.started_at DESC, s.id DESC
                LIMIT 25
                """,
                params,
            )
        )
        deck_options = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT COALESCE(deck_name, '(unknown)') AS deck_name
                FROM participants
                WHERE role = 'player'
                ORDER BY deck_name COLLATE NOCASE
                """
            )
        ]
        format_options = []
        for row in conn.execute(
                """
                SELECT COALESCE(format, '(unknown)') AS raw_format, MAX(COALESCE(best_of, 1))
                FROM matches
                WHERE COALESCE(format, '(unknown)') NOT LIKE 'Jump!_In%' ESCAPE '!'
                GROUP BY raw_format
                ORDER BY raw_format COLLATE NOCASE
                """
        ):
            normalized = normalize_match_format(
                row[0], default_best_of=int(row[1] or 1)
            )
            if normalized.is_midweek:
                continue
            format_options.append(
                {"raw_format": row[0], "format_label": normalized.label}
            )
        combat_deck_rows = _combat_deck_rows(conn, where, params)
        combat_split_rows = _combat_split_rows(conn, where, params)
        deck_visuals = _deck_visuals(conn)
        for row in deck_rows:
            deck_name = row["deck_name"]
            row["deck_visual"] = deck_visuals.get(deck_name, _empty_deck_visual(deck_name))
        for row in recent_rows:
            quality = _game_draw_quality(
                conn,
                str(row.get("game_id")),
                row.pop("player_participant_id", None),
                row.pop("deck_size", None),
            )
            row["flood_reasons"] = quality["flood_reasons"]
            row["is_flood"] = quality["is_flood"]
            row["screw_reasons"] = quality["screw_reasons"]
            row["is_screw"] = quality["is_screw"]

    summary_dict = {
        "games": int(summary[0] or 0),
        "wins": int(summary[1] or 0),
        "losses": int(summary[2] or 0),
        "draws": int(summary[3] or 0),
        "win_rate": summary[4],
    }
    total_games = summary_dict["games"]
    for row in drawn_card_rows:
        games_seen = row.get("games_seen") or 0
        row["pct_of_games"] = round(100.0 * games_seen / total_games, 1) if total_games else None
    for row in recent_rows:
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
    for row in match_rows:
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
        row["record"] = f"{int(row.get('wins') or 0)}-{int(row.get('losses') or 0)}"
    for row in rank_progress_rows:
        rank_class = str(row.get("rank_class") or "Bronze")
        rank_level = int(row.get("rank_level") or 1)
        rank_step = int(
            row.get("raw_step")
            if row.get("raw_step") is not None
            else row.get("rank_step") or 0
        )
        rank_steps = int(row.get("rank_steps") or 6)
        row["rank_step"] = rank_step
        row["rank_score"] = _rank_score(rank_class, rank_level, rank_step, rank_steps)
        row["rank_label"] = (
            f"{rank_class} {rank_level} ({rank_step}/{rank_steps})"
            if rank_class != "Mythic"
            else f"Mythic #{row['mythic_rank']}"
            if row.get("mythic_rank")
            else "Mythic"
        )
    return {
        "summary": summary_dict,
        "decks": deck_rows,
        "formats": format_rows,
        "midweek_formats": midweek_rows,
        "play_draw": play_draw_rows,
        "deck_play_draw": deck_play_draw_rows,
        "draw_quality": draw_quality_rows,
        "drawn_cards": drawn_card_rows,
        "momentum": momentum_rows,
        "combat_decks": combat_deck_rows,
        "combat_split": combat_split_rows,
        "recent": recent_rows,
        "trend": trend_rows,
        "rank_progress": rank_progress_rows,
        "matches": match_rows,
        "sessions": session_rows,
        "filters": {"deck": deck, "format": fmt, "days": days},
        "filter_options": {"decks": deck_options, "formats": format_options},
    }


def deck_detail(
    db_path: Path = DEFAULT_DB_PATH,
    deck_name: str = "(unknown)",
    fmt: Optional[str] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """Return drill-down analytics for a single deck.

    Raises LookupError when the deck has no recorded games.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    where, params = _games_filter(deck_name, fmt, days)
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        summary = conn.execute(
            f"""
            SELECT
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              SUM(g.outcome = 'draw') AS draws,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM games g
            WHERE {where}
            """,
            params,
        ).fetchone()
        if not summary or not summary[0]:
            raise LookupError(f"No recorded games for deck: {deck_name}")
        profile = conn.execute(
            f"""
            SELECT
              ROUND(AVG(g.duration_seconds), 0) AS avg_duration_seconds,
              ROUND(AVG(g.total_turns), 1) AS avg_turns,
              ROUND(AVG(COALESCE(p.mulligans, 0)), 2) AS avg_mulligans,
              ROUND(100.0 * SUM(p.went_first = 1) / NULLIF(SUM(p.went_first IN (0, 1)), 0), 1) AS on_play_pct
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE {where}
            """,
            params,
        ).fetchone()
        combat_rows = _combat_deck_rows(conn, where, params)
        combat_profile = combat_rows[0] if combat_rows else None
        composition_rows, version_rows, sideboard_summary = _deck_decklist_analysis(
            conn, where, params
        )
        format_rows, midweek_rows = _grouped_format_rows(conn, where, params)
        submitted_cards_by_game: Dict[str, Set[str]] = {}
        if _table_exists(conn, "game_deck_cards"):
            for row in _dict_rows(
                conn.execute(
                    f"""
                    SELECT dc.game_id, dc.display_name
                    FROM game_deck_cards dc
                    JOIN participants p ON p.id = dc.participant_id AND p.role = 'player'
                    JOIN games g ON g.id = dc.game_id
                    WHERE {where}
                    """,
                    params,
                )
            ):
                canonical_name = _arena_export_card_name(conn, str(row["display_name"]))
                submitted_cards_by_game.setdefault(row["game_id"], set()).update(
                    _card_name_aliases(canonical_name)
                )

        observed_deck_cards: Set[str] = set()
        for table_name in ("game_opening_hand_cards", "game_drawn_cards"):
            for row in _dict_rows(
                conn.execute(
                    f"""
                    SELECT owned.display_name
                    FROM {table_name} owned
                    JOIN participants p ON p.id = owned.participant_id AND p.role = 'player'
                    JOIN games g ON g.id = owned.game_id
                    WHERE {where}
                    """,
                    params,
                )
            ):
                observed_deck_cards.update(_card_name_aliases(row.get("display_name")))
        for names in submitted_cards_by_game.values():
            observed_deck_cards.update(names)

        def is_deck_member(game_id: str, display_name: Optional[str]) -> bool:
            aliases = _card_name_aliases(display_name)
            if not aliases:
                return False
            submitted_names = submitted_cards_by_game.get(game_id)
            if submitted_names is not None:
                return not aliases.isdisjoint(submitted_names)
            return not observed_deck_cards or not aliases.isdisjoint(observed_deck_cards)

        raw_card_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  s.game_id,
                  s.display_name,
                  COALESCE(s.type_category, 'Other') AS type_category,
                  COALESCE(s.played_count, 0) AS times_played,
                  g.outcome
                FROM game_card_summary s
                JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
                JOIN games g ON g.id = s.game_id
                WHERE {where}
                """,
                params,
            )
        )
        card_aggregates: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in raw_card_rows:
            if not is_deck_member(row["game_id"], row.get("display_name")):
                continue
            clean_name = _clean_card_name(row.get("display_name"))
            if not clean_name:
                continue
            type_category = str(row.get("type_category") or "Other")
            key = (clean_name, type_category)
            aggregate = card_aggregates.setdefault(
                key,
                {
                    "display_name": clean_name,
                    "type_category": type_category,
                    "game_ids": set(),
                    "times_played": 0,
                    "win_game_ids": set(),
                    "loss_game_ids": set(),
                    "times_drawn": 0,
                },
            )
            aggregate["game_ids"].add(row["game_id"])
            aggregate["times_played"] += int(row.get("times_played") or 0)
            if row.get("outcome") == "win":
                aggregate["win_game_ids"].add(row["game_id"])
            elif row.get("outcome") == "loss":
                aggregate["loss_game_ids"].add(row["game_id"])

        # game_drawn_cards stays the authoritative per-draw source (summary
        # drawn_count is an aggregate maintained since schema migration 3).
        for row in _dict_rows(
            conn.execute(
                f"""
                SELECT d.game_id, d.display_name, COALESCE(d.type_category, 'Other') AS type_category
                FROM game_drawn_cards d
                JOIN participants p ON p.id = d.participant_id AND p.role = 'player'
                JOIN games g ON g.id = d.game_id
                WHERE {where}
                """,
                params,
            )
        ):
            if not is_deck_member(row["game_id"], row.get("display_name")):
                continue
            clean_name = _clean_card_name(row.get("display_name"))
            type_category = str(row.get("type_category") or "Other")
            aggregate = card_aggregates.get((clean_name, type_category))
            if aggregate is None:
                aggregate = next(
                    (
                        item
                        for (name, _category), item in card_aggregates.items()
                        if name == clean_name
                    ),
                    None,
                )
            if aggregate is not None:
                aggregate["times_drawn"] += 1

        card_rows = []
        for aggregate in card_aggregates.values():
            wins = len(aggregate.pop("win_game_ids"))
            losses = len(aggregate.pop("loss_game_ids"))
            games_seen = len(aggregate.pop("game_ids"))
            aggregate.update(
                {
                    "games_seen": games_seen,
                    "wins_when_seen": wins,
                    "losses_when_seen": losses,
                    "win_rate_when_seen": _win_rate(wins, losses),
                }
            )
            card_rows.append(aggregate)
        card_rows.sort(key=lambda row: (-row["games_seen"], row["display_name"]))
        card_rows = card_rows[:100]
        opener_rows = _dict_rows(
            conn.execute(
                f"""
                WITH opener_games AS (
                  SELECT DISTINCT h.game_id, h.display_name, COALESCE(h.type_category, 'Other') AS type_category
                  FROM game_opening_hand_cards h
                  JOIN participants p ON p.id = h.participant_id AND p.role = 'player'
                  JOIN games g ON g.id = h.game_id
                  WHERE {where}
                )
                SELECT
                  og.display_name,
                  og.type_category,
                  COUNT(*) AS games_in_opener,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM opener_games og
                JOIN games g ON g.id = og.game_id
                GROUP BY og.display_name, og.type_category
                ORDER BY games_in_opener DESC, og.display_name
                LIMIT 60
                """,
                params,
            )
        )
        mulligan_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  COALESCE(p.mulligans, 0) AS mulligans,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                GROUP BY COALESCE(p.mulligans, 0)
                ORDER BY mulligans
                """,
                params,
            )
        )
        recent_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  g.id AS game_id,
                  g.started_at,
                  g.outcome,
                  g.duration_seconds,
                  g.total_turns,
                  (
                    SELECT ROUND(AVG(gt.duration_seconds), 1)
                    FROM game_turns gt
                    WHERE gt.game_id = g.id AND gt.seat_id = p.seat_id
                  ) AS player_avg_turn_seconds,
                  (
                    SELECT ROUND(AVG(gt.duration_seconds), 1)
                    FROM game_turns gt
                    JOIN participants timing_opponent
                      ON timing_opponent.game_id = gt.game_id
                     AND timing_opponent.role = 'opponent'
                     AND timing_opponent.seat_id = gt.seat_id
                    WHERE gt.game_id = g.id
                  ) AS opponent_avg_turn_seconds,
                  m.format AS raw_format,
                  m.best_of,
                  p.mulligans,
                  CASE p.went_first WHEN 1 THEN 'On the play' WHEN 0 THEN 'On the draw' ELSE NULL END AS play_draw
                FROM games g
                JOIN matches m ON m.id = g.match_id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                ORDER BY g.started_at DESC
                LIMIT 25
                """,
                params,
            )
        )
        trend_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  g.id AS game_id,
                  COALESCE(g.started_at, g.ended_at) AS started_at,
                  g.outcome
                FROM games g
                WHERE {where} AND g.outcome IN ('win', 'loss')
                ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
                LIMIT 200
                """,
                params,
            )
        )
        trend_rows.reverse()
        deck_visuals = _deck_visuals(conn)
        deck_export = _deck_export_snapshot(conn, where, params, deck_name)

    for row in recent_rows:
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
    for row in opener_rows:
        row["display_name"] = _clean_card_name(row.get("display_name"))
    return {
        "deck_name": deck_name,
        "deck_visual": deck_visuals.get(deck_name, _empty_deck_visual(deck_name)),
        "deck_export": deck_export,
        "summary": {
            "games": int(summary[0] or 0),
            "wins": int(summary[1] or 0),
            "losses": int(summary[2] or 0),
            "draws": int(summary[3] or 0),
            "win_rate": summary[4],
        },
        "profile": {
            "avg_duration_seconds": profile[0],
            "avg_turns": profile[1],
            "avg_mulligans": profile[2],
            "on_play_pct": profile[3],
        },
        "combat_profile": combat_profile,
        "composition": composition_rows,
        "versions": version_rows,
        "sideboard": sideboard_summary,
        "formats": format_rows,
        "midweek_formats": midweek_rows,
        "card_performance": card_rows,
        "opening_hands": opener_rows,
        "mulligans": mulligan_rows,
        "recent": recent_rows,
        "trend": trend_rows,
    }


def game_detail(db_path: Path = DEFAULT_DB_PATH, game_id: str = "") -> Dict[str, Any]:
    """Return a detailed, game-scoped dashboard payload.

    Raises LookupError when the game id is unknown.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        game_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  g.id AS game_id,
                  g.match_id,
                  g.game_number,
                  g.started_at,
                  g.ended_at,
                  g.duration_seconds,
                  g.total_turns,
                  g.player_turns,
                  g.opponent_turns,
                  g.outcome,
                  g.outcome_reason,
                  m.format AS raw_format,
                  m.best_of
                FROM games g
                JOIN matches m ON m.id = g.match_id
                WHERE g.id = ?
                """,
                (game_id,),
            )
        )
        if not game_rows:
            raise LookupError(f"No recorded game for id: {game_id}")
        game = game_rows[0]
        game["format_label"] = format_label(
            game.get("raw_format"), default_best_of=int(game.get("best_of") or 1)
        )

        participant_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  id,
                  role,
                  seat_id,
                  display_name,
                  deck_name,
                  deck_size,
                  went_first,
                  mulligans,
                  opening_hand_size,
                  starting_life,
                  ending_life
                FROM participants
                WHERE game_id = ?
                ORDER BY CASE role WHEN 'player' THEN 0 WHEN 'opponent' THEN 1 ELSE 2 END
                """,
                (game_id,),
            )
        )
        player = next((row for row in participant_rows if row.get("role") == "player"), None)
        opponent = next((row for row in participant_rows if row.get("role") == "opponent"), None)
        player_participant_id = player.get("id") if player else None
        opponent_participant_id = opponent.get("id") if opponent else None

        turn_timings = _dict_rows(
            conn.execute(
                """
                SELECT
                  turn_number,
                  seat_id,
                  started_at,
                  ended_at,
                  duration_seconds,
                  timing_source
                FROM game_turns
                WHERE game_id = ?
                ORDER BY turn_number
                """,
                (game_id,),
            )
        )
        player_seat_id = player.get("seat_id") if player else None
        opponent_seat_id = opponent.get("seat_id") if opponent else None
        for row in turn_timings:
            if player_seat_id is not None and row.get("seat_id") == player_seat_id:
                row["role"] = "player"
            elif opponent_seat_id is not None and row.get("seat_id") == opponent_seat_id:
                row["role"] = "opponent"
            else:
                row["role"] = "unknown"

        def timing_summary(role: str) -> Dict[str, Any]:
            durations = [
                int(row.get("duration_seconds") or 0)
                for row in turn_timings
                if row.get("role") == role
            ]
            if not durations:
                return {"total_seconds": None, "turns_timed": 0, "avg_seconds": None}
            return {
                "total_seconds": sum(durations),
                "turns_timed": len(durations),
                "avg_seconds": round(sum(durations) / len(durations), 1),
            }

        turn_timing_summary = {
            "player": timing_summary("player"),
            "opponent": timing_summary("opponent"),
        }

        opening_hand = _dict_rows(
            conn.execute(
                """
                SELECT display_name, COALESCE(type_category, 'Other') AS type_category, hand_position, copy_number
                FROM game_opening_hand_cards
                WHERE game_id = ? AND participant_id = ?
                ORDER BY hand_position, copy_number
                """,
                (game_id, player_participant_id),
            )
        )
        drawn = _dict_rows(
            conn.execute(
                """
                SELECT display_name, COALESCE(type_category, 'Other') AS type_category, turn_number, draw_position, copy_number
                FROM game_drawn_cards
                WHERE game_id = ? AND participant_id = ?
                ORDER BY draw_position
                """,
                (game_id, player_participant_id),
            )
        )
        stats_drawn_row = conn.execute(
            """
            SELECT cards_drawn
            FROM game_participant_stats
            WHERE game_id = ? AND participant_id = ?
            """,
            (game_id, player_participant_id),
        ).fetchone()
        recorded_draws = int(stats_drawn_row[0] or 0) if stats_drawn_row else 0
        deck_size = int((player or {}).get("deck_size") or 60)
        draw_quality = _draw_quality_metrics(
            opening_hand,
            drawn,
            recorded_draws,
            deck_size,
        )
        cards_played = _dict_rows(
            conn.execute(
                """
                SELECT display_name, COALESCE(type_category, 'Other') AS type_category, played_count
                FROM game_card_summary
                WHERE game_id = ? AND participant_id = ? AND played_count > 0
                ORDER BY played_count DESC, display_name
                """,
                (game_id, player_participant_id),
            )
        )
        for row in cards_played:
            row["display_name"] = _clean_card_name(row.get("display_name"))
        opponent_cards = _dict_rows(
            conn.execute(
                """
                SELECT
                  display_name,
                  COALESCE(type_category, 'Other') AS type_category,
                  played_count,
                  drawn_count,
                  discarded_count,
                  milled_count,
                  exiled_count
                FROM game_card_summary
                WHERE game_id = ?
                  AND participant_id = ?
                  AND (
                    played_count > 0
                    OR drawn_count > 0
                    OR discarded_count > 0
                    OR milled_count > 0
                    OR exiled_count > 0
                  )
                ORDER BY
                  played_count + drawn_count + discarded_count + milled_count + exiled_count DESC,
                  display_name
                """,
                (game_id, opponent_participant_id),
            )
        )
        for row in opponent_cards:
            row["display_name"] = _clean_card_name(row.get("display_name"))

        timeline = _dict_rows(
            conn.execute(
                """
                SELECT
                  turn_number,
                  phase,
                  step,
                  event_type,
                  actor_role,
                  text,
                  player_life,
                  opponent_life
                FROM game_events
                WHERE game_id = ?
                ORDER BY event_time, id
                LIMIT 500
                """,
                (game_id,),
            )
        )
        linkable_cards: Dict[str, Optional[str]] = {}
        for display_name, type_category in conn.execute(
            """
            SELECT DISTINCT display_name, type_category
            FROM game_card_summary
            """
        ):
            clean_name = _clean_card_name(display_name)
            if clean_name and (
                clean_name not in linkable_cards or not linkable_cards[clean_name]
            ):
                linkable_cards[clean_name] = type_category
        for row in timeline:
            row["text_segments"] = _timeline_text_segments(
                str(row.get("text") or ""), linkable_cards
            )
        life_curve = [
            {
                "turn_number": row.get("turn_number"),
                "player_life": row.get("player_life"),
                "opponent_life": row.get("opponent_life"),
            }
            for row in timeline
            if row.get("player_life") is not None and row.get("opponent_life") is not None
        ]
        participant_stats = _dict_rows(
            conn.execute(
                """
                SELECT
                  p.role,
                  s.attack_steps,
                  s.attacking_creatures,
                  s.attackers_lost,
                  s.blocking_creatures,
                  s.blockers_lost,
                  s.damage_dealt,
                  s.damage_taken,
                  s.life_lost,
                  s.self_damage,
                  s.life_gained,
                  s.cards_played,
                  s.cards_drawn,
                  s.cards_discarded,
                  s.cards_milled,
                  s.cards_exiled
                FROM game_participant_stats s
                JOIN participants p ON p.id = s.participant_id
                WHERE s.game_id = ?
                ORDER BY p.role = 'player' DESC
                """,
                (game_id,),
            )
        )

    return {
        "game": game,
        "player": player or {},
        "opponent": opponent or {},
        "participant_stats": participant_stats,
        "opening_hand": opening_hand,
        "drawn": drawn,
        "draw_quality": draw_quality,
        "turn_timing": turn_timing_summary,
        "turns": turn_timings,
        "cards_played": cards_played,
        "opponent_cards": opponent_cards,
        "timeline": timeline,
        "life_curve": life_curve,
    }


def opponent_detail(db_path: Path = DEFAULT_DB_PATH, opponent_name: str = "") -> Dict[str, Any]:
    """Return head-to-head history for one exact Arena opponent name."""
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    requested_name = str(opponent_name or "").strip()
    if not requested_name:
        raise LookupError("Opponent name is required")
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        summary = conn.execute(
            """
            SELECT
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              SUM(g.outcome = 'draw') AS draws,
              ROUND(
                100.0 * SUM(g.outcome = 'win')
                / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0),
                1
              ) AS win_rate,
              MAX(o.display_name) AS display_name
            FROM games g
            JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
            WHERE o.display_name = ? COLLATE NOCASE
            """,
            (requested_name,),
        ).fetchone()
        if not summary or not summary[0]:
            raise LookupError(f"No recorded games against opponent: {requested_name}")
        game_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  g.id AS game_id,
                  g.started_at,
                  g.outcome,
                  g.duration_seconds,
                  g.total_turns,
                  g.player_turns,
                  g.opponent_turns,
                  m.format AS raw_format,
                  m.best_of,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  CASE p.went_first
                    WHEN 1 THEN 'On the play'
                    WHEN 0 THEN 'On the draw'
                    ELSE 'Unknown'
                  END AS play_draw,
                  p.ending_life AS player_final_life,
                  o.ending_life AS opponent_final_life
                FROM games g
                JOIN matches m ON m.id = g.match_id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
                WHERE o.display_name = ? COLLATE NOCASE
                ORDER BY g.started_at DESC, g.id DESC
                """,
                (requested_name,),
            )
        )
    for row in game_rows:
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
    return {
        "opponent_name": summary[5] or requested_name,
        "summary": {
            "games": int(summary[0] or 0),
            "wins": int(summary[1] or 0),
            "losses": int(summary[2] or 0),
            "draws": int(summary[3] or 0),
            "win_rate": summary[4],
        },
        "games": game_rows,
    }


def card_detail(db_path: Path = DEFAULT_DB_PATH, card_name: str = "") -> Dict[str, Any]:
    """Return drill-down analytics for one clean card name.

    Raises LookupError when the card has no summary rows for either participant.
    """
    clean_name = _clean_card_name(card_name) or card_name
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        match_params = (clean_name, f"{clean_name} (%")
        all_usage = conn.execute(
            """
            SELECT
              COUNT(DISTINCT g.id) AS games_seen,
              COALESCE(SUM(s.played_count), 0) AS total_played
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id
            JOIN games g ON g.id = s.game_id
            WHERE s.display_name = ? OR s.display_name LIKE ?
            """,
            match_params,
        ).fetchone()
        if not all_usage or not all_usage[0]:
            raise LookupError(f"No recorded card for name: {clean_name}")
        summary = conn.execute(
            """
            SELECT
              COUNT(DISTINCT g.id) AS games_seen,
              COALESCE(SUM(s.played_count), 0) AS total_played,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
            JOIN games g ON g.id = s.game_id
            WHERE (s.display_name = ? OR s.display_name LIKE ?)
              AND s.played_count > 0
            """,
            match_params,
        ).fetchone()
        by_role = _dict_rows(
            conn.execute(
                """
                SELECT
                  p.role,
                  CASE p.role WHEN 'player' THEN 'You' ELSE 'Opponent' END AS side_label,
                  COUNT(DISTINCT g.id) AS games_seen,
                  COALESCE(SUM(s.played_count), 0) AS total_played,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(
                    100.0 * SUM(g.outcome = 'win')
                    / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0),
                    1
                  ) AS win_rate
                FROM game_card_summary s
                JOIN participants p ON p.id = s.participant_id
                JOIN games g ON g.id = s.game_id
                WHERE (s.display_name = ? OR s.display_name LIKE ?)
                  AND s.played_count > 0
                GROUP BY p.role
                ORDER BY CASE p.role WHEN 'player' THEN 0 ELSE 1 END
                """,
                match_params,
            )
        )
        by_deck = _dict_rows(
            conn.execute(
                """
                SELECT
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  COUNT(DISTINCT g.id) AS games_seen,
                  COALESCE(SUM(s.played_count), 0) AS total_played,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM game_card_summary s
                JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
                JOIN games g ON g.id = s.game_id
                WHERE (s.display_name = ? OR s.display_name LIKE ?)
                  AND s.played_count > 0
                GROUP BY p.deck_name
                ORDER BY games_seen DESC, win_rate DESC, deck_name
                LIMIT 50
                """,
                match_params,
            )
        )
        opener = conn.execute(
            """
            SELECT
              COUNT(DISTINCT g.id) AS games_in_opener,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM game_opening_hand_cards h
            JOIN participants p ON p.id = h.participant_id AND p.role = 'player'
            JOIN games g ON g.id = h.game_id
            WHERE h.display_name = ? OR h.display_name LIKE ?
            """,
            match_params,
        ).fetchone()
        drawn = conn.execute(
            """
            SELECT COUNT(*) AS times_drawn
            FROM game_drawn_cards d
            JOIN participants p ON p.id = d.participant_id AND p.role = 'player'
            WHERE d.display_name = ? OR d.display_name LIKE ?
            """,
            match_params,
        ).fetchone()

    opponent_usage = next((row for row in by_role if row["role"] == "opponent"), None)
    opponent_games = int(opponent_usage["games_seen"] or 0) if opponent_usage else 0
    opponent_wins = int(opponent_usage["wins"] or 0) if opponent_usage else 0
    opponent_losses = int(opponent_usage["losses"] or 0) if opponent_usage else 0
    opponent_decided = opponent_wins + opponent_losses

    return {
        "card_name": clean_name,
        "image_url": _card_image_url(None, clean_name),
        "summary": {
            "games_seen": int(summary[0] or 0),
            "total_played": int(summary[1] or 0),
            "wins": int(summary[2] or 0),
            "losses": int(summary[3] or 0),
            "win_rate": summary[4],
        },
        "all_usage": {
            "games_seen": int(all_usage[0] or 0),
            "total_played": int(all_usage[1] or 0),
            "player_games_seen": next(
                (int(row["games_seen"] or 0) for row in by_role if row["role"] == "player"),
                0,
            ),
            "player_played": next(
                (int(row["total_played"] or 0) for row in by_role if row["role"] == "player"),
                0,
            ),
            "opponent_games_seen": next(
                (int(row["games_seen"] or 0) for row in by_role if row["role"] == "opponent"),
                0,
            ),
            "opponent_played": next(
                (int(row["total_played"] or 0) for row in by_role if row["role"] == "opponent"),
                0,
            ),
        },
        "by_role": by_role,
        "opponent_impact": {
            "games": opponent_games,
            "plays": int(opponent_usage["total_played"] or 0) if opponent_usage else 0,
            "wins": opponent_wins,
            "losses": opponent_losses,
            "win_rate": opponent_usage["win_rate"] if opponent_usage else None,
            "loss_rate": (
                round(100.0 * opponent_losses / opponent_decided, 1)
                if opponent_decided
                else None
            ),
        },
        "by_deck": by_deck,
        "opener_impact": {
            "games_in_opener": int(opener[0] or 0) if opener else 0,
            "wins": int(opener[1] or 0) if opener else 0,
            "losses": int(opener[2] or 0) if opener else 0,
            "win_rate": opener[3] if opener else None,
            "times_drawn": int(drawn[0] or 0) if drawn else 0,
        },
    }


def search_cards(
    db_path: Path = DEFAULT_DB_PATH, query: str = "", limit: int = 8
) -> List[Dict[str, Any]]:
    """Return cards seen on either side of locally tracked games."""
    clean_query = (_clean_card_name(query) or "").strip()
    if not clean_query:
        return []

    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")

    escaped_query = (
        clean_query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    )
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  s.game_id,
                  s.display_name,
                  s.type_category,
                  s.played_count,
                  p.role,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  COALESCE(g.started_at, g.ended_at) AS seen_at
                FROM game_card_summary s
                JOIN participants p ON p.id = s.participant_id
                JOIN games g ON g.id = s.game_id
                WHERE s.display_name LIKE ? ESCAPE '!' COLLATE NOCASE
                  AND NOT EXISTS (
                    SELECT 1 FROM matches mj
                    WHERE mj.id = g.match_id AND mj.format LIKE 'Jump!_In%' ESCAPE '!'
                  )
                """,
                (f"%{escaped_query}%",),
            )
        )

    matches: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        card_name = _clean_card_name(row.get("display_name")) or row["display_name"]
        key = card_name.casefold()
        entry = matches.setdefault(
            key,
            {
                "card_name": card_name,
                "type_category": row.get("type_category") or "Other",
                "game_ids": set(),
                "deck_names": set(),
                "total_played": 0,
                "last_seen_at": None,
            },
        )
        entry["game_ids"].add(row["game_id"])
        if row["role"] == "player" and row["deck_name"] != "(unknown)":
            entry["deck_names"].add(row["deck_name"])
        entry["total_played"] += int(row.get("played_count") or 0)
        if row.get("seen_at") and (
            entry["last_seen_at"] is None or row["seen_at"] > entry["last_seen_at"]
        ):
            entry["last_seen_at"] = row["seen_at"]

    query_folded = clean_query.casefold()
    ranked = sorted(
        matches.values(),
        key=lambda item: (
            0
            if item["card_name"].casefold() == query_folded
            else 1
            if item["card_name"].casefold().startswith(query_folded)
            else 2,
            -len(item["game_ids"]),
            -item["total_played"],
            item["card_name"].casefold(),
        ),
    )
    return [
        {
            "card_name": item["card_name"],
            "type_category": item["type_category"],
            "games_seen": len(item["game_ids"]),
            "deck_count": len(item["deck_names"]),
            "total_played": item["total_played"],
            "last_seen_at": item["last_seen_at"],
        }
        for item in ranked[: max(1, min(limit, 25))]
    ]


def _table(headers: List[str], rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<p class='empty'>No rows yet.</p>"
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(row.get(header, '') if row.get(header, '') is not None else ''))}</td>"
                for header in headers
            )
            + "</tr>"
        )
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_dashboard_html(snapshot: Dict[str, Any]) -> str:
    """Render a simple dashboard HTML document from a snapshot."""
    summary = snapshot["summary"]
    deck_rows = [
        {
            "Deck": row["deck_name"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
        }
        for row in snapshot["decks"]
    ]
    format_rows = [
        {
            "Format": row["format_label"],
            "Raw": row["raw_formats"],
            "Games": row["games"],
            "WR": row["win_rate"],
        }
        for row in snapshot["formats"]
    ]
    play_draw_rows = [
        {
            "Split": row["play_draw"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
        }
        for row in snapshot["play_draw"]
    ]
    draw_quality_rows = [
        {
            "Started": row["started_at"],
            "Deck": row["deck_name"],
            "Outcome": row["outcome"],
            "Seen": row["cards_seen"],
            "Lands": row["lands_seen"],
            "Land %": row["land_seen_pct"],
            "Opening": row["opening_cards"],
            "Known Draws": row["known_draws"],
        }
        for row in snapshot["draw_quality"]
    ]
    drawn_card_rows = [
        {
            "Card": row["display_name"],
            "Type": row["type_category"],
            "Draws": row["times_drawn"],
            "Games": row["games_seen"],
            "% Games": row["pct_of_games"],
        }
        for row in snapshot["drawn_cards"]
    ]
    momentum_rows = [
        {
            "Split": row["split"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
            "Avg Mulligans": row["avg_mulligans"],
            "On Play %": row["on_play_pct"],
        }
        for row in snapshot["momentum"]
    ]
    draw_quality_by_game = {
        row["game_id"]: row for row in snapshot["draw_quality"]
    }
    recent_rows = [
        {
            "Started": row["started_at"],
            "Deck": row["deck_name"],
            "Format": row["format_label"],
            "Outcome": row["outcome"],
            "Draw Status": (
                "Flood"
                if row.get("is_flood")
                else ("Mana Screwed" if row.get("is_screw") else "Normal")
            ),
            "Mulligan(s)": row["mulligans"],
            "Total Turns": row["total_turns"],
            "Cards Seen": draw_quality_by_game.get(row["game_id"], {}).get("cards_seen"),
            "Lands Seen": (
                f"{draw_quality_by_game[row['game_id']]['lands_seen']} "
                f"({math.ceil(draw_quality_by_game[row['game_id']]['land_seen_pct'])}%)"
                if draw_quality_by_game.get(row["game_id"], {}).get("land_seen_pct")
                is not None
                else draw_quality_by_game.get(row["game_id"], {}).get("lands_seen")
            ),
            "Game Time": f"{round((row['duration_seconds'] or 0) / 60.0)} min",
        }
        for row in snapshot["recent"]
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="20">
  <title>MTGA Tracker Dashboard</title>
  <style>
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background: #111827; color: #f9fafb; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 18px; font-size: 32px; }}
    h2 {{ margin-top: 30px; color: #bfdbfe; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }}
    .card {{ background: linear-gradient(135deg, #1f2937, #0f172a); border: 1px solid #374151; border-radius: 16px; padding: 18px; }}
    .label {{ color: #9ca3af; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; }}
    .value {{ font-size: 30px; font-weight: 800; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; background: #0f172a; border: 1px solid #374151; border-radius: 14px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #1f2937; }}
    th {{ color: #93c5fd; background: #111827; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ color: #9ca3af; }}
    .note {{ color: #cbd5e1; margin: 8px 0 14px; max-width: 900px; line-height: 1.45; }}
  </style>
</head>
<body>
<main>
  <h1>MTGA Tracker Dashboard</h1>
  <section class="cards">
    <div class="card"><div class="label">Games</div><div class="value">{summary["games"]}</div></div>
    <div class="card"><div class="label">Wins</div><div class="value">{summary["wins"]}</div></div>
    <div class="card"><div class="label">Losses</div><div class="value">{summary["losses"]}</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value">{summary["win_rate"] or ""}%</div></div>
  </section>
  <h2>Decks</h2>{_table(["Deck", "Games", "Wins", "Losses", "WR"], deck_rows)}
  <h2>Formats</h2>{_table(["Format", "Raw", "Games", "WR"], format_rows)}
  <h2>Play / Draw</h2>{_table(["Split", "Games", "Wins", "Losses", "WR"], play_draw_rows)}
  <h2>Draw Quality</h2>
  <p class="note">Opening hands plus known visible draws. Older games may only have opening-hand data.</p>
  {_table(["Started", "Deck", "Outcome", "Seen", "Lands", "Land %", "Opening", "Known Draws"], draw_quality_rows)}
  <h2>Visible Drawn Cards</h2>{_table(["Card", "Type", "Draws", "Games", "% Games"], drawn_card_rows)}
  <h2>Momentum</h2>
  <p class="note">Next-game results after wins and losses, including mulligans and on-play percentage.</p>
  {_table(["Split", "Games", "Wins", "Losses", "WR", "Avg Mulligans", "On Play %"], momentum_rows)}
  <h2>Recent Games</h2>{_table(["Started", "Deck", "Format", "Outcome", "Flood", "Mulligan(s)", "Total Turns", "Cards Seen", "Lands Seen", "Game Time"], recent_rows)}
</main>
</body>
</html>"""


def render_snapshot_json(snapshot: Dict[str, Any]) -> bytes:
    """Return UTF-8 encoded dashboard JSON."""
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _send_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
    headers: Dict[str, str] | None = None,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def _safe_static_path(static_dir: Path, request_path: str) -> Path | None:
    relative = unquote(request_path.lstrip("/")) or "index.html"
    if relative == "index.html":
        candidate = static_dir / "index.html"
    else:
        candidate = static_dir / relative
    try:
        resolved_static = static_dir.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:
        return None
    if resolved_candidate == resolved_static or resolved_static not in resolved_candidate.parents:
        return None
    if resolved_candidate.is_dir():
        resolved_candidate = resolved_candidate / "index.html"
        try:
            resolved_candidate = resolved_candidate.resolve()
        except OSError:
            return None
        if resolved_candidate == resolved_static or resolved_static not in resolved_candidate.parents:
            return None
    if not resolved_candidate.is_file():
        return None
    return resolved_candidate


def _content_type(path: Path) -> str:
    if path.suffix == ".html":
        return "text/html; charset=utf-8"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler rendering the dashboard on each request."""

    db_path: Path = DEFAULT_DB_PATH
    static_dir: Path | None = DEFAULT_STATIC_DIR if DEFAULT_STATIC_DIR.exists() else None

    def log_message(self, message_format: str, *args: Any) -> None:
        """Avoid writing request logs when a windowed build has no stderr stream."""
        if sys.stderr is not None:
            super().log_message(message_format, *args)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        request_path = parsed.path
        if request_path == "/api/snapshot":
            query = parse_qs(parsed.query)
            deck = query.get("deck", [None])[0] or None
            fmt = query.get("format", [None])[0] or None
            days_raw = query.get("days", [None])[0]
            try:
                days = int(days_raw) if days_raw else None
            except ValueError:
                days = None
            if days is not None and days <= 0:
                days = None
            try:
                body = render_snapshot_json(dashboard_snapshot(self.db_path, deck=deck, fmt=fmt, days=days))
            except FileNotFoundError as exc:
                _send_bytes(
                    self,
                    404,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                _send_bytes(
                    self,
                    500,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if request_path == "/api/deck":
            query = parse_qs(parsed.query)
            deck_name = query.get("name", [None])[0]
            fmt = query.get("format", [None])[0] or None
            days_raw = query.get("days", [None])[0]
            try:
                days = int(days_raw) if days_raw else None
            except ValueError:
                days = None
            if days is not None and days <= 0:
                days = None
            if not deck_name:
                _send_bytes(
                    self,
                    400,
                    b"Missing required query parameter: name",
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            try:
                body = render_snapshot_json(deck_detail(self.db_path, deck_name, fmt=fmt, days=days))
            except (FileNotFoundError, LookupError) as exc:
                _send_bytes(
                    self,
                    404,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                _send_bytes(
                    self,
                    500,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if request_path == "/api/game":
            query = parse_qs(parsed.query)
            game_id = query.get("id", [None])[0]
            if not game_id:
                _send_bytes(
                    self,
                    400,
                    b"Missing required query parameter: id",
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            try:
                body = render_snapshot_json(game_detail(self.db_path, game_id))
            except (FileNotFoundError, LookupError) as exc:
                _send_bytes(
                    self,
                    404,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                _send_bytes(
                    self,
                    500,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if request_path == "/api/opponent":
            query = parse_qs(parsed.query)
            name = query.get("name", [None])[0]
            if not name:
                _send_bytes(
                    self,
                    400,
                    b"Missing required query parameter: name",
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            try:
                body = render_snapshot_json(opponent_detail(self.db_path, name))
            except (FileNotFoundError, LookupError) as exc:
                _send_bytes(
                    self,
                    404,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                _send_bytes(
                    self,
                    500,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if request_path == "/api/card":
            query = parse_qs(parsed.query)
            name = query.get("name", [None])[0]
            if not name:
                _send_bytes(
                    self,
                    400,
                    b"Missing required query parameter: name",
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            try:
                body = render_snapshot_json(card_detail(self.db_path, name))
            except (FileNotFoundError, LookupError) as exc:
                _send_bytes(
                    self,
                    404,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                _send_bytes(
                    self,
                    500,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if request_path == "/api/cards":
            query = parse_qs(parsed.query)
            search_query = query.get("q", [None])[0]
            limit_raw = query.get("limit", [None])[0]
            if not search_query:
                _send_bytes(
                    self,
                    400,
                    b"Missing required query parameter: q",
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            try:
                limit = int(limit_raw) if limit_raw else 8
            except ValueError:
                limit = 8
            try:
                body = render_snapshot_json(search_cards(self.db_path, search_query, limit))
            except FileNotFoundError as exc:
                _send_bytes(
                    self,
                    404,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                _send_bytes(
                    self,
                    500,
                    str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return
        if self.static_dir:
            static_path = _safe_static_path(Path(self.static_dir), request_path)
            if static_path:
                _send_bytes(self, 200, static_path.read_bytes(), _content_type(static_path))
                return
            if request_path not in {"/", "/index.html"}:
                self.send_error(404)
                return
        if request_path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        try:
            body = render_dashboard_html(dashboard_snapshot(self.db_path)).encode("utf-8")
        except FileNotFoundError as exc:
            _send_bytes(self, 404, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        except Exception as exc:
            _send_bytes(self, 500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        _send_bytes(self, 200, body, "text/html; charset=utf-8")


def create_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    static_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """Create a configured dashboard server without mutating global handler state."""
    resolved_static_dir = static_dir if static_dir is not None else DEFAULT_STATIC_DIR
    handler_class = type(
        "ConfiguredDashboardHandler",
        (DashboardHandler,),
        {
            "db_path": Path(db_path).expanduser(),
            "static_dir": resolved_static_dir if resolved_static_dir.exists() else None,
        },
    )
    return ThreadingHTTPServer((host, port), handler_class)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local MTGA tracker dashboard.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port.")
    args = parser.parse_args()

    server = create_dashboard_server(args.host, args.port, db_path=args.db)
    print(f"Dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nExiting dashboard...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
