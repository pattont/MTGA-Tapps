"""Cards made public without being played: mills, discards, and exiles from a
hidden zone (library or hand).

The live tracker records them per seat and persists the opponent's into
``game_card_summary.milled_count`` / ``discarded_count`` / ``exiled_count``,
which feed the game page's Opponent Revealed Cards table and the opponent's
revealed colors. ``backfill_revealed_card_counts`` fills the same columns for
games recorded before they were written (migration 36).

Exiles count only from the library or hand: a card exiled from the
battlefield, graveyard, or stack was already public (played, milled, or
discarded), so it reveals nothing new. Tokens, face-down cards, and cards the
local player cannot see never count.

Only the opponent side is persisted: the player's own rows feed deck-page
"games seen" and the deck thumbnail, where a card milled from your library
was never in play.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, Optional, Tuple

#: CardEvent.source value -> game_card_summary column.
REVEAL_COLUMNS = {
    "discard": "discarded_count",
    "mill": "milled_count",
    "exile": "exiled_count",
}

#: Zones a card must leave for its exile to reveal it.
HIDDEN_ZONES = ("library", "hand")

_NON_CARD_OBJECT_MARKERS = ("Token", "Ability", "Emblem")

# Console text of mills and discards, for games recorded before replay rows.
_MILLED_RE = re.compile(r"\bmilled \[([^\]]+)\]")
_DISCARDED_RE = re.compile(r"\[([^\]]+)\] was discarded\b")


def is_public_card_object(card_obj: Any, *, opponent: bool) -> bool:
    """True for a real card whose face the local player can see."""
    if not isinstance(card_obj, dict) or not card_obj.get("grpId"):
        return False
    object_type = str(card_obj.get("type") or "")
    if any(marker in object_type for marker in _NON_CARD_OBJECT_MARKERS):
        return False
    if card_obj.get("isFacedown"):
        return False
    if opponent and card_obj.get("visibility") == "Visibility_Private":
        return False
    return True


def is_known_card_name(name: Any) -> bool:
    """False for placeholders: unresolved ``Card #N`` ids and ``Unknown``."""
    text = str(name or "").strip()
    return bool(text) and text != "Unknown" and not text.startswith("Card #")


def _recorded_reveals(conn: sqlite3.Connection, participants: Dict[str, str]):
    """(game_id, participant_id, kind, name, type) from structured replay rows."""
    for game_id, participant_id, zone_from, payload_json in conn.execute(
        """
        SELECT e.game_id, e.participant_id, e.zone_from, e.payload_json
        FROM game_events e
        JOIN games g ON g.id = e.game_id
        WHERE g.replay_version IS NOT NULL
          AND e.visible = 1
          AND e.event_subtype = 'move'
          AND e.arena_id IS NOT NULL
          AND e.participant_id IS NOT NULL
        """
    ):
        if str(participant_id) not in participants:
            continue
        try:
            payload = json.loads(payload_json or "{}")
        except (TypeError, ValueError):
            continue
        kind = payload.get("reason")
        if kind not in REVEAL_COLUMNS or payload.get("token"):
            continue
        if kind == "exile" and zone_from not in HIDDEN_ZONES:
            continue
        name = payload.get("name")
        if not is_known_card_name(name):
            continue
        yield str(game_id), str(participant_id), kind, str(name), payload.get("type")


def _legacy_reveals(conn: sqlite3.Connection, participants: Dict[str, str]):
    """Mills and discards from console text of games without replay rows.

    Exiles are skipped: the text names neither the source zone nor whether
    the exiled object was a token.
    """
    for game_id, participant_id, text in conn.execute(
        """
        SELECT e.game_id, e.participant_id, e.text
        FROM game_events e
        JOIN games g ON g.id = e.game_id
        WHERE g.replay_version IS NULL
          AND e.visible = 1
          AND e.participant_id IS NOT NULL
          AND (e.text LIKE '%milled [%' OR e.text LIKE '%] was discarded%')
        """
    ):
        if str(participant_id) not in participants:
            continue
        text = str(text or "")
        for kind, pattern in (("mill", _MILLED_RE), ("discard", _DISCARDED_RE)):
            match = pattern.search(text)
            if match and is_known_card_name(match.group(1)):
                yield str(game_id), str(participant_id), kind, match.group(1).strip(), None
                break


def backfill_revealed_card_counts(conn: sqlite3.Connection) -> None:
    """Fill opponent milled/discarded/exiled counts for already-recorded games.

    Skips any opponent that already has a nonzero count (written live), so it
    never double counts. A revealed card merges into the game's existing row
    for that card (a card both played and milled stays one row); otherwise it
    gets a new row with played_count = 0.
    """
    from .analytics_persistence import (
        analytics_card_base_name,
        canonical_split_display,
        split_card_half_map,
    )

    participants = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            """
            SELECT p.id, p.game_id
            FROM participants p
            WHERE p.role = 'opponent'
              AND NOT EXISTS (
                SELECT 1 FROM game_card_summary s
                WHERE s.participant_id = p.id
                  AND (s.discarded_count > 0 OR s.milled_count > 0 OR s.exiled_count > 0)
              )
            """
        )
    }
    if not participants:
        return

    half_map = split_card_half_map(conn)
    totals: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for source in (_recorded_reveals, _legacy_reveals):
        for game_id, participant_id, kind, name, type_category in source(conn, participants):
            display = canonical_split_display(name, half_map)
            entry = totals.setdefault(
                (game_id, participant_id, display), {"type": None, **{k: 0 for k in REVEAL_COLUMNS}}
            )
            entry[kind] += 1
            if type_category and not entry["type"]:
                entry["type"] = str(type_category)

    for (game_id, participant_id, display), entry in totals.items():
        base = analytics_card_base_name(display)
        escaped = base.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        existing = conn.execute(
            """
            SELECT id FROM game_card_summary
            WHERE game_id = ? AND participant_id = ?
              AND (display_name = ? OR display_name LIKE ? ESCAPE '!')
            ORDER BY played_count DESC, id
            LIMIT 1
            """,
            (game_id, participant_id, base, f"{escaped} (%"),
        ).fetchone()
        counts = (entry["discard"], entry["mill"], entry["exile"])
        if existing is not None:
            conn.execute(
                """
                UPDATE game_card_summary
                SET discarded_count = ?, milled_count = ?, exiled_count = ?
                WHERE id = ?
                """,
                (*counts, existing[0]),
            )
            continue
        card = conn.execute("SELECT id, primary_type FROM cards WHERE name = ?", (base,)).fetchone()
        card_id: Optional[int] = card[0] if card else None
        type_category = entry["type"] or (card[1] if card and card[1] else None) or "Other"
        conn.execute(
            """
            INSERT INTO game_card_summary (
                game_id, participant_id, card_id, display_name, type_category,
                played_count, drawn_count, discarded_count, milled_count, exiled_count
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
            """,
            (game_id, participant_id, card_id, display, type_category, *counts),
        )
