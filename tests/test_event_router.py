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


def test_router_names_ordinary_client_chatter():
    """Client requests, server answers, scene changes and startup notes are
    not game state, but they are not unknown either — an "unknown" is
    written to the diagnostics log and archived as a raw payload, and a
    launch used to produce dozens of them."""
    router = EventRouter()
    cases = {
        '[UnityCrossThreadLogger]==> GetFormats {"id":"d45c","request":"{ }"}': "client_request",
        '[UnityCrossThreadLogger]==> GraphGetGraphState {"id":"7539","request":"{\\"GraphId\\":\\"NPE_Tutorial\\"}"}': "client_request",
        "[UnityCrossThreadLogger]06/09/2026 17:12:40\n<== GetFormats(d45c)\n{\"formats\":[]}": "server_response",
        "[UnityCrossThreadLogger]9/6/2026 5:12:40 PM": "timestamp",
        '[UnityCrossThreadLogger]Client.SceneChange {"fromSceneName":"None","toSceneName":"Home"}': "scene",
        "[UnityCrossThreadLogger]Got non-message event: Wizards.Arena.TcpConnection.TcpOpenedEvent": "client_info",
        '[UnityCrossThreadLogger]FrontDoorConnectionAWS.Open {"creator":"ArenaGlobals.Constructor"}': "client_info",
        "[UnityCrossThreadLogger]Loading SqlLocalizationManager from file: G:/x.mtga {}": "client_info",
        "[UnityCrossThreadLogger]Default currency for SKUs: EUR": "client_info",
    }
    for body, expected in cases.items():
        assert router.route(_entry(body)).category == expected, body
    assert router.stats.unknown_count == 0
    # Still unknown: something genuinely new.
    assert router.route(_entry("[UnityCrossThreadLogger]some new arena thing")).category == "unknown"
