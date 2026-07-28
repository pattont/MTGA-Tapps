# Fable Improvements — Review Findings & Ideas

A review of the tracker, the SQLite schema, the dashboard API, and the React UI, with
improvement ideas organized by theme. Written 2026-07-28 from a read-only pass over the
codebase (no changes made). Overlap with existing backlog docs
(`TRACKER_ENHANCEMENT_BACKLOG.md`, `thoughts.md`, `MISSING_FEATURES.md`) is noted where
relevant rather than repeated.

The single biggest finding: **the tracker captures far more data than the dashboard
surfaces.** Several whole tables are write-only. Most of the highest-value analytics below
require *zero* new log parsing — just new queries and UI.

---

## 1. Light mode (your known issue) — root causes and a fix plan

Light mode isn't bad because of any one color — it has five structural problems in
`ui/src/styles.css`. Fixing these is mostly token work, not a redesign.

### Root causes

1. **`--panel` and `--surface` are both `#ffffff` in light mode.** In dark they differ
   (`#171d23` vs `#141a20`), so inputs, selects, the theme toggle, and chart plates read
   as recessed. In light, everything is white-on-white with only a faint `#d7dee7` border
   separating it. This is the direct cause of the "fully white" feel.
2. **Elevation semantics invert.** Dark: `--panel-strong` (`#1f2730`) is *lighter* than
   `--panel` → chips/table headers read as raised. Light: `--panel-strong` (`#eef2f6`) is
   *darker* than white → the same elements read as sunken. Affects badges, timeline chips,
   table headers, zebra rows, pagination buttons, deck visuals, etc.
3. **`--accent-strong` inverts.** Dark: it's the *brighter* gold (`#f0c66c`). Light: it's
   a *darker* brown (`#74500e`). Every "highlight" usage (active nav, links, sort icons,
   trend line, rank chart, timeline turn headers, focus outlines) turns muddy.
4. **`color-mix()` percentages are tuned for a dark base.** Zebra striping
   (`34%` of `--panel-strong` over white ≈ `#f8fafc`), metric-card danger/info/warning
   tints at `7%`, hover states, and the trend area fill all wash out to near-invisible on
   white.
5. **Hardcoded colors with no light override.** The worst: `.timeline-chip-draw/-cast/
   -land/-attack/-ability` (lines ~1742–1749) use the pastel palette (`#7db4d8`,
   `#b795d9`, `#8fb573`, `#d98a6a`, `#d9c06a`) with **no light-mode override** — someone
   added light overrides for `.type-chip-*` (lines 1582–1588) and forgot the timeline
   chips. At 0.68rem/700-weight on `#eef2f6` they're roughly 2:1 contrast — illegible.
   Also unoverridden: `.card-preview` box-shadow (heavy black `rgb(0 0 0 / 42%)` glow on
   white), `.mana-pip` dark drop-shadow.

### Recommended approach: a "soft" light theme, not white

Since you don't want stark white, build light mode on warm off-whites so the three-surface
hierarchy survives. A candidate token set (parchment-adjacent, fits the MTG gold accent):

| Token | Current light | Suggested | Rationale |
|---|---|---|---|
| `--bg` | `#f5f7fa` | `#e9e5dd` (warm) or `#e7eaef` (cool) | page canvas noticeably darker than panels |
| `--panel` | `#ffffff` | `#f6f3ec` / `#f4f6f9` | cards sit *above* bg, below pure white |
| `--surface` | `#ffffff` | `#ebe7de` / `#e9edf2` | **must differ from `--panel`** — inputs/chart plates recess again |
| `--panel-strong` | `#eef2f6` | `#fbf9f4` / `#fbfcfe` | *lighter* than `--panel` so elevation reads "raised" in both themes |
| `--border` | `#d7dee7` | `#c9c2b4` / `#c3ccd8` | stronger edges since shadows are weak in light |
| `--shadow` | 10% alpha | ~18–22% alpha, smaller blur | cards need edge definition |

