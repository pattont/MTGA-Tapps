# MTGA Tracker Dashboard — Site Completion Plan

Plan for finishing the local analytics site. Written for a Claude Code (Opus 4.8) session
with no prior context. Work through the phases in order; each is independently shippable.
Verify in the browser and keep both test suites green after every phase.

---

## 1. Current state (do not rebuild these)

The site is a two-part app, both already working:

- **Backend**: `src/mtga_tracker/dashboard.py` — dependency-free stdlib HTTP server.
  Serves `ui/dist` statics, a no-JS HTML fallback, and two JSON endpoints:
  - `GET /api/snapshot?deck=&format=&days=` — all dashboard aggregates, filterable
  - `GET /api/deck?name=` — per-deck drill-down (cards, openers, mulligans, formats, trend)
- **Frontend**: `ui/` — React 19 + Vite + vitest, **no router library** (hash routing),
  **no chart library** (hand-rolled SVG), no CSS framework (plain `styles.css` with CSS vars).

Already built: global filter bar (deck/format/period), rolling win-rate SVG trend chart,
Scryfall card art with gradient fallback, win/loss bar cells, sortable tables, dark/light
theme, deck detail page at `#/deck/<encoded name>` with context-aware sidebar nav, deck
links everywhere a deck name appears, per-route `document.title`.

### Key frontend files
- `ui/src/App.tsx` — routing shell + dashboard page + all dashboard column defs
- `ui/src/api.ts` — all API types + fetchers (`fetchDashboardSnapshot`, `fetchDeckDetail`)
- `ui/src/routes.ts` — `deckRouteHash()` / `parseDeckRoute()` (add new route helpers here)
- `ui/src/nav.ts` — `dashboardNavItems` / `deckNavItems` (sidebar contents per page)
- `ui/src/format.ts` — shared formatters (`formatDateTime`, `formatDuration`, `outcomeTone`…)
- `ui/src/components/` — `AppShell` (sidebar+topbar), `SortableTable` (generic, `numeric`
  column flag), `WinRateBar`, `TrendChart` (+ `ui/src/trend.ts` math), `DeckVisual`
  (art + fallback), `DeckLink`, `FilterBar`, `MetricCard` (optional `href`), `DeckDetailPage`
- Tests: `ui/src/App.test.tsx` (mock snapshot + deckDetail fixtures), `*.test.ts(x)` per module

### Commands (run from repo root unless noted)
```bash
venv/bin/python -m pytest tests -q          # Python suite (232 passing)
cd ui && npm test                            # vitest (33 passing)
cd ui && npx tsc -b && npm run lint          # must stay clean
cd ui && npm run build                       # REQUIRED after UI changes: prod server serves ui/dist
```
Dev servers are defined in `.claude/launch.json`: `api` (port 8765, restart it after any
dashboard.py change) and `ui` (Vite on 5173, proxies `/api`). Real data lives in
`data/mtga_tracker.sqlite3` — open read-only for inspection, never write to it.

---

## 2. Data reference (verified facts — trust these, don't re-derive)

Tables: `tracker_sessions`, `matches`, `games`, `participants`, `game_card_summary`,
`game_opening_hand_cards`, `game_drawn_cards`, `game_events`, `game_participant_stats`,
`session_participant_stats`, `participant_commanders`, `cards`, `raw_game_payloads`,
`console_logs`, `schema_migrations`.

- `games`: id, match_id, started_at/ended_at (local ISO), duration_seconds, total_turns
  (fully populated), player_turns, opponent_turns, outcome ('win'/'loss'/'draw'), outcome_reason.
- `participants`: per game, role='player'|'opponent'. deck_name only meaningful for player.
  went_first, mulligans, starting_life, ending_life, opening_hand_size.
- `matches`: format (raw queue string), best_of, games_played, winner_participant_id.
  559 matches, only 10 are Bo3 — keep match features proportionate.
- `game_events`: **57k rows, rich**: event_time, elapsed_seconds, turn_number, phase/step,
  actor_role, event_type (ability/draw/cast/turn/stack_resolve/zone/land/attack/…),
  text (human-readable line), player_life/opponent_life, zone_from/zone_to, amount.
  Indexed by session/time. This powers the game detail page (Phase 1).
- `game_card_summary`: one row per (game, participant, display_name); played/discarded/
  milled/exiled counts. **`drawn_count` is dead — always 0.** Real draws are in
  `game_drawn_cards` (clean names). Summary `display_name`s carry suffixes like
  " (Creature 2/2)" — strip with `_clean_card_name()` in dashboard.py.
- `cards`: `arena_id` is NULL for 1482/1497 rows — that's why image URLs use Scryfall
  `named?fuzzy=` by card name (art_crop). Keep that approach.
