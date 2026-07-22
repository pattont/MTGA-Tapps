# Changelog

## Unreleased

- Added user-editable `settings.json` sizing for the desktop live-log window and increased its default size to 1400 by 1020.
- Enlarged the desktop live-log window, enabled its colored event output by default, and made menu-bar icon clicks open only the menu instead of relaunching the dashboard.
- Fixed live event rows using the previous game's analytics ID, added timestamp-based historical event reassignment, and made DB repair remove empty unknown-result game artifacts.

### Dashboard UI

- Added game detail routes with life charts, opening hand, drawn cards, played cards, and filterable event timeline.
- Added card drill-down routes with card art, by-deck performance, and opening-hand impact.
- Added filter-aware deck routes, sidebar scrollspy, deck/card table search, match recap rows, session recap rows, and empty-dashboard setup guidance.
- Extended the local dashboard API with `/api/game`, `/api/card`, filtered `/api/deck`, match/session snapshot data, and larger deck/card result limits.
- Added global tracked-card search with usage-ranked autocomplete results and direct card detail navigation.
- Expanded card analytics to include player and opponent usage, with compact side-by-side and deck tables.
- Added per-game draw totals, land-draw percentage, and Flood detection for games above 50% land draws.
- Preserved dashboard section context when opening a game so Back returns to the originating table and scroll position.
- Merged Draw Quality into Recent Games and moved Recent Games directly below Win Rate Trend in dashboard navigation.
- Reordered dashboard content so its top-to-bottom section sequence exactly matches sidebar navigation.
- Consolidated Play / Draw and Momentum into Overview and replaced intersection-based navigation highlighting with position-based scroll tracking.
- Added game length and average turn pace to Recent Games and deck history, plus sortable per-turn timing with player/opponent totals and live/estimated provenance in Game Detail.

### Desktop Launcher

- Added a unified tracker/dashboard launcher with automatic browser opening and free-port fallback.
- Added a macOS menu-bar controller with tracker status, start/stop controls, dashboard access, a bounded live tracker log, and clean coordinated shutdown.
- Added PyInstaller app-bundle and DMG build scripts with bundled frontend assets and per-user Application Support storage.
- Added original card-analytics app and menu-bar icons, corrected the native application display name, and made the Live Tracker Log window open automatically with the dashboard.
- Added matching ICO, PNG, and Apple touch favicons to the web dashboard.

## v0.4.0 - Complete Game Tracking & Auto-Summary (2025-11-19)

### Major Features

**Starting Hand & Mulligan Tracking**
- ✅ Shows your opening hand with card names
- ✅ Detects mulligans automatically
- ✅ Counts number of mulligans
- ✅ Tracks hand size (7, 6, 5, etc.)
- ✅ Displayed at start and in game summary

**Combat Tracking**
- ⚔️ Attacker declarations with power/toughness
- 🛡️ Blocker declarations showing what blocks what
- 💢 Combat damage tracking
- 💥 Creature deaths in combat
- Shows which player's creatures

