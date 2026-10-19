"""Unified tracker, dashboard, and desktop-app launcher."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable, Optional, TextIO

from .analytics import AnalyticsStore
from .dashboard import DEFAULT_DB_PATH, create_dashboard_server
from .deck_downloader_launcher import DECK_FINDER_FLAG
from .log_parser import MTGALogParser
from .single_instance import SingleInstanceGuard, acquire_with_retry
from .tracker import CardTracker


StatusCallback = Callable[[str], None]

#: How long a version relaunched by the updater waits for the old process's
#: instance locks before giving up quietly.
AFTER_UPDATE_LOCK_WAIT_S = 60.0


class CallbackTextStream:
    """Minimal text stream that forwards tracker output to a callback."""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback

    def write(self, text: str) -> int:
        if text:
            self.callback(text)
        return len(text)

    def flush(self) -> None:
        return None


def _configured_mtga_data_dir() -> Optional[str]:
    configured = os.getenv("MTGA_DATA_DIR")
    if configured:
        return configured
    try:
        import config as user_config  # type: ignore[import-not-found]

        return getattr(user_config, "MTGA_DATA_DIR", None)
    except ImportError:
        return None


class UnifiedLauncher:
    """Own the tracker worker and local dashboard server as one application."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        db_path: Path = DEFAULT_DB_PATH,
        log_path: Optional[Path] = None,
        output_stream: Optional[TextIO] = None,
        status_callback: Optional[StatusCallback] = None,
        use_colors: Optional[bool] = None,
        update_flags: Optional[dict] = None,
    ):
        self.host = host
        self.requested_port = port
        self.db_path = Path(db_path).expanduser()
        self.log_path = Path(log_path).expanduser() if log_path else None
        self.output_stream = output_stream or sys.stdout
        self.status_callback = status_callback or (lambda _status: None)
        self.use_colors = use_colors
        self.dashboard_server = None
        self.dashboard_thread: Optional[threading.Thread] = None
        self.tracker: Optional[CardTracker] = None
        self.tracker_thread: Optional[threading.Thread] = None
        self.tracker_error: Optional[Exception] = None
        self._stop_requested = threading.Event()
        #: Clear while a tracker session runs on any thread (the background
        #: worker, or the main thread in --no-gui mode); set once it returned.
        self._tracker_stopped = threading.Event()
        self._tracker_stopped.set()
        self._stop_status_pending = False
        #: --after-update / --updated-from / --update-failed from this launch.
        self.update_flags = dict(update_flags or {})

    @property
    def dashboard_url(self) -> Optional[str]:
        if self.dashboard_server is None:
            return None
        host, port = self.dashboard_server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def tracker_is_running(self) -> bool:
        return self.tracker_thread is not None and self.tracker_thread.is_alive()

    @property
    def tracker_active(self) -> bool:
        """True while a tracker session runs, background or foreground."""
        return not self._tracker_stopped.is_set()

    def wait_tracker_stopped(self, timeout: float) -> bool:
        """Wait until no tracker session is running (a foreground session
        returns from start_tracker); False when it is still running."""
        return self._tracker_stopped.wait(timeout)

    def _set_status(self, status: str) -> None:
        self.status_callback(status)

    def start_dashboard(self) -> str:
        """Start the dashboard in a daemon thread and return its local URL."""
        if self.dashboard_server is not None:
            return self.dashboard_url or ""

        store = AnalyticsStore(self.db_path)
        store.connect()
        store.close()
        try:
            server = create_dashboard_server(
                self.host,
                self.requested_port,
                db_path=self.db_path,
                tracker_control=self,
            )
        except OSError:
            if self.requested_port == 0:
                raise
            server = create_dashboard_server(
                self.host, 0, db_path=self.db_path, tracker_control=self
            )

        self.dashboard_server = server
        self.dashboard_thread = threading.Thread(
            target=server.serve_forever,
            name="mtga-dashboard",
            daemon=True,
        )
        self.dashboard_thread.start()
        self._set_status("dashboard-running")
        return self.dashboard_url or ""

    def open_dashboard(self, fragment: str = "") -> bool:
        """Open the dashboard in the browser, optionally at a hash route
        (e.g. "/#/settings" for the Settings page)."""
        url = self.dashboard_url or self.start_dashboard()
        return webbrowser.open(f"{url}{fragment}" if fragment else url)

    def _build_tracker(self) -> CardTracker:
        if self.log_path is not None:
            if not self.log_path.is_file():
                raise FileNotFoundError(f"Log file not found at {self.log_path}")
            parser = MTGALogParser(str(self.log_path))
        else:
            parser = MTGALogParser()
        tracker = CardTracker(
            parser,
            mtga_data_dir=_configured_mtga_data_dir(),
            output_stream=self.output_stream,
        )
        tracker.analytics.close()
        tracker._console_db_path = self.db_path
        tracker.analytics = AnalyticsStore(self.db_path)
        # The console prints "Replay: <dashboard>/#/replay/<game_id>" after a
        # game is saved; resolved lazily because the port is known only once
        # the dashboard server is listening.
        tracker.dashboard_url_provider = lambda: self.dashboard_url
        if self.use_colors is not None:
            tracker.use_colors = self.use_colors
        elif self.output_stream is not sys.stdout:
            tracker.use_colors = False
        return tracker

    def _run_tracker(self) -> None:
        self.tracker_error = None
        self._set_status("tracker-starting")
        try:
            tracker = self._build_tracker()
            self.tracker = tracker
            if self._stop_requested.is_set():
                return
            self._set_status("tracker-running")
            tracker.start()
        except Exception as exc:
            self.tracker_error = exc
            self.output_stream.write(f"Tracker failed: {exc}\n")
            self.output_stream.flush()
            self._set_status("tracker-error")
        finally:
            self.tracker = None
            self._mark_tracker_stopped()
            if not self._stop_requested.is_set() or self._stop_status_pending:
                self._stop_status_pending = False
                self._set_status("tracker-stopped")
            self._tracker_stopped.set()

    def start_tracker(self, *, background: bool = True) -> None:
        """Start a fresh tracker session in the background or current thread."""
        if self.tracker_is_running:
            return
        self._stop_requested.clear()
        self._tracker_stopped.clear()
        if not background:
            self._run_tracker()
            return
        self.tracker_thread = threading.Thread(
            target=self._run_tracker,
            name="mtga-tracker",
            daemon=True,
        )
        self.tracker_thread.start()

    def _mark_tracker_stopped(self) -> None:
        """Best-effort: stamp live_status stale so the dashboard's Live Log
        light and /live tracker state flip off immediately on stop."""
        try:
            store = AnalyticsStore(self.db_path)
            try:
                store.mark_live_status_stopped()
            finally:
                store.close()
        except Exception:
            pass

    def stop_tracker(self, *, timeout: float = 3.0) -> None:
        self._stop_requested.set()
        if self.tracker is not None:
            self.tracker.request_stop()
        thread = self.tracker_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
            if thread.is_alive():
                # Still finishing a write: keep the reference so
                # tracker_is_running stays true and nothing starts a second
                # tracker beside it. Its own exit reports "stopped".
                self._stop_status_pending = True
                return
        self.tracker_thread = None
        self._mark_tracker_stopped()
        self._set_status("tracker-stopped")

    def stop_dashboard(self) -> None:
        server = self.dashboard_server
        if server is None:
            return
        server.shutdown()
        server.server_close()
        thread = self.dashboard_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.dashboard_server = None
        self.dashboard_thread = None
        self._set_status("dashboard-stopped")

    def start_updater(
        self, request_exit: Callable[[], None], *, foreground_tracker: bool = False
    ) -> None:
        """Start the in-app updater (a no-op unless this is a frozen build
        with update checks on). Call after start_dashboard(), never from it:
        tests and tools create launchers freely."""
        from .updater import get_manager

        manager = get_manager()
        manager.configure(
            db_path=self.db_path,
            launcher=self,
            request_exit=request_exit,
            foreground_tracker=foreground_tracker,
            launch_flags=self.update_flags,
        )
        manager.start()

    def shutdown(self) -> None:
        self.stop_tracker()
        self.stop_dashboard()


