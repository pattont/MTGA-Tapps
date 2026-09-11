"""Backups: one `.tappsbackup` file holding everything the tracker knows.

A backup is a zip with a manifest, a consistent snapshot of the analytics
database (taken with SQLite's online backup API — never a file copy, which is
unsafe on a live WAL database), and the settings files. It exists for two
reasons: a copy of your history somewhere that is not this disk, and carrying
that history to another computer — export at home into a folder a sync client
mirrors (Google Drive, iCloud Drive, Dropbox, OneDrive), restore on the
laptop, play, export there, restore at home.

Restore replaces the database (this pass has no merge). It refuses a snapshot
whose schema is newer than this build, shows what would be lost before doing
anything, writes a safety backup of the current state first, and swaps the
migrated snapshot in only while the tracker is stopped.

The plan: docs/plans/BACKUP_AND_SYNC.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BACKUP_FORMAT_VERSION = 1
BACKUP_SUFFIX = ".tappsbackup"
BACKUP_SUBFOLDER = "Tapps Tracker"
MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "tracker.sqlite3"
SETTINGS_NAME = "settings.json"
DECKFINDER_NAME = "deckfinder_config.json"
OVERLAY_NAME = "overlay.json"
SCRYFALL_CACHE_NAME = "scryfall_id_cache.json"

#: Emptied in the snapshot: a 30-day diagnostics buffer nothing reads back,
#: and the live row, which describes a tracker that is not the one restoring.
TRUNCATED_TABLES = ("raw_game_payloads", "live_status")

#: Where the pre-restore safety copy goes, and its file-name tag.
SAFETY_DIR_NAME = "backups"
SAFETY_TAG = "pre-restore"

#: A live_status heartbeat younger than this means a tracker is writing to
#: the database right now (mirrors live_api.OFFLINE_AFTER_SECONDS).
TRACKER_ACTIVE_WITHIN_SECONDS = 20.0

#: settings.json values that describe *this* computer and never travel with
#: a backup: the backup section itself, the port, the window size.
LOCAL_SETTINGS_SECTIONS = ("backup", "dashboard", "live_log_window")

#: Deck AI keys scrubbed when the export leaves API keys out.
SECRET_KEY_PATTERN = re.compile(r"(API_KEY|_KEY|TOKEN|SECRET)$", re.IGNORECASE)


class BackupError(Exception):
    """A backup or restore that cannot proceed; `code` tells the UI why."""

    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


# --- settings section -------------------------------------------------------


def _settings_path() -> Path:
    from .settings import SETTINGS_PATH

    return SETTINGS_PATH


def read_settings_document(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path) if path is not None else _settings_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def write_settings_document(document: Dict[str, Any], path: Optional[Path] = None) -> Path:
    path = Path(path) if path is not None else _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def update_settings_section(name: str, values: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    """Merge `values` into one top-level section of settings.json, leaving
    every other section as it is. Returns the section."""
    document = read_settings_document(path)
    section = document.get(name)
    if not isinstance(section, dict):
        section = {}
    section.update(values)
    document[name] = section
    write_settings_document(document, path)
    return section


def backup_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """The "backup" section: folder, install id, last backup, all optional."""
    section = read_settings_document(path).get("backup")
    return dict(section) if isinstance(section, dict) else {}


def install_id(path: Optional[Path] = None) -> str:
    """A stable id for this data directory, minted on first use, so a backup
    can be recognised as this computer's own."""
    section = backup_settings(path)
    value = section.get("install_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    value = uuid.uuid4().hex[:12]
    try:
        update_settings_section("backup", {"install_id": value}, path)
    except OSError:
        pass
    return value


def machine_name() -> str:
    """This computer's name as it appears in file names: letters, digits,
    dashes."""
    raw = platform.node().split(".")[0] if platform.node() else ""
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-")
    return cleaned or "computer"


# --- synced-folder detection -------------------------------------------------


def detect_sync_folders(
    *,
    home: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    system: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Cloud-synced folders present on this machine, as {name, path}.

    Well-known locations only, checked for existence — nothing talks to any
    service. A backup folder inside one of these is what makes a backup
    appear on the next computer with no code of ours involved.
    """
    home = Path(home) if home is not None else Path.home()
    env = dict(os.environ if env is None else env)
    system = system or platform.system()
    candidates: List[Tuple[str, Path]] = []

    if system == "Darwin":
        cloud = home / "Library" / "CloudStorage"
        if cloud.is_dir():
            for entry in sorted(cloud.iterdir()):
                if entry.name.startswith("GoogleDrive-"):
                    for sub in ("My Drive", "Mon Drive", "Mi unidad", "Meine Ablage"):
                        if (entry / sub).is_dir():
                            candidates.append(("Google Drive", entry / sub))
                            break
                    else:
                        candidates.append(("Google Drive", entry))
                elif entry.name.startswith("OneDrive"):
                    candidates.append(("OneDrive", entry))
                elif entry.name.startswith("Dropbox"):
                    candidates.append(("Dropbox", entry))
        candidates.append(("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"))
    elif system == "Windows":
        for letter in "GHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:/My Drive")
            if drive.is_dir():
                candidates.append(("Google Drive", drive))
                break
        candidates.append(("Google Drive", home / "My Drive"))
        for key in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
            value = env.get(key)
            if value:
                candidates.append(("OneDrive", Path(value)))
        candidates.append(("OneDrive", home / "OneDrive"))
    else:
        candidates.append(("Google Drive", home / "google-drive"))

    candidates.append(("Dropbox", home / "Dropbox"))
    if system != "Windows":
        candidates.append(("OneDrive", home / "OneDrive"))

    found: List[Dict[str, str]] = []
    seen: set = set()
    for name, path in candidates:
        try:
            resolved = path.expanduser()
            if not resolved.is_dir():
                continue
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        found.append({"name": name, "path": str(resolved / BACKUP_SUBFOLDER)})
    return found


# --- snapshot and manifest ------------------------------------------------------


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def database_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Facts about a database the manifest and the preview need."""

    def scalar(sql: str, default: Any = None) -> Any:
        try:
            row = conn.execute(sql).fetchone()
        except sqlite3.Error:
            return default
        return row[0] if row and row[0] is not None else default

    try:
        game_ids = [str(r[0]) for r in conn.execute("SELECT id FROM games ORDER BY started_at, id")]
    except sqlite3.Error:
        game_ids = []
    return {
        "schema_version": int(scalar("SELECT MAX(version) FROM schema_migrations", 0) or 0),
        "games": len(game_ids),
        "game_ids": game_ids,
        "newest_game_at": scalar("SELECT MAX(started_at) FROM games"),
        "oldest_game_at": scalar("SELECT MIN(started_at) FROM games"),
        "sessions": int(scalar("SELECT COUNT(*) FROM tracker_sessions", 0) or 0),
    }


def snapshot_database(db_path: Path, dest_path: Path) -> Dict[str, Any]:
    """Write a consistent copy of `db_path` to `dest_path` with the
    diagnostics buffer and the live row emptied, and return its summary."""
    db_path = Path(db_path)
    dest_path = Path(dest_path)
    if not db_path.is_file():
        raise BackupError(f"No database at {db_path}", "no-database")
    if dest_path.exists():
        dest_path.unlink()
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        source.execute("PRAGMA busy_timeout = 30000")
        dest = sqlite3.connect(dest_path)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    dest = sqlite3.connect(dest_path)
    try:
        dest.execute("PRAGMA journal_mode = DELETE")
        for table in TRUNCATED_TABLES:
            try:
                dest.execute(f"DELETE FROM {table}")
            except sqlite3.Error:
                pass
        dest.commit()
        dest.execute("VACUUM")
        summary = database_summary(dest)
    finally:
        dest.close()
    return summary


def _scrub_secrets(document: Dict[str, Any]) -> Dict[str, Any]:
    scrubbed = json.loads(json.dumps(document))
    deck_ai = scrubbed.get("deck_ai")
    if isinstance(deck_ai, dict):
        for key in list(deck_ai):
            if SECRET_KEY_PATTERN.search(str(key)):
                deck_ai.pop(key, None)
    return scrubbed


def _deckfinder_config_path() -> Optional[Path]:
    try:
        from .deckfinder_api import _writable_config_path

        return _writable_config_path()
    except Exception:
        return None


def overlay_settings_path(*, home: Optional[Path] = None, env: Optional[Dict[str, str]] = None, system: Optional[str] = None) -> Path:
    """Where the overlay (a Tauri app) keeps its preferences."""
    home = Path(home) if home is not None else Path.home()
    env = dict(os.environ if env is None else env)
    system = system or platform.system()
    identifier = "com.tappstracker.overlay"
    if system == "Darwin":
        base = home / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(env.get("APPDATA") or (home / "AppData" / "Roaming"))
    else:
        base = Path(env.get("XDG_DATA_HOME") or (home / ".local" / "share"))
    return base / identifier / OVERLAY_NAME


def backup_file_name(machine: str, when: datetime, tag: Optional[str] = None) -> str:
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S") if when.tzinfo else when.strftime("%Y%m%d-%H%M%S")
    parts = ["TappsTracker", machine, stamp]
    if tag:
        parts.append(tag)
    return "-".join(parts) + BACKUP_SUFFIX


def export_backup(
    db_path: Path,
    folder: Path,
    *,
    include_keys: bool = True,
    settings_path: Optional[Path] = None,
    deckfinder_path: Optional[Path] = None,
    overlay_path: Optional[Path] = None,
    scryfall_cache_path: Optional[Path] = None,
    machine: Optional[str] = None,
    tag: Optional[str] = None,
    now: Optional[datetime] = None,
    progress: Optional[Callable[[str], None]] = None,
    record: bool = True,
) -> Dict[str, Any]:
    """Write a backup into `folder` and return its manifest plus `path` and
    `size`. `record=True` notes it as the last backup in settings.json."""
    db_path = Path(db_path)
    folder = Path(folder).expanduser()
    settings_path = Path(settings_path) if settings_path is not None else _settings_path()
    when = now or _now()
    machine = machine or machine_name()
    report = progress or (lambda _msg: None)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / backup_file_name(machine, when, tag)
    # Never overwrite: a second export in the same second (or an undo file
    # that is itself about to be restored) gets its own name.
    counter = 2
    while target.exists():
        target = folder / backup_file_name(machine, when, f"{tag}-{counter}" if tag else str(counter))
        counter += 1

    with tempfile.TemporaryDirectory(prefix="tapps-backup-") as tmp:
        report("Taking a snapshot of the database")
        snapshot = Path(tmp) / DATABASE_NAME
        summary = snapshot_database(db_path, snapshot)

        files: Dict[str, bytes] = {}
        settings_document = read_settings_document(settings_path)
        if settings_document:
            for section in LOCAL_SETTINGS_SECTIONS:
                settings_document.pop(section, None)
            if not include_keys:
                settings_document = _scrub_secrets(settings_document)
            files[SETTINGS_NAME] = (json.dumps(settings_document, indent=2) + "\n").encode("utf-8")
        deckfinder_path = deckfinder_path if deckfinder_path is not None else _deckfinder_config_path()
        for name, path in (
            (DECKFINDER_NAME, deckfinder_path),
            (OVERLAY_NAME, overlay_path if overlay_path is not None else overlay_settings_path()),
            (SCRYFALL_CACHE_NAME, scryfall_cache_path if scryfall_cache_path is not None else db_path.parent / SCRYFALL_CACHE_NAME),
        ):
            try:
                if path is not None and Path(path).is_file():
                    files[name] = Path(path).read_bytes()
            except OSError:
                pass

        from . import __version__ as app_version

        manifest: Dict[str, Any] = {
            "format": BACKUP_FORMAT_VERSION,
            "app_version": str(app_version),
            "schema_version": summary["schema_version"],
            "machine": machine,
            "install_id": install_id(settings_path),
            "exported_at": _iso(when),
            "games": summary["games"],
            "sessions": summary["sessions"],
            "newest_game_at": summary["newest_game_at"],
            "oldest_game_at": summary["oldest_game_at"],
            "includes": sorted([DATABASE_NAME, *files]),
            "include_keys": bool(include_keys),
            "tag": tag,
            "game_ids": summary["game_ids"],
        }

        report("Compressing")
        partial = target.with_suffix(target.suffix + ".part")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            archive.write(snapshot, DATABASE_NAME)
            for name, blob in files.items():
                archive.writestr(name, blob)
        os.replace(partial, target)

    result = dict(manifest)
    result.pop("game_ids", None)
    result["path"] = str(target)
    result["size"] = target.stat().st_size
    if record and not tag:
        try:
            update_settings_section(
                "backup",
                {"last_backup": {"at": manifest["exported_at"], "path": str(target), "games": manifest["games"], "machine": machine}},
                settings_path,
            )
        except OSError:
            pass
    report("Done")
    return result


# --- reading backups ------------------------------------------------------------


def read_manifest(path: Path) -> Dict[str, Any]:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if MANIFEST_NAME not in names or DATABASE_NAME not in names:
                raise BackupError(f"{path.name} is not a Tapps Tracker backup", "not-a-backup")
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except zipfile.BadZipFile:
        raise BackupError(f"{path.name} is not a Tapps Tracker backup", "not-a-backup")
    except OSError as exc:
        raise BackupError(f"Could not read {path.name}: {exc}", "unreadable")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("format"), int):
        raise BackupError(f"{path.name} has no readable manifest", "not-a-backup")
    return manifest


def _public(manifest: Dict[str, Any]) -> Dict[str, Any]:
    public = dict(manifest)
    public.pop("game_ids", None)
    return public


def list_backups(folder: Optional[Path]) -> List[Dict[str, Any]]:
    """Backups in `folder`, newest first; unreadable files are listed with
    an `error` so the UI can say so instead of hiding them."""
    if not folder:
        return []
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for entry in folder.iterdir():
        if entry.suffix != BACKUP_SUFFIX or not entry.is_file():
            continue
        row: Dict[str, Any] = {"path": str(entry), "name": entry.name}
        try:
            row["size"] = entry.stat().st_size
            row.update(_public(read_manifest(entry)))
        except BackupError as exc:
            row["error"] = str(exc)
        except OSError:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r.get("exported_at") or "", r["name"]), reverse=True)
    return rows


