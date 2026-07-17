from mtga_tracker.log_sanitize import scrub_raw_log


def test_scrub_raw_log_removes_tokens_paths_names_and_hardware():
    raw = """
Token: secret-token
Authorization: Bearer abc.def.ghi
"userId": "ABC123"
"playerName": "Player#12345"
/Users/travispatton/Library/Logs/Wizards Of The Coast/MTGA/Player.log
  Renderer: Very Specific GPU
"""

    scrubbed = scrub_raw_log(raw)

    assert "secret-token" not in scrubbed
    assert "abc.def.ghi" not in scrubbed
    assert "ABC123" not in scrubbed
    assert "Player#12345" not in scrubbed
    assert "/Users/travispatton/" not in scrubbed
    assert "Very Specific GPU" not in scrubbed
    assert "Token: <redacted>" in scrubbed
    assert '"playerName": "<redacted>"' in scrubbed