def _update_flags(args: argparse.Namespace) -> dict:
    return {
        "after_update": bool(getattr(args, "after_update", False)),
        "updated_from": getattr(args, "updated_from", None),
        "update_failed": getattr(args, "update_failed", None),
    }


def _run_without_gui(args: argparse.Namespace) -> int:
    launcher = UnifiedLauncher(
        host=args.host,
        port=args.port,
        db_path=args.db,
        log_path=args.log_path,
        update_flags=_update_flags(args),
    )
    from .updater import get_manager

    try:
        url = launcher.start_dashboard()
        print(f"Dashboard: {url}")
        if not args.no_browser:
            launcher.open_dashboard()
        # The tracker owns this thread; an install stops it, which returns
        # start_tracker() below, and the process exits once the detached
        # installer is spawned.
        launcher.start_updater(lambda: None, foreground_tracker=True)
        while True:
            launcher.start_tracker(background=False)
            if get_manager().wait_for_handoff() != "resumed":
                break
            print("Update could not be installed; tracking resumed.")
        return 1 if launcher.tracker_error else 0
    finally:
        get_manager().stop()
        launcher.shutdown()


def _with_relaunch_arguments(arguments: list) -> list:
    """A relaunch by the updater's installer/helper carries only the update
    flags; put back the command line the updated run was started with
    (recorded in pending.json), so --db, --port and --no-gui survive."""
    if "--after-update" not in arguments and not any(
        item == "--update-failed" or item.startswith("--update-failed=") for item in arguments
    ):
        return arguments
    from .updater_support import read_relaunch_arguments

    recorded = read_relaunch_arguments()
    return (recorded + arguments) if recorded else arguments


