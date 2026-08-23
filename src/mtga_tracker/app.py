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
from .log_parser import MTGALogParser
from .tracker import CardTracker


StatusCallback = Callable[[str], None]


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

    @property
    def dashboard_url(self) -> Optional[str]:
        if self.dashboard_server is None:
            return None
        host, port = self.dashboard_server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def tracker_is_running(self) -> bool:
        return self.tracker_thread is not None and self.tracker_thread.is_alive()

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
            )
        except OSError:
            if self.requested_port == 0:
                raise
            server = create_dashboard_server(self.host, 0, db_path=self.db_path)

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
            if not self._stop_requested.is_set():
                self._set_status("tracker-stopped")

    def start_tracker(self, *, background: bool = True) -> None:
        """Start a fresh tracker session in the background or current thread."""
        if self.tracker_is_running:
            return
        self._stop_requested.clear()
        if not background:
            self._run_tracker()
            return
        self.tracker_thread = threading.Thread(
            target=self._run_tracker,
            name="mtga-tracker",
            daemon=True,
        )
        self.tracker_thread.start()

    def stop_tracker(self, *, timeout: float = 3.0) -> None:
        self._stop_requested.set()
        if self.tracker is not None:
            self.tracker.request_stop()
        thread = self.tracker_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self.tracker_thread = None
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

    def shutdown(self) -> None:
        self.stop_tracker()
        self.stop_dashboard()


def _run_without_gui(args: argparse.Namespace) -> int:
    launcher = UnifiedLauncher(
        host=args.host,
        port=args.port,
        db_path=args.db,
        log_path=args.log_path,
    )
    try:
        url = launcher.start_dashboard()
        print(f"Dashboard: {url}")
        if not args.no_browser:
            launcher.open_dashboard()
        launcher.start_tracker(background=False)
        return 1 if launcher.tracker_error else 0
    finally:
        launcher.shutdown()


def main(argv: Optional[list[str]] = None) -> int:
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
    args = parser.parse_args(argv)
    if args.port is None:
        from .settings import load_app_settings

        args.port = load_app_settings(create=False).dashboard_port

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


if __name__ == "__main__":
    raise SystemExit(main())
