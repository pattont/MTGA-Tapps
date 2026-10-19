"""In-app updater: versions, manifest parsing, asset choice, fetch and
download (fake sessions and a local http.server), the UpdateManager state
machine, the safety gate, the install sequence, and the next launch's
reconciliation. Offline only: nothing here reaches the network."""

import hashlib
import io
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from mtga_tracker import update_install, updater, updater_download, updater_handoff
from mtga_tracker import updater_manifest
from mtga_tracker.settings import AppSettings
from mtga_tracker.updater import UpdateBlocked, UpdateError, UpdateManager
from mtga_tracker.updater_download import (
    MANIFEST_URL,
    SIGNATURE_URL,
    DownloadError,
    FetchResult,
    UpdateNetworkError,
    UrlPolicy,
    download_asset,
    fetch_manifest,
    verify_file,
)
from mtga_tracker.updater_manifest import (
    ManifestError,
    is_newer,
    is_release_build,
    load_signed_manifest,
    parse_manifest,
    parse_version,
    select_asset,
)
from tests.update_support import (
    TEST_PUBLIC_HEX,
    FakeResponse,
    FakeSession,
    asset,
    manifest_bytes,
    manifest_doc,
    sign_b64,
    static,
)

PAYLOAD = b"tapps tracker update payload " * 64


@pytest.fixture(autouse=True)
def _test_signing_key(monkeypatch):
    monkeypatch.setattr(updater_manifest, "UPDATE_PUBLIC_KEYS", (TEST_PUBLIC_HEX,))
    monkeypatch.setattr(updater_handoff, "EXIT_BACKSTOP_S", 0.01)


# --- versions ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "newer,older",
    [
        ("0.6.5.3", "0.6.5"),
        ("0.6.5.4", "0.6.5.3"),
        ("0.6.3", "0.6.3rc8"),
        ("0.6.3rc8", "0.6.3rc7"),
        ("0.6.3rc1", "0.6.3b2"),
        ("0.7.0rc1", "0.7.0.dev3+g1a2b3c"),
        ("0.6.5.post1", "0.6.5"),
        ("v0.6.6", "0.6.5.3"),
    ],
)
def test_pep440_ordering(newer, older):
    assert is_newer(newer, older)
    assert not is_newer(older, newer)


def test_equal_and_unparsable_versions_are_never_newer():
    assert parse_version("0.6.5") == parse_version("0.6.5.0")
    assert parse_version("0.6.3rc8") == parse_version("v0.6.3-rc.8")
    assert not is_newer("0.6.5.0", "0.6.5")
    assert parse_version("0.0.0+unknown") is None
    assert parse_version("garbage") is None
    assert parse_version(None) is None
    assert not is_newer("garbage", "0.6.5")
    assert not is_newer("0.6.6", "0.0.0+unknown")
    # Local segments never order releases.
    assert not is_newer("0.6.5+abc", "0.6.5")


def test_release_build_excludes_dev_and_local_versions():
    assert is_release_build("0.6.5.3")
    assert is_release_build("0.6.3rc8")
    assert not is_release_build("0.6.5.4.dev21+g7071c7409.d20261019")
    assert not is_release_build("0.6.5+local")
    assert not is_release_build("0.0.0+unknown")


# --- manifest -----------------------------------------------------------------------


def test_parse_manifest_accepts_schema_one_and_ignores_unknown_keys():
    document = manifest_doc(
        assets=[asset(), asset(kind="dmg"), asset("windows", "x64", "inno-setup")],
        future_field={"x": 1},
    )
    document["assets"][0]["extra"] = True
    manifest = parse_manifest(document)
    assert manifest.version == "0.6.6"
    assert [a.kind for a in manifest.assets] == ["app-zip", "dmg", "inno-setup"]


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda d: d.update(schema=2), "unknown-schema"),
        (lambda d: d.update(version="not-a-version"), "bad-manifest"),
        (lambda d: d.update(tag="v0.6.7"), "bad-manifest"),
        (lambda d: d["assets"][0].update(url="http://github.com/x/y.zip"), "host-not-allowed"),
        (lambda d: d["assets"][0].update(url="https://evil.example/y.zip"), "host-not-allowed"),
        (lambda d: d["assets"][0].update(url="https://github.com:8443/y.zip"), "host-not-allowed"),
        (lambda d: d["assets"][0].update(sha256="xyz"), "bad-manifest"),
        (lambda d: d["assets"][0].update(size=0), "bad-manifest"),
        (lambda d: d["assets"][0].update(size=True), "bad-manifest"),
        (lambda d: d["assets"][0].update(name="../evil.zip"), "bad-manifest"),
        (lambda d: d["assets"][0].update(kind="msi"), "bad-manifest"),
        (lambda d: d.update(minimum_version="nope"), "bad-manifest"),
        (lambda d: d.update(mandatory="yes"), "bad-manifest"),
        (lambda d: d.update(notes_url="https://evil.example/notes"), "bad-manifest"),
    ],
)
def test_parse_manifest_rejects_unsafe_documents(mutate, code):
    document = manifest_doc()
    mutate(document)
    with pytest.raises(ManifestError) as caught:
        parse_manifest(document)
    assert caught.value.code == code


def test_signature_is_checked_before_parsing():
    body = b"{ this is not json"
    with pytest.raises(ManifestError) as caught:
        load_signed_manifest(body, sign_b64(b"something else"))
    assert caught.value.code == "bad-signature"
    good = manifest_bytes(manifest_doc())
    assert load_signed_manifest(good, sign_b64(good)).version == "0.6.6"
    tampered = good.replace(b"0.6.6", b"0.6.7")
    with pytest.raises(ManifestError):
        load_signed_manifest(tampered, sign_b64(good))
    with pytest.raises(ManifestError):
        load_signed_manifest(good, "not base64!!")


def test_select_asset_by_install_kind_and_arch():
    manifest = parse_manifest(
        manifest_doc(
            assets=[
                asset(kind="dmg"),
                asset(kind="app-zip"),
                asset("windows", "x64", "inno-setup"),
                asset("windows", "x64", "portable-zip"),
            ]
        )
    )
    pick = partial(select_asset, manifest)
    assert pick(platform="macos", arch="arm64", install_kind="macos-app").kind == "app-zip"
    assert (
        pick(platform="windows", arch="x64", install_kind="windows-installer").kind == "inno-setup"
    )
    assert pick(platform="windows", arch="x64", install_kind="windows-portable") is None
    assert pick(platform="macos", arch="x64", install_kind="macos-app") is None
    assert pick(platform="linux", arch="x64", install_kind="linux") is None
    dmg_only = parse_manifest(manifest_doc(assets=[asset(kind="dmg")]))
    assert (
        select_asset(dmg_only, platform="macos", arch="arm64", install_kind="macos-app").kind
        == "dmg"
    )


