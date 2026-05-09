from mtga_tracker.log_json import (
    extract_json_text,
    parse_json_from_body,
    parse_nested_json_field,
)


def test_extract_json_text_handles_nested_objects():
    body = 'prefix {"outer": {"inner": [1, {"two": 2}]}} trailing'

    assert extract_json_text(body) == '{"outer": {"inner": [1, {"two": 2}]}}'


def test_extract_json_text_handles_arrays():
    body = "prefix [1, {\"two\": 2}] trailing"

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
    value = {"payload": "{\"type\":\"ClientMessageType_SelectNResp\"}"}

    assert parse_nested_json_field(value, "payload") == {"type": "ClientMessageType_SelectNResp"}


def test_parse_nested_json_field_rejects_non_string_or_malformed_payload():
    assert parse_nested_json_field({"payload": {}}, "payload") is None
    assert parse_nested_json_field({"payload": "{bad"}, "payload") is None
