# Tracker Enhancement Backlog

This list captures high-value tracker improvements identified after adding visible drawn-card persistence and draw-quality reports.

## Recommended Next Work

1. **Draw-bias evidence pack**
   Track per-game expected vs. actual draws, opening hand quality, land streaks, duplicate streaks, on-play/on-draw, matchup, mulligans, and outcome. This will not prove matchmaking is weighted by itself, but it makes the data defensible instead of anecdotal.

2. **Backfill from saved raw payloads/logs**
   If `raw_game_payloads`, console logs, or old `Player.log` files contain visible draw identities, replay them into `game_drawn_cards`. Older rows may not have enough data, but a backfill tool should recover whatever is available.

3. **Decklist-aware statistics**
   Replace assumptions like `--land-rate 0.37` and `--card-copies 4` with the actual decklist when available. This lets the tracker know exact land count, spell count, card copies, curve, and expected probabilities per deck.

4. **Matchmaking/momentum audit**
   Add reports for win/loss streaks, opponent archetypes after wins/losses, on-play frequency after wins/losses, mulligan frequency after wins/losses, and draw quality by recent record. This is the closest path to testing whether results cluster around a 50% win rate.

5. **Dashboard upgrade**
   Surface the SQL reports in the local dashboard with filters for deck, format, date range, play/draw, and target card. The data is becoming too rich for one-off CLI output.

6. **Combat/stack explanation improvements**
   Improve the live tracker by adding attack targets, combat death attribution, ability costs/effects, and trigger descriptions.

## Suggested Priority

Start with decklist-aware draw and matchmaking audits. They provide the best foundation for answering questions about weighted draws, streaks, and win-rate pressure with real statistics.