# --- fetch --------------------------------------------------------------------------


def test_fetch_manifest_ok_not_modified_not_found_and_timeout():
    body = manifest_bytes(manifest_doc())
    session = FakeSession({MANIFEST_URL: static(body, headers={"ETag": '"abc"'})})
    result = fetch_manifest(session)
    assert result == FetchResult("ok", body, '"abc"')
    assert session.calls[0]["headers"]["User-Agent"].startswith("TappsTracker/")

    def conditional(headers):
        assert headers["If-None-Match"] == '"abc"'
        return FakeResponse(304)

    assert fetch_manifest(FakeSession({MANIFEST_URL: conditional}), etag='"abc"').status == (
        "not-modified"
    )
    assert fetch_manifest(FakeSession()).status == "not-found"

    class ReadTimeout(Exception):
        pass

    with pytest.raises(UpdateNetworkError) as caught:
        fetch_manifest(FakeSession({MANIFEST_URL: lambda _h: ReadTimeout("slow")}))
    assert caught.value.code == "timeout"


def test_redirects_are_followed_only_to_allowed_hosts():
    cdn = "https://release-assets.githubusercontent.com/x/latest.json"
    body = b"{}"
    session = FakeSession(
        {
            MANIFEST_URL: static(b"", 302, {"Location": cdn}),
            cdn: static(body),
        }
    )
    assert fetch_manifest(session).body == body
    evil = FakeSession({MANIFEST_URL: static(b"", 302, {"Location": "https://evil.example/x"})})
    with pytest.raises(UpdateNetworkError) as caught:
        fetch_manifest(evil)
    assert caught.value.code == "host-not-allowed"
    downgrade = FakeSession({MANIFEST_URL: static(b"", 302, {"Location": "http://github.com/x"})})
    with pytest.raises(UpdateNetworkError):
        fetch_manifest(downgrade)


# --- download -----------------------------------------------------------------------


def _asset_obj(payload=PAYLOAD, **kwargs):
    return parse_manifest(manifest_doc(assets=[asset(payload=payload, **kwargs)])).assets[0]


def test_download_full_and_verified(tmp_path):
    item = _asset_obj()
    seen = []
    session = FakeSession({item.url: static(PAYLOAD, headers={"ETag": '"e1"'})})
    path = download_asset(item, tmp_path, session=session, progress=lambda r, t: seen.append(r))
    assert path.read_bytes() == PAYLOAD
    assert not (tmp_path / (item.name + ".part")).exists()
    assert seen[-1] == len(PAYLOAD)
    assert verify_file(path, item.sha256, item.size)
    # Already downloaded: no second request.
    download_asset(item, tmp_path, session=session)
    assert len(session.calls) == 1


def test_download_hash_mismatch_deletes_the_file(tmp_path):
    item = _asset_obj()
    wrong = bytes(reversed(PAYLOAD))
    session = FakeSession({item.url: static(wrong)})
    with pytest.raises(DownloadError) as caught:
        download_asset(item, tmp_path, session=session)
    assert caught.value.code == "sha256-mismatch"
    assert list(tmp_path.iterdir()) == []


def test_download_resumes_with_range_and_if_range(tmp_path):
    item = _asset_obj()
    part = tmp_path / (item.name + ".part")
    part.write_bytes(PAYLOAD[:100])
    (tmp_path / (item.name + ".part.json")).write_text(json.dumps({"etag": '"e1"'}))

    def ranged(headers):
        assert headers["Range"] == "bytes=100-"
        assert headers["If-Range"] == '"e1"'
        return FakeResponse(
            206, PAYLOAD[100:], {"Content-Range": f"bytes 100-{len(PAYLOAD) - 1}/*"}
        )

    path = download_asset(item, tmp_path, session=FakeSession({item.url: ranged}))
    assert path.read_bytes() == PAYLOAD


def test_download_restarts_when_the_server_answers_200(tmp_path):
    item = _asset_obj()
    (tmp_path / (item.name + ".part")).write_bytes(b"stale bytes from an older file")
    path = download_asset(item, tmp_path, session=FakeSession({item.url: static(PAYLOAD)}))
    assert path.read_bytes() == PAYLOAD


def test_download_checks_free_space_and_honours_cancel(tmp_path):
    item = _asset_obj()
    session = FakeSession({item.url: static(PAYLOAD)})
    with pytest.raises(DownloadError) as caught:
        download_asset(
            item, tmp_path, session=session, disk_usage=lambda _p: SimpleNamespace(free=10)
        )
    assert caught.value.code == "disk-space"
    with pytest.raises(DownloadError) as caught:
        download_asset(item, tmp_path, session=session, cancelled=lambda: True)
    assert caught.value.code == "cancelled"


def test_download_dropped_connection_keeps_the_part_for_resume(tmp_path):
    item = _asset_obj()
    chunks = [PAYLOAD[:500], PAYLOAD[500:]]
    session = FakeSession({item.url: lambda _h: FakeResponse(200, chunks=chunks, fail_after=1)})
    with pytest.raises(DownloadError) as caught:
        download_asset(item, tmp_path, session=session)
    assert caught.value.code == "network"
    assert (tmp_path / (item.name + ".part")).stat().st_size == 500


