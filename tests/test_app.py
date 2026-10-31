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


def test_after_update_waits_for_the_old_instance_lock(monkeypatch):
    from functools import partial

    from mtga_tracker import single_instance

    attempts = []

    class SlowGuard:
        def acquire(self):
            attempts.append(True)
            return len(attempts) >= 3

        def release(self):
            pass

    captured = []
    monkeypatch.setattr(app, "SingleInstanceGuard", SlowGuard)
    monkeypatch.setattr(
        app,
        "acquire_with_retry",
        partial(single_instance.acquire_with_retry, sleep=lambda _s: None),
    )
    monkeypatch.setattr(app, "_run_without_gui", lambda args: captured.append(args) or 0)

    assert (
        app.main(["--no-gui", "--after-update", "--updated-from", "0.6.5.3", "--port", "9001"]) == 0
    )
    assert len(attempts) == 3
    args = captured[0]
    assert args.after_update is True and args.updated_from == "0.6.5.3"
    # The relaunched app never opens a second tab; the old one reloads itself.
    assert args.no_browser is True
    assert app._update_flags(args) == {
        "after_update": True,
        "updated_from": "0.6.5.3",
        "update_failed": None,
    }


def test_after_update_with_a_held_lock_exits_quietly(monkeypatch, capsys):
    from mtga_tracker import updater_support

    class HeldGuard:
        def acquire(self):
            return False

        def release(self):
            raise AssertionError("an unacquired guard must not be released")

    logged = []
    monkeypatch.setattr(app, "SingleInstanceGuard", HeldGuard)
    monkeypatch.setattr(app, "AFTER_UPDATE_LOCK_WAIT_S", 0.0)
    monkeypatch.setattr(
        updater_support, "append_log", lambda message, path=None: logged.append(message)
    )
    monkeypatch.setattr(app, "_run_without_gui", lambda _args: pytest.fail("must not start"))

    assert app.main(["--no-gui", "--after-update", "--port", "9001"]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and captured.out == ""
    assert logged and "still running" in logged[0]


def test_update_failed_flag_accepts_an_optional_version(monkeypatch, available_instance_guard):
    captured = []
    monkeypatch.setattr(app, "_run_without_gui", lambda args: captured.append(args) or 0)

    assert app.main(["--no-gui", "--update-failed", "--port", "9001"]) == 0
    assert app.main(["--no-gui", "--update-failed", "0.6.6", "--port", "9001"]) == 0
    assert captured[0].update_failed == "unknown"
    assert captured[1].update_failed == "0.6.6"
    assert captured[0].after_update is False


def test_start_updater_configures_the_shared_manager(tmp_path, monkeypatch):
    from mtga_tracker import updater

    configured = {}

    class FakeManager:
        def configure(self, **kwargs):
            configured.update(kwargs)

        def start(self):
            configured["started"] = True

    monkeypatch.setattr(updater, "_manager", FakeManager())
    launcher = UnifiedLauncher(db_path=tmp_path / "t.sqlite3", update_flags={"after_update": True})
    exit_request = lambda: None  # noqa: E731
    launcher.start_updater(exit_request, foreground_tracker=True)
    assert configured["db_path"] == tmp_path / "t.sqlite3"
    assert configured["launcher"] is launcher and configured["request_exit"] is exit_request
    assert configured["foreground_tracker"] is True
    assert configured["launch_flags"] == {"after_update": True}
    assert configured["started"] is True


@pytest.mark.parametrize("outcomes,expected_runs", [(["none"], 1), (["resumed", "exit"], 2)])
def test_headless_loop_follows_the_update_handoff(monkeypatch, outcomes, expected_runs):
    from mtga_tracker import updater

    events = []

    class FakeLauncher:
        def __init__(self, **kwargs):
            self.tracker_error = None
            events.append(("flags", kwargs.get("update_flags")))

        def start_dashboard(self):
            return "http://127.0.0.1:1"

        def open_dashboard(self):
            events.append("browser")

        def start_updater(self, request_exit, *, foreground_tracker=False):
            events.append(("updater", foreground_tracker))

        def start_tracker(self, *, background=True):
            assert background is False
            events.append("tracker")

        def shutdown(self):
            events.append("shutdown")

    class FakeManager:
        def wait_for_handoff(self, timeout=60.0):
            return outcomes.pop(0)

        def stop(self):
            events.append("updater-stop")

    monkeypatch.setattr(app, "UnifiedLauncher", FakeLauncher)
    monkeypatch.setattr(updater, "_manager", FakeManager())
    args = SimpleNamespace(
        host="127.0.0.1",
        port=0,
        db=Path("t.sqlite3"),
        log_path=None,
        no_browser=True,
        after_update=False,
        updated_from=None,
        update_failed=None,
    )
    assert app._run_without_gui(args) == 0
    assert events.count("tracker") == expected_runs
    assert ("updater", True) in events
    assert events[-2:] == ["updater-stop", "shutdown"]


def test_foreground_tracker_reports_when_it_has_really_stopped(tmp_path, monkeypatch):
    fake_tracker = _FakeTracker()
    launcher = UnifiedLauncher(db_path=tmp_path / "tracker.sqlite3")
    monkeypatch.setattr(launcher, "_build_tracker", lambda: fake_tracker)
    assert launcher.tracker_active is False and launcher.wait_tracker_stopped(0) is True

    # --no-gui: the session runs on "the main thread" (here, a plain thread
    # that is not tracker_thread), so stop_tracker() can only ask.
    main = threading.Thread(target=lambda: launcher.start_tracker(background=False))
    main.start()
    assert fake_tracker.started.wait(timeout=2)
    assert launcher.tracker_is_running is False  # no tracker thread to look at
    assert launcher.tracker_active is True
    assert launcher.wait_tracker_stopped(0.05) is False
    launcher.stop_tracker(timeout=0.1)
    assert launcher.wait_tracker_stopped(5) is True
    main.join(timeout=2)
    assert launcher.tracker_active is False


def test_tracker_stop_requested_during_startup_is_not_lost():
    from mtga_tracker.tracker_runtime import TrackerRuntimeMixin

    loops = []
    closed = []

    class BareTracker(TrackerRuntimeMixin):
        waiting_for_next_game = False
        parser = SimpleNamespace(reset_position=lambda: None)
        analytics = SimpleNamespace(close=lambda: closed.append(True))

        def _process_new_events(self):
            loops.append(True)
            self.running = False

        def __getattr__(self, name):  # every startup helper is a no-op here
            if name.startswith("_"):
                return lambda *args, **kwargs: None
            raise AttributeError(name)

    tracker = BareTracker()
    # The updater asks for a stop while the startup banner is still printing.
    tracker.request_stop()
    tracker.start()
    assert loops == [] and closed == [True]


def test_stop_that_times_out_keeps_the_tracker_and_never_starts_a_second(tmp_path, monkeypatch):
    class SlowTracker(_FakeTracker):
        def request_stop(self):
            pass  # still finishing a write

    statuses = []
    slow = SlowTracker()
    built = []
    launcher = UnifiedLauncher(db_path=tmp_path / "t.sqlite3", status_callback=statuses.append)
    monkeypatch.setattr(launcher, "_build_tracker", lambda: built.append(1) or slow)
    launcher.start_tracker(background=True)
    assert slow.started.wait(2)
    launcher.stop_tracker(timeout=0.05)
    assert launcher.tracker_is_running is True and launcher.tracker_thread is not None
    assert "tracker-stopped" not in statuses
    launcher.start_tracker(background=True)
    assert built == [1]  # no second tracker beside the slow one
    slow.stopped.set()
    assert launcher.wait_tracker_stopped(5)
    launcher.tracker_thread.join(2)
    assert launcher.tracker_is_running is False
    assert statuses[-1] == "tracker-stopped"


@pytest.mark.parametrize(
    "flags", [["--after-update", "--updated-from", "0.6.5.3"], ["--update-failed"]]
)
def test_relaunch_restores_the_original_command_line(tmp_path, monkeypatch, flags):
    import json

    from mtga_tracker import updater_support

    updates = tmp_path / "updates"
    updates.mkdir()
    (updates / "pending.json").write_text(
        json.dumps(
            {
                "to": "0.6.6",
                "relaunch_args": ["--no-gui", "--db", "/data/x.sqlite3", "--port", "9000"],
            }
        )
    )
    monkeypatch.setattr(updater_support, "default_updates_dir", lambda: updates)

    class Guard:
        def acquire(self):
            return True

        def release(self):
            pass

    captured = []
    monkeypatch.setattr(app, "SingleInstanceGuard", Guard)
    monkeypatch.setattr(app, "_run_without_gui", lambda args: captured.append(args) or 0)
    monkeypatch.setattr(app, "acquire_with_retry", lambda guard, timeout: guard.acquire())
    assert app.main(flags) == 0  # a GUI-less run comes back GUI-less
    args = captured[0]
    assert args.no_gui is True and args.db == Path("/data/x.sqlite3") and args.port == 9000
    if "--after-update" in flags:
        assert args.after_update and args.updated_from == "0.6.5.3"
    else:
        assert args.update_failed == "unknown"
