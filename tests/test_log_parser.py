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
    assert result["type"] == "game_state"

    # Test line without card events
    line = "Some random log line"
    result = parser.extract_card_events(line)
    assert result is None


def test_extract_game_state_events_preserves_gre_message_order():
    """Each GRE game-state message should be surfaced separately and in order."""
    parser = MTGALogParser.__new__(MTGALogParser)

    line = (
        '{"greToClientEvent":{"greToClientMessages":['
        '{"type":"GREMessageType_GameStateMessage","gameStateMessage":{"gameStateId":7,"gameInfo":{"matchState":"MatchState_GameComplete"}}},'
        '{"type":"GREMessageType_GameStateMessage","gameStateMessage":{"gameStateId":8,"gameInfo":{"matchState":"MatchState_MatchComplete"}}},'
        '{"type":"GREMessageType_GameStateMessage","gameStateMessage":{"gameStateId":9,"turnInfo":{"turnNumber":1,"activePlayer":1}}}'
        ']}}'
    )

    events = parser.extract_game_state_events(line)

    assert [event["data"]["gameStateId"] for event in events] == [7, 8, 9]
    assert events[2]["data"]["turnInfo"]["turnNumber"] == 1


def test_read_new_lines_reconstructs_multiline_client_to_gre_message(tmp_path: Path):
    """Multiline ClientToGREMessage blocks should be yielded as one parseable line."""
    log_path = tmp_path / "Player.log"
    log_path.write_text(
        "\n".join(
            [
                "[UnityCrossThreadLogger] to Match: ClientToGremessage",
                "{",
                '  "clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage",',
                '  "payload": {',
                '    "type": "ClientMessageType_MulliganResp",',
                '    "mulliganResp": {',
                '      "decision": "MulliganOption_Mulligan"',
                "    }",
                "  }",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    parser = MTGALogParser(str(log_path))

    lines = list(parser.read_new_lines())

    assert len(lines) == 1
    payloads = parser.extract_client_gre_payloads(lines[0])
    assert payloads[0]["data"]["type"] == "ClientMessageType_MulliganResp"
    assert payloads[0]["data"]["mulliganResp"]["decision"] == "MulliganOption_Mulligan"


def test_extract_client_gre_payloads_from_service_message():
    """ClientToMatchServiceMessageType_ClientToGREMessage payloads should be extracted."""
    parser = MTGALogParser.__new__(MTGALogParser)
    line = (
        '{"clientToMatchServiceMessageType":"ClientToMatchServiceMessageType_ClientToGREMessage",'
        '"payload":{"type":"ClientMessageType_SelectNResp","selectNResp":{"ids":[444]}}}'
    )

    payloads = parser.extract_client_gre_payloads(line)

    assert len(payloads) == 1
    assert payloads[0]["data"]["type"] == "ClientMessageType_SelectNResp"
    assert payloads[0]["data"]["selectNResp"]["ids"] == [444]


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


def test_constructed_parser_smoke_fixture_routes_expected_entries():
    fixture = Path(__file__).parent / "fixtures" / "constructed_parser_smoke.txt"
    parser = MTGALogParser(str(fixture))

    entries = list(parser.read_new_entries())
    categories = [parser.route_entry(entry).category for entry in entries]

    assert categories == [
        "metadata",
        "match_state",
        "gre",
        "client_action",
        "connection_state",
        "tcp_connection_close",
        "websocket_closed",
        "connection_error",
        "rank",
        "event_lifecycle",
        "inventory",
    ]