class _RangeHandler(BaseHTTPRequestHandler):
    body = PAYLOAD
    honour_range = True
    requests = []

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 - http.server API
        type(self).requests.append(dict(self.headers))
        data = self.body
        range_header = self.headers.get("Range")
        if range_header and self.honour_range:
            start = int(range_header.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            data = data[start:]
        else:
            self.send_response(200)
        self.send_header("ETag", '"local"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.mark.parametrize("honour_range", [True, False])
def test_download_against_a_local_http_server(tmp_path, monkeypatch, honour_range):
    import requests

    _RangeHandler.honour_range = honour_range
    _RangeHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        updater_download, "URL_POLICY", UrlPolicy(hosts=("127.0.0.1",), require_https=False)
    )
    try:
        port = server.server_address[1]
        item = updater_manifest.UpdateAsset(
            "macos",
            "arm64",
            "app-zip",
            "MTGA-Tracker-0.6.6-macos.zip",
            f"http://127.0.0.1:{port}/asset.zip",
            len(PAYLOAD),
            hashlib.sha256(PAYLOAD).hexdigest(),
        )
        (tmp_path / (item.name + ".part")).write_bytes(PAYLOAD[:300])
        path = download_asset(item, tmp_path, session=requests.Session())
        assert path.read_bytes() == PAYLOAD
        assert _RangeHandler.requests[0]["Range"] == "bytes=300-"
    finally:
        server.shutdown()
        server.server_close()


# --- the manager ----------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Harness:
    """An UpdateManager wired to fakes that record the install order."""

    def __init__(
        self,
        tmp_path,
        *,
        version="0.6.5.3",
        kind="macos-app",
        can_install=True,
        reason=None,
        document=None,
        settings=None,
        frozen=True,
        install_mode=None,
        launch_flags=None,
        routes=True,
        environ=None,
    ):
        self.tmp_path = tmp_path
        self.calls = []
        self.clock = Clock()
        self.arena = False
        self.settings = settings or AppSettings()
        self.fail_backup = False
        self.fail_install = False
        self.document = document or manifest_doc(assets=[asset(payload=PAYLOAD)])
        body = manifest_bytes(self.document)
        self.session = FakeSession()
        if routes:
            self.session.routes = {
                MANIFEST_URL: static(body, headers={"ETag": '"m1"'}),
                SIGNATURE_URL: static(sign_b64(body).encode("ascii")),
            }
            for entry in self.document["assets"]:
                self.session.routes[entry["url"]] = static(PAYLOAD)
        self.launcher = SimpleNamespace(
            tracker=None,
            tracker_is_running=True,
            output_stream=io.StringIO(),
            stop_tracker=self._stop_tracker,
            start_tracker=lambda background=True: self.calls.append("start_tracker"),
        )
        self.overlay = SimpleNamespace(
            running=True,
            stop=lambda: self.calls.append("overlay_stop"),
            start_if_enabled=lambda: self.calls.append("overlay_start"),
        )
        info = update_install.InstallInfo(
            kind,
            can_install,
            reason,
            tmp_path / "MTGA Tracker.app",
            tmp_path / "exe",
            install_mode=install_mode,
        )
        self.manager = UpdateManager(
            current_version=version,
            state_dir=tmp_path / "updates",
            install_info=info,
            frozen=frozen,
            environ=dict(environ or {}),
            session_factory=lambda: self.session,
            monotonic=self.clock,
            settings_loader=lambda: self.settings,
            arena_probe=lambda: self.arena,
            installer=SimpleNamespace(
                prepare_install=self._prepare, install_and_restart=self._install
            ),
            backup_fn=self._backup,
            overlay_factory=lambda: self.overlay,
            release_handles=lambda _db: self.calls.append("release_handles"),
            exit_backstop=lambda: None,
            log_path=tmp_path / "updater.log",
            platform_name="macos",
            arch="arm64",
        )
        tmp_path.mkdir(parents=True, exist_ok=True)
        # Tests drive the scheduler by hand through _tick().
        self.manager._ensure_worker = lambda: None
        (tmp_path / "tracker.sqlite3").touch()
        self.manager.configure(
            db_path=tmp_path / "tracker.sqlite3",
            launcher=self.launcher,
            request_exit=lambda: self.calls.append("exit"),
            launch_flags=launch_flags,
        )

    def _stop_tracker(self, timeout=3.0):
        self.calls.append("stop_tracker")
        self.launcher.tracker_is_running = False

    def _prepare(self, plan):
        self.calls.append("prepare")
        return plan

    def _install(self, plan):
        self.calls.append("install")
        self.plan = plan
        if self.fail_install:
            raise OSError("spawn failed")

    def _backup(self, db_path, from_version):
        self.calls.append(f"backup:{from_version}")
        if self.fail_backup:
            raise OSError("disk full")

    def run_check(self):
        self.manager._next_check = self.clock()
        self.manager._tick()
        return self.manager.status()

    def asset_requests(self):
        urls = {entry["url"] for entry in self.document["assets"]}
        return [call for call in self.session.calls if call["url"] in urls]


def test_source_run_checks_on_schedule_and_links_out(tmp_path):
    h = Harness(tmp_path, kind="source", can_install=False, reason="source", frozen=False)
    assert h.manager.status()["state"] == "idle"
    h.manager.start()
    try:
        assert h.manager._thread is not None  # the scheduler runs for source runs too
    finally:
        h.manager.stop()
    status = h.run_check()
    assert status["state"] == "available" and status["latest_version"] == "0.6.6"
    assert status["can_install"] is False and status["reason"] == "source"
    assert h.asset_requests() == []
    with pytest.raises(UpdateError) as caught:
        h.manager.download()
    assert caught.value.code == "unsupported"
    with pytest.raises(UpdateError):
        h.manager.request_install()
    killed = Harness(
        tmp_path / "k",
        kind="source",
        can_install=False,
        reason="source",
        frozen=False,
        environ={"MTGA_TRACKER_DISABLE_UPDATES": "1"},
    )
    killed.manager.start()
    assert killed.manager._thread is None
    assert killed.manager.status()["state"] == "disabled"


def test_dashboard_only_manager_reports_unsupported(tmp_path):
    manager = UpdateManager(
        current_version="0.6.5.3",
        state_dir=tmp_path,
        frozen=True,
        environ={},
        settings_loader=AppSettings,
    )
    status = manager.status()
    assert status["state"] == "unsupported" and status["reason"] == "dashboard-only"
    assert manager.check_now()["state"] == "unsupported"


def test_check_off_is_disabled_and_never_fetches(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(update_check=False))
    h.manager.start()
    try:
        assert h.manager.status()["state"] == "disabled"
        h.clock.advance(10_000)
        h.manager._tick()
        assert h.session.calls == []
    finally:
        h.manager.stop()


def test_kill_switch_disables_the_scheduler(tmp_path):
    h = Harness(tmp_path)
    h.manager._environ = {"MTGA_TRACKER_DISABLE_UPDATES": "1"}
    h.manager.start()
    assert h.manager._thread is None
    assert h.manager.status()["state"] == "disabled"
    assert h.manager.support()["supported"] is False


def test_available_downloads_automatically_then_ready(tmp_path):
    h = Harness(tmp_path)
    status = h.run_check()
    assert status["state"] == "ready"
    assert status["latest_version"] == "0.6.6"
    assert status["can_install"] is True and status["progress"] is None
    assert (tmp_path / "updates" / h.document["assets"][0]["name"]).read_bytes() == PAYLOAD
    assert "downloaded and verified" in h.launcher.output_stream.getvalue()
    state = json.loads((tmp_path / "updates" / "state.json").read_text())
    assert state["etag"] == '"m1"' and state["download"]["verified"] is True
    assert "available -> downloading" in (tmp_path / "updater.log").read_text()


def test_manual_download_when_auto_download_is_off(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(update_auto_download=False))
    assert h.run_check()["state"] == "available"
    assert h.asset_requests() == []
    h.manager.download()
    h.manager._tick()
    assert h.manager.status()["state"] == "ready"


def test_skipped_version_suppresses_download_but_reports_available(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(skipped_update_version="0.6.6"))
    status = h.run_check()
    assert status["state"] == "available" and status["skipped"] is True
    assert h.asset_requests() == []
    mandatory = Harness(
        tmp_path / "m",
        settings=AppSettings(skipped_update_version="0.6.6"),
        document=manifest_doc(assets=[asset(payload=PAYLOAD)], mandatory=True),
    )
    assert mandatory.run_check()["skipped"] is False


@pytest.mark.parametrize("latest", ["0.6.5.3", "0.6.5", "0.6.4"])
def test_equal_or_older_release_is_never_offered(tmp_path, latest):
    h = Harness(
        tmp_path, document=manifest_doc(latest, assets=[asset(version=latest, payload=PAYLOAD)])
    )
    status = h.run_check()
    assert status["state"] == "up_to_date"
    assert h.asset_requests() == []


def test_below_minimum_links_out(tmp_path):
    h = Harness(
        tmp_path, document=manifest_doc(assets=[asset(payload=PAYLOAD)], minimum_version="0.6.6")
    )
    status = h.run_check()
    assert status["state"] == "available" and status["below_minimum"] is True
    assert status["can_install"] is False and status["reason"] == "manual-required"
    assert h.asset_requests() == []


def test_bad_signature_is_an_error_and_downloads_nothing(tmp_path):
    h = Harness(tmp_path)
    h.session.routes[SIGNATURE_URL] = static(sign_b64(b"other bytes").encode("ascii"))
    status = h.run_check()
    assert status["state"] == "error" and status["error"]["code"] == "bad-signature"
    assert h.asset_requests() == []


def test_not_modified_reuses_the_cached_signed_manifest(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(update_auto_download=False))
    h.run_check()
    h.session.routes[MANIFEST_URL] = lambda headers: FakeResponse(
        304 if headers.get("If-None-Match") == '"m1"' else 500
    )
    h.session.routes.pop(SIGNATURE_URL)
    assert h.run_check()["state"] == "available"


def test_missing_manifest_is_not_an_error(tmp_path):
    h = Harness(tmp_path, routes=False)
    status = h.run_check()
    # No release information at all is "idle" with a check time, never
    # "up to date" (the UI says no release information was available).
    assert status["state"] == "idle"
    assert status["last_check"] and status["latest_version"] is None
    assert status["error"] is None
    # Once a manifest was seen, a later 404 keeps what is known.
    seen = Harness(tmp_path / "seen", settings=AppSettings(update_auto_download=False))
    seen.run_check()
    seen.session.routes = {}
    seen.manager._runtime.pop("etag", None)
    assert seen.run_check()["state"] == "available"


def test_portable_copy_reports_available_and_links_out(tmp_path):
    h = Harness(tmp_path, kind="windows-portable", can_install=False, reason="portable")
    status = h.run_check()
    assert status["state"] == "available" and status["reason"] == "portable"
    assert h.asset_requests() == []


def test_cached_download_is_ready_after_restart_and_corruption_is_deleted(tmp_path):
    first = Harness(tmp_path)
    first.run_check()
    second = Harness(tmp_path, routes=False)
    second.manager._startup_tasks()
    assert second.manager.status()["state"] == "ready"
    assert second.session.calls == []

    target = tmp_path / "updates" / first.document["assets"][0]["name"]
    target.write_bytes(b"corrupted")
    third = Harness(tmp_path, routes=False)
    third.manager._startup_tasks()
    assert third.manager.status()["state"] == "available"
    assert not target.exists()


# --- the gate -----------------------------------------------------------------------


def _live_db(path, *, in_game=0, heartbeat_age=1.0, ended_ago=None):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE live_status (id INTEGER PRIMARY KEY, updated_at TEXT, in_game INTEGER)"
    )
    conn.execute(
        "INSERT INTO live_status VALUES (1, ?, ?)",
        ((datetime.now() - timedelta(seconds=heartbeat_age)).isoformat(), in_game),
    )
    conn.execute("CREATE TABLE games (id TEXT, ended_at TEXT)")
    if ended_ago is not None:
        conn.execute(
            "INSERT INTO games VALUES ('G1', ?)",
            ((datetime.now() - timedelta(seconds=ended_ago)).isoformat(),),
        )
    conn.commit()
    conn.close()


