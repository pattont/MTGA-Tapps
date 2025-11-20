# Complete Game Tracking

This document shows the comprehensive game tracking features added in v0.4.0.

## Game Flow

### 1. Game Start

```
======================================================================
🎮 GAME STARTED
======================================================================

🔄 Mulligan to 6 (mulligans: 1)

🎴 Your Starting Hand (6 cards):
   • Lightning Bolt
   • Mountain
   • Mountain
   • Goblin Guide
   • Monastery Swiftspear
   • Shock
```

### 2. Gameplay

#### Turn Markers
```
======================================================================
⚔️  Turn 1 - YOUR TURN
   Life: You 20 - 20 Opponent
======================================================================
```

#### Spell Casting with Targets
```
🎯 You      cast Lightning Bolt (Instant) targeting Tarmogoyf (opponent's)
💥 Tarmogoyf (opponent's) was destroyed
   Opponent lost 3 life (now 17)

👤 Opponent  cast Murder (Instant) targeting Serra Angel (your)
💥 Serra Angel (your) was destroyed
```

#### Combat
```
⚔️ You      attacking with Goblin Guide (2/2)
⚔️ You      attacking with Monastery Swiftspear (1/2)

🛡️ Opponent  blocking Goblin Guide with Vampire Nighthawk (2/3)

💢 Goblin Guide (your) took 2 damage
💢 Vampire Nighthawk (opponent's) took 2 damage
💥 Goblin Guide (your) was destroyed

   Opponent lost 1 life (now 16)
```

#### Life Changes
```
💔 You lost 4 life (now 16)
💚 You gained 3 life (now 19)
   Opponent lost 2 life (now 15)
   Opponent gained 5 life (now 20)
```

#### Card Draw and Scry
```
🎯 You      cast Opt (Instant)
🔮 You scried
📥 You drew a card
```

### 3. Game End (Automatic)

```
======================================================================
🏁 GAME ENDED
======================================================================

⏱️  Game Duration: 8m 42s

🎉 You won! (Opponent at 0 life)

🎴 Starting Hand (6 cards):
   (After 1 mulligan(s))
   • Lightning Bolt
   • Mountain
   • Mountain
   • Goblin Guide
   • Monastery Swiftspear
   • Shock

📊 Cards Played:
   Your cards: 12
   Opponent cards: 15

   🎯 Your Cards:
      • Goblin Guide x2
      • Lightning Bolt x3
      • Monastery Swiftspear x2
      • Mountain x4
      • Shock

   👤 Opponent's Cards:
      • Counterspell x2
      • Island x5
      • Murder
      • Snapcaster Mage x2
      • Tarmogoyf x3
      • Thought Scour x2

======================================================================
Ready for next game...

```

## Complete Feature List

### Starting Hand Tracking
- ✅ Shows your opening hand
- ✅ Detects mulligans
- ✅ Counts mulligan number
- ✅ Tracks hand size (7, 6, 5, etc.)

### Spell Targeting
- ✅ Shows what card was targeted
- ✅ Shows who owned the target
- ✅ Works with removal, auras, counters, etc.

### Combat Tracking
- ⚔️ Attacker declarations with power/toughness
- 🛡️ Blocker declarations showing what's blocking what
- 💢 Combat damage tracking
- 💥 Creature deaths in combat

### Life Tracking
- ✅ Accurate between turns
- ✅ Only announces actual changes
- ✅ Shows life gain and life loss separately
- ✅ Shows current life total after change

### Game Timer
- ✅ Tracks from game start to end
- ✅ Shows duration in minutes and seconds
- ✅ Displayed in game summary

### Auto Game Detection
- ✅ Detects when game starts
- ✅ Detects when game ends
- ✅ Automatically shows summary
- ✅ Resets for next game
- ✅ No need to stop tracker between games

### Game Summary
- ✅ Win/loss detection
- ✅ Game duration
- ✅ Starting hand display
- ✅ All cards played by both players
- ✅ Card counts and duplicates

## Icon Reference

