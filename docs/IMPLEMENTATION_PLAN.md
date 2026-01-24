# Implementation Plan: Combat, Targeting, and Abilities Tracking

## Overview

This document outlines the plan to implement three major features:
1. **Combat Tracking** - Show which creatures attacked/blocked
2. **Targeting Info** - Show what spells/abilities targeted
3. **Triggers/Abilities** - Track card abilities and triggered effects

## Current State Analysis

### What Already Exists

1. **Combat Infrastructure (Partial)**
   - `_handle_attacker_declared()` - Exists but may need enhancement
   - `_handle_blocker_declared()` - Working, shows blocking
   - `self.game_state.attackers` - Tracks attacker instance IDs
   - `self.game_state.blockers` - Tracks blocker → attacker mappings

2. **Targeting Infrastructure (Partial)**
   - `target_id` extraction from annotation details
   - `target_obj` lookup in gameObjects
   - `target_str` formatting for spells (lines 711-717)
   - Currently only works for CastSpell category

3. **Abilities/Triggers**
   - No current implementation

## Implementation Plan

### Phase 1: Enhance Combat Tracking

#### 1.1 Attack Declaration
**Status**: Partially implemented
**Current**: `_handle_attacker_declared()` exists but may not be called correctly

**Tasks**:
- [ ] Verify `AnnotationType_AttackerDeclared` is being detected
- [ ] Ensure attacker names are displayed correctly
- [ ] Show attack target (player vs planeswalker vs creature)
- [ ] Track attack phase state
- [ ] Display combat summary at end of combat step

**Expected Output**:
```
⚔️  Turn 5 - YOUR TURN
   Life: You 18 - 20 Opponent
======================================================================

⚔️ You      attacking with Serra Angel (4/4)
⚔️ You      attacking with Llanowar Elves (1/1)
```

#### 1.2 Block Declaration
**Status**: Working
**Current**: `_handle_blocker_declared()` shows blocking

**Tasks**:
- [ ] Verify all blocking scenarios are covered
- [ ] Handle multiple blockers on one attacker
- [ ] Handle one blocker blocking multiple attackers

**Expected Output**:
```
🛡️ Opponent blocking Serra Angel with Vampire Nighthawk (2/3)
```

#### 1.3 Combat Damage Resolution
**Status**: Partial
**Current**: `_handle_damage()` shows damage but doesn't link to combat

**Tasks**:
- [ ] Link damage events to combat phase
- [ ] Show combat damage separately from non-combat damage
- [ ] Display which creatures dealt/received combat damage
- [ ] Show if creatures died from combat damage

**Expected Output**:
```
💥 Combat damage: Serra Angel (4/4) dealt 4 damage to opponent (16)
💥 Combat damage: Vampire Nighthawk (2/3) dealt 2 damage to Serra Angel (your)
💥 Serra Angel (your) was destroyed (combat damage)
```

### Phase 2: Enhance Targeting Information

#### 2.1 Spell Targeting
**Status**: Partially implemented
**Current**: Targeting code exists but may not work for all spell types

**Tasks**:
- [ ] Verify targeting works for all spell categories
- [ ] Test with different target types (creature, player, planeswalker, etc.)
- [ ] Handle spells with multiple targets
- [ ] Show targeting for abilities (not just spells)

**Expected Output**:
```
> You      cast Lightning Bolt (Instant) targeting Vampire Nighthawk (opponent's)
> You      cast Doom Blade (Instant) targeting Serra Angel (your)
```

#### 2.2 Ability Targeting
**Status**: Not implemented

**Tasks**:
- [ ] Detect activated abilities in annotations
- [ ] Extract ability source (card name)
- [ ] Extract ability targets
- [ ] Display ability activations

**Expected Output**:
```
🔮 You      activated ability: Lightning Bolt (your) targeting opponent
🔮 Opponent activated ability: Shock (opponent's) targeting you
```

#### 2.3 Triggered Abilities
**Status**: Not implemented

**Tasks**:
- [ ] Detect triggered ability annotations
- [ ] Identify trigger source
- [ ] Show trigger effects
- [ ] Link triggers to their causes

**Expected Output**:
```
✨ Triggered: When Serra Angel attacks, you gain 1 life
✨ Triggered: When Vampire Nighthawk dies, opponent draws a card
```

### Phase 3: Implement Abilities and Triggers Tracking

#### 3.1 Activated Abilities
**Status**: Not implemented

**Annotation Types to Look For**:
- `AnnotationType_AbilityActivated`
- `AnnotationType_ActivatedAbility`
- Look for ability-related details in annotations

**Tasks**:
- [ ] Research MTGA log structure for activated abilities
- [ ] Create `_handle_ability_activated()` method
- [ ] Extract ability source card
- [ ] Extract ability cost (if available)
- [ ] Extract ability targets/effects
- [ ] Display ability activations

**Expected Output**:
```
🔮 You      activated: Lightning Bolt (your) → Deal 3 damage to target creature or player
🔮 Opponent activated: Shock (opponent's) → Deal 2 damage to target creature or player
```

