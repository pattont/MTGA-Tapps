"""The macOS App Nap opt-out: accepted on a Mac, a quiet no-op everywhere else."""

import sys

import pytest

from mtga_tracker import app, app_nap


def test_other_systems_do_nothing(monkeypatch):
    monkeypatch.setattr(app_nap, "_activity", None)
    monkeypatch.setattr(app_nap.sys, "platform", "win32")
    monkeypatch.setattr(app_nap, "_load", lambda *_args: pytest.fail("no library on Windows"))

    assert app_nap.stay_awake() is False
    assert app_nap._activity is None


def test_a_failure_leaves_the_app_as_it_was(monkeypatch):
    def missing(*_args):
        raise OSError("library not found")

    monkeypatch.setattr(app_nap, "_activity", None)
    monkeypatch.setattr(app_nap.sys, "platform", "darwin")
    monkeypatch.setattr(app_nap, "_load", missing)

    assert app_nap.stay_awake() is False
    assert app_nap._activity is None


def test_the_activity_allows_the_mac_to_sleep():
    idle_sleep_disabled = 1 << 20
    assert app_nap.ACTIVITY_OPTIONS & idle_sleep_disabled == 0
    # Everything else of NSActivityUserInitiated, which is what ends App Nap.
    assert app_nap.ACTIVITY_OPTIONS == 0x00FFFFFF & ~idle_sleep_disabled


@pytest.mark.skipif(sys.platform != "darwin", reason="App Nap is a macOS feature")
def test_macos_accepts_the_activity_once(monkeypatch):
    monkeypatch.setattr(app_nap, "_activity", None)

    assert app_nap.stay_awake() is True
    token = app_nap._activity
    assert token
    # A second call keeps the first activity instead of starting another.
    assert app_nap.stay_awake() is True
    assert app_nap._activity == token


def test_the_launcher_opts_out_only_once_it_owns_the_instance(monkeypatch):
    calls = []
    monkeypatch.setattr(app_nap, "stay_awake", lambda: calls.append("awake") or True)
    monkeypatch.setattr(app, "_run_without_gui", lambda _args: 0)

    class Guard:
        held = False

        def acquire(self):
            return not self.held

        def release(self):
            pass

    monkeypatch.setattr(app, "SingleInstanceGuard", Guard)
    assert app.main(["--no-gui", "--port", "9001"]) == 0
    assert calls == ["awake"]

    # A second launch that finds the tracker running exits without it.
    Guard.held = True
    assert app.main(["--no-gui", "--login-start", "--port", "9001"]) == 0
    assert calls == ["awake"]