- Opponent `display_name` is always the literal "Opponent" and opponent `deck_archetype`
  is always NULL — **do not build opponent-name/archetype features.**
- `participant_commanders`: only 12 rows (Brawl) — footnote-level feature at best.

---

## 3. Conventions & gotchas (violating these broke builds before)

1. **No new dependencies** — backend stays stdlib-only, frontend adds no npm packages.
2. **Hash routing rule**: routes are `#/…`; anything else renders the dashboard. NEVER add
   raw `<a href="#section-id">` anchors — they clobber routes. Sidebar section links call
   `preventDefault()` + `scrollIntoView({ block: 'start' })` (see AppShell). Smooth
   scrolling is intentionally not used (silently no-ops in some browsers).
3. **eslint traps**: `react-refresh/only-export-components` — component files may export
   only components; put constants/helpers in `nav.ts`, `routes.ts`, `format.ts`, etc.
   `react-hooks/set-state-in-effect` — never call setState synchronously in an effect
   body; for per-route resets, remount with `key=` instead (see `<DeckDetailPage key=…>`).
4. **New pages** follow the DeckDetailPage pattern: own `LoadState` union, AbortController,
   20s refresh interval, remount via `key`, `window.scrollTo(0,0)` on mount, error state
   includes a "← Back" link.
5. **New endpoints** follow the `/api/deck` pattern: parse with `parse_qs`, return 400 on
   missing params / 404 via `LookupError` / 500 fallback, `Cache-Control: no-store`,
   read-only SQLite URI (`?mode=ro` + `PRAGMA query_only`). Reuse `_games_filter()` for
   games-scoped WHERE clauses and `_dict_rows()` for row dicts.
6. **Tables**: reuse `SortableTable` with `numeric: true` on number columns; win-rate
   columns render `<WinRateBar wins losses winRate>`; SQL computes win_rate as
   `ROUND(100.0*SUM(outcome='win')/NULLIF(SUM(outcome IN ('win','loss')),0),1)`.
7. **Tests are mandatory per phase**: Python (extend `tests/test_dashboard.py` — copy an
   existing handler test for new endpoints; fixture builder `_sample_dashboard_db`) and
   vitest (extend the mock fixtures in `App.test.tsx`; note jsdom lacks
   `scrollTo`/`scrollIntoView` — beforeEach stubs `window.scrollTo`; use optional-call
   `?.scrollIntoView?.()` in app code).
