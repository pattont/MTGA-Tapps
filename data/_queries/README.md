# MTGA Tracker Queries

Run any query with:

```sh
sqlite3 data/mtga_tracker.sqlite3 < data/_queries/GamesPerDeck.sql
```

Useful starting points:

- `GamesPerDeck.sql`: deck-level win/loss summary.
- `RecentGames.sql`: latest games with deck, outcome, duration, mulligans, and life totals.
- `OpeningHandCardStats.sql`: opening-hand card frequency and win rate by deck.
- `CardPerformancePlayed.sql`: cards played and associated game outcomes.
- `MulliganStatsByDeck.sql`: win rate grouped by deck and mulligan count.
- `DeckCombatDamageStats.sql`: aggregate combat, damage, draw, discard, and mill stats by deck.
- `GameTimeline.sql`: event timeline for one game after replacing `PASTE_GAME_ID_HERE`.
- `UnknownDeckGames.sql`: games still missing a deck name, useful for backfill/debugging.
