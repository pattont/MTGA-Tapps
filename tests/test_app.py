import io
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from http.client import HTTPConnection

import pytest

from mtga_tracker import app
from mtga_tracker.app import CallbackTextStream, UnifiedLauncher
from mtga_tracker.settings import AppSettings


class _FakeTracker:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self):
        self.started.set()
        self.stopped.wait(timeout=5)

    def request_stop(self):
        self.stopped.set()


@pytest.fixture
def available_instance_guard(monkeypatch):
    """Keep app.main tests independent of a real running Tapps process."""

    class AvailableGuard:
        def acquire(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(app, "SingleInstanceGuard", AvailableGuard)


def test_callback_text_stream_forwards_writes():
    chunks = []
    stream = CallbackTextStream(chunks.append)

    assert stream.write("Turn 1\n") == 7
    stream.flush()

    assert chunks == ["Turn 1\n"]


def test_unified_launcher_runs_dashboard_and_tracker_together(tmp_path, monkeypatch):
    statuses = []
    fake_tracker = _FakeTracker()
    launcher = UnifiedLauncher(
        port=0,
        db_path=tmp_path / "tracker.sqlite3",
        status_callback=statuses.append,
    )
    monkeypatch.setattr(launcher, "_build_tracker", lambda: fake_tracker)

    try:
        url = launcher.start_dashboard()
        launcher.start_tracker(background=True)
        assert fake_tracker.started.wait(timeout=2)
        assert launcher.tracker_is_running is True

        connection = HTTPConnection("127.0.0.1", launcher.dashboard_server.server_address[1])
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        connection.close()

        assert url.startswith("http://127.0.0.1:")
        assert response.status == 200
        assert "dashboard-running" in statuses
        assert "tracker-running" in statuses
    finally:
        launcher.shutdown()

    assert fake_tracker.stopped.is_set()
    assert launcher.dashboard_server is None
    assert statuses[-1] == "dashboard-stopped"


def test_unified_launcher_uses_a_free_port_when_preferred_port_is_busy(tmp_path):
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    occupied_port = occupied.getsockname()[1]
    launcher = UnifiedLauncher(port=occupied_port, db_path=tmp_path / "tracker.sqlite3")

    try:
        launcher.start_dashboard()
        assert launcher.dashboard_server.server_address[1] != occupied_port
    finally:
        launcher.stop_dashboard()
        occupied.close()


def test_unified_launcher_records_tracker_startup_errors(tmp_path):
    output = io.StringIO()
    launcher = UnifiedLauncher(
        port=0,
        db_path=tmp_path / "tracker.sqlite3",
        log_path=tmp_path / "missing.log",
        output_stream=output,
    )

    launcher.start_tracker(background=False)

    assert isinstance(launcher.tracker_error, FileNotFoundError)
    assert "Tracker failed: Log file not found" in output.getvalue()


def test_unified_launcher_can_force_colors_for_gui_stream(monkeypatch):
    analytics = SimpleNamespace(close=lambda: None)
    tracker = SimpleNamespace(use_colors=False, analytics=analytics, _console_db_path=None)
    monkeypatch.setattr("mtga_tracker.app.MTGALogParser", lambda: object())
    monkeypatch.setattr("mtga_tracker.app.CardTracker", lambda *args, **kwargs: tracker)
    launcher = UnifiedLauncher(
        db_path=Path("/tmp/selected-tracker.sqlite3"),
        output_stream=io.StringIO(),
        use_colors=True,
    )

    built_tracker = launcher._build_tracker()

    assert built_tracker is tracker
    assert tracker.use_colors is True
    assert tracker._console_db_path == Path("/tmp/selected-tracker.sqlite3")
    assert tracker.analytics.path == Path("/tmp/selected-tracker.sqlite3")


def test_saved_browser_preference_disables_automatic_open(
    monkeypatch, available_instance_guard
):
    captured = []
    monkeypatch.setattr(
        "mtga_tracker.settings.load_app_settings",
        lambda create=False: AppSettings(open_dashboard_on_launch=False),
    )
    monkeypatch.setattr(app, "_run_without_gui", lambda args: captured.append(args) or 0)

    assert app.main(["--no-gui", "--port", "9001"]) == 0

    assert captured[0].no_browser is True


def test_saved_browser_preference_allows_automatic_open(
    monkeypatch, available_instance_guard
):
    captured = []
    monkeypatch.setattr(
        "mtga_tracker.settings.load_app_settings",
        lambda create=False: AppSettings(open_dashboard_on_launch=True),
    )
    monkeypatch.setattr(app, "_run_without_gui", lambda args: captured.append(args) or 0)

    assert app.main(["--no-gui", "--port", "9001"]) == 0

    assert captured[0].no_browser is False


def test_no_browser_cli_flag_overrides_saved_preference(
    monkeypatch, available_instance_guard
):
    captured = []
    monkeypatch.setattr(
        "mtga_tracker.settings.load_app_settings",
        lambda create=False: AppSettings(open_dashboard_on_launch=True),
    )
    monkeypatch.setattr(app, "_run_without_gui", lambda args: captured.append(args) or 0)

    assert app.main(["--no-gui", "--no-browser", "--port", "9001"]) == 0

    assert captured[0].no_browser is True


def test_second_headless_instance_exits_before_starting_tracker(monkeypatch, capsys):
    class HeldGuard:
        def acquire(self):
            return False

        def release(self):
            raise AssertionError("an unacquired guard must not be released")

    monkeypatch.setattr(app, "SingleInstanceGuard", HeldGuard)
    monkeypatch.setattr(
        app,
        "_run_without_gui",
        lambda _args: pytest.fail("a second instance must not start"),
    )

    assert app.main(["--no-gui", "--port", "9001"]) == 0
    assert "already running" in capsys.readouterr().err


def test_single_instance_guard_is_released_after_launcher_exits(monkeypatch):
    released = []

    class AvailableGuard:
        def acquire(self):
            return True

        def release(self):
            released.append(True)

    monkeypatch.setattr(app, "SingleInstanceGuard", AvailableGuard)
    monkeypatch.setattr(app, "_run_without_gui", lambda _args: 7)

    assert app.main(["--no-gui", "--port", "9001"]) == 7
    assert released == [True]


def test_duplicate_login_launch_exits_quietly(monkeypatch, capsys):
    class HeldGuard:
        def acquire(self):
            return False

        def release(self):
            raise AssertionError("an unacquired guard must not be released")

    monkeypatch.setattr(app, "SingleInstanceGuard", HeldGuard)

    assert app.main(["--no-gui", "--login-start", "--port", "9001"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
