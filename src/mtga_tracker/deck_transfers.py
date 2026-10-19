"""Verified native transfers with durable intents and read-only reconciliation."""

from __future__ import annotations

import json
from collections import Counter
import sqlite3
import uuid

from . import deck_manager as dm
from . import native_deck_archive as na

TERMINAL = ("complete", "cancelled")


def _card_key(card, aliases=None):
    """(section, name) for comparing an import with Arena's result. Names in export
    text may omit the back face, and Arena accepts either of a card's interchangeable
    names (a Universes Beyond card and its Omenpath name), returning the printing the
    player has; `aliases` maps both names to one key."""
    name = card["name"].split(" // ")[0].strip().casefold()
    return (card["section"], (aliases or {}).get(name, name))


def _quantities(cards, aliases=None):
    # Quantities/piles must still agree exactly; never silently import
    # inventory-clamped lists.
    result = Counter()
    for card in cards:
        result[_card_key(card, aliases)] += card["quantity"]
    return result


def _import_differences(expected_cards, actual_cards, wanted, returned, aliases=None, limit=5):
    """Name the cards whose quantities differ, e.g. "Deck: 4 Forest in the list, 2 from Arena"."""
    names = {}
    for card in list(actual_cards) + list(expected_cards):
        names[_card_key(card, aliases)] = card["name"]
    keys = sorted(set(wanted) | set(returned), key=lambda key: (key[0], key[1]))
    changed = [key for key in keys if wanted.get(key, 0) != returned.get(key, 0)]
    parts = [
        f"{section}: {wanted.get(key, 0)} {names[key]} in the list, "
        f"{returned.get(key, 0)} from Arena"
        for key in changed[:limit]
        for section in [key[0]]
    ]
    more = f"; and {len(changed) - limit} more" if len(changed) > limit else ""
    return "Differences: " + "; ".join(parts) + more + "."


def add_import(
    conn,
    bridge,
    selection,
    request_id,
    report,
    resolve_name,
    progress=None,
    card_type=None,
    aliases=None,
):
    """Prepare text with Arena's parser, reject dropped cards, then use journaled restore.

    `aliases` maps casefolded interchangeable card names to one shared key
    (`CardDatabase.interchangeable_name_index`)."""
    source_id = str(uuid.uuid5(uuid.UUID(request_id), "text-import-source"))
    bindings = conn.execute(
        "SELECT deck_id FROM managed_deck_bindings WHERE account_key=? AND arena_deck_id=?",
        (bridge.account_key, source_id),
    ).fetchone()
    if bindings:
        previous = dm.deck_detail(conn, bindings[0])
        original = previous["deck"].get("metadata", {}).get("native_import_request")
        if original != {key: selection[key] for key in ("text", "name", "format_name")}:
            raise dm.DeckManagerError("This import request ID already belongs to another decklist.")
        return transfer(
            conn, bridge, "restore", {"id": bindings[0]}, request_id, report, resolve_name, progress
        )
    if pending(conn, bridge.account_key):
        raise dm.DeckManagerError("Reconcile the interrupted transfer before adding another deck.")
    if report.get("deck_screen_open") is not True or report.get("limit_reached") is not False:
        raise dm.DeckManagerError("Open Arena on Decks outside a match with a free deck slot.")
    expected = dm.parse_import(selection["text"], selection["name"], selection["format_name"])
    if not resolve_name or any(c["section"] == "Maybeboard" for c in expected["cards"]):
        raise dm.DeckManagerError(
            "Direct import requires local card names and Arena-supported piles."
        )
    archive = na.validate_archive(
        bridge.prepare_import(selection["text"], expected["name"], source_id)
    )
    archive = na.with_import_summary(
        archive,
        na.arena_format(selection["format_name"]),
        na.tile_card(archive["source_snapshot"], card_type),
    )
    actual = na.document(archive, resolve_name)
    if actual["name"] != expected["name"] or archive["source_snapshot"]["arena_id"] != source_id:
        raise dm.DeckManagerError("Arena returned a different prepared deck. No deck was created.")

    def quantities(cards):
        return _quantities(cards, aliases)

    wanted, returned = quantities(expected["cards"]), quantities(actual["cards"])
    if wanted != returned:
        raise dm.DeckManagerError(
            "Arena’s importer changed the card list, possibly because cards are missing. "
            "No deck was created. Use Arena’s text import to review missing cards. "
            + _import_differences(expected["cards"], actual["cards"], wanted, returned, aliases)
        )
    saved_id = selection.get("saved_deck_id")
    if saved_id:
        previous = dm.deck_detail(conn, saved_id)
        if previous["trashed_at"] or quantities(previous["deck"]["cards"]) != quantities(
            expected["cards"]
        ):
            raise dm.DeckManagerError("The saved deck changed. Refresh before adding it to Arena.")
        if previous["account_key"] not in (None, bridge.account_key):
            raise dm.DeckManagerError("This saved deck belongs to another Arena account.")
    saved = persist_archive(
        conn,
        archive,
        bridge.account_key,
        resolve_name,
        deck_id=saved_id,
        collection_id=selection.get("collection_id"),
        metadata={
            "native_import_request": {
                key: selection[key] for key in ("text", "name", "format_name")
            }
        },
    )
    return transfer(
        conn, bridge, "restore", {"id": saved["id"]}, request_id, report, resolve_name, progress
    )


