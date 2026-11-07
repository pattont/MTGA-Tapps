"""Suite-wide test isolation."""

from datetime import datetime

import pytest

from mtga_tracker import log_timestamp


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
