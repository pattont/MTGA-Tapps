"""Turn a bounded native-cache snapshot into a separate, verified deck library."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

from mtga_tracker import deck_manager as dm

SECTIONS = {
    "Main": "Deck",
    "Sideboard": "Sideboard",
    "CommandZone": "Commander",
    "Companions": "Companion",
}


def documents(report, resolve_name=None):
    """Validate every ordinary-deck snapshot before opening any output database."""
    if (
        report.get("schema") != 1
        or report.get("runtime") != "IL2CPP"
        or report.get("unity_thread_observed") is not True
    ):
        raise ValueError("A supported Unity-thread cache snapshot is required.")
    pile_names = report.get("pile_names", {})
    decks = report.get("decks")
    if not isinstance(decks, list) or len(decks) > 2000:
        raise ValueError("Invalid deck catalog.")
    result = []
    ids = set()
    for deck in decks:
        if type(deck.get("is_net_deck")) is not bool:
            raise ValueError("Missing deck classification.")
        if deck["is_net_deck"]:
            continue
        arena_id = str(uuid.UUID(deck["arena_id"]))
        if arena_id in ids:
            raise ValueError("Duplicate Arena deck identity.")
        ids.add(arena_id)
        if deck.get("contents_loaded") is not True or "skins" not in deck:
            raise ValueError("An ordinary deck has incomplete cached contents.")
        cards = []
        seen_piles = set()
        for pile in deck.get("piles", []):
            label = pile_names.get(str(pile["pile"]))
            if label not in SECTIONS or label in seen_piles:
                raise ValueError("Unsupported or duplicate deck pile; no partial archive written.")
            seen_piles.add(label)
            for card in pile["entries"]:
                card_id, quantity = card["id"], card["quantity"]
                if (
                    type(card_id) is not int
                    or card_id <= 0
                    or type(quantity) is not int
                    or quantity <= 0
                ):
                    raise ValueError("Invalid native card entry.")
                cards.append(
                    {
                        "section": SECTIONS[label],
                        "arena_id": card_id,
                        "quantity": quantity,
                        "name": (resolve_name(card_id) if resolve_name else None)
                        or f"Card #{card_id}",
                        "set_code": None,
                        "collector_number": None,
                    }
                )
        if seen_piles != set(SECTIONS):
            raise ValueError("A cached deck is missing a required pile.")
        summary = deck["summary"]
        if summary.get("DeckId") != arena_id or summary.get("Name") != deck.get("name"):
            raise ValueError("Deck summary identity mismatch.")
        attributes = {a["key"]: a["value"] for a in summary.get("Attributes", [])}
        normalized = dm.validate_deck(
            {
                "name": deck["name"],
                "format_name": attributes.get("Format") or "",
                "cards": cards,
                "import_text": None,
                "completeness": "full",
                "source": "arena_native_cache",
                "metadata": {
                    "arena_deck_id": arena_id,
                    "raw_runtime_deck": deck,
                    "scope": "Loaded cache observation; no authenticated binding or freshness claim.",
                },
            }
        )
        result.append(normalized)
    return result


def write_library(report, destination, resolve_name=None):
    """Publish a new library only after every snapshot passes a read-back check."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Capture requires a new database; existing databases are never modified.")
    decks = documents(report, resolve_name)
    fd, staging_name = tempfile.mkstemp(
        prefix=".native-decks-", suffix=".sqlite3", dir=destination.parent
    )
    os.close(fd)
    staging = Path(staging_name)
    conn = None
    try:
        conn = dm.library_connection(staging)
        for deck in decks:
            saved = dm.save_deck(conn, deck)
            restored = dm.deck_detail(conn, saved["id"])["deck"]
            if dm.content_hash(restored) != dm.content_hash(deck):
                raise ValueError("Deck archive read-back verification failed.")
        if conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] != 0:
            raise ValueError("Experiment database unexpectedly contains game history.")
        conn.close()
        conn = None
        with staging.open("r+b") as handle:  # Windows fsync needs write access
            os.fsync(handle.fileno())
        # Same-directory hard link publishes a complete file atomically and
        # refuses overwrite even if another process created the destination.
        os.link(staging, destination)
        return len(decks)
    finally:
        if conn:
            conn.close()
        staging.unlink(missing_ok=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        count = write_library(
            json.loads(args.snapshot.read_text(encoding="utf-8")), args.destination
        )
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"Capture failed: {exc}\n")
    print(
        f"Verified and archived {count} ordinary cached decks; Arena and existing databases unchanged."
    )


if __name__ == "__main__":
    main()
