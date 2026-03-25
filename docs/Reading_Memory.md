# MTGA Memory Reading – Notes (Tabled)

These notes capture what memory reading would allow beyond log parsing. **Not currently implemented**; kept for future reference.

---

## Why Memory at All?

**Logs** give you game state (life, zones, turns, card plays, annotations) and, with `matchGameRoomStateChangedEvent` → `reservedPlayers`, an **opponent internal ID** (`userId`) and seat. They do **not** give you the opponent’s **screen name** or your own account/rank/collection/economy in a clean way.

**Memory reading** means reading data from the running MTGA process (e.g. via offsets/signatures or a daemon that already does it). It unlocks data the game never writes to Player.log.

---

## What Memory Reading Would Allow

Based on what **MTG Arena Tool** and tools like **mtga-tracker-daemon** read from the MTGA process:

### Identity & match participants

| Data | Source (conceptually) | Notes |
|------|------------------------|--------|
| **Your display name** | Account / match-player structs | `DisplayName`, `_screenName` |
| **Opponent display name** | Match-opponent struct | `_screenName` – not available in logs |
| **Account IDs** | Account / match structs | `AccountID`, `PersonaID`, `GameID`, `WizardsAccountIdForPrivateGaming` |

### Match metadata (from “match manager”)

- **Match ID** – unique ID for the current match  
- **Format** – Constructed / Limited / etc. (numeric code)  
- **Game number** – which game in the match (1, 2, 3…)  
- **LocalPlayerSeatId** – your seat (1 or 2) from the game itself  
- **Match state** – in progress, complete, etc.  
- **Flags** – `IsPracticeGame`, `IsPrivateGame`, `HasReconnected`  
- **Win condition** – how the match can end (e.g. life, poison)

### Rank / ladder

- **Your rank** – `RankingClass`, `RankingTier`, `MythicPercentile`, `MythicPlacement`  
- **Opponent rank** – same fields for the current opponent  
- **Commander** – `CommanderGrpId` (e.g. Brawl/Commander)  
- **WotC account** – `IsWotc`

### Collection & economy

- **Full collection** – list of `(grpId, count)` for every card you own (e.g. mtga-tracker-daemon’s `/cards`)  
- **Inventory** – **gems**, **gold** (e.g. mtga-tracker-daemon’s `/inventory`)

Logs do not expose full collection or economy; memory does.

### Cosmetics

- **Avatar** – `AvatarSelection` (you and opponent)  
- **Sleeve** – `SleeveSelection` (you and opponent)

### Process / overlay

- **Process ID** – MTGA’s PID (e.g. “is MTGA running?”, overlay placement)  
- **Window position/size** – when exposed by the reader, useful for overlays

---

## Logs vs Memory (Summary)

| Data | Logs only | With memory |
|------|-----------|-------------|
| Game state (life, zones, turns, card plays) | ✅ | ✅ (can double-check) |
| Player/opponent seat | ✅ (inferred) | ✅ (e.g. `LocalPlayerSeatId`) |
| Opponent **name** | ❌ | ✅ |
| Your **name** | ⚠️ (auth payload, if present) | ✅ (e.g. `DisplayName`) |
| Match ID, format, game # | ❌ / inferred | ✅ |
| Your/opponent **rank** | ❌ | ✅ |
| **Collection** (owned cards) | ❌ | ✅ |
| **Gems / gold** | ❌ | ✅ |
| **Deck list** for current match | ⚠️ (from zones at game start, if parsed) | ✅ if exposed in match structs |

---

## How Others Do It

- **MTG Arena Tool** – Uses an internal “mtga-reader” and several reader modules:  
  `readPlayerId`, `readMatchPlayerInfo`, `readMatchOpponentInfo`, `readMatchManger`, `readCards`.  
  These walk known memory paths (e.g. `MTGA` → `PAPA` → `_instance` → `_matchManager`, etc.) and return typed structs.

- **mtga-tracker-daemon** – HTTP server that reads from the MTGA process and exposes:  
  - `GET /status` – isRunning, processId, updating  
  - `GET /cards` – collection (grpId, owned)  
  - `GET /playerId` – Wizards account ID  
  - `GET /inventory` – gems, gold  

  A **log-only** app could call this daemon’s HTTP API to get collection/economy/playerId without implementing memory reads itself.

- **Opponent name** – Comes from **memory** (e.g. `readMatchOpponentInfo` → `_screenName`), not from Player.log.  
  Mapping opponent seat (from logs or memory) gives you *which* opponent; the display name is only in the process.

---

## Tradeoffs

- **Platform / implementation** – Requires a reader that can attach to the MTGA process (offsets/signatures or a separate daemon). Often implies native code or a prebuilt binary (e.g. mtga-tracker-daemon).
- **Privileges** – Reading another process’ memory usually needs elevated rights (admin/sudo) or similar, depending on OS.
- **Fragility** – Game updates can change layouts and break readers; someone has to maintain offsets/signatures.
- **Policy** – Memory reading is a judgment call; logs are the “official” observable output. No guarantee from Wizards that third-party memory readers are allowed.

---

## Reference: MTG Arena Tool reader shapes (from their source)

- **readPlayerId** – `AccountID`, `DisplayName`, `PersonaID`, `GameID`, `Email`, `AccessToken`, etc.  
- **readMatchPlayerInfo** – `_screenName`, `AvatarSelection`, `SleeveSelection`, `RankingClass`, `RankingTier`, `MythicPercentile`, `MythicPlacement`, `CommanderGrpId`, `WizardsAccountIdForPrivateGaming`, `IsWotc`.  
- **readMatchOpponentInfo** – Same shape as readMatchPlayerInfo.  
- **readMatchManger** – `MatchID`, `CurrentGameNumber`, `Format`, `LocalPlayerSeatId`, `MatchState`, `IsPracticeGame`, `IsPrivateGame`, `HasReconnected`, `BattlefieldId`, `Variant`, `WinCondition`, etc.

---

*Tabled for possible future use. Current tracker is log-only.*
