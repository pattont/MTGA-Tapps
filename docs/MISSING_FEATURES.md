# Missing Features (Beyond Testing)

This document lists what has NOT been implemented yet from the implementation plan.

## Combat Tracking

### ❌ Attack Target Display
**Status**: Not implemented
**What's missing**: Show what attackers are targeting (player vs planeswalker vs creature)
- Currently shows: `⚔️ You attacking with Serra Angel (4/4)`
- Should show: `⚔️ You attacking opponent with Serra Angel (4/4)` or `⚔️ You attacking planeswalker with Serra Angel (4/4)`

**Implementation needed**: Extract attack target from annotation details (likely in `attackerDeclared` annotation)

### ❌ Multiple Blockers on One Attacker
**Status**: Partially handled (may work but not explicitly tested)
**What's missing**: When multiple creatures block one attacker, we should show all blockers clearly
- Current implementation handles one blocker at a time
- Need to verify it works correctly when multiple blockers are declared

### ❌ One Blocker Blocking Multiple Attackers
**Status**: Not implemented
**What's missing**: Some creatures can block multiple attackers (e.g., creatures with banding or special abilities)
- Current implementation assumes one blocker → one attacker
- Need to handle `blocker_id → [attacker_ids]` mapping

### ❌ Combat Death Detection
**Status**: Not implemented
**What's missing**: Explicitly show when creatures die from combat damage
- Currently shows: `⚔️ Combat: Serra Angel dealt 4 damage to Vampire Nighthawk`
- Should also show: `💥 Vampire Nighthawk (opponent's) was destroyed (combat damage)`
- Need to link destruction events to combat damage

## Abilities & Triggers

### ❌ Ability Cost Display
**Status**: Not implemented
**What's missing**: Show the cost paid to activate abilities
- Currently shows: `🔮 You activated ability: Lightning Bolt (your) targeting opponent`
- Should show: `🔮 You activated ability: Lightning Bolt (your) [Cost: {R}] targeting opponent`
- Need to extract cost from annotation details

### ❌ Ability Effect Description
**Status**: Not implemented
**What's missing**: Show what the ability actually does
- Currently shows: `🔮 You activated ability: Lightning Bolt (your) targeting opponent`
- Should show: `🔮 You activated ability: Lightning Bolt (your) → Deal 3 damage targeting opponent`
- This requires either:
  - Parsing ability text from card data
  - Or extracting effect description from annotation

### ❌ Enhanced Trigger Condition Parsing
**Status**: Partially implemented
**What's missing**: Better identification of common trigger conditions
- Currently shows: `✨ Triggered: Serra Angel (your) - triggered` (generic)
- Should show: `✨ Triggered: Serra Angel (your) - enters the battlefield`
- Or: `✨ Triggered: Vampire Nighthawk (opponent's) - dies`
- Or: `✨ Triggered: Serra Angel (your) - attacks`
- Need to parse common trigger types from `trigger_type` or infer from context

### ❌ Trigger Effect Display
**Status**: Not implemented
**What's missing**: Show what the trigger actually does
- Currently shows: `✨ Triggered: Serra Angel (your) - triggered`
- Should show: `✨ Triggered: When Serra Angel enters the battlefield, you gain 1 life`
- Need to extract trigger effect from annotation or link to resulting game events

### ❌ Static Abilities
**Status**: Not implemented (marked as future)
**What's missing**: Track static abilities that affect the game
- Static abilities don't always generate events, making them hard to track
- Examples: "Creatures you control get +1/+1", "Your opponents can't cast spells"
- May require analyzing game state changes rather than events

## Data Structures

### ❌ Comprehensive Tracking Dictionaries
**Status**: Partially implemented
**What's missing**: Some planned data structures weren't fully implemented:
- `spell_targets: Dict[int, List[int]]` - Track all spell targets for analysis
- `ability_targets: Dict[int, List[int]]` - Track all ability targets
- `activated_abilities: List[Dict]` - History of activated abilities
- `triggered_abilities: List[Dict]` - History of triggered abilities

**Note**: These were planned for future analysis features but aren't critical for basic functionality.

## Other Enhancements

### ❌ Combat Statistics
**Status**: Not implemented (marked as future)
**What's missing**: Track damage dealt/received per creature over the game
- Show total damage dealt by each creature
- Show total damage received by each creature
- Useful for game analysis

### ❌ Ability History
**Status**: Not implemented (marked as future)
**What's missing**: Track all abilities used in a game for summary
- Show which abilities were activated most
- Show which triggers fired most often

### ❌ Targeting Analysis
**Status**: Not implemented (marked as future)
**What's missing**: Show targeting patterns/statistics
- Which cards target which types of cards most
- Targeting patterns by player

## Summary

### Critical Missing Features (Should Implement)
1. **Attack target display** - Show what attackers are targeting
2. **Combat death detection** - Link creature deaths to combat damage
3. **Ability effect description** - Show what abilities do
4. **Enhanced trigger parsing** - Better trigger condition identification

### Nice-to-Have Features (Future Enhancements)
1. Multiple blockers on one attacker (verify it works)
2. One blocker blocking multiple attackers
3. Ability cost display
4. Trigger effect display
5. Static abilities tracking
6. Combat/ability statistics and history

### Already Implemented ✅
- Combat phase detection
- Attacker/blocker declaration display
- Combat damage tracking
- Combat summary
- Multiple target handling
- Player targeting
- Activated ability detection
- Triggered ability detection
- Basic targeting for spells and abilities
