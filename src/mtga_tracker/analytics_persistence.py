"""Focused analytics persistence helpers."""

import re
import sqlite3
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .state import CardEvent


def analytics_card_base_name(display_name: str) -> str:
    """Strip display-only type/P-T suffixes from summary card names."""
    return re.sub(r"\s+\([^()]*\)$", "", str(display_name or "")).strip()


def analytics_card_power_toughness(display_name: str) -> tuple:
    """Best-effort parse of creature power/toughness from display names."""
    match = re.search(r"\((?:[^()]*)\s+(-?\d+|\*)/(-?\d+|\*)\)$", str(display_name or ""))
    if not match:
        return None, None
    return match.group(1), match.group(2)


def upsert_card(
    conn: sqlite3.Connection,
    display_name: str,
    type_category: Optional[str] = None,
) -> Optional[int]:
    """Upsert a card dimension row and return its id."""
    base_name = analytics_card_base_name(display_name)
    if not base_name:
        return None
    power, toughness = analytics_card_power_toughness(display_name)
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO cards (name, primary_type, power, toughness, first_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            primary_type = COALESCE(excluded.primary_type, cards.primary_type),
            power = COALESCE(excluded.power, cards.power),
            toughness = COALESCE(excluded.toughness, cards.toughness)
        """,
        (base_name, type_category, power, toughness, now),
    )
    row = conn.execute("SELECT id FROM cards WHERE name = ?", (base_name,)).fetchone()
    return int(row[0]) if row else None


def persist_card_summary(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: str,
    events: List[CardEvent],
    *,
    refresh_display_name: Callable[[str], str],
) -> None:
    """Persist played-card counts by participant."""
    counts: Dict[str, Dict[str, object]] = {}
    for event in events:
        display_name = refresh_display_name(event.card_name)
        if display_name not in counts:
            counts[display_name] = {
                "played_count": 0,
                "type_category": event.card_type_category,
            }
        counts[display_name]["played_count"] = int(counts[display_name]["played_count"]) + 1
        if event.card_type_category and event.card_type_category != "Other":
            counts[display_name]["type_category"] = event.card_type_category

    for display_name, data in counts.items():
        type_category = data.get("type_category")
        card_id = upsert_card(conn, display_name, type_category if isinstance(type_category, str) else None)
        conn.execute(
            """
            INSERT INTO game_card_summary (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                played_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, participant_id, display_name) DO UPDATE SET
                card_id = excluded.card_id,
                type_category = excluded.type_category,
                played_count = excluded.played_count
            """,
            (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                int(data["played_count"]),
            ),
        )


def persist_opening_hand(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: str,
    *,
    starting_hand_events: List[CardEvent],
    starting_hand: List[str],
    refresh_display_name: Callable[[str], str],
) -> None:
    """Persist the player's kept opening hand as one row per card slot."""
    conn.execute(
        "DELETE FROM game_opening_hand_cards WHERE game_id = ? AND participant_id = ?",
        (game_id, participant_id),
    )
    source_events = starting_hand_events
    if not source_events and starting_hand:
        source_events = [CardEvent(card, "player", card_type_category=None) for card in starting_hand]

    copy_counts: Dict[str, int] = {}
    for index, event in enumerate(source_events, start=1):
        display_name = refresh_display_name(event.card_name)
        if not display_name:
            continue
        copy_counts[display_name] = copy_counts.get(display_name, 0) + 1
        type_category = event.card_type_category
        card_id = upsert_card(conn, display_name, type_category)
        conn.execute(
            """
            INSERT INTO game_opening_hand_cards (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                hand_position,
                copy_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                index,
                copy_counts[display_name],
            ),
        )


def persist_commanders(
    conn: sqlite3.Connection,
    participant_id: str,
    names: List[str],
    *,
    refresh_display_name: Callable[[str], str],
) -> None:
    """Persist commander/card-role data when available."""
    for name in names:
        display_name = refresh_display_name(name)
        card_id = upsert_card(conn, display_name)
        conn.execute(
            """
            INSERT INTO participant_commanders (participant_id, card_id, card_name)
            VALUES (?, ?, ?)
            ON CONFLICT(participant_id, card_name) DO UPDATE SET
                card_id = excluded.card_id
            """,
            (participant_id, card_id, display_name),
        )
