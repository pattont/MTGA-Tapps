"""Dashboard endpoints for the MTGA collection exporter.

A background job scans MTGA's memory (via ``collection_export``), the raw
``{arena_id: quantity}`` result is cached briefly, and each format is written
from that cache — so a second export within the cache window skips the scan
(and, on macOS, the admin prompt). The dashboard only serves localhost, so
the produced files are written under DATA_DIR/exports and served back by name.

Endpoints:
- POST /api/collection/export  {format, refresh?} -> {job}
- GET  /api/collection/export?job=<id>            -> job status
- GET  /api/collection/download?file=<name>       -> the exported file
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .paths import DATA_DIR

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

#: The last raw scan result, reused across formats and the ~5-minute window.
_SCAN_CACHE: Dict[str, Any] = {"collection": None, "at": 0.0}
_SCAN_CACHE_LOCK = threading.Lock()
_SCAN_CACHE_TTL = 300.0  # seconds

_VALID_FORMATS = ("json", "csv", "txt")
_JOB_TTL = 900.0


def _exports_dir() -> Path:
    out = DATA_DIR / "exports"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _prune_jobs(now: float) -> None:
    for job_id in [jid for jid, job in _JOBS.items() if job["created"] < now - _JOB_TTL]:
        _JOBS.pop(job_id, None)


def _set(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(fields)


def _cached_collection() -> Optional[Dict[int, int]]:
    with _SCAN_CACHE_LOCK:
        collection = _SCAN_CACHE["collection"]
        if collection is not None and (time.monotonic() - _SCAN_CACHE["at"]) < _SCAN_CACHE_TTL:
            return dict(collection)
    return None


def _store_collection(collection: Dict[int, int]) -> None:
    with _SCAN_CACHE_LOCK:
        _SCAN_CACHE["collection"] = dict(collection)
        _SCAN_CACHE["at"] = time.monotonic()


def start_export(db_path: Optional[Path], fmt: str, *, refresh: bool) -> str:
    """Kick off an export job; returns its id."""
    now = time.time()
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _prune_jobs(now)
        _JOBS[job_id] = {
            "created": now,
            "state": "running",
            "detail": "Starting…",
            "format": fmt,
            "file": None,
            "unique": None,
            "total": None,
            "error_code": None,
        }

    def progress(message: str) -> None:
        _set(job_id, detail=message)

    def run() -> None:
        try:
            _run_export(job_id, db_path, fmt, refresh=refresh, progress=progress)
        except _ExportError as exc:
            _set(job_id, state="error", detail=exc.message, error_code=exc.code)
        except Exception as exc:  # noqa: BLE001 - surface, never crash the server
            _set(job_id, state="error", detail=str(exc), error_code="scan_failed")

    threading.Thread(target=run, name=f"collection-{job_id[:8]}", daemon=True).start()
    return job_id


class _ExportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _run_export(
    job_id: str,
    db_path: Optional[Path],
    fmt: str,
    *,
    refresh: bool,
    progress,
) -> None:
    from . import collection_export as ce

    collection = None if refresh else _cached_collection()
    if collection is None:
        collection = _scan(db_path, progress)
        _store_collection(collection)
    else:
        progress("Using the last scan…")

    progress(f"Mapping {len(collection)} cards…")
    metadata = _load_metadata(db_path)
    entries = ce.aggregate(collection, metadata)
    if not entries:
        raise _ExportError(
            "no_collection",
            "The scan returned no cards this tool could name — try again with "
            "Arena's Decks tab open.",
        )

    writer, ext = ce.WRITERS[fmt]
    out_dir = _exports_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"mtga_collection_{stamp}.{ext}"
    if fmt == "json":
        writer(entries, out_path, database_size=len(metadata), now=datetime.now().isoformat())
    else:
        writer(entries, out_path)

    total = sum(e.count for e in entries)
    _set(
        job_id,
        state="done",
        detail=f"Exported {len(entries):,} unique cards ({total:,} total).",
        file=out_path.name,
        unique=len(entries),
        total=total,
    )


def _scan(db_path: Optional[Path], progress) -> Dict[int, int]:
    """Run the scan — directly on Windows, via an elevated helper on macOS."""
    from . import collection_export as ce

    if sys.platform == "darwin":
        return _scan_macos_elevated(db_path, progress)

    import sqlite3

    progress("Attaching to MTG Arena…")
    conn = _readonly_conn(db_path)
    try:
        return ce.scan_collection(conn, progress=progress)
    except ce.ProcessNotFound:
        raise _ExportError("arena_not_running", _ERROR_TEXT["arena_not_running"])
    except PermissionError:
        raise _ExportError("permission_denied", _ERROR_TEXT["permission_denied"])
    except ce.CollectionNotFound:
        raise _ExportError("no_collection", _ERROR_TEXT["no_collection"])
    except sqlite3.Error as exc:
        raise _ExportError("scan_failed", f"Database error: {exc}")
    finally:
        conn.close()


def _scan_macos_elevated(db_path: Optional[Path], progress) -> Dict[int, int]:
    """Run the scanner as an admin helper via osascript, read its JSON output.

    macOS blocks reading another process's memory without elevation, so the
    scan can't run inside the (unprivileged) dashboard. osascript shows the
    native password dialog and runs only the scanner elevated; the raw result
    lands in a temp file the dashboard then owns.
    """
    resolved_db = str(_resolve_db_path(db_path))
    out_fd, out_name = tempfile.mkstemp(prefix="mtga-collection-", suffix=".json")
    os.close(out_fd)
    python = sys.executable or "python3"
    inner = (
        f"{_sh_quote(python)} -m mtga_tracker.collection_export "
        f"--scan-json {_sh_quote(resolved_db)} {_sh_quote(out_name)}"
    )
    env_prefix = ""
    src_root = _module_src_root()
    if src_root:
        env_prefix = f"PYTHONPATH={_sh_quote(src_root)} "
    script = (
        'do shell script "' + (env_prefix + inner).replace("\\", "\\\\").replace('"', '\\"')
        + '" with administrator privileges'
    )
    progress_name = out_name + ".progress"
    try:
        open(progress_name, "w").close()
    except OSError:
        pass

    progress("Waiting for the macOS administrator prompt…")
    try:
        proc = subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        _cleanup(out_name)
        _cleanup(progress_name)
        raise _ExportError("scan_failed", "Couldn't launch the elevated scan.")

    # Poll the sidecar the helper writes so the UI shows real progress while
    # the (blocking) elevated command runs. A full deep scan of a large
    # collection can genuinely take several minutes.
    deadline = time.monotonic() + 900.0
    last = None
    while proc.poll() is None:
        line = _read_text(progress_name)
        if line and line != last:
            last = line
            progress(line)
        if time.monotonic() > deadline:
            proc.kill()
            _cleanup(out_name)
            _cleanup(progress_name)
            raise _ExportError("scan_failed", "The scan timed out.")
        time.sleep(0.3)
    stdout, stderr = proc.communicate()

    if proc.returncode != 0:
        _cleanup(out_name)
        _cleanup(progress_name)
        combined = f"{stdout}\n{stderr}".lower()
        if "-128" in combined or "user canceled" in combined or "cancelled" in combined:
            raise _ExportError("permission_denied", _ERROR_TEXT["permission_denied"])
        code = _parse_helper_error(stderr)
        raise _ExportError(code, _ERROR_TEXT.get(code, "The scan failed."))

    progress("Reading the scan result…")
    try:
        with open(out_name, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        _cleanup(out_name)
        _cleanup(progress_name)
        raise _ExportError("scan_failed", "The scan produced no readable output.")
    _cleanup(out_name)
    _cleanup(progress_name)
    return {int(k): int(v) for k, v in raw.items()}


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _parse_helper_error(stderr: str) -> str:
    for line in (stderr or "").splitlines():
        if line.startswith("ERROR "):
            token = line.split()[1] if len(line.split()) > 1 else "scan_failed"
            return token
    return "scan_failed"


_ERROR_TEXT = {
    "arena_not_running": "MTG Arena isn't running — launch it and open the Decks tab, then try again.",
    "permission_denied": "The administrator prompt was cancelled — the scan can't run without it.",
    "no_collection": "Couldn't find your collection in Arena's memory — open the Decks tab in Arena so it loads, then try again.",
    "db_unreadable": "Couldn't read the tracker database for the scan.",
    "scan_failed": "The scan failed. Make sure Arena is running with the Decks tab open, then try again.",
}


def _load_metadata(db_path: Optional[Path]) -> Dict[int, Tuple[str, str, str]]:
    """arena_id -> (name, set, collector) from Arena's card DB, plus a
    display-name fallback from the tracker's own recorded cards."""
    from .card_database import CardDatabase

    metadata: Dict[int, Tuple[str, str, str]] = {}
    try:
        metadata.update(CardDatabase().export_index_by_arena_id())
    except Exception:
        pass

    # Backfill names for ids the Arena DB missed but the tracker has seen.
    import sqlite3

    try:
        conn = _readonly_conn(db_path)
    except sqlite3.Error:
        return metadata
    try:
        for arena_id, name in conn.execute(
            "SELECT DISTINCT arena_id, display_name FROM game_deck_cards WHERE arena_id IS NOT NULL"
        ):
            try:
                aid = int(arena_id)
            except (TypeError, ValueError):
                continue
            if aid not in metadata and name:
                metadata[aid] = (str(name), "", "")
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return metadata