### Game Flow
- 🎮 Game started/ended
- ⏱️  Game duration
- 🔄 Mulligan
- 🎴 Starting hand
- 🎉 Victory
- 💀 Defeat
- 🏁 Game ended

### Spells
- 🎯 You cast
- 👤 Opponent cast
- 🚫 Exiled/Countered
- 💥 Destroyed
- ⚰️ Sacrificed
- 🗑️ Discarded

### Combat
- ⚔️ You attacking
- 🗡️ Opponent attacking
- 🛡️ Blocking
- 💢 Damage taken

### Card Draw/Scry
- 📥 Drew a card
- 🔮 Scried
- 🌊 Milled

### Life
- 💚 Life gained
- 💔 Life lost

## Example Complete Game

```
======================================================================
🎮 GAME STARTED
======================================================================

🎴 Your Starting Hand (7 cards):
   • Forest
   • Forest
   • Llanowar Elves
   • Tarmogoyf
   • Lightning Bolt
   • Mountain
   • Oko, Thief of Crowns

======================================================================
⚔️  Turn 1 - YOUR TURN
   Life: You 20 - 20 Opponent
======================================================================

🎯 You      cast Forest (Land)
🎯 You      cast Llanowar Elves (Creature 1/1)

======================================================================
⚔️  Turn 2 - OPPONENT'S TURN
   Life: You 20 - 20 Opponent
======================================================================

👤 Opponent  cast Island (Land)
👤 Opponent  cast Fatal Push (Instant) targeting Llanowar Elves (your)
💥 Llanowar Elves (your) was destroyed

======================================================================
⚔️  Turn 3 - YOUR TURN
   Life: You 20 - 20 Opponent
======================================================================

📥 You drew a card
🎯 You      cast Mountain (Land)
🎯 You      cast Tarmogoyf (Creature 2/3)

======================================================================
⚔️  Turn 4 - OPPONENT'S TURN
   Life: You 20 - 20 Opponent
======================================================================

👤 Opponent  cast Island (Land)
👤 Opponent  cast Snapcaster Mage (Creature 2/1)

======================================================================
⚔️  Turn 5 - YOUR TURN
   Life: You 20 - 20 Opponent
======================================================================

🎯 You      cast Forest (Land)
⚔️ You      attacking with Tarmogoyf (3/4)
💔 Opponent lost 3 life (now 17)

🎯 You      cast Oko, Thief of Crowns (Planeswalker)

======================================================================
⚔️  Turn 6 - OPPONENT'S TURN
   Life: You 20 - 17 Opponent
======================================================================

👤 Opponent  cast Mountain (Land)
👤 Opponent  cast Lightning Bolt (Instant) targeting Tarmogoyf (your)
💢 Tarmogoyf (your) took 3 damage
💥 Tarmogoyf (your) was destroyed

======================================================================
🏁 GAME ENDED
======================================================================

⏱️  Game Duration: 6m 23s

💀 You lost (0 life)

🎴 Starting Hand (7 cards):
   • Forest
   • Forest
   • Llanowar Elves
   • Tarmogoyf
   • Lightning Bolt
   • Mountain
   • Oko, Thief of Crowns

📊 Cards Played:
   Your cards: 6
   Opponent cards: 7

   🎯 Your Cards:
      • Forest x2
      • Llanowar Elves
      • Lightning Bolt
      • Mountain
      • Oko, Thief of Crowns
      • Tarmogoyf

   👤 Opponent's Cards:
      • Fatal Push
      • Island x2
      • Lightning Bolt
      • Mountain
      • Snapcaster Mage
      • Thoughtseize

======================================================================
Ready for next game...

```

## Benefits

1. **No manual intervention** - Tracker runs continuously
2. **Complete game record** - Starting hand through final summary
3. **Combat clarity** - See exactly what fought what
4. **Spell targeting** - Know what was targeted
5. **Accurate life tracking** - Only shows real changes
6. **Game timing** - See how long games take
7. **Multiple games** - Auto-resets between games
