# Scaling to tens of thousands of games

Status: Steps 0, 1 and 2 are built on the `scaling-large-histories` branch
(2026-11-09) and need a live check in the real app on macOS and Windows.
What is left is listed under "Still to do".
The question this answers: what happens to a player who logs 2,000–3,000
ranked games a month, a year from now?

How the built parts work is in AGENTS.md (`game_derived.py`, the
`dashboard.py` entry). This file keeps the measurements, the reasons, and the
remaining work.

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
  prints `0 differ`.**
- Both pin SQLite's bound-parameter limit to 32,766 on every connection, so a
  Mac run fails where a Windows user would.

Two kinds of copy were measured, because Travis's history is half games
recorded before decklists were captured (2026-07-25) and a future heavy
player's is not:

- **mixed**: the whole real database (1,264 games) times 10 and 30.
- **modern**: only its 675 games that submitted a decklist, times 19 and 56.
  This is the shape a long history recorded from now on will have.

## Measured

Cold times of the functions behind each endpoint on the dev Mac, 2026-11-09.
"Before" is 0.7.7 plus the Step 0 fix (0.7.7 itself fails past 32,766 games
on Windows); "after" is this branch with the stored values filled in.

| Page | modern, 12,825 games | modern, 37,800 games | mixed, 37,920 games |
| --- | --- | --- | --- |
| Overview (`/api/snapshot`) | 2.8 s → 1.1 s | 9.1 s → 3.6 s | 9.8 s → 5.6 s |
| Overview, last 7 days | 1.0 s → 0.13 s | 3.2 s → 0.38 s | 3.0 s → 0.38 s |
| Overview, one deck | 1.8 s → 0.25 s | 5.6 s → 0.8 s | 6.4 s → 1.9 s |
| All Games (`/api/games`) | 1.6 s → 0.31 s | 5.1 s → 1.0 s, 22 MB | 5.5 s → 3.0 s |
| All Games, last 30 days | 0.28 s → 0.02 s | 0.83 s → 0.03 s | 0.80 s → 0.03 s |
| Deck page, average of 17 decks | 1.5 s → 0.14 s | 4.8 s → 0.44 s | 4.6 s → 0.42 s |
| Deck page, the most-played deck | 1.8 s → 0.5 s | 5.9 s → 1.6 s | 6.6 s → 2.6 s |
| Opponent page | 0.19 s → 0.01 s | 0.55 s → 0.05 s | 0.52 s → 0.09 s |
| Card page (`/api/card`) | 0.8 s (unchanged) | 2.5 s (unchanged) | 2.3 s (unchanged) |
| Card search, per keystroke | 0.09 s (unchanged) | 0.28 s (unchanged) | 0.27 s (unchanged) |
| Opponents list | 0.04 s, 1.8 MB | 0.11 s, 5.4 MB | 0.11 s, 4.5 MB |
| Game page | 0.07 s | 0.2 s | 0.2 s |

The mixed copy gains less on the Overview and All Games because 47% of its
games have no decklist of their own, and those are computed live on purpose
(see "What is stored"). A real history has at most a few thousand such games.

Payloads: `0 differ` between the Step 0 code and this branch on the real
database, both mixed copies and both modern copies, with the stored table
absent, part filled and full. One difference from 0.7.7 is intended: a
two-part card's mana cost (Step 0).

Upgrade, simulated on the 37,800-game modern copy: the new build's first open
(schema and maintenance) took 0.2 s; the background pass stored all 37,800
games in 5 s alone and 15 s while another thread wrote to the database every
50 ms; one of those writes waited 149 ms at worst, 24 ms on average.

## What was built

### Step 0 — the hard failure and the tools

The first measurement ran on a Mac, whose SQLite binds up to 500,000
parameters in one statement. The SQLite in the Windows build binds 32,766
(confirmed on the Windows 11 test machine). `_draw_quality_batch`,
`_mana_readiness_rows` and `_deck_decklist_analysis` bound one parameter per
game, so past 32,766 games in view the Overview and All Games did not get
slow on Windows, they failed with "too many SQL variables": thirteen months
of play at 2,500 games a month. Every id list now goes through
`dashboard._in_chunks`, and a test reads every page over more games than a
pinned limit allows.

The payload diff's first run also found a bug unrelated to scale: a two-part
card's cost on the deck and game pages came from walking a set, so a Room
showed its first door's cost, its second door's, or both joined, depending on
the launch. It now always shows the front face's.

### Step 1 — a view costs what it shows