def local_summary(db_path: Path) -> Dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.is_file():
        return {"schema_version": 0, "games": 0, "game_ids": [], "newest_game_at": None, "oldest_game_at": None, "sessions": 0}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
    try:
        return database_summary(conn)
    finally:
        conn.close()


_supported_schema: Optional[int] = None


def supported_schema_version() -> int:
    """The newest migration this build applies (found by building an empty
    database in memory once; the migrations' progress lines are muted)."""
    global _supported_schema
    if _supported_schema is not None:
        return _supported_schema
    import contextlib
    import io

    from .analytics import AnalyticsStore

    scratch = sqlite3.connect(":memory:")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            AnalyticsStore.ensure_schema(scratch)
        row = scratch.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        _supported_schema = int(row[0] or 0) if row else 0
    finally:
        scratch.close()
    return _supported_schema


def inspect_backup(path: Path, db_path: Path, *, settings_path: Optional[Path] = None) -> Dict[str, Any]:
    """Everything the restore preview shows: the backup's facts, this
    computer's, and what a restore would add and drop."""
    path = Path(path).expanduser()
    manifest = read_manifest(path)
    if int(manifest.get("format") or 0) > BACKUP_FORMAT_VERSION:
        raise BackupError("This backup was made by a newer tracker; update the tracker first", "newer-format")
    local = local_summary(db_path)
    theirs = set(manifest.get("game_ids") or [])
    mine = set(local["game_ids"])
    adds = len(theirs - mine)
    drops = len(mine - theirs)
    supported = supported_schema_version()
    schema_ok = int(manifest.get("schema_version") or 0) <= supported
    if not schema_ok:
        verdict = "newer-schema"
    elif not mine:
        verdict = "fresh"
    elif drops == 0 and adds == 0:
        verdict = "same"
    elif drops == 0:
        verdict = "newer"
    elif adds == 0:
        verdict = "older"
    else:
        verdict = "diverged"
    return {
        "path": str(path),
        "manifest": _public(manifest),
        "local": {k: v for k, v in local.items() if k != "game_ids"},
        "adds": adds,
        "drops": drops,
        "same_install": manifest.get("install_id") == install_id(settings_path),
        "schema_ok": schema_ok,
        "supported_schema_version": supported,
        "verdict": verdict,
        "requires_confirm": drops > 0,
    }


