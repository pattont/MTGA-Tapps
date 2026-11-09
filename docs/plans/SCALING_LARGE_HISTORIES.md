# Scaling to tens of thousands of games

Status: planned, not built. Measured 2026-11-09 during the performance pass.
The question it answers: what happens to a player who logs 2,000–3,000 ranked
games a month, a year from now?

## Measured

Travis's real database (1,256 games, 160 MB) was replicated 10x and 30x with
new ids and shifted dates (`game_events`, `console_logs` and raw payloads were
not replicated, so the file sizes below understate a real database of that
size by roughly 3x). Cold timings over HTTP against the dashboard, after the
2026-11-08 fixes:

| Page | 1,256 games | 12,560 games | 37,680 games |
| --- | --- | --- | --- |
| Overview (`/api/snapshot`) | 0.3 s, 380 KB | 3.1 s, 790 KB | 7.9 s, 1.5 MB |
| All Games (`/api/games`) | 0.15 s, 757 KB | 2.1 s, 7.5 MB | 8.9 s, 22 MB |
| Deck page (`/api/deck`) | 0.2 s | 2.3 s | 6.7 s |
| Game page (`/api/game`) | 0.02 s | 0.06 s | 0.16 s |
| Live Scoreboard / overlay polls | < 1 ms | 20 ms | 58 ms |
| Dashboard process RSS | 115 MB | 196 MB | 364 MB |

Everything scales linearly with the number of games, nothing quadratic. The
second request of each page within 60 s is served from the response cache in
about 10 ms; the cost is paid on every first visit and after every finished
game. The Overview is the landing page, so at 37k games the tracker opens on an
eight-second spinner. That is the number that decides whether a heavy player
keeps the tracker.

### Where the Overview's time goes (12,560 games, profiled)

| Part | Share | What it is |
| --- | --- | --- |
| SQL | ~45% | 169 statements; the costly ones scan `game_card_summary`, `game_deck_cards`, `game_drawn_cards` and `game_opening_hand_cards` across all history: deck land profile (0.5 s), deck visuals window query (0.3 s), card roles (0.25 s), drawn-card table (0.15 s) |
| Per-game draw quality in Python | ~30% | `_draw_quality_batch` → `draw_quality_metrics` once per game, every request, over the opener and draws of every game |
| Format normalisation | ~12% | `normalize_match_format` ~37,000 calls per request on a handful of distinct raw labels |
| Row conversion, colours, labels | ~13% | `_dict_rows`, `_display_opponent_colors`, `format_label` per row |

The deck page has the same shape: it builds deck-wide maps for *every* deck
(`_deck_color_map`, `_deck_visuals`) and the full card-role table, then picks
one deck out.

## Principle

Per-game facts that never change once the game is over are computed once,
stored, and read back. Aggregates (win rates by deck, format, mulligan count,
opener lands, momentum) stay as SQL over indexed columns: they are cheap when
the per-row inputs are columns rather than Python. Only games recorded since
the last launch need computing. When a rule changes, a version constant is
bumped and one pass recomputes every stored row; the mechanism already exists
(`maintenance_state`, see AGENTS.md).

This is not a rewrite of the dashboard. It is one new table, one write at game
end, one startup pass, and a handful of read functions switching from
"compute per row" to "read the column". The pages, their payloads and their
numbers do not change; a test proves it.

## Step 1 — exact quick wins (no schema change)

1. Memoise `normalize_match_format` / `format_label` on their arguments
   (`functools.lru_cache`; the inputs are a few dozen distinct raw labels).
   Removes ~12% of every page.
2. Make the deck page compute its maps for the requested deck only
   (`_deck_color_map`, `_deck_visuals`, the card-role table all accept a deck
   filter). The deck page becomes proportional to the deck, not the history.
3. Index review for the scanning queries above with `EXPLAIN QUERY PLAN` on the
   30x copy; add covering indexes where a scan over `game_card_summary` or
   `game_deck_cards` can become an index range (candidates:
   `game_deck_cards(participant_id, deck_zone, display_name)`,
   `game_card_summary(game_id, display_name)`).
4. All Games: send only the fields the page renders (the response is 22 MB at
   37k games, much of it unused per-row text).

Expected: Overview and deck page roughly halve; All Games transfer shrinks.
Each change is verifiable by comparing payloads before and after on the real
database copy (byte-identical except for removed unused fields).

## Step 2 — stored per-game derived values

New table `game_derived`, one row per game (or per player participant):

| Column | Source today |
| --- | --- |
| `is_flood`, `is_screw`, `is_land_streak`, `cards_seen`, `lands_seen`, `land_seen_pct`, `flood_probability_pct`, `screw_probability_pct`, `expected_land_rate`, `land_rate_source`, `reason` | `draw_quality_metrics` over opener + draws + decklist |
| `format_label`, `format_family`, `is_ranked` | `format_normalizer` over `matches.format` / `best_of` |
| `deck_colors` | `_participant_deck_color_map` over the submitted decklist and `cards.color_identity` |
| `opp_colors` | revealed cards / opponent commanders and `cards.color_identity` |
| `rules_version` | the constant that recomputes rows when any rule above changes |

Writers:
- The tracker, at game end, in the same persistence step as the game row,
  calling the exact functions the dashboard uses today.
- A startup pass with a `maintenance_state` watermark on `games.rowid`
  (games without a row), plus a full recompute when `rules_version` changes.

Refresh triggers (the two inputs that can change after a game ends):
- **Card colours.** The startup colour/mana backfill fills `cards` rows that
  were unknown when a game was played. When it writes any row, mark the
  derived rows of games that reference those cards for recompute (one query
  over `game_card_summary`/`game_deck_cards` by `card_id`).
