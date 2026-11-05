"""Local dashboard endpoints for explicit deck-library actions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import deck_manager as dm
from . import deck_collections as dc
from .deck_colors import COLOR_SECTIONS, deck_colors
from . import native_deck_archive


def _read_connection(path):
    path = Path(path)
    if not path.is_file():
        return None
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'managed_decks'").fetchone():
        conn.close()
        return None
    return conn


_PRINTINGS = None


def _with_printings(deck):
    """Add set/collector numbers from Arena's card DB to a full backup's list.

    Native backups store printing IDs, not set codes; without them Arena's
    importer picks a printing itself. Unknown IDs keep the name-only line.
    """
    global _PRINTINGS
    if deck.get("import_text"):
        return deck
    if _PRINTINGS is None:
        try:
            from .card_database import CardDatabase

            _PRINTINGS = CardDatabase().export_index_by_arena_id()
        except Exception:
            _PRINTINGS = {}
    cards = []
    for card in deck["cards"]:
        printing = _PRINTINGS.get(card.get("arena_id") or 0)
        if printing and printing[1] and printing[2] and not card.get("set_code"):
            card = {**card, "set_code": printing[1], "collector_number": printing[2]}
        cards.append(card)
    return {**deck, "cards": cards}


def _saved_tile_art(deck, cards):
    """Direct image links for a saved deck's tile card (its ``art_card``)."""
    from .card_art import tile_art

    card = next((c for c in cards if c["name"] == deck.get("art_card")), None)
    try:
        return tile_art(
            card and card["arena_id"],
            deck.get("art_card"),
            card and card["set_code"],
            card and card["collector_number"],
        )
    except Exception:  # noqa: BLE001 - art is cosmetic
        return {"art_url": None, "art_print": None}


_CARD_DB = None


def _front_face(name):
    """A two-faced card's front face: Unholy Annex for Unholy Annex // Ritual Chamber."""
    for separator in (" // ", " / "):
        if separator in name:
            return name.split(separator)[0].strip()
    return name


def _card_info(cards):
    """Mana cost and card type per card name, from Arena's local card DB.

    The deck dialogs group cards by type and show costs; Deck Compare sorts
    lands last. Missing data is left out; the dialog shows the name alone.
    """
    global _CARD_DB
    if _CARD_DB is None:
        try:
            from .card_database import CardDatabase

            _CARD_DB = CardDatabase()
        except Exception:
            _CARD_DB = False
    if not _CARD_DB:
        return {}
    try:
        mana = _CARD_DB.mana_cost_index_by_name()
    except Exception:
        mana = {}
    try:
        types_by_id, types_by_name = _CARD_DB.list_type_indexes()
    except Exception:
        types_by_id, types_by_name = {}, {}
    info = {}
    for card in cards:
        name = card.get("name") or ""
        if not name or name in info:
            continue
        entry = {}
        front = _front_face(name)
        # Arena joins a two-faced card's costs ({2}{B}{3}{B}{B} for a Room):
        # the front face's cost is the one you cast it for.
        cost = mana.get(front) or mana.get(name)
        if cost:
            entry["mana_cost"], entry["mana_value"] = cost[0], cost[1]
        kind = types_by_id.get(card.get("arena_id") or 0)
        kind = kind or types_by_name.get(name) or types_by_name.get(front)
        if kind:
            entry["type"] = kind
        if entry:
            info[name] = entry
    return info