def test_gate_reads_the_live_row_and_recent_game_end(tmp_path):
    h = Harness(tmp_path)
    db = tmp_path / "tracker.sqlite3"
    _live_db(db, in_game=1)
    assert h.manager.busy_reasons("manual") == ["game-in-progress"]
    db.unlink()
    _live_db(db, in_game=1, heartbeat_age=600)  # a dead tracker's stale flag
    fresh = Harness(tmp_path)
    assert fresh.manager.busy_reasons("manual") == []
    db.unlink()
    _live_db(db, ended_ago=30)
    assert Harness(tmp_path).manager.busy_reasons("manual") == ["game-in-progress"]
    db.unlink()
    _live_db(db, ended_ago=180)
    assert Harness(tmp_path).manager.busy_reasons("manual") == []


def test_gate_remembers_a_game_for_two_minutes(tmp_path):
    h = Harness(tmp_path)
    db = tmp_path / "tracker.sqlite3"
    _live_db(db, in_game=1)
    assert h.manager.busy_reasons("auto") == ["game-in-progress"]
    db.unlink()
    _live_db(db, in_game=0)
    h.clock.advance(60)
    assert h.manager.busy_reasons("manual") == ["game-in-progress"]
    h.clock.advance(61)
    assert h.manager.busy_reasons("manual") == []