def journal_phase(conn, transfer_id, phase, error=None):
    with conn:
        conn.execute(
            "UPDATE managed_deck_transfers SET phase=?, error=?, updated_at=? WHERE id=?",
            (phase, error, dm.now(), transfer_id),
        )


def pending(conn, account=None):
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM managed_deck_transfers WHERE phase NOT IN ('complete','cancelled')"
    return [
        dict(r)
        for r in conn.execute(
            sql + (" AND account_key=?" if account else "") + " ORDER BY created_at",
            (account,) if account else (),
        )
    ]


def roster_ids(report):
    decks = report.get("decks")
    if (
        report.get("roster_refreshed") is not True
        or not isinstance(decks, list)
        or len(decks) > 2000
    ):
        raise dm.DeckManagerError("A fresh Arena roster is required.")
    ids = [str(uuid.UUID(d["arena_id"])) for d in decks]
    if len(ids) != len(set(ids)) or any(d.get("is_net_deck") is not False for d in decks):
        raise dm.DeckManagerError("Invalid Arena roster.")
    return ids


def check_remaining(before, after, removed=None):
    expected = set(before) - ({removed} if removed else set())
    if not expected <= set(roster_ids(after)):
        raise dm.DeckManagerError(
            "Other Arena decks changed during the transfer. Reconcile before continuing."
        )


def persist_archive(
    conn,
    archive,
    account,
    resolve_name=None,
    *,
    metadata=None,
    deck_id=None,
    collection_id=None,
    assign_collection=False,
):
    deck = na.document(archive, resolve_name)
    deck["metadata"]["native_account_key"] = account
    deck["metadata"].update(metadata or {})
    conn.execute("PRAGMA synchronous=FULL")
    saved = dm.save_deck(
        conn,
        deck,
        deck_id=deck_id,
        collection_id=collection_id,
        assign_collection=assign_collection,
        account_key=account,
        arena_deck_id=archive["source_snapshot"]["arena_id"],
        observed_at=dm.now(),
    )
    # Read the committed immutable revision and compare its full normalized hash.
    restored = dm.deck_detail(conn, saved["id"], saved["revision_id"])
    if dm.content_hash(restored["deck"]) != dm.content_hash(deck):
        raise dm.DeckManagerError("The saved backup did not pass read-back verification.")
    return restored


def created_matches(saved, actual, archive, arena_id):
    if na.import_draft(saved["deck"]):
        return na.same_contents(actual, archive["source_snapshot"], restored_id=arena_id)
    return na.equivalent(actual, archive["source_snapshot"], restored_id=arena_id)


def save_arena_copy(conn, bridge, saved, arena_id, resolve_name):
    """Save Arena's stored copy of a created deck as the backup's newest revision.

    Later moves compare snapshots exactly, so the backup must hold what Arena
    actually stored. Earlier revisions are kept.
    """
    archives = bridge.archive([arena_id])
    if len(archives) != 1 or archives[0]["source_snapshot"]["arena_id"] != arena_id:
        raise dm.DeckManagerError("Arena returned a different backup identity.")
    metadata = saved["deck"].get("metadata", {})
    persist_archive(
        conn,
        na.validate_archive(archives[0]),
        bridge.account_key,
        resolve_name,
        deck_id=saved["id"],
        metadata={k: metadata[k] for k in ("native_import_request",) if k in metadata},
    )


def set_presence(conn, account, arena_id, deck_id, presence):
    with conn:
        conn.execute(
            """INSERT INTO managed_deck_bindings
                     (account_key,arena_deck_id,deck_id,observed_at,presence)
                     VALUES(?,?,?,?,?) ON CONFLICT(account_key,arena_deck_id) DO UPDATE SET
                     deck_id=excluded.deck_id,observed_at=excluded.observed_at,
                     presence=excluded.presence""",
            (account, arena_id, deck_id, dm.now(), presence),
        )


