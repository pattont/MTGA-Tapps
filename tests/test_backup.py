"""Backups: the .tappsbackup round trip, the restore guard, migration on
restore, machine-local settings, and synced-folder detection."""

import json
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mtga_tracker import backup
from mtga_tracker.analytics import AnalyticsStore


def _db(path: Path, game_ids, *, raw_payloads=1, heartbeat=None) -> Path:
    """A database with the given games (plus the tables a restore must
    carry), a raw-payload row that must NOT travel, and a live row."""
    store = AnalyticsStore(path)
    conn = store.connect()
    for index, game_id in enumerate(game_ids):
        started = (datetime(2026, 9, 1, 10, 0, 0) + timedelta(hours=index)).isoformat()
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES (?, ?) ON CONFLICT DO NOTHING",
            ("S", "2026-09-01T09:00:00"),
        )
        conn.execute("INSERT INTO matches (id, session_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (f"M{index}", "S"))
        conn.execute(
            "INSERT INTO games (id, session_id, match_id, started_at) VALUES (?, ?, ?, ?)",
            (game_id, "S", f"M{index}", started),
        )
        conn.execute(
            "INSERT INTO participants (id, game_id, role, deck_name) VALUES (?, ?, 'player', 'Dragons')",
            (f"{game_id}-p", game_id),
        )
    for _ in range(raw_payloads):
        conn.execute(
            "INSERT INTO raw_game_payloads (session_id, created_at, payload_type, payload_json) VALUES ('S', '2026-09-01T09:00:00', 'x', '{}')"
        )
    conn.execute(
        "INSERT OR REPLACE INTO live_status (id, session_id, updated_at, in_game) VALUES (1, 'S', ?, 0)",
        ((heartbeat or datetime(2020, 1, 1)).isoformat(),),
    )
    conn.commit()
    store.close()
    return path


def _settings(path: Path, **extra) -> Path:
    document = {
        "live_log_window": {"width": 1400, "height": 1020},
        "dashboard": {"port": 8765},
        "deck_ai": {"DECK_LLM_ENABLED": True, "CHATGPT_API_KEY": "sk-secret", "DECK_LLM_OPENAI_MODEL": "gpt"},
        "backup": {"install_id": "home00000001", "folder": str(path.parent / "cloud")},
    }
    document.update(extra)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _games(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT id FROM games ORDER BY started_at")]
    finally:
        conn.close()


class FakeTracker:
    def __init__(self, running=True):
        self.tracker_is_running = running
        self.calls = []

    def stop_tracker(self):
        self.calls.append("stop")
        self.tracker_is_running = False

    def start_tracker(self, *, background=True):
        self.calls.append("start")
        self.tracker_is_running = True


def test_export_writes_a_backup_with_manifest_and_no_diagnostics(tmp_path):
    db = _db(tmp_path / "tracker.sqlite3", ["g1", "g2", "g3"], raw_payloads=3)
    settings = _settings(tmp_path / "settings.json")
    deckfinder = tmp_path / "deckfinder_config.json"
    deckfinder.write_text('{"moxfield": ["Ash"]}')
    overlay = tmp_path / "overlay.json"
    overlay.write_text('{"scale": 120}')

    result = backup.export_backup(
        db,
        tmp_path / "cloud",
        settings_path=settings,
        deckfinder_path=deckfinder,
        overlay_path=overlay,
        machine="Desktop",
        now=datetime(2026, 9, 11, 3, 4, 5),
    )

    path = Path(result["path"])
    assert path.name == "TappsTracker-Desktop-20260911-030405.tappsbackup"
    assert result["games"] == 3 and result["schema_version"] == backup.supported_schema_version()
    assert result["install_id"] == "home00000001" and "game_ids" not in result
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "tracker.sqlite3", "settings.json", "deckfinder_config.json", "overlay.json"} <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["game_ids"] == ["g1", "g2", "g3"]
        shipped_settings = json.loads(archive.read("settings.json"))
        # This computer's own sections never travel; the API key does by default.
        assert "backup" not in shipped_settings and "dashboard" not in shipped_settings
        assert shipped_settings["deck_ai"]["CHATGPT_API_KEY"] == "sk-secret"
        archive.extract("tracker.sqlite3", tmp_path / "peek")
    conn = sqlite3.connect(tmp_path / "peek" / "tracker.sqlite3")
    assert conn.execute("SELECT COUNT(*) FROM raw_game_payloads").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM live_status").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 3
    conn.close()
    # The last backup is remembered for the Settings card.
    assert backup.backup_settings(settings)["last_backup"]["games"] == 3
    # The original database is untouched.
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM raw_game_payloads").fetchone()[0] == 3
    conn.close()


def test_export_can_leave_api_keys_out(tmp_path):
    db = _db(tmp_path / "tracker.sqlite3", ["g1"])
    settings = _settings(tmp_path / "settings.json")
    result = backup.export_backup(db, tmp_path / "cloud", settings_path=settings, include_keys=False, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    with zipfile.ZipFile(result["path"]) as archive:
        shipped = json.loads(archive.read("settings.json"))
    assert "CHATGPT_API_KEY" not in shipped["deck_ai"]
    assert shipped["deck_ai"]["DECK_LLM_OPENAI_MODEL"] == "gpt"
    assert result["include_keys"] is False


def test_inspect_reports_what_a_restore_adds_and_drops(tmp_path):
    desktop = _db(tmp_path / "desktop.sqlite3", ["g1", "g2", "g3"])
    settings = _settings(tmp_path / "settings.json")
    made = backup.export_backup(desktop, tmp_path / "cloud", settings_path=settings, machine="Desktop", overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")

    laptop_fresh = tmp_path / "fresh.sqlite3"
    assert backup.inspect_backup(made["path"], laptop_fresh, settings_path=settings)["verdict"] == "fresh"

    laptop = _db(tmp_path / "laptop.sqlite3", ["g1", "g2"])
    preview = backup.inspect_backup(made["path"], laptop, settings_path=settings)
    assert (preview["adds"], preview["drops"], preview["verdict"], preview["requires_confirm"]) == (1, 0, "newer", False)
    assert preview["same_install"] is True and preview["schema_ok"] is True

    laptop_played = _db(tmp_path / "played.sqlite3", ["g1", "g2", "g3", "L1", "L2"])
    preview = backup.inspect_backup(made["path"], laptop_played, settings_path=settings)
    assert (preview["adds"], preview["drops"], preview["verdict"], preview["requires_confirm"]) == (0, 2, "older", True)

    diverged = _db(tmp_path / "diverged.sqlite3", ["g1", "L1"])
    assert backup.inspect_backup(made["path"], diverged, settings_path=settings)["verdict"] == "diverged"


def test_restore_replaces_database_keeps_local_settings_and_leaves_an_undo(tmp_path):
    desktop = _db(tmp_path / "desktop.sqlite3", ["g1", "g2", "g3"])
    desktop_settings = _settings(tmp_path / "desktop-settings.json")
    made = backup.export_backup(desktop, tmp_path / "cloud", settings_path=desktop_settings, machine="Desktop", overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")

    laptop = _db(tmp_path / "laptop" / "tracker.sqlite3", ["g1"])
    laptop_settings = _settings(
        tmp_path / "laptop" / "settings.json",
        dashboard={"port": 9999},
        backup={"install_id": "laptop0000001", "folder": "/laptop/cloud"},
        deck_ai={"DECK_LLM_ENABLED": False},
    )
    laptop_overlay = tmp_path / "laptop" / "overlay.json"
    laptop_deckfinder = tmp_path / "laptop" / "deckfinder_config.json"
    tracker = FakeTracker(running=True)
    swaps = []

    result = backup.restore_backup(
        made["path"],
        laptop,
        tracker_control=tracker,
        settings_path=laptop_settings,
        overlay_path=laptop_overlay,
        deckfinder_path=laptop_deckfinder,
        before_swap=lambda: swaps.append(True),
    )

    assert result["ok"] and result["games"] == 3 and result["tracker_restarted"] is True
    assert _games(laptop) == ["g1", "g2", "g3"]
    assert tracker.calls == ["stop", "start"] and swaps == [True]
    # Settings: the backup's Deck AI config arrives; the laptop's own port,
    # folder and install id stay.
    document = json.loads(laptop_settings.read_text())
    assert document["deck_ai"]["CHATGPT_API_KEY"] == "sk-secret"
    assert document["dashboard"]["port"] == 9999
    assert document["backup"]["install_id"] == "laptop0000001"
    assert document["backup"]["folder"] == "/laptop/cloud"
    assert document["backup"]["last_restore"]["games"] == 3
    # The safety copy holds the pre-restore state and can be restored back.
    undo = Path(result["undo"])
    assert undo.is_file() and undo.name.endswith("-pre-restore.tappsbackup")
    assert backup.read_manifest(undo)["game_ids"] == ["g1"]
    back = backup.restore_backup(
        undo, laptop, confirm="REPLACE", tracker_control=FakeTracker(running=False),
        settings_path=laptop_settings, overlay_path=laptop_overlay, deckfinder_path=laptop_deckfinder,
    )
    assert back["games"] == 1 and back["tracker_restarted"] is False and _games(laptop) == ["g1"]
    # No stale WAL/SHM left beside the swapped-in database.
    assert not (laptop.parent / "tracker.sqlite3-wal").exists()
    assert not (laptop.parent / "tracker.sqlite3.restoring").exists()


def test_restore_refuses_to_drop_games_without_the_word(tmp_path):
    desktop = _db(tmp_path / "desktop.sqlite3", ["g1"])
    settings = _settings(tmp_path / "settings.json")
    made = backup.export_backup(desktop, tmp_path / "cloud", settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    laptop = _db(tmp_path / "laptop.sqlite3", ["g1", "L1"])

    with pytest.raises(backup.BackupError) as excinfo:
        backup.restore_backup(made["path"], laptop, tracker_control=FakeTracker(), settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    assert excinfo.value.code == "confirm-required" and "1 game" in str(excinfo.value)
    assert _games(laptop) == ["g1", "L1"]

    backup.restore_backup(made["path"], laptop, confirm="REPLACE", tracker_control=FakeTracker(), settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    assert _games(laptop) == ["g1"]


def test_restore_refuses_while_a_tracker_writes_and_refuses_newer_schemas(tmp_path):
    desktop = _db(tmp_path / "desktop.sqlite3", ["g1"])
    settings = _settings(tmp_path / "settings.json")
    made = backup.export_backup(desktop, tmp_path / "cloud", settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")

    busy = _db(tmp_path / "busy.sqlite3", [], heartbeat=datetime.now())
    with pytest.raises(backup.BackupError) as excinfo:
        backup.restore_backup(made["path"], busy, settings_path=settings)
    assert excinfo.value.code == "tracker-running"

    # A backup from the future: rewrite its manifest's schema version.
    future = tmp_path / "future.tappsbackup"
    with zipfile.ZipFile(made["path"]) as src, zipfile.ZipFile(future, "w") as dst:
        for name in src.namelist():
            blob = src.read(name)
            if name == "manifest.json":
                manifest = json.loads(blob)
                manifest["schema_version"] = backup.supported_schema_version() + 5
                blob = json.dumps(manifest).encode("utf-8")
            dst.writestr(name, blob)
    preview = backup.inspect_backup(future, tmp_path / "idle.sqlite3", settings_path=settings)
    assert preview["verdict"] == "newer-schema" and preview["schema_ok"] is False
    with pytest.raises(backup.BackupError) as excinfo:
        backup.restore_backup(future, tmp_path / "idle.sqlite3", tracker_control=FakeTracker(), settings_path=settings)
    assert excinfo.value.code == "newer-schema"

    with pytest.raises(backup.BackupError) as excinfo:
        backup.read_manifest(settings)
    assert excinfo.value.code == "not-a-backup"


def test_restore_migrates_an_older_snapshot_forward(tmp_path):
    desktop = _db(tmp_path / "desktop.sqlite3", ["g1", "g2"])
    settings = _settings(tmp_path / "settings.json")
    made = backup.export_backup(desktop, tmp_path / "cloud", settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    # Age the snapshot: drop the scry columns and forget migration 29, the
    # way a database from before 0.6.3 looks.
    aged = tmp_path / "aged.tappsbackup"
    with zipfile.ZipFile(made["path"]) as src, zipfile.ZipFile(aged, "w") as dst:
        for name in src.namelist():
            blob = src.read(name)
            if name == "tracker.sqlite3":
                old_db = tmp_path / "old.sqlite3"
                old_db.write_bytes(blob)
                conn = sqlite3.connect(old_db)
                for column in AnalyticsStore._LIBRARY_STAT_COLUMNS:
                    conn.execute(f"ALTER TABLE game_participant_stats DROP COLUMN {column}")
                conn.execute("DROP TABLE game_library_events")
                conn.execute("DELETE FROM schema_migrations WHERE version = 29")
                conn.commit()
                conn.execute("VACUUM")
                conn.close()
                blob = old_db.read_bytes()
            elif name == "manifest.json":
                manifest = json.loads(blob)
                manifest["schema_version"] = 28
                blob = json.dumps(manifest).encode("utf-8")
            dst.writestr(name, blob)

    target = tmp_path / "laptop" / "tracker.sqlite3"
    result = backup.restore_backup(aged, target, tracker_control=FakeTracker(running=False), settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    assert result["games"] == 2 and result["undo"] is None  # nothing to save on a fresh laptop
    conn = sqlite3.connect(target)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(game_participant_stats)")}
    assert set(AnalyticsStore._LIBRARY_STAT_COLUMNS) <= columns
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == backup.supported_schema_version()
    conn.close()


def test_list_backups_newest_first_and_names_unreadable_files(tmp_path):
    db = _db(tmp_path / "tracker.sqlite3", ["g1"])
    settings = _settings(tmp_path / "settings.json")
    folder = tmp_path / "cloud"
    older = backup.export_backup(db, folder, settings_path=settings, machine="Laptop", now=datetime(2026, 9, 1, 12), overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    newer = backup.export_backup(db, folder, settings_path=settings, machine="Desktop", now=datetime(2026, 9, 5, 12), overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    (folder / "junk.tappsbackup").write_bytes(b"nope")
    (folder / "notes.txt").write_text("ignored")

    rows = backup.list_backups(folder)
    assert [r["name"] for r in rows][:2] == [Path(newer["path"]).name, Path(older["path"]).name]
    assert rows[0]["machine"] == "Desktop" and rows[0]["games"] == 1 and "game_ids" not in rows[0]
    junk = next(r for r in rows if r["name"] == "junk.tappsbackup")
    assert "not a Tapps Tracker backup" in junk["error"]
    assert backup.list_backups(None) == [] and backup.list_backups(tmp_path / "missing") == []


def test_detect_sync_folders_per_platform(tmp_path):
    mac = tmp_path / "mac"
    (mac / "Library" / "CloudStorage" / "GoogleDrive-travis@gmail.com" / "My Drive").mkdir(parents=True)
    (mac / "Library" / "CloudStorage" / "OneDrive-Personal").mkdir(parents=True)
    (mac / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(parents=True)
    (mac / "Dropbox").mkdir()
    # macOS OneDrive also drops a ~/OneDrive symlink to the CloudStorage
    # folder: it must not show up as a second OneDrive.
    (mac / "OneDrive").symlink_to(mac / "Library" / "CloudStorage" / "OneDrive-Personal", target_is_directory=True)
    found = backup.detect_sync_folders(home=mac, env={}, system="Darwin")
    assert [f["name"] for f in found] == ["Google Drive", "OneDrive", "iCloud Drive", "Dropbox"]
    assert not any(f["path"].startswith(str(mac / "OneDrive")) for f in found)
    # Nothing was created by looking.
    assert not any(Path(f["path"]).exists() for f in found)
    assert found[0]["path"] == str(mac / "Library" / "CloudStorage" / "GoogleDrive-travis@gmail.com" / "My Drive" / "Tapps Tracker")

    win = tmp_path / "win"
    (win / "My Drive").mkdir(parents=True)
    (win / "OneDrive - Contoso").mkdir()
    found = backup.detect_sync_folders(home=win, env={"OneDriveCommercial": str(win / "OneDrive - Contoso")}, system="Windows")
    assert [(f["name"], f["path"]) for f in found] == [
        ("Google Drive", str(win / "My Drive" / "Tapps Tracker")),
        ("OneDrive", str(win / "OneDrive - Contoso" / "Tapps Tracker")),
    ]

    assert backup.detect_sync_folders(home=tmp_path / "empty", env={}, system="Linux") == []


def test_backup_status_and_folder_setting(tmp_path):
    db = _db(tmp_path / "tracker.sqlite3", ["g1", "g2"])
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    (tmp_path / "cloud").mkdir()
    assert backup.set_backup_folder(str(tmp_path / "cloud" / "Tapps Tracker"), settings_path=settings) == str(tmp_path / "cloud" / "Tapps Tracker")
    # Choosing a folder creates nothing; the first backup into it does.
    assert not (tmp_path / "cloud" / "Tapps Tracker").exists()
    with pytest.raises(backup.BackupError) as excinfo:
        backup.set_backup_folder(str(tmp_path / "nowhere" / "Tapps Tracker"), settings_path=settings)
    assert excinfo.value.code == "bad-folder"
    status = backup.backup_status(db, settings_path=settings)
    assert status["folder"] == str(tmp_path / "cloud" / "Tapps Tracker")
    assert status["local"]["games"] == 2 and status["backups"] == [] and status["tracker_active"] is False
    made = backup.export_backup(db, tmp_path / "cloud" / "Tapps Tracker", settings_path=settings, overlay_path=tmp_path / "none", deckfinder_path=tmp_path / "none")
    assert (tmp_path / "cloud" / "Tapps Tracker").is_dir() and Path(made["path"]).is_file()
    assert backup.backup_status(db, settings_path=settings)["backups"][0]["path"] == made["path"]
    assert len(status["install_id"]) == 12 and status["install_id"] == backup.install_id(settings)
    assert backup.set_backup_folder("", settings_path=settings) is None
    assert backup.backup_settings(settings)["folder"] is None


def test_backup_api_routes_and_error_codes(tmp_path, monkeypatch):
    from mtga_tracker import backup_api

    db = _db(tmp_path / "tracker.sqlite3", ["g1", "g2"])
    settings = _settings(tmp_path / "settings.json", backup={"install_id": "x", "folder": None})
    monkeypatch.setattr(backup, "_settings_path", lambda: settings)
    monkeypatch.setattr(backup, "_deckfinder_config_path", lambda: tmp_path / "none")
    monkeypatch.setattr(backup, "overlay_settings_path", lambda **_: tmp_path / "none")

    status, body = backup_api.handle_post("/api/backup/export", {}, db)
    assert (status, body["code"]) == (400, "no-folder")
    status, body = backup_api.handle_post("/api/settings/backup", {"folder": str(tmp_path / "cloud")}, db)
    assert status == 200 and body["folder"] == str(tmp_path / "cloud")
    status, body = backup_api.handle_post("/api/backup/export", {"include_keys": False}, db)
    assert status == 200 and body["backup"]["games"] == 2 and body["status"]["backups"][0]["path"] == body["backup"]["path"]
    made = body["backup"]["path"]

    status, body = backup_api.handle_get("/api/backup", db)
    assert status == 200 and body["last_backup"]["games"] == 2 and body["local"]["games"] == 2

    status, body = backup_api.handle_post("/api/backup/inspect", {"path": made}, db)
    assert status == 200 and body["verdict"] == "same"

    other = _db(tmp_path / "other.sqlite3", ["g1", "g2", "mine"])
    status, body = backup_api.handle_post("/api/backup/restore", {"path": made}, other, tracker_control=FakeTracker())
    assert (status, body["code"]) == (409, "confirm-required")
    status, body = backup_api.handle_post("/api/backup/restore", {"path": made, "confirm": "REPLACE"}, other, tracker_control=FakeTracker())
    assert status == 200 and body["restore"]["games"] == 2 and body["status"]["last_restore"]["games"] == 2
    status, body = backup_api.handle_post("/api/backup/inspect", {"path": str(settings)}, db)
    assert (status, body["code"]) == (400, "not-a-backup")
    assert backup_api.handle_post("/api/backup/other", {}, db) is None