def test_gate_uses_in_process_tracker_state(tmp_path):
    h = Harness(tmp_path)
    game = SimpleNamespace(
        in_match=True,
        game_start_time=datetime.now(),
        match_complete=False,
        match_type="best_of_1",
        arena_match_over=False,
        game_end_time=None,
        authoritative_event_id=None,
    )
    h.launcher.tracker = SimpleNamespace(game_state=game, waiting_for_next_game=False)
    assert h.manager.busy_reasons("manual") == ["game-in-progress"]
    # Between best-of-three games: in_game reads 0 but the match continues.
    game.match_complete = True
    game.match_type = "best_of_3"
    game.game_end_time = datetime.now() - timedelta(minutes=5)
    assert Harness(tmp_path).manager.busy_reasons("manual") == []  # no tracker there
    h2 = Harness(tmp_path)
    h2.launcher.tracker = SimpleNamespace(game_state=game, waiting_for_next_game=False)
    assert h2.manager.busy_reasons("manual") == ["game-in-progress"]
    game.arena_match_over = True
    h3 = Harness(tmp_path)
    h3.launcher.tracker = SimpleNamespace(game_state=game, waiting_for_next_game=True)
    assert h3.manager.busy_reasons("manual") == ["game-in-progress"]


def test_arena_blocks_auto_install_and_asks_for_manual(tmp_path):
    h = Harness(tmp_path)
    h.arena = True
    assert h.manager.busy_reasons("auto") == ["arena-running"]
    assert h.manager.busy_reasons("manual") == ["arena-running"]
    assert h.manager.busy_reasons("pending") == []
    assert h.manager.busy_reasons("forced") == []
    h.arena = None  # the probe failed: unknown blocks only unattended installs
    assert h.manager.busy_reasons("auto") == ["arena-running"]
    assert h.manager.busy_reasons("manual") == []


def test_jobs_block_even_a_forced_install(tmp_path, monkeypatch):
    from mtga_tracker import backup_api, collection_api, deck_native_api

    h = Harness(tmp_path)
    monkeypatch.setattr(deck_native_api, "job_active", lambda: True)
    monkeypatch.setattr(collection_api, "job_running", lambda: True)
    monkeypatch.setattr(backup_api, "restore_in_progress", lambda: True)
    assert h.manager.busy_reasons("forced") == [
        "deck-transfer",
        "collection-export",
        "backup-restore",
    ]


# --- install sequence ----------------------------------------------------------------


def _ready(tmp_path, **kwargs):
    h = Harness(tmp_path, **kwargs)
    assert h.run_check()["state"] == "ready"
    h.calls.clear()
    return h


def _run_install(h):
    h.clock.advance(1.0)
    h.manager._tick()


def test_install_runs_the_sequence_in_order(tmp_path):
    h = _ready(tmp_path)
    status = h.manager.request_install()
    assert status["state"] == "installing"
    assert h.calls == []  # answers first; the worker runs the hand-off later
    _run_install(h)
    assert h.calls == [
        "prepare",
        "backup:0.6.5.3",
        "stop_tracker",
        "release_handles",
        "overlay_stop",
        "install",
        "exit",
    ]
    pending = json.loads((tmp_path / "updates" / "pending.json").read_text())
    assert pending["from"] == "0.6.5.3" and pending["to"] == "0.6.6"
    assert h.plan.relaunch is True and h.plan.to_version == "0.6.6"
    assert h.manager.wait_for_handoff(0.1) == "exit"
    assert "Installing update v0.6.6" in h.launcher.output_stream.getvalue()


def test_backup_failure_aborts_before_anything_stops(tmp_path):
    h = _ready(tmp_path)
    h.fail_backup = True
    h.manager.request_install()
    _run_install(h)
    assert h.calls == ["prepare", "backup:0.6.5.3"]
    status = h.manager.status()
    assert status["state"] == "error" and status["error"]["code"] == "backup-failed"
    assert not (tmp_path / "updates" / "pending.json").exists()
    assert h.manager.wait_for_handoff(0.1) == "none"


def test_handoff_failure_restarts_tracker_and_overlay(tmp_path):
    h = _ready(tmp_path)
    h.fail_install = True
    h.manager.request_install()
    _run_install(h)
    assert h.calls[-3:] == ["install", "start_tracker", "overlay_start"]
    assert "exit" not in h.calls
    assert h.manager.status()["error"]["code"] == "handoff-failed"
    assert h.manager.wait_for_handoff(0.1) == "resumed"


def test_tracker_that_will_not_stop_aborts(tmp_path):
    h = _ready(tmp_path)
    h.launcher.stop_tracker = lambda timeout=3.0: h.calls.append("stop_tracker")
    h.manager.request_install()
    _run_install(h)
    assert "install" not in h.calls
    # The slow tracker is still running: starting another would mean two
    # trackers tailing Player.log into one database.
    assert "start_tracker" not in h.calls
    assert h.manager.status()["error"]["code"] == "tracker-busy"


def test_install_reverifies_the_download(tmp_path):
    h = _ready(tmp_path)
    (tmp_path / "updates" / h.document["assets"][0]["name"]).write_bytes(b"tampered")
    h.manager.request_install()
    _run_install(h)
    assert h.calls == []
    assert h.manager.status()["error"]["code"] == "sha256-mismatch"


def test_busy_install_is_refused_until_forced(tmp_path):
    h = _ready(tmp_path)
    _live_db(tmp_path / "tracker.sqlite3", in_game=1)
    with pytest.raises(UpdateBlocked) as caught:
        h.manager.request_install()
    assert caught.value.code == "game-in-progress"
    assert caught.value.blocked_by == ["game-in-progress"]
    h.clock.advance(6)  # the status payload caches the gate for a few seconds
    assert h.manager.status()["blocked_by"] == ["game-in-progress"]
    h.manager.request_install(force=True)
    _run_install(h)
    assert "install" in h.calls


def test_install_when_not_ready_is_refused(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(update_auto_download=False))
    h.run_check()
    with pytest.raises(UpdateError) as caught:
        h.manager.request_install()
    assert caught.value.code == "not-ready"


def test_install_after_this_game_waits_for_the_gate(tmp_path):
    h = _ready(tmp_path)
    db = tmp_path / "tracker.sqlite3"
    _live_db(db, in_game=1)
    h.arena = True
    h.manager.request_install(when="idle")
    assert h.manager.status()["pending_install"] is True
    h.clock.advance(20)
    h.manager._tick()
    assert "install" not in h.calls
    db.unlink()
    _live_db(db, in_game=0)
    h.clock.advance(200)
    h.manager._tick()
    assert "install" in h.calls  # Arena still open: the user asked for it
    assert h.manager.status()["pending_install"] is False


