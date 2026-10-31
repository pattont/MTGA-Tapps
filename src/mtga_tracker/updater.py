"""In-app updates: one process-wide :class:`UpdateManager` (like the overlay
manager) that checks the signed release manifest, downloads and verifies the
new installer in the background, and runs the install hand-off when the user
asks (or, opted in, when no game is running and Arena is closed).

- Pure logic lives in `updater_manifest.py` (versions, manifest, signature)
  and `updater_download.py` (HTTP, resumable download); the per-OS hand-off
  in `update_install.py`; HTTP glue in `update_api.py`.
- User preferences are settings.json's "updates" section; runtime state
  (last check, ETag, cached manifest, download journal, last result) is
  `<data>/updates/state.json`, so a background write never races a Settings
  save.
- The manager runs whenever `UnifiedLauncher` starts it (frozen builds and
  `python -m mtga_tracker.app` alike). Source runs check on the same cadence
  and report `available` with `can_install: false, reason: "source"` (the
  pill links to the release); they never download or install. The
  dashboard-only entry point never configures it and reports `unsupported`.
- Environment: `MTGA_TRACKER_DISABLE_UPDATES=1` turns it off (CI, previews).
  `MTGA_TRACKER_UPDATE_MANIFEST_URL=<url>` replaces the manifest URL for
  release validation (for example a local `http.server` serving a draft's
  files); the signature URL is that URL plus ".sig", and the override's host
  joins the redirect/download allow-list for the session (http allowed for
  that host only). The Ed25519 signature check stays mandatory.

See docs/plans/AUTO_UPDATE.md.
"""

from __future__ import annotations

import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import update_install as installer_module
from .updater_fetch import UpdateFetchMixin
from .updater_gate import UpdateGateMixin
from .updater_handoff import UpdateHandoffMixin
from .updater_download import (  # noqa: F401 - re-exported for callers and tests
    MANIFEST_URL,
    MANIFEST_URL_ENV,
    UrlPolicy,
    manifest_override,
    SIGNATURE_URL,
    DownloadError,
    UpdateNetworkError,
    download_asset,
    fetch_manifest,
    fetch_signature,
    stale_download_files,
    verify_file,
)
from .updater_manifest import (  # noqa: F401 - re-exported
    ALLOWED_DOWNLOAD_HOSTS,
    UPDATE_PUBLIC_KEYS,
    Manifest,
    ManifestError,
    UpdateAsset,
    current_arch,
    current_platform,
    is_newer,
    is_release_build,
    load_signed_manifest,
    parse_manifest,
    parse_version,
    select_asset,
    versions_equal,
)

from .updater_support import (  # noqa: F401 - re-exported
    FIRST_CHECK_DELAY_S,
    CHECK_INTERVAL_S,
    CHECK_JITTER,
    ERROR_RETRY_S,
    IDLE_WAKE_S,
    IDLE_REQUIRED_S,
    HEALTHY_AFTER_S,
    INSTALL_DELAY_S,
    EXIT_BACKSTOP_S,
    QUEUED_EVENT_WINDOW_S,
    BO3_BETWEEN_GAMES_WINDOW_S,
    DOWNLOAD_ATTEMPTS,
    DISABLE_ENV,
    HANDOFF_WAIT_LIMIT_S,
    STATES,
    BUSY_ORDER,
    FORCE_BYPASS,
    _RETRYABLE,
    UpdateError,
    UpdateBlocked,
    _utc_iso,
    _naive,
    _write_json_atomic,
    _read_json,
    append_log,
)


def _default_updates_dir() -> Path:
    from .paths import DATA_DIR

    return DATA_DIR / "updates"


def _default_log_path() -> Path:
    from .paths import LOGS_DIR

    return LOGS_DIR / "updater.log"


