"""Timestamp parsing for MTGA Player.log entries."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


_DOTNET_EPOCH = datetime(1, 1, 1)

_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %I:%M:%S %p",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %I:%M:%S %p",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %I:%M:%S %p",
    "%Y-%m-%dT%H:%M:%S",
)


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
