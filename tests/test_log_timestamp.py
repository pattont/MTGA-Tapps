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


def _gre_entry(header_date: str, epoch_local: datetime) -> str:
    millis = int(epoch_local.timestamp() * 1000)
    return (
        f"[UnityCrossThreadLogger]{header_date}: Match to ABC: GreToClientEvent\n"
        f'{{ "transactionId": "1", "requestId": 2, "timestamp": "{millis}", '
        '"greToClientEvent": {} }'
    )


def _force_locale(monkeypatch, day_first: bool) -> None:
    from mtga_tracker import log_timestamp

    monkeypatch.setattr(log_timestamp, "_system_day_first", day_first)


def test_embedded_epoch_settles_month_first_date_despite_day_first_locale(monkeypatch):
    # Issue #51: a US Windows with a custom day-first short date. Arena still
    # logs month-first, and every GRE entry carries the true epoch time.
    _force_locale(monkeypatch, day_first=True)
    body = _gre_entry("11/4/2026 10:52:18 PM", datetime(2026, 11, 4, 22, 52, 18))

    assert extract_entry_timestamp(body) == datetime(2026, 11, 4, 22, 52, 18)
    # ...and the learned order carries to entries without an epoch field.
    assert extract_entry_timestamp(
        "[UnityCrossThreadLogger]11/3/2026 7:43:22 PM: STATE CHANGED"
    ) == datetime(2026, 11, 3, 19, 43, 22)


def test_embedded_epoch_settles_day_first_date_despite_month_first_locale(monkeypatch):
    # Issue #51, Italian Windows: 04/11/2026 is 4 November.
    _force_locale(monkeypatch, day_first=False)
    body = _gre_entry("04/11/2026 21:54:39", datetime(2026, 11, 4, 21, 54, 39))

    assert extract_entry_timestamp(body) == datetime(2026, 11, 4, 21, 54, 39)


def test_embedded_epoch_outranks_a_wrongly_learned_order():
    # Something taught month-first; the entry's own epoch says day-first.
    assert parse_log_timestamp("8/13/2026 11:17:32 AM") == datetime(2026, 8, 13, 11, 17, 32)
    body = _gre_entry("04/11/2026 21:54:39", datetime(2026, 11, 4, 21, 54, 39))

    assert extract_entry_timestamp(body) == datetime(2026, 11, 4, 21, 54, 39)


def test_clock_picks_the_recent_reading_before_anything_is_learned(monkeypatch):
    from mtga_tracker import log_timestamp

    monkeypatch.setattr(log_timestamp, "_clock", lambda: datetime(2026, 11, 4, 23, 0))
    _force_locale(monkeypatch, day_first=True)
    # Read day-first, 11/3 is 11 March, months ago; month-first it is yesterday.
    assert parse_log_timestamp("11/3/2026 7:43:22 PM") == datetime(2026, 11, 3, 19, 43, 22)
    # The clock's answer is learned for older ambiguous lines of the same log.
    assert parse_log_timestamp("5/8/2026 10:15:01 PM") == datetime(2026, 5, 8, 22, 15, 1)


def test_clock_handles_day_first_logs_with_a_month_first_locale(monkeypatch):
    from mtga_tracker import log_timestamp

    monkeypatch.setattr(log_timestamp, "_clock", lambda: datetime(2026, 11, 4, 23, 0))
    _force_locale(monkeypatch, day_first=False)
    assert parse_log_timestamp("04/11/2026 21:54:39") == datetime(2026, 11, 4, 21, 54, 39)


def test_locale_is_the_last_resort_when_no_reading_is_recent(monkeypatch):
    _force_locale(monkeypatch, day_first=True)
    # Clock pinned to 1999 by conftest: neither reading is recent.
    assert parse_log_timestamp("5/8/2026 10:15:01 PM") == datetime(2026, 8, 5, 22, 15, 1)
