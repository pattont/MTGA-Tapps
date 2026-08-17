from datetime import datetime

import pytest

from mtga_tracker.log_timestamp import (
    extract_entry_timestamp,
    parse_log_timestamp,
    reset_day_month_inference,
)


@pytest.fixture(autouse=True)
def _fresh_inference():
    reset_day_month_inference()
    yield
    reset_day_month_inference()


def test_parse_log_timestamp_supports_us_12_hour():
    # An unambiguous month-first entry pins the log's field order...
    assert parse_log_timestamp("8/13/2026 09:00:00 AM") == datetime(2026, 8, 13, 9)
    # ...so ambiguous entries from the same log follow it.
    assert parse_log_timestamp("5/8/2026 10:15:01 PM") == datetime(2026, 5, 8, 22, 15, 1)


def test_parse_log_timestamp_supports_iso_and_european_formats():
    assert parse_log_timestamp("2026-05-08 22:15:01") == datetime(2026, 5, 8, 22, 15, 1)
    assert parse_log_timestamp("08.05.2026 22:15:01") == datetime(2026, 5, 8, 22, 15, 1)


def test_parse_log_timestamp_learns_day_first_from_unambiguous_entry():
    # 13/08 can only be day-first: an Australian-style log.
    assert parse_log_timestamp("13/08/2026 11:17:32 AM") == datetime(2026, 8, 13, 11, 17, 32)
    # The ambiguous 9/8 from the same log is now 9 August, not September 8.
    assert parse_log_timestamp("9/08/2026 08:54:00 AM") == datetime(2026, 8, 9, 8, 54)


def test_parse_log_timestamp_learns_month_first_from_unambiguous_entry():
    assert parse_log_timestamp("8/13/2026 11:17:32 AM") == datetime(2026, 8, 13, 11, 17, 32)
    assert parse_log_timestamp("9/8/2026 08:54:00 AM") == datetime(2026, 9, 8, 8, 54)


def test_parse_log_timestamp_dotted_dates_stay_day_first():
    # Even after a month-first slash entry, dotted dates keep the European order.
    assert parse_log_timestamp("8/13/2026 11:17:32 AM") == datetime(2026, 8, 13, 11, 17, 32)
    assert parse_log_timestamp("03.02.2026 10:00:00") == datetime(2026, 2, 3, 10)


def test_parse_log_timestamp_rejects_impossible_dates():
    assert parse_log_timestamp("13/13/2026 10:00:00") is None
    assert parse_log_timestamp("31/02/2026 10:00:00") is None


def test_parse_log_timestamp_supports_epoch_millis_and_dotnet_ticks():
    assert parse_log_timestamp("1778278501000") == datetime.fromtimestamp(1778278501)
    assert parse_log_timestamp("621355968000000000") == datetime(1970, 1, 1)


def test_extract_entry_timestamp_from_header_line():
    body = "[UnityCrossThreadLogger]5/8/2026 10:15:01 PM greToClientEvent\n{}"

    assert extract_entry_timestamp(body) == datetime(2026, 5, 8, 22, 15, 1)


def test_extract_entry_timestamp_returns_none_for_non_timestamp_header():
    assert extract_entry_timestamp("[UnityCrossThreadLogger]STATE CHANGED") is None
