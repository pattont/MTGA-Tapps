"""User-editable desktop application settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .paths import DATA_DIR


SETTINGS_PATH = DATA_DIR / "settings.json"
DEFAULT_DASHBOARD_PORT = 8765
MIN_DASHBOARD_PORT = 1024
MAX_DASHBOARD_PORT = 65535
DEFAULT_LIVE_LOG_WIDTH = 1400
DEFAULT_LIVE_LOG_HEIGHT = 1020
MIN_LIVE_LOG_WIDTH = 820
MIN_LIVE_LOG_HEIGHT = 560
MAX_LIVE_LOG_WIDTH = 4096
MAX_LIVE_LOG_HEIGHT = 2160


@dataclass(frozen=True)
class AppSettings:
    """Validated desktop settings used by the menu-bar application."""

    live_log_width: int = DEFAULT_LIVE_LOG_WIDTH
    live_log_height: int = DEFAULT_LIVE_LOG_HEIGHT
    dashboard_port: int = DEFAULT_DASHBOARD_PORT


def _default_document() -> Dict[str, Any]:
    return {
        "live_log_window": {
            "width": DEFAULT_LIVE_LOG_WIDTH,
            "height": DEFAULT_LIVE_LOG_HEIGHT,
        },
        "dashboard": {
            "port": DEFAULT_DASHBOARD_PORT,
        },
    }


def _bounded_dimension(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))


def load_app_settings(path: Path = SETTINGS_PATH, *, create: bool = True) -> AppSettings:
    """Load validated settings, creating a default JSON file when missing."""
    path = Path(path).expanduser()
    if not path.exists():
        if create:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(_default_document(), indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
        return AppSettings()

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(document, dict):
        return AppSettings()
    window = document.get("live_log_window")
    if not isinstance(window, dict):
        window = {}
    dashboard = document.get("dashboard")
    if not isinstance(dashboard, dict):
        dashboard = {}
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
    )
