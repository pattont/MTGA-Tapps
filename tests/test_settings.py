import json

from mtga_tracker.settings import AppSettings, load_app_settings


def test_load_app_settings_creates_default_file(tmp_path):
    settings_path = tmp_path / "settings.json"

    settings = load_app_settings(settings_path)

    assert settings == AppSettings(live_log_width=1400, live_log_height=1020)
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "live_log_window": {"width": 1400, "height": 1020},
        "dashboard": {"port": 8765},
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
