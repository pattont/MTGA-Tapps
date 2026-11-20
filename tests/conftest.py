"""Suite-wide test isolation."""

from datetime import datetime

import pytest

from mtga_tracker import dashboard, log_timestamp, settings


@pytest.fixture(autouse=True)
def _deterministic_log_dates(monkeypatch):
    """Each test starts with no learned log date order and a pinned clock.

    The parser's clock tier picks the reading of an ambiguous date that falls
    in the last two weeks. Pinned far from every fixture date it never
    applies, so results do not depend on the day the suite runs; tests of
    that tier set `log_timestamp._clock` themselves.
    """
    log_timestamp.reset_day_month_inference()
    monkeypatch.setattr(log_timestamp, "_clock", lambda: datetime(1999, 1, 1))
    yield
    log_timestamp.reset_day_month_inference()


@pytest.fixture(autouse=True)
def _private_settings_file(tmp_path, monkeypatch):
    """Each test reads its own empty settings.json, never the checkout's.

    Settings → Saved game modes decides what the tracker saves and what the
    dashboard hides, so the developer's own choices must not leak in.
    """
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    dashboard.note_tracking_changed()
    yield
    dashboard.note_tracking_changed()
