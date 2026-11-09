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
        "]}}"
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


def test_iter_lines_reversed_matches_readlines(tmp_path):
    from mtga_tracker.log_parser import iter_lines_reversed, tail_lines

    path = tmp_path / "Player.log"
    lines = [f"line {i} " + "x" * (i * 700 % 2000) + "\n" for i in range(400)]
    lines[5] = '[UnityCrossThreadLogger]caf\u00e9 {"k": 1}\n'
    path.write_text("".join(lines), encoding="utf-8")

    with open(path, encoding="utf-8") as handle:
        expected = handle.readlines()
    assert list(iter_lines_reversed(path, chunk_size=1000)) == list(reversed(expected))
    assert tail_lines(path, 7) == expected[-7:]
    assert tail_lines(path, 10_000) == expected


def test_iter_lines_reversed_handles_no_final_newline_and_crlf(tmp_path):
    from mtga_tracker.log_parser import iter_lines_reversed, tail_lines

    path = tmp_path / "Player.log"
    path.write_bytes(b"first\r\nsecond\r\nlast partial")

    assert list(iter_lines_reversed(path, chunk_size=4)) == ["last partial", "second\n", "first\n"]
    assert tail_lines(path, 2) == ["second\n", "last partial"]
    empty = tmp_path / "empty.log"
    empty.write_bytes(b"")
    assert list(iter_lines_reversed(empty)) == []
    assert tail_lines(empty, 5) == []


def test_unchanged_log_is_not_reopened(tmp_path, monkeypatch):
    import builtins

    from mtga_tracker.log_parser import MTGALogParser

    log = tmp_path / "Player.log"
    log.write_text("[UnityCrossThreadLogger]1/2/2026 1:00:00 PM\n{\"a\": 1}\n", encoding="utf-8")
    parser = MTGALogParser(log_path=str(log))
    parser.last_position = 0
    assert len(list(parser.read_new_entries())) == 1

    real_open = builtins.open

    def refusing_open(*args, **kwargs):  # a second read of an unchanged file must not happen
        raise AssertionError("log reopened without new bytes")

    monkeypatch.setattr(builtins, "open", refusing_open)
    assert list(parser.read_new_entries()) == []
    monkeypatch.setattr(builtins, "open", real_open)

    with real_open(log, "a", encoding="utf-8") as handle:
        handle.write("[UnityCrossThreadLogger]1/2/2026 1:00:01 PM\n{\"b\": 2}\n")
    assert len(list(parser.read_new_entries())) == 1
