"""Tests for the log parser module."""

import pytest
from pathlib import Path
from mtga_tracker.log_parser import MTGALogParser


def test_parse_json_from_line():
    """Test JSON parsing from log lines."""
    parser = MTGALogParser.__new__(MTGALogParser)  # Create without __init__

    # Test valid JSON
    line = '[2024-01-01 12:00:00] Event: {"grpId": 12345, "type": "card"}'
    result = parser.parse_json_from_line(line)
    assert result is not None
    assert result["grpId"] == 12345
    assert result["type"] == "card"

    # Test no JSON
    line = "This line has no JSON"
    result = parser.parse_json_from_line(line)
    assert result is None

    # Test invalid JSON
    line = "This has invalid {json: broken}"
    result = parser.parse_json_from_line(line)
    assert result is None


def test_extract_card_events():
    """Test card event extraction."""
    parser = MTGALogParser.__new__(MTGALogParser)

    # Test line with GameStateMessage
    line = '[2024-01-01] GameStateMessage {"gameStateMessage": {"zones": []}}'
    result = parser.extract_card_events(line)
    assert result is not None
    assert result["type"] == "zone_change"

    # Test line without card events
    line = "Some random log line"
    result = parser.extract_card_events(line)
    assert result is None


def test_find_log_path_error_handling():
    """Test that finding log path handles errors gracefully."""
    # This test just ensures the method doesn't crash
    # Actual file existence depends on the system
    try:
        path = MTGALogParser._find_log_path()
        assert isinstance(path, str)
    except FileNotFoundError as e:
        # Expected if MTGA is not installed
        assert "not found" in str(e).lower()
