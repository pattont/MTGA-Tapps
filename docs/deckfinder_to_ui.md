# Deck Finder → the webapp — implementation plan

Run all of Deck Finder inside the dashboard instead of launching a separate
terminal window. The blue **Deck Finder** button stays where it is — it just
navigates to a new `#/deck-finder` page instead of spawning a terminal.

## Why this is very doable

The terminal app is a thin shell. All the real machinery is already
UI-agnostic:

- `providers/base.py` defines a clean interface — `list_sources(format)`,
  `fetch_decks(format, limit, source)`, `fetch_deck_variants(...)`,
  `hydrate_deck(...)` — implemented by untapped.gg, Aetherhub, Moxfield,
  magic.gg, MTGO, and TCGplayer providers. None of them touch the terminal.
- `result_view_config()` and the `_show_*_column` helpers already describe
  *what to display* per provider (which columns, labels, helper text) —
  that maps 1:1 to table config JSON for the React page.
- `ui.py` (1,100 lines of Rich rendering, prompts, pagination, clipboard
  hacks) is the only terminal-specific code, and none of it needs porting —
  the browser does pagination, tables, and clipboard natively and better.

So the work is: an API layer over the providers, plus a React page. No
scraper changes at all.

## Server: `/api/deckfinder/*` in the dashboard

New module `src/mtga_tracker/deckfinder_api.py`, wired into `dashboard.py`'s
router (keep imports LAZY so the dashboard stays stdlib-only until the page
is opened — the deck-downloader modules pull in `requests`).

- `GET /api/deckfinder/providers` — key, display name, description,
  homepage, supported formats, picker labels, `uses_source_picker` /
  `allow_all_sources` flags.
- `GET /api/deckfinder/sources?provider=&format=` — the source/creator list
  for the picker (creators split from endpoints like `_split_creator_sources`).
- `POST /api/deckfinder/fetch` `{provider, format, source?, limit}` —
  starts a scrape **as a background job** and returns `{job_id}`. Scrapes
  take seconds (rate-limited sessions); the job pattern keeps dashboard
  request threads free and avoids browser timeouts.
- `GET /api/deckfinder/jobs/{id}` — `{status, progress_note, decks?}` with
  `DeckEntry` serialized as JSON plus the provider's `result_view_config`
  so the UI knows which columns to show. Poll every ~700ms (same pattern
  the page already uses for refreshes).
- `POST /api/deckfinder/hydrate` `{provider, deck}` — on-demand deck-text
  resolution (untapped deckstring decode) when a row is opened.
- `POST /api/deckfinder/variants` `{provider, deck, format}` — archetype
  variants, also as a job.
- `GET/PUT /api/deckfinder/config` — read/update `deckfinder_config.json`
  (Moxfield/Aetherhub/TCGplayer creator lists) so the config finally gets a
  UI instead of hand-editing JSON.

**Caching**: in-memory TTL cache (~10 min) keyed by (provider, format,
source) so tab-hopping doesn't re-scrape; persist the last result set to the
data dir so reopening the page is instant, with a "Refresh" button that
forces a new job. Job store is a small dict with a lock — same threading
model the tracker already uses.

## UI: a `#/deck-finder` route

New `ui/src/components/DeckFinderPage.tsx`, using ONLY existing building
blocks (SortableTable, Section, Badge, ColorPips, ManaCost, quick-filter
chips):

1. **Provider row** — one card per provider (name, description, homepage
   link), like the Formats rectangles.
2. **Format chips** — Bo1 / Bo3 / Any, shown per provider support.
3. **Source picker** — creators vs endpoints, honoring
   `uses_source_picker` / `allow_all_sources`, with the provider's own
   labels.
4. **Results table** — columns driven by the provider's view config: deck
   name, player, win rate, matches, event/date, notes (Aetherhub creator
   tags rendered as chips). Sortable and paginated for free via
   SortableTable.
5. **Deck detail drawer** — the decklist with the mana-font Mana column
   (reusing the deck page's renderer), a **Copy for Arena** button
   (`navigator.clipboard` on a click — strictly better than the terminal's
   pbcopy/xclip guessing), the source link, and a variants list when the
   provider supports it.
6. **Surprise Me** — port of "play a random deck": one click, random
   provider/format/deck, straight to the detail drawer with copy ready.
7. **Settings panel** — edit the creator lists (the `GET/PUT config`
   endpoints), replacing hand-edited JSON.

Sidebar: the blue Deck Finder button becomes a link to `#/deck-finder`.
Keep `POST /api/deck-downloader/launch` and the bundled terminal app for one
release as an "Open in a terminal instead" escape hatch, then retire both
(that also removes a whole PyInstaller companion binary from the build).

## Dependencies & packaging

- The dashboard process imports deck-downloader modules lazily; `requests`
  and the scrapers already ship inside the app bundle, so frozen builds need
  no packaging change.
- `rich` remains only for the terminal app; the new path never imports it.
  When the terminal app retires, `rich` (and the second PyInstaller target)
  drop out of the build entirely.

## Testing

- API tests with a stub provider (instant fake decks) covering the job
  lifecycle, caching, hydrate, and config round-trip.
- Existing scraper tests already cover the providers with recorded fixtures
  — unchanged.
- UI tests: mocked fetch for providers/jobs; assert the provider → format →
  source → results → detail flow and the copy button (clipboard mocked, same
  as the deck page's copy test).

## Risks / honest notes

- **Slow scrapes**: the job pattern + polling absorbs them; the UI shows
  the provider's progress note ("decoding deckstrings…").
- **Site drift**: unchanged risk — same scrapers, same fixtures; failures
  surface as a readable job error with a retry button instead of a
  terminal stack trace.
- **Two front-ends during transition**: terminal and web page share the
  provider layer, so there's no logic fork — only the escape-hatch button
  to delete later.

## Phases & effort

1. **API layer + job store** (~1 day): providers/sources/fetch/jobs/hydrate,
   lazy imports, tests.
2. **React page** (~1–1.5 days): provider → format → source → results →
   detail drawer with Copy for Arena; sidebar button becomes a route.
3. **Polish** (~0.5–1 day): variants, Surprise Me, config editor, caching +
   persisted last results.
4. **Retirement** (a later release): drop the terminal app, launcher
   endpoint, `rich`, and the companion PyInstaller binary.