def test_auto_install_needs_arena_closed(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(auto_install_updates=True))
    h.arena = None
    assert h.run_check()["state"] == "ready"
    h.clock.advance(20)
    h.manager._tick()
    assert "install" not in h.calls
    h.arena = False
    h.clock.advance(20)
    h.manager._tick()
    assert "install" in h.calls


def test_all_users_install_never_auto_installs(tmp_path):
    h = _ready(tmp_path, settings=AppSettings(auto_install_updates=True), install_mode="admin")
    assert h.manager.status()["needs_elevation"] is True
    h.clock.advance(20)
    h.manager._tick()
    assert "install" not in h.calls


def test_install_and_quit_suppresses_the_relaunch(tmp_path):
    h = _ready(tmp_path)
    h.manager.request_install(force=True, relaunch=False)
    _run_install(h)
    assert h.plan.relaunch is False


# --- after the restart -----------------------------------------------------------------


def _pending(tmp_path, to="0.6.6"):
    updates = tmp_path / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    (updates / "pending.json").write_text(
        json.dumps({"from": "0.6.5.3", "to": to, "notes_url": "https://github.com/x", "log": "L"})
    )
    (updates / "MTGA-Tracker-0.6.6-macos.zip").write_bytes(PAYLOAD)
    return updates


def test_successful_update_is_recorded_once(tmp_path):
    updates = _pending(tmp_path)
    h = Harness(tmp_path, version="0.6.6", routes=False, launch_flags={"after_update": True})
    h.manager._startup_tasks()
    status = h.manager.status()
    assert status["just_updated"] == {
        "from": "0.6.5.3",
        "to": "0.6.6",
        "notes_url": "https://github.com/x",
        "ok": True,
    }
    assert not (updates / "pending.json").exists()
    assert not (updates / "MTGA-Tracker-0.6.6-macos.zip").exists()
    assert (updates / "healthy-0.6.6").exists()
    assert "Updated from 0.6.5.3 to 0.6.6" in h.launcher.output_stream.getvalue()
    assert h.manager.acknowledge()["just_updated"] is None
    again = Harness(tmp_path, version="0.6.6", routes=False)
    again.manager._startup_tasks()
    assert again.manager.status()["just_updated"] is None


def test_install_not_applied_keeps_the_download(tmp_path):
    updates = _pending(tmp_path)
    first = Harness(tmp_path)
    first.run_check()  # records the verified download in state.json
    h = Harness(tmp_path, routes=False)
    h.manager._startup_tasks()
    status = h.manager.status()
    assert status["state"] == "error" and status["error"]["code"] == "install-not-applied"
    assert status["just_updated"]["ok"] is False
    assert (updates / "MTGA-Tracker-0.6.6-macos.zip").exists()


def test_update_failed_flag_reports_install_failed(tmp_path):
    _pending(tmp_path)
    h = Harness(tmp_path, routes=False, launch_flags={"update_failed": "0.6.6"})
    h.manager._startup_tasks()
    status = h.manager.status()
    assert status["error"]["code"] == "install-failed"
    assert "L" in status["error"]["message"]
    # A failed version is never auto-installed again.
    assert "0.6.6" in h.manager._runtime["failed_versions"]


def test_healthy_runtime_removes_the_rollback_copy(tmp_path):
    h = Harness(tmp_path)
    rollback = tmp_path / "updates" / "rollback" / "MTGA Tracker.app"
    rollback.mkdir(parents=True)
    h.manager._started_at = h.clock()
    h.manager._healthy_tasks()
    assert rollback.exists()
    h.clock.advance(61)
    h.manager._healthy_tasks()
    assert not rollback.parent.exists()


def test_settings_changed_toggles_disabled(tmp_path):
    h = Harness(tmp_path)
    h.manager.start()
    try:
        h.settings = AppSettings(update_check=False)
        h.manager.settings_changed()
        assert h.manager.status()["state"] == "disabled"
        h.settings = AppSettings(update_check=True)
        h.manager.settings_changed()
        assert h.manager.status()["state"] == "idle"
    finally:
        h.manager.stop()


def test_get_manager_is_a_singleton(monkeypatch):
    monkeypatch.setattr(updater, "_manager", None)
    assert updater.get_manager() is updater.get_manager()


def test_scheduler_sleeps_while_ready_instead_of_spinning(tmp_path):
    h = _ready(tmp_path)
    h.clock.advance(updater.CHECK_INTERVAL_S * 2)  # the next check is long overdue
    timeout = h.manager._tick()
    # Ready: wake every 15 s to re-sample the gate, never the 50 ms floor.
    assert timeout == updater.IDLE_WAKE_S
    assert h.manager.status()["state"] == "ready"
    armed = Harness(tmp_path / "armed", settings=AppSettings(auto_install_updates=True))
    armed.arena = True
    assert armed.run_check()["state"] == "ready"
    armed.clock.advance(updater.CHECK_INTERVAL_S * 2)
    assert armed.manager._tick() == updater.IDLE_WAKE_S


def test_first_check_waits_ninety_seconds(tmp_path):
    h = Harness(tmp_path)
    h.manager._started_at = h.clock()
    h.manager._next_check = h.clock() + updater.FIRST_CHECK_DELAY_S
    assert h.manager._tick() == pytest.approx(updater.HEALTHY_AFTER_S)
    assert h.session.calls == []
    h.clock.advance(updater.FIRST_CHECK_DELAY_S)
    h.manager._tick()
    assert h.session.calls[0]["url"] == MANIFEST_URL
    # The following check is six hours away, with up to 10 % jitter.
    delay = h.manager._next_check - h.clock()
    assert updater.CHECK_INTERVAL_S * 0.9 <= delay <= updater.CHECK_INTERVAL_S * 1.1


def test_scheduler_thread_end_to_end(tmp_path):
    h = Harness(tmp_path)
    manager = h.manager
    manager._monotonic = time.monotonic
    del manager._ensure_worker  # use the real method again
    manager.start()
    try:
        assert manager._thread is not None and manager._thread.name == "mtga-updater"
        manager.check_now()
        deadline = time.time() + 10
        while manager.status()["state"] != "ready" and time.time() < deadline:
            time.sleep(0.02)
        assert manager.status()["state"] == "ready"
        response = manager.request_install()
        assert response["state"] == "installing"
        while "exit" not in h.calls and time.time() < deadline:
            time.sleep(0.02)
        assert h.calls[-1] == "exit"
        assert manager.wait_for_handoff(1.0) == "exit"
    finally:
        manager.stop()
    assert manager._thread is None


