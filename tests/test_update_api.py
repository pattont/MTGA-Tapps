"""`/api/update` through a real dashboard server (port 0) with a fake
manager, plus the `/api/settings/updates` preferences endpoint."""

import json
import threading
from http.client import HTTPConnection

import pytest

from mtga_tracker import dashboard, settings, settings_api, updater
from mtga_tracker.updater import UpdateBlocked, UpdateError


class FakeManager:
    def __init__(self):
        self.calls = []
        self.state = "ready"
        self.blocked = []
        self.settings_changes = 0

    def status(self):
        return {"state": self.state, "current_version": "0.6.5.3", "latest_version": "0.6.6"}

    def support(self):
        return {"supported": True, "install_kind": "macos-app"}

    def check_now(self):
        self.calls.append("check")
        return dict(self.status(), state="checking")

    def download(self):
        self.calls.append("download")
        if self.state != "available":
            raise UpdateError("No update is available to download.", "not-available")
        return self.status()

    def request_install(self, *, force=False, when="now"):
        self.calls.append(("install", force, when))
        if self.state != "ready":
            raise UpdateError("No verified update is ready to install.", "not-ready")
        if self.blocked and not force and when == "now":
            raise UpdateBlocked(list(self.blocked))
        return dict(self.status(), state="installing")

    def skip(self, version):
        self.calls.append(("skip", version))
        return self.status()

    def acknowledge(self):
        self.calls.append("acknowledge")
        return self.status()

    def settings_changed(self):
        self.settings_changes += 1


@pytest.fixture
def fake_manager(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(updater, "_manager", manager)
    return manager


@pytest.fixture
def server(tmp_path, fake_manager):
    instance = dashboard.create_dashboard_server("127.0.0.1", 0, db_path=tmp_path / "t.sqlite3")
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance
    instance.shutdown()
    instance.server_close()


def _request(server, method, path, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {"Content-Type": "application/json"} if payload is not None else {}
    request_headers.update(headers or {})
    connection.request(method, path, body=payload, headers=request_headers)
    response = connection.getresponse()
    raw = response.read()
    headers_out = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, headers_out, json.loads(raw.decode("utf-8")) if raw else None


def test_get_update_status_is_uncached_json(server):
    status, headers, body = _request(server, "GET", "/api/update")
    assert status == 200 and body["state"] == "ready"
    assert headers["cache-control"] == "no-store"
    assert headers["content-type"].startswith("application/json")
    assert int(headers["content-length"]) > 0


def test_post_requires_local_origin_and_json(server, fake_manager):
    status, _h, body = _request(
        server, "POST", "/api/update/install", {}, {"Origin": "https://example.com"}
    )
    assert status == 403
    status, _h, _b = _request(
        server, "POST", "/api/update/install", {}, {"Content-Type": "text/plain"}
    )
    assert status == 403
    assert fake_manager.calls == []
    status, _h, _b = _request(
        server, "POST", "/api/update/check", {}, {"Origin": "http://127.0.0.1:8765"}
    )
    assert status == 202 and fake_manager.calls == ["check"]


def test_install_conflicts_and_force(server, fake_manager):
    fake_manager.blocked = ["game-in-progress"]
    status, headers, body = _request(server, "POST", "/api/update/install", {})
    assert status == 409
    assert body["code"] == "game-in-progress" and body["blocked_by"] == ["game-in-progress"]
    assert headers["connection"] == "close" and headers["cache-control"] == "no-store"

    status, _h, body = _request(server, "POST", "/api/update/install", {"force": True})
    assert status == 202 and body["state"] == "installing"

    status, _h, _b = _request(server, "POST", "/api/update/install", {"when": "idle"})
    assert status == 202
    assert fake_manager.calls[-1] == ("install", False, "idle")

    status, _h, body = _request(server, "POST", "/api/update/install", {"force": "yes"})
    assert status == 400

    fake_manager.state = "available"
    status, _h, body = _request(server, "POST", "/api/update/install", {})
    assert status == 409 and body["code"] == "not-ready"


def test_download_skip_acknowledge_and_unknown(server, fake_manager):
    status, _h, body = _request(server, "POST", "/api/update/download", {})
    assert status == 409 and body["code"] == "not-available"
    fake_manager.state = "available"
    assert _request(server, "POST", "/api/update/download", {})[0] == 202
    assert _request(server, "POST", "/api/update/skip", {"version": "0.6.6"})[0] == 200
    assert _request(server, "POST", "/api/update/skip", {"version": None})[0] == 200
    assert _request(server, "POST", "/api/update/skip", {"version": 3})[0] == 400
    assert _request(server, "POST", "/api/update/acknowledge", {})[0] == 200
    assert ("skip", "0.6.6") in fake_manager.calls and ("skip", None) in fake_manager.calls
    status, _h, body = _request(server, "POST", "/api/update/frobnicate", {})
    assert status == 404


def test_settings_updates_endpoint(monkeypatch, tmp_path, fake_manager):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"startup": {"start_at_login": True}, "custom": {"x": 1}}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)

    status, body = settings_api.handle_post("/api/settings/updates", {"auto_install": True})
    assert status == 200
    assert body["updates"] == {
        "check": True,
        "auto_download": True,
        "auto_install": True,
        "channel": "stable",
        "skipped_version": None,
        "supported": True,
        "install_kind": "macos-app",
    }
    assert fake_manager.settings_changes == 1
    document = json.loads(path.read_text())
    assert document["startup"] == {"start_at_login": True}
    assert document["custom"] == {"x": 1}

    status, body = settings_api.handle_post("/api/settings/updates", {"check": False})
    assert status == 200 and body["updates"]["check"] is False
    assert body["updates"]["auto_install"] is True  # partial payloads merge

    assert settings_api.handle_post("/api/settings/updates", {"check": "no"})[0] == 400
    assert settings_api.handle_post("/api/settings/updates", {})[0] == 400


def test_settings_get_includes_updates(monkeypatch, tmp_path, fake_manager):
    from mtga_tracker import startup

    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(startup, "_launch_target", lambda: None)
    status, body = settings_api.handle_get("/api/settings", tmp_path / "missing.sqlite3")
    assert status == 200
    assert body["updates"]["check"] is True and body["updates"]["supported"] is True
    assert body["updates"]["install_kind"] == "macos-app"