- History-filtered card queries start from `games` (`CROSS JOIN` order). The
  planner used to scan the whole card table and test each row's game; starting
  from the games in view is 35–40% faster over a whole history and about 50
  times faster for a week.
- The deck filter reads the deck's games from the `(role, deck_name)` index
  instead of testing every game ever recorded.
- Deck colours and deck images are built for the decks a page shows; observed
  cards are read only for decks with no decklist, and openers and draws only
  for decks that have never played a nonland card.
- The Overview picks its 100 recent games before joining their cards.
- The always-on test for untracked modes (Jump In, Midweek Magic) leaves every
  statement when the database holds no such match.
- `normalize_match_format` remembers its answers.
- The response cache keys on the event log only for the game page, so a game
  in progress no longer rebuilds a visible Overview on every 20-second poll;
  the safety-net TTL grows with a page's build time.

### Step 2 — each finished game's derived values, stored once

`game_derived`, one row per game: the draw-quality dict as
`draw_quality_metrics` returned it, the submitted deck's colours, and the
opponent's colour letters. Written by the tracker at game end and by a
background pass after launch; read by `_draw_quality_batch`,
`_participant_deck_color_map` and `_opponent_letters`, each of which computes
live for any game without a current row.

**What is stored** is only what belongs to the game alone. A game with no
decklist of its own borrows the nearest decklist of the same deck for its
land rate, and that answer moves when other games are added, renamed or
re-dated: its draw quality is stored as NULL and always computed live. On the
real database that is 589 of 1,264 games, all from before 2026-07-25.

**Format labels are not stored.** A match's format can be rewritten after the
game, and the memo makes the label free.

**What drops a row**: a card's colour or cost learned later (the games that
used the card), a repaired "Card #N" label (every row), an audit repair
(every row), a reset. A backup merge never copies the table. Bumping
`game_derived.RULES_VERSION` recomputes everything; a test fails when
`draw_quality_metrics` answers differently without the bump.

**Upgrade**: the table is created empty with the schema, which is instant.
The pass runs on a daemon thread after "Now ready to track", in batches of
500, newest games first, sharing a lock with the game-end save so it never
stores an answer computed from a half-written game. It can stop at any point
and continue at the next launch. An older build ignores the table.

## Still to do

In the order they are worth doing.

1. **Live check.** Run this branch against a copy of a real database on the
   Mac Studio and on Windows: first launch after the "update" (the pass runs,
   tracking starts at once), a few real games (a row per game appears in
   `game_derived`), and the same pages before and after. Then the payload diff
   once more on that copy.
2. **Card page and card search.** Untouched: 2.5 s and 0.28 s per keystroke
   at 37,800 games. The name match is `display_name = ? OR display_name LIKE
   'Name (%'`, which no index serves today. Candidate: an index on
   `display_name COLLATE NOCASE` for the three card tables and the clause
   rewritten so both halves use it, with the same results. The indexes cost
   about a second to build once on a 38k-game database, on the launcher's
   main thread: build them from the background pass instead. Search matches
   anywhere in a name and needs a different approach (search the `cards`
   table, then read stats for the matches).
3. **The Overview's last second.** At 12,825 games it takes 1.1 s; the target
   is under 1 s, and under 3 s at 37,800 (now 3.6 s). What is left, largest
   first: land availability on curve (`_mana_readiness_rows`, about 13%; its
   inputs could join `game_derived`), the land profile's JSON decoding (hot
   fields as columns), opponent threats and the drawn-card table (aggregates
   over card rows in view), and about 35 small aggregates that each read the
   games in view once.
4. **All Games is 22 MB at 37,800 games**, about 600 bytes a game, nearly all
   of it rendered. It now builds in a second, so the size is the cost: page it
   on the server (sorting and search then move there too) or accept it.
5. **If the Overview must open instantly at any size**: serve the last built
   body at once and rebuild behind the page. That changes what a user sees
   (numbers up to one refresh old after a game), so it is a product decision,
   not an optimisation.
6. **Housekeeping.** Bound the response cache by bytes, not entries (the
   process held about 10 KB of RSS per game). Make it single-flight, so two
   requests for the same uncached page do not both build it. Measure backup,
   restore and merge on a 30x copy built with `--events`.
7. `game_events` (`visible = 1`) is the one table that still grows with the
   history, roughly 1.7 GB at 37k games; the [raw log archive](RAW_LOG_ARCHIVE.md)
   plan decides whether the originals replace any of it.
