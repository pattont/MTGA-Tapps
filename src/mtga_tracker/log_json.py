"""JSON extraction helpers for MTGA log entries."""

from __future__ import annotations

import json
from typing import Any, Optional


#: `strict=False` lets control characters through inside strings, like the
#: character scan this replaced; the strict decoder is what json.loads uses.
_LENIENT_DECODER = json.JSONDecoder(strict=False)
_STRICT_DECODER = json.JSONDecoder()


def _json_start(body: str) -> Optional[int]:
    """Index of the first `{` or `[` after the entry's `[Header]`, if any."""
    start_at = 0
    if body.startswith("["):
        header_end = body.find("]")
        if header_end >= 0:
            start_at = header_end + 1
    brace = body.find("{", start_at)
    bracket = body.find("[", start_at)
    if brace < 0:
        return None if bracket < 0 else bracket
    if bracket < 0:
        return brace
    return min(brace, bracket)


def _scan_balanced(body: str, start: int) -> Optional[str]:
    """The slow path for text the decoder rejects: the first balanced
    object/array from `start`, brackets inside strings ignored."""
    open_char = body[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape_next = False

    for index in range(start, len(body)):
        char = body[index]
        if escape_next:
            escape_next = False
            continue
        if char == "\\" and in_string:
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return body[start : index + 1]
    return None


def extract_json_text(body: str) -> Optional[str]:
    """Return the first complete JSON object/array from a log entry body.

    The decoder's C scanner finds the end of a well-formed value; the
    character walk it replaced was a quarter of the tracker's CPU per game.
    """
    if not isinstance(body, str) or not body:
        return None
    start = _json_start(body)
    if start is None:
        return None
    try:
        _, end = _LENIENT_DECODER.raw_decode(body, start)
    except ValueError:
        return _scan_balanced(body, start)
    return body[start:end]


def parse_json_from_body(body: str) -> Any:
    """Parse the first complete JSON value from a log entry body."""
    if not isinstance(body, str) or not body:
        return None
    start = _json_start(body)
    if start is None:
        return None
    try:
        value, _ = _STRICT_DECODER.raw_decode(body, start)
    except ValueError:
        pass
    else:
        return value
    json_text = _scan_balanced(body, start)
    if json_text is None:
        return None
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None


def parse_nested_json_field(value: dict, field: str) -> Any:
    """Parse a nested field containing JSON encoded as a string."""
    if not isinstance(value, dict):
        return None
    nested = value.get(field)
    if not isinstance(nested, str):
        return None
    try:
        return json.loads(nested)
    except json.JSONDecodeError:
        return None
