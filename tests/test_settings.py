import json

import pytest

from mtga_tracker.settings import (
    AppSettings,
    load_app_settings,
    save_startup_settings,
    save_update_settings,
)

def test_load_app_settings_creates_default_file(tmp_path):
    settings_path = tmp_path / "settings.json"

    settings = load_app_settings(settings_path)

    assert settings == AppSettings(live_log_width=1400, live_log_height=1020)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "live_log_window": {"width": 1400, "height": 1020},
        "dashboard": {"port": 8765},
        "startup": {
            "start_at_login": False,
            "open_dashboard_on_launch": True,
        },
        "updates": {
            "check": True,
            "auto_download": True,
            "auto_install": False,
            "channel": "stable",
            "skipped_version": None,
        },
    }


def test_load_app_settings_uses_custom_window_size(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"live_log_window": {"width": 1440, "height": 900}}),
        encoding="utf-8",
    )

    settings = load_app_settings(settings_path)

    assert settings.live_log_width == 1440
    assert settings.live_log_height == 900


def test_load_app_settings_bounds_dimensions_and_handles_invalid_values(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"live_log_window": {"width": 400, "height": "large"}}),
        encoding="utf-8",
    )

    settings = load_app_settings(settings_path)

    assert settings.live_log_width == 820
    assert settings.live_log_height == 1020


def test_load_app_settings_preserves_invalid_file(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("not-json", encoding="utf-8")

    settings = load_app_settings(settings_path)

    assert settings == AppSettings()
    assert settings_path.read_text(encoding="utf-8") == "not-json"


def test_load_app_settings_reads_dashboard_port(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"dashboard": {"port": 9001}}), encoding="utf-8"
    )

    settings = load_app_settings(settings_path)

    assert settings.dashboard_port == 9001


def test_load_app_settings_bounds_dashboard_port(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"dashboard": {"port": 80}}), encoding="utf-8"
    )

    settings = load_app_settings(settings_path)

    assert settings.dashboard_port == 1024


def test_settings_path_is_project_top_level_for_source_checkouts():
    """settings.json must sit next to config.py, not buried in data/."""
    from mtga_tracker.paths import PROJECT_ROOT
    from mtga_tracker.settings import _settings_file_path

    # conftest points SETTINGS_PATH at a scratch file; the rule is in the function.
    assert _settings_file_path() == PROJECT_ROOT / "settings.json"


def test_load_app_settings_reads_startup_preferences(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"startup": {"start_at_login": True, "open_dashboard_on_launch": False}}),
        encoding="utf-8",
    )

    settings = load_app_settings(settings_path)

    assert settings.start_at_login is True
    assert settings.open_dashboard_on_launch is False


def test_load_app_settings_rejects_non_boolean_startup_values(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"startup": {"start_at_login": 1, "open_dashboard_on_launch": "no"}}),
        encoding="utf-8",
    )

    settings = load_app_settings(settings_path)

    assert settings.start_at_login is False
    assert settings.open_dashboard_on_launch is True


def test_save_startup_settings_preserves_other_sections(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"dashboard": {"port": 9001}, "custom": {"keep": True}}),
        encoding="utf-8",
    )

    saved = save_startup_settings(
        start_at_login=True,
        open_dashboard_on_launch=False,
        path=settings_path,
    )

    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document["custom"] == {"keep": True}
    assert saved.dashboard_port == 9001
    assert saved.start_at_login is True
    assert saved.open_dashboard_on_launch is False


def test_update_settings_defaults_and_validation(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "updates": {
                    "check": "yes",
                    "auto_install": True,
                    "channel": "nightly",
                    "skipped_version": "not a version; rm -rf",
                }
            }
        ),
        encoding="utf-8",
    )

    settings = load_app_settings(settings_path)

    assert settings.update_check is True
    assert settings.update_auto_download is True
    assert settings.auto_install_updates is True
    assert settings.update_channel == "stable"
    assert settings.skipped_update_version is None


