"""Background native deck jobs. GET never attaches to Arena."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
import uuid

from . import deck_manager as dm
from . import deck_transfers as dt
from . import native_deck_bridge as nb
from .deck_colors import deck_colors

_LOCK = threading.Lock()
# Decks archived per Arena frame during a backup; also the cancel granularity.
BACKUP_BATCH = 5
_JOBS = {}
_STATUS = {}
_ACTIVE = None


def _key(db_path):
    return str(Path(db_path).resolve())


def game_in_progress(db_path):
    """The live row's in_game flag, whatever the heartbeat's age (fail closed:
    a database read error propagates)."""
    from .live_api import game_activity

    return bool(game_activity(db_path)["in_game"])


def job_active():
    """True while a native deck job (backup, move, restore, add) is running."""
    with _LOCK:
        return _ACTIVE is not None


def status(db_path):
    available, message = nb.availability()
    with _LOCK:
        result = dict(_STATUS.get(_key(db_path), {}))
        active = _ACTIVE if _ACTIVE and _JOBS[_ACTIVE]["db"] == _key(db_path) else None
    account = result.pop("_account_key", None)
    pending = []
    path = Path(db_path)
    if path.is_file():
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='managed_deck_transfers'"
            ).fetchone():
                pending = [
                    {"id": r[0], "action": r[1], "phase": r[2], "deck_id": r[3]}
                    for r in conn.execute(
                        "SELECT id,action,phase,deck_id FROM managed_deck_transfers "
                        "WHERE phase NOT IN ('complete','cancelled')"
                        + (" AND account_key=?" if account else ""),
                        (account,) if account else (),
                    )
                ]
        finally:
            conn.close()
    return {
        "available": available,
        "connected": False,
        "decks": [],
        "limit": None,
        "limit_reached": None,
        "deck_screen_open": False,
        "message": message,
        **result,
        "busy": active is not None,
        "active_job": active,
        "pending_transfers": pending,
        "in_game": game_in_progress(db_path),
    }


def _roster_colors(deck, pile_names):
    sections = {"Main": "Deck", "CommandZone": "Commander", "Companions": "Companion"}
    return deck_colors(
        {
            "section": sections.get(pile_names.get(str(p["pile"]))),
            "quantity": c["quantity"],
            "arena_id": c["id"],
        }
        for p in deck.get("piles", [])
        for c in p["entries"]
    )


def _public_roster(report):
    dt.roster_ids(report)
    pile_names = {str(k): v for k, v in (report.get("pile_names") or {}).items()}
    return {
        "connected": True,
        "decks": [
            {
                "id": d["arena_id"],
                "name": d["name"],
                "art_card_id": _roster_art_id(d),
                "format_name": next(
                    (
                        a["value"]
                        for a in d["summary"].get("Attributes", [])
                        if a["key"] == "Format"
                    ),
                    "",
                ),
                "colors": _roster_colors(d, pile_names),
                "main_count": sum(
                    c["quantity"]
                    for p in d.get("piles", [])
                    if p["pile"] == 1
                    for c in p["entries"]
                ),
            }
            for d in report["decks"]
        ],
        "limit": report["limit"],
        "limit_reached": report["limit_reached"],
        "deck_screen_open": report["deck_screen_open"],
        "refreshed_at": dm.now(),
        "message": "Arena decks loaded. Transfers require the Decks screen outside a match.",
    }


def _roster_art_id(deck):
    artwork = deck["summary"].get("DeckArtId")
    if type(artwork) is int and artwork > 0:
        return artwork
    for pile_id in (3, 1):
        for pile in deck.get("piles", []):
            if pile["pile"] == pile_id:
                for card in pile["entries"]:
                    if type(card.get("id")) is int and card["id"] > 0:
                        return card["id"]
    return None


def _card_types():
    from .card_database import CardDatabase

    try:
        return CardDatabase().get_card_type_category
    except Exception:
        return None


def _resolve_names():
    from .card_database import CardDatabase

    try:
        return CardDatabase().get_card_name
    except Exception:
        return None


def _interchangeable_names():
    from .card_database import CardDatabase

    try:
        return CardDatabase().interchangeable_name_index()
    except Exception:
        return {}


def execute(db_path, action, selections, request_id, progress, cancelled=lambda: False):
    """Every job uses a fresh native/account connection and this selected DB.

    Cancellation is checked only between decks: an Arena request already sent
    is always allowed to finish and be verified.
    """
    stopped = False
    started = time.monotonic()
    timings = []

    def mark(label):
        timings.append(f"{label} {time.monotonic() - started:.2f}s")

    if game_in_progress(db_path):
        raise dm.DeckManagerError(
            "Finish your game first. Deck Manager can work with Arena again when it ends."
        )
    conn = dm.library_connection(db_path)
    try:
        if action in ("add", "store") and selections:
            from .deck_collections import validate_destination

            validate_destination(conn, selections[0].get("collection_id"))
        with nb.attach() as bridge:
            mark("attached")
            progress("Reading Arena’s current decks…")
            report = bridge.roster()
            dt.roster_ids(report)
            mark(f"roster of {len(report['decks'])}")
            if action == "reconcile":
                report = dt.reconcile(conn, bridge, report, _resolve_names())
            elif action == "add":
                progress(
                    {
                        "detail": "Preparing the deck with Arena’s importer…",
                        "completed": 0,
                        "total": 3,
                    }
                )
                resolver = _resolve_names()
                report = dt.add_import(
                    conn,
                    bridge,
                    selections[0],
                    request_id,
                    report,
                    resolver,
                    lambda step, detail: progress(
                        {"detail": detail, "completed": step, "total": 3}
                    ),
                    _card_types(),
                    _interchangeable_names(),
                )
            elif action == "backup":
                if report.get("deck_screen_open") is not True:
                    raise dm.DeckManagerError(
                        "Open Arena’s Decks screen outside a match to back up decks."
                    )
                ids = [s["id"] for s in selections] if selections else dt.roster_ids(report)
                if not set(ids) <= set(dt.roster_ids(report)):
                    raise dm.DeckManagerError(
                        "A selected deck is no longer in Arena. Refresh the list."
                    )
                progress(f"Backing up {len(ids)} deck{'s' if len(ids) != 1 else ''}…")
                progress(
                    {"detail": "Reading full deck backups…", "completed": 0, "total": len(ids) * 2}
                )
                archives = []
                for i in range(0, len(ids), BACKUP_BATCH):
                    if cancelled():
                        # Keep the decks already read; they are verified and saved below.
                        stopped, ids = True, ids[:i]
                        break
                    batch = ids[i : i + BACKUP_BATCH]
                    chunk = bridge.archive(batch)
                    if [a["source_snapshot"]["arena_id"] for a in chunk] != batch:
                        raise dm.DeckManagerError("Arena returned a different backup identity.")
                    archives.extend(chunk)
                    read = i + len(batch)
                    progress(
                        {
                            "detail": f"Read {read} of {len(ids)} decks…",
                            "completed": read,
                            "total": len(ids) * 2,
                        }
                    )
                mark(f"read {len(archives)} backups")
                if (
                    len(archives) != len(ids)
                    or [a["source_snapshot"]["arena_id"] for a in archives] != ids
                ):
                    raise dm.DeckManagerError("Arena returned a different backup selection.")
                # Validate every returned archive before publishing the batch.
                from .native_deck_archive import validate_archive

                for archive in archives:
                    validate_archive(archive)
                resolver = _resolve_names()
                for i, archive in enumerate(archives):
                    saved = dt.persist_archive(conn, archive, bridge.account_key, resolver)
                    dt.set_presence(
                        conn,
                        bridge.account_key,
                        archive["source_snapshot"]["arena_id"],
                        saved["id"],
                        "present",
                    )
                    progress(
                        {
                            "detail": f"Verified {i + 1} of {len(ids)} saved backups…",
                            "completed": len(ids) + i + 1,
                            "total": len(ids) * 2,
                        }
                    )
            elif action in ("store", "restore"):
                resolver = _resolve_names()
                for i, selection in enumerate(selections):
                    if i and cancelled():
                        stopped, selections = True, selections[:i]
                        break
                    if game_in_progress(db_path):
                        raise dm.DeckManagerError(
                            "Arena entered a game. Remaining decks were not transferred."
                        )
                    progress(
                        {
                            "detail": (
                                "Moving to collection: "
                                if action == "store"
                                else "Restoring to Arena: "
                            )
                            + f"{i + 1} of {len(selections)}…",
                            "completed": i * 3,
                            "total": len(selections) * 3,
                        }
                    )
                    report = dt.transfer(
                        conn,
                        bridge,
                        action,
                        selection,
                        request_id,
                        report,
                        resolver,
                        lambda step, detail: progress(
                            {
                                "detail": f"{i + 1} of {len(selections)} · {detail}",
                                "completed": i * 3 + step,
                                "total": len(selections) * 3,
                            }
                        ),
                    )
                    progress(
                        {
                            "detail": f"Verified {i + 1} of {len(selections)} transfers…",
                            "completed": (i + 1) * 3,
                            "total": len(selections) * 3,
                        }
                    )
                    # Publish completed progress even if the next deck fails.
                    with _LOCK:
                        _STATUS[_key(db_path)] = {
                            **_public_roster(report),
                            "_account_key": bridge.account_key,
                        }
            elif action != "connect":
                raise dm.DeckManagerError("Unknown native deck action.")
            mark(action)
            current = _public_roster(report)
            current["_account_key"] = bridge.account_key
            current["pending_transfers"] = [
                {"id": r["id"], "action": r["action"], "phase": r["phase"], "deck_id": r["deck_id"]}
                for r in dt.pending(conn, bridge.account_key)
            ]
            with _LOCK:
                _STATUS[_key(db_path)] = current
            if action == "backup":
                count = len(ids)
            else:
                count = len(selections)
            return {"count": count, "action": action, "cancelled": stopped}
    finally:
        conn.close()
        # Durations only; never deck names or account details.
        mark("total")
        print(f"Deck Manager {action} timings (cumulative): " + ", ".join(timings), file=sys.stderr)


def _adapter_reason(text):
    """Frida reports "Error: <reason>" plus a script stack; keep only the reason."""
    reason = re.split(r"\n|\s+at\s+\S+\s+\(", text, maxsplit=1)[0].strip()
    return reason[len("Error:") :].strip() if reason.startswith("Error:") else reason


def _failure_message(exc, action):
    """The user-facing reason a job failed.

    The adapter's own errors (Frida RPC errors) carry messages written in
    arena_decks.js, such as "Open Arena's Decks screen…"; they contain no deck
    data or credentials, so they are shown as-is.
    """
    if isinstance(exc, (dm.DeckManagerError, ValueError, KeyError)):
        return str(exc).strip("'\"")
    if type(exc).__name__ == "RPCException" and _adapter_reason(str(exc)):
        return _adapter_reason(str(exc))
    if action in ("store", "restore", "add"):
        return (
            "Arena could not complete this operation. "
            "Refresh and reconcile before repeating a transfer."
        )
    return (
        "Tapps Tracker lost its connection to Arena. Open Arena on the Decks screen "
        "outside a match, then click Refresh Arena."
    )


def start(db_path, payload):
    global _ACTIVE
    action = payload.get("action")
    if action not in ("connect", "backup", "store", "restore", "reconcile", "add"):
        raise dm.DeckManagerError("Choose a native deck action.")
    request_id = str(uuid.UUID(payload.get("request_id", "")))
    selections = payload.get("decks", [])
    if not isinstance(selections, list) or len(selections) > 2000:
        raise dm.DeckManagerError("Invalid deck selection.")
    clean = []
    if action == "add":
        imported = payload.get("import")
        if not isinstance(imported, dict):
            raise dm.DeckManagerError("An Arena decklist is required.")
        text = imported.get("text")
        name = imported.get("name")
        format_name = imported.get("format_name", "")
        if (
            not isinstance(text, str)
            or not text
            or len(text) > 20000
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(format_name, str)
        ):
            raise dm.DeckManagerError("Invalid deck name, format or bounded Arena decklist.")
        saved_deck_id = imported.get("saved_deck_id")
        if saved_deck_id is not None:
            saved_deck_id = str(uuid.UUID(saved_deck_id))
        dm.parse_import(text, name, format_name)
        if selections:
            raise dm.DeckManagerError("Direct import accepts one decklist, not a deck selection.")
        clean.append(
            {
                "id": str(uuid.uuid5(uuid.UUID(request_id), "text-import-source")),
                "text": text,
                "name": name.strip(),
                "format_name": format_name,
                **({"saved_deck_id": saved_deck_id} if saved_deck_id else {}),
                **(
                    {"collection_id": imported["collection_id"]}
                    if imported.get("collection_id")
                    else {}
                ),
            }
        )
    destination = {}
    if action == "store" and "collection_id" in payload:
        # One destination for the whole move; None means Unsorted.
        if payload["collection_id"] is not None and not isinstance(payload["collection_id"], str):
            raise dm.DeckManagerError("Choose an existing collection or Unsorted.")
        destination = {"collection_id": payload["collection_id"] or None}
    for item in selections:
        if not isinstance(item, dict):
            raise dm.DeckManagerError("Invalid selected deck.")
        row = {"id": str(uuid.UUID(item.get("id", ""))), **destination}
        if item.get("revision"):
            row["revision"] = str(uuid.UUID(item["revision"]))
        clean.append(row)
    if len({d["id"] for d in clean}) != len(clean) or (
        action in ("store", "restore") and not clean
    ):
        raise dm.DeckManagerError("Select at least one distinct deck.")
    if action == "store" and payload.get("confirm") != "MOVE":
        raise dm.DeckManagerError(
            "Confirm moving the selected decks out of Arena after verified backup."
        )
    with _LOCK:
        if request_id in _JOBS:
            existing = _JOBS[request_id]
            if (
                existing["db"] != _key(db_path)
                or existing["action"] != action
                or existing["selections"] != clean
            ):
                raise dm.DeckManagerError("This request ID was already used for another action.")
            return request_id
        if _ACTIVE:
            raise dm.DeckManagerError("Wait for the current Arena deck operation to finish.")
        for key in list(_JOBS):
            if _JOBS[key]["state"] != "running" and time.monotonic() - _JOBS[key]["created"] > 3600:
                del _JOBS[key]
        _ACTIVE = request_id
        _JOBS[request_id] = {
            "db": _key(db_path),
            "action": action,
            "selections": clean,
            "state": "running",
            "detail": "Contacting Arena…",
            "progress": {"completed": 0, "total": None},
            "created": time.monotonic(),
        }

    def progress(message):
        with _LOCK:
            if isinstance(message, dict):
                _JOBS[request_id]["detail"] = message["detail"]
                _JOBS[request_id]["progress"] = {
                    key: message[key] for key in ("completed", "total")
                }
            else:
                _JOBS[request_id]["detail"] = message

    def run():
        global _ACTIVE
        try:
            result = execute(
                db_path,
                action,
                clean,
                request_id,
                progress,
                lambda: _JOBS[request_id].get("cancel", False),
            )
            with _LOCK:
                total = _JOBS[request_id]["progress"]["total"] or 1
                _JOBS[request_id].update(
                    state="done",
                    detail="Completed.",
                    result=result,
                    progress={"completed": total, "total": total},
                )
        except Exception as exc:
            message = _failure_message(exc, action)
            print(f"Deck Manager {action} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            with _LOCK:
                _JOBS[request_id].update(state="error", detail=message)
        finally:
            with _LOCK:
                _ACTIVE = None

    threading.Thread(target=run, name="arena-deck-manager", daemon=True).start()
    return request_id


def handle_get(path, query, db_path):
    if path == "/api/deck-manager/native":
        return 200, status(db_path)
    if path == "/api/deck-manager/native/job":
        with _LOCK:
            job = dict(_JOBS.get(query.get("id", [""])[0], {}))
        if not job or job.pop("db") != _key(db_path):
            return 404, {
                "error": "Deck operation not found. Refresh and reconcile if the tracker restarted."
            }
        job.pop("created", None)
        job.pop("selections", None)
        return 200, job
    return None


def cancel(db_path, job_id):
    """Ask a running backup or bulk transfer to stop after its current deck."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job or job["db"] != _key(db_path):
            raise dm.DeckManagerError("Deck operation not found.")
        if job["state"] == "running" and job["action"] in ("backup", "store", "restore"):
            job["cancel"] = True
            job["detail"] = "Stopping after the current deck…"
        return {"state": job["state"], "cancel": bool(job.get("cancel"))}


def handle_post(path, payload, db_path):
    if path == "/api/deck-manager/native/cancel":
        try:
            if not isinstance(payload, dict) or not isinstance(payload.get("job_id"), str):
                raise dm.DeckManagerError("A deck operation is required.")
            return 200, cancel(db_path, payload["job_id"])
        except dm.DeckManagerError as exc:
            return 404, {"error": str(exc)}
    if path != "/api/deck-manager/native/run":
        return None
    try:
        if not isinstance(payload, dict):
            raise dm.DeckManagerError("Expected a deck action.")
        return 202, {"job_id": start(db_path, payload)}
    except (ValueError, TypeError, AttributeError) as exc:
        return 400, {
            "error": (
                str(exc)
                if isinstance(exc, dm.DeckManagerError)
                else "Invalid deck operation or identity."
            )
        }
