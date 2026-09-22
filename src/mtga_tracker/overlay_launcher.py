"""Start and stop the in-game overlay (a separate Tauri process).

The overlay is its own small native app (`overlay/`), built by
`scripts/build_overlay.sh` and shipped inside the tracker bundle. This
module is the only thing in the Python side that knows where the binary
lives and how to run it: the menu-bar app and the dashboard's Settings page
both go through :class:`OverlayManager`, so "Start Overlay" in the menu bar and
the "In-game overlay" toggle on the Settings page agree with each other.

The overlay talks to the tracker only through the dashboard's
``GET /api/overlay`` endpoint — it is launched with ``--api <dashboard url>``
so it follows whichever port the dashboard actually bound.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .paths import DATA_DIR, PROJECT_ROOT

#: settings.json section that remembers whether the overlay should start.
SETTINGS_SECTION = "overlay"

#: Environment override for the overlay executable (development, testing).
BINARY_ENV = "MTGA_TRACKER_OVERLAY_BIN"

#: The overlay's own diagnostic log (placement, show/hide, Arena probe, page
#: errors) and its raw stderr (panics), both in the tracker's data folder so
#: "it didn't show up" has somewhere to look.
OVERLAY_LOG = DATA_DIR / "overlay.log"
OVERLAY_STDERR_LOG = DATA_DIR / "overlay-stderr.log"

# The overlay uses this distinct exit code only when the player selects
# "Quit overlay" inside its own UI. A successful second-instance handoff
# exits with 0 and must not be mistaken for the overlay being turned off.
USER_QUIT_EXIT_CODE = 23

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
        if sys.platform == "darwin":
            # The macOS build copies the overlay's .app into the tracker
            # bundle's Contents/Helpers (a real nested bundle, where Apple
            # wants helper apps and where codesign --deep can seal it);
            # PyInstaller's data tree would mangle a nested .app.
            exe = Path(sys.executable).resolve()
            candidates.append(exe.parent.parent / "Helpers" / _MAC_EXECUTABLE)
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


#: The overlay starts with the tracker unless the user has turned it off.
OVERLAY_ENABLED_DEFAULT = True


def load_overlay_enabled(path: Optional[Path] = None) -> bool:
    """The saved "overlay.enabled" flag — on until the user turns it off
    (a missing or unreadable settings file means the default)."""
    settings_path = path or _settings_path()
    try:
        document = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return OVERLAY_ENABLED_DEFAULT
    section = document.get(SETTINGS_SECTION) if isinstance(document, dict) else None
    if not isinstance(section, dict):
        return OVERLAY_ENABLED_DEFAULT
    return bool(section.get("enabled", OVERLAY_ENABLED_DEFAULT))


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
ProcessFinder = Callable[[Path], List[int]]
ProcessKiller = Callable[[int], None]


def _overlay_process_ids(binary: Path) -> List[int]:
    """Return other processes running this exact overlay executable.

    Tauri's single-instance handoff makes the newly launched child exit while
    the original overlay keeps running. Tracking only the child therefore
    reports a false stop after a tracker restart. Keep this dependency-free:
    macOS/Linux have pgrep+ps, and Windows has tasklist.
    """
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {binary.name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                **_detached_kwargs(),
            )
            pids: List[int] = []
            for line in result.stdout.splitlines():
                columns = [part.strip().strip('"') for part in line.split(",")]
                if len(columns) >= 2 and columns[0].lower() == binary.name.lower():
                    try:
                        pids.append(int(columns[1]))
                    except ValueError:
                        continue
            return pids

        result = subprocess.run(
            ["/usr/bin/pgrep", "-x", binary.name],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        candidates = [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]
        expected = (str(binary), str(binary.resolve()))
        found: List[int] = []
        for pid in candidates:
            details = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            command = details.stdout.strip()
            if any(command.startswith(path) for path in expected):
                found.append(pid)
        return found
    except (OSError, subprocess.SubprocessError):
        return []


def _terminate_process(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


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
        log_dir: Optional[Path] = None,
        process_finder: ProcessFinder = _overlay_process_ids,
        process_killer: ProcessKiller = _terminate_process,
    ):
        self._binary_override = binary
        self._settings_path = settings_path
        self._popen = popen
        self._log_dir = log_dir
        self._process_finder = process_finder
        self._process_killer = process_killer
        self._stderr_file: Optional[Any] = None
        self._lock = threading.RLock()
        self._process: Optional[Any] = None
        self._api_url: Optional[str] = None
        self._listeners: List[Listener] = []
        self._last_error: Optional[str] = None
        self._last_exit_code: Optional[int] = None

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
            return self._process is not None or bool(self._external_process_ids())

    @property
    def log_path(self) -> Path:
        return (self._log_dir / OVERLAY_LOG.name) if self._log_dir else OVERLAY_LOG

    @property
    def stderr_log_path(self) -> Path:
        return (self._log_dir / OVERLAY_STDERR_LOG.name) if self._log_dir else OVERLAY_STDERR_LOG

    def status(self) -> Dict[str, Any]:
        binary = self.binary
        return {
            "enabled": self.enabled,
            "available": binary is not None,
            "running": self.running,
            "binary": str(binary) if binary else None,
            "log": str(self.log_path),
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
            if self._external_process_ids(binary):
                # A previous tracker process may have left the single Tauri
                # instance running. It is still the live overlay; do not
                # spawn a short-lived handoff child and later call it a stop.
                self._last_error = None
                return True
            self._ensure_executable(binary)
            args = [str(binary), "--log", str(self.log_path)]
            if self._api_url:
                args += ["--api", self._api_url]
            stderr: Any = subprocess.DEVNULL
            try:
                self.stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
                self._stderr_file = open(self.stderr_log_path, "w", encoding="utf-8")
                stderr = self._stderr_file
            except OSError:
                self._stderr_file = None
            try:
                self._process = self._popen(
                    args,
                    cwd=str(binary.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=stderr,
                    stderr=stderr,
                    **_detached_kwargs(),
                )
            except OSError as exc:
                self._last_error = f"Could not start the overlay: {exc}"
                self._process = None
                return False
            self._last_error = None
            self._last_exit_code = None
            return True

    #: Flags the running overlay understands from a second launch (its
    #: single-instance guard hands the arguments over and the second copy
    #: exits): open the ⚙ flyout, show, hide.
    REQUESTS = {"open-settings": "--open-settings", "show": "--show", "hide": "--hide"}

    def send(self, request: str) -> bool:
        """Ask the running overlay to do something (from the tracker's menu)."""
        flag = self.REQUESTS.get(request)
        if flag is None:
            raise ValueError(f"Unknown overlay request: {request!r}")
        with self._lock:
            if not self.running:
                return False
            binary = self.binary
            if binary is None:
                return False
            try:
                self._popen(
                    [str(binary), flag],
                    cwd=str(binary.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_detached_kwargs(),
                )
            except OSError as exc:
                self._last_error = f"Could not reach the overlay: {exc}"
                return False
        return True

    def stop(self, *, timeout: float = 3.0) -> None:
        with self._lock:
            process = self._process
            self._process = None
            external_pids = self._external_process_ids()
            owned_pid = getattr(process, "pid", None)
        if process is None:
            owned_pid = None
        else:
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
        for pid in external_pids:
            if pid == owned_pid:
                continue
            try:
                self._process_killer(pid)
            except OSError:
                pass
        self._close_stderr()

    def _close_stderr(self) -> None:
        handle = self._stderr_file
        self._stderr_file = None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def refresh(self) -> Dict[str, Any]:
        """Poll the child and preserve the difference between a handoff,
        a crash, and the player's explicit Quit overlay command."""
        with self._lock:
            was_running = self._process is not None
            self._reap()
            exited = was_running and self._process is None
            externally_running = exited and bool(self._external_process_ids())
            user_quit = exited and self._last_exit_code == USER_QUIT_EXIT_CODE
            if user_quit and self.enabled:
                save_overlay_enabled(False, self._settings_path)
            if externally_running:
                self._last_error = None
        if exited:
            self._notify()
        return self.status()

    def _reap(self) -> None:
        process = self._process
        if process is not None and process.poll() is not None:
            self._last_exit_code = process.returncode
            self._last_error = (
                f"The overlay exited with code {process.returncode}; see {self.log_path}."
            )
            self._process = None
            self._close_stderr()

    def _external_process_ids(self, binary: Optional[Path] = None) -> List[int]:
        binary = binary or self.binary
        if binary is None:
            return []
        try:
            return self._process_finder(binary)
        except OSError:
            return []

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
    """Keep background child processes out of the tracker's console on Windows."""
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