Then:

- Keep `--accent` gold but pick a light-mode gold that is both accessible *and* clearly
  the accent (e.g. `#8a5c14`–`#9d6b13` range), and make `--accent-strong` a *deeper,
  more saturated* version used consistently as "emphasis" — audit each `--accent-strong`
  usage and decide whether it wanted "brighter" (swap to a new `--accent-bright` token)
  or "stronger" semantically. The real fix is splitting the token by intent.
- Re-tune every `color-mix()` percentage per theme, or introduce
  `--tint-weak/--tint-medium` tokens that hold theme-appropriate percentages.
- Add `:root[data-theme="light"]` overrides for `.timeline-chip-*` (mirror the existing
  `.type-chip-*` overrides), `.card-preview` shadow, and `.mana-pip` shadow.
- Fix `--subtle` (`#778392` on white ≈ 3.9:1) — used at 0.7–0.82rem for refresh status,
  chart axes, rank scale; needs ≥4.5:1 at those sizes.

### Theme mechanism fixes (cheap, do alongside)

- **Respect `prefers-color-scheme`** in `getInitialTheme()` when localStorage is empty.
- **Kill the light-mode FOUC**: `data-theme` is only set in a React `useEffect`, so light
  users get a dark flash every load. Add a tiny inline script in `ui/index.html` that
  reads localStorage and sets the attribute before first paint.
- Add an "Auto (system)" third option to the toggle; give the toggle `aria-pressed`
  or `role="switch"`.
- A dedicated **light-mode visual QA checklist page-by-page** (Phase 5 of
  `SITE_COMPLETION_PLAN.md` called this out; the timeline chips prove it never happened).

---

## 2. Analytics you already have the data for (no new parsing)

### 2a. Combat & aggression profiles — the biggest untapped table

`game_participant_stats` stores 16 per-game metrics for both seats (`attack_steps`,
`attacking_creatures`, `attackers_lost`, `blocking_creatures`, `blockers_lost`,
`damage_dealt`, `damage_taken`, `life_lost`, `self_damage`, `life_gained`, `cards_played`,
`cards_drawn`, `cards_discarded`, `cards_milled`, `cards_exiled`). The dashboard reads
exactly **one** of them. Ideas, all straightforward aggregations:

