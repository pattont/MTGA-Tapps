"""User-editable desktop application settings.

settings.json lives at the project top level, next to config.py, so it is
easy to find and edit by hand. Frozen (installed) builds have no project
checkout, so they keep it in the per-user data directory instead.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import DATA_DIR, PROJECT_ROOT


def _settings_file_path() -> Path:
    if getattr(sys, "frozen", False):
        return DATA_DIR / "settings.json"
    return PROJECT_ROOT / "settings.json"


SETTINGS_PATH = _settings_file_path()

#: Where settings.json lived before it moved up to the project top level.
LEGACY_SETTINGS_PATH = DATA_DIR / "settings.json"


def _migrate_legacy_settings() -> None:
    """One-time move of data/settings.json up to the project top level."""
    if SETTINGS_PATH == LEGACY_SETTINGS_PATH or SETTINGS_PATH.exists():
        return
    try:
        if LEGACY_SETTINGS_PATH.is_file():
            SETTINGS_PATH.write_text(
                LEGACY_SETTINGS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
    except OSError:
        pass


_migrate_legacy_settings()
DEFAULT_DASHBOARD_PORT = 8765
MIN_DASHBOARD_PORT = 1024
MAX_DASHBOARD_PORT = 65535
DEFAULT_LIVE_LOG_WIDTH = 1400
DEFAULT_LIVE_LOG_HEIGHT = 1020
MIN_LIVE_LOG_WIDTH = 820
MIN_LIVE_LOG_HEIGHT = 560
MAX_LIVE_LOG_WIDTH = 4096
MAX_LIVE_LOG_HEIGHT = 2160
DEFAULT_START_AT_LOGIN = False
DEFAULT_OPEN_DASHBOARD_ON_LAUNCH = True
DEFAULT_UPDATE_CHECK = True
DEFAULT_UPDATE_AUTO_DOWNLOAD = True
DEFAULT_UPDATE_AUTO_INSTALL = False
DEFAULT_UPDATE_CHANNEL = "stable"
#: Update channels the manifest URL knows ("beta" is a later phase).
UPDATE_CHANNELS = ("stable",)


@dataclass(frozen=True)
class AppSettings:
    """Validated desktop settings used by the menu-bar application."""

    live_log_width: int = DEFAULT_LIVE_LOG_WIDTH
    live_log_height: int = DEFAULT_LIVE_LOG_HEIGHT
    dashboard_port: int = DEFAULT_DASHBOARD_PORT
    start_at_login: bool = DEFAULT_START_AT_LOGIN
    open_dashboard_on_launch: bool = DEFAULT_OPEN_DASHBOARD_ON_LAUNCH
    update_check: bool = DEFAULT_UPDATE_CHECK
    update_auto_download: bool = DEFAULT_UPDATE_AUTO_DOWNLOAD
    auto_install_updates: bool = DEFAULT_UPDATE_AUTO_INSTALL
    update_channel: str = DEFAULT_UPDATE_CHANNEL
    skipped_update_version: Optional[str] = None


def _default_update_section() -> Dict[str, Any]:
    return {
        "check": DEFAULT_UPDATE_CHECK,
        "auto_download": DEFAULT_UPDATE_AUTO_DOWNLOAD,
        "auto_install": DEFAULT_UPDATE_AUTO_INSTALL,
        "channel": DEFAULT_UPDATE_CHANNEL,
        "skipped_version": None,
    }


def _default_document() -> Dict[str, Any]:
    return {
        "live_log_window": {
            "width": DEFAULT_LIVE_LOG_WIDTH,
            "height": DEFAULT_LIVE_LOG_HEIGHT,
        },
        "dashboard": {
            "port": DEFAULT_DASHBOARD_PORT,
        },
        "startup": {
            "start_at_login": DEFAULT_START_AT_LOGIN,
            "open_dashboard_on_launch": DEFAULT_OPEN_DASHBOARD_ON_LAUNCH,
        },
        "updates": _default_update_section(),
    }


def _bounded_dimension(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))


def _boolean(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _update_channel(value: Any) -> str:
    return value if isinstance(value, str) and value in UPDATE_CHANNELS else DEFAULT_UPDATE_CHANNEL


def _version_text(value: Any) -> Optional[str]:
    """A skipped-version string, validated by the updater's own parser so
    settings and the manager accept exactly the same versions."""
    from .updater_manifest import parse_version

    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= 64 and parse_version(value) is not None else None


def _read_document(path: Path) -> Dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def _write_document(path: Path, document: Dict[str, Any]) -> None:
    """Atomically replace settings without dropping unrelated sections."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_app_settings(path: Optional[Path] = None, *, create: bool = True) -> AppSettings:
    """Load validated settings, creating a default JSON file when missing."""
    path = Path(path or SETTINGS_PATH).expanduser()
    if not path.exists():
        if create:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(_default_document(), indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
        return AppSettings()

    document = _read_document(path)
    if not document:
        return AppSettings()
    window = document.get("live_log_window")
    if not isinstance(window, dict):
        window = {}
    dashboard = document.get("dashboard")
    if not isinstance(dashboard, dict):
        dashboard = {}
    startup = document.get("startup")
    if not isinstance(startup, dict):
        startup = {}
    updates = document.get("updates")
    if not isinstance(updates, dict):
        updates = {}
    return AppSettings(
        live_log_width=_bounded_dimension(
            window.get("width"),
            default=DEFAULT_LIVE_LOG_WIDTH,
            minimum=MIN_LIVE_LOG_WIDTH,
            maximum=MAX_LIVE_LOG_WIDTH,
        ),
        live_log_height=_bounded_dimension(
            window.get("height"),
            default=DEFAULT_LIVE_LOG_HEIGHT,
            minimum=MIN_LIVE_LOG_HEIGHT,
            maximum=MAX_LIVE_LOG_HEIGHT,
        ),
        dashboard_port=_bounded_dimension(
            dashboard.get("port"),
            default=DEFAULT_DASHBOARD_PORT,
            minimum=MIN_DASHBOARD_PORT,
            maximum=MAX_DASHBOARD_PORT,
        ),
        start_at_login=_boolean(startup.get("start_at_login"), default=DEFAULT_START_AT_LOGIN),
        open_dashboard_on_launch=_boolean(
            startup.get("open_dashboard_on_launch"),
            default=DEFAULT_OPEN_DASHBOARD_ON_LAUNCH,
        ),
        update_check=_boolean(updates.get("check"), default=DEFAULT_UPDATE_CHECK),
        update_auto_download=_boolean(
            updates.get("auto_download"), default=DEFAULT_UPDATE_AUTO_DOWNLOAD
        ),
        auto_install_updates=_boolean(
            updates.get("auto_install"), default=DEFAULT_UPDATE_AUTO_INSTALL
        ),
        update_channel=_update_channel(updates.get("channel")),
        skipped_update_version=_version_text(updates.get("skipped_version")),
    )


def save_startup_settings(
    *,
    start_at_login: bool,
    open_dashboard_on_launch: bool,
    path: Optional[Path] = None,
) -> AppSettings:
    """Persist startup preferences while preserving unrelated settings."""
    if not isinstance(start_at_login, bool) or not isinstance(open_dashboard_on_launch, bool):
        raise TypeError("Startup settings must be booleans.")
    path = Path(path or SETTINGS_PATH).expanduser()
    document = _read_document(path) if path.exists() else _default_document()
    document["startup"] = {
        "start_at_login": start_at_login,
        "open_dashboard_on_launch": open_dashboard_on_launch,
    }
    _write_document(path, document)
    return load_app_settings(path, create=False)


def save_update_settings(
    *,
    check: bool,
    auto_download: bool,
    auto_install: bool,
    channel: str = DEFAULT_UPDATE_CHANNEL,
    skipped_version: Optional[str] = None,
    path: Optional[Path] = None,
) -> AppSettings:
    """Persist update preferences while preserving unrelated settings.

    Only user preferences live here; the updater's runtime state (last
    check, ETag, download journal) is in the data folder's updates/state.json.
    """
    if not all(isinstance(value, bool) for value in (check, auto_download, auto_install)):
        raise TypeError("Update settings must be booleans.")
    if channel not in UPDATE_CHANNELS:
        raise ValueError(f"Unknown update channel: {channel!r}")
    if skipped_version is not None and _version_text(skipped_version) is None:
        raise ValueError(f"Not a version: {skipped_version!r}")
    path = Path(path or SETTINGS_PATH).expanduser()
    document = _read_document(path) if path.exists() else _default_document()
    document["updates"] = {
        "check": check,
        "auto_download": auto_download,
        "auto_install": auto_install,
        "channel": channel,
        "skipped_version": _version_text(skipped_version),
    }
    _write_document(path, document)
    return load_app_settings(path, create=False)