# --- review regressions -----------------------------------------------------------


@pytest.mark.parametrize(
    "route",
    [
        lambda _h: ConnectionError("offline"),
        lambda _h: FakeResponse(404),
        "older",
    ],
)
def test_failed_or_empty_recheck_keeps_the_ready_download(tmp_path, route):
    h = _ready(tmp_path)
    if route == "older":
        older = manifest_bytes(manifest_doc("0.6.5", assets=[asset(version="0.6.5")]))
        h.session.routes[MANIFEST_URL] = static(older)
        h.session.routes[SIGNATURE_URL] = static(sign_b64(older).encode("ascii"))
        h.manager._runtime.pop("etag", None)
    else:
        h.session.routes[MANIFEST_URL] = route
    h.manager.check_now()
    h.manager._tick()
    status = h.manager.status()
    assert status["state"] == "ready" and status["latest_version"] == "0.6.6"
    assert status["error"] is None
    assert (tmp_path / "updates" / h.document["assets"][0]["name"]).is_file()
    h.manager.request_install()
    _run_install(h)
    assert "install" in h.calls


def test_failed_check_with_nothing_ready_is_an_error(tmp_path):
    h = Harness(tmp_path)
    h.session.routes[MANIFEST_URL] = lambda _h: ConnectionError("offline")
    assert h.run_check()["state"] == "error"


def test_foreground_tracker_must_really_stop_before_the_handoff(tmp_path):
    h = _ready(tmp_path)
    loop_done = threading.Event()

    def stop_tracker(timeout=3.0):
        h.calls.append("stop_tracker")
        # Like --no-gui: only a request; the main-thread loop ends a bit later.
        threading.Timer(0.2, lambda: (h.calls.append("loop-ended"), loop_done.set())).start()

    h.launcher.stop_tracker = stop_tracker
    h.launcher.tracker_is_running = False  # no tracker thread in --no-gui mode
    h.launcher.wait_tracker_stopped = loop_done.wait
    h.manager.request_install()
    _run_install(h)
    assert h.calls.index("loop-ended") < h.calls.index("release_handles")
    assert h.calls[-1] == "exit"


def test_foreground_tracker_that_never_stops_aborts(tmp_path):
    h = _ready(tmp_path)
    h.launcher.tracker_is_running = False
    h.launcher.wait_tracker_stopped = lambda timeout: False
    h.manager.request_install()
    _run_install(h)
    assert "install" not in h.calls and "release_handles" not in h.calls
    assert h.manager.status()["error"]["code"] == "tracker-busy"


@pytest.mark.parametrize("failure", ["backup", "install", "stage"])
def test_install_and_quit_quits_even_when_the_install_fails(tmp_path, failure):
    h = _ready(tmp_path)
    if failure == "backup":
        h.fail_backup = True
    elif failure == "install":
        h.fail_install = True
    else:

        def broken(plan):
            raise update_install.InstallError("bad zip", "stage-failed")

        h.manager._installer.prepare_install = broken
    h.manager.request_install(force=True, relaunch=False)
    _run_install(h)
    assert h.calls[-1] == "exit"
    assert "start_tracker" not in h.calls and "overlay_start" not in h.calls
    assert h.manager.status()["state"] == "error"
    assert h.manager.wait_for_handoff(0.1) == "none"


def test_skip_accepts_every_version_the_manager_parses(tmp_path, monkeypatch):
    from mtga_tracker import settings as settings_module

    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "settings.json")
    h = Harness(tmp_path, settings=None)
    h.manager._settings_loader = None
    for version in ("0.7.0.dev3+g1a2b3c", "v0.6.3-rc.8", "0.6.5.post1"):
        h.manager.skip(version)
        assert settings_module.load_app_settings(create=False).skipped_update_version == version
    with pytest.raises(UpdateError):
        h.manager.skip("0.0.0+unknown")


def test_startup_and_abort_remove_staging_folders_but_not_the_bundle(tmp_path):
    h = Harness(tmp_path)
    app_parent = tmp_path
    stage_sibling = app_parent / ".tapps-update-0.6.6"
    rollback_sibling = app_parent / ".tapps-update-rollback"
    outside = tmp_path / "elsewhere"
    for folder in (
        stage_sibling / "MTGA Tracker.app",
        rollback_sibling,
        outside,
        tmp_path / "updates" / "stage" / "x",
        tmp_path / "MTGA Tracker.app",
    ):
        folder.mkdir(parents=True, exist_ok=True)
    (app_parent / ".tapps-update-link").symlink_to(outside, target_is_directory=True)
    h.manager._startup_tasks()
    assert not stage_sibling.exists() and not (tmp_path / "updates" / "stage").exists()
    assert rollback_sibling.is_dir() and outside.is_dir()
    assert (tmp_path / "MTGA Tracker.app").is_dir()

    ready = _ready(tmp_path / "abort")
    sibling = tmp_path / "abort" / ".tapps-update-0.6.6"

    def stage_then_fail(plan):
        sibling.mkdir()
        raise update_install.InstallError("codesign", "codesign-failed")

    ready.manager._installer.prepare_install = stage_then_fail
    ready.manager.request_install()
    _run_install(ready)
    assert not sibling.exists()
    assert ready.manager.status()["error"]["code"] == "codesign-failed"


def test_status_never_probes_arena_on_the_request_thread(tmp_path):
    h = _ready(tmp_path)
    probes = []
    h.manager._arena_probe = lambda: probes.append(True) or True
    for _ in range(5):
        h.manager.status()
    assert probes == []
    h.clock.advance(20)
    h.manager._tick()
    assert len(probes) == 1
    assert h.manager.status()["blocked_by"] == ["arena-running"]
    with pytest.raises(UpdateBlocked):
        h.manager.request_install()  # the POST still evaluates the gate fresh
    assert len(probes) == 2


def test_complete_part_file_is_finished_without_a_request(tmp_path):
    item = _asset_obj()
    (tmp_path / (item.name + ".part")).write_bytes(PAYLOAD)
    session = FakeSession()
    path = download_asset(item, tmp_path, session=session)
    assert path.read_bytes() == PAYLOAD and session.calls == []
    assert not (tmp_path / (item.name + ".part")).exists()
    # A full-length part with the wrong bytes restarts from zero.
    path.unlink()
    (tmp_path / (item.name + ".part")).write_bytes(b"x" * len(PAYLOAD))
    session = FakeSession({item.url: static(PAYLOAD)})
    assert download_asset(item, tmp_path, session=session).read_bytes() == PAYLOAD
    assert "Range" not in session.calls[0]["headers"]