def _resolve_db_path(db_path: Optional[Path]) -> Path:
    if db_path is not None:
        return Path(db_path)
    return DATA_DIR / "mtga_tracker.sqlite3"


def _readonly_conn(db_path: Optional[Path]):
    import sqlite3

    resolved = _resolve_db_path(db_path)
    return sqlite3.connect(f"file:{Path(resolved).as_posix()}?mode=ro", uri=True)


def _module_src_root() -> Optional[str]:
    """The directory that must be on PYTHONPATH for the helper to import the
    package when running from source (a no-op inside a frozen build)."""
    if getattr(sys, "frozen", False):
        return None
    here = Path(__file__).resolve().parent.parent
    return str(here)


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --- HTTP surface -----------------------------------------------------------


def handle_post(
    path: str, payload: Dict[str, Any], db_path: Optional[Path]
) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/collection/export":
        return None
    fmt = str(payload.get("format") or "").strip().lower()
    if fmt not in _VALID_FORMATS:
        return 400, {"error": f"Unknown format: {fmt!r}"}
    job_id = start_export(db_path, fmt, refresh=bool(payload.get("refresh")))
    return 202, {"job": job_id, **_job_payload(job_id)}


def handle_get(
    path: str, query: Dict[str, List[str]], db_path: Optional[Path]
) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path == "/api/collection/export":
        job_id = (query.get("job") or [""])[0]
        payload = _job_payload(job_id)
        if payload is None:
            return 404, {"error": "unknown job"}
        return 200, payload
    if path == "/api/collection/download":
        return _download(query)
    return None


def _job_payload(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return {
            "state": job["state"],
            "detail": job["detail"],
            "format": job["format"],
            "file": job["file"],
            "unique": job["unique"],
            "total": job["total"],
            "error_code": job["error_code"],
        }


def _download(query: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
    """Validate a filename against the exports dir (no traversal) and return
    its bytes via a sentinel the dashboard turns into a file response."""
    name = (query.get("file") or [""])[0]
    out_dir = _exports_dir()
    target = (out_dir / name).resolve()
    if target.parent != out_dir.resolve() or not target.is_file():
        return 404, {"error": "file not found"}
    return 200, {"_file": str(target)}
