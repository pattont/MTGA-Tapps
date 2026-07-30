"""Focused analytics persistence helpers."""

import re
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

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


SPLIT_NAME_SEPARATOR = " // "


def split_card_half_map(conn: sqlite3.Connection) -> Dict[str, str]:
    """Map each half of a known split/room/adventure card to its full name.

    Arena resolves each door/half of these cards as its own game object, so
    play events can arrive as "Ritual Chamber" while draws and decklists use
    "Unholy Annex // Ritual Chamber". The cards table accumulates the full
    names from decklists and visible draws.
    """
    mapping: Dict[str, str] = {}
    for (name,) in conn.execute(
        "SELECT name FROM cards WHERE name LIKE '% // %'"
    ):
        full = analytics_card_base_name(name)
        if SPLIT_NAME_SEPARATOR not in full:
            continue
        for half in full.split(SPLIT_NAME_SEPARATOR):
            half = half.strip()
            if half and half not in mapping:
                mapping[half] = full
    return mapping


def canonical_split_display(display_name: str, half_map: Dict[str, str]) -> str:
    """Rewrite a split-card half display name to the full-card name."""
    base = analytics_card_base_name(display_name)
    full = half_map.get(base)
    if not full or base == full:
        return display_name
    suffix = display_name[len(base):] if display_name.startswith(base) else ""
    return f"{full}{suffix}"


def upsert_card(
    conn: sqlite3.Connection,
    display_name: str,
    type_category: Optional[str] = None,
    arena_id: Optional[int] = None,
) -> Optional[int]:
    """Upsert a card dimension row and return its id."""
    base_name = analytics_card_base_name(display_name)
    if not base_name:
        return None
    power, toughness = analytics_card_power_toughness(display_name)
    now = datetime.now().isoformat()
    try:
        conn.execute(
            """
            INSERT INTO cards (name, primary_type, power, toughness, first_seen_at, arena_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                primary_type = COALESCE(excluded.primary_type, cards.primary_type),
                power = COALESCE(excluded.power, cards.power),
                toughness = COALESCE(excluded.toughness, cards.toughness),
                arena_id = COALESCE(cards.arena_id, excluded.arena_id)
            """,
            (base_name, type_category, power, toughness, now, arena_id),
        )
    except sqlite3.IntegrityError:
        # A different card name already owns this arena_id (UNIQUE constraint),
        # e.g. split-card name variants. Keep the existing mapping.
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
    drawn_events: Optional[List[CardEvent]] = None,
) -> None:
    """Persist played- and drawn-card counts by participant.

    Played events keep their full display names (one row per display variant,
    matching historical rows). Drawn events are matched to a played row by base
    card name when possible so a card played and drawn stays one row; cards
    drawn but never played get their own row with played_count = 0.
    """
    counts: Dict[str, Dict[str, object]] = {}
    base_to_display: Dict[str, str] = {}
    half_map = split_card_half_map(conn)
    # Names in this batch may introduce split cards not yet in the cards table.
    for event in list(events) + list(drawn_events or []):
        batch_base = analytics_card_base_name(str(event.card_name or ""))
        if SPLIT_NAME_SEPARATOR in batch_base:
            for half in batch_base.split(SPLIT_NAME_SEPARATOR):
                half = half.strip()
                if half and half not in half_map:
                    half_map[half] = batch_base
    for event in events:
        display_name = canonical_split_display(refresh_display_name(event.card_name), half_map)
        if display_name not in counts:
            counts[display_name] = {
                "played_count": 0,
                "drawn_count": 0,
                "type_category": event.card_type_category,
            }
        counts[display_name]["played_count"] = int(counts[display_name]["played_count"]) + 1
        if event.card_type_category and event.card_type_category != "Other":
            counts[display_name]["type_category"] = event.card_type_category
        base_name = analytics_card_base_name(display_name)
        if base_name and base_name not in base_to_display:
            base_to_display[base_name] = display_name

    for event in drawn_events or []:
        display_name = canonical_split_display(refresh_display_name(event.card_name), half_map)
        base_name = analytics_card_base_name(display_name)
        target_name = base_to_display.get(base_name, display_name)
        if target_name not in counts:
            counts[target_name] = {
                "played_count": 0,
                "drawn_count": 0,
                "type_category": event.card_type_category,
            }
        counts[target_name]["drawn_count"] = int(counts[target_name]["drawn_count"]) + 1
        if event.card_type_category and event.card_type_category != "Other":
            existing = counts[target_name].get("type_category")
            if not existing or existing == "Other":
                counts[target_name]["type_category"] = event.card_type_category

    for display_name, data in counts.items():
        type_category = data.get("type_category")
        card_id = upsert_card(
            conn, display_name, type_category if isinstance(type_category, str) else None
        )
        conn.execute(
            """
            INSERT INTO game_card_summary (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                played_count,
                drawn_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, participant_id, display_name) DO UPDATE SET
                card_id = excluded.card_id,
                type_category = excluded.type_category,
                played_count = excluded.played_count,
                drawn_count = excluded.drawn_count
            """,
            (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                int(data["played_count"]),
                int(data["drawn_count"]),
            ),
        )


