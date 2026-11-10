# Scaling to tens of thousands of games

Status: Steps 0 to 4 are built on the `scaling-large-histories` branch
(2026-11-09). Steps 0 to 3 passed a live check on the dev Mac; Step 4 (the
Overview's last second) and Windows have not been run in the real app yet.
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
  and a branch are compared on the same file. Cards are the most-played ones
  plus a spread of rarer ones and the two-part cards; the card page is also
  read under each filter, and search as it is typed (one, two, three letters,
  a card type, a half of a two-part card).
- `scripts/dashboard_payloads.py diff A B` lists every value that differs
  between two dumps. **"The pages and their numbers do not change" means this
  prints `0 differ`.** "Last 7 days" in a dump counts back from the newest
  game in the copy, not from the clock: two dumps made half an hour apart
  once differed by the one game that had left the window in between.
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
| Card page (`/api/card`), median of 26 cards | not measured | 2.0 s → 0.3 s | 1.7 s → 0.26 s |
| Card page, a basic land (half of all games) | not measured | 2.4 s → 0.9 s | 2.1 s → 0.8 s |
| Card search, the first after a new game | not measured | 0.2–2.6 s → 0.9 s | 0.2–1.6 s → 0.9 s |
| Card search, each keystroke after that | not measured | 0.2–2.6 s → 0.01 s | 0.2–1.6 s → 0.01 s |
| Opponents list | 0.04 s, 1.8 MB | 0.11 s, 5.4 MB | 0.11 s, 4.5 MB |
| Game page | 0.07 s | 0.2 s | 0.2 s |

The mixed copy gains less on the Overview and All Games because 47% of its
games have no decklist of their own, and those are computed live on purpose
(see "What is stored"). A real history has at most a few thousand such games.

The card and search rows were measured on new copies of the same two shapes
(38,136 and 38,100 games); "before" for them is Step 2. A search used to cost
0.2 s for a selective query and up to 2.6 s for a single letter, every
keystroke.

Payloads: `0 differ` between the Step 0 code and this branch on the real
database, both mixed copies and both modern copies, with the stored table
absent, part filled and full. One difference from 0.7.7 is intended: a
two-part card's mana cost (Step 0). Step 3: `0 differ` against Step 2 on the
real database and both 38k copies (136 payloads each), with the card-name
indexes absent and present.

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

### Step 3 — the card page and card search

**Card page.** Every statement scanned a whole card table for the name, and
two parts read the whole history whatever the card:

- The name match (`display_name = ? OR display_name LIKE 'Name (%'`) is now
  written so both halves use an index on `display_name COLLATE NOCASE`, with
  the same rows: LIKE was always case-insensitive, and the exact half asks the
  index for any case and keeps the exact spelling. Four indexes (card summary,
  opening hands, draws, decklists): 45–55 MB on a 1.1–1.3 GB file at 38,000
  games, about 4%. Until they exist the same rows come from a scan and the
  page takes about 1 s.
- The background pass builds them after it has stored the derived values:
  1.2 s in total at 38,100 games, during which a concurrent write waited
  385 ms at worst. They are not in the schema baseline because that runs
  before tracking starts.
- Repeat draws read each game's hand, draw and deck totals only for the games
  the card was in (it used to total every game ever recorded).
- "How often could they have cast it" reads the opponent colours stored in
  Step 2. It still reads every game in view, about 0.1 s at 38,000 games,
  which is most of what a rarely played card's page now costs.

A card in half of all games (a basic land) still costs 0.9 s: about 20,000
games' rows are read by six statements, and the repeat-draw table does its
arithmetic per game.

**Search** matches anywhere in the name and ranks by games, so no index
narrows it. The card table is instead summed once per display name (one
statement, 0.7 s at 38,000 games) and kept in memory under the response
cache's fingerprint and TTL; a keystroke compares the query with a few
thousand names. The first search after a new game pays the 0.9 s; requests
that arrive while it is being built wait for it instead of building their own.
A card recorded under several names ("Opt", "Opt (Instant)") is merged per
query, counting a game once; deck counts and last-seen dates are worked out
only for the results returned. Which row names a result and gives its type
used to depend on the query plan; it is now the card's earliest row.

Tried and dropped: finding search matches through the name index. Reading a
card's rows through an index costs about seven times a sequential read per
row, so it only won for queries matching under 4% of rows.

### Step 4 — the Overview's last second

The targets were an Overview under 1 s at about 13,000 games and under 3 s at
about 38,000. Measured on new copies (13,186, 38,864 and 38,490 games), best
of three, Step 3's code against this step's on the same stored rows:

| Page | modern, 13,186 games | modern, 38,864 games | mixed, 38,490 games |
| --- | --- | --- | --- |
| Overview | 0.96 s → 0.69 s | 3.4 s → 2.4 s | 5.4 s → 4.6 s |
| Overview, last 7 days | 0.12 s → 0.07 s | 0.45 s → 0.23 s | 0.39 s → 0.21 s |
| Overview, one deck | 0.21 s → 0.17 s | 0.75 s → 0.66 s | 1.9 s → 1.7 s |
| All Games | 0.28 s → 0.20 s | 0.94 s → 0.70 s | 3.0 s → 2.5 s |
| Deck page, the most-played deck | 0.41 s → 0.33 s | 1.5 s → 1.0 s | 2.7 s → 2.2 s |

The payload diff printed `136 identical, 0 differ` against Step 3 on all
three copies and on the real database with the table full, emptied, half
filled, and still in its Step 2 shape (no summary columns). The mixed copy
still spends most of its time computing live the 46% of its games that have
no decklist of their own.

What changed:

- **A few numbers per game, stored beside the dict.** Land availability on
  curve and win rate by opening lands counted every game's opening hand with
  two subqueries each and read every land draw; the flood / screw split and
  All Games decoded every game's whole draw-quality dict to read five
  numbers. `game_derived` now also holds the opening hand's cards and lands,
  the turn of each land drawn, and the dict's counts and verdicts
  (`SUMMARY_COLUMNS`). `store` fills them from the same computation; a game
  without a current row is counted the old way inside the same statement
  (`COALESCE(stored column, live subquery)`), so the numbers cannot differ.
  `RULES_VERSION` is 2: the pass re-stores every row after the update, 9 s in
  the background at 38,000 games, and pages compute live until it is done.
- **Games first, everywhere.** Step 1 fixed the join order for the card
  tables. Nine more Overview statements still started from every player row
  and looked its game up, so "last 7 days" joined the whole history for each.
- **Recent games pick their 30 first.** Both recent-games tables sorted every
  game in view with all its per-game subqueries (opponent colours, commanders,
  turn times) and then kept 30: 60 ms at 38,000 games, now under 1 ms.
- Smaller: opponent colours are labelled once per distinct combination, not
  once per game; card counts use the game's integer rowid; deck images leave
  lands out of the first pass; cleaned card names are remembered (a deck page
  cleaned the same few hundred names half a million times).

The Overview at 38,000 games is now about forty statements, none over 0.35 s:
deck images (0.3 s), opponent threats (0.25 s), the drawn-card table (0.2 s),
each deck's newest decklist (0.13 s), and about seventeen aggregates of 40 to
65 ms that each read every game in view once.

**The page cache** builds a page once however many requests ask for it at
the same moment (two tabs, a poll during a navigation), and holds at most
64 MB of bodies, oldest dropped first (All Games is 22 MB at 38,000 games;
the old limit was 64 bodies of any size).

## Still to do

In the order they are worth doing.

1. **Live check on Windows.** Run this branch against a copy of a real
   database: first launch after the "update" (the pass runs, tracking starts
   at once), a few real games (a row per game appears in `game_derived`), the
   four card-name indexes appear, and the same pages before and after. Then
   the payload diff once more on that copy. Done on the dev Mac on 2026-11-09
   for Steps 0 to 3. At 1,264 games, then six played: the pass stored every
   game within a second of launch, each new game got its row at game end, no
   earlier row of the game tables changed, and the payload diff printed
   `0 differ` with the table full against emptied. After the next restart
   (1,277 games): the four indexes were there and the running dashboard
   answered card pages and searches in milliseconds.
2. **Live check of Step 4** on the Mac: after the restart every
   `game_derived` row is at `rules_version` 2 with its summary columns
   filled, and the pages show the same numbers.
3. **The Overview below 2 s at 38,000 games**, if it matters. No single
   statement is left to fix; the cost is forty statements that each read the
   games in view. Two ways on: build one pre-joined temporary table of the
   games in view per request and point the small aggregates at it (about
   0.5 s, and every statement changes), or run the statements on several
   read connections at once (SQLite releases the GIL; the same work on more
   cores, which a streamer's machine may not have spare).
4. **All Games is 22 MB at 37,800 games**, about 600 bytes a game, nearly all
   of it rendered. It now builds in a second, so the size is the cost: page it
   on the server (sorting and search then move there too) or accept it.
5. **If the Overview must open instantly at any size**: serve the last built
   body at once and rebuild behind the page. That changes what a user sees
   (numbers up to one refresh old after a game), so it is a product decision,
   not an optimisation.
6. **Search on first use.** If 0.9 s on the first search after a game is too
   long at this size, build the summary on a background thread when the
   Overview is loaded, so it is ready before anyone types.
7. **Housekeeping.** Measure backup, restore and merge on a 30x copy built
   with `--events`.
8. `game_events` (`visible = 1`) is the one table that still grows with the
   history, roughly 1.7 GB at 37k games; the [raw log archive](RAW_LOG_ARCHIVE.md)
   plan decides whether the originals replace any of it.