def test_save_update_settings_preserves_other_sections(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"startup": {"start_at_login": True}, "deck_ai": {"X": 1}}), encoding="utf-8"
    )

    settings = save_update_settings(
        check=True,
        auto_download=False,
        auto_install=True,
        skipped_version="0.6.6",
        path=settings_path,
    )

    assert settings.update_auto_download is False and settings.auto_install_updates is True
    assert settings.skipped_update_version == "0.6.6"
    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document["startup"] == {"start_at_login": True}
    assert document["deck_ai"] == {"X": 1}
    assert document["updates"]["channel"] == "stable"
    with pytest.raises(TypeError):
        save_update_settings(
            check="yes", auto_download=True, auto_install=False, path=settings_path
        )
    with pytest.raises(ValueError):
        save_update_settings(
            check=True, auto_download=True, auto_install=False, channel="beta", path=settings_path
        )


def test_skipped_version_uses_the_updater_version_parser(tmp_path):
    settings_path = tmp_path / "settings.json"
    for version in ("0.7.0.dev3+g1a2b3c", "v0.6.3-rc.8", "0.6.5.post1", "0.6.5.4"):
        settings = save_update_settings(
            check=True,
            auto_download=True,
            auto_install=False,
            skipped_version=version,
            path=settings_path,
        )
        assert settings.skipped_update_version == version
    with pytest.raises(ValueError):
        save_update_settings(
            check=True,
            auto_download=True,
            auto_install=False,
            skipped_version="0.0.0+unknown",
            path=settings_path,
        )


def test_the_session_break_setting_is_gone(tmp_path, monkeypatch):
    """Records count calendar days, so Settings has no session break: the
    endpoint is gone and the settings payload no longer carries it."""
    from mtga_tracker import settings, settings_api

    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    assert settings_api.handle_post("/api/settings/sessions", {"break_hours": 6}) is None
    assert not hasattr(settings, "session_break_hours")


def test_tracker_info_reports_recorded_games(tmp_path, monkeypatch):
    """The Settings page's Tracker card shows how many games are recorded,
    and the collection export stays disabled until there is one."""
    import sqlite3

    from mtga_tracker import settings_api

    monkeypatch.setattr(settings_api, "_deck_ai_summary", lambda: "disabled")
    db = tmp_path / "tracker.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE games (id TEXT, started_at TEXT)")
    info = settings_api._tracker_info(db)
    assert (info["games"], info["first_game_at"], info["last_game_at"]) == (0, None, None)
    # No live_status table yet: the paths stay unknown, the count still reads.
    assert info["monitoring"] is None

    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO games VALUES (?, ?)",
            [("a", "2026-03-01T10:00:00"), ("b", "2026-10-30T21:15:00")],
        )
    info = settings_api._tracker_info(db)
    assert info["games"] == 2
    assert info["first_game_at"] == "2026-03-01T10:00:00"
    assert info["last_game_at"] == "2026-10-30T21:15:00"

    missing = settings_api._tracker_info(tmp_path / "missing.sqlite3")
    assert missing["games"] is None


def test_tracked_modes_default_and_save(tmp_path, monkeypatch):
    import pytest

    from mtga_tracker import dashboard, settings, settings_api

    settings_path = tmp_path / "settings.json"
    defaults = {
        "direct_challenge": True,
        "jump_in": False,
        "midweek_magic": False,
        "momir": False,
        "welcome_deck": False,
        "practice": False,
    }
    assert settings.tracked_modes(settings_path) == defaults
    assert settings.track_direct_challenge(settings_path) is True
    save_startup_settings(start_at_login=True, open_dashboard_on_launch=False, path=settings_path)
    assert settings.save_track_direct_challenge(False, settings_path) is False
    saved = settings.save_tracked_modes({"jump_in": True}, settings_path)
    assert saved == {**defaults, "direct_challenge": False, "jump_in": True}
    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document["tracking"] == {"direct_challenge": False, "jump_in": True}
    assert document["startup"]["start_at_login"] is True
    for value in (None, "false", 0):
        with pytest.raises(ValueError):
            settings.save_tracked_modes({"momir": value}, settings_path)
    for changes in ({}, None, {"arena_open": True}):
        with pytest.raises(ValueError):
            settings.save_tracked_modes(changes, settings_path)

    settings_path.write_text(
        json.dumps({"tracking": {"direct_challenge": "no", "momir": 1}}), encoding="utf-8"
    )
    assert settings.tracked_modes(settings_path) == defaults

    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)
    noted = []
    monkeypatch.setattr(dashboard, "note_tracking_changed", lambda: noted.append(1))
    code, body = settings_api.handle_post(
        "/api/settings/tracking", {"direct_challenge": False, "midweek_magic": True}
    )
    assert code == 200
    assert body["tracking"] == {**defaults, "direct_challenge": False, "midweek_magic": True}
    assert noted == [1]
    code, body = settings_api.handle_post("/api/settings/tracking", {})
    assert code == 400
    assert settings.track_direct_challenge() is False
    assert settings_api.handle_get("/api/settings/tracking") == (
        200,
        {"tracking": {**defaults, "direct_challenge": False, "midweek_magic": True}},
    )


