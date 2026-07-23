import io
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from http.client import HTTPConnection

from mtga_tracker.app import CallbackTextStream, UnifiedLauncher


class _FakeTracker:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self):
        self.started.set()
        self.stopped.wait(timeout=5)

    def request_stop(self):
        self.stopped.set()


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
