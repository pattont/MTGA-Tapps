# Example Output

This document shows what the improved MTGA Tracker output looks like during a game.

## Starting the Tracker

```
======================================================================
🎮 MTGA Card Tracker - Real-time Match Analyzer
======================================================================
📂 Monitoring: /Users/username/Library/Logs/Wizards Of The Coast/MTGA/Player.log
💾 Card cache: 45 cards loaded

   Waiting for match to start...
   Play a game in MTGA to see cards tracked in real-time!

   Press Ctrl+C to stop
======================================================================

```

## During a Match

```
======================================================================
⚔️  Turn 1 - YOUR TURN
   Life: You 20 - 20 Opponent
======================================================================

🎯 You      cast Plains (Land)

======================================================================
⚔️  Turn 2 - OPPONENT'S TURN
   Life: You 20 - 20 Opponent
======================================================================

👤 Opponent  cast Swamp (Land)
👤 Opponent  cast Dark Ritual (Instant)

======================================================================
⚔️  Turn 3 - YOUR TURN
   Life: You 20 - 20 Opponent
======================================================================

🎯 You      cast Plains (Land)
🎯 You      cast Llanowar Elves (Creature 1/1)

======================================================================
⚔️  Turn 4 - OPPONENT'S TURN
   Life: You 20 - 20 Opponent
======================================================================

👤 Opponent  cast Swamp (Land)
👤 Opponent  cast Vampire Nighthawk (Creature 2/3)

💔 You lost 2 life (18)

======================================================================
⚔️  Turn 5 - YOUR TURN
   Life: You 18 - 20 Opponent
======================================================================

🎯 You      cast Forest (Land)
🎯 You      cast Lightning Bolt (Instant)
💥 Vampire Nighthawk (opponent's) was destroyed

   Opponent lost 3 life (17)

======================================================================
⚔️  Turn 6 - OPPONENT'S TURN
   Life: You 18 - 17 Opponent
======================================================================

👤 Opponent  cast Mountain (Land)
👤 Opponent  cast Anger of the Gods (Sorcery)

💥 Llanowar Elves (your) was destroyed

======================================================================
⚔️  Turn 7 - YOUR TURN
   Life: You 18 - 17 Opponent
======================================================================

🎯 You      cast Opt (Instant)
🔮 You scried
📥 You drew a card

🎯 You      cast Forest (Land)
🎯 You      cast Serra Angel (Creature 4/4)

======================================================================
⚔️  Turn 8 - OPPONENT'S TURN
   Life: You 18 - 17 Opponent
======================================================================

👤 Opponent  cast Doom Blade (Instant)
💥 Serra Angel (your) was destroyed

👤 Opponent  cast Thoughtseize (Sorcery)
🗑️ Wrath of God (your) was discarded

💔 You lost 2 life (16)
```

## When You Stop the Tracker (Ctrl+C)

```
======================================================================
🛑 Stopping tracker...

📊 Session Summary
======================================================================
   Final Life: You 12 - 0 Opponent
   Turns Played: 8
   Your cards played: 12
   Opponent cards played: 15

   🎯 Your Cards This Game:
      • Forest x3
      • Lightning Bolt x2
      • Llanowar Elves x2
      • Plains x3
      • Shock x2

   👤 Opponent's Cards This Game:
      • Anger of the Gods
      • Dark Ritual x2
      • Mountain x2
      • Swamp x4
      • Vampire Nighthawk x3
      • Vraska's Contempt

======================================================================
```

## Key Improvements

### What's Better Now

1. **Card Names** - Shows actual card names instead of IDs
   - `Lightning Bolt` instead of `Card ID 74567`

2. **Clear Turn Markers** - Easy to follow game flow
   - Turn number, whose turn, life totals

3. **Life Tracking** - See damage and healing
   - `💔 You lost 2 life (18)`
   - `💚 You gained 3 life (23)`

4. **Visual Icons** - Quick visual identification
   - 🎯 Your cards
   - 👤 Opponent cards
   - 💥 Cards destroyed
   - ⚔️ Turn markers

5. **Card Types** - Know what kind of card was played
   - `(Creature 2/3)` for creatures with power/toughness
   - `(Instant)`, `(Sorcery)`, etc.

6. **Deduplication** - Each card announced only once
   - No more seeing the same card 3 times

7. **Interaction Tracking** - See what happens to cards
   - Destruction: `💥 Serra Angel (your) was destroyed`
   - Exile: `🚫 Tarmogoyf (opponent's) was exiled`
   - Counters: `🚫 Lightning Bolt (your) was countered`
   - Discard: `🗑️ Force of Will (your) was discarded`
   - Shows ownership: your vs opponent's cards

8. **Instant Detection** - Instants are now tracked properly
   - Catches both CastSpell and PlaySpell categories
   - Shows when instants resolve

9. **Additional Effects** - Tracks more game actions
   - Card draw: `📥 You drew a card`
   - Scry: `🔮 You scried`
   - Mill: `🌊 You milled Brainstorm`
   - Sacrifice: `⚰️ Bloodghast (your) was sacrificed`

10. **Summary** - Game overview with card counts
    - See what cards were played multiple times
    - Quick deck analysis

### What's Not Perfect Yet

These are areas for future improvement:

1. **Card names may take a moment** - First time seeing a card, needs to fetch from Scryfall API
2. **No combat tracking** - Doesn't show which creatures attacked/blocked
3. **No targeting info** - Doesn't show what Lightning Bolt targeted
4. **No triggers/abilities** - Doesn't track card abilities or triggered effects
5. **Match result not detected** - Doesn't announce who won

These can be added in future versions based on further log analysis.
