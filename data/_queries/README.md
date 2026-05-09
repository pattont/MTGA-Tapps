# MTGA Tracker Queries

Run any query with:

```sh
sqlite3 data/mtga_tracker.sqlite3 < data/_queries/GamesPerDeck.sql
```

Useful starting points:

- `GamesPerDeck.sql`: deck-level win/loss summary.
- `WinRateByDeck.sql`: deck-level win rate with average game length.
- `RecentGames.sql`: latest games with deck, outcome, duration, mulligans, and life totals.
- `SessionPlayTime.sql`: tracker sessions using active game play time, not idle process uptime.
- `OpeningHandCardStats.sql`: opening-hand card frequency and win rate by deck.
- `OpeningHandCardFrequency.sql`: opening-hand card frequency including duplicate copies seen.
- `CardPerformancePlayed.sql`: cards played and associated game outcomes.
- `CardPlayedFrequency.sql`: played-card frequency and win rate when played.
- `MulliganStatsByDeck.sql`: win rate grouped by deck and mulligan count.
- `DeckCombatDamageStats.sql`: aggregate combat, damage, draw, discard, and mill stats by deck.
- `GameTimeline.sql`: event timeline for one game after replacing `PASTE_GAME_ID_HERE`.
- `UnknownDeckGames.sql`: games still missing a deck name, useful for backfill/debugging.
