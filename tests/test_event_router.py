from mtga_tracker.event_router import EventRouter
from mtga_tracker.log_entry import LogEntry


def _entry(body, timestamp=None):
    return LogEntry(
        header="[UnityCrossThreadLogger]",
        body=body,
        first_line=body.splitlines()[0],
        timestamp=timestamp,
    )


def test_router_classifies_known_entries_and_counts_routed():
    router = EventRouter()

    assert router.route(_entry('[UnityCrossThreadLogger]greToClientEvent {"greToClientEvent": {}}')).category == "gre"
    assert router.route(_entry('[UnityCrossThreadLogger]ClientToGREMessage {"payload": {}}')).category == "client_action"
    assert router.route(_entry('[UnityCrossThreadLogger]matchGameRoomStateChangedEvent {"matchGameRoomStateChangedEvent": {}}')).category == "match_state"
    assert router.route(_entry("[ConnectionManager] Reconnect succeeded")).category == "connection"
    assert router.route(_entry("DETAILED LOGS: ENABLED")).category == "metadata"

    assert router.stats.routed_count == 5
    assert router.stats.unknown_count == 0


def test_router_classifies_start_hook_deck_collection():
    router = EventRouter()
    body = '[UnityCrossThreadLogger]5/8/2026 10:15:01 PM\n<== StartHook(abc)\n{"DeckSummaries": [], "Decks": {}}'

    routed = router.route(_entry(body))

    assert routed.category == "deck_collection"
    assert router.stats.routed_count == 1


def test_router_counts_unknown_without_crashing():
    router = EventRouter()

    routed = router.route(_entry("[UnityCrossThreadLogger]some new arena thing"))

    assert routed.category == "unknown"
    assert router.stats.unknown_count == 1


def test_router_counts_malformed_json_and_timestamp_failures():
    router = EventRouter()
    body = "[UnityCrossThreadLogger]5/8/2026 10:15:01 PM greToClientEvent\n{bad"
    entry = LogEntry(
        header="[UnityCrossThreadLogger]",
        body=body,
        first_line=body.splitlines()[0],
        timestamp=None,
    )

    routed = router.route(entry)

    assert routed.category == "gre"
    assert routed.malformed_json is True
    assert routed.timestamp_failure is True
    assert router.stats.malformed_json_count == 1
    assert router.stats.timestamp_failure_count == 1


def test_router_classifies_connection_lifecycle_entries():
    router = EventRouter()

    assert router.route(_entry('[UnityCrossThreadLogger]STATE CHANGED {"old":"Connecting","new":"Connected"}')).category == "connection_state"
    assert router.route(_entry('[UnityCrossThreadLogger]Client.TcpConnection.Close {"status":"Closed"}')).category == "tcp_connection_close"
    assert router.route(_entry('[UnityCrossThreadLogger]GREConnection.HandleWebSocketClosed {"reason":"normal"}')).category == "websocket_closed"
    assert router.route(_entry('[UnityCrossThreadLogger]TcpConnection.ProcessRead.Exception {"exception":"boom"}')).category == "connection_error"


def test_router_classifies_non_ui_constructed_support_entries():
    router = EventRouter()

    assert router.route(_entry('[UnityCrossThreadLogger]<== RankGetCombinedRankInfo(abc) {"constructedClass":"Gold"}')).category == "rank"
    assert router.route(_entry('[UnityCrossThreadLogger]<== EventJoin {"eventId":"Ladder"}')).category == "event_lifecycle"
    assert router.route(_entry('[UnityCrossThreadLogger]<== StartHook(abc) {"InventoryInfo":{}}')).category == "inventory"
