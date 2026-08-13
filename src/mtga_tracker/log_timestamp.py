"""Timestamp parsing for MTGA Player.log entries.

Arena writes log timestamps in the OS locale's date format, so the same
`Player.log` line can mean different dates on different machines: `9/8/2026`
is September 8 on a US system but 9 August anywhere day-first (Australia,
most of Europe). Storage is always ISO 8601 — the only locale-sensitive step
is *interpreting* these ambiguous strings, handled here in three tiers:

1. Unambiguous entries (one field > 12) decide themselves, and teach us the
   log's field order for the rest of the process lifetime.
2. Otherwise, the order learned from the most recent unambiguous entry wins —
   Arena writes one consistent format per machine.
3. Before anything has been learned, fall back to the OS locale's own date
   order (probed once via strftime), since Arena runs on this same machine
   and follows the same locale.
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


def _parse_day_month_timestamp(raw: str) -> Optional[datetime]:
    """Parse `a/b/YYYY time` where a and b could be day or month."""
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
    elif _learned_day_first is not None:
        day_first = _learned_day_first
    else:
        day_first = _default_day_first()

    day, month = (first, second) if day_first else (second, first)
    try:
        parsed = datetime(year, month, day, hour, minute, second_of_minute)
    except ValueError:
        return None
    if separator == "/" and (first > 12) != (second > 12):
        # A valid, unambiguous slash entry teaches us this log's field order.
        _learned_day_first = day_first
    return parsed


def parse_log_timestamp(text: str) -> Optional[datetime]:
    """Parse a timestamp commonly found in MTGA logs."""
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

    day_month = _parse_day_month_timestamp(raw)
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
    words = remainder.split()
    for count in range(min(4, len(words)), 1, -1):
        candidate = " ".join(words[:count]).rstrip(":")
        parsed = parse_log_timestamp(candidate)
        if parsed is not None:
            return parsed
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
