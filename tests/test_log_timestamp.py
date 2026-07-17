from datetime import datetime

from mtga_tracker.log_timestamp import extract_entry_timestamp, parse_log_timestamp


def test_parse_log_timestamp_supports_us_12_hour():
    assert parse_log_timestamp("5/8/2026 10:15:01 PM") == datetime(2026, 5, 8, 22, 15, 1)


def test_parse_log_timestamp_supports_iso_and_european_formats():
    assert parse_log_timestamp("2026-05-08 22:15:01") == datetime(2026, 5, 8, 22, 15, 1)
    assert parse_log_timestamp("08.05.2026 22:15:01") == datetime(2026, 5, 8, 22, 15, 1)


def test_parse_log_timestamp_supports_epoch_millis_and_dotnet_ticks():
    assert parse_log_timestamp("1778278501000") == datetime.fromtimestamp(1778278501)
    assert parse_log_timestamp("621355968000000000") == datetime(1970, 1, 1)


def test_extract_entry_timestamp_from_header_line():
    body = "[UnityCrossThreadLogger]5/8/2026 10:15:01 PM greToClientEvent\n{}"

    assert extract_entry_timestamp(body) == datetime(2026, 5, 8, 22, 15, 1)


def test_extract_entry_timestamp_returns_none_for_non_timestamp_header():
    assert extract_entry_timestamp("[UnityCrossThreadLogger]STATE CHANGED") is None
