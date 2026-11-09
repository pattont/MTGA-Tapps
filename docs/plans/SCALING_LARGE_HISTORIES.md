# Scaling to tens of thousands of games

Status: in progress on the `scaling-large-histories` branch. Step 0 (the test
tools and the hard failure) is built; Steps 1 to 3 are planned.
First measured 2026-11-09 during the performance pass, reviewed against the
code and re-measured the same day.
The question it answers: what happens to a player who logs 2,000–3,000 ranked
games a month, a year from now?

## The tools every step is checked with

- `scripts/build_scaled_db.py --factor N --out FILE` writes a copy of a real
  database holding N times its history: replicas shifted into the past, with
  their own session, match, game and participant ids and their own opponent
  names. It reads the source read-only. `game_events` is replicated only with
  `--events`; `console_logs`, `raw_game_payloads` and `rank_snapshots` never
  (the script's docstring says why).
- `scripts/dashboard_payloads.py dump --db COPY --out DIR` calls every read
  endpoint for a fixed set of requests taken from the database (the Overview
  under several filters, All Games, decks, games, opponents, cards, search,
  audit), writes each payload as JSON, and prints the cold time and size of
  each. `--src <other checkout>/src` runs another checkout's code, so `main`
  and a branch are compared on the same file.
- `scripts/dashboard_payloads.py diff A B` lists every value that differs
  between two dumps. **"The pages and their numbers do not change" means this
  prints `0 differ`** on the 1x copy and the 10x copy, apart from differences
  a step lists in advance.
- Both tools pin SQLite's bound-parameter limit to 32,766 on every connection
  (see Step 0), so a Mac run fails where a Windows user would.

## Measured

Travis's database (1,264 games, 102 MB after migration 38's compaction) and
its 10x and 30x copies, built with `build_scaled_db.py` (no `--events`, so
file sizes understate a real database). Cold times of the functions behind
each endpoint, 2026-11-09, on the dev Mac, after Step 0:

| Page | 1,264 games | 12,640 games | 37,920 games |
| --- | --- | --- | --- |
| Overview (`/api/snapshot`) | 0.3 s, 373 KB | 2.8 s, 694 KB | 9.8 s, 1.4 MB |
| Overview, last 7 days | 0.13 s | 1.0 s | 3.0 s |
| Overview, all-time trend | 0.3 s, 480 KB | 2.9 s, 1.9 MB | 9.9 s, 5.2 MB |
| All Games (`/api/games`) | 0.14 s, 744 KB | 1.4 s, 7.5 MB | 5.5 s, 22.6 MB |
| All Games, last 30 days | 0.04 s | 0.27 s | 0.8 s |
| Deck page (`/api/deck`), most-played decks | 0.2 s | 1.9 s | 6.6 s |
| Card page (`/api/card`) | 0.06 s | 0.76 s | 2.3 s |
| Card search (`/api/cards`, per keystroke) | 0.01 s | 0.1 s | 0.28 s |
| Opponent page (`/api/opponent`) | 0.03 s | 0.2 s | 0.5 s |
| Opponents list (`/api/opponents`) | 4 ms, 147 KB | 37 ms, 1.5 MB | 0.1 s, 4.5 MB |
| Game page (`/api/game`) | 0.02 s | 0.08 s | 0.2 s |
| Database health (`/api/audit`) | 1.2 s | 2.2 s | 4.4 s |

Earlier in the day, with the dashboard process running: Live Scoreboard and
overlay polls took under 1 ms, 20 ms and 58 ms, and the process held 115 MB,
196 MB and 364 MB.

Everything scales linearly with the number of games, nothing quadratic. Three
things the first measurement missed:

- **A filtered view still pays for the whole history.** Seven days of games
  cost 3 s at 37k, because the deck maps, card roles and opponent colours are
  built for every game ever recorded and then narrowed.
- **The card page and card search scale too**, and search runs per keystroke.
- **The opponents list grows with distinct opponents** (the first copies
  reused the same names, so it looked flat).