def begin(conn, transfer_id, account, saved, arena_id, action, baseline):
    conn.execute("PRAGMA synchronous=FULL")
    with conn:
        locked = conn.execute("UPDATE managed_decks SET id=id WHERE id=?", (saved["id"],))
        if (
            not locked.rowcount
            or not conn.execute(
                "SELECT 1 FROM managed_deck_revisions WHERE id=? AND deck_id=?",
                (saved["revision_id"], saved["id"]),
            ).fetchone()
        ):
            raise dm.DeckManagerError(
                "The local backup changed before transfer. No Arena request was made."
            )
        if (
            action == "restore"
            and conn.execute(
                "SELECT trashed_at FROM managed_decks WHERE id=?", (saved["id"],)
            ).fetchone()[0]
        ):
            raise dm.DeckManagerError("The backup was moved to Trash before transfer.")
        conn.execute(
            """INSERT INTO managed_deck_transfers
                     (id,account_key,deck_id,revision_id,arena_deck_id,action,phase,baseline_ids_json,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,'prepared',?,?,?)""",
            (
                transfer_id,
                account,
                saved["id"],
                saved["revision_id"],
                arena_id,
                action,
                dm.encoded(baseline),
                dm.now(),
                dm.now(),
            ),
        )


def transfer(conn, bridge, action, selection, request_id, report, resolve_name=None, progress=None):
    """One deck at a time. Persist write intent before calling Arena exactly once."""
    notify = progress or (lambda _step, _detail: None)
    account = bridge.account_key
    transfer_id = str(uuid.uuid5(uuid.UUID(request_id), action + ":" + selection["id"]))
    existing = conn.execute(
        "SELECT phase,account_key,revision_id FROM managed_deck_transfers WHERE id=?",
        (transfer_id,),
    ).fetchone()
    if existing:
        if existing[1] != account or (
            selection.get("revision") and selection["revision"] != existing[2]
        ):
            raise dm.DeckManagerError(
                "This request identity was already used for another account or revision."
            )
        if existing[0] == "complete":
            return report
        raise dm.DeckManagerError(
            "This transfer was already started. Reconcile it instead of repeating it."
        )
    if pending(conn, account):
        raise dm.DeckManagerError(
            "An interrupted transfer needs reconciliation before another transfer."
        )
    baseline = roster_ids(report)
    if report.get("deck_screen_open") is not True:
        raise dm.DeckManagerError(
            "Arena isn’t on its Decks screen. Go to Decks in Arena, outside a match, then try again."
        )
    if action == "store":
        arena_id = str(uuid.UUID(selection["id"]))
        if arena_id not in baseline:
            raise dm.DeckManagerError("This deck is no longer in Arena. Refresh the list.")
        archives = bridge.archive([arena_id])
        if len(archives) != 1 or archives[0]["source_snapshot"]["arena_id"] != arena_id:
            raise dm.DeckManagerError("Arena returned a different backup identity.")
        archive = na.validate_archive(archives[0])
        # A chosen destination also moves a deck that was backed up earlier.
        saved = persist_archive(
            conn,
            archive,
            account,
            resolve_name,
            collection_id=selection.get("collection_id"),
            assign_collection="collection_id" in selection,
        )
        # Fetch again after disk commit: an external edit must prevent deletion.
        if not na.equivalent(bridge.fetch(arena_id), archive["source_snapshot"]):
            raise dm.DeckManagerError(
                "The Arena deck changed after backup; it has not been removed."
            )
    elif action == "restore":
        if report.get("limit_reached") is not False:
            raise dm.DeckManagerError(
                "Arena’s deck slots are full. Move a deck to your collection first."
            )
        saved = dm.deck_detail(conn, selection["id"], selection.get("revision"))
        if saved["trashed_at"]:
            raise dm.DeckManagerError("Restore this deck from Trash first.")
        archive = na.revision_archive(saved["deck"])
        # Portable backups may be moved between PCs, but native restores stay
        # scoped to their original authenticated account in this implementation.
        if (
            saved["account_key"] or saved["deck"].get("metadata", {}).get("native_account_key")
        ) != account:
            raise dm.DeckManagerError("This native backup belongs to another Arena account.")
        bindings = conn.execute(
            "SELECT arena_deck_id FROM managed_deck_bindings WHERE account_key=? AND deck_id=?",
            (account, saved["id"]),
        ).fetchall()
        if archive["source_snapshot"]["arena_id"] in baseline or any(
            r[0] in baseline for r in bindings
        ):
            raise dm.DeckManagerError("This deck is already in Arena. Refresh before restoring.")
        arena_id = str(uuid.uuid5(uuid.UUID(transfer_id), "arena-deck"))
        if arena_id in baseline:
            raise dm.DeckManagerError(
                "Restore identity already exists; reconcile instead of creating again."
            )
    else:
        raise dm.DeckManagerError("Unknown native transfer.")
    begin(conn, transfer_id, account, saved, arena_id, action, baseline)
    dispatched = False
    try:
        if action == "restore":
            notify(0, "Rebuilding the saved deck in Arena…")
            bridge.prepare_create(archive, arena_id)
        notify(
            1,
            (
                "Removing the verified backup from Arena…"
                if action == "store"
                else "Creating the deck in Arena…"
            ),
        )
        journal_phase(conn, transfer_id, "write_started")
        dispatched = True
        if action == "store":
            bridge.remove(archive["source_snapshot"])
        else:
            actual = bridge.create_prepared(arena_id)
            if not created_matches(saved, actual, archive, arena_id):
                raise dm.DeckManagerError(
                    "Arena’s restored deck differs from the backup. It was retained for review."
                )
        notify(2, "Checking Arena’s refreshed deck list…")
        journal_phase(conn, transfer_id, "verifying")
        after = bridge.roster()
        ids = roster_ids(after)
        if action == "store":
            if arena_id in ids:
                raise dm.DeckManagerError("Arena still reports this deck; reconcile its removal.")
            check_remaining(baseline, after, arena_id)
            presence = "absent"
        else:
            if arena_id not in ids or not created_matches(
                saved, bridge.fetch(arena_id), archive, arena_id
            ):
                raise dm.DeckManagerError(
                    "The restored deck could not be verified. Reconcile before continuing."
                )
            check_remaining(baseline, after)
            if na.import_draft(saved["deck"]):
                save_arena_copy(conn, bridge, saved, arena_id, resolve_name)
            presence = "present"
        set_presence(conn, account, arena_id, saved["id"], presence)
        journal_phase(conn, transfer_id, "complete")
        notify(3, "Transfer verified.")
        return after
    except Exception:
        journal_phase(
            conn,
            transfer_id,
            "uncertain" if dispatched else "cancelled",
            (
                "The native outcome needs reconciliation. No request was repeated."
                if dispatched
                else "Preparation failed before any Arena write. The saved deck remains."
            ),
        )
        raise