def handle_get(path, query, db_path):
    from . import deck_native_api

    native = deck_native_api.handle_get(path, query, db_path)
    if native is not None:
        return native
    if path not in ("/api/deck-manager", "/api/deck-manager/deck", "/api/deck-manager/export"):
        return None
    conn = None
    try:
        conn = _read_connection(db_path)
        if path == "/api/deck-manager":
            decks = dm.list_decks(conn) if conn else []
            records = {}
            for deck in decks:
                deck["tags"] = json.loads(deck.pop("tags_json"))
            if conn:
                # An import draft (no Version attribute) is added from its text instead:
                # restoring it would recreate Arena's empty format and missing art.
                restorable = {
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM managed_deck_revisions WHERE json_extract(payload_json,'$.metadata.native_archive.archive_kind')='arena_typed_model_poc'"
                        " AND (json_extract(payload_json,'$.metadata.native_import_request') IS NULL"
                        " OR EXISTS (SELECT 1 FROM json_each(payload_json,'$.metadata.native_archive.source_snapshot.summary.Attributes')"
                        " WHERE json_extract(value,'$.key')='Version'))"
                    )
                }
                for deck in decks:
                    deck["native_restorable"] = deck["current_revision_id"] in restorable
                bindings = {}
                for deck_id, arena_id in conn.execute(
                    "SELECT deck_id,arena_deck_id FROM managed_deck_bindings"
                ):
                    bindings.setdefault(deck_id, []).append(arena_id)
                for deck in decks:
                    deck["native_arena_ids"] = bindings.get(deck["id"], [])
                cards = {}
                for deck_id, section, quantity, name, arena_id, set_code, number in conn.execute(
                    "SELECT d.id,c.section,c.quantity,c.name,c.arena_id,c.set_code,c.collector_number"
                    " FROM managed_decks d"
                    " JOIN managed_deck_cards c ON c.revision_id=d.current_revision_id"
                    f" WHERE c.section IN ({','.join('?' * len(COLOR_SECTIONS))})",
                    COLOR_SECTIONS,
                ):
                    cards.setdefault(deck_id, []).append(
                        {
                            "section": section,
                            "quantity": quantity,
                            "name": name,
                            "arena_id": arena_id,
                            "set_code": set_code,
                            "collector_number": number,
                        }
                    )
                for deck in decks:
                    deck["colors"] = deck_colors(cards.get(deck["id"], []))
                    deck.update(_saved_tile_art(deck, cards.get(deck["id"], [])))
                # Win-loss from tracked games, by Arena deck id: Arena tiles look
                # theirs up in "records"; a saved deck adds up every id it has been.
                records = dm.played_records(conn)
                arena_ids = dm.saved_arena_ids(conn)
                for deck in decks:
                    deck["record"] = dm.combined_record(records, arena_ids.get(deck["id"], ()))
            available, message = deck_native_api.nb.availability()
            return 200, {
                "decks": decks,
                "records": records,
                "collections": dc.list_collections(conn) if conn else [],
                "capabilities": {
                    "arena_transfers": available,
                    "native_section": False,
                    "capacity": None,
                    "message": message,
                },
            }
        if conn is None:
            raise KeyError("Saved deck not found.")
        detail = dm.deck_detail(conn, query.get("id", [""])[0], query.get("revision", [None])[0])
        detail["tags"] = json.loads(detail.pop("tags_json"))
        detail["native_restorable"] = bool(
            detail["deck"].get("metadata", {}).get("native_archive")
        ) and not native_deck_archive.import_draft(detail["deck"])
        detail["colors"] = deck_colors(detail["deck"]["cards"])
        detail["native_arena_ids"] = [
            r[0]
            for r in conn.execute(
                "SELECT arena_deck_id FROM managed_deck_bindings WHERE deck_id=?", (detail["id"],)
            )
        ]
        if path.endswith("/export"):
            fmt = query.get("format", ["backup"])[0]
            if fmt not in ("backup", "arena"):
                raise dm.DeckManagerError("Unknown export format.")
            return 200, {
                "text": (
                    dm.export_document(detail)
                    if fmt == "backup"
                    else dm.portable_text(_with_printings(detail["deck"]))
                ),
                "name": detail["name"],
                "extension": ".tappsdeck" if fmt == "backup" else ".txt",
                "note": (
                    "Card styles and deck art are kept only in the full backup."
                    if fmt == "arena" and not detail["deck"].get("import_text")
                    else ""
                ),
            }
        detail["card_info"] = _card_info(detail["deck"]["cards"])
        snapshot = (detail["deck"].get("metadata") or {}).get("native_archive") or {}
        detail.update(dm.arena_dates((snapshot.get("source_snapshot") or {}).get("summary")))
        return 200, detail
    except KeyError as exc:
        return 404, {"error": exc.args[0]}
    except dm.DeckManagerError as exc:
        return 400, {"error": str(exc)}
    except sqlite3.Error:
        return 500, {"error": "The deck library could not be read. Check the tracker data folder."}
    finally:
        if conn:
            conn.close()


