"""Capture complete submitted decklists independently of gameplay analytics."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import timezone
from pathlib import Path

from .deck_manager import DeckManagerError, validate_deck
from .log_entry import LineBuffer
from .log_json import parse_json_from_body

DECK_REQUEST = re.compile(r"==>\s+(DeckUpsertDeckV3|EventSetDeckV3)\b")
PILES = {
    "MainDeck": "Deck",
    "Sideboard": "Sideboard",
    "CommandZone": "Commander",
    "Companions": "Companion",
}


def captured_deck_id(arena_id):
    """The entry for an Arena deck seen only in the log (not yet tied to a native transfer)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "tapps:unassigned-arena-deck:" + arena_id))


def _tracked_entry(conn, arena_id):
    """The saved entry a native transfer tied to this Arena deck, if any.

    A transfer row commits before Arena creates the deck, so it covers the save
    Arena logs before the transfer binds the deck.
    """
    row = conn.execute(
        """SELECT link.deck_id FROM (
               SELECT deck_id, observed_at AS seen FROM managed_deck_bindings
               WHERE arena_deck_id = ?
               UNION ALL
               SELECT deck_id, updated_at AS seen FROM managed_deck_transfers
               WHERE arena_deck_id = ?
           ) AS link JOIN managed_decks ON managed_decks.id = link.deck_id
           ORDER BY link.seen DESC LIMIT 1""",
        (arena_id, arena_id),
    ).fetchone()
    return row[0] if row else None


def _already_saved(conn, deck_id, deck):
    """Whether any revision of the entry holds this name and card list.

    Comparing history, not only the newest revision, keeps a rescan of older log
    saves from replacing a newer full backup.
    """

    def counts(rows):
        totals = Counter()
        for section, arena_id, quantity in rows:
            totals[(section, arena_id)] += quantity
        return totals

    wanted = counts((c["section"], c.get("arena_id"), c["quantity"]) for c in deck["cards"])
    for revision_id, payload in conn.execute(
        "SELECT id, payload_json FROM managed_deck_revisions WHERE deck_id = ?", (deck_id,)
    ):
        cards = conn.execute(
            "SELECT section, arena_id, quantity FROM managed_deck_cards WHERE revision_id = ?",
            (revision_id,),
        )
        if json.loads(payload).get("name") == deck["name"] and counts(cards) == wanted:
            return True
    return False


class DeckCapture:
    """Only deck-specific payloads enter the archive; outgoing saves stay unconfirmed."""

    def __init__(self, conn, name_resolver=None):
        self.conn = conn
        self.name_resolver = name_resolver or (lambda arena_id: f"Card #{arena_id}")

    def consume(self, entry):
        marker = DECK_REQUEST.search(entry.body)
        if marker is None:
            return None
        data = parse_json_from_body(entry.body)
        if not isinstance(data, dict):
            return None
        payload = data.get("request", data)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return None
        if not isinstance(payload, dict):
            return None
        summary, raw = payload.get("Summary"), payload.get("Deck")
        if (
            not isinstance(summary, dict)
            or not isinstance(raw, dict)
            or not isinstance(raw.get("MainDeck"), list)
        ):
            return None
        arena_id = summary.get("DeckId")
        if not isinstance(arena_id, str) or not arena_id:
            return None
        cards = []
        for pile, section in PILES.items():
            entries = raw.get(pile, [])
            if not isinstance(entries, list):
                raise DeckManagerError("Malformed Arena deck pile; nothing was archived.")
            for card in entries:
                if not isinstance(card, dict):
                    raise DeckManagerError("Malformed Arena card; nothing was archived.")
                card_id, quantity = card.get("cardId"), card.get("quantity")
                if (
                    type(card_id) is not int
                    or card_id < 1
                    or type(quantity) is not int
                    or quantity < 1
                ):
                    raise DeckManagerError(
                        "Malformed Arena card quantity or ID; nothing was archived."
                    )
                name = self.name_resolver(card_id)
                if not name or name.startswith("Unknown Card"):
                    name = f"Card #{card_id}"
                cards.append(
                    {
                        "section": section,
                        "quantity": quantity,
                        "arena_id": card_id,
                        "name": name,
                        "set_code": None,
                        "collector_number": None,
                    }
                )
        attributes = summary.get("Attributes", [])
        fmt = (
            next(
                (
                    a.get("value", "")
                    for a in attributes
                    if isinstance(a, dict) and a.get("name") == "Format"
                ),
                "",
            )
            if isinstance(attributes, list)
            else ""
        )
        deck = {
            "name": summary.get("Name") or "Untitled deck",
            "format_name": fmt,
            "cards": cards,
            "import_text": None,
            "source": (
                "arena_save_request"
                if marker[1] == "DeckUpsertDeckV3"
                else "arena_event_submission"
            ),
            "completeness": "full" if all(p in raw for p in PILES) else "main_only",
            "metadata": {"arena_deck_id": arena_id, "summary": summary, "deck": raw},
        }
        deck = validate_deck(deck)
        # A deck Deck Manager moved into Arena keeps its one entry: Arena's save of a
        # list already in that entry adds nothing; a later edit becomes a revision.
        tracked = _tracked_entry(self.conn, arena_id)
        if tracked and _already_saved(self.conn, tracked, deck):
            return tracked
        # GUID identity groups revisions without making any account/presence claim.
        # No server bindings are written until a real authenticated adapter exists.
        local_id = tracked or captured_deck_id(arena_id)
        from .analytics_persistence import persist_managed_deck

        observed_at = (
            entry.timestamp.astimezone(timezone.utc).isoformat() if entry.timestamp else None
        )
        persist_managed_deck(
            self.conn, deck, deck_id=local_id, create=True, observed_at=observed_at
        )
        return local_id


def capture_log(conn, log_path: Path, name_resolver=None):
    """Explicit bounded rescan, using the existing multiline entry buffer."""
    buffer = LineBuffer()
    capture = DeckCapture(conn, name_resolver)
    captured = set()
    failures = 0

    def consume(entry):
        nonlocal failures
        try:
            deck_id = capture.consume(entry)
            if deck_id:
                captured.add(deck_id)
        except (DeckManagerError, ValueError, TypeError):
            failures += 1

    # Snapshot length bounds this job if Arena continues appending.
    size = Path(log_path).stat().st_size
    with Path(log_path).open("rb") as handle:
        remaining = size
        while remaining > 0:
            raw_line = handle.readline(min(remaining, 2_000_001))
            if not raw_line:
                break
            remaining -= len(raw_line)
            for entry in buffer.push_line(raw_line.decode("utf-8", errors="replace")):
                consume(entry)
        for entry in buffer.flush():
            consume(entry)
    return {
        "captured": len(captured),
        "rejected": failures,
        "note": "Only full lists present in this log were captured. Other Arena decks may need to be exported or saved first.",
    }