def test_restore_defaults_resets_preferences_and_keeps_the_users_own(monkeypatch, tmp_path):
    """Settings → Restore defaults: every preference on the page goes back as
    shipped; Deck AI keys and models, Deck Finder creators and the backup
    folder stay; one failing step does not stop the others."""
    from types import SimpleNamespace

    from mtga_tracker import (
        overlay_launcher,
        paper_prices,
        settings,
        settings_api,
        startup,
        updater,
    )

    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "startup": {"start_at_login": True, "open_dashboard_on_launch": False},
                "updates": {"check": False, "auto_download": False, "auto_install": True},
                "sessions": {"break_hours": 8},
                "tracking": {"direct_challenge": False, "jump_in": True},
                "deck_ai": {
                    "DECK_LLM_ENABLED": True,
                    "DECK_LLM_PROVIDER": "anthropic",
                    "ANTHROPIC_API_KEY": "sk-keep",
                },
                "backup": {"folder": "/keep/me"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    registrations = []
    monkeypatch.setattr(
        startup,
        "set_start_at_login",
        lambda enabled: registrations.append(enabled)
        or startup.StartupRegistrationStatus(True, enabled),
    )
    monkeypatch.setattr(
        startup, "registration_status", lambda: startup.StartupRegistrationStatus(True, False)
    )
    monkeypatch.setattr(
        updater,
        "_manager",
        SimpleNamespace(
            settings_changed=lambda: None,
            support=lambda: {"supported": True, "install_kind": "macos-app"},
        ),
    )
    paper = {"enabled": False}
    panels_set = []
    monkeypatch.setattr(paper_prices, "status", lambda path=None: dict(paper))
    monkeypatch.setattr(
        paper_prices, "set_enabled", lambda enabled, path=None: paper.update(enabled=enabled)
    )
    monkeypatch.setattr(
        overlay_launcher,
        "get_manager",
        lambda: SimpleNamespace(
            available=True, enabled=False, panels="opponent", set_panels=panels_set.append
        ),
    )

    def overlay_fails(payload):
        raise ValueError("The overlay could not be started.")

    monkeypatch.setattr(settings_api, "_set_overlay_enabled", overlay_fails)

    assert settings_api.handle_post("/api/settings/restore-defaults", {})[0] == 400
    status, body = settings_api.handle_post("/api/settings/restore-defaults", {"confirm": True})

    assert status == 200
    assert body == {
        "restored": True,
        "errors": ["In-game overlay: The overlay could not be started."],
    }
    assert registrations == [False]
    assert paper == {"enabled": True}
    # Opponent only goes back to both panels, even when the overlay cannot start.
    assert panels_set == ["both"]
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["startup"] == {"start_at_login": False, "open_dashboard_on_launch": True}
    assert document["updates"]["check"] is True
    assert document["updates"]["auto_download"] is True
    assert document["updates"]["auto_install"] is False
    # An old session break is left as it was: nothing reads it any more.
    assert document["sessions"] == {"break_hours": 8}
    assert settings.tracked_modes(path) == settings.TRACKED_MODE_DEFAULTS
    assert document["deck_ai"] == {
        "DECK_LLM_ENABLED": False,
        "DECK_LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "sk-keep",
    }
    assert document["backup"] == {"folder": "/keep/me"}
