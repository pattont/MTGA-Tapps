"""Player inventory (wildcards, gold, gems, vault) from Arena's log.

Arena includes an ``InventoryInfo`` block in several client responses: the
``StartHook`` payload at launch (alongside deck summaries), event joins
(``Course`` + ``InventoryInfo``), prize claims, and purchases. Each one is a
full snapshot, not a delta, so the newest occurrence is the current state.

Only the counts a player cares about on the dashboard are kept — the four
wildcard tallies, gold, gems, and vault progress. Nothing else in the block
(cosmetics, boosters, vouchers) is persisted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from .log_entry import LineBuffer
from .log_json import parse_json_from_body

INVENTORY_FIELDS: Tuple[str, ...] = (
    "gems",
    "gold",
    "vault_progress",
    "wc_common",
    "wc_uncommon",
    "wc_rare",
    "wc_mythic",
)

# Arena field -> our column. Kept explicit so protocol drift shows up as a
# missing key (snapshot skipped) rather than a silent zero.
_ARENA_KEYS: Dict[str, str] = {
    "Gems": "gems",
    "Gold": "gold",
    "TotalVaultProgress": "vault_progress",
    "WildCardCommons": "wc_common",
    "WildCardUnCommons": "wc_uncommon",
    "WildCardRares": "wc_rare",
    "WildCardMythics": "wc_mythic",
}


def _inventory_block(payload: Any) -> Optional[Dict[str, Any]]:
    """Locate the InventoryInfo dict inside a parsed payload (top level or one
    level down), or accept a payload that IS the block."""
    if not isinstance(payload, dict):
        return None
    block = payload.get("InventoryInfo")
    if isinstance(block, dict):
        return block
    if "WildCardRares" in payload and "Gold" in payload:
        return payload
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("InventoryInfo"), dict):
            return value["InventoryInfo"]
    return None


def parse_inventory_snapshot(body: str) -> Optional[Dict[str, int]]:
    """Return the inventory counts from a log entry body, or None when the
    entry carries no complete InventoryInfo block."""
    if "InventoryInfo" not in body and "WildCardRares" not in body:
        return None
    block = _inventory_block(parse_json_from_body(body))
    if block is None:
        return None
    snapshot: Dict[str, int] = {}
    for arena_key, column in _ARENA_KEYS.items():
        value = block.get(arena_key)
        if value is None:
            # Vault progress is the only field Arena omits at times; the
            # wildcard and currency counts must all be present.
            if column == "vault_progress":
                continue
            return None
        try:
            snapshot[column] = int(value)
        except (TypeError, ValueError):
            return None
    return snapshot


def iter_inventory_snapshots(log_path: Path | str) -> Iterator[Tuple[datetime, Dict[str, int]]]:
    """Yield (timestamp, snapshot) for every InventoryInfo block already in a
    Player.log — the startup backfill, mirroring the rank import."""
    buffer = LineBuffer()
    with Path(log_path).open("r", encoding="utf-8", errors="ignore") as stream:
        for raw_line in stream:
            for entry in buffer.push_line(raw_line):
                snapshot = parse_inventory_snapshot(entry.body)
                if snapshot is not None and entry.timestamp is not None:
                    yield entry.timestamp, snapshot
        for entry in buffer.flush():
            snapshot = parse_inventory_snapshot(entry.body)
            if snapshot is not None and entry.timestamp is not None:
                yield entry.timestamp, snapshot
