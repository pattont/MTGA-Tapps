"""The overlay process supervisor and its settings/API surface."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from mtga_tracker import overlay_launcher, settings_api
from mtga_tracker.overlay_launcher import OverlayManager, load_overlay_enabled, save_overlay_enabled


class FakeProcess:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _fake_binary(tmp_path: Path) -> Path:
    binary = tmp_path / "tapps-overlay"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o644)
    return binary


def test_enabled_flag_round_trips_without_touching_other_sections(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"dashboard": {"port": 9000}}), encoding="utf-8")
    assert load_overlay_enabled(path) is False
    save_overlay_enabled(True, path)
    assert load_overlay_enabled(path) is True
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["dashboard"] == {"port": 9000}
    assert document["overlay"] == {"enabled": True}
    save_overlay_enabled(False, path)
    assert load_overlay_enabled(path) is False


def test_missing_or_broken_settings_mean_disabled(tmp_path):
    assert load_overlay_enabled(tmp_path / "missing.json") is False
    broken = tmp_path / "settings.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_overlay_enabled(broken) is False
    save_overlay_enabled(True, broken)
    assert load_overlay_enabled(broken) is True


def test_manager_starts_with_api_url_and_stops(tmp_path):
    binary = _fake_binary(tmp_path)
    launched = []

    def popen(args, **kwargs):
        process = FakeProcess(args, **kwargs)
        launched.append(process)
        return process

    manager = OverlayManager(binary=binary, settings_path=tmp_path / "settings.json", popen=popen, log_dir=tmp_path / "data")
    manager.configure("http://127.0.0.1:8123")
    assert manager.available
    assert manager.running is False

    status = manager.set_enabled(True)
    assert status["running"] is True
    assert status["enabled"] is True
    assert launched[0].args == [str(binary), "--log", str(tmp_path / "data" / "overlay.log"), "--api", "http://127.0.0.1:8123"]
    assert launched[0].kwargs["cwd"] == str(tmp_path)
    assert (tmp_path / "data" / "overlay-stderr.log").exists()
    assert status["log"] == str(tmp_path / "data" / "overlay.log")
    if os.name != "nt":
        assert stat.S_IMODE(binary.stat().st_mode) & 0o111, "exec bit restored before launch"

    # Starting twice does not spawn twice.
    manager.start()
    assert len(launched) == 1

    status = manager.set_enabled(False)
    assert status["running"] is False
    assert launched[0].terminated
    assert load_overlay_enabled(tmp_path / "settings.json") is False


def test_manager_restarts_when_the_dashboard_url_changes(tmp_path):
    binary = _fake_binary(tmp_path)
    launched = []

    def popen(args, **kwargs):
        process = FakeProcess(args, **kwargs)
        launched.append(process)
        return process

    manager = OverlayManager(binary=binary, settings_path=tmp_path / "settings.json", popen=popen, log_dir=tmp_path)
    manager.configure("http://127.0.0.1:8765")
    manager.set_enabled(True)
    manager.configure("http://127.0.0.1:8766")
    assert len(launched) == 2
    assert launched[0].terminated
    assert launched[1].args[-1] == "http://127.0.0.1:8766"


def test_manager_reports_a_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay_launcher, "overlay_binary_path", lambda: None)
    manager = OverlayManager(settings_path=tmp_path / "settings.json", popen=FakeProcess)
    assert manager.available is False
    status = manager.set_enabled(True)
    assert status["running"] is False
    assert "not included" in status["error"]


def test_refresh_turns_the_setting_off_when_the_overlay_quits_itself(tmp_path):
    binary = _fake_binary(tmp_path)
    processes = []

    def popen(args, **kwargs):
        process = FakeProcess(args, **kwargs)
        processes.append(process)
        return process

    manager = OverlayManager(binary=binary, settings_path=tmp_path / "settings.json", popen=popen, log_dir=tmp_path)
    seen = []
    manager.add_listener(seen.append)
    manager.set_enabled(True)
    assert seen[-1]["running"] is True
    processes[0].returncode = 0  # the player picked "Quit overlay" in its tray
    status = manager.refresh()
    assert status["running"] is False
    assert status["enabled"] is False
    assert "exited with code 0" in status["error"]
    assert seen[-1]["running"] is False


def test_settings_api_exposes_and_toggles_the_overlay(tmp_path, monkeypatch):
    binary = _fake_binary(tmp_path)
    manager = OverlayManager(binary=binary, settings_path=tmp_path / "settings.json", popen=FakeProcess, log_dir=tmp_path)
    monkeypatch.setattr(overlay_launcher, "_manager", manager)

    code, body = settings_api.handle_post("/api/settings/overlay", {"enabled": True})
    assert code == 200
    assert body["overlay"]["running"] is True
    assert body["overlay"]["enabled"] is True

    code, body = settings_api.handle_post("/api/settings/overlay", {})
    assert code == 400

    code, body = settings_api.handle_post("/api/settings/overlay", {"enabled": False})
    assert code == 200
    assert body["overlay"]["running"] is False

    monkeypatch.setattr(overlay_launcher, "overlay_binary_path", lambda: None)
    manager._binary_override = None
    code, body = settings_api.handle_post("/api/settings/overlay", {"enabled": True})
    assert code == 400
    assert "not included" in body["error"]


def test_overlay_status_in_settings_get(tmp_path, monkeypatch):
    manager = OverlayManager(binary=_fake_binary(tmp_path), settings_path=tmp_path / "settings.json", popen=FakeProcess, log_dir=tmp_path)
    monkeypatch.setattr(overlay_launcher, "_manager", manager)
    code, body = settings_api.handle_get("/api/settings", None)
    assert code == 200
    assert body["overlay"] == {
        "enabled": False,
        "available": True,
        "running": False,
        "binary": str(manager.binary),
        "log": str(tmp_path / "overlay.log"),
        "error": None,
    }


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_binary_candidates_follow_the_platform(monkeypatch, platform):
    monkeypatch.setattr(overlay_launcher.sys, "platform", platform)
    monkeypatch.delenv(overlay_launcher.BINARY_ENV, raising=False)
    names = [str(c) for c in overlay_launcher.overlay_binary_candidates()]
    if platform == "darwin":
        assert any(name.endswith("Tapps Overlay.app/Contents/MacOS/tapps-overlay") for name in names)
    else:
        assert any(name.endswith("tapps-overlay.exe") for name in names)
    monkeypatch.setenv(overlay_launcher.BINARY_ENV, "/tmp/custom-overlay")
    assert str(overlay_launcher.overlay_binary_candidates()[0]) == "/tmp/custom-overlay"