The second request of each page within 60 s is served from the response cache
in about 10 ms. The cost is paid on every first visit and after every change
to the cache fingerprint, which includes `MAX(game_events.id)`: that moves
with every logged line, so **during a game a visible Overview recomputes on
each 20-second poll**, in the tracker's own process. For a streamer with the
dashboard on a second monitor that is 3 to 10 s of one core every 20 s while
OBS encodes. The Overview is also the landing page, so at 37k games the
tracker opens on a ten-second spinner.

### Where the Overview's time goes (12,560 games, profiled before Step 0)

| Part | Share | What it is |
| --- | --- | --- |
| SQL | ~45% | 169 statements; the costly ones scan `game_card_summary`, `game_deck_cards`, `game_drawn_cards` and `game_opening_hand_cards` across all history: deck land profile (0.5 s), deck visuals window query (0.3 s), card roles (0.25 s), drawn-card table (0.15 s) |
| Per-game draw quality in Python | ~30% | `_draw_quality_batch` → `draw_quality_metrics` once per game, every request, over the opener and draws of every game |
| Format normalisation | ~12% | `normalize_match_format` ~37,000 calls per request on a handful of distinct raw labels (9 distinct format/best-of pairs in the real database) |
| Row conversion, colours, labels | ~13% | `_dict_rows`, `_display_opponent_colors`, `format_label` per row |

The deck page has the same shape: it builds deck-wide maps for *every* deck
(`_deck_color_map`, `_deck_visuals`) and the full card-role table, then picks
one deck out.

## Principle

Per-game facts that never change once the game is over are computed once,
stored, and read back. Aggregates (win rates by deck, format, mulligan count,
opener lands, momentum) stay as SQL over indexed columns: they are cheap when
the per-row inputs are columns rather than Python. A view asks only for the
games it shows. When a rule changes, a version constant is bumped and every
stored row is recomputed.

This is not a rewrite of the dashboard. The pages, their payloads and their
numbers do not change, and the payload diff proves it at every step.

## Step 0 — the hard failure and the tools (built)

