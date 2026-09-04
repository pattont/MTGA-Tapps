"""Start and stop the in-game overlay (a separate Tauri process).

The overlay is its own small native app (`overlay/`), built by
`scripts/build_overlay.sh` and shipped inside the tracker bundle. This
module is the only thing in the Python side that knows where the binary
lives and how to run it: the menu-bar app and the dashboard's Settings page
both go through :class:`OverlayManager`, so "Show Overlay" in the tray and
the "In-game overlay" toggle on the Settings page agree with each other.

The overlay talks to the tracker only through the dashboard's
``GET /api/overlay`` endpoint — it is launched with ``--api <dashboard url>``
so it follows whichever port the dashboard actually bound.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .paths import PROJECT_ROOT

#: settings.json section that remembers whether the overlay should start.
SETTINGS_SECTION = "overlay"

#: Environment override for the overlay executable (development, testing).
BINARY_ENV = "MTGA_TRACKER_OVERLAY_BIN"

_MAC_APP_NAME = "Tapps Overlay.app"
_MAC_EXECUTABLE = Path(_MAC_APP_NAME) / "Contents" / "MacOS" / "tapps-overlay"
_WINDOWS_EXECUTABLE = "tapps-overlay.exe"
_POSIX_EXECUTABLE = "tapps-overlay"


def _platform_relative_binary() -> Path:
    if sys.platform == "darwin":
        return _MAC_EXECUTABLE
    if sys.platform == "win32":
        return Path(_WINDOWS_EXECUTABLE)
    return Path(_POSIX_EXECUTABLE)


def _frozen_roots() -> List[Path]:
    """Where PyInstaller puts bundled data files, in the order to try."""
    roots: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        # Tapps Tracker.app/Contents/MacOS/<exe> -> Contents/Resources
        roots.append(exe.parent.parent / "Resources")
        roots.append(exe.parent.parent / "Frameworks")
    roots.append(exe.parent)
    roots.append(exe.parent / "_internal")
    return roots


def overlay_binary_candidates() -> List[Path]:
    """Every place the overlay executable might be, most specific first."""
    relative = _platform_relative_binary()
    candidates: List[Path] = []
    override = os.environ.get(BINARY_ENV)
    if override:
        candidates.append(Path(override).expanduser())
    if getattr(sys, "frozen", False):
        for root in _frozen_roots():
            candidates.append(root / "overlay" / relative)
    overlay_dir = PROJECT_ROOT / "overlay"
    candidates.append(overlay_dir / "build-out" / relative)
    target = overlay_dir / "src-tauri" / "target"
    for profile in ("release", "debug"):
        if sys.platform == "darwin":
            candidates.append(target / profile / "bundle" / "macos" / _MAC_EXECUTABLE)
        candidates.append(target / profile / relative.name)
    return candidates


def overlay_binary_path() -> Optional[Path]:
    """The overlay executable to run, or None when this build has none."""
    for candidate in overlay_binary_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _settings_path() -> Path:
    from .settings import SETTINGS_PATH

    return SETTINGS_PATH


def load_overlay_enabled(path: Optional[Path] = None) -> bool:
    """The saved "overlay.enabled" flag (off until the user turns it on)."""
    settings_path = path or _settings_path()
    try:
        document = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    section = document.get(SETTINGS_SECTION) if isinstance(document, dict) else None
    if not isinstance(section, dict):
        return False
    return bool(section.get("enabled", False))


def save_overlay_enabled(enabled: bool, path: Optional[Path] = None) -> None:
    """Merge the flag into settings.json without touching other sections."""
    settings_path = path or _settings_path()
    try:
        document = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            document = {}
    except (OSError, ValueError):
        document = {}
    section = document.get(SETTINGS_SECTION)
    if not isinstance(section, dict):
        section = {}
    section["enabled"] = bool(enabled)
    document[SETTINGS_SECTION] = section
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


Listener = Callable[[Dict[str, Any]], None]


class OverlayManager:
    """Process supervisor for the overlay, shared by the tray and the API.

    Thread-safe: the dashboard's request threads and the Qt main thread both
    call into it. Listeners are invoked on whichever thread changed the
    state; Qt consumers should hop to the GUI thread themselves.
    """

    def __init__(
        self,
        *,
        binary: Optional[Path] = None,
        settings_path: Optional[Path] = None,
        popen: Callable[..., Any] = subprocess.Popen,
    ):
        self._binary_override = binary
        self._settings_path = settings_path
        self._popen = popen
        self._lock = threading.RLock()
        self._process: Optional[Any] = None
        self._api_url: Optional[str] = None
        self._listeners: List[Listener] = []
        self._last_error: Optional[str] = None

    # -- discovery ---------------------------------------------------------

    @property
    def binary(self) -> Optional[Path]:
        return self._binary_override or overlay_binary_path()

    @property
    def available(self) -> bool:
        return self.binary is not None

    # -- state -------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return load_overlay_enabled(self._settings_path)

    @property
    def running(self) -> bool:
        with self._lock:
            self._reap()
            return self._process is not None

    def status(self) -> Dict[str, Any]:
        binary = self.binary
        return {
            "enabled": self.enabled,
            "available": binary is not None,
            "running": self.running,
            "binary": str(binary) if binary else None,
            "error": self._last_error,
        }

    def add_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self) -> None:
        snapshot = self.status()
        for listener in list(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                pass

    # -- lifecycle ---------------------------------------------------------

    def configure(self, api_url: Optional[str]) -> None:
        """Remember the dashboard URL; restart the overlay if it changed."""
        with self._lock:
            changed = api_url != self._api_url
            self._api_url = api_url
            if changed and self._process is not None:
                self.stop()
                self.start()

    def set_enabled(self, enabled: bool, *, persist: bool = True) -> Dict[str, Any]:
        """Turn the overlay on or off (the tray item and the Settings toggle)."""
        with self._lock:
            if persist:
                save_overlay_enabled(enabled, self._settings_path)
            if enabled:
                self.start()
            else:
                self.stop()
        self._notify()
        return self.status()

    def start_if_enabled(self) -> None:
        if self.enabled:
            self.start()
            self._notify()

    def start(self) -> bool:
        with self._lock:
            self._reap()
            if self._process is not None:
                return True
            binary = self.binary
            if binary is None:
                self._last_error = "The overlay is not included in this build."
                return False
            self._ensure_executable(binary)
            args = [str(binary)]
            if self._api_url:
                args += ["--api", self._api_url]
            try:
                self._process = self._popen(
                    args,
                    cwd=str(binary.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_detached_kwargs(),
                )
            except OSError as exc:
                self._last_error = f"Could not start the overlay: {exc}"
                self._process = None
                return False
            self._last_error = None
            return True

    def stop(self, *, timeout: float = 3.0) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except Exception:
                    process.kill()
                    try:
                        process.wait(timeout=1.0)
                    except Exception:
                        pass
        except OSError:
            pass

    def refresh(self) -> Dict[str, Any]:
        """Poll the child; if the player quit it from its own tray, remember
        that as "off" so it does not come back on the next launch."""
        with self._lock:
            was_running = self._process is not None
            self._reap()
            exited = was_running and self._process is None
            if exited and self.enabled:
                save_overlay_enabled(False, self._settings_path)
        if exited:
            self._notify()
        return self.status()

    def _reap(self) -> None:
        process = self._process
        if process is not None and process.poll() is not None:
            self._process = None

    @staticmethod
    def _ensure_executable(binary: Path) -> None:
        if sys.platform == "win32":
            return
        try:
            mode = binary.stat().st_mode
            if not mode & 0o111:
                binary.chmod(mode | 0o755)
        except OSError:
            pass


def _detached_kwargs() -> Dict[str, Any]:
    """Keep the overlay out of the tracker's console/job on Windows."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flags}
    return {}


_manager: Optional[OverlayManager] = None
_manager_lock = threading.Lock()


def get_manager() -> OverlayManager:
    """The process-wide manager (the tray and the dashboard share one)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = OverlayManager()
        return _manager
