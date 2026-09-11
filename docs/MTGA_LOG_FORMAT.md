# MTGA log format and tracker parsing

This reference describes the current parser, not a stable contract from
Arena. Real logs and focused regression fixtures take precedence over
schematic examples. Gameplay tracking needs **Detailed Logs (Plugin Support)**
enabled in Arena's Account options.

## Files and entry boundaries

- Windows: `%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log`.
  `%APPDATA%` normally ends in `Roaming`; `LocalLow` is its sibling.
- macOS: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log`.
- Both tracker launchers accept `--log-path` for an explicit file.

Arena emits plain startup text, timestamped headers, JSON objects, and JSON
continued over several physical lines. A line is not necessarily an event.
`log_entry.py` groups complete entries; `log_json.py` extracts their JSON;
`event_router.py` classifies them and maintains parser-health counters.
`log_parser.py` emits the ordered game-state/client messages.

Timestamps are locale-formatted. `log_timestamp.py` learns month/day order
from unambiguous dates, with a system-locale fallback; stored timestamps are
ISO. Never assume a fixed US date order. The tracker polls the file and
retains an offset. The current reader resets on a smaller file; file
replacement that has already grown beyond that offset is not independently
detected by inode today.

## GRE state and actions

`greToClientEvent.greToClientMessages` carries GRE messages, including full
and differential game state, queued state messages, and UI messages.
Client-to-GRE actions are normalized by `client_actions.py`. Room and queue
metadata supply match grouping, format, seats, submitted decks and names;
GRE messages supply gameplay state and annotations.

Important object fields:

| Field | Meaning |
| --- | --- |
| `instanceId` | In-game object identity; must be interpreted with snapshots and identity changes |
| `grpId` | Arena card/group ID; normal name lookup uses Arena's local card database |
| `ownerSeatId` / `controllerSeatId` | Ownership and current control, which can differ |
| `zoneId` | Numeric reference to an entry in the state's `zones` array |
| `objectSourceGrpId` | Source card group ID on some ability objects |

Zone **types** include `ZoneType_Hand`, `ZoneType_Library`,
`ZoneType_Battlefield`, `ZoneType_Graveyard`, `ZoneType_Exile`,
`ZoneType_Stack`, and `ZoneType_Command`. These strings are not fixed numeric
zone IDs. Resolve a zone through its current `zoneId`, type, and owner seat.
A battlefield snapshot alone does not establish whether a card was cast,
created as a token, returned, transformed or copied.

The tracker combines annotations and object/zone snapshots to track draws,
zone transfers, spells/abilities, combat, life, targets and turns. Focused
`tracker_event_*`, `tracker_zone_transfers.py`, `tracker_stack.py` and
`tracker_combat.py` helpers own those interpretations.

## Seats, names and formats

Match-room `gameRoomInfo.gameRoomConfig.reservedPlayers` provides
`userId`/`systemSeatId` and can provide displayed names. The tracker accepts
`screenName`, `playerName`, `displayName` and their case variants through
`tracker_opening_deck.py`. **Opponent names do not require memory access.**
When metadata is absent, leave it unknown instead of inventing a name from
another seat or game.

Seats can change between games. A complete visible opening hand identifies
the local seat, correcting stale metadata; never assume the local player
is seat 1. Resolve opponent identity and the winner relative to that seat.

Queue information is normalized by `format_normalizer.py`. Re-resolve it
for every game. Brawl's join event (`EventSetDeckV3`, for example
`EventName: Brawl_Ladder`) is stronger queue evidence than the generic
Historic Brawl room label. Deck format attributes describe a deck and must
not override an authoritative queue.

## Scry and card metadata

Scry annotations list card IDs in `affectedIds`; they do not put the seat
there. Resolve the ability controller from current/retained snapshots.
Counts are available for both seats; record player card names only when
visible. See [Scry tracking](SCRY_TRACKING.md) for details and persistence.

Arena's local `Raw_CardDatabase_*.mtga` resolves card names/types, colors,
rules text and mana costs. `grpId` is not automatically interchangeable with
a Scryfall identifier. See [Card database discovery](MTGA_INSTALL_DISCOVERY.md)
for log-header paths, overrides and missing-card behavior.

## Persistence and regression fixtures

Completed tracked games produce structured tables for participants, turns,
events, hands, draws, decklists and stats. Raw payloads are privacy-scrubbed
by `log_sanitize.py`, compressed with `payload_codec.py`, and retained as a
30-day diagnostic archive. Read them through `payload_dump`, not raw SQL
text assumptions. Unhandled-annotation diagnostics belong in the text log.
Collection memory export is a separate explicit action and does not feed
normal gameplay parsing.

Useful examples: `tests/test_log_entry.py`, `test_log_parser.py`,
`test_log_replay.py`, `test_scry_tracking.py`, and
`test_tracker_combat_winner.py`. Add minimal payload regressions for parser
or state-machine bugs. In particular, preserve stack LIFO order, stale-seat
correction, winner/concession handling, turn timing, and NULL-versus-zero
historical stats; the fuller invariant list is in [AGENTS.md](../AGENTS.md).