The first measurement ran on a Mac, whose SQLite binds up to 500,000
parameters in one statement. **The SQLite in the Windows build binds 32,766**
(confirmed on the Windows 11 test machine with the build's Python 3.12).
`_draw_quality_batch`, `_mana_readiness_rows` and `_deck_decklist_analysis`
bound one parameter per game, so past 32,766 games in view the Overview and
All Games did not get slow on Windows, they failed with "too many SQL
variables". At 2,500 games a month that is thirteen months of play.

- Every id list bound into `IN (...)` goes through `dashboard._in_chunks`
  (900 ids a statement). Each game's rows arrive in one slice, so the results
  are identical; the payload diff on the 1x and 10x copies shows no change,
  and the 30x copy now loads under the pinned limit.
- `tests/test_scaling_tools.py` runs every page's endpoint over more games
  than a pinned limit allows, and fails if a query binds a parameter per game.
- The payload diff's first run found a bug unrelated to scale: a two-part
  card's cost (`card_mana` on the deck and game pages) came from walking a
  set, so a Room showed its first door's cost, its second door's, or both
  joined, depending on the launch. It now always shows the front face's.

## Step 1 — exact quick wins (no schema change)

1. Memoise `normalize_match_format` / `format_label` on their arguments
   (`functools.lru_cache`; `NormalizedFormat` is frozen, and the inputs are a
   few dozen distinct raw labels). Removes ~12% of every page.
2. Make the deck page compute its maps for the requested deck only
   (`_deck_color_map`, `_deck_visuals`, the card-role table all accept a deck
   filter). The deck page becomes proportional to the deck, not the history.
3. Make filtered views proportional to the filter: All Games' opponent-colour
   queries and the Overview's whole-history maps take the same game filter as
   the rest of the request. A 7-day Overview should cost what 7 days of games
   cost.
4. Stop a live game from invalidating pages that do not show it. Give the
   response cache a per-endpoint fingerprint: only `/api/game` and the replay
   availability check read `game_events`, so `MAX(game_events.id)` leaves the
   Overview's, All Games' and the deck page's keys. Check first whether an
   unfinished game's row can appear in those payloads; if it can, key them on
   the finished-game count instead.
5. Index review for the scanning queries above with `EXPLAIN QUERY PLAN` on the
   30x copy; add covering indexes where a scan over `game_card_summary` or
   `game_deck_cards` can become an index range (candidates:
   `game_deck_cards(participant_id, deck_zone, display_name)`,
   `game_card_summary(game_id, display_name)`). Include the card page and
   card search.
6. All Games: 22 MB at 37k games is about 600 bytes a game, and the page
   renders most of it, so trimming fields will not fix it. Page it on the
   server (30 rows a page today; sorting and search then move to the server
   too) or leave it and accept the size. Decide after items 1 to 5 are
   measured.

Each change is verified with the payload diff on the 1x and 10x copies:
`0 differ`, except fields a change removes on purpose.

## Step 2 — stored per-game derived values

New table `game_derived`, one row per game:

| Column | Source today |
| --- | --- |
| `game_id` (primary key), `rules_version` | |
| `draw_quality_json` | the whole dict `draw_quality_metrics` returns, as written |
| `is_flood`, `is_screw`, `is_land_streak`, `total_cards_seen`, `lands_seen`, `total_draws`, `land_draws`, `deck_size`, `deck_lands`, `land_rate_source` | the same dict's fields that SQL filters or sums (the land profile reads all of them) |
| `deck_colors` | `_participant_deck_color_map` over the submitted decklist and `cards.color_identity` |
| `opp_colors` | revealed cards / opponent commanders and `cards.color_identity` |

Storing the function's whole output, rather than a hand-picked list of
columns, is what makes the stored path exact: the Recent Games rows need the
three reason lists, and the land profile needs fields an earlier draft of
this table left out.

**Format labels are not stored.** A match's format can be rewritten after the
game (the startup match-metadata backfill, `db_audit --repair`), and Step 1's
memoisation already makes the label free.

Writers:
- The tracker, at game end, in the same persistence step as the game row,
  calling the exact functions the dashboard uses today.
- A background pass after launch (see the upgrade section) for games with no
  row or a row from an older `rules_version`. It finds them with an anti-join
  on `game_derived`, not a rowid watermark, so games added by a backup merge,
  an audit reconstruction or an import script are picked up without anyone
  remembering to reset anything.

Invalidation. The inputs of a stored row can change after the game ends. A
full recompute is cheap (below), so the rule is coarse on purpose: **a writer
that changes an input deletes the derived rows it may have touched, and the
pass refills them.** Readers fall back to computing live for a game with no
row, so nothing is ever stale, only briefly slower. The writers:

| Writer | What it changes | Rows to delete |
| --- | --- | --- |
| Card colour backfill (startup, game end) | `cards.color_identity` for cards unknown when played | games referencing those cards, or all rows when any card changed |
| "Card #N" label repair (startup) | `display_name` and `type_category` in the opener, draw and deck tables: a land can stop counting as "Other" | the games whose rows it rewrote |
| Imported-deck rename (startup) | `participants.deck_name`, which picks the borrowed decklist | the renamed deck's games |
| Date repair (migrations, merge, audit) | `games.started_at`, which orders the borrowed decklist | the repaired sessions' games |
| `events_backfill` (migration 19) | `game_participant_stats.cards_drawn` when it was NULL | covered: a migration that touches inputs bumps `rules_version` |
| Backup merge | adds games | none (new games have no row); `game_derived` joins `MERGE_SKIP_TABLES` so another machine's rows are never copied in |
| `db_audit --repair`, `scripts/delete_match.py`, `scripts/import_game_from_log.py` | reconstructs or removes games | the affected games; a deleted game's row goes with it |

**Borrowed decklists.** A game with no submitted list borrows the deck's
nearest list for its land rate. Counted on the real database: 589 of 1,264
games have no list of their own, all recorded before 2026-07-25 (decklist
capture began then); 213 borrow one and 376 use the size estimate. Every
later game submits its own. An old game's pick is "the earliest later list",
which new games never change, so there is no drift to handle beyond the
rename and date-repair rows above.

Readers to switch: `dashboard_snapshot` (recent games, the land profile,
momentum, deck table colours), `all_games`, `deck_detail` (Normal/Flood/Screw
split, land profile), `game_detail` (the badge; it can keep computing live).
Each reads `game_derived` and falls back to computing for a game that has no
current row.

Exactness: a test runs the old compute path and the stored path over every
game of a real database copy and asserts every value identical, and the
payload diff shows `0 differ` with the table empty, half filled and full. The
live write and the pass share one function so they cannot diverge.

Expected: the Overview and All Games lose their per-game Python and the
card-table scans behind it. From the profile's shares that is roughly 2 to
3 s cold at 37k games after Steps 1 and 2 together, not "well under a
second": the remaining aggregates still read the whole history. **Set the
target before building: Overview under 1 s cold at 12,640 games and under 3 s
at 37,920, on the dev Mac.** If the measured result misses it, the next lever
is the same idea one level up (per-deck stored aggregates), or serving the
last computed Overview at once and refreshing it behind the page.

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
  pre-update backup and restore slow. Measure once Step 2 is in, on a 30x
  copy built with `--events`.
- The dashboard process holds about 10 KB of RSS per game across its caches
  (364 MB at 37k). The response cache is bounded by entry count, not bytes;
  bound it by bytes.
- Two requests for the same uncached page both compute it. With ten-second
  pages that doubles the cost of a second tab; make the cache single-flight.

## Upgrading an existing database

What a user with history sees on the first launch after an update that
carries Step 2. The updater's side is unchanged: the signed download, the
mandatory `pre-update` `.tappsbackup`, the hand-off and the "Updated to X"
notice all run as they do today, and the backup is the recovery path.

- **The migration creates the empty table and nothing else.** A numbered
  migration runs inside `AnalyticsStore` construction, on the launcher's main
  thread, before the dashboard or the tracker exist. It must stay instant.
- **The backfill is one background thread, started after "Now ready to
  track".** Measured: draw quality for all 1,264 games takes 60 ms (47 µs a
  game) and the per-game deck colours 27 ms, so a 37,920-game history is
  about 2 to 5 s of work in total, and perhaps 15 s on a slow laptop. That is
  too long to sit inside the startup banner (a game started at once would be
  attached mid-game and never saved), and far too short to need a time budget
  or resuming across launches, which an earlier draft of this plan called for.
  The thread writes in batches of 500, newest games first, each batch one
  short transaction so it never holds the writer while a game is being
  recorded, and it stops when the tracker stops. A launch that ends early
  simply continues next time: the anti-join finds what is left.