def reconcile(conn, bridge, report, resolve_name=None):
    """Never writes to Arena: verify committed outcomes or cancel uncommitted ones."""
    ids = roster_ids(report)
    for row in pending(conn, bridge.account_key):
        saved = dm.deck_detail(conn, row["deck_id"], row["revision_id"])
        archive = na.validate_archive(saved["deck"].get("metadata", {}).get("native_archive"))
        arena_id = row["arena_deck_id"]
        baseline = json.loads(row["baseline_ids_json"])
        if row["action"] == "store":
            check_remaining(baseline, report, arena_id)
            if arena_id in ids:
                # Removal did not commit; preserve both copies, require a new
                # explicit move rather than ever replaying the old delete.
                if not na.equivalent(bridge.fetch(arena_id), archive["source_snapshot"]):
                    raise dm.DeckManagerError(
                        "An interrupted deck was edited in Arena. "
                        "Its saved backup remains; review it before continuing."
                    )
                phase, presence = "cancelled", "present"
            else:
                phase, presence = "complete", "absent"
        else:
            check_remaining(baseline, report)
            if arena_id in ids:
                # The identity is derived from this transfer, so its presence
                # proves Arena created it. Edits made in Arena since then (name,
                # format, art, styles) are the player's: keep the original
                # revision and save Arena's current copy on top of it.
                if na.import_draft(saved["deck"]) or not created_matches(
                    saved, bridge.fetch(arena_id), archive, arena_id
                ):
                    save_arena_copy(conn, bridge, saved, arena_id, resolve_name)
                phase, presence = "complete", "present"
            elif row["phase"] == "prepared":
                # No create intent committed, so a request could not start.
                phase, presence = "cancelled", "absent"
            else:
                # A late server commit can follow a timeout. Absence alone does
                # not establish that retrying creation is safe.
                raise dm.DeckManagerError(
                    "Arena has not confirmed the interrupted restore. "
                    "Reconnect after Arena finishes syncing; no creation was retried."
                )
        set_presence(conn, bridge.account_key, arena_id, row["deck_id"], presence)
        journal_phase(conn, row["id"], phase)
    return report