def persist_submitted_deck(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: str,
    *,
    deck_cards: Sequence[int],
    sideboard_cards: Sequence[int],
    resolve_name: Callable[[int], str],
    resolve_type_category: Callable[[int], Optional[str]],
) -> None:
    """Persist Arena's authoritative submitted main deck and sideboard."""
    conn.execute(
        "DELETE FROM game_deck_cards WHERE game_id = ? AND participant_id = ?",
        (game_id, participant_id),
    )
    for deck_zone, arena_ids in (("deck", deck_cards), ("sideboard", sideboard_cards)):
        for arena_id, quantity in Counter(int(value) for value in arena_ids).items():
            display_name = analytics_card_base_name(resolve_name(arena_id))
            if not display_name:
                continue
            type_category = resolve_type_category(arena_id) or "Other"
            card_id = upsert_card(conn, display_name, type_category, arena_id=arena_id)
            conn.execute(
                """
                INSERT INTO game_deck_cards (
                    game_id,
                    participant_id,
                    card_id,
                    arena_id,
                    display_name,
                    type_category,
                    deck_zone,
                    quantity
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    participant_id,
                    card_id,
                    arena_id,
                    display_name,
                    type_category,
                    deck_zone,
                    quantity,
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
        source_events = [
            CardEvent(card, "player", card_type_category=None) for card in starting_hand
        ]

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


def persist_mulligan_hands(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: str,
    hands: List[Dict[str, Any]],
    *,
    refresh_display_name: Callable[[str], str],
) -> None:
    """Persist each full pre-mulligan hand, flagging London-bottomed cards."""
    conn.execute(
        "DELETE FROM game_mulligan_hands WHERE game_id = ? AND participant_id = ?",
        (game_id, participant_id),
    )
    for hand_number, hand in enumerate(hands, start=1):
        events = hand.get("events") or []
        bottomed_positions = {int(index) for index in (hand.get("bottomed") or [])}
        for index, event in enumerate(events):
            display_name = refresh_display_name(event.card_name)
            if not display_name:
                continue
            type_category = event.card_type_category
            card_id = upsert_card(conn, display_name, type_category)
            conn.execute(
                """
                INSERT INTO game_mulligan_hands (
                    game_id,
                    participant_id,
                    hand_number,
                    hand_position,
                    card_id,
                    display_name,
                    type_category,
                    bottomed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    participant_id,
                    hand_number,
                    index + 1,
                    card_id,
                    display_name,
                    type_category,
                    1 if index in bottomed_positions else 0,
                ),
            )


def persist_drawn_cards(
    conn: sqlite3.Connection,
    game_id: str,
    participant_id: str,
    events: List[CardEvent],
    *,
    refresh_display_name: Callable[[str], str],
) -> None:
    """Persist visible drawn-card identities as one row per draw slot."""
    conn.execute(
        "DELETE FROM game_drawn_cards WHERE game_id = ? AND participant_id = ?",
        (game_id, participant_id),
    )
    copy_counts: Dict[str, int] = {}
    for index, event in enumerate(events, start=1):
        display_name = refresh_display_name(event.card_name)
        if not display_name:
            continue
        copy_counts[display_name] = copy_counts.get(display_name, 0) + 1
        type_category = event.card_type_category
        card_id = upsert_card(conn, display_name, type_category)
        conn.execute(
            """
            INSERT INTO game_drawn_cards (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                draw_position,
                turn_number,
                copy_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                index,
                getattr(event, "turn_number", None),
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