- **Readers never wait for it.** Every reader falls back to today's compute
  path for a game with no current row. During the backfill the dashboard is
  exactly as fast as it is today, and gets faster as rows land.
- **One function writes every row**, live at game end or from the pass, so a
  game recorded while the pass runs is not a special case.

Other upgrade properties:

- **Rule changes later.** Bumping `rules_version` makes the pass recompute
  every row. Readers use a row only when its version matches the current
  constant and otherwise compute live, so a rule change never shows an old
  verdict.
- **Downgrade.** `game_derived` is additive. An older build ignores the table
  and computes live, as it does today; `db_newer_than_app` reports it. No
  data is lost in either direction.
- **Backups, merges, reset.** A `.tappsbackup` is a whole-database snapshot,
  so the table travels with it; on restore its rows are valid for that data.
  A merge skips it (`MERGE_SKIP_TABLES`) and the pass computes the merged
  games. A reset empties it (`RESET_TABLES`; the test that sorts every table
  into reset or kept will insist).
- **Disk.** One row per game, about 1 KB (the JSON averages 733 bytes on the
  real database); at 37k games about 40 MB. Small against the roughly 80 KB a
  game the history already costs.
- **Acceptance, measured before shipping** on the 30x copy: tracking ready
  within five seconds of launch, the pass finished within a minute, and the
  payload diff at `0 differ` before, during and after the pass.

## Order

Step 0 is done. Step 1 next, one item at a time with the payload diff after
each. Then Step 2 as designed above, then Step 3 with the archive decision.
Re-measure on the 10x and 30x copies after each step and update the table at
the top.
