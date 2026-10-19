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
