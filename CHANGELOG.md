# Changelog

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