def handle_post(path, payload, db_path):
    from . import deck_native_api

    native = deck_native_api.handle_post(path, payload, db_path)
    if native is not None:
        return native
    if path not in (
        "/api/deck-manager/import",
        "/api/deck-manager/update",
        "/api/deck-manager/delete",
        "/api/deck-manager/remove-selected",
        "/api/deck-manager/capture",
        "/api/deck-manager/collections/save",
        "/api/deck-manager/collections/remove",
        "/api/deck-manager/collections/move",
    ):
        return None
    if not isinstance(payload, dict):
        return 400, {"error": "Expected a JSON object."}
    conn = None
    try:
        if "/collections/" in path:
            conn = dm.library_connection(db_path)
            if path.endswith("/save"):
                return 200, dc.save_collection(conn, payload.get("name"), payload.get("id"))
            if path.endswith("/remove"):
                if payload.get("confirm") != "REMOVE":
                    raise dm.DeckManagerError("Confirm removal of this collection.")
                return 200, {"ok": True, "count": dc.remove_collection(conn, payload.get("id"))}
            return 200, {
                "ok": True,
                "count": dc.move_decks(conn, payload.get("ids"), payload.get("collection_id")),
            }
        if path.endswith("/remove-selected"):
            action = payload.get("action")
            if action not in ("trash", "delete") or payload.get("confirm") != action.upper():
                raise dm.DeckManagerError("Confirm removal of the selected saved decks.")
            conn = dm.library_connection(db_path)
            count = dm.remove_decks(conn, payload.get("ids"), action)
            return 200, {"ok": True, "count": count}
        if path.endswith("/delete"):
            deck_id = payload.get("id")
            if not isinstance(deck_id, str) or not deck_id.strip():
                raise dm.DeckManagerError("A saved deck ID is required.")
            if payload.get("confirm") != "DELETE":
                raise dm.DeckManagerError(
                    "Confirm permanent deletion of this deck and all its revisions."
                )
            conn = dm.library_connection(db_path)
            dm.delete_deck(conn, deck_id)
            return 200, {"ok": True}
        if path.endswith("/import"):
            text = payload.get("text")
            if not isinstance(text, str):
                raise dm.DeckManagerError("Paste an Arena decklist or choose a .tappsdeck backup.")
            for field in ("name", "format_name", "deck_id"):
                if payload.get(field) is not None and not isinstance(payload[field], str):
                    raise dm.DeckManagerError(f"Invalid {field}.")
            deck = dm.import_document(text, payload.get("name"), payload.get("format_name") or "")
            conn = dm.library_connection(db_path)
            dc.validate_destination(conn, payload.get("collection_id"))
            return 200, dm.save_deck(
                conn,
                deck,
                deck_id=payload.get("deck_id"),
                collection_id=payload.get("collection_id"),
                assign_collection="collection_id" in payload,
            )
        if path.endswith("/update"):
            conn = dm.library_connection(db_path)
            deck_id = payload.get("id")
            if not isinstance(deck_id, str):
                raise dm.DeckManagerError("A saved deck ID is required.")
            dm.update_metadata(conn, deck_id, payload)
            return 200, {"ok": True}
        from .card_database import CardDatabase
        from .deck_capture import capture_log
        from .log_parser import MTGALogParser

        # No browser-supplied arbitrary path; reuse the resolved log and local DB.
        conn = dm.library_connection(db_path)
        selected_log = conn.execute(
            "SELECT log_path FROM live_status WHERE log_path IS NOT NULL LIMIT 1"
        ).fetchone()
        log = selected_log[0] if selected_log else MTGALogParser._find_log_path()
        cards = CardDatabase(log_path=log)
        return 200, capture_log(conn, Path(log), cards.get_card_name)
    except KeyError as exc:
        return 404, {"error": exc.args[0]}
    except (dm.DeckManagerError, FileNotFoundError, ValueError) as exc:
        return 400, {"error": str(exc)}
    except (OSError, sqlite3.Error):
        return 500, {
            "error": "The deck library could not be read or saved. Check the tracker data folder."
        }
    finally:
        if conn:
            conn.close()