8. Keep the no-JS `render_dashboard_html` fallback working (it ignores new snapshot keys —
   just don't remove keys it uses).
9. **Do not touch** `src/mtga_tracker/tracker_*.py`, `tests/test_tracker_combat_winner.py`
   (uncommitted parser work in progress on this branch), or the SQLite DB contents.
10. After each phase: pytest + vitest + tsc + lint green, `npm run build`, restart `api`
    server, click through the feature in the browser at the Vite URL.

---

## 4. Phases

### Phase 1 — Game detail page (the biggest missing piece)
Every game row today is a dead end. Add `#/game/<encoded game_id>`.

**Backend** `GET /api/game?id=`, new `game_detail(db_path, game_id)`:
- Header data: game row + match (format → `format_label()`, best_of, game_number) +
  both participants (player: deck_name/went_first/mulligans/opening_hand_size/
  starting_life/ending_life; opponent: life fields only), outcome, outcome_reason,
  duration_seconds, total_turns.
- `opening_hand`: rows from `game_opening_hand_cards` for the player (name, type, ordered
  by hand_position, copy_number).
- `drawn`: from `game_drawn_cards` (name, type, turn_number, draw_position order).
- `cards_played`: from `game_card_summary` for the player where played_count>0
  (cleaned names, type, played_count).
- `timeline`: from `game_events` WHERE game_id=? ORDER BY event_time/id — cap ~500 rows;
  select turn_number, phase, event_type, text, actor_role, player_life, opponent_life.
  Also emit a compact `life_curve`: one point per event that has both life values
  (turn_number, player_life, opponent_life) for a life-total chart.
- 404 (LookupError) for unknown id. Tests: aggregates + handler 200/404/400 (missing id).

**Frontend**:
- `routes.ts`: `gameRouteHash(id)` / `parseGameRoute(hash)`; App renders
  `<GameDetailPage key={id} …>`; title `Game <date> – MTGA Tracker`.
- Link into it: Started/date cells in Recent Games + Draw Quality (dashboard) and the
  deck page's Recent Games table become links.
- Page layout: back link (to `#/deck/<deck>` if navigable, else `#overview` — simplest:
  always dashboard, plus a DeckLink chip in the header), metric cards (outcome badge,
  format, play/draw, mulligans, turns, duration, final life), **life-total chart**
  (second SVG series component: two lines, player vs opponent — generalize TrendChart or
  add `LifeChart.tsx` + pure math in `ui/src/life.ts` with unit tests), opening hand as
  card list, drawn cards table (turn drawn), cards played table, and a filterable
  timeline (client-side `<select>` on event_type; render turn/phase, text, life columns;
  group visually by turn_number).
- `nav.ts`: `gameNavItems` (Back / Summary / Life / Opening Hand / Draws / Timeline).

### Phase 2 — Card drill-down page
Cards appear in three tables but aren't clickable. Add `#/card/<encoded name>`.

**Backend** `GET /api/card?name=` (clean name), `card_detail()`:
- Match rows by cleaned summary name: `WHERE s.display_name = ? OR s.display_name LIKE ? || ' (%'`
  (bind the clean name twice) — avoids scanning with Python-side cleaning.
- `summary`: games seen, total played, wins/losses/win_rate when seen (player rows only).
- `by_deck`: same stats grouped per deck_name (DeckLink these rows in the UI).
- `opener_impact`: from `game_opening_hand_cards` by name — games in opener, win rate;
  plus overall deck-independent draw count from `game_drawn_cards`.
- `image_url` via existing `_card_image_url(None, name)`; `trend` optional — skip.
**Frontend**: `CardDetailPage` (art banner via `<img>` with the DeckVisual fallback
pattern, metric cards, by-deck table, opener stats). Add `CardLink` component; use it in
Visible Drawn Cards (dashboard) and Card Performance / Opening Hands (deck page).
Tests both sides, mirroring Phase 1.

### Phase 3 — Make the dashboard fully filter-aware & navigable
1. **Carry filters into subpages**: lift `SnapshotFilters` → serialize into deck route as
   `#/deck/<name>?days=30&format=Play` (extend `parseDeckRoute` to return
   `{name, filters}`; extend `/api/deck` to accept `format`/`days` and thread through
   `_games_filter(deck, fmt, days)` — the SQL already supports it). Deck links built from
   dashboard tables include current filters; "Back to dashboard" restores them (App keeps
   filter state; on deck→dashboard nav, re-apply from the route it came from).
2. **Active-section highlight (scrollspy)**: IntersectionObserver in AppShell marking the
   nav item of the section nearest the top with an `.active` class (guard
   `typeof IntersectionObserver === 'undefined'` for jsdom).
3. **Table depth**: server LIMITs (20/25) hide data. Add `limit` param to `/api/snapshot`
   (default 25, max 200) + a per-section "Show all" toggle in the UI, or simpler: raise
   deck/drawn-card limits to 100 and add a client-side text filter box above the Decks
   and Visible Drawn Cards tables (case-insensitive substring on name). Prefer the
   simpler option unless it feels slow.

### Phase 4 — Matches & sessions (round out the data model)
- **Matches section** on the dashboard (after Recent Games): last 25 matches from
  `matches` joined to player games: date, format_label, best_of, games W–L within the
  match, match result (from winner_participant_id ↔ player participant), deck (from its
  games). Only 10 Bo3 matches exist, so this is one table, not a page.
- **Sessions section**: `tracker_sessions` (73 rows) with games/wins/losses per session
  (join through games), started_at, duration. Gives a "play session" recap feel.
- Both: extend `/api/snapshot` (respect filters), add nav items, tests.

### Phase 5 — Fit & finish
- **Empty/onboarding states**: fresh DB or missing DB should render a friendly setup card
  (how to run the tracker) instead of bare error text — check `snapshot.summary.games === 0`.
- **Mobile pass**: at ≤980px the sidebar nav is a horizontal scroller — verify deck/game
  pages, filter bar wrap, and table overflow (use `preview_resize` mobile preset).
- **Light-theme QA**: click through every page in light mode; fix contrast (accent gold
  on white is the risky one).
- **README**: update the dashboard section with routes, filters, endpoints, screenshots
  optional. Update `CHANGELOG.md`.
- Optional (only if asked): local Scryfall image cache endpoint (`/api/card-image?name=` →
  fetch once, store under `data/card_images/`, serve with long cache) to make the site
  fully offline; adds urllib fetching to the server — keep timeout + failure fallback.

---

## 5. Definition of done

- No dead-end entities: decks, cards, and games all click through to detail pages;
  every detail page links back.
- Filters apply everywhere they claim to and survive navigation.
- `pytest` (all), vitest, `tsc -b`, `eslint` all green; `ui/dist` rebuilt; both servers
  restarted and every new page click-verified in the browser (screenshot each page once,
  dark + light).
- No new dependencies, no writes to the DB, tracker_*.py untouched.
