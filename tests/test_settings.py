import json

from mtga_tracker.settings import AppSettings, load_app_settings, save_startup_settings


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
    from mtga_tracker.settings import SETTINGS_PATH

    assert SETTINGS_PATH == PROJECT_ROOT / "settings.json"


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


def test_session_break_defaults_to_four_hours_and_keeps_other_settings(tmp_path):
    from mtga_tracker.settings import save_session_break_hours, session_break_hours

    settings_path = tmp_path / "settings.json"
    assert session_break_hours(settings_path) == 4
    save_startup_settings(start_at_login=True, open_dashboard_on_launch=False, path=settings_path)
    assert save_session_break_hours(8, settings_path) == 8
    assert save_session_break_hours(0, settings_path) == 0
    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document["sessions"] == {"break_hours": 0}
    assert document["startup"]["start_at_login"] is True

    settings_path.write_text(json.dumps({"sessions": {"break_hours": "6"}}), encoding="utf-8")
    assert session_break_hours(settings_path) == 4


def test_session_break_rejects_unsupported_values(tmp_path):
    import pytest

    from mtga_tracker.settings import save_session_break_hours

    for value in (5, -1, True, "4", None):
        with pytest.raises(ValueError):
            save_session_break_hours(value, tmp_path / "settings.json")


def test_settings_api_reads_and_saves_the_session_break(tmp_path, monkeypatch):
    from mtga_tracker import settings, settings_api

    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    code, body = settings_api.handle_post("/api/settings/sessions", {"break_hours": 6})
    assert code == 200
    assert body["sessions"] == {"break_hours": 6, "choices": [0, 1, 2, 3, 4, 6, 8, 12]}
    code, body = settings_api.handle_post("/api/settings/sessions", {"break_hours": 7})
    assert code == 400
    assert settings.session_break_hours() == 6