- **Deck aggression profile**: avg damage dealt/turn, attack steps per game, attackers
  per attack — badge decks as Aggro/Midrange/Control from their own telemetry rather
  than guessing. Compare *your* profile in wins vs losses ("you win when you attack by
  turn 3" style insights).
- **Combat trade efficiency**: `attackers_lost` vs `blockers_lost` per deck and per
  matchup — are your attacks profitable?
- **Race analytics**: your damage-dealt vs damage-taken curves; "in losses, opponent
  out-damaged you by turn X".
- **Lifegain report**: `life_gained` vs win rate per deck (does the lifegain package
  actually convert to wins?).
- **Discard/mill exposure**: win rate in games where you were milled/discarded N+ cards.
- Caveat to fix first: `damage_taken` is currently written from the same value as
  `life_lost` (tracker_analytics.py ~452–461), so it isn't really "opponent-inflicted
  damage" yet.

### 2b. Decklist-aware everything

`game_deck_cards` stores the authoritative submitted 60 + sideboard per game, and it's
only used for deck export and membership checks. This unlocks:

- **Real hypergeometric inputs**: the flood/screw engine hardcodes
  `expected_land_rate = 0.4/0.425` (and the CLI uses 0.37 — the two implementations
  disagree). Count actual lands in the submitted list instead. This was backlog item #3;
  it materially improves the credibility of the flood/screw verdicts.
- **Mana curve per deck** (CMC needs card data — see §4 arena_id fix) and land count
  shown on the deck page.
- **"Dead weight" report**: cards in the deck that were rarely/never drawn across N
  games, and their win rate when they *were* drawn — cut candidates.
- **Draw rate vs copies**: observed draw frequency per card vs expected from quantity.
- **Deck version tracking**: you already snapshot the decklist *every game*. Diff
  consecutive snapshots to detect deck edits, then split the deck's stats **by version**
  ("since you swapped in 2x Sheltered by Ghosts: 12–5"). This is a killer feature no
  major tracker does well, and the data is already sitting there.
- **Bo3 sideboard analytics**: diff game-1 vs game-2/3 submitted lists within a match to
  show what you boarded, and game-1 vs post-board win rates per deck.

### 2c. Duplicate-draw stats (your `thoughts.md` card-detail idea)

`game_drawn_cards.copy_number` and `game_opening_hand_cards.copy_number` are already
captured and never used. The card page can show exactly what you described: "% of games
seen 2+, 3+, 4 times", plus win rate conditioned on multiplicity ("seeing the 2nd
Sheltered by Ghosts correlates with…"). Combine with 2b's copies-in-deck to show
expected-vs-actual multiplicity (hypergeometric — the math already exists in
`draw_quality.py`, including the target-card feature that is currently CLI-only and
unreachable from the UI).

### 2d. Curve & tempo (turn-indexed draws)

`game_drawn_cards.turn_number` is captured but every draw metric indexes by
`draw_position`. Turn indexing unlocks:

- **Land drops on curve**: what % of games did you hit land drops through turn 3/4/5?
  Win rate when you missed turn-3 land drop vs not. This is more actionable than
  flood/screw probability alone.
- **Curve-out rate**: turns where you cast something at your mana (needs cast events by
  turn, which the timeline already has).
- Per-turn draw heatmap on the game page (what arrived when).

### 2e. Session, streak & schedule analytics

- **Win rate by time of day / day of week** — `games.started_at` is all you need.
  Are the 1 a.m. queues actually worse for you?
- **Fatigue curve**: win rate by Nth game of a session (`tracker_sessions` join). "You
  drop under 45% after game 7" is a real, actionable insight.
- **Session-bounded momentum**: the current momentum LAG chains across days; add a
  same-session variant. Also surface streak distributions (longest W/L streaks, streak
  length histogram vs coin-flip expectation) — this rounds out backlog item #4
  (matchmaking/momentum audit) with data you already store.
- `session_participant_stats` is maintained after every game and read by nothing —
  either power the sessions panel from it or drop the table.

### 2f. Opponent & meta intelligence

- **"Cards that beat me" leaderboard**: `card_detail.opponent_impact` exists per card,
  but there's no cross-card ranked view. One query over opponent-side
  `game_card_summary`: cards with highest loss rate against you, filtered by format/days.
- **Opponent archetype inference**: `deck_llm.py` is fully implemented (3 providers) and
  **orphaned** — nothing imports it, and `participants.deck_archetype` is hardcoded
  `None`. Wiring it up (per `LLM_DECK_ID_PLAN.md`, ideally rule-based-first with LLM
  fallback) unlocks the matchup matrix below.
- **Matchup matrix**: your deck × opponent archetype win rates — the #1 feature of
  commercial trackers, and the schema already has the destination column.
- **Meta snapshot**: most-seen opponent cards/colors by format over the last N days —
  what is the ladder actually playing this week?
- Opponent color identity is derivable *today* (no LLM) from opponent cards played —
  even just "win rate vs mono-red / vs UW" would be immediately useful.

### 2g. Rank & competitive context

- **Season selector**: `rank_snapshots` stores every season but the API hard-filters to
  `MAX(season_ordinal)`; historical seasons are unreachable. Add a season filter.
- **Limited rank**: `rank_format` is hardcoded `'constructed'` at capture time — record
  limited rank too.
- **Rank-aware game list**: your `thoughts.md` ranked/unranked toggle idea — plus show
  net rank-step delta per session ("tonight: +4 steps") and rank tier icons.
- **Win rate by rank tier**: performance vs Bronze/Silver/…/Mythic opponents isn't
  captured per-game today, but your *own* tier at game time is derivable from snapshot
  timestamps — "your win rate in Plat is 48% vs 61% in Gold" tells you where you plateau.
- Fix: `rank_progress_rows` ignores the deck/format/days filters entirely.

### 2h. Turn timing & pace

`game_turns` has per-turn durations with a `timing_source` confidence tag that is never
used to qualify averages (estimated turns average in with live ones silently).

- **Think-time vs outcome**: avg turn duration in wins vs losses; per-deck pace.
- **Slow-turn detection** on the game timeline (highlight turns > Nx your median).
- **Game length distribution** per deck/format (histogram, not just average) — good for
  "how long will a ladder session take".
- Qualify or exclude `estimated_header_events` turns in averages; show a confidence dot.

### 2i. Outcome forensics

- **Win rate by `outcome_reason`** (concede vs damage vs decking etc.) — how many losses
  are early concessions vs fought-out games? Do you concede too early with some decks?
- **Comeback tracker**: from `game_events` life data — win rate after dropping below
  5/10 life; biggest comebacks list; "was this game actually winnable" context.
- **Mulligan decision quality**: `participants.opening_hand_size` + opener composition
  (lands in kept hand from `game_opening_hand_cards` + type data) vs outcome — "keeping
  2-landers: 38% WR; mulling to 6: 44%" — genuinely useful ladder advice.

### 2j. Best Deck metric (your `thoughts.md` gripe)

Agreed the Wilson-score "Best Deck" showing a 4-0 deck is weak. Options: enforce a
minimum-games floor (e.g. 10) before eligibility; display the confidence interval on the
deck page ("54% ± 9%") so small samples look as shaky as they are; or replace the single
card with "Best decks (min 10 games)" top-3.

---

## 3. UI / UX improvements

### Filters & navigation

- **Custom date range picker** — `DAY_CHOICES = [7, 30, 90]` is limiting; add
  since/until dates and a season option (pairs with 2g).
- **Filters on detail pages**: `/api/card` and `/api/opponent` accept no
  deck/format/days params at all, so those pages always span all history even when the
  dashboard is filtered. Thread `_games_filter()` through both, and render the FilterBar
  on the deck page (it receives filters but can't change them).
- **URL-synced filters**: dashboard filter changes call `setFilters` without updating
  the hash — filtered views aren't bookmarkable/shareable, and Back doesn't undo a
  filter. The helpers (`dashboardRouteHash`) already exist for outbound links; use them
  on change too. Same for sidebar section clicks (they `preventDefault()` and never
  update the hash).
- **Global search**: card search exists in the topbar; extend it to decks and opponents
  (one combined typeahead).
- A play/draw filter (backlog item #5 asked for this) — the data is on `participants`.

### Tables

- **Pagination everywhere**: exactly one table paginates (Decks). Recent Games (11
  columns), Drawn Cards, Matches, Sessions, and every detail-page table render unbounded
  — on a mature DB that's thousands of rows. `SortableTable` already supports
  `pageSize`; apply it, and consider server-side `limit`/`offset` for the big ones.
- Text filter boxes on Recent Games / Matches / Sessions (exists only on Decks and
  Drawn Cards today).
- Sort persistence per table (survives the 20s refresh remounts and route changes).
- Sticky first column in horizontally-scrolling tables on mobile.
- `formatPercent` doesn't round — raw floats can render as `53.84615384615385%`.

### Charts

All three charts are hand-rolled SVG with `preserveAspectRatio="none"`, which stretches
strokes and turns the rank chart's circles into ellipses (only some elements have
`vector-effect: non-scaling-stroke`; the life-chart lines don't).

- **Tooltips/hover**: only the rank chart has any (native `<title>`). Add a hover
  crosshair + tooltip to trend and life charts (nearest-point lookup is easy in the
  existing SVG approach; no library needed).
- **Axis labels/ticks**: trend chart has only first-date/50%/last-date text; life chart
  has no turn axis.
- **Legend swatches**: the life chart legend is bare text — line identity is conveyed by
  color alone (`--success` vs `--danger`), a colorblind failure. Add swatches and
  differing dash patterns.
- **Accessibility**: TrendChart and LifeChart set `role="img"` *and*
  `aria-hidden="true"` — screen readers get nothing. Expose labels and add a table
  fallback (a `<details>` with the data table is enough).
- Chart ideas that pay off with the new analytics: win-rate-by-turn-count histogram,
  land-drop curve, damage race chart on the game page (cumulative damage both seats),
  matchup matrix heatmap, calendar heatmap of games/win rate (GitHub-graph style).

### States, polling, resilience

- **Loading skeletons** instead of full-page "Loading…" text (current approach causes
  total layout shift on every navigation), with `role="status"`/`aria-busy`.
- **Stale-data indicator**: on detail pages, background refresh failures are silently
  swallowed once loaded — a page can be hours stale while looking healthy. Show a "last
  updated Xs ago / retry" chip like the dashboard's refresh status line.
- **Retry buttons** on error states (currently only a back-link, or nothing).
- **Smarter polling**: pause when `document.hidden`, back off on failures; consider
  ETag/304 or a `since=` delta — `/api/snapshot` re-ships 15 full collections every 20s.
- `OpponentDetailPage` never polls (one-shot fetch) — inconsistent with every other page.

### Accessibility & mobile

- **Focus outlines are removed** (`outline: none` on `:focus-visible`) across ~11
  selectors in favor of color changes alone — WCAG 2.4.7 problem, worse in light mode.
  Restore visible focus rings.
- `aria-current="page"` on active nav; skip-to-content link (9 sidebar links precede
  `<main>`); `tabindex="0"` + `role="region"` on `.table-wrap` scrollers; move
  `title`-attribute-only info (rank points, timing source, export availability) into
  visible/togglable UI for touch users.
- Mobile: sidebar collapses to a horizontal strip showing ~5 of 9+ items with no
  overflow affordance — add a fade/chevron or a drawer. Column-priority hiding for the
  11-column Recent Games table. Metric grid jumps 5→2→1 columns, never 3–4.
- Consolidate the four duplicated `Section` components into one shared collapsible
  component (only the game page can collapse sections today; long dashboard tables
  should collapse too).

### Quality-of-life features

- **Game notes & tags**: mark games "misplay", "mana screw", "great game" and filter on
  tags. Requires the first write endpoint (server is currently GET-only and opens the DB
  read-only) — small, contained addition, big analytical payoff (tag-conditioned win
  rates).
- **CSV/JSON export** for any table + a full-DB export (the Phase-3 roadmap in
  `FUTURE_DEVELOPMENT.md` promised this and it never landed).
- **DB health page**: `db_audit.py` computes rich findings (format mismatches, missing
  timings, empty games) that are CLI-only — surface them at `/api/audit` with repair
  suggestions.
- Keyboard shortcuts (`/` to focus search, `g d` go to decks…).
- Live-game view: the tracker renders a live console; a dashboard "current game" page
  (life totals, drawn-so-far, live draw odds from the decklist) would reuse §2b math.
  This is the natural first step toward the long-planned overlay mode.

---

## 4. Data & engineering hygiene (enables the above)

1. **Populate `cards.arena_id`.** It's NULL for ~99% of rows, so *every* card image is a
   fuzzy Scryfall name lookup — but `game_deck_cards.arena_id` holds the real Arena IDs
   and is never joined back. One backfill + upsert change makes image lookups exact and
   enables a proper card-data join (mana value, colors, rarity → unlocks curve, color,
   and rarity analytics everywhere). Consider caching Scryfall bulk data locally
   (`type_line`, `primary_type`, `power`, `toughness` columns already exist and are
   written but never read).
2. **Unify the two draw-quality implementations.** `draw_quality.py` (CLI, 0.37 land
   rate, relative DB path that breaks outside repo root) vs `dashboard.py` (0.4/0.425)
   give different flood/screw verdicts on the same game. One module, decklist-aware
   (§2b), used by both — and move the client-side fallback math in `GameDetailPage`
   server-side.
3. **Make `game_events` structured.** `event_subtype`, `source_card_id`,
   `target_card_id`, `amount`, `zone_from`, `zone_to`, `payload_json` are in the schema
   but omitted from the INSERT; `event_type` stores a console *style* string. Populating
   these turns the timeline from styled text into queryable data (removal counts,
   targeting patterns, per-event-type analytics — the `MISSING_FEATURES.md` items all
   land here).
4. **Persist parsed-but-dropped annotations.** `annotations.py` extracts scry/surveil
   top/bottom decisions, counters, mana color payments — then drops them. Scry decisions
   alone would enrich draw-quality analysis ("you scried 2 lands to the bottom then
   flooded anyway").
5. **Populate or drop dead columns.** `game_card_summary.drawn/discarded/milled/
   exiled_count` are queried by the opponent-cards block but never written (the
   predicates are permanently false — acknowledged in a comment at dashboard.py:1205).
   Either write them from the zone-transfer tracker or remove them and the dead query
   arms. Same audit for `matches.raw_match_id`, `tracker_sessions.app_version` (always
   NULL), `participants.deck_archetype` (see §2f).
6. **Real migrations.** `schema_migrations` is pinned at version 1 forever; evolution
   happens via ad-hoc `ensure_table_column()`. A tiny numbered-migration runner will
   matter the moment any of the above lands.
7. **Settings**: port 8765, DB path, and land-rate constants are hardcoded;
   `settings.py` only stores window size. Fold them in.
8. **`/api/snapshot` payload diet**: split rarely-changing collections (sessions,
   matches, filter options) from the hot path, or add per-section endpoints — pairs with
   the polling work.

---

## 5. Bigger swings (roadmap-level)

- **Limited/draft support** (17Lands-style): draft pick logging, per-set card win rates
  from your own games, deck-build assist from your pick history. The log has the events;
  this is the largest untracked game mode.
- **Overlay mode** (long-standing roadmap item): now that the dashboard exists, a
  minimal always-on-top webview showing live draw odds + opponent-seen cards is the
  highest-value slice.
- **Backfill tool** (backlog item #2): replay `raw_game_payloads`/`console_logs`/old
  `Player.log` files through the current parser to enrich historical rows —
  `raw_game_payloads` is currently write-only, so all that stored history does nothing.
- **Draw-bias evidence pack** (backlog item #1): §2b + §2d + §2e together essentially
  build it — expected-vs-actual per game with decklist-exact probabilities, streaks,
  momentum splits, all filterable. Worth framing as one report page ("Fairness") rather
  than scattered stats.
- **Cross-tracker comparison**: optional import of 17Lands/Untapped public meta data to
  contextualize your card win rates vs the field ("your WR with this card is 8 points
  under the format average").

---

## 6. Suggested priority order

1. **Light theme overhaul** (§1) — known pain, self-contained, mostly token work.
2. **Arena-ID backfill + card-data join** (§4.1) — small, unlocks curve/color analytics
   and exact images everywhere.
3. **Surface `game_participant_stats`** (§2a) — biggest analytics payoff per line of
   code; the data is complete and untouched.
4. **Decklist-aware draw quality + dedupe the two implementations** (§2b, §4.2) — fixes
   correctness of an existing headline feature.
5. **Duplicate-draw and turn-indexed draw stats** (§2c, §2d) — directly answers your
   `thoughts.md` card-detail question.
6. **Filter/URL/pagination pass** (§3) — broad usability lift, no schema work.
7. **Archetype wiring + matchup matrix** (§2f) — `deck_llm.py` is already built; this is
   plumbing plus one new page.
8. **Notes/tags write endpoint** (§3 QoL) — small feature that compounds with every
   other analytic.