class UpdateManager(UpdateFetchMixin, UpdateGateMixin, UpdateHandoffMixin):
    """State machine, scheduler thread, safety gate, and install sequence."""

    def __init__(
        self,
        *,
        current_version: Optional[str] = None,
        state_dir: Optional[Path] = None,
        install_info: Optional[installer_module.InstallInfo] = None,
        frozen: Optional[bool] = None,
        environ: Optional[Dict[str, str]] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], float] = time.time,
        settings_loader: Optional[Callable[[], Any]] = None,
        arena_probe: Optional[Callable[[], Optional[bool]]] = None,
        installer: Any = None,
        backup_fn: Optional[Callable[[Path, str], Any]] = None,
        overlay_factory: Optional[Callable[[], Any]] = None,
        release_handles: Optional[Callable[[Path], None]] = None,
        exit_backstop: Optional[Callable[[], None]] = None,
        log_path: Optional[Path] = None,
        platform_name: Optional[str] = None,
        arch: Optional[str] = None,
        rng: Optional[random.Random] = None,
        argv: Optional[List[str]] = None,
    ) -> None:
        if current_version is None:
            from . import __version__ as current_version
        self.current_version = str(current_version)
        self.state_dir = Path(state_dir) if state_dir is not None else _default_updates_dir()
        self._environ = environ if environ is not None else os.environ
        self._frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self._info = install_info
        self._session_factory = session_factory
        self._monotonic = monotonic
        self._clock = clock
        self._settings_loader = settings_loader
        self._arena_probe = arena_probe
        self._installer = installer or installer_module
        self._backup_fn = backup_fn
        self._overlay_factory = overlay_factory
        self._release_handles = release_handles
        self._exit_backstop = exit_backstop
        self.log_path = Path(log_path) if log_path is not None else _default_log_path()
        self._platform = platform_name or current_platform()
        self._arch = arch or current_arch()
        self._rng = rng or random.Random()
        self._settings_cache: Any = None
        #: The command line this run was started with, for the relaunch.
        self._argv = list(sys.argv[1:] if argv is None else argv)
        #: Set when the --no-gui wait gave up: the worker must not spawn.
        self._handoff_abandoned = False
        self._spawning = False

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []

        self._configured = False
        self.db_path: Optional[Path] = None
        self.launcher: Any = None
        self._request_exit: Callable[[], None] = lambda: None
        self._foreground_tracker = False
        self._launch_flags: Dict[str, Any] = {}

        # Until a launcher configures it (the dashboard-only entry point never
        # does), the manager reports "unsupported".
        self._state = "unsupported"
        self._latest: Optional[Manifest] = None
        self._asset: Optional[UpdateAsset] = None
        self._error: Optional[Dict[str, str]] = None
        self._progress: Optional[Dict[str, Any]] = None
        self._download_path: Optional[Path] = None
        self._runtime: Dict[str, Any] = {}
        self._runtime_loaded = False
        self._check_requested = False
        self._download_requested = False
        self._install_request: Optional[Dict[str, Any]] = None
        self._next_check: Optional[float] = None
        self._started_at: Optional[float] = None
        self._healthy_done = False
        self._last_game_seen: Optional[float] = None
        self._event_first_seen: Dict[str, float] = {}
        #: Gate result for the status payload, refreshed on the updater
        #: thread (never on an HTTP handler thread).
        self._blocked_by: List[str] = []
        #: (latest, asset, download path) while a verified update is ready,
        #: so a failed or empty re-check does not throw the download away.
        self._ready_snapshot: Optional[tuple] = None
        #: Set for "Install update and quit": an abort quits instead of resuming.
        self._quit_after_install = False
        override = manifest_override(self._environ)
        self._manifest_url = override or MANIFEST_URL
        self._signature_url = self._manifest_url + ".sig"
        self._url_policy = UrlPolicy.for_override(override)
        self._last_progress_notify = 0.0
        self._handoff_done = threading.Event()
        self._handoff_outcome = "none"
        self._reassert_after_update = False

    # -- configuration -----------------------------------------------------

    @property
    def kill_switch(self) -> bool:
        return self._environ.get(DISABLE_ENV) == "1"

    def install_info(self) -> installer_module.InstallInfo:
        if self._info is None:
            if self._frozen:
                self._info = installer_module.detect_install(version=self.current_version)
            else:
                self._info = installer_module.InstallInfo("source", False, "source")
        return self._info

    def _settings(self) -> Any:
        """The update preferences, read from settings.json once and cached
        until settings_changed() / skip() say they moved."""
        cached = self._settings_cache
        if cached is not None:
            return cached
        if self._settings_loader is not None:
            loaded = self._settings_loader()
        else:
            from .settings import load_app_settings

            loaded = load_app_settings(create=False)
        self._settings_cache = loaded
        return loaded

    def _invalidate_settings(self) -> None:
        self._settings_cache = None

    def configure(
        self,
        *,
        db_path: Path,
        launcher: Any,
        request_exit: Callable[[], None],
        foreground_tracker: bool = False,
        launch_flags: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self.db_path = Path(db_path)
            self.launcher = launcher
            self._request_exit = request_exit
            self._foreground_tracker = foreground_tracker
            self._launch_flags = dict(launch_flags or {})
            self._configured = True
            self._state = self._resting_state()

    def _resting_state(self) -> str:
        if not self._configured:
            return "unsupported"
        if self.kill_switch or not self._settings().update_check:
            return "disabled"
        return "idle"

    def support(self) -> Dict[str, Any]:
        info = self.install_info()
        return {
            "supported": bool(self._configured and info.can_install and not self.kill_switch),
            "install_kind": info.kind,
        }

    def add_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self) -> None:
        snapshot = self.status()
        for listener in list(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                pass

    # -- logging and runtime state ---------------------------------------------

    def _log(self, message: str) -> None:
        append_log(message, self.log_path)

    def _console(self, message: str) -> None:
        stream = getattr(self.launcher, "output_stream", None)
        if stream is None:
            return
        try:
            stream.write(message + "\n")
            stream.flush()
        except Exception:
            pass

    @property
    def _state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def _pending_file(self) -> Path:
        return self.state_dir / "pending.json"

    def _load_runtime(self) -> None:
        if not self._runtime_loaded:
            self._runtime = _read_json(self._state_file)
            self._runtime_loaded = True

    def _save_runtime(self) -> None:
        try:
            _write_json_atomic(self._state_file, self._runtime)
        except OSError as exc:
            self._log(f"could not write state.json: {exc}")

    def _set_state(self, state: str, *, error: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            previous = self._state
            self._state = state
            self._error = error
            if state != "downloading":
                self._progress = None
            if state not in ("ready", "installing"):
                self._blocked_by = []
        if state == "ready" and threading.current_thread() is self._thread:
            self._refresh_blocked_by()
        if previous != state or error:
            detail = f" ({error['code']}: {error['message']})" if error else ""
            self._log(f"{previous} -> {state}{detail}")
        self._notify()

    def _fail(self, code: str, message: str) -> None:
        self._set_state("error", error={"code": code, "message": message})

    # -- status ----------------------------------------------------------------

    def _below_minimum(self) -> bool:
        latest = self._latest
        return bool(
            latest
            and latest.minimum_version
            and is_newer(latest.minimum_version, self.current_version)
        )

    def _capability(self) -> tuple:
        if not self._configured:
            return False, "dashboard-only"
        info = self.install_info()
        if not info.can_install:
            return False, info.reason or "unsupported-platform"
        if self._latest is not None and self._below_minimum():
            return False, "manual-required"
        if self._latest is not None and self._asset is None:
            return False, "unsupported-platform"
        return True, None

    def _skipped(self, settings: Any) -> bool:
        latest = self._latest
        if latest is None or latest.mandatory:
            return False
        return versions_equal(getattr(settings, "skipped_update_version", None), latest.version)

    def _just_updated(self) -> Optional[Dict[str, Any]]:
        result = self._runtime.get("last_result")
        if not isinstance(result, dict) or result.get("acknowledged"):
            return None
        return {
            "from": result.get("from"),
            "to": result.get("to"),
            "notes_url": result.get("notes_url"),
            "ok": bool(result.get("ok")),
        }

    def _refresh_blocked_by(self) -> None:
        """Sample the gate for the status payload (updater thread only: the
        Arena probe and a database read must not run per HTTP request)."""
        if self._state not in ("ready", "installing"):
            reasons: List[str] = []
        else:
            reasons = self.busy_reasons(gate="manual")
        with self._lock:
            self._blocked_by = reasons

    def status(self) -> Dict[str, Any]:
        settings = self._settings()
        with self._lock:
            blocked_by = list(self._blocked_by)
            self._load_runtime()
            latest = self._latest
            can_install, reason = self._capability()
            info = self.install_info()
            from .analytics import DB_SCHEMA_STATUS

            return {
                "state": self._state,
                "current_version": self.current_version,
                "latest_version": latest.version if latest else None,
                "notes_url": latest.notes_url if latest else None,
                "released_at": latest.released_at if latest else None,
                "mandatory": bool(latest and latest.mandatory),
                "below_minimum": self._below_minimum(),
                "install_kind": info.kind,
                "can_install": can_install,
                "reason": None if can_install else reason,
                "needs_elevation": bool(info.needs_elevation),
                "progress": dict(self._progress) if self._progress else None,
                "error": dict(self._error) if self._error else None,
                "last_check": self._runtime.get("last_check"),
                "skipped": self._skipped(settings),
                "auto_download": bool(settings.update_auto_download),
                "auto_install": bool(settings.auto_install_updates),
                "pending_install": bool(self._runtime.get("pending_install")),
                "blocked_by": blocked_by,
                "just_updated": self._just_updated(),
                "db_newer_than_app": bool(DB_SCHEMA_STATUS.get("newer_than_app")),
            }

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler thread. A no-op unless configured by the
        launcher, runtime-capable, and not switched off."""
        with self._lock:
            if not self._configured or self._thread is not None:
                return
            if self._state in ("idle", "unsupported", "disabled"):
                self._state = self._resting_state()
            if self.kill_switch:
                return
            if self._manifest_url != MANIFEST_URL:
                self._log(f"{MANIFEST_URL_ENV} is set: checking {self._manifest_url}")
            self._stop.clear()
            self._started_at = self._monotonic()
            self._next_check = self._started_at + FIRST_CHECK_DELAY_S
            self._thread = threading.Thread(target=self._run, name="mtga-updater", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def settings_changed(self) -> None:
        self._invalidate_settings()
        settings = self._settings()
        with self._lock:
            if self._state in ("idle", "up_to_date", "available", "error", "disabled"):
                if not settings.update_check or self.kill_switch:
                    if self._state != "disabled":
                        self._state = "disabled"
                elif self._state == "disabled" and self._configured:
                    self._state = "available" if self._latest_is_newer() else "idle"
                    self._next_check = self._monotonic() + 5.0
        self._log("settings changed")
        self._wake.set()
        self._notify()

    def _latest_is_newer(self) -> bool:
        return bool(self._latest and is_newer(self._latest.version, self.current_version))

    # -- user actions ------------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._thread is None and self._configured:
            self.start()
        if self._thread is None and self._configured:
            # A manual check without a scheduler (source/dashboard checks).
            threading.Thread(target=self._tick, name="mtga-updater-once", daemon=True).start()

    def check_now(self) -> Dict[str, Any]:
        with self._lock:
            if not self._configured or self.kill_switch:
                return self.status()
            if self._state in ("downloading", "installing"):
                return self.status()
            if self._state == "ready" and self._download_path is not None:
                self._ready_snapshot = (self._latest, self._asset, self._download_path)
            self._check_requested = True
        self._set_state("checking")
        self._wake.set()
        self._ensure_worker()
        return self.status()

    def download(self) -> Dict[str, Any]:
        with self._lock:
            if self._state in ("downloading", "ready", "installing"):
                return self.status()
            can_install, _reason = self._capability()
            if not can_install:
                raise UpdateError("This copy cannot install updates in place.", "unsupported")
            if self._state != "available" or not self._latest_is_newer():
                raise UpdateError("No update is available to download.", "not-available")
            self._download_requested = True
        self._wake.set()
        return self.status()

    def request_install(
        self, *, force: bool = False, when: str = "now", relaunch: bool = True
    ) -> Dict[str, Any]:
        gate = "forced" if force else "manual"
        with self._lock:
            if self._state != "ready":
                raise UpdateError("No verified update is ready to install.", "not-ready")
            can_install, reason = self._capability()
            if not can_install:
                raise UpdateError(f"This copy cannot install updates ({reason}).", "unsupported")
        reasons = [] if when == "idle" else self.busy_reasons(gate=gate)
        with self._lock:
            if self._state != "ready":
                raise UpdateError("No verified update is ready to install.", "not-ready")
            if when == "idle":
                self._load_runtime()
                self._runtime["pending_install"] = True
                self._save_runtime()
                self._log("install armed for when no game is running")
            else:
                self._blocked_by = list(reasons)
                if reasons:
                    raise UpdateBlocked(reasons)
                self._quit_after_install = not relaunch
                self._install_request = {
                    "gate": gate,
                    "relaunch": bool(relaunch),
                    "at": self._monotonic() + INSTALL_DELAY_S,
                }
                self._handoff_done.clear()
                self._handoff_outcome = "pending"
                self._state = "installing"
        self._log(f"install requested (when={when}, force={force}, relaunch={relaunch})")
        self._wake.set()
        self._ensure_worker()
        self._notify()
        return self.status()

    def skip(self, version: Optional[str]) -> Dict[str, Any]:
        from .settings import save_update_settings

        if version is not None and (not isinstance(version, str) or parse_version(version) is None):
            raise UpdateError("Not a version.", "bad-version", 400)
        settings = self._settings()
        save_update_settings(
            check=settings.update_check,
            auto_download=settings.update_auto_download,
            auto_install=settings.auto_install_updates,
            channel=settings.update_channel,
            skipped_version=version,
        )
        self._invalidate_settings()
        self._log(f"skipped version set to {version}")
        self._notify()
        return self.status()

    def acknowledge(self) -> Dict[str, Any]:
        self._invalidate_settings()
        with self._lock:
            self._load_runtime()
            result = self._runtime.get("last_result")
            if isinstance(result, dict):
                result["acknowledged"] = True
                self._save_runtime()
        self._notify()
        return self.status()

    def wait_for_handoff(self, timeout: float = HANDOFF_WAIT_LIMIT_S) -> str:
        """For the --no-gui foreground loop: "none" when no install is in
        flight; otherwise wait while the hand-off runs and return "exit" or
        "resumed". `timeout` is far above the hand-off's own bounded steps;
        reaching it abandons the install (pending.json removed, state error)
        so the process never exits with the installer unspawned."""
        deadline = self._monotonic() + timeout
        while True:
            with self._lock:
                outcome = self._handoff_outcome
            if outcome != "pending":
                break
            if self._monotonic() >= deadline:
                with self._lock:
                    spawning = self._spawning
                    if not spawning:
                        self._handoff_abandoned = True
                if spawning:
                    deadline = self._monotonic() + 5.0  # the spawn is quick
                    continue
                self._abort_install(
                    "handoff-timeout", "The update hand-off took too long.", stopped=True
                )
                break
            self._handoff_done.wait(1.0)
        with self._lock:
            outcome = self._handoff_outcome
            if outcome == "resumed":
                self._handoff_outcome = "none"
        if outcome == "resumed":
            return "resumed"
        return "exit" if outcome == "exit" else "none"

    # -- worker ----------------------------------------------------------------------

    def _run(self) -> None:
        try:
            self._startup_tasks()
        except Exception as exc:  # never let the thread die at startup
            self._log(f"startup tasks failed: {type(exc).__name__}: {exc}")
        while not self._stop.is_set():
            try:
                timeout = self._tick()
            except Exception as exc:
                self._log(f"worker error: {type(exc).__name__}: {exc}")
                timeout = 60.0
            self._wake.wait(max(0.05, timeout))
            self._wake.clear()

    def _tick(self) -> float:
        """One scheduler pass; returns seconds until the next one is due."""
        now = self._monotonic()
        settings = self._settings()
        with self._lock:
            scheduled = self._next_check is not None and now >= self._next_check
            allowed = (
                settings.update_check
                and not self.kill_switch
                and self._state not in ("downloading", "installing", "ready")
            )
            check_due = self._check_requested or (scheduled and allowed)
            self._check_requested = False
            if scheduled and not allowed:
                # Not now (checks off, or an update is already in hand): look
                # again a full interval later instead of waking constantly.
                self._schedule_next_check(CHECK_INTERVAL_S)
        if check_due:
            self._check()
        self._maybe_download(settings)
        install = None
        with self._lock:
            request = self._install_request
            if request is not None and self._monotonic() >= request["at"]:
                install, self._install_request = request, None
        if install is not None:
            self._perform_install(gate=install["gate"], relaunch=install["relaunch"])
        elif self._auto_install_armed(settings):
            gate = "pending" if self._runtime.get("pending_install") else "auto"
            reasons = self.busy_reasons(gate=gate)
            if not reasons:
                with self._lock:
                    self._state = "installing"
                    self._handoff_done.clear()
                    self._handoff_outcome = "pending"
                self._notify()
                self._perform_install(gate=gate, relaunch=True, reasons=reasons)
        if self._state == "ready":
            self._refresh_blocked_by()
        self._healthy_tasks()
        return self._next_timeout(settings)

    def _next_timeout(self, settings: Any) -> float:
        now = self._monotonic()
        waits = [CHECK_INTERVAL_S]
        if self._next_check is not None:
            waits.append(self._next_check - now)
        if self._install_request is not None:
            waits.append(self._install_request["at"] - now)
        if self._state == "ready":
            # Re-sample the gate for the status payload, and for an armed
            # auto-install or "install after this game".
            waits.append(IDLE_WAKE_S)
        if not self._healthy_done and self._started_at is not None:
            waits.append(self._started_at + HEALTHY_AFTER_S - now)
        return max(0.05, min(waits))

    def _auto_install_armed(self, settings: Any) -> bool:
        if self._state != "ready" or self._latest is None:
            return False
        if self._runtime.get("pending_install"):
            return True
        if not settings.auto_install_updates or self._skipped(settings):
            return False
        if self.install_info().needs_elevation:
            return False
        failed = self._runtime.get("failed_versions") or []
        return not any(versions_equal(self._latest.version, item) for item in failed)

    def _schedule_next_check(self, delay: float) -> None:
        jitter = 1.0 + self._rng.uniform(-CHECK_JITTER, CHECK_JITTER)
        self._next_check = self._monotonic() + delay * jitter

    def _session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()
        from .updater_download import default_session

        return default_session()


_manager: Optional[UpdateManager] = None
_manager_lock = threading.Lock()


def get_manager() -> UpdateManager:
    """The process-wide manager (the tray and the dashboard share one)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = UpdateManager()
        return _manager
