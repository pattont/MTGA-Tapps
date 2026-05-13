"""Privacy scrubbing helpers for raw MTGA log text."""

from __future__ import annotations

import re


_SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Token:\s*\S+"), "Token: <redacted>"),
    (re.compile(r"\bBearer\s+\S+"), "Bearer <redacted>"),
    (re.compile(r"Match to [A-Z0-9_]+:"), "Match to <redacted>:"),
    (re.compile(r'"[Cc]lient[Ii]d"\s*:\s*"[^"]+"'), '"clientId": "<redacted>"'),
    (re.compile(r'"[Uu]ser[Ii]d"\s*:\s*"[^"]+"'), '"userId": "<redacted>"'),
    (re.compile(r'"[Tt]oken"\s*:\s*"[^"]+"'), '"token": "<redacted>"'),
    (re.compile(r'"[Ss]ession[Ii]d"\s*:\s*"[^"]+"'), '"sessionId": "<redacted>"'),
    (re.compile(r'"[Ss]creen[Nn]ame"\s*:\s*"[^"]+"'), '"screenName": "<redacted>"'),
    (re.compile(r'"[Pp]layer[Nn]ame"\s*:\s*"[^"]+"'), '"playerName": "<redacted>"'),
    (re.compile(r"[A-Z]:\\Users\\[^\\]+\\"), r"<user-path>\\"),
    (re.compile(r"/Users/[^/]+/"), "<user-path>/"),
    (re.compile(r"/home/[^/]+/"), "<user-path>/"),
    (re.compile(r"(?m)^\s+Renderer:\s+.+"), "  Renderer: <redacted>"),
    (re.compile(r"(?m)^\s+Vendor:\s+.+"), "  Vendor: <redacted>"),
    (re.compile(r"(?m)^\s+VRAM:\s+.+"), "  VRAM: <redacted>"),
    (re.compile(r"(?m)^\s+Driver:\s+.+"), "  Driver: <redacted>"),
)


def scrub_raw_log(text: str) -> str:
    """Return raw log text with local PII and credentials redacted."""
    if not text:
        return ""
    scrubbed = str(text)
    for pattern, replacement in _SCRUB_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed
