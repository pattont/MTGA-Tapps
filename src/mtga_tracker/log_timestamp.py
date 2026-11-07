"""Timestamp parsing for MTGA Player.log entries.

Arena writes log timestamps in a locale's date format, so the same
`Player.log` line can mean different dates on different machines: `9/8/2026`
is September 8 on a US system but 9 August anywhere day-first (Australia,
most of Europe). Storage is always ISO 8601 — the only locale-sensitive step
is *interpreting* these ambiguous strings, decided in this order:

1. Unambiguous entries (one field > 12) decide themselves, and teach us the
   log's field order for the rest of the process lifetime.
2. An epoch-millisecond `"timestamp"` inside the same entry (every GRE
   message carries one) picks the reading that matches it, and teaches the
   order too. This is the log's own evidence, so it outranks what was learned.
3. Otherwise, the order learned from earlier entries wins — Arena writes one
   consistent format per machine.
4. Before anything has been learned, the system clock: the two readings of
   a swapped date are at least 29 days apart, so at most one of them is
   within the last two weeks. Arena's log is live, so that one is right.
5. Last, the OS locale's own date order (probed once via strftime). Arena
   does not always follow it — a US Windows with a custom day-first short
   date still logs month-first — so it is only the final fallback.
"""

from __future__ import annotations

import locale
import re
from datetime import datetime, timedelta
from typing import Optional


_DOTNET_EPOCH = datetime(1, 1, 1)

# Year-first formats are never ambiguous; keep them on the strptime path.
_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %I:%M:%S %p",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %I:%M:%S %p",
    "%Y-%m-%dT%H:%M:%S",
)

# day-or-month, separator, day-or-month, 4-digit year, time, optional AM/PM.
_DAY_MONTH_RE = re.compile(
    r"^(\d{1,2})([/.])(\d{1,2})\2(\d{4})[ T]"
    r"(\d{1,2}):(\d{2}):(\d{2})(?:\s*([AaPp])\.?[Mm]\.?)?$"
)

# Learned slash-date field order: True = day first. Set by the first
# unambiguous entry seen and trusted for the rest of the process.
_learned_day_first: Optional[bool] = None
_system_day_first: Optional[bool] = None

# An epoch-millisecond "timestamp" field inside an entry's JSON.
_EPOCH_MS_RE = re.compile(r'"timestamp"\s*:\s*"?(1\d{12})\b')

# How close the embedded epoch time must be to a reading to confirm it.
_EVIDENCE_TOLERANCE = timedelta(days=1)
# The clock window: log lines can be from earlier in a long Arena session,
# never meaningfully from the future. Must stay well under 29 days in total.
_CLOCK_PAST = timedelta(days=14)
_CLOCK_FUTURE = timedelta(days=2)

# The wall clock, replaceable by tests.
_clock = datetime.now


def reset_day_month_inference() -> None:
    """Forget the learned field order (tests, or reprocessing another log)."""
    global _learned_day_first
    _learned_day_first = None


def _detect_system_day_first() -> bool:
    """Probe whether the OS locale writes the day before the month.

    Formats a known date (Feb 3) with the locale's `%x` and checks whether
    the 3 (day) or the 2 (month) appears first. Year-first locales report
    month-first here, which matches how their Arena logs are written.
    """
    try:
        locale.setlocale(locale.LC_TIME, "")
    except locale.Error:
        pass
    try:
        probe = datetime(2001, 2, 3).strftime("%x")
    except ValueError:
        return False
    for token in re.findall(r"\d+", probe):
        value = int(token)
        if value == 3:
            return True
        if value in (2, 2001, 1):
            return False
    return False


def _default_day_first() -> bool:
    global _system_day_first
    if _system_day_first is None:
        _system_day_first = _detect_system_day_first()
    return _system_day_first


def _only_reading_near(
    readings: "dict[bool, datetime]", anchor: datetime, before: timedelta, after: timedelta
) -> Optional[bool]:
    """The field order whose reading alone falls in [anchor - before, anchor + after]."""
    near = [
        day_first
        for day_first, value in readings.items()
        if anchor - before <= value <= anchor + after
    ]
    return near[0] if len(near) == 1 else None


def _ambiguous_readings(
    first: int, second: int, year: int, hour: int, minute: int, second_of_minute: int
) -> "dict[bool, datetime]":
    readings = {}
    for day_first in (True, False):
        day, month = (first, second) if day_first else (second, first)
        try:
            readings[day_first] = datetime(year, month, day, hour, minute, second_of_minute)
        except ValueError:
            continue
    return readings


