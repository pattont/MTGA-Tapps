"""Constants, errors, and small file helpers shared by the updater modules
(`updater.py` and its `updater_gate` / `updater_handoff` mixins)."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FIRST_CHECK_DELAY_S = 90.0
CHECK_INTERVAL_S = 6 * 3600.0
CHECK_JITTER = 0.10
ERROR_RETRY_S = 3600.0
IDLE_WAKE_S = 15.0
IDLE_REQUIRED_S = 120.0
HEALTHY_AFTER_S = 60.0
INSTALL_DELAY_S = 0.5
EXIT_BACKSTOP_S = 20.0
#: How long a --no-gui main thread waits for a running hand-off. Far above
#: its bounded steps (tracker stop 5 s, checkpoint 10 s, overlay 4 s, spawn
#: retries ~8 s); reaching it abandons the install instead of exiting early.
HANDOFF_WAIT_LIMIT_S = 900.0
QUEUED_EVENT_WINDOW_S = 600.0
BO3_BETWEEN_GAMES_WINDOW_S = 900.0
DOWNLOAD_ATTEMPTS = 3

DISABLE_ENV = "MTGA_TRACKER_DISABLE_UPDATES"

STATES = (
    "idle",
    "checking",
    "up_to_date",
    "available",
    "downloading",
    "ready",
    "installing",
    "error",
    "disabled",
    "unsupported",
)
#: Busy reasons in reporting order; the first is the 409 `code`.
BUSY_ORDER = (
    "deck-transfer",
    "collection-export",
    "backup-restore",
    "game-in-progress",
    "arena-running",
)
#: Reasons an explicit, confirmed user click may override.
FORCE_BYPASS = ("game-in-progress", "arena-running")
_RETRYABLE = {"network", "timeout", "incomplete", "bad-range", "write-failed"}


class UpdateError(Exception):
    def __init__(self, message: str, code: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class UpdateBlocked(UpdateError):
    def __init__(self, reasons: List[str]) -> None:
        super().__init__("An install would interrupt: " + ", ".join(reasons), reasons[0])
        self.blocked_by = list(reasons)


def _utc_iso(stamp: Optional[float] = None) -> str:
    when = datetime.fromtimestamp(stamp if stamp is not None else time.time(), timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _naive(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def append_log(message: str, path: Optional[Path] = None) -> None:
    """One timestamped line in `<logs>/updater.log` (never raises)."""
    try:
        if path is None:
            from .paths import LOGS_DIR

            path = LOGS_DIR / "updater.log"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{_utc_iso()} {message}\n")
    except OSError:
        pass


def default_updates_dir() -> Path:
    """`<data>/updates`: the download cache, state.json and pending.json."""
    from .paths import DATA_DIR

    return DATA_DIR / "updates"


#: Flags the updater adds to a relaunch; never carried into the next one.
_UPDATE_FLAGS_WITH_VALUE = ("--updated-from",)
_UPDATE_FLAGS = ("--after-update", "--login-start")
_PATH_OPTIONS = ("--db", "--log-path")


def relaunch_arguments(argv: List[str], cwd: Optional[Path] = None) -> List[str]:
    """This run's command line for the relaunched app: the updater's own
    flags (and macOS's -psn_ token) removed, path options made absolute
    because the installer/helper relaunches from another directory."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    out: List[str] = []
    items = [str(item) for item in argv]
    index = 0
    while index < len(items):
        item = items[index]
        name = item.split("=", 1)[0]
        if item in _UPDATE_FLAGS or item.startswith("-psn_"):
            index += 1
            continue
        if name in _UPDATE_FLAGS_WITH_VALUE:
            index += 1 if "=" in item else 2
            continue
        if name == "--update-failed":
            # Optional value: skip the next token unless it is another flag.
            has_value = "=" not in item and index + 1 < len(items)
            index += 2 if has_value and not items[index + 1].startswith("-") else 1
            continue
        if name in _PATH_OPTIONS:
            if "=" in item:
                out.append(f"{name}={(base / Path(item.split('=', 1)[1]).expanduser())}")
            elif index + 1 < len(items):
                out += [item, str(base / Path(items[index + 1]).expanduser())]
                index += 1
            else:
                out.append(item)
            index += 1
            continue
        out.append(item)
        index += 1
    return out


def read_relaunch_arguments(updates_dir: Optional[Path] = None) -> Optional[List[str]]:
    """`relaunch_args` from pending.json, or None when absent or malformed."""
    document = _read_json(
        (Path(updates_dir) if updates_dir else default_updates_dir()) / "pending.json"
    )
    value = document.get("relaunch_args")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)