- **Borrowed decklists.** A game with no submitted list borrows the deck's
  nearest list for its land rate (`land_rate_source = deck_history`). Travis
  considers this a non-issue in the current build. Before building, count
  such games on a real database (`land_rate_source != 'submitted'` in Game
  Detail); if the count is zero or negligible, store the verdict as computed
  and let the versioned recompute cover the rest.

Readers to switch: `dashboard_snapshot` (recent games, draw-quality tables,
momentum, deck table colours), `all_games`, `deck_detail` (Normal/Flood/Screw
split, land profile), `game_detail` (the badge; it can keep computing live for
the current game). Each reads `game_derived` and falls back to computing only
for a game that has no row yet (the game in progress).

Exactness: a test loads a real database copy, runs the old compute path and
the stored path over every game, and asserts every value identical; the live
write and the backfill share one function so they cannot diverge.

Expected: Overview and All Games lose their per-game Python entirely and most
of their card-table scans; at 37k games the Overview should be well under a
second cold.

## Step 3 — what stays large

- `console_logs` is already a rolling window: `CONSOLE_LOG_RETENTION_DAYS` (30)
  is pruned at every store connect, and migration 38 made the first cut and
  compacted the file. It no longer grows with the history. The one copy of the
  printed history that remains is `game_events` (`visible = 1`), roughly
  1.7 GB at 37k games; the [raw log archive](RAW_LOG_ARCHIVE.md) plan decides
  whether the originals replace any of it. Nothing in this plan depends on
  that decision.
- `raw_game_payloads` is pruned after 30 days and does not grow either.
- Backups and merges move whole tables; a multi-GB database makes the
  pre-update backup and restore slow. Measure once Step 2 is in.
- The dashboard process holds about 10 KB of RSS per game across its caches
  (364 MB at 37k). The response cache is bounded by entry count, not bytes;
  bound it by bytes.

## Upgrading an existing database

What a user with history sees on the first launch after an update that
carries Step 2. The updater's side is unchanged: the signed download, the
mandatory `pre-update` `.tappsbackup`, the hand-off and the "Updated to X"
notice all run as they do today, and the backup is the recovery path.

Two mechanisms exist for one-time work at startup, and they block different
things. Which one Step 2 uses is the design decision:

- **A numbered migration** runs inside `AnalyticsStore` construction, on the
  launcher's main thread, before the dashboard thread or the tracker exist
  (`app.start_dashboard` builds the store first). A migration that recomputes
  every game would make a 37k-game launch sit with no tray icon, no dashboard
  and no tracking until it finishes. Step 2's backfill must **not** be a
  migration. The migration creates the empty `game_derived` table and nothing
  else, which is instant.
- **A watermarked startup pass** runs in the tracker thread, inside the
  startup banner (`tracker_runtime`, next to turn-time recovery and the colour
  backfill), after the dashboard is already serving. The dashboard stays up
  while it runs, but the tracker prints "Now ready to track" only when the
  passes finish. A pass that takes minutes on a large database delays
  tracking: a user who updates and starts a game at once would be attached
  mid-game, and that game is never persisted.

So the backfill is a watermarked pass with two additions:

1. **Bounded work per launch, or a background thread.** The pass processes
   games in batches (say 500 per transaction, newest first, so Recent Games is
   fast first) and either stops after a time budget and resumes at the next
   launch from its watermark, or runs on a daemon thread after the banner so
   tracking starts immediately. Either way the tracker is ready within
   seconds of launch regardless of history size. The budget must still make
   progress on a database where the budget is never enough; batching by
   rowid with a persisted watermark guarantees that.
2. **Readers never wait for it.** Every reader of `game_derived` falls back to
   today's compute path for games without a row (the plan already requires
   this for the game in progress). During the backfill the dashboard is
   exactly as fast as it is today, and gets faster as rows land. Nothing is
   wrong or missing while the pass is incomplete; the Overview is only slow.

Rows written by the live tracker at game end and rows written by the pass
come from one function, so a game recorded between launch and the pass
reaching it is not a special case.

Other upgrade properties worth stating:

- **Rule changes later.** Bumping `rules_version` makes the pass recompute
  every row under the same budget; until it reaches a game, the game's row is
  stale, not missing. Readers prefer a row whose version matches the current
  constant and otherwise fall back to computing live, so a rule change never
  shows old verdicts, only slower pages until the pass catches up.
- **Downgrade.** `game_derived` is additive. An older build ignores the table
  and computes live, as it does today; `db_newer_than_app` reports it. No
  data is lost in either direction.
- **Backups and merges.** `game_derived` is derived data and need not travel
  in `.tappsbackup`; a restore or merge clears the watermark
  (`merge_snapshot_into` already clears `maintenance_state`) and the next
  launch recomputes. A reset empties it (`RESET_TABLES`).
- **Disk.** One narrow row per game, a few hundred bytes; at 37k games about
  10–20 MB. Negligible against the 160 MB per 1,256 games the history already
  costs.
- **First launch cost, measured before shipping.** Time the pass on the 10x
  and 30x copies with the batch size chosen; the acceptance number is
  "tracking ready in under five seconds on the 30x copy", not the total
  backfill time.

## Order

Step 1 first (exact, small, measurable), then Step 2 behind a plan review, then
Step 3 together with the archive decision. Re-measure on the 10x and 30x copies
after each step with the same table as above; the build script lives in the
performance-pass scratch notes and takes a minute to recreate from a real
database with `.backup`.
