"""Dashboard endpoints for backups (the Settings page's Backup card).

- GET  /api/backup                 -> folder, detected synced folders, last
                                      backup/restore, the backups in the
                                      folder, this database's facts
- POST /api/backup/export          {folder?, include_keys?} -> the manifest
- POST /api/backup/inspect         {path} -> the restore preview
- POST /api/backup/restore         {path, confirm?} -> the result
- POST /api/settings/backup        {folder} -> the folder as stored

A restore stops the tracker through the launcher the dashboard was given
(`tracker_control`); a dashboard running on its own refuses while a tracker
is writing to the database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import backup

Response = Tuple[int, Dict[str, Any]]


def handle_get(path: str, db_path: Path) -> Optional[Response]:
    if path != "/api/backup":
        return None
    try:
        return 200, backup.backup_status(db_path)
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


def _error(exc: backup.BackupError) -> Response:
    status = {
        "confirm-required": 409,
        "tracker-running": 409,
        "newer-schema": 409,
        "newer-format": 409,
        "not-a-backup": 400,
        "bad-folder": 400,
        "no-database": 404,
        "unreadable": 404,
    }.get(exc.code, 400)
    return status, {"error": str(exc), "code": exc.code}


def handle_post(
    path: str,
    payload: Dict[str, Any],
    db_path: Path,
    *,
    tracker_control: Any = None,
    before_swap: Any = None,
) -> Optional[Response]:
    try:
        if path == "/api/settings/backup":
            folder = backup.set_backup_folder(payload.get("folder"))
            return 200, {"folder": folder}
        if path == "/api/backup/export":
            folder = payload.get("folder") or backup.backup_settings().get("folder")
            if not folder:
                return 400, {"error": "Choose a backup folder first", "code": "no-folder"}
            include_keys = payload.get("include_keys", True)
            result = backup.export_backup(db_path, Path(str(folder)), include_keys=bool(include_keys))
            return 200, {"backup": result, "status": backup.backup_status(db_path)}
        if path == "/api/backup/inspect":
            target = payload.get("path")
            if not target:
                return 400, {"error": "No backup file given", "code": "no-path"}
            return 200, backup.inspect_backup(Path(str(target)), db_path)
        if path == "/api/backup/restore":
            target = payload.get("path")
            if not target:
                return 400, {"error": "No backup file given", "code": "no-path"}
            confirm = payload.get("confirm")
            result = backup.restore_backup(
                Path(str(target)),
                db_path,
                confirm=str(confirm) if confirm else None,
                tracker_control=tracker_control,
                before_swap=before_swap,
            )
            return 200, {"restore": result, "status": backup.backup_status(db_path)}
    except backup.BackupError as exc:
        return _error(exc)
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return None
