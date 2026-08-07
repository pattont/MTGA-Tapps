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
import time
import traceback
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
from .colors import color_combo_label, normalize_colors
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


def _opponent_color_letters(conn: sqlite3.Connection, game_id: str, participant_id: str) -> str:
    """WUBRG letters seen across the opponent's revealed cards in one game."""
    try:
        rows = conn.execute(
            """
            SELECT c.color_identity
            FROM game_card_summary s
            JOIN cards c ON c.id = s.card_id
            WHERE s.game_id = ? AND s.participant_id = ?
              AND COALESCE(c.color_identity, '') != ''
            """,
            (game_id, participant_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return ""
    return normalize_colors("".join(str(row[0] or "") for row in rows))


def _dominant_player_name(conn: sqlite3.Connection) -> Optional[str]:
    """The player name seen in the most games (newest wins ties).

    Multiple Arena accounts can share one computer; the dashboard greets
    whichever name owns the bulk of the tracked history.
    """
    try:
        row = conn.execute(
            """
            SELECT p.display_name
            FROM participants p
            JOIN games g ON g.id = p.game_id
            WHERE p.role = 'player' AND COALESCE(p.display_name, '') != ''
            GROUP BY p.display_name
            ORDER BY COUNT(*) DESC, MAX(g.started_at) DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row[0]:
        return None
    # Arena names can carry a "#12345" discriminator; the greeting doesn't need it.
    return str(row[0]).split("#", 1)[0].strip() or None


def _split_name_variants(conn: sqlite3.Connection, clean_name: str) -> List[str]:
    """All base names that refer to the same physical card as clean_name.

    Split/room/adventure cards resolve each half as its own game object, so
    stats can exist under "Unholy Annex", "Ritual Chamber", and the full
    "Unholy Annex // Ritual Chamber". Given any one of those, return them all.
    """
    variants = {clean_name}
    full_base: Optional[str] = None
    if " // " in clean_name:
        full_base = clean_name
    else:
        for (name,) in conn.execute("SELECT name FROM cards WHERE name LIKE '% // %'"):
            base = _clean_card_name(name) or str(name)
            halves = [half.strip() for half in base.split(" // ")]
            if clean_name in halves:
                full_base = base
                break
    if full_base:
        variants.add(full_base)
        variants.update(half.strip() for half in full_base.split(" // ") if half.strip())
    return sorted(variants)


def _card_name_clause(alias: str, variants: List[str]) -> str:
    """SQL fragment matching a display-name column against every variant."""
    column = f"{alias}.display_name" if alias else "display_name"
    return "(" + " OR ".join([f"{column} = ? OR {column} LIKE ?"] * len(variants)) + ")"


def _card_name_params(variants: List[str]) -> Tuple[str, ...]:
    return tuple(param for variant in variants for param in (variant, f"{variant} (%"))


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
                    "games_seen_multiple": 0,
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
                if copies_seen >= 2:
                    entry["games_seen_multiple"] += 1
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
        entry["multiple_pct"] = (
            round(100.0 * entry["games_seen_multiple"] / entry["games_in_deck"], 1)
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
    # Per-card swap aggregation: each post-board game is diffed against the
    # PREVIOUS game's submitted maindeck, so game-3 re-boarding counts too.
    swap_stats: Dict[str, Dict[str, Any]] = {}
    swap_game_ids: set = set()
    multi_game_matches = 0

    def _swap_bucket(name: str) -> Dict[str, Any]:
        return swap_stats.setdefault(
            name,
            {
                "display_name": name,
                "boarded_in": 0,
                "boarded_out": 0,
                "games_in": 0,
                "wins_in": 0,
                "losses_in": 0,
                "vs_in": {},
                "vs_out": {},
            },
        )

    swap_events: List[Dict[str, Any]] = []
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
            if index > 0:
                previous_signature = signature_by_game.get(ordered[index - 1]["game_id"])
                signature = signature_by_game.get(game["game_id"])
                if previous_signature is None or signature is None:
                    continue
                before = dict(previous_signature)
                after = dict(signature)
                for name in set(before) | set(after):
                    delta = after.get(name, 0) - before.get(name, 0)
                    if delta == 0:
                        continue
                    if delta > 0:
                        boarded_in[name] = boarded_in.get(name, 0) + delta
                    swap_events.append(
                        {
                            "name": name,
                            "delta": delta,
                            "game_id": game["game_id"],
                            "outcome": game.get("outcome"),
                        }
                    )
                    swap_game_ids.add(game["game_id"])

    # Opponent color combo per post-board game with at least one swap.
    combo_by_game: Dict[str, Optional[str]] = {}
    for game_id in swap_game_ids:
        participant_row = conn.execute(
            "SELECT id FROM participants WHERE game_id = ? AND role = 'opponent'",
            (game_id,),
        ).fetchone()
        letters = (
            _opponent_color_letters(conn, game_id, str(participant_row[0]))
            if participant_row
            else ""
        )
        combo_by_game[game_id] = color_combo_label(letters)

    for event in swap_events:
        stats = _swap_bucket(event["name"])
        combo = combo_by_game.get(event["game_id"])
        if event["delta"] > 0:
            stats["boarded_in"] += event["delta"]
            stats["games_in"] += 1
            if event["outcome"] == "win":
                stats["wins_in"] += 1
            elif event["outcome"] == "loss":
                stats["losses_in"] += 1
            if combo:
                stats["vs_in"][combo] = stats["vs_in"].get(combo, 0) + 1
        else:
            stats["boarded_out"] += -event["delta"]
            if combo:
                stats["vs_out"][combo] = stats["vs_out"].get(combo, 0) + 1

    def _top_combos(counter: Dict[str, int]) -> str:
        ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:2]
        return " · ".join(
            f"{label} ×{count}" if count > 1 else label for label, count in ranked
        )

    swap_rows = []
    for stats in swap_stats.values():
        decided = stats["wins_in"] + stats["losses_in"]
        swap_rows.append(
            {
                "display_name": stats["display_name"],
                "boarded_in": stats["boarded_in"],
                "boarded_out": stats["boarded_out"],
                "games_in": stats["games_in"],
                "wins_in": stats["wins_in"],
                "losses_in": stats["losses_in"],
                "win_rate_in": round(100.0 * stats["wins_in"] / decided, 1)
                if decided
                else None,
                "vs_in": _top_combos(stats["vs_in"]),
                "vs_out": _top_combos(stats["vs_out"]),
            }
        )
    swap_rows.sort(
        key=lambda row: (
            -(row["boarded_in"] + row["boarded_out"]),
            row["display_name"].casefold(),
        )
    )

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
            "swaps": swap_rows[:20],
        }

    return composition_rows, version_rows, sideboard_summary


def _opponent_threat_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> List[Dict[str, Any]]:
    """Opponent-side cards ranked by how often they appear in your losses."""
    rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              s.display_name,
              COALESCE(s.type_category, 'Other') AS type_category,
              COUNT(DISTINCT g.id) AS games,
              COALESCE(SUM(s.played_count), 0) AS plays,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'loss') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS loss_rate
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id AND p.role = 'opponent'
            JOIN games g ON g.id = s.game_id
            WHERE {where} AND s.played_count > 0
            GROUP BY s.display_name
            HAVING COUNT(DISTINCT g.id) >= 2
            ORDER BY loss_rate DESC, games DESC, s.display_name COLLATE NOCASE
            LIMIT 30
            """,
            params,
        )
    )
    for row in rows:
        row["display_name"] = _clean_card_name(row.get("display_name"))
    return rows


def _matchup_rows(conn: sqlite3.Connection, where: str, params: List[Any]) -> List[Dict[str, Any]]:
    """Your deck vs identified opponent archetype win rates."""
    has_archetypes = conn.execute(
        "SELECT 1 FROM participants WHERE role = 'opponent' AND deck_archetype IS NOT NULL LIMIT 1"
    ).fetchone()
    if not has_archetypes:
        return []
    return _dict_rows(
        conn.execute(
            f"""
            SELECT
              COALESCE(pp.deck_name, '(unknown)') AS deck_name,
              COALESCE(po.deck_archetype, '(unidentified)') AS opponent_archetype,
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM games g
            JOIN participants pp ON pp.game_id = g.id AND pp.role = 'player'
            JOIN participants po ON po.game_id = g.id AND po.role = 'opponent'
            WHERE {where}
            GROUP BY COALESCE(pp.deck_name, '(unknown)'), COALESCE(po.deck_archetype, '(unidentified)')
            ORDER BY COALESCE(pp.deck_name, '(unknown)') COLLATE NOCASE, games DESC
            """,
            params,
        )
    )


def _opponent_color_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> List[Dict[str, Any]]:
    """Win/loss record grouped by the opponent's revealed color combination."""
    try:
        rows = conn.execute(
            f"""
            SELECT
              g.id,
              g.outcome,
              (
                SELECT GROUP_CONCAT(COALESCE(c.color_identity, ''), '')
                FROM game_card_summary s
                JOIN cards c ON c.id = s.card_id
                WHERE s.game_id = g.id AND s.participant_id = po.id
              ) AS letters
            FROM games g
            JOIN participants po ON po.game_id = g.id AND po.role = 'opponent'
            WHERE {where}
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    buckets: Dict[str, Dict[str, Any]] = {}
    for _game_id, outcome, letters in rows:
        colors = normalize_colors(str(letters or ""))
        label = color_combo_label(colors)
        if not label:
            # No opponent cards captured (quick concede or a legacy
            # half-tracked game) — nothing actionable to bucket.
            continue
        entry = buckets.setdefault(
            label, {"color_label": label, "colors": colors, "games": 0, "wins": 0, "losses": 0}
        )
        entry["games"] += 1
        if outcome == "win":
            entry["wins"] += 1
        elif outcome == "loss":
            entry["losses"] += 1
    total_games = sum(entry["games"] for entry in buckets.values())
    result = []
    for entry in buckets.values():
        entry["win_rate"] = _win_rate(entry["wins"], entry["losses"])
        entry["pct_of_games"] = (
            round(100.0 * entry["games"] / total_games, 1) if total_games else None
        )
        result.append(entry)
    result.sort(key=lambda item: (-item["games"], item["color_label"]))
    return result


def _schedule_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """Win rate by weekday and by time-of-day bucket."""
    weekday_rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              CAST(strftime('%w', COALESCE(g.started_at, g.ended_at)) AS INTEGER) AS weekday,
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM games g
            WHERE {where} AND COALESCE(g.started_at, g.ended_at) IS NOT NULL
            GROUP BY weekday
            ORDER BY weekday
            """,
            params,
        )
    )
    weekday_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    for row in weekday_rows:
        index = row.get("weekday")
        row["label"] = weekday_names[int(index)] if index is not None else "Unknown"

    hour_rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              CASE
                WHEN CAST(strftime('%H', COALESCE(g.started_at, g.ended_at)) AS INTEGER) BETWEEN 5 AND 11 THEN 0
                WHEN CAST(strftime('%H', COALESCE(g.started_at, g.ended_at)) AS INTEGER) BETWEEN 12 AND 16 THEN 1
                WHEN CAST(strftime('%H', COALESCE(g.started_at, g.ended_at)) AS INTEGER) BETWEEN 17 AND 21 THEN 2
                ELSE 3
              END AS bucket,
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM games g
            WHERE {where} AND COALESCE(g.started_at, g.ended_at) IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket
            """,
            params,
        )
    )
    bucket_labels = {
        0: "Morning (5am–noon)",
        1: "Afternoon (noon–5pm)",
        2: "Evening (5pm–10pm)",
        3: "Late Night (10pm–5am)",
    }
    for row in hour_rows:
        row["label"] = bucket_labels.get(int(row.get("bucket") or 0), "Unknown")
    return {"by_weekday": weekday_rows, "by_time_of_day": hour_rows}


def _fatigue_rows(conn: sqlite3.Connection, where: str, params: List[Any]) -> List[Dict[str, Any]]:
    """Win rate by Nth game of a tracker session."""
    rows = _dict_rows(
        conn.execute(
            f"""
            WITH ordered AS (
              SELECT
                g.outcome,
                ROW_NUMBER() OVER (
                  PARTITION BY g.session_id
                  ORDER BY COALESCE(g.started_at, g.ended_at), g.id
                ) AS nth
              FROM games g
              WHERE {where}
            )
            SELECT
              CASE
                WHEN nth <= 4 THEN 0
                WHEN nth <= 9 THEN 1
                WHEN nth <= 14 THEN 2
                WHEN nth <= 19 THEN 3
                ELSE 4
              END AS bucket,
              COUNT(*) AS games,
              SUM(outcome = 'win') AS wins,
              SUM(outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(outcome = 'win') / NULLIF(SUM(outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM ordered
            GROUP BY bucket
            ORDER BY bucket
            """,
            params,
        )
    )
    # Fresh baseline is games 1–4; fatigue only plausibly sets in from game 5,
    # and marathon 20+ game sessions are common enough to earn their own tier.
    labels = {
        0: "Games 1–4",
        1: "Games 5–9",
        2: "Games 10–14",
        3: "Games 15–19",
        4: "Games 20+",
    }
    for row in rows:
        row["label"] = labels.get(int(row.get("bucket") or 0), "Unknown")
    return rows


def _streak_summary(conn: sqlite3.Connection, where: str, params: List[Any]) -> Dict[str, Any]:
    """Current and longest win/loss streaks over the filtered games."""
    outcomes = [
        row[0]
        for row in conn.execute(
            f"""
            SELECT g.outcome
            FROM games g
            WHERE {where} AND g.outcome IN ('win', 'loss')
            ORDER BY COALESCE(g.started_at, g.ended_at), g.id
            """,
            params,
        )
    ]
    longest_win = longest_loss = 0
    current_run = 0
    current_kind: Optional[str] = None
    for outcome in outcomes:
        if outcome == current_kind:
            current_run += 1
        else:
            current_kind = outcome
            current_run = 1
        if outcome == "win":
            longest_win = max(longest_win, current_run)
        else:
            longest_loss = max(longest_loss, current_run)
    current = {"kind": current_kind, "length": current_run} if current_kind else None
    return {
        "games": len(outcomes),
        "current": current,
        "longest_win": longest_win,
        "longest_loss": longest_loss,
    }


def _outcome_reason_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> List[Dict[str, Any]]:
    """How wins and losses actually end (concession, damage, timeout...)."""
    return _dict_rows(
        conn.execute(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(g.outcome_reason), ''), 'unknown') AS reason,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              COUNT(*) AS games
            FROM games g
            WHERE {where} AND g.outcome IN ('win', 'loss')
            GROUP BY reason
            ORDER BY games DESC
            """,
            params,
        )
    )


def _opener_land_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> List[Dict[str, Any]]:
    """Win rate by number of lands in the kept opening hand."""
    rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              MIN(opener_lands, 5) AS lands,
              COUNT(*) AS games,
              SUM(outcome = 'win') AS wins,
              SUM(outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(outcome = 'win') / NULLIF(SUM(outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM (
              SELECT
                g.outcome,
                (
                  SELECT COUNT(*) FROM game_opening_hand_cards oh
                  WHERE oh.participant_id = p.id
                    AND (oh.type_category = 'Land' OR oh.display_name LIKE '%(Land)')
                ) AS opener_lands,
                (
                  SELECT COUNT(*) FROM game_opening_hand_cards oh
                  WHERE oh.participant_id = p.id
                ) AS opener_cards
              FROM games g
              JOIN participants p ON p.game_id = g.id AND p.role = 'player'
              WHERE {where} AND g.outcome IN ('win', 'loss')
            )
            WHERE opener_cards > 0
            GROUP BY MIN(opener_lands, 5)
            ORDER BY lands
            """,
            params,
        )
    )
    for row in rows:
        lands = int(row.get("lands") or 0)
        row["label"] = "5+ lands" if lands >= 5 else f"{lands} {'land' if lands == 1 else 'lands'}"
    return rows


def _mana_readiness_rows(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> List[Dict[str, Any]]:
    """Land availability on curve: had N lands by (global) turn N, with win rates.

    Uses opening-hand lands plus visible drawn lands with a known turn number.
    Games with unknown-turn land draws are excluded per threshold to avoid
    counting a land as late/early when its draw turn was not captured.
    """
    games = _dict_rows(
        conn.execute(
            f"""
            SELECT
              g.id AS game_id,
              g.outcome,
              p.id AS participant_id,
              (
                SELECT COUNT(*) FROM game_opening_hand_cards oh
                WHERE oh.participant_id = p.id
                  AND (oh.type_category = 'Land' OR oh.display_name LIKE '%(Land)')
              ) AS opening_lands,
              (
                SELECT COUNT(*) FROM game_opening_hand_cards oh
                WHERE oh.participant_id = p.id
              ) AS opening_cards
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE {where} AND g.outcome IN ('win', 'loss')
            """,
            params,
        )
    )
    if not games:
        return []
    participant_ids = [row["participant_id"] for row in games]
    placeholders = ",".join("?" for _ in participant_ids)
    land_draws: Dict[str, List[Optional[int]]] = {}
    for row in _dict_rows(
        conn.execute(
            f"""
            SELECT participant_id, turn_number
            FROM game_drawn_cards
            WHERE participant_id IN ({placeholders})
              AND (type_category = 'Land' OR display_name LIKE '%(Land)')
            """,
            participant_ids,
        )
    ):
        land_draws.setdefault(row["participant_id"], []).append(row["turn_number"])

    rows: List[Dict[str, Any]] = []
    for threshold in (2, 3, 4, 5):
        on_time = {"wins": 0, "losses": 0}
        behind = {"wins": 0, "losses": 0}
        eligible = 0
        for game in games:
            if not int(game.get("opening_cards") or 0):
                continue
            draws = land_draws.get(game["participant_id"], [])
            if any(turn is None for turn in draws):
                continue
            eligible += 1
            lands_by_turn = int(game.get("opening_lands") or 0) + sum(
                1 for turn in draws if turn is not None and int(turn) <= threshold
            )
            bucket = on_time if lands_by_turn >= threshold else behind
            if game.get("outcome") == "win":
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
        if not eligible:
            continue
        on_time_games = on_time["wins"] + on_time["losses"]
        behind_games = behind["wins"] + behind["losses"]
        rows.append(
            {
                "threshold": threshold,
                "label": f"{threshold} lands by turn {threshold}",
                "games": eligible,
                "on_time_games": on_time_games,
                "on_time_pct": round(100.0 * on_time_games / eligible, 1),
                "on_time_win_rate": (
                    round(100.0 * on_time["wins"] / on_time_games, 1) if on_time_games else None
                ),
                "behind_games": behind_games,
                "behind_win_rate": (
                    round(100.0 * behind["wins"] / behind_games, 1) if behind_games else None
                ),
            }
        )
    return rows


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
        # Aggression is judged by damage pace (damage dealt per one of your
        # turns), not attack frequency: decks that close games through drain,
        # burn, or a few big swings attack on well under half their turns but
        # are still aggressive, while grindy decks can attack often and slowly.
        attacks = row.get("avg_attack_steps") or 0
        turns = row.get("avg_player_turns") or 0
        damage = row.get("avg_damage_dealt") or 0
        damage_per_turn = (damage / turns) if turns else None
        attacks_per_turn = (attacks / turns) if turns else 0
        row["damage_per_turn"] = round(damage_per_turn, 2) if damage_per_turn else None
        if damage_per_turn is None:
            row["aggression_profile"] = None
        elif damage_per_turn >= 3.2 or (damage_per_turn >= 2.9 and turns <= 5.5):
            row["aggression_profile"] = "Aggro"
        elif damage_per_turn <= 2.4 or (attacks_per_turn <= 0.2 and damage_per_turn <= 2.7):
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
    deck: Optional[str],
    fmt: Optional[str],
    days: Optional[int],
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    """WHERE fragment (referencing games alias `g`) plus bound params."""
    # Jump In and Midweek Magic games are intentionally untracked; hide them
    # from every aggregate even if legacy rows linger in the database.
    clauses = [
        """NOT EXISTS (
          SELECT 1 FROM matches mj
          WHERE mj.id = g.match_id AND (
            mj.format LIKE 'Jump!_In%' ESCAPE '!'
            OR mj.format LIKE 'MWM%'
            OR mj.format LIKE 'Midweek%'
            OR COALESCE(mj.queue, '') LIKE 'MWM%'
            OR COALESCE(mj.event_name, '') LIKE 'MWM%'
          )
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
    if since:
        clauses.append("COALESCE(g.started_at, g.ended_at) >= ?")
        params.append(f"{since}T00:00:00" if len(since) == 10 else since)
    if until:
        clauses.append("COALESCE(g.started_at, g.ended_at) <= ?")
        params.append(f"{until}T23:59:59" if len(until) == 10 else until)
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
    season: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Return dashboard-friendly aggregate data from SQLite.

    Optional filters narrow every aggregate: `deck` matches the player's deck
    name, `fmt` matches the raw queue/format string, and `days` keeps games
    started within the last N days.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    where, params = _games_filter(deck, fmt, days, since, until)
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
                  g.match_id,
                  g.game_number,
                  g.started_at,
                  g.outcome,
                  g.duration_seconds,
                  g.total_turns,
                  p.id AS player_participant_id,
                  p.deck_size,
                  m.format AS raw_format,
                  m.best_of,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  p.mulligans,
                  (
                    SELECT SUM(g2.outcome = 'win') FROM games g2
                    WHERE g2.match_id = g.match_id
                  ) AS match_wins,
                  (
                    SELECT SUM(g2.outcome = 'loss') FROM games g2
                    WHERE g2.match_id = g.match_id
                  ) AS match_losses,
                  (
                    SELECT GROUP_CONCAT(COALESCE(c.color_identity, ''), '')
                    FROM game_card_summary s
                    JOIN participants po ON po.id = s.participant_id AND po.role = 'opponent'
                    JOIN cards c ON c.id = s.card_id
                    WHERE s.game_id = g.id AND po.game_id = g.id
                  ) AS opp_color_letters
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
                  AND r.season_ordinal = COALESCE(
                    ?,
                    (
                      SELECT MAX(season_ordinal)
                      FROM rank_snapshots
                      WHERE rank_format = 'constructed'
                    )
                  )
                ORDER BY r.captured_at, r.id
                """,
                (season,),
            )
        )
        rank_seasons = [
            int(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT season_ordinal FROM rank_snapshots
                WHERE rank_format = 'constructed'
                ORDER BY season_ordinal DESC
                """
            )
        ]
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
        mana_readiness_rows = _mana_readiness_rows(conn, where, params)
        schedule = _schedule_rows(conn, where, params)
        fatigue_rows = _fatigue_rows(conn, where, params)
        streaks = _streak_summary(conn, where, params)
        outcome_reason_rows = _outcome_reason_rows(conn, where, params)
        opener_land_rows = _opener_land_rows(conn, where, params)
        opponent_threat_rows = _opponent_threat_rows(conn, where, params)
        matchup_rows = _matchup_rows(conn, where, params)
        opponent_color_rows = _opponent_color_rows(conn, where, params)
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
        "player_name": _dominant_player_name(conn),
    }
    total_games = summary_dict["games"]
    for row in drawn_card_rows:
        games_seen = row.get("games_seen") or 0
        row["pct_of_games"] = round(100.0 * games_seen / total_games, 1) if total_games else None
    for row in recent_rows:
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
        row["opp_colors"] = normalize_colors(str(row.pop("opp_color_letters", "") or ""))
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
        "mana_readiness": mana_readiness_rows,
        "schedule": schedule,
        "fatigue": fatigue_rows,
        "streaks": streaks,
        "outcome_reasons": outcome_reason_rows,
        "opener_lands": opener_land_rows,
        "opponent_threats": opponent_threat_rows,
        "opponent_colors": opponent_color_rows,
        "matchups": matchup_rows,
        "recent": recent_rows,
        "trend": trend_rows,
        "rank_progress": rank_progress_rows,
        "matches": match_rows,
        "sessions": session_rows,
        "filters": {
            "deck": deck,
            "format": fmt,
            "days": days,
            "season": season,
            "since": since,
            "until": until,
        },
        "filter_options": {
            "decks": deck_options,
            "formats": format_options,
            "rank_seasons": rank_seasons,
        },
    }


def deck_detail(
    db_path: Path = DEFAULT_DB_PATH,
    deck_name: str = "(unknown)",
    fmt: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Return drill-down analytics for a single deck.

    Raises LookupError when the deck has no recorded games.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    where, params = _games_filter(deck_name, fmt, days, since, until)
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
        streaks = _streak_summary(conn, where, params)
        composition_rows, version_rows, sideboard_summary = _deck_decklist_analysis(
            conn, where, params
        )
        mana_readiness_rows = _mana_readiness_rows(conn, where, params)
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
                  p.id AS player_participant_id,
                  p.deck_size,
                  CASE p.went_first WHEN 1 THEN 'On the play' WHEN 0 THEN 'On the draw' ELSE NULL END AS play_draw,
                  (
                    SELECT GROUP_CONCAT(COALESCE(c.color_identity, ''), '')
                    FROM game_card_summary s
                    JOIN participants po ON po.id = s.participant_id AND po.role = 'opponent'
                    JOIN cards c ON c.id = s.card_id
                    WHERE s.game_id = g.id AND po.game_id = g.id
                  ) AS opp_color_letters
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
        opponent_color_rows = _opponent_color_rows(conn, where, params)
        land_profile = _deck_land_profile(conn, where, params)
        account_rows = _dict_rows(
            conn.execute(
                f"""
                SELECT p.display_name AS name, COUNT(*) AS games
                FROM games g
                JOIN matches m ON m.id = g.match_id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where} AND COALESCE(p.display_name, '') != ''
                GROUP BY p.display_name
                ORDER BY games DESC
                """,
                params,
            )
        )
        for row in recent_rows:
            quality = _game_draw_quality(
                conn,
                str(row.get("game_id")),
                row.pop("player_participant_id", None),
                row.pop("deck_size", None),
            )
            row["is_flood"] = quality["is_flood"]
            row["is_screw"] = quality["is_screw"]

    for row in recent_rows:
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
        row["opp_colors"] = normalize_colors(str(row.pop("opp_color_letters", "") or ""))
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
        "streaks": streaks,
        "composition": composition_rows,
        "versions": version_rows,
        "opponent_colors": opponent_color_rows,
        "sideboard": sideboard_summary,
        "accounts": account_rows,
        "land_profile": land_profile,
        "mana_readiness": mana_readiness_rows,
        "formats": format_rows,
        "midweek_formats": midweek_rows,
        "card_performance": card_rows,
        "opening_hands": opener_rows,
        "mulligans": mulligan_rows,
        "recent": recent_rows,
        "trend": trend_rows,
    }


#: Tables emptied by a dashboard-initiated reset, in FK-safe order. The cards
#: reference cache and schema_migrations survive — a reset starts tracking
#: history fresh, it does not un-migrate the schema.
RESET_TABLES = (
    "game_mulligan_hands",
    "game_opening_hand_cards",
    "game_drawn_cards",
    "game_card_summary",
    "game_participant_stats",
    "game_turns",
    "game_events",
    "game_deck_cards",
    "game_annotations",
    "participant_commanders",
    "participants",
    "games",
    "matches",
    "session_participant_stats",
    "console_logs",
    "raw_game_payloads",
    "rank_snapshots",
    "tracker_sessions",
)


def reset_database(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Wipe all tracked history after writing a timestamped backup.

    Uses SQLite's online backup API, then empties every stats table (keeping
    the cards cache and applied schema_migrations) and VACUUMs. Returns the
    backup path so the UI can tell the user where their old data went.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.backup.{timestamp}.pre-reset")
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        backup_conn = sqlite3.connect(str(backup_path))
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        existing = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        with conn:
            for table_name in RESET_TABLES:
                if table_name in existing:
                    conn.execute(f"DELETE FROM {table_name}")
            if "sqlite_sequence" in existing:
                conn.execute("DELETE FROM sqlite_sequence")
        conn.execute("VACUUM")
        # Fold the (large) post-VACUUM WAL back into the main file so the
        # on-disk size visibly shrinks right away.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return {"ok": True, "backup": str(backup_path)}


def _deck_land_profile(
    conn: sqlite3.Connection, where: str, params: List[Any]
) -> Dict[str, Any]:
    """Flood / screw / normal split across a deck's games, plus land count.

    Lands and deck size come from the newest submitted decklist; the per-game
    classification reuses the shared draw-quality rules. Games with no visible
    cards (nothing to classify) are excluded from the split.
    """
    game_rows = conn.execute(
        f"""
        SELECT g.id, p.id AS participant_id, p.deck_size
        FROM games g
        JOIN matches m ON m.id = g.match_id
        JOIN participants p ON p.game_id = g.id AND p.role = 'player'
        WHERE {where}
        ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
        """,
        params,
    ).fetchall()
    deck_size: Optional[int] = None
    lands: Optional[int] = None
    flood = screw = normal = 0
    for game_id, participant_id, row_deck_size in game_rows:
        if deck_size is None:
            decklist = deck_land_stats(conn, str(game_id), participant_id)
            if decklist is not None:
                deck_size, lands = decklist
        quality = _game_draw_quality(
            conn, str(game_id), participant_id, row_deck_size
        )
        if not quality.get("total_cards_seen"):
            continue
        if quality.get("is_flood"):
            flood += 1
        elif quality.get("is_screw"):
            screw += 1
        else:
            normal += 1
    classified = flood + screw + normal
    return {
        "deck_size": deck_size,
        "lands": lands,
        "flood_games": flood,
        "screw_games": screw,
        "normal_games": normal,
        "classified_games": classified,
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
                f"""
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
                  deck_archetype,
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
        try:
            mulligan_hand_rows = _dict_rows(
                conn.execute(
                    """
                    SELECT m.hand_number, m.hand_position, m.display_name,
                           COALESCE(
                             m.type_category,
                             c.primary_type,
                             (
                               SELECT c2.primary_type FROM cards c2
                               WHERE (c2.name = m.display_name OR c2.name LIKE m.display_name || ' (%')
                                 AND COALESCE(c2.primary_type, 'Other') != 'Other'
                               LIMIT 1
                             ),
                             'Other'
                           ) AS type_category,
                           m.bottomed
                    FROM game_mulligan_hands m
                    LEFT JOIN cards c ON c.id = m.card_id
                    WHERE m.game_id = ? AND m.participant_id = ?
                    ORDER BY m.hand_number, m.hand_position
                    """,
                    (game_id, player_participant_id),
                )
            )
        except sqlite3.OperationalError:
            # Databases written before the mulligan-history feature lack this table.
            mulligan_hand_rows = []
        hands_by_number: Dict[int, Dict[str, Any]] = {}
        for row in mulligan_hand_rows:
            hand_number = int(row["hand_number"] or 0)
            entry = hands_by_number.setdefault(
                hand_number, {"hand_number": hand_number, "cards": []}
            )
            entry["cards"].append(
                {
                    "hand_position": row["hand_position"],
                    "display_name": row["display_name"],
                    "type_category": row["type_category"],
                    "bottomed": bool(row["bottomed"]),
                }
            )
        # Backfilled games may only know the final hand; return only hands
        # whose cards were actually recorded.
        mulligan_hands = [hands_by_number[key] for key in sorted(hands_by_number)]
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
                LIMIT 10000
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
        opponent_colors = _opponent_color_letters(conn, game_id, opponent_participant_id)
        # Multi-account machines: flag which account played this game (shown
        # in the UI only when more than one account exists in the database).
        distinct_accounts = conn.execute(
            "SELECT COUNT(DISTINCT display_name) FROM participants "
            "WHERE role = 'player' AND COALESCE(display_name, '') != ''"
        ).fetchone()[0]

        # Bo3 games 2+: the deck taken into THIS game compared with the deck
        # that STARTED the match. Diffing against the original (not just the
        # previous game) means game 3 still shows the changes made before
        # game 2 when nothing new was boarded in between.
        sideboard_changes = None
        deck_changes = None
        game_number = int(game.get("game_number") or 1)
        if game_number > 1 and game.get("match_id"):
            base_game = conn.execute(
                """
                SELECT id, COALESCE(game_number, 1) FROM games
                WHERE match_id = ? AND COALESCE(game_number, 1) < ?
                ORDER BY COALESCE(game_number, 1), started_at
                LIMIT 1
                """,
                (game["match_id"], game_number),
            ).fetchone()
            if base_game:

                def _player_maindeck(target_game_id: str) -> Dict[str, Dict[str, Any]]:
                    rows: Dict[str, Dict[str, Any]] = {}
                    for name, type_category, qty in conn.execute(
                        """
                        SELECT d.display_name, COALESCE(d.type_category, 'Other'), SUM(d.quantity)
                        FROM game_deck_cards d
                        JOIN participants p ON p.id = d.participant_id AND p.role = 'player'
                        WHERE d.game_id = ? AND d.deck_zone = 'deck'
                        GROUP BY d.display_name
                        """,
                        (target_game_id,),
                    ):
                        rows[str(name)] = {
                            "type_category": str(type_category or "Other"),
                            "quantity": int(qty or 0),
                        }
                    return rows

                base = _player_maindeck(str(base_game[0]))
                current = _player_maindeck(game_id)
                if base and current:
                    added = [
                        f"{current[name]['quantity'] - base.get(name, {}).get('quantity', 0)}x {name}"
                        for name in sorted(current)
                        if current[name]["quantity"] > base.get(name, {}).get("quantity", 0)
                    ]
                    removed = [
                        f"{base[name]['quantity'] - current.get(name, {}).get('quantity', 0)}x {name}"
                        for name in sorted(base)
                        if base[name]["quantity"] > current.get(name, {}).get("quantity", 0)
                    ]
                    if added or removed:
                        sideboard_changes = {"added": added, "removed": removed}
                        deck_changes = {
                            "base_game_number": int(base_game[1]),
                            "deck_total": sum(row["quantity"] for row in current.values()),
                            "base_deck_total": sum(row["quantity"] for row in base.values()),
                            "lands": sum(
                                row["quantity"]
                                for row in current.values()
                                if row["type_category"] == "Land"
                            ),
                            "base_lands": sum(
                                row["quantity"]
                                for row in base.values()
                                if row["type_category"] == "Land"
                            ),
                            "cards": [
                                {
                                    "display_name": name,
                                    "type_category": row["type_category"],
                                    "quantity": row["quantity"],
                                    "delta": row["quantity"]
                                    - base.get(name, {}).get("quantity", 0),
                                }
                                for name, row in sorted(current.items())
                            ],
                            "removed": [
                                {
                                    "display_name": name,
                                    "type_category": row["type_category"],
                                    "quantity": 0,
                                    "delta": -row["quantity"],
                                }
                                for name, row in sorted(base.items())
                                if name not in current
                            ],
                        }

        # Sibling games of the same Bo3 match, for the match roundup strip.
        match_games: List[Dict[str, Any]] = []
        if game.get("match_id"):
            match_games = _dict_rows(
                conn.execute(
                    """
                    SELECT
                      g.id AS game_id,
                      g.game_number,
                      g.outcome,
                      g.started_at,
                      g.duration_seconds,
                      g.total_turns
                    FROM games g
                    WHERE g.match_id = ?
                    ORDER BY COALESCE(g.game_number, 1), g.started_at
                    """,
                    (game["match_id"],),
                )
            )
        if len(match_games) < 2 and int(game.get("best_of") or 1) <= 1:
            match_games = []

    annotation = game_annotation(db_path, game_id)
    opponent_payload = dict(opponent or {})
    opponent_payload["colors"] = opponent_colors
    opponent_payload["color_label"] = color_combo_label(opponent_colors)
    return {
        "game": game,
        "match_games": match_games,
        "multi_account": int(distinct_accounts or 0) > 1,
        "sideboard_changes": sideboard_changes,
        "deck_changes": deck_changes,
        "player": player or {},
        "opponent": opponent_payload,
        "annotation": annotation,
        "participant_stats": participant_stats,
        "opening_hand": opening_hand,
        "mulligan_hands": mulligan_hands,
        "drawn": drawn,
        "draw_quality": draw_quality,
        "turn_timing": turn_timing_summary,
        "turns": turn_timings,
        "cards_played": cards_played,
        "opponent_cards": opponent_cards,
        "timeline": timeline,
        "life_curve": life_curve,
    }


def opponent_detail(
    db_path: Path = DEFAULT_DB_PATH,
    opponent_name: str = "",
    deck: Optional[str] = None,
    fmt: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Return head-to-head history for one exact Arena opponent name."""
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    requested_name = str(opponent_name or "").strip()
    if not requested_name:
        raise LookupError("Opponent name is required")
    where, filter_params = _games_filter(deck, fmt, days, since, until)
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
              ROUND(
                100.0 * SUM(g.outcome = 'win')
                / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0),
                1
              ) AS win_rate,
              MAX(o.display_name) AS display_name
            FROM games g
            JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
            WHERE o.display_name = ? COLLATE NOCASE AND {where}
            """,
            (requested_name, *filter_params),
        ).fetchone()
        if not summary or not summary[0]:
            raise LookupError(f"No recorded games against opponent: {requested_name}")
        game_rows = _dict_rows(
            conn.execute(
                f"""
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
                WHERE o.display_name = ? COLLATE NOCASE AND {where}
                ORDER BY g.started_at DESC, g.id DESC
                """,
                (requested_name, *filter_params),
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


def _card_multiplicity(
    conn: sqlite3.Connection, variants: List[str]
) -> Dict[str, Any]:
    """Repeat-draw analysis for one card across the player's games.

    For every game where the card was in the submitted maindeck (or, lacking a
    decklist, where it was seen), count how many copies the player saw
    (opening hand + visible draws) and compare against the hypergeometric
    expectation from the decklist copies and total cards seen that game.
    """
    name_clause = _card_name_clause("", variants)
    name_params = _card_name_params(variants)
    seen_rows = _dict_rows(
        conn.execute(
            f"""
            SELECT
              g.id AS game_id,
              g.outcome,
              p.id AS participant_id,
              COALESCE(oh.copies, 0) + COALESCE(dr.copies, 0) AS copies_seen,
              COALESCE(oh_total.total, 0) + COALESCE(dr_total.total, 0) AS cards_seen,
              dc.quantity AS copies_in_deck,
              dc_total.deck_size AS deck_size
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            LEFT JOIN (
              SELECT participant_id, COUNT(*) AS copies
              FROM game_opening_hand_cards
              WHERE {name_clause}
              GROUP BY participant_id
            ) oh ON oh.participant_id = p.id
            LEFT JOIN (
              SELECT participant_id, COUNT(*) AS copies
              FROM game_drawn_cards
              WHERE {name_clause}
              GROUP BY participant_id
            ) dr ON dr.participant_id = p.id
            LEFT JOIN (
              SELECT participant_id, COUNT(*) AS total
              FROM game_opening_hand_cards
              GROUP BY participant_id
            ) oh_total ON oh_total.participant_id = p.id
            LEFT JOIN (
              SELECT participant_id, COUNT(*) AS total
              FROM game_drawn_cards
              GROUP BY participant_id
            ) dr_total ON dr_total.participant_id = p.id
            LEFT JOIN (
              SELECT participant_id, SUM(quantity) AS quantity
              FROM game_deck_cards
              WHERE deck_zone = 'deck' AND {name_clause}
              GROUP BY participant_id
            ) dc ON dc.participant_id = p.id
            LEFT JOIN (
              SELECT participant_id, SUM(quantity) AS deck_size
              FROM game_deck_cards
              WHERE deck_zone = 'deck'
              GROUP BY participant_id
            ) dc_total ON dc_total.participant_id = p.id
            WHERE COALESCE(dc.quantity, 0) > 0
               OR COALESCE(oh.copies, 0) + COALESCE(dr.copies, 0) > 0
            """,
            name_params * 3,
        )
    )
    if not seen_rows:
        return {"games": 0, "buckets": []}

    buckets: Dict[int, Dict[str, Any]] = {}
    expected_at_least: Dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    expected_games = 0
    for row in seen_rows:
        copies_seen = int(row.get("copies_seen") or 0)
        bucket_key = min(copies_seen, 4)
        bucket = buckets.setdefault(
            bucket_key,
            {"copies_seen": bucket_key, "games": 0, "wins": 0, "losses": 0},
        )
        bucket["games"] += 1
        if row.get("outcome") == "win":
            bucket["wins"] += 1
        elif row.get("outcome") == "loss":
            bucket["losses"] += 1
        deck_size = int(row.get("deck_size") or 0)
        copies_in_deck = int(row.get("copies_in_deck") or 0)
        cards_seen = int(row.get("cards_seen") or 0)
        if deck_size and copies_in_deck and cards_seen:
            expected_games += 1
            for k in expected_at_least:
                expected_at_least[k] += hypergeom_tail_at_least(
                    k,
                    population_size=deck_size,
                    success_count=copies_in_deck,
                    draw_count=min(cards_seen, deck_size),
                )

    total_games = len(seen_rows)
    bucket_rows = []
    for key in sorted(buckets):
        bucket = buckets[key]
        decided = bucket["wins"] + bucket["losses"]
        games_at_least = sum(b["games"] for k, b in buckets.items() if k >= key)
        bucket_rows.append(
            {
                "copies_seen": key,
                "label": f"{key}+" if key == 4 else str(key),
                "games": bucket["games"],
                "pct_of_games": round(100.0 * bucket["games"] / total_games, 1),
                "pct_at_least": round(100.0 * games_at_least / total_games, 1),
                "expected_pct_at_least": (
                    round(100.0 * expected_at_least[key] / expected_games, 1)
                    if expected_games and key in expected_at_least and key > 0
                    else None
                ),
                "wins": bucket["wins"],
                "losses": bucket["losses"],
                "win_rate": round(100.0 * bucket["wins"] / decided, 1) if decided else None,
            }
        )
    return {"games": total_games, "buckets": bucket_rows}


def card_detail(
    db_path: Path = DEFAULT_DB_PATH,
    card_name: str = "",
    deck: Optional[str] = None,
    fmt: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Return drill-down analytics for one clean card name.

    Accepts the shared deck/format/days/since/until filters so card stats can
    match whatever slice the dashboard is showing.
    Raises LookupError when the card has no summary rows for either participant.
    """
    clean_name = _clean_card_name(card_name) or card_name
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    where, filter_params = _games_filter(deck, fmt, days, since, until)
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        variants = _split_name_variants(conn, clean_name)
        canonical_name = next((v for v in variants if " // " in v), clean_name)
        name_clause_s = _card_name_clause("s", variants)
        name_clause_h = _card_name_clause("h", variants)
        name_clause_d = _card_name_clause("d", variants)
        match_params = (*_card_name_params(variants), *filter_params)
        all_usage = conn.execute(
            f"""
            SELECT
              COUNT(DISTINCT g.id) AS games_seen,
              COALESCE(SUM(s.played_count), 0) AS total_played
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id
            JOIN games g ON g.id = s.game_id
            WHERE {name_clause_s} AND {where}
            """,
            match_params,
        ).fetchone()
        if not all_usage or not all_usage[0]:
            raise LookupError(f"No recorded card for name: {clean_name}")
        summary = conn.execute(
            f"""
            SELECT
              COUNT(DISTINCT g.id) AS games_seen,
              COALESCE(SUM(s.played_count), 0) AS total_played,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id AND p.role = 'player'
            JOIN games g ON g.id = s.game_id
            WHERE {name_clause_s}
              AND s.played_count > 0 AND {where}
            """,
            match_params,
        ).fetchone()
        by_role = _dict_rows(
            conn.execute(
                f"""
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
                WHERE {name_clause_s}
                  AND s.played_count > 0 AND {where}
                GROUP BY p.role
                ORDER BY CASE p.role WHEN 'player' THEN 0 ELSE 1 END
                """,
                match_params,
            )
        )
        by_deck = _dict_rows(
            conn.execute(
                f"""
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
                WHERE {name_clause_s}
                  AND s.played_count > 0 AND {where}
                GROUP BY p.deck_name
                ORDER BY games_seen DESC, win_rate DESC, deck_name
                LIMIT 50
                """,
                match_params,
            )
        )
        opener = conn.execute(
            f"""
            SELECT
              COUNT(DISTINCT g.id) AS games_in_opener,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM game_opening_hand_cards h
            JOIN participants p ON p.id = h.participant_id AND p.role = 'player'
            JOIN games g ON g.id = h.game_id
            WHERE {name_clause_h} AND {where}
            """,
            match_params,
        ).fetchone()
        drawn = conn.execute(
            f"""
            SELECT COUNT(*) AS times_drawn
            FROM game_drawn_cards d
            JOIN participants p ON p.id = d.participant_id AND p.role = 'player'
            JOIN games g ON g.id = d.game_id
            WHERE {name_clause_d} AND {where}
            """,
            match_params,
        ).fetchone()
        multiplicity = _card_multiplicity(conn, variants)

    opponent_usage = next((row for row in by_role if row["role"] == "opponent"), None)
    opponent_games = int(opponent_usage["games_seen"] or 0) if opponent_usage else 0
    opponent_wins = int(opponent_usage["wins"] or 0) if opponent_usage else 0
    opponent_losses = int(opponent_usage["losses"] or 0) if opponent_usage else 0
    opponent_decided = opponent_wins + opponent_losses

    return {
        "card_name": canonical_name,
        "image_url": _card_image_url(None, canonical_name),
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
        "multiplicity": multiplicity,
        "opener_impact": {
            "games_in_opener": int(opener[0] or 0) if opener else 0,
            "wins": int(opener[1] or 0) if opener else 0,
            "losses": int(opener[2] or 0) if opener else 0,
            "win_rate": opener[3] if opener else None,
            "times_drawn": int(drawn[0] or 0) if drawn else 0,
        },
    }


def all_games(
    db_path: Path = DEFAULT_DB_PATH,
    deck: Optional[str] = None,
    fmt: Optional[str] = None,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Every tracked game (newest first) with match records and draw-quality flags.

    Unlike the snapshot's 25-row recent list, flags here are computed in one
    set-based pass so the full history stays cheap (<50ms on ~800 games).
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    where, params = _games_filter(deck, fmt, days, since, until)
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        rows = _dict_rows(
            conn.execute(
                f"""
                SELECT
                  g.id AS game_id,
                  g.match_id,
                  g.game_number,
                  g.started_at,
                  g.outcome,
                  g.duration_seconds,
                  g.total_turns,
                  p.id AS player_participant_id,
                  p.deck_size,
                  m.format AS raw_format,
                  m.best_of,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  p.mulligans,
                  (
                    SELECT SUM(g2.outcome = 'win') FROM games g2
                    WHERE g2.match_id = g.match_id
                  ) AS match_wins,
                  (
                    SELECT SUM(g2.outcome = 'loss') FROM games g2
                    WHERE g2.match_id = g.match_id
                  ) AS match_losses,
                  (
                    SELECT GROUP_CONCAT(COALESCE(c.color_identity, ''), '')
                    FROM game_card_summary s
                    JOIN participants po ON po.id = s.participant_id AND po.role = 'opponent'
                    JOIN cards c ON c.id = s.card_id
                    WHERE s.game_id = g.id AND po.game_id = g.id
                  ) AS opp_color_letters
                FROM games g
                JOIN matches m ON m.id = g.match_id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE {where}
                ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
                """,
                params,
            )
        )
        participant_ids = [row["player_participant_id"] for row in rows]
        opener_by_participant: Dict[str, List[Dict[str, Any]]] = {}
        drawn_by_participant: Dict[str, List[Dict[str, Any]]] = {}
        stats_drawn: Dict[str, int] = {}
        deck_stats: Dict[str, Tuple[int, int]] = {}
        if participant_ids:
            placeholders = ",".join("?" for _ in participant_ids)
            for record in _dict_rows(
                conn.execute(
                    f"""
                    SELECT participant_id, display_name,
                           COALESCE(type_category, 'Other') AS type_category
                    FROM game_opening_hand_cards
                    WHERE participant_id IN ({placeholders})
                    ORDER BY hand_position
                    """,
                    participant_ids,
                )
            ):
                opener_by_participant.setdefault(record["participant_id"], []).append(record)
            for record in _dict_rows(
                conn.execute(
                    f"""
                    SELECT participant_id, display_name,
                           COALESCE(type_category, 'Other') AS type_category, draw_position
                    FROM game_drawn_cards
                    WHERE participant_id IN ({placeholders})
                    ORDER BY draw_position
                    """,
                    participant_ids,
                )
            ):
                drawn_by_participant.setdefault(record["participant_id"], []).append(record)
            for record in conn.execute(
                f"""
                SELECT participant_id, cards_drawn FROM game_participant_stats
                WHERE participant_id IN ({placeholders})
                """,
                participant_ids,
            ):
                stats_drawn[record[0]] = int(record[1] or 0)
            for record in conn.execute(
                f"""
                SELECT participant_id, SUM(quantity),
                       SUM(CASE WHEN type_category = 'Land' THEN quantity ELSE 0 END)
                FROM game_deck_cards
                WHERE deck_zone = 'deck' AND participant_id IN ({placeholders})
                GROUP BY participant_id
                """,
                participant_ids,
            ):
                deck_stats[record[0]] = (int(record[1] or 0), int(record[2] or 0))

    for row in rows:
        participant_id = row.pop("player_participant_id", None)
        fallback_size = int(row.pop("deck_size", None) or 60)
        decklist = deck_stats.get(participant_id)
        deck_size = decklist[0] if decklist and decklist[0] else fallback_size
        deck_lands = decklist[1] if decklist and decklist[0] else None
        quality = draw_quality_metrics(
            opener_by_participant.get(participant_id, []),
            drawn_by_participant.get(participant_id, []),
            stats_drawn.get(participant_id, 0),
            deck_size,
            deck_lands=deck_lands,
        )
        row["is_flood"] = quality["is_flood"]
        row["is_screw"] = quality["is_screw"]
        row["cards_seen"] = quality["total_cards_seen"]
        row["lands_seen"] = quality["lands_seen"]
        row["land_seen_pct"] = quality["land_seen_pct"]
        row["format_label"] = format_label(
            row.get("raw_format"), default_best_of=int(row.get("best_of") or 1)
        )
        row["opp_colors"] = normalize_colors(str(row.pop("opp_color_letters", "") or ""))
    return {"games": rows, "total": len(rows)}


def game_annotation(db_path: Path = DEFAULT_DB_PATH, game_id: str = "") -> Dict[str, Any]:
    """Return the user's note/tags for one game (empty defaults when unset)."""
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        row = conn.execute(
            "SELECT note, tags, updated_at FROM game_annotations WHERE game_id = ?",
            (game_id,),
        ).fetchone()
    if row is None:
        return {"game_id": game_id, "note": "", "tags": [], "updated_at": None}
    tags = [tag for tag in str(row[1] or "").split(",") if tag]
    return {"game_id": game_id, "note": row[0] or "", "tags": tags, "updated_at": row[2]}


MAX_ANNOTATION_NOTE_LENGTH = 4000
MAX_ANNOTATION_TAGS = 12
MAX_ANNOTATION_TAG_LENGTH = 40


def save_game_annotation(
    db_path: Path = DEFAULT_DB_PATH,
    game_id: str = "",
    note: str = "",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Persist a note/tags for one game. The dashboard's only write path.

    The game must exist. Empty note + no tags deletes the row.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Dashboard database not found: {db_path}")
    clean_note = str(note or "").strip()[:MAX_ANNOTATION_NOTE_LENGTH]
    clean_tags: List[str] = []
    for tag in tags or []:
        cleaned = str(tag or "").strip()[:MAX_ANNOTATION_TAG_LENGTH]
        if cleaned and "," not in cleaned and cleaned.casefold() not in {
            existing.casefold() for existing in clean_tags
        }:
            clean_tags.append(cleaned)
        if len(clean_tags) >= MAX_ANNOTATION_TAGS:
            break
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                conn.execute("PRAGMA busy_timeout = 5000")
                exists = conn.execute(
                    "SELECT 1 FROM games WHERE id = ?", (game_id,)
                ).fetchone()
                if not exists:
                    raise LookupError(f"No recorded game for id: {game_id}")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS game_annotations (
                        game_id TEXT PRIMARY KEY,
                        note TEXT,
                        tags TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                if not clean_note and not clean_tags:
                    conn.execute(
                        "DELETE FROM game_annotations WHERE game_id = ?", (game_id,)
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO game_annotations (game_id, note, tags, updated_at)
                        VALUES (?, ?, ?, datetime('now'))
                        ON CONFLICT(game_id) DO UPDATE SET
                            note = excluded.note,
                            tags = excluded.tags,
                            updated_at = excluded.updated_at
                        """,
                        (game_id, clean_note, ",".join(clean_tags)),
                    )
                conn.commit()
            return {"game_id": game_id, "note": clean_note, "tags": clean_tags}
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    raise sqlite3.OperationalError(
        "the database write lock is held by another process (usually the "
        "tracker) — make sure the tracker is on the latest build and restart it"
    ) from last_error


def audit_report(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Database consistency findings from db_audit, JSON-friendly."""
    from .db_audit import audit_database

    findings = audit_database(Path(db_path).expanduser(), readonly=True)
    rows = [
        {
            "code": finding.code,
            "severity": finding.severity,
            "table_name": finding.table_name,
            "row_id": finding.row_id,
            "message": finding.message,
            "current_value": finding.current_value,
            "suggested_value": finding.suggested_value,
            "repairable": finding.repairable,
        }
        for finding in findings
    ]
    by_code: Dict[str, int] = {}
    for row in rows:
        by_code[row["code"]] = by_code.get(row["code"], 0) + 1
    return {
        "findings": rows,
        "total": len(rows),
        "by_code": [
            {"code": code, "count": count}
            for code, count in sorted(by_code.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def global_search(
    db_path: Path = DEFAULT_DB_PATH, query: str = "", limit: int = 8
) -> Dict[str, Any]:
    """Search tracked cards, your decks, and opponent names in one call."""
    cards = search_cards(db_path, query, limit)
    clean_query = str(query or "").strip()
    decks: List[Dict[str, Any]] = []
    opponents: List[Dict[str, Any]] = []
    if clean_query:
        like = f"%{clean_query}%"
        db_path = Path(db_path).expanduser()
        db_uri = db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(db_uri, uri=True) as conn:
            conn.execute("PRAGMA query_only = ON")
            decks = _dict_rows(
                conn.execute(
                    """
                    SELECT
                      COALESCE(p.deck_name, '(unknown)') AS deck_name,
                      COUNT(*) AS games
                    FROM participants p
                    JOIN games g ON g.id = p.game_id
                    WHERE p.role = 'player'
                      AND p.deck_name IS NOT NULL
                      AND p.deck_name LIKE ?
                    GROUP BY p.deck_name
                    ORDER BY games DESC, deck_name COLLATE NOCASE
                    LIMIT ?
                    """,
                    (like, max(1, min(int(limit), 25))),
                )
            )
            opponents = _dict_rows(
                conn.execute(
                    """
                    SELECT
                      o.display_name,
                      COUNT(*) AS games
                    FROM participants o
                    JOIN games g ON g.id = o.game_id
                    WHERE o.role = 'opponent'
                      AND o.display_name IS NOT NULL
                      AND o.display_name != 'Opponent'
                      AND o.display_name LIKE ?
                    GROUP BY o.display_name
                    ORDER BY games DESC, o.display_name COLLATE NOCASE
                    LIMIT ?
                    """,
                    (like, max(1, min(int(limit), 25))),
                )
            )
    return {"cards": cards, "decks": decks, "opponents": opponents}


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
                else ("Mana Screw" if row.get("is_screw") else "Normal")
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


def _parse_common_filters(query: Dict[str, List[str]]) -> Dict[str, Any]:
    """Parse deck/format/days/since/until filter params shared across endpoints."""
    def first(key: str) -> Optional[str]:
        return query.get(key, [None])[0] or None

    days_raw = first("days")
    try:
        days: Optional[int] = int(days_raw) if days_raw else None
    except ValueError:
        days = None
    if days is not None and days <= 0:
        days = None

    def date_param(key: str) -> Optional[str]:
        value = (first(key) or "").strip()
        if not value:
            return None
        try:
            datetime.fromisoformat(value)
        except ValueError:
            return None
        return value

    return {
        "deck": first("deck"),
        "fmt": first("format"),
        "days": days,
        "since": date_param("since"),
        "until": date_param("until"),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler rendering the dashboard on each request."""

    db_path: Path = DEFAULT_DB_PATH
    static_dir: Path | None = DEFAULT_STATIC_DIR if DEFAULT_STATIC_DIR.exists() else None

    def log_message(self, message_format: str, *args: Any) -> None:
        """Avoid writing request logs when a windowed build has no stderr stream."""
        if sys.stderr is not None:
            super().log_message(message_format, *args)

    def do_POST(self):  # noqa: N802 - http.server API
        """Handle the dashboard's writes: game notes/tags and the DB reset."""
        parsed = urlparse(self.path)
        if parsed.path == "/api/deck-downloader/launch":
            # The dashboard server runs on the player's machine, so it can
            # open the Deck Downloader terminal app on their behalf.
            from .deck_downloader_launcher import launch_deck_downloader

            ok, message = launch_deck_downloader()
            _send_bytes(
                self,
                200 if ok else 409,
                json.dumps({"ok": ok, "message": message}).encode("utf-8"),
                "application/json; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return
        if parsed.path == "/api/db/reset":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else None
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            confirm = payload.get("confirm") if isinstance(payload, dict) else None
            if confirm != "RESET":
                _send_bytes(
                    self,
                    400,
                    b'Body must be JSON {"confirm": "RESET"}',
                    "text/plain; charset=utf-8",
                    {"Cache-Control": "no-store"},
                )
                return
            try:
                result = reset_database(self.db_path)
            except FileNotFoundError as exc:
                _send_bytes(
                    self, 404, str(exc).encode("utf-8"),
                    "text/plain; charset=utf-8", {"Cache-Control": "no-store"},
                )
                return
            except Exception as exc:
                traceback.print_exc()
                _send_bytes(
                    self, 500, f"{type(exc).__name__}: {exc}".encode("utf-8"),
                    "text/plain; charset=utf-8", {"Cache-Control": "no-store"},
                )
                return
            print(f"⚠️  Database reset by dashboard request — backup: {result['backup']}")
            _send_bytes(
                self,
                200,
                render_snapshot_json(result),
                "application/json; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return
        if parsed.path != "/api/game/annotation":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            _send_bytes(
                self,
                400,
                b"Missing or oversized request body",
                "text/plain; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        game_id = str(payload.get("game_id") or "") if isinstance(payload, dict) else ""
        if not payload or not game_id:
            _send_bytes(
                self,
                400,
                b"Body must be JSON with a game_id",
                "text/plain; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return
        tags = payload.get("tags")
        try:
            result = save_game_annotation(
                self.db_path,
                game_id,
                note=str(payload.get("note") or ""),
                tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
            )
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
            # Surface the failure in the server console too — the UI shows
            # the same message, but the traceback only lives here.
            traceback.print_exc()
            _send_bytes(
                self,
                500,
                f"{type(exc).__name__}: {exc}".encode("utf-8"),
                "text/plain; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return
        _send_bytes(
            self,
            200,
            render_snapshot_json(result),
            "application/json; charset=utf-8",
            {"Cache-Control": "no-store"},
        )
        return

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        request_path = parsed.path
        if request_path == "/api/version":
            from . import __version__ as tracker_version

            _send_bytes(
                self,
                200,
                render_snapshot_json({"version": tracker_version}),
                "application/json; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return
        if request_path == "/api/snapshot":
            query = parse_qs(parsed.query)
            common = _parse_common_filters(query)
            season_raw = query.get("season", [None])[0]
            try:
                season = int(season_raw) if season_raw else None
            except ValueError:
                season = None
            try:
                body = render_snapshot_json(
                    dashboard_snapshot(
                        self.db_path,
                        deck=common["deck"],
                        fmt=common["fmt"],
                        days=common["days"],
                        season=season,
                        since=common["since"],
                        until=common["until"],
                    )
                )
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
            common = _parse_common_filters(query)
            fmt = common["fmt"]
            days = common["days"]
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
                body = render_snapshot_json(
                    deck_detail(
                        self.db_path,
                        deck_name,
                        fmt=fmt,
                        days=days,
                        since=common["since"],
                        until=common["until"],
                    )
                )
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
            common = _parse_common_filters(query)
            try:
                body = render_snapshot_json(
                    opponent_detail(
                        self.db_path,
                        name,
                        deck=common["deck"],
                        fmt=common["fmt"],
                        days=common["days"],
                        since=common["since"],
                        until=common["until"],
                    )
                )
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
            common = _parse_common_filters(query)
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
                body = render_snapshot_json(
                    card_detail(
                        self.db_path,
                        name,
                        deck=common["deck"],
                        fmt=common["fmt"],
                        days=common["days"],
                        since=common["since"],
                        until=common["until"],
                    )
                )
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
        if request_path == "/api/games":
            query = parse_qs(parsed.query)
            common = _parse_common_filters(query)
            try:
                body = render_snapshot_json(
                    all_games(
                        self.db_path,
                        deck=common["deck"],
                        fmt=common["fmt"],
                        days=common["days"],
                        since=common["since"],
                        until=common["until"],
                    )
                )
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
        if request_path == "/api/audit":
            try:
                body = render_snapshot_json(audit_report(self.db_path))
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
        if request_path == "/api/search":
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
                body = render_snapshot_json(global_search(self.db_path, search_query, limit))
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