class _ReleaseServer(BaseHTTPRequestHandler):
    files = {}

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 - http.server API
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_manifest_url_override_serves_a_local_validation_release(tmp_path):
    import requests

    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReleaseServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        entry = asset(payload=PAYLOAD)
        entry["url"] = f"{base}/{entry['name']}"
        body = manifest_bytes(manifest_doc(assets=[entry]))
        _ReleaseServer.files = {
            "/latest.json": body,
            "/latest.json.sig": sign_b64(body).encode("ascii"),
            f"/{entry['name']}": PAYLOAD,
        }
        env = {updater.MANIFEST_URL_ENV: f"{base}/latest.json"}
        logged = Harness(tmp_path / "log", environ=env, routes=False)
        logged.manager.start()
        logged.manager.stop()
        log_text = (tmp_path / "log" / "updater.log").read_text()
        assert "MTGA_TRACKER_UPDATE_MANIFEST_URL is set" in log_text
        h = Harness(tmp_path, environ=env, routes=False)
        h.manager._session_factory = requests.Session
        status = h.run_check()
        assert status["state"] == "ready", status

        # The signature is still mandatory with the override.
        _ReleaseServer.files["/latest.json.sig"] = sign_b64(b"tampered").encode("ascii")
        bad = Harness(tmp_path / "bad", environ=env, routes=False)
        bad.manager._session_factory = requests.Session
        assert bad.run_check()["error"]["code"] == "bad-signature"
    finally:
        server.shutdown()
        server.server_close()

    # Without the override a manifest naming that host is refused.
    with pytest.raises(ManifestError) as caught:
        parse_manifest(manifest_doc(assets=[entry]))
    assert caught.value.code == "host-not-allowed"
    assert updater_download.manifest_override({updater.MANIFEST_URL_ENV: "ftp://x/y"}) is None


# --- second review pass -------------------------------------------------------------


def test_pending_journal_records_the_relaunch_command_line(tmp_path):
    h = _ready(tmp_path)
    h.manager._argv = [
        "--no-gui",
        "--db",
        "rel/tracker.sqlite3",
        "--port",
        "9000",
        "--after-update",
        "--updated-from",
        "0.6.5.2",
        "--update-failed",
    ]
    written = []
    real = updater_handoff._write_json_atomic
    updater_handoff._write_json_atomic = lambda path, data: written.append(data) or real(path, data)
    try:
        h.manager.request_install()
        _run_install(h)
    finally:
        updater_handoff._write_json_atomic = real
    args = written[0]["relaunch_args"]
    assert args[:2] == ["--no-gui", "--db"] and Path(args[2]).is_absolute()
    assert args[3:] == ["--port", "9000"]


def test_relaunch_arguments_strip_update_flags():
    from mtga_tracker.updater_support import relaunch_arguments

    cwd = Path("/work")
    assert relaunch_arguments(
        [
            "--login-start",
            "-psn_0_123",
            "--db=data/x.sqlite3",
            "--update-failed",
            "0.6.6",
            "--log-path",
            "/abs/Player.log",
            "--updated-from=0.6.5",
            "--no-browser",
        ],
        cwd,
    ) == ["--db=/work/data/x.sqlite3", "--log-path", "/abs/Player.log", "--no-browser"]
    assert relaunch_arguments(["--update-failed", "--no-gui"], cwd) == ["--no-gui"]


def test_no_gui_waits_for_a_slow_handoff_and_abandons_only_at_the_limit(tmp_path):
    h = _ready(tmp_path)
    h.manager._monotonic = time.monotonic
    release = threading.Event()

    def slow_release(_db):
        h.calls.append("release_handles")
        release.wait(5)

    h.manager._release_handles = slow_release
    h.manager.request_install()
    h.manager._install_request["at"] = 0
    worker = threading.Thread(target=h.manager._tick)
    worker.start()
    threading.Timer(1.5, release.set).start()  # slower than any short timeout
    assert h.manager.wait_for_handoff(timeout=30) == "exit"
    worker.join(5)
    assert h.calls[-2:] == ["install", "exit"]

    stuck = _ready(tmp_path / "stuck")
    stuck.manager._monotonic = time.monotonic
    gate = threading.Event()
    stuck.manager._release_handles = lambda _db: gate.wait(5)
    stuck.manager.request_install()
    stuck.manager._install_request["at"] = 0
    worker = threading.Thread(target=stuck.manager._tick)
    worker.start()
    time.sleep(0.2)
    assert stuck.manager.wait_for_handoff(timeout=0.3) == "resumed"
    gate.set()
    worker.join(5)
    assert "install" not in stuck.calls and "exit" not in stuck.calls
    assert not (tmp_path / "stuck" / "updates" / "pending.json").exists()
    assert stuck.manager.status()["error"]["code"] == "handoff-timeout"


def test_update_failed_without_a_journal_names_no_version(tmp_path):
    h = Harness(tmp_path, routes=False, launch_flags={"update_failed": "unknown"})
    (tmp_path / "updates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "updates" / "install-0.6.6.log").write_text("log")
    h.manager._startup_tasks()
    status = h.manager.status()
    assert status["error"]["code"] == "install-failed"
    assert status["error"]["message"].startswith("The last update did not finish")
    assert "install-0.6.6.log" in status["error"]["message"]
    assert "vunknown" not in status["error"]["message"]
    assert h.manager._runtime.get("failed_versions", []) == []


def test_runtime_capable_is_gone():
    assert not hasattr(UpdateManager, "runtime_capable")


def test_status_reads_settings_once_until_they_change(tmp_path):
    h = Harness(tmp_path)
    loads = []
    h.manager._settings_loader = lambda: loads.append(True) or h.settings
    h.manager._invalidate_settings()
    for _ in range(5):
        h.manager.status()
    assert len(loads) == 1
    h.settings = AppSettings(update_auto_download=False)
    h.manager.settings_changed()
    assert h.manager.status()["auto_download"] is False
    assert len(loads) == 2


def test_auto_install_evaluates_the_gate_once(tmp_path):
    h = Harness(tmp_path, settings=AppSettings(auto_install_updates=True))
    h.arena = True
    h.run_check()
    h.arena = False
    calls = []
    real = h.manager.busy_reasons
    h.manager.busy_reasons = lambda gate="auto": calls.append(gate) or real(gate)
    h.clock.advance(20)
    h.manager._tick()
    assert "install" in h.calls
    assert calls == ["auto"]
