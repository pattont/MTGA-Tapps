"""Player inventory (wildcards, gold, gems) from Arena's InventoryInfo blocks."""

import json
import sqlite3
from datetime import datetime

from mtga_tracker.analytics import AnalyticsStore, SessionSnapshot
from mtga_tracker.dashboard import dashboard_snapshot
from mtga_tracker.inventory import iter_inventory_snapshots, parse_inventory_snapshot

INVENTORY = {
    "SeqId": 1,
    "Changes": [],
    "Gems": 6675,
    "Gold": 6875,
    "TotalVaultProgress": 825,
    "wcTrackPosition": 9,
    "WildCardCommons": 297,
    "WildCardUnCommons": 292,
    "WildCardRares": 63,
    "WildCardMythics": 9,
    "CustomTokens": {},
    "Boosters": [],
}

EXPECTED = {
    "gems": 6675,
    "gold": 6875,
    "vault_progress": 825,
    "wc_common": 297,
    "wc_uncommon": 292,
    "wc_rare": 63,
    "wc_mythic": 9,
}


def _entry(payload):
    return "[UnityCrossThreadLogger]8/30/2026 9:20:02 PM\n<== StartHook(abc)\n" + json.dumps(
        payload, indent=1
    )


def test_parse_inventory_from_starthook_and_event_join():
    # Launch payload: InventoryInfo beside the deck summaries.
    assert parse_inventory_snapshot(_entry({"InventoryInfo": INVENTORY, "DeckSummaries": []})) == EXPECTED
    # Event join: Course + InventoryInfo.
    assert parse_inventory_snapshot(_entry({"Course": {}, "InventoryInfo": INVENTORY})) == EXPECTED
    # Nothing inventory-shaped -> None, cheaply.
    assert parse_inventory_snapshot("[UnityCrossThreadLogger] hello") is None
    # A block missing a wildcard count is protocol drift, not zero wildcards.
    broken = {k: v for k, v in INVENTORY.items() if k != "WildCardRares"}
    assert parse_inventory_snapshot(_entry({"InventoryInfo": broken})) is None
    # Vault progress is optional.
    no_vault = {k: v for k, v in INVENTORY.items() if k != "TotalVaultProgress"}
    parsed = parse_inventory_snapshot(_entry({"InventoryInfo": no_vault}))
    assert parsed["wc_rare"] == 63 and "vault_progress" not in parsed


def test_iter_inventory_snapshots_from_log(tmp_path):
    log = tmp_path / "Player.log"
    later = dict(INVENTORY, WildCardRares=64, Gold=7875)
    log.write_text(
        "[UnityCrossThreadLogger]8/30/2026 9:20:02 PM\n<== StartHook(a)\n"
        + json.dumps({"InventoryInfo": INVENTORY}, indent=1)
        + "\n[UnityCrossThreadLogger]8/30/2026 9:24:26 PM\n<== EventJoin(b)\n"
        + json.dumps({"Course": {"x": 1}, "InventoryInfo": later}, indent=1)
        + "\n[UnityCrossThreadLogger]8/30/2026 9:25:00 PM\n<== Other(c)\n{\"Nope\": 1}\n",
        encoding="utf-8",
    )
    snapshots = list(iter_inventory_snapshots(log))
    assert [s["wc_rare"] for _, s in snapshots] == [63, 64]
    assert snapshots[1][0] == datetime(2026, 8, 30, 21, 24, 26)


def test_record_inventory_snapshot_keeps_only_changes(tmp_path):
    store = AnalyticsStore(tmp_path / "t.sqlite3")
    session = SessionSnapshot(
        session_id="S1", started_at=datetime(2026, 8, 30, 21, 0),
        games_played=0, wins=0, losses=0, unknown_results=0,
    )
    when = datetime(2026, 8, 30, 21, 20)
    assert store.record_inventory_snapshot(session, captured_at=when, **EXPECTED) is True
    # Identical restatement (Arena repeats the block on every event join) -> no row.
    assert store.record_inventory_snapshot(session, captured_at=when, **EXPECTED) is False
    changed = dict(EXPECTED, wc_rare=61, gold=7475)  # crafted two rares, won gold
    assert store.record_inventory_snapshot(session, captured_at=when, **changed) is True
    conn = store.connect()
    rows = conn.execute("SELECT wc_rare, gold FROM inventory_snapshots ORDER BY id").fetchall()
    assert rows == [(63, 6875), (61, 7475)]

    # The overview carries the newest snapshot.
    inventory = dashboard_snapshot(tmp_path / "t.sqlite3")["inventory"]
    assert inventory["wc_rare"] == 61 and inventory["wc_mythic"] == 9
    assert inventory["gold"] == 7475 and inventory["vault_progress"] == 825
    store.close()


def test_dashboard_inventory_absent_when_never_seen(tmp_path):
    store = AnalyticsStore(tmp_path / "t.sqlite3")
    assert store.connect() is not None  # creates the schema
    store.close()
    assert dashboard_snapshot(tmp_path / "t.sqlite3")["inventory"] is None