def main(argv: Optional[list[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    arguments = _with_relaunch_arguments(arguments)
    if DECK_FINDER_FLAG in arguments:
        # The packaged tracker doubles as the Deck Finder terminal tool: the
        # dashboard's launcher runs this same binary with the flag inside a
        # terminal window, so the install ships one executable.
        from .deck_downloader_launcher import run_deck_finder

        return run_deck_finder([arg for arg in arguments if arg != DECK_FINDER_FLAG])

    parser = argparse.ArgumentParser(description="Run the MTGA tracker and dashboard together.")
    parser.add_argument("--log-path", type=Path, help="Path to MTGA Player.log.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path.")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind host.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Preferred dashboard port (default: data/settings.json dashboard.port, else 8765).",
    )
    parser.add_argument("--no-gui", action="store_true", help="Run in one terminal without the menu bar.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the dashboard automatically.")
    parser.add_argument("--login-start", action="store_true", help=argparse.SUPPRESS)
    # Passed by the updater's installer/helper when it relaunches the app.
    parser.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--updated-from", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--update-failed", nargs="?", const="unknown", default=None, help=argparse.SUPPRESS
    )
    args = parser.parse_args(arguments)
    from .settings import load_app_settings

    app_settings = load_app_settings(create=False)
    if args.port is None:
        args.port = app_settings.dashboard_port
    # Keep --no-browser as a one-run override of the saved preference. A
    # relaunch after an update never opens a tab: the old one reloads itself.
    args.no_browser = (
        args.no_browser or args.after_update or not app_settings.open_dashboard_on_launch
    )

    instance_guard = SingleInstanceGuard()
    try:
        if args.after_update:
            # The old version may still be shutting down; wait for its lock.
            guard_acquired = acquire_with_retry(instance_guard, AFTER_UPDATE_LOCK_WAIT_S)
        else:
            guard_acquired = instance_guard.acquire()
    except OSError as exc:
        message = f"Tapps Tracker could not establish its single-instance lock: {exc}"
        if args.no_gui:
            print(message, file=sys.stderr)
        else:
            from .menu_app import show_instance_message

            show_instance_message(message, title="Tapps Tracker startup error")
        return 1

    if not guard_acquired:
        if args.after_update:
            from .updater_support import append_log

            append_log("relaunch after update found another instance still running; exiting")
            return 0
        if args.login_start:
            return 0
        message = (
            "Tapps Tracker is already running. Look for its icon in the "
            "menu bar (macOS) or system tray (Windows)."
        )
        if args.no_gui:
            print(message, file=sys.stderr)
        else:
            from .menu_app import show_instance_message

            show_instance_message(message)
        return 0

    try:
        if args.no_gui:
            return _run_without_gui(args)

        try:
            from .menu_app import run_menu_app
        except ImportError as exc:
            parser.error(
                "The menu-bar launcher requires the GUI dependencies. "
                "Install them with: pip install -e '.[gui]'"
            )
            raise exc
        return run_menu_app(args)
    finally:
        instance_guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
