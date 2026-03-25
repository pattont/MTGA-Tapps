# MTGA Log Format

This document describes the MTGA Player.log format and how to parse it.

## Log File Location

### Windows
```
%APPDATA%\LocalLow\Wizards Of The Coast\MTGA\Player.log
```
Typically: `C:\Users\<username>\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log`

### macOS
```
~/Library/Logs/Wizards Of The Coast/MTGA/Player.log
```

## Log Format

The MTGA log file is a text file with JSON-formatted events. Each line typically follows this pattern:

```
[timestamp] LogType: JSON_data
```

Example:
```
[UnityCrossThreadLogger]11/17/2025 1:23:45 PM: Match.GREMessageType_GameStateMessage
```

## Key Event Types

### Game State Messages
These contain information about the current state of the game, including:
- Cards in zones (hand, battlefield, graveyard, etc.)
- Player information
- Turn/phase information

### GRE Messages (Game Rules Engine)
- `GREMessageType_GameStateMessage`: Full game state updates
- `GREMessageType_QueuedGameStateMessage`: Queued state changes
- `GREMessageType_UIMessage`: UI-related events

### Card Events
Look for these patterns:
- `CardInstance`: Information about specific card instances
- `grpId`: Card ID (can be mapped to card names via Scryfall API)
- `zoneId`: Which zone the card is in
- `ownerSeatId`: Which player owns the card

## Zone IDs

Common zone IDs:
- `ZoneType_Hand`: Player's hand
- `ZoneType_Library`: Player's library (deck)
- `ZoneType_Battlefield`: Battlefield (cards in play)
- `ZoneType_Graveyard`: Graveyard
- `ZoneType_Exile`: Exile zone
- `ZoneType_Stack`: The stack

## Parsing Strategy

1. **Monitor the file**: Use file watching (watchdog library) to detect new lines
2. **Extract JSON**: Most important data is in JSON format
3. **Filter events**: Look for specific event types related to card plays
4. **Map card IDs**: Use the grpId to look up card names (requires card database)

## Card Database

To convert card IDs to names, you'll need a card database. Options:
- **Scryfall API**: https://api.scryfall.com/
- **MTGA card database**: Can be extracted from MTGA installation
- **MTG JSON**: https://mtgjson.com/

## Example Log Entries

### Card Play Event
```json
{
  "greToClientEvent": {
    "greToClientMessages": [
      {
        "type": "GREMessageType_GameStateMessage",
        "gameStateMessage": {
          "zones": [
            {
              "zoneId": 2,
              "type": "ZoneType_Battlefield",
              "objectInstanceIds": [5, 12, 23]
            }
          ]
        }
      }
    ]
  }
}
```

### Card Instance
```json
{
  "instanceId": 23,
  "grpId": 74567,
  "ownerSeatId": 1,
  "controllerSeatId": 1,
  "zoneId": 2
}
```

## Identifying the Opponent

**From the logs only**, you can get an **internal opponent identifier**, but not the human‑readable screen name.

### What the logs contain

The `matchGameRoomStateChangedEvent` (when a match/game room is set up) includes a `gameRoomInfo.gameRoomConfig.reservedPlayers` array. Each entry has:

- **`userId`** — Internal account ID (numeric or UUID). This identifies the opponent in Wizards’ backend but is **not** the displayed Arena username (e.g. `Player#12345`).
- **`systemSeatId`** — Seat index (1 or 2) used in game state (life, zones, `ownerSeatId`, etc.).
- **`teamId`** — Team identifier.

To know “which `userId` is the opponent,” you must first know which seat is yours (e.g. via hand visibility in game state) and then treat the other seat’s `userId` in `reservedPlayers` as the opponent’s internal ID.

### What the logs do *not* contain

The opponent’s **screen name** (the name shown in the Arena client) is **not** written to Player.log. Tools that show opponent names (e.g. MTG Arena Tool) get them by **reading game memory** (e.g. their `readMatchOpponentInfo` via the mtga-reader), which needs access to the MTGA process and is outside pure log parsing.

### Summary

| Data              | In Player.log? | Where it comes from          |
|-------------------|-----------------|------------------------------|
| Opponent `userId` | ✅ Yes          | `matchGameRoomStateChangedEvent` → `reservedPlayers` |
| Opponent seat ID | ✅ Yes          | Same, or derived from game state |
| Opponent screen name | ❌ No       | Game memory only (e.g. MTG Arena Tool) |

So with **logs only**, you can identify the opponent by internal `userId` and by seat, but not by their displayed username.

## Future Improvements

1. **Complete JSON parsing**: Implement full parsing of all event types
2. **Card database integration**: Map grpId to actual card names
3. **Player tracking**: Properly track which player (you vs opponent) played what
4. **Match detection**: Detect match start/end events
5. **Deck recognition**: Identify decks being played
6. **Statistics**: Track win rates, card frequencies, etc.
7. **Opponent ID**: Parse `reservedPlayers` from `matchGameRoomStateChangedEvent` to store opponent `userId` per match (internal ID only; screen name would require memory reading).

## Resources

- [MTGA Log Parser by apzxi](https://github.com/apzxi/mtga_log_parser)
- [17Lands Tracker](https://www.17lands.com/) - Reference implementation
- [MTGA Pro Tracker](https://mtgarena.pro/mtga-pro-tracker/) - Another reference
- [Scryfall API Documentation](https://scryfall.com/docs/api)