# --- restore ---------------------------------------------------------------------


def tracker_active(db_path: Path, *, now: Optional[datetime] = None) -> bool:
    """True when a tracker wrote its heartbeat to this database recently."""
    db_path = Path(db_path)
    if not db_path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute("SELECT updated_at FROM live_status WHERE id = 1").fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    if not row or not row[0]:
        return False
    try:
        stamp = datetime.fromisoformat(str(row[0]))
    except ValueError:
        return False
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    current = (now or datetime.now()).replace(tzinfo=None)
    return current - stamp < timedelta(seconds=TRACKER_ACTIVE_WITHIN_SECONDS)


def _prune_safety_backups(folder: Path, keep: int = 2) -> None:
    files = sorted(
        (p for p in folder.glob(f"*-{SAFETY_TAG}*{BACKUP_SUFFIX}") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def _remove_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = db_path.with_name(db_path.name + suffix)
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            pass


def _merge_settings(local: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """The backup's settings, with this computer's own sections kept."""
    merged = json.loads(json.dumps(incoming)) if incoming else {}
    for section in LOCAL_SETTINGS_SECTIONS:
        if section in local:
            merged[section] = local[section]
        else:
            merged.pop(section, None)
    return merged


def restore_backup(
    path: Path,
    db_path: Path,
    *,
    confirm: Optional[str] = None,
    tracker_control: Any = None,
    settings_path: Optional[Path] = None,
    deckfinder_path: Optional[Path] = None,
    overlay_path: Optional[Path] = None,
    safety_dir: Optional[Path] = None,
    before_swap: Optional[Callable[[], None]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Replace this computer's database and settings with the backup's.

    `tracker_control` (the UnifiedLauncher) stops the tracker for the swap
    and starts it again after; without one, a tracker that is writing to
    the database makes the restore refuse. `before_swap` lets the dashboard
    close its kept-open connections. A safety backup of the current state
    is written first, always; `undo` in the result is its path.
    """
    path = Path(path).expanduser()
    db_path = Path(db_path)
    settings_path = Path(settings_path) if settings_path is not None else _settings_path()
    report = progress or (lambda _msg: None)

    preview = inspect_backup(path, db_path, settings_path=settings_path)
    if not preview["schema_ok"]:
        raise BackupError(
            "This backup was made by a newer tracker (database schema "
            f"{preview['manifest'].get('schema_version')} vs {preview['supported_schema_version']} here); "
            "update the tracker first",
            "newer-schema",
        )
    if preview["requires_confirm"] and confirm != "REPLACE":
        raise BackupError(
            f"Restoring would drop {preview['drops']} game(s) recorded here that the backup does not have; "
            'confirm with "REPLACE" to go ahead',
            "confirm-required",
        )

    was_running = False
    if tracker_control is not None:
        was_running = bool(getattr(tracker_control, "tracker_is_running", False))
        report("Stopping the tracker")
        tracker_control.stop_tracker()
        if getattr(tracker_control, "tracker_is_running", False):
            raise BackupError("The tracker did not stop in time; try again in a moment", "tracker-running")
    elif tracker_active(db_path):
        raise BackupError("The tracker is running and writing to this database; stop it first", "tracker-running")

    try:
        safety_folder = Path(safety_dir) if safety_dir is not None else db_path.parent / SAFETY_DIR_NAME
        undo_path: Optional[str] = None
        if db_path.is_file():
            report("Saving a copy of the current state")
            safety = export_backup(
                db_path,
                safety_folder,
                settings_path=settings_path,
                deckfinder_path=deckfinder_path,
                overlay_path=overlay_path,
                tag=SAFETY_TAG,
                record=False,
            )
            undo_path = safety["path"]
            _prune_safety_backups(safety_folder)

        report("Unpacking the backup")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        staged = db_path.with_name(db_path.name + ".restoring")
        files: Dict[str, bytes] = {}
        with zipfile.ZipFile(path) as archive:
            with archive.open(DATABASE_NAME) as src, open(staged, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            for name in (SETTINGS_NAME, DECKFINDER_NAME, OVERLAY_NAME, SCRYFALL_CACHE_NAME):
                if name in archive.namelist():
                    files[name] = archive.read(name)

        report("Bringing the database up to date")
        from .analytics import AnalyticsStore

        store = AnalyticsStore(staged)
        try:
            store.connect()
        finally:
            store.close()
        _remove_sidecars(staged)

        report("Swapping the database in")
        if before_swap is not None:
            before_swap()
        _remove_sidecars(db_path)
        os.replace(staged, db_path)

        report("Restoring settings")
        if SETTINGS_NAME in files:
            try:
                incoming = json.loads(files[SETTINGS_NAME].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                incoming = {}
            if isinstance(incoming, dict):
                write_settings_document(_merge_settings(read_settings_document(settings_path), incoming), settings_path)
        deckfinder_path = deckfinder_path if deckfinder_path is not None else _deckfinder_config_path()
        overlay_path = overlay_path if overlay_path is not None else overlay_settings_path()
        for name, target in (
            (DECKFINDER_NAME, deckfinder_path),
            (OVERLAY_NAME, overlay_path),
            (SCRYFALL_CACHE_NAME, db_path.parent / SCRYFALL_CACHE_NAME),
        ):
            if name in files and target is not None:
                try:
                    Path(target).parent.mkdir(parents=True, exist_ok=True)
                    Path(target).write_bytes(files[name])
                except OSError:
                    pass
        try:
            from . import deck_llm

            deck_llm._settings_cache = None
            deck_llm._settings_mtime = None
        except Exception:
            pass
    finally:
        if tracker_control is not None and was_running:
            report("Starting the tracker")
            tracker_control.start_tracker(background=True)

    restored = local_summary(db_path)
    result = {
        "ok": True,
        "restored_from": str(path),
        "manifest": preview["manifest"],
        "games": restored["games"],
        "newest_game_at": restored["newest_game_at"],
        "undo": undo_path,
        "tracker_restarted": bool(tracker_control is not None and was_running),
    }
    try:
        update_settings_section(
            "backup",
            {"last_restore": {"at": _iso(_now()), "path": str(path), "games": restored["games"], "undo": undo_path}},
            settings_path,
        )
    except OSError:
        pass
    report("Done")
    return result


# --- what the Settings card shows -------------------------------------------------


def backup_status(db_path: Path, *, settings_path: Optional[Path] = None) -> Dict[str, Any]:
    section = backup_settings(settings_path)
    folder = section.get("folder") if isinstance(section.get("folder"), str) else None
    detected = detect_sync_folders()
    local = local_summary(db_path)
    return {
        "folder": folder,
        "detected_folders": detected,
        "default_folder": detected[0]["path"] if detected else str(Path(db_path).parent / SAFETY_DIR_NAME),
        "machine": machine_name(),
        "install_id": install_id(settings_path),
        "last_backup": section.get("last_backup"),
        "last_restore": section.get("last_restore"),
        "backups": list_backups(folder),
        "local": {k: v for k, v in local.items() if k != "game_ids"},
        "tracker_active": tracker_active(db_path),
    }


def set_backup_folder(folder: Optional[str], *, settings_path: Optional[Path] = None) -> Optional[str]:
    value = (folder or "").strip()
    if value:
        resolved = Path(value).expanduser()
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupError(f"Cannot use {resolved}: {exc}", "bad-folder")
        value = str(resolved)
    update_settings_section("backup", {"folder": value or None}, settings_path)
    return value or None


# --- command line ------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    from .dashboard import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(prog="python -m mtga_tracker.backup", description="Back up and restore the tracker.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export", help="Write a .tappsbackup into a folder.")
    p_export.add_argument("folder", type=Path, nargs="?", help="Destination folder (default: the configured backup folder).")
    p_export.add_argument("--no-keys", action="store_true", help="Leave API keys out of the settings copy.")
    p_inspect = sub.add_parser("inspect", help="Describe a backup and what restoring it would do here.")
    p_inspect.add_argument("path", type=Path)
    p_restore = sub.add_parser("restore", help="Replace this computer's database and settings with a backup's.")
    p_restore.add_argument("path", type=Path)
    p_restore.add_argument("--confirm", default=None, help='Pass REPLACE to drop games recorded here that the backup lacks.')
    sub.add_parser("list", help="List the backups in the configured folder.")
    sub.add_parser("folders", help="Show the synced folders found on this computer.")
    args = parser.parse_args(argv)

    try:
        if args.command == "export":
            folder = args.folder or backup_settings().get("folder")
            if not folder:
                parser.error("no folder given and none configured in settings.json")
            result = export_backup(args.db, Path(folder), include_keys=not args.no_keys, progress=print)
            print(f"{result['path']}  ({result['size'] / 1e6:.1f} MB, {result['games']} games)")
        elif args.command == "inspect":
            print(json.dumps(inspect_backup(args.path, args.db), indent=2))
        elif args.command == "restore":
            result = restore_backup(args.path, args.db, confirm=args.confirm, progress=print)
            print(f"Restored {result['games']} games. Undo: {result['undo']}")
        elif args.command == "list":
            for row in list_backups(backup_settings().get("folder")):
                print(f"{row.get('exported_at', '?')}  {row.get('machine', '?'):<16} {row.get('games', '?'):>5} games  {row['name']}")
        elif args.command == "folders":
            for row in detect_sync_folders():
                print(f"{row['name']:<14} {row['path']}")
    except BackupError as exc:
        print(f"{exc} [{exc.code}]", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