#### 3.2 Triggered Abilities
**Status**: Not implemented

**Annotation Types to Look For**:
- `AnnotationType_TriggeredAbility`
- `AnnotationType_Triggered`
- Look for trigger-related details

**Tasks**:
- [ ] Research MTGA log structure for triggered abilities
- [ ] Create `_handle_triggered_ability()` method
- [ ] Identify trigger conditions (ETB, dies, attacks, etc.)
- [ ] Extract trigger source
- [ ] Extract trigger effects
- [ ] Display triggers with context

**Expected Output**:
```
✨ Triggered: When Serra Angel enters the battlefield, you gain 1 life
✨ Triggered: When Vampire Nighthawk dies, opponent draws a card
✨ Triggered: When you attack, Serra Angel gets +1/+1 until end of turn
```

#### 3.3 Static Abilities
**Status**: Not implemented

**Tasks**:
- [ ] Research how static abilities appear in logs
- [ ] Identify when static abilities affect the game
- [ ] Display static ability effects (if trackable)

**Note**: Static abilities may be harder to track as they don't always generate events.

## Technical Implementation Details

### Annotation Types to Monitor

Based on MTGA log structure, we need to look for:

1. **Combat**:
   - `AnnotationType_AttackerDeclared`
   - `AnnotationType_BlockerDeclared`
   - `AnnotationType_CombatDamageDealt`
   - `AnnotationType_Damage` (in combat context)

2. **Targeting**:
   - `target` or `target_id` in annotation details
   - `targets` (array) for multiple targets
   - Check in both `CastSpell` and ability annotations

3. **Abilities**:
   - `AnnotationType_AbilityActivated`
   - `AnnotationType_TriggeredAbility`
   - `AnnotationType_ActivatedAbility`
   - Look for `ability` or `ability_id` in details

### Data Structures Needed

```python
class GameState:
    # ... existing fields ...
    
    # Combat tracking (enhanced)
    combat_phase_active: bool = False
    current_attackers: Dict[int, Dict] = {}  # instance_id -> {card_name, power, toughness, target}
    current_blockers: Dict[int, Dict] = {}  # blocker_id -> {attacker_id, blocker_info}
    
    # Targeting tracking
    spell_targets: Dict[int, List[int]] = {}  # spell_instance_id -> [target_instance_ids]
    ability_targets: Dict[int, List[int]] = {}  # ability_id -> [target_instance_ids]
    
    # Abilities tracking
    activated_abilities: List[Dict] = []  # List of ability activations
    triggered_abilities: List[Dict] = []  # List of triggered abilities
```

### Methods to Add/Enhance

1. **`_handle_combat_phase()`** - Detect combat phase start/end
2. **`_handle_combat_damage()`** - Process combat-specific damage
3. **`_enhance_targeting()`** - Improve targeting extraction
4. **`_handle_ability_activated()`** - Process activated abilities
5. **`_handle_triggered_ability()`** - Process triggered abilities
6. **`_display_combat_summary()`** - Show combat results

## Testing Strategy

### Unit Tests
- Test attacker declaration parsing
- Test blocker declaration parsing
- Test targeting extraction for various spell types
- Test ability detection

### Integration Tests
- Run tracker during actual MTGA games
- Verify combat tracking works correctly
- Verify targeting shows correctly
- Verify abilities are detected

### Manual Testing Checklist
- [ ] Attack with single creature → shows attack
- [ ] Attack with multiple creatures → shows all attacks
- [ ] Block single attacker → shows blocking
- [ ] Block multiple attackers → shows all blocks
- [ ] Cast spell targeting creature → shows target
- [ ] Cast spell targeting player → shows target
- [ ] Activate ability → shows activation
- [ ] Triggered ability fires → shows trigger

## Implementation Order

### Priority 1: Combat Tracking (Most Visible)
1. Fix/enhance attacker declaration display
2. Enhance combat damage display
3. Add combat summary

### Priority 2: Targeting Info (High Value)
1. Fix targeting for all spell types
2. Add targeting for abilities
3. Handle multiple targets

### Priority 3: Abilities/Triggers (Complex)
1. Research ability annotation structure
2. Implement activated abilities
3. Implement triggered abilities

## Success Criteria

### Combat Tracking
- ✅ All attackers are displayed when declared
- ✅ All blockers are displayed when declared
- ✅ Combat damage is clearly shown
- ✅ Combat results are summarized

### Targeting Info
- ✅ All targeted spells show their targets
- ✅ All targeted abilities show their targets
- ✅ Multiple targets are shown correctly
- ✅ Target ownership is clear

### Abilities/Triggers
- ✅ Activated abilities are detected and displayed
- ✅ Triggered abilities are detected and displayed
- ✅ Ability sources are identified
- ✅ Ability effects are shown

## Future Enhancements

1. **Combat History** - Track all combat interactions in a game
2. **Ability History** - Track all abilities used in a game
3. **Targeting Analysis** - Show targeting patterns/statistics
4. **Combat Statistics** - Show damage dealt/received per creature