def _parse_day_month_timestamp(raw: str, evidence: Optional[datetime] = None) -> Optional[datetime]:
    """Parse `a/b/YYYY time` where a and b could be day or month.

    `evidence` is a trustworthy time for the same entry (its JSON epoch
    timestamp), used only when the date itself is ambiguous.
    """
    global _learned_day_first
    match = _DAY_MONTH_RE.match(raw)
    if not match:
        return None
    first, separator, second = int(match.group(1)), match.group(2), int(match.group(3))
    year = int(match.group(4))
    hour, minute, second_of_minute = (
        int(match.group(5)),
        int(match.group(6)),
        int(match.group(7)),
    )
    meridiem = (match.group(8) or "").lower()
    if meridiem == "p":
        hour = hour % 12 + 12
    elif meridiem == "a":
        hour = hour % 12

    if first > 12 and second <= 12:
        day_first = True
    elif second > 12 and first <= 12:
        day_first = False
    elif first > 12 and second > 12:
        return None
    elif separator == ".":
        # Dotted dates (8.5.2026) are a day-first convention everywhere.
        day_first = True
    else:
        day_first = _resolve_ambiguous(
            _ambiguous_readings(first, second, year, hour, minute, second_of_minute),
            evidence,
        )

    day, month = (first, second) if day_first else (second, first)
    try:
        parsed = datetime(year, month, day, hour, minute, second_of_minute)
    except ValueError:
        return None
    if separator == "/" and (first > 12) != (second > 12):
        # A valid, unambiguous slash entry teaches us this log's field order.
        _learned_day_first = day_first
    return parsed


def _resolve_ambiguous(readings: "dict[bool, datetime]", evidence: Optional[datetime]) -> bool:
    """Pick the field order for a slash date whose fields are both <= 12."""
    global _learned_day_first
    if len(readings) == 2 and readings[True] != readings[False]:
        if evidence is not None:
            confirmed = _only_reading_near(
                readings, evidence, _EVIDENCE_TOLERANCE, _EVIDENCE_TOLERANCE
            )
            if confirmed is not None:
                _learned_day_first = confirmed
                return confirmed
        if _learned_day_first is not None:
            return _learned_day_first
        try:
            now = _clock()
        except Exception:  # noqa: BLE001 - a broken clock leaves the locale fallback
            now = None
        if now is not None:
            recent = _only_reading_near(readings, now, _CLOCK_PAST, _CLOCK_FUTURE)
            if recent is not None:
                _learned_day_first = recent
                return recent
    if _learned_day_first is not None:
        return _learned_day_first
    return _default_day_first()


def parse_log_timestamp(text: str, evidence: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a timestamp commonly found in MTGA logs.

    `evidence` optionally confirms which reading an ambiguous slash date
    means (see the module docstring).
    """
    if text is None:
        return None
    raw = str(text).strip().strip(":")
    if not raw:
        return None

    numeric = _parse_numeric_timestamp(raw)
    if numeric is not None:
        return numeric

    iso = raw.rstrip("Z")
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass

    day_month = _parse_day_month_timestamp(raw, evidence)
    if day_month is not None:
        return day_month

    for fmt in _FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def extract_entry_timestamp(body: str) -> Optional[datetime]:
    """Extract and parse a timestamp from a complete log entry body."""
    if not isinstance(body, str) or not body:
        return None
    first_line = body.splitlines()[0] if "\n" in body else body
    if not first_line.startswith("["):
        return None
    close = first_line.find("]")
    if close < 0:
        return None
    remainder = first_line[close + 1 :].strip()
    if not remainder:
        return None
    if not remainder[:1].isdigit():
        return None
    evidence = _embedded_epoch_time(body)
    words = remainder.split()
    for count in range(min(4, len(words)), 1, -1):
        candidate = " ".join(words[:count]).rstrip(":")
        parsed = parse_log_timestamp(candidate, evidence)
        if parsed is not None:
            return parsed
    return None


def _embedded_epoch_time(body: str) -> Optional[datetime]:
    """The local time of the entry's JSON epoch-ms "timestamp", if any.

    Arena stamps every GRE message with one, in the same clock as the
    header, so it settles a header date like 11/4/2026 exactly.
    """
    if '"timestamp"' not in body:
        return None
    match = _EPOCH_MS_RE.search(body)
    if not match:
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_numeric_timestamp(raw: str) -> Optional[datetime]:
    if not raw.isdigit():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    try:
        if value > 10_000_000_000_000_000:
            return _DOTNET_EPOCH + timedelta(microseconds=value / 10)
        if value > 10_000_000_000:
            return datetime.fromtimestamp(value / 1000)
    except (OverflowError, OSError, ValueError):
        return None
    return None