**Spell Targeting**
- ✅ Shows what card/permanent was targeted
- ✅ Shows ownership of target (your vs opponent's)
- ✅ Example: "Lightning Bolt targeting Tarmogoyf (opponent's)"
- Works with removal, auras, counters, etc.

**Game Timer**
- ⏱️  Tracks game duration from start to end
- Shows minutes and seconds
- Displayed in final summary

**Auto Game Detection**
- ✅ Detects game start automatically
- ✅ Detects game end automatically
- ✅ Shows summary when game ends (no manual stop needed)
- ✅ Resets state for next game
- ✅ Tracker runs continuously through multiple games

**Improved Life Tracking**
- ✅ Fixed: Now accurately tracks between turns
- ✅ Only announces actual changes (not initial values)
- ✅ Only shows changes after turn 1
- ✅ Shows current life after change

**Enhanced Game Summary**
- 🏁 Automatic at game end
- ⏱️  Game duration
- 🎴 Starting hand displayed
- 🎉/💀 Win/loss detection
- 📊 All cards played by both players
- Shows card counts

### Game Flow Example

```
🎮 GAME STARTED

🎴 Your Starting Hand (6 cards):
   (After 1 mulligan)
   • Lightning Bolt
   • Mountain x2
   • Goblin Guide
   ...

⚔️  Turn 1 - YOUR TURN

🎯 You cast Lightning Bolt targeting Tarmogoyf (opponent's)
💥 Tarmogoyf (opponent's) was destroyed

⚔️ You attacking with Goblin Guide (2/2)
🛡️ Opponent blocking with Wall (0/4)

🏁 GAME ENDED
⏱️  Game Duration: 8m 42s
🎉 You won!
```

### Files Added
- `docs/COMPLETE_GAME_TRACKING.md` - Complete feature documentation

### Files Modified
- `src/mtga_tracker/tracker.py` - Major expansion of tracking features
- All new tracking systems implemented

### Breaking Changes
None - fully backwards compatible

## v0.3.0 - Instant Detection & Interaction Tracking (2025-11-19)

### Major Improvements

**Instant Detection Fixed**
- ✅ Instants are now properly tracked
- ✅ Added support for "PlaySpell" category (in addition to "CastSpell")
- ✅ All spell types now detected reliably

**Interaction Tracking**
- ✅ Destruction effects show ownership: "Serra Angel (your) was destroyed"
- ✅ Multiple removal types tracked:
  - 💥 Destroy
  - 🚫 Exile
  - ⚰️ Sacrifice
  - 🗑️ Discard
  - 🚫 Counter
- ✅ Shows which player's card was affected

**Additional Game Events**
- ✅ Card draw tracking: `📥 You drew a card`
- ✅ Scry tracking: `🔮 You scried`
- ✅ Mill tracking: `🌊 You milled Brainstorm`
- ✅ Sacrifice tracking with ownership

**Debug Tools**
- ✅ debug_annotations.py - Analyzes all annotation categories in log
- ✅ Shows instant/sorcery detection
- ✅ Shows destruction/removal patterns
- ✅ Recommends which categories to track

### Files Added
- `debug_annotations.py` - Comprehensive annotation analyzer
- `docs/INTERACTION_EXAMPLES.md` - Examples of all tracked interactions

### Files Modified
- `src/mtga_tracker/tracker.py` - Expanded annotation processing
- `docs/EXAMPLE_OUTPUT.md` - Updated with new features

### Examples

**Before:**
```
🎯 You cast Lightning Bolt (Instant)
💥 Vampire Nighthawk was destroyed
```

**After:**
```
🎯 You cast Lightning Bolt (Instant)
💥 Vampire Nighthawk (opponent's) was destroyed
   Opponent lost 3 life (17)
```

**Now also tracks:**
```
👤 Opponent cast Thoughtseize (Sorcery)
🗑️ Force of Will (your) was discarded

🎯 You cast Opt (Instant)
🔮 You scried
📥 You drew a card
```

## v0.2.1 - Player Detection & Life Tracking Fixes (2025-11-19)

### Bug Fixes

**Player vs Opponent Detection**
- 🐛 Fixed: Player/opponent showing backwards
- ✅ Auto-detects player seat ID from log
- ✅ Scans matchGameRoomStateChangedEvent for seat assignments
- ✅ Shows detected seat on startup

**Life Total Tracking**
- 🐛 Fixed: Life totals not updating correctly
- ✅ Uses detected seat IDs for life mapping
- ✅ Prevents false announcements at game start
- ✅ Only announces changes after match begins

### Files Added
- `debug_seats.py` - Seat ID detection analyzer
- `docs/TROUBLESHOOTING.md` - Common issues and solutions

## v0.2.0 - Narrative Output & Card Name Resolution (2025-11-19)

### Major Improvements

**Card Name Resolution**
- ✅ Actual card names instead of IDs using Scryfall API
- ✅ Local caching to minimize API calls (stored in `data/card_cache.json`)
- ✅ Automatic card lookup on first encounter

**Game State Tracking**
- ✅ Life total tracking with change notifications
- ✅ Turn number and active player display
- ✅ Match start/end detection
- ✅ Clear turn boundaries with life totals

**Better Output**
- ✅ Narrative-style output that tells the story of the game
- ✅ Visual icons for quick identification (🎯 You, 👤 Opponent, 💥 Destroyed)
- ✅ Card type information (Creature 2/3, Instant, etc.)
- ✅ Event deduplication (no more duplicate announcements)
- ✅ Improved summary with card counts

**Code Architecture**
- ✅ New `CardDatabase` class for card name lookups
- ✅ `GameState` class to track match state
- ✅ Cleaner event processing with proper filtering
- ✅ Removed duplicate/noisy output

### Files Added
- `src/mtga_tracker/card_database.py` - Card name resolution
- `docs/EXAMPLE_OUTPUT.md` - Example of improved output
- `CHANGELOG.md` - This file

### Files Modified
- `src/mtga_tracker/tracker.py` - Complete rewrite of event handling
- `src/mtga_tracker/log_parser.py` - Improved JSON parsing (by user)

### Breaking Changes
None - backwards compatible

## v0.1.0 - Initial Release (2025-11-19)

### Features
- Basic log file monitoring
- Cross-platform support (macOS, Windows)
- Card ID tracking
- Console output
- Player vs opponent tracking
