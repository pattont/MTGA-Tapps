"""Focused analytics persistence helpers."""

import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from .revealed_cards import REVEAL_COLUMNS
from .state import CardEvent


def persist_managed_deck(
    conn,
    deck,
    *,
    deck_id=None,
    account_key=None,
    arena_deck_id=None,
    observed_at=None,
    create=False,
    collection_id=None,
    assign_collection=False,
):
    """Commit a verified immutable snapshot before any later Arena operation."""
    from .deck_manager import content_hash, deck_detail, encoded, now

    stamp = observed_at or now()
    if deck_id is None and account_key and arena_deck_id:
        binding = conn.execute(
            "SELECT deck_id FROM managed_deck_bindings WHERE account_key = ? AND arena_deck_id = ?",
            (account_key, arena_deck_id),
        ).fetchone()
        if binding:
            deck_id = binding[0]
        else:
            # Adopt the entry the log capture already made for this Arena deck,
            # unless it was put in Trash, so one Arena deck keeps one saved entry.
            from .deck_capture import captured_deck_id

            captured = captured_deck_id(arena_deck_id)
            if conn.execute(
                "SELECT 1 FROM managed_decks WHERE id = ? AND trashed_at IS NULL", (captured,)
            ).fetchone():
                deck_id = captured
    existing = (
        conn.execute(
            "SELECT current_revision_id, updated_at FROM managed_decks WHERE id = ?", (deck_id,)
        ).fetchone()
        if deck_id
        else None
    )
    if deck_id and existing is None and not create:
        raise KeyError("Saved deck not found.")
    deck_id = deck_id or str(uuid.uuid4())
    digest = content_hash(deck)
    revision_id = str(uuid.uuid4())
    with conn:
        conn.execute("UPDATE managed_decks SET id=id WHERE id=?", (deck_id,))
        from .deck_collections import validate_destination

        validate_destination(conn, collection_id)
        duplicate = conn.execute(
            "SELECT id FROM managed_deck_revisions WHERE deck_id = ? AND content_hash = ?",
            (deck_id, digest),
        ).fetchone()
        if duplicate:
            revision_id = duplicate[0]
        if existing:
            replay = deck.get("source", "").startswith("arena_") and (
                (observed_at and stamp <= existing[1])
                or (not observed_at and duplicate is not None)
            )
            if not replay:
                conn.execute(
                    "UPDATE managed_decks SET name = ?, format_name = ?, current_revision_id = ?, updated_at = ? WHERE id = ?",
                    (deck["name"], deck.get("format_name", ""), revision_id, stamp, deck_id),
                )
        else:
            conn.execute(
                "INSERT INTO managed_decks(id, account_key, name, format_name, current_revision_id, created_at, updated_at, collection_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    deck_id,
                    account_key,
                    deck["name"],
                    deck.get("format_name", ""),
                    revision_id,
                    stamp,
                    stamp,
                    collection_id,
                ),
            )
        if existing and assign_collection:
            conn.execute(
                "UPDATE managed_decks SET collection_id=?,updated_at=? WHERE id=?",
                (collection_id, stamp, deck_id),
            )
        if not duplicate:
            conn.execute(
                "INSERT INTO managed_deck_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revision_id,
                    deck_id,
                    existing[0] if existing else None,
                    digest,
                    encoded(deck),
                    deck.get("source", "import"),
                    deck.get("completeness", "text"),
                    stamp,
                ),
            )
            conn.executemany(
                "INSERT INTO managed_deck_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        revision_id,
                        i,
                        c["section"],
                        c["quantity"],
                        c["name"],
                        c.get("arena_id"),
                        c.get("set_code"),
                        c.get("collector_number"),
                    )
                    for i, c in enumerate(deck["cards"])
                ],
            )
        if account_key and arena_deck_id:
            conn.execute(
                """INSERT INTO managed_deck_bindings VALUES (?, ?, ?, ?, 'unknown')
                ON CONFLICT(account_key, arena_deck_id) DO UPDATE SET
                deck_id = excluded.deck_id, observed_at = excluded.observed_at""",
                (account_key, arena_deck_id, deck_id, stamp),
            )
        stored = conn.execute(
            "SELECT payload_json FROM managed_deck_revisions WHERE id = ?", (revision_id,)
        ).fetchone()
        import json

        if stored is None or content_hash(json.loads(stored[0])) != digest:
            raise ValueError("Deck backup verification failed.")
    return deck_detail(conn, deck_id)


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
    for (name,) in conn.execute("SELECT name FROM cards WHERE name LIKE '% // %'"):
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
    suffix = display_name[len(base) :] if display_name.startswith(base) else ""
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
    revealed_events: Optional[List[CardEvent]] = None,
) -> None:
    """Persist played-, drawn- and revealed-card counts by participant.

    Played events keep their full display names (one row per display variant,
    matching historical rows). Drawn and revealed events (milled, discarded,
    exiled from a hidden zone; ``CardEvent.source`` names which) are matched to
    an existing row by base card name when possible so a card played and drawn
    stays one row; other cards get their own row with played_count = 0.
    """
    counts: Dict[str, Dict[str, object]] = {}
    base_to_display: Dict[str, str] = {}
    half_map = split_card_half_map(conn)
    # Names in this batch may introduce split cards not yet in the cards table.
    for event in list(events) + list(drawn_events or []) + list(revealed_events or []):
        batch_base = analytics_card_base_name(str(event.card_name or ""))
        if SPLIT_NAME_SEPARATOR in batch_base:
            for half in batch_base.split(SPLIT_NAME_SEPARATOR):
                half = half.strip()
                if half and half not in half_map:
                    half_map[half] = batch_base
    count_columns = ("played_count", "drawn_count", *REVEAL_COLUMNS.values())

    def new_row(event: CardEvent) -> Dict[str, object]:
        row: Dict[str, object] = {column: 0 for column in count_columns}
        row["type_category"] = event.card_type_category
        return row

    for event in events:
        display_name = canonical_split_display(refresh_display_name(event.card_name), half_map)
        if display_name not in counts:
            counts[display_name] = new_row(event)
        counts[display_name]["played_count"] = int(counts[display_name]["played_count"]) + 1
        if event.card_type_category and event.card_type_category != "Other":
            counts[display_name]["type_category"] = event.card_type_category
        base_name = analytics_card_base_name(display_name)
        if base_name and base_name not in base_to_display:
            base_to_display[base_name] = display_name

    unplayed = [(event, "drawn_count") for event in drawn_events or []] + [
        (event, REVEAL_COLUMNS[str(event.source)])
        for event in revealed_events or []
        if event.source in REVEAL_COLUMNS
    ]
    for event, column in unplayed:
        display_name = canonical_split_display(refresh_display_name(event.card_name), half_map)
        base_name = analytics_card_base_name(display_name)
        target_name = base_to_display.get(base_name, display_name)
        if target_name not in counts:
            counts[target_name] = new_row(event)
            if base_name:
                base_to_display[base_name] = target_name
        counts[target_name][column] = int(counts[target_name][column]) + 1
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
                drawn_count,
                discarded_count,
                milled_count,
                exiled_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, participant_id, display_name) DO UPDATE SET
                card_id = excluded.card_id,
                type_category = excluded.type_category,
                played_count = excluded.played_count,
                drawn_count = excluded.drawn_count,
                discarded_count = excluded.discarded_count,
                milled_count = excluded.milled_count,
                exiled_count = excluded.exiled_count
            """,
            (
                game_id,
                participant_id,
                card_id,
                display_name,
                type_category,
                *(int(data[column]) for column in count_columns),
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
        source = getattr(event, "source", None)
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
                copy_number,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                source,
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
