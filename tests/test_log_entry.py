from mtga_tracker.log_entry import LineBuffer


def test_line_buffer_groups_multiline_gre_entry_until_next_header():
    buffer = LineBuffer()

    assert buffer.push_line("[Client GRE]5/8/2026 10:15:01 PM greToClientEvent") == []
    assert buffer.push_line('{"greToClientEvent": {"greToClientMessages": []}}') == []
    entries = buffer.push_line("[UnityCrossThreadLogger]STATE CHANGED")

    assert len(entries) == 2
    assert entries[0].header == "[Client GRE]"
    assert entries[0].first_line == "[Client GRE]5/8/2026 10:15:01 PM greToClientEvent"
    assert '"greToClientMessages"' in entries[0].body
    assert entries[1].body == "[UnityCrossThreadLogger]STATE CHANGED"


def test_line_buffer_groups_date_prefixed_unity_start_hook():
    buffer = LineBuffer()

    buffer.push_line("[UnityCrossThreadLogger]5/8/2026 10:15:02 PM")
    buffer.push_line("<== StartHook(abc)")
    buffer.push_line('{"DeckSummaries": [], "Decks": {}}')
    entries = buffer.flush()

    assert len(entries) == 1
    assert entries[0].header == "[UnityCrossThreadLogger]"
    assert "<== StartHook(abc)" in entries[0].body
    assert '"DeckSummaries"' in entries[0].body


def test_line_buffer_emits_single_line_headers_immediately():
    buffer = LineBuffer()

    entries = buffer.push_line("[ConnectionManager] Reconnect succeeded")
    entries += buffer.push_line("Matchmaking: GRE connection lost")
    entries += buffer.push_line("DETAILED LOGS: ENABLED")

    assert [entry.header for entry in entries] == [
        "[ConnectionManager]",
        "Matchmaking:",
        "DETAILED LOGS:",
    ]
    assert buffer.flush() == []


def test_line_buffer_reset_discards_partial_entry_after_truncation():
    buffer = LineBuffer()

    buffer.push_line("[Client GRE]5/8/2026 10:15:01 PM greToClientEvent")
    buffer.push_line('{"partial":')
    buffer.reset()

    assert buffer.flush() == []
    entries = buffer.push_line("[UnityCrossThreadLogger]STATE CHANGED")
    assert len(entries) == 1
    assert entries[0].body == "[UnityCrossThreadLogger]STATE CHANGED"
