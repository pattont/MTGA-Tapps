"""JSON extraction helpers for MTGA log entries."""

from __future__ import annotations

import json
from typing import Any, Optional


def extract_json_text(body: str) -> Optional[str]:
    """Return the first complete JSON object/array from a log entry body."""
    if not isinstance(body, str) or not body:
        return None

    start_at = 0
    if body.startswith("["):
        header_end = body.find("]")
        if header_end >= 0:
            start_at = header_end + 1

    start = None
    for index in range(start_at, len(body)):
        if body[index] in "{[":
            start = index
            break
    if start is None:
        return None

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


def parse_json_from_body(body: str) -> Any:
    """Parse the first complete JSON value from a log entry body."""
    json_text = extract_json_text(body)
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
