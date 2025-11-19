# Interaction Examples

This document shows how different card interactions are now tracked.

## Casting Spells (Including Instants)

The tracker now catches both `CastSpell` and `PlaySpell` categories to ensure instants are detected:

```
🎯 You      cast Lightning Bolt (Instant)
🎯 You      cast Shock (Instant)
👤 Opponent  cast Counterspell (Instant)
👤 Opponent  cast Llanowar Elves (Creature 1/1)
🎯 You      cast Wrath of God (Sorcery)
```

## Destruction Effects

When a card is destroyed, the tracker shows:
- What card was destroyed
- Who owned it (your vs opponent's)
- The type of removal

```
🎯 You      cast Murder (Instant)
💥 Llanowar Elves (opponent's) was destroyed

👤 Opponent  cast Doom Blade (Instant)
💥 Serra Angel (your) was destroyed
```

## Exile Effects

```
🎯 You      cast Path to Exile (Instant)
🚫 Tarmogoyf (opponent's) was exiled

👤 Opponent  cast Swords to Plowshares (Instant)
🚫 Dark Confidant (your) was exiled
```

## Sacrifice Effects

```
🎯 You      cast Viscera Seer (Creature 1/1)
⚰️ Bloodghast (your) was sacrificed

👤 Opponent  cast Diabolic Edict (Sorcery)
⚰️ Delver of Secrets (your) was sacrificed
```

## Counterspells

```
🎯 You      cast Lightning Bolt (Instant)
👤 Opponent  cast Counterspell (Instant)
🚫 Lightning Bolt (your) was countered
```

## Discard Effects

```
👤 Opponent  cast Thoughtseize (Sorcery)
🗑️ Brainstorm (your) was discarded

🎯 You      cast Hymn to Tourach (Sorcery)
🗑️ Dark Ritual (opponent's) was discarded
🗑️ Force of Will (opponent's) was discarded
```

## Card Draw

```
🎯 You      cast Opt (Instant)
📥 You drew a card

👤 Opponent  cast Brainstorm (Instant)
   Opponent drew a card
```

## Scry

```
🎯 You      cast Serum Visions (Sorcery)
🔮 You scried
📥 You drew a card

👤 Opponent  cast Opt (Instant)
🔮 Opponent scried
   Opponent drew a card
```

## Mill Effects

```
👤 Opponent  cast Thought Scour (Instant)
🌊 You milled Tarmogoyf
🌊 You milled Dark Ritual

🎯 You      cast Glimpse the Unthinkable (Sorcery)
🌊 Opponent milled Force of Will
🌊 Opponent milled Brainstorm
🌊 Opponent milled Island
... (continues for all milled cards)
```

## Complex Interaction Example

Here's a complete turn with multiple interactions:

```
======================================================================
⚔️  Turn 4 - YOUR TURN
   Life: You 15 - 18 Opponent
======================================================================

🎯 You      cast Mountain (Land)
🎯 You      cast Lightning Bolt (Instant)
💔 You lost 2 life (13)
💥 Tarmogoyf (opponent's) was destroyed

👤 Opponent  cast Fatal Push (Instant)
💥 Goblin Guide (your) was destroyed

🎯 You      cast Monastery Swiftspear (Creature 1/2)
```

## Seam Rip Example (Your Specific Case)

When opponent plays Seam Rip on your creature:

```
👤 Opponent  cast Seam Rip (Instant)
💥 Serra Angel (your) was destroyed
```

Or if you use it:

```
🎯 You      cast Seam Rip (Instant)
💥 Vampire Nighthawk (opponent's) was destroyed
```

## Icon Legend

- 🎯 **You** cast a card
- 👤 **Opponent** cast a card
- 💥 **Destroyed** - permanent destroyed
- 🚫 **Exiled/Countered** - card exiled or spell countered
- ⚰️ **Sacrificed** - permanent sacrificed
- 🗑️ **Discarded** - card discarded from hand
- 📥 **Drew** - card drawn
- 🔮 **Scry** - player scried
- 🌊 **Mill** - card milled to graveyard
- 💚 **Life Gain** - player gained life
- 💔 **Life Loss** - player lost life
- ⚔️ **Turn** - new turn started

## What's Still Not Tracked

Some interactions are very complex and may not show perfectly:

1. **Targeting** - We don't show "Lightning Bolt targeting Llanowar Elves" yet
2. **Combat** - Attacking/blocking declarations not tracked
3. **Triggers** - Triggered abilities not shown separately
4. **Stack ordering** - Multiple spells on stack shown in log order
5. **Partial effects** - "Draw 2 cards" shows as 2 separate draws

These may be added in future versions as we analyze more log patterns!
