from mtga_tracker.log_json import (
    extract_json_text,
    parse_json_from_body,
    parse_nested_json_field,
)


def test_extract_json_text_handles_nested_objects():
    body = 'prefix {"outer": {"inner": [1, {"two": 2}]}} trailing'

    assert extract_json_text(body) == '{"outer": {"inner": [1, {"two": 2}]}}'


def test_extract_json_text_handles_arrays():
    body = 'prefix [1, {"two": 2}] trailing'

    assert extract_json_text(body) == '[1, {"two": 2}]'


def test_extract_json_text_ignores_braces_inside_strings():
    body = 'prefix {"text": "not the end } and not a start {", "ok": true} trailing'

    assert extract_json_text(body) == '{"text": "not the end } and not a start {", "ok": true}'


def test_extract_json_text_skips_bracket_log_header():
    body = '[UnityCrossThreadLogger]5/8/2026 10:15:01 PM {"key": "value"}'

    assert extract_json_text(body) == '{"key": "value"}'


def test_parse_json_from_body_returns_none_for_missing_or_malformed_json():
    assert parse_json_from_body("no json here") is None
    assert parse_json_from_body("bad {json") is None


def test_parse_nested_json_field_parses_string_payload():
    value = {"payload": '{"type":"ClientMessageType_SelectNResp"}'}

    assert parse_nested_json_field(value, "payload") == {"type": "ClientMessageType_SelectNResp"}


def test_parse_nested_json_field_rejects_non_string_or_malformed_payload():
    assert parse_nested_json_field({"payload": {}}, "payload") is None
    assert parse_nested_json_field({"payload": "{bad"}, "payload") is None


def test_extract_json_text_falls_back_to_the_scan_for_truncated_json():
    # A log entry cut mid-write: no decoder can finish it, and the balanced
    # scan finds no end either.
    assert extract_json_text('prefix {"a": [1, 2') is None
    assert parse_json_from_body('prefix {"a": [1, 2') is None


def test_extract_json_text_keeps_balanced_but_invalid_text():
    # Balanced braces that are not JSON still come back as text (the scan's
    # old answer); parsing them yields None.
    body = "prefix {unquoted: value} trailing"

    assert extract_json_text(body) == "{unquoted: value}"
    assert parse_json_from_body(body) is None


def test_parse_json_from_body_returns_the_first_value_only():
    body = '[Header] {"first": 1} {"second": 2}'

    assert parse_json_from_body(body) == {"first": 1}
    assert extract_json_text(body) == '{"first": 1}'


def test_parse_json_from_body_handles_large_nested_payloads():
    inner = {
        "gameStateMessage": {
            "gameObjects": [{"instanceId": i, "name": f"card {i}"} for i in range(5000)]
        }
    }
    body = "[UnityCrossThreadLogger]GRE " + __import__("json").dumps(
        {"greToClientEvent": {"greToClientMessages": [inner]}}
    )

    parsed = parse_json_from_body(body)

    assert parsed["greToClientEvent"]["greToClientMessages"][0] == inner
