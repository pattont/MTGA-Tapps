# AGENTS.md

Guidance for coding agents working on this MTGA tracker. Keep this file current when tracker behavior, database schema, or test commands change.

This is the single source of truth for agent instructions — there is deliberately no
`CLAUDE.md`; do not add one.

## Project Overview

This is a Python log-only gameplay tracker for Magic: The Gathering Arena. It tails MTGA `Player.log`, parses GRE game-state messages, prints a readable console log, and persists dashboard-friendly analytics to SQLite. A React/TypeScript dashboard (`ui/`) is built to static assets and served by the Python dashboard server — there is no separate web backend, no account, and no cloud. The optional collection exporter separately reads Arena process memory on macOS/Windows.

Repo layout:

- `src/mtga_tracker/`: tracker runtime, analytics store, dashboard server, desktop app.
- `src/mtga_deck_downloader/`: the bundled Deck Finder companion tool.
- `ui/`: React/Vite dashboard frontend (built to the gitignored `ui/dist`).
- `overlay/`: the in-game overlay, a Tauri v2 app — Rust shell in `overlay/src-tauri/`
  (window, docking, hotkeys, Arena probe; no tray — the tracker menu drives it via a
  second launch with `--open-settings`/`--show`/`--hide`) and a Preact page in `overlay/src/`.
  It talks to the tracker only through `GET /api/overlay`; the Python side that launches
  it is `src/mtga_tracker/overlay_launcher.py`. See `overlay/README.md`.
- `tests/`: pytest suite, including `tests/deck_downloader/`. `tests/deprecated/` holds
  non-test debug scripts and is not part of the suite.
- `packaging/` + `scripts/`: PyInstaller specs, entry points, and OS build scripts.
- `docs/`: reference guides, research notes and the removal ledger; `docs/plans/` holds
  only unfinished implementation plans and related validation notes. README and
  release screenshots live in `docs/images/`. `docs/plans/INDEX.md` records plan status;
  completed behavior belongs in reference docs, and the README links only to current
  features and reference guides. `docs/RELEASING.md` covers releases. `CHANGELOG.md` tracks releases.
  The version comes from the git tag (setuptools-scm writes `_version.py`); there is no
  hand-edited version string anywhere, and a release is cut by pushing a `v*` tag. Never
  bump or invent a version in code. For pre-tag screenshots, the dashboard accepts
  `?screenshotVersion=<version>` before its hash route; this changes only the sidebar
  footer label, not the actual package version or update check.

### Entry points

`pyproject.toml` defines these console scripts (all runnable as `python -m` equivalents):

- `mtga-tracker-app` → `app.py`: unified launcher (tracker + dashboard + menu-bar app).
- `mtga-tracker` → `main.py`: console tracker only.
- `mtga-tracker-dashboard` → `dashboard.py`: dashboard server only.
- `mtga-tracker-audit-db` → `db_audit.py`, `mtga-tracker-draw-quality` → `draw_quality.py`.
- `mtga-deck-downloader` → `mtga_deck_downloader.__main__`.

Primary code paths:

- `src/mtga_tracker/main.py`: console-tracker CLI entry point.
- `src/mtga_tracker/app.py`: unified launcher that wires one `AnalyticsStore`/`--db` into both
  the tracker thread and the dashboard server, with or without the GUI (`--no-gui`). It holds
  the process-wide `single_instance.py` guard before starting any of them: a named mutex on
  Windows and a per-user advisory lock on macOS/Linux. Deck Finder mode bypasses this guard.
- `src/mtga_tracker/menu_app.py`: PyQt6 menu-bar/tray controller. Its "Live Scoreboard"
  item opens the dashboard's `#/live`; the old Qt log window is a debug fallback. GUI-only;
  guarded by the `gui` extra and skipped in headless test runs.
- `src/mtga_tracker/paths.py`: cross-platform discovery of `Player.log`, the data dir, and
  Arena's raw card DB (macOS, Windows Steam libraries via `libraryfolders.vdf`, Epic,
  `MTGA_DATA_DIR` override). All path logic belongs here — do not inline OS checks elsewhere.
- `src/mtga_tracker/log_entry.py`: groups raw file lines into complete log entries (Arena
  writes some events as a header plus continuation JSON).
- `src/mtga_tracker/log_json.py` / `log_timestamp.py` / `log_sanitize.py`: JSON extraction,
  timestamp parsing, and privacy scrubbing of raw log text before archival.
- `src/mtga_tracker/log_parser.py`: JSON extraction and ordered game-state/client-message parsing.
- `src/mtga_tracker/event_router.py`: lightweight log-entry routing plus parser health counters.
- `src/mtga_tracker/client_actions.py`: normalizes client-to-GRE actions.
- `src/mtga_tracker/annotations.py`: dataclass helpers for parsed GRE annotation details.
- `src/mtga_tracker/opening_hand.py`: opening-hand payload helpers.
- `src/mtga_tracker/state.py`: mutable tracker state and event models (`CardEvent`, etc.).
- `src/mtga_tracker/rendering.py`: low-level console rendering helpers (terminal/stream level);
  game-facing formatting lives in `tracker_rendering.py`.
- `src/mtga_tracker/rank_progress.py`: parses and normalizes MTGA rank snapshots.
- `src/mtga_tracker/tracker.py`: thin `CardTracker` composition/init class. Keep it small.
- `src/mtga_tracker/tracker_runtime.py`: startup banner, live polling loop, stop/cleanup.
- `src/mtga_tracker/tracker_lifecycle.py`: game start/end, match lifecycle, winner/outcome handling.
- `src/mtga_tracker/tracker_events.py`: core GRE event orchestration and annotation dispatch.
- `src/mtga_tracker/tracker_event_*.py`: focused event helpers for abilities, client actions, life, targets, and turns.
- `src/mtga_tracker/tracker_zone_transfers.py`: zone-transfer handling for draw/discard/mill/exile/destroy/return/play/cast.
- `src/mtga_tracker/tracker_stack.py`: stack lifecycle tracking and resolution/fizzle/counter display.
- `src/mtga_tracker/tracker_combat.py`: attack/block/combat damage handling.
- `src/mtga_tracker/tracker_opening_deck.py`: opening hand, mulligan, format, commander, deck metadata.
- `src/mtga_tracker/tracker_analytics.py`: SQLite persistence helpers.
- `src/mtga_tracker/format_normalizer.py`: single source of truth for raw queue/format labels and best-of inference. Unknown identifiers with an `Event` token or a terminal YYYYMMDD date are generic events: preserve and humanize them instead of guessing a constructed or Brawl format.
- `src/mtga_tracker/removal_classifier.py`: text-based card-role classification (removal /
  board wipe / bounce / counter) from Arena rules text, cached per grpId. Roles feed the
  played/drawn interaction stats; behavioral stats (things actually destroyed, countered,
  bounced) come from game events and work without the Arena card DB.
- `src/mtga_tracker/events_backfill.py`: recomputes behavioral interaction stats for
  historical games from the `game_events` timeline (used by migration v19 — fills NULL
  columns only, never overwrites live-tracked values).
- `src/mtga_tracker/db_audit.py`: SQLite consistency audit and safe repair CLI.
- `src/mtga_tracker/dashboard.py`: dependency-free local SQLite dashboard. Read paths are
  set-based on purpose: `_draw_quality_batch` classifies every game in a handful of queries
  (the overview and All Games use it — never call the per-game `_game_draw_quality` in a loop
  over history), `_split_card_index` replaces per-row LIKE lookups, and All Games gathers
  opponent colors in one grouped query. Profile with a copy of a real database before
  adding a correlated subquery that runs once per game.
  The handler speaks HTTP/1.1 with keep-alive: every response must carry a
  Content-Length (`_send_bytes`) or be bodiless (304, `send_error`); POSTs close the
  connection because not every branch drains its body. Built files under `assets/` are
  served immutable for a year (Vite content-hashes them), `index.html` and icons revalidate
  by Last-Modified; API responses stay `no-store`.
- `src/mtga_tracker/live_api.py`: `/api/live` payload — current game, frozen previous-game
  scoreboard, records vs. deck / opponent / opponent commander, local archetype guess.
- `src/mtga_tracker/draw_quality.py`: CLI/report helpers for land flood/screw and repeated-card draw audits.
- `src/mtga_tracker/tracker_summary.py`: end-game and session summary rendering.
- `src/mtga_tracker/tracker_rendering.py`: console formatting, actor labels, mana/text cleanup, runtime strings.
- `src/mtga_tracker/tracker_state_lookup.py`: object snapshots, identity/copy-state, card type, zone/seat lookup helpers.
- `src/mtga_tracker/tracker_diagnostics.py`: unhandled annotation and parser diagnostics text logging.
- `src/mtga_tracker/card_database.py`: local Arena card ID to card name/type resolution, plus
  color-identity lookup from Arena's local card DB.
- `src/mtga_tracker/analytics.py`: `AnalyticsStore` — schema, numbered migrations, and startup
  maintenance (card-color backfill, imported-deck-name canonicalization).
- `src/mtga_tracker/analytics_persistence.py`: focused persistence helpers split out of the
  store; put new write helpers here rather than growing `analytics.py`.
- `src/mtga_tracker/colors.py`: WUBRG normalization and community color-combo naming
  (Mono-X, guilds, shards/wedges, 4c names, 5c). The UI mirrors this in `ui/src/colorCombos.ts`.
- `src/mtga_tracker/payload_codec.py` / `payload_dump.py`: zlib codec for the raw payload
  archive and the CLI to print archived payloads as readable JSON.
- `src/mtga_tracker/deck_llm.py`: opt-in AI opponent-deck identification (OpenAI/Claude/Gemini).
  Config resolution order: `settings.json` ("deck_ai" section) → `config.py` → env. One cheap
  call per completed game, fired from `_start_opponent_archetype_lookup` on a daemon thread —
  it must NEVER block live tracking. Reasoning-class OpenAI models (gpt-5/o-series) get
  `reasoning_effort: low` and a retry on token-starved empty replies.
- `src/mtga_tracker/replay_capture.py` / `replay_capture_events.py`: live replay capture.
  Tracker mixins attach a `ReplayFact` to the lines they already print and write silent
  (`visible = 0`) `game_events` rows for facts the console never prints (taps, counters,
  tokens, blocks, attachments, hidden-card moves, phases). Rows from one message go in one
  transaction; silent rows store `game_id` only. `games.replay_version = 1` marks a recorded
  game. Console text and the printed row set must stay byte-identical
  (`tests/fixtures/replay_capture_baseline.json` guards this). Every hook called from a
  mixin is wrapped in `@replay_safe()` (a failure logs one diagnostics line and drops the
  fact), and a failed batch never loses its printed rows.
- `src/mtga_tracker/replay_stream.py` / `replay_builder.py` / `replay_reconstruct.py`
  (row handlers; `_grammar.py` regexes and stack pairing, `_board.py` objects/zones/setup) /
  `replay_dump.py`: the replay stream served by `GET /api/replay?id=` — built from
  structured rows for recorded games, reconstructed from the text timeline for older ones
  (`fidelity: reconstructed`, with a `limitations` list). `docs/REPLAY_FORMAT.md` is the
  binding contract for rows, stream and UI module APIs; change it first. Fixtures in
  `tests/fixtures/replay/` are exported read-only and anonymized by
  `scripts/export_replay_fixture.py`. `python -m mtga_tracker.replay_dump <game_id>` prints a
  stream. `ui/src/replay/effects.ts` keeps the current action's effect window
  (damage, life, removal, counters, P/T, discards, mills, each with its source)
  until the next action, or any event in a new step or phase (`applyEvent`);
  removed permanents stay dimmed in their slot meanwhile,
  and moves carry `by` (Arena's affector root) for recorded games.
  Flying creatures (card `keywords` `flying`, Arena ability id 8, matched by
  Abilities.Id since it has BaseId 0; tokens by grpId) hover `FLYING_LIFT`
  above the felt with a further, darker shadow. Tokens never take the
  `set|collector` image cache (Arena's token number names another card in the
  set); they carry `token_print` (`t<set>/<number>`, Scryfall's token set).
  The builder moves a `token_create` row ahead of earlier rows of its turn that
  name the token (Mobilize attackers print before their creation).
  Identical tokens and lands stack in one battlefield slot (`layout.stackKey`),
  and identical abilities next to each other on the stack show as one preview
  card (`stackView.groupStack`/`foldResolved`); counters the tracker records as
  `counter_<n>` are named from Arena's `Enums` CounterType at build time.
- `ui/src/replay/`: the Replay page — pure reducer/layout/playback-clock/image-queue/prefs
  modules with tests, `export/` (pure video plan, Canvas 2D frame composer, WebCodecs +
  mp4-muxer encoder for the in-browser MP4 export; each codec is probed with one frame and
  H.264 without a reported `decoderConfig` is skipped for VP9, whose config is filled in; the
  export driver waits for the canvas's own reconciler to commit each clock step
  (`state.seq === clock.snapshot.seq`) before drawing, or frames lag an action and
  the closing hold misses the ending card; Firefox's VP9 ignores bitrate, so sizes
  are shown as upper limits), and `components/` holding the `@react-three/fiber` scene (lazy-loaded
  route `#/replay/<id>`, list at `#/replay`). Teal `--replay` is reserved for replay
  affordances; everything replay-related carries `replay-wide-only` and is hidden below
  900 px.
  On Live Scoreboard, the header replay link matches the other pills, the
  between-game waiting status sits beside the format on the right, and Today's
  Games uses compact 20 px replay icons and one-letter W/L/D result pills
  (full word on hover and for screen readers) to preserve space for deck names.
  A tiny teal Play / purple Draw `Badge` (`participants.went_first`) follows the deck
  name; the name truncates first and unknown turn order shows nothing.
- `src/mtga_tracker/settings.py`: shared `settings.json` — top level of the repo next to
  `config.py` for source runs, per-user data dir for frozen builds (legacy `data/settings.json`
  migrates automatically). Startup preferences are stored in its `startup` section.
- `src/mtga_tracker/startup.py`: per-user Windows Run / macOS LaunchAgent registration. Frozen
  builds register the app/executable; source runs register the active Python environment.
  `--login-start` marks OS launches so an already-running app exits quietly; it does not override
  the saved browser preference.
- `src/mtga_tracker/settings_api.py`: dashboard settings for Deck AI, Deck Finder creators,
  startup behavior, the session break, overlay control, platform capabilities, and resolved tracker paths. The menu
  "Tracker Settings" action opens this dashboard page. `settings_dialog.py` retains
  the PyQt Deck AI settings implementation.
- `src/mtga_tracker/deck_manager.py` / `deck_manager_api.py`: general local deck library,
  `#/deck-manager` and `/api/deck-manager/*`, using the same selected `--db` as analytics.
  The collection uses a full-page responsive tile grid; details/revision editing and
  new imports open native dialogs. CardLink previews portal into their containing
  dialog so the browser’s top layer does not obscure them.
  Saved/Arena tiles share a fixed height and 76px artwork. Arena reuses matching
  library artwork or its roster printing ID, with the existing Scryfall loader.
  Bottom-right colored status/backup pills filter through clicks or the status
  selector; changing a filter clears selection. An unconnected roster must show
  Not checked, never infer Collection only from a missing native observation.
  Moving a deck to Trash opens a recoverable-action confirmation; native Restore
  to Arena (or Add to Arena for text-only revisions) appears as a yellow button
  in the deck dialog header beside Copy deck list and Close, hidden when Arena has the deck.
  Every saved/trash tile has a top-right 24px checkbox in a separate 44px target;
  selection never opens details. Local bulk removal supports all saved deck types,
  including decks still in Arena. Both bulk Trash and permanent-delete dialogs list
  every selected deck; `/api/deck-manager/remove-selected` validates explicit
  confirmation and applies the entire selection in one transaction. Permanent
  deletion still requires Trash and protects pending transfer backups.
  Migration 33 creates independent `managed_decks`, `managed_deck_revisions`,
  `managed_deck_cards` and `managed_deck_bindings` tables. Library trash/reset
  never deletes Arena decks; gameplay reset preserves the library. Permanent local
  deletion requires a trashed entry and explicit confirmation, and removes its cards,
  bindings and revisions in one transaction. `.tappsbackup` carries
  decks and revisions; merge unions verified snapshots and skips Arena bindings. Restore
  previews count deck/revision losses even when no games are lost.
- `deck_native_api.py` / `deck_transfers.py` / `native_deck_bridge.py` /
  `native_deck_archive.py` + `assets/arena_decks.js`: direct native Deck Manager
  jobs, explicitly started from the dashboard. GET/status polling never attaches.
  The Arena tab supports bulk backup/move; Saved supports direct native restores.
  Deck Finder's Add to Arena uses explicit `add` jobs. Arena's TryImportDeck parses
  text in memory with live Decks providers; validate complete pile/card-name counts
  before persisting a native archive and calling the existing journaled restore.
  Reject inventory clamping/unresolved names/Maybeboard instead of creating a partial
  list. Import request IDs retain text/name/format provenance and must not replay as
  different lists. The localization provider is the verified static field
  `Wotc.Mtga.Loc.Languages.ActiveLocProvider`, not a getter; CurrentLanguage is a getter.
  Do not attach or restart Arena/tracker while the user plays. Wait for the user to explicitly report
  being out of a match on Decks before any live validation; app restarts still
  require explicit approval.
  Runtime support is Unity `6000.3.14f1` on Apple Silicon macOS (IL2CPP, validated)
  and x64 Windows (Mono, validated), gated by `paths.native_deck_platform_supported`
  and the adapter's `ARENA_ARCH` build check. Windows Arena ships no `GameAssembly.dll`;
  it embeds `mono-2.0-bdwgc.dll`. `arena_decks.js` picks `il2cppRuntime()` or
  `monoRuntime()`, which expose the same helper names; keep deck logic runtime-neutral
  and put any new runtime call in both. Object/array/string/struct layouts match on
  64-bit, so the layout checks are shared. Mono pitfalls (both seen live): its JIT
  uses hardware faults for null checks, so `mono_runtime_invoke` must keep Frida's
  `exceptions: 'propagate'`; `mono_field_set_value` takes a reference value
  itself but a value type by pointer; and Mono's invoke takes a `Nullable<T>`
  argument as a boxed `T` or null, where IL2CPP takes the raw struct. The bridge attaches to `MTGA` or `MTGA.exe`. Frida is pinned for Mac and Windows and lazily imported; the asset and
  extension are included in both platforms' packaging configuration.
  Check the active-game row before attachment and between transfers, and check the
  live Decks controller, same native service and authenticated account for writes.
  Only AccountInformation.AccountID is read/hashed; never read credentials.
  Migration 35 adds `managed_deck_collections` and nullable `managed_decks.collection_id`.
  Named collections render collapsed and Unsorted open; search/status filters expand
  all, and creating or moving decks into a collection expands it.
  Saved decks belong to one named collection or Unsorted. Store jobs take one optional
  top-level `collection_id` (null = Unsorted) that also reassigns an earlier backup. Collection removal moves
  all members (including Trash) to Unsorted; it never deletes decks/revisions.
  `deck_collections.py` owns atomic moves and collection merge mapping; backup merge
  combines equal collection names and gameplay reset preserves memberships.
  Deck Finder passes the saved entry ID to native add so its full native revision
  upgrades the same entry, retaining notes, collection and earlier text revisions.
  Jobs expose verified step counts for progress bars; connecting stays indeterminate.
  After a job that sent a create/delete, closing the attachment calls `refreshscreen`:
  it starts Arena's own `DeckManagerController.Coroutine_LoadDecks(_selectedBucket,
  deckId)` on the open Decks screen, selecting the last created deck (`Guid?` is a
  HasValue byte plus the Guid at +4); skipped while Arena is loading or a request is
  pending. Selection does not scroll, so `scrollToSelectedDeck` then centers that tile
  via the `ScrollRect` on the `DeckViewSelector` (content pinned at the top) once the
  rebuilt tile exists, skipping a collapsed folder. It is display only and best effort,
  and never fails a verified transfer.
  Not-on-Decks failures use the bridge's single `DECKS_SCREEN` message; the job API
  strips Frida's `Error:` prefix and script stack before showing adapter reasons.
  Migration 34 adds `managed_deck_transfers` with one pending intent per account.
  Commit/read back exact native archives before any removal; write intents commit
  before single native calls. Interrupted outcomes stop; reconciliation is read-only,
  never a create/delete retry. Pending journals protect their local backups from
  permanent deletion. Full backups carry journals; merge skips journals/bindings.
  Use all four piles and explicit native deserialization types; preserve Int64
  model JSON as text and exclude computed summary setters. Source/restore comparison
  ignores JSON object-key order and permits only null/empty-description equivalence;
  array order and all values remain checked. Native preparation is a separate RPC
  before write intent; preparation errors cancel locally with no create dispatched.
  A dispatched timeout remains uncertain and cannot be cancelled from absence alone.
  Native revisions with edited
  lists/name/format cannot restore stale model data. Native portable backups retain
  the hashed account provenance. No queue, crafting or gameplay calls are allowed.
  Tests: `tests/test_deck_transfers.py` and `node --test tests/native_decks.test.cjs`
  are offline and must never attach to Arena. UI checks remain the normal four commands.
  `scripts/preview_deck_manager.py --db <separate-library> --tracker-db <active-db>`
  runs only a dashboard on port 8880 by default, with live Arena actions. Its game
  guard reads the active DB in read-only mode on each check, fails closed when
  unavailable, and rejects sharing that database with the test library. Other
  dashboard POST routes are disabled except read-oriented Deck Finder fetch,
  hydrate, variants and surprise jobs. It starts no tracker or desktop app.
  `tests/test_deck_manager_preview.py` covers isolation and fresh game-status checks.
- `src/mtga_tracker/deck_capture.py`: the existing log-entry pipeline archives available
  `DeckUpsertDeckV3` / `EventSetDeckV3` outgoing lists for any format before game-exclusion
  gates. They are unconfirmed observations, not a complete roster or successful save.
  A capture for an Arena deck tied to an entry by a binding or transfer row (the row
  commits before Arena logs its create) goes to that entry, and adds nothing when any of
  its revisions has the same name and list; a native backup adopts the log-captured
  `captured_deck_id` entry unless it is trashed. One Arena deck keeps one saved entry.
  Replay must not move the current revision backward; unresolved IDs remain intact in
  full backups. Do not infer slot usage/account/presence or enable native writes from logs.
  See the README's Deck Manager section, `docs/plans/INDEX.md`, `tests/test_deck_manager.py`
  and `ui/src/components/DeckManagerPage.test.tsx`.
- `deck-manager-bridge/poc/`: explicit development-only Frida/IL2CPP experiment,
  never auto-loaded or packaged. Mac Unity 6 native folder and bulk cache capture
  are demonstrated; one disk-reconstructed duplicate persisted across an Arena
  restart, was fetched with matching metadata/piles/skins, and was removed.
  The initial verification probe crashed Arena; borrowed-thread detach was fixed
  before recovery. This is feasibility evidence, not production reliability.
  Attach to an explicit running PID; never restart Arena or modify its installation.
  Reports contain private decks and belong outside git. Capture targets a new,
  separate database only. Temporary UI tests require an agreed out-of-match Decks
  session; `disposable_copy.py --execute` and `disk_restore.py --execute` require
  approval for their specific account
  create/delete test. It may delete only its new verified test copy after durable
  read-back, never the source. Unknown outcomes stop without retry.
  `disk_restore.py --resume` adopts only the journaled existing copy; it cannot
  create another deck. Typed archives keep Int64 JSON as text and restore only
  physical summary fields, excluding computed setters. Never detach an existing
  Arena-owned IL2CPP thread; release only attachments made by the probe.
  See its README
  and `docs/plans/deck-manager/NATIVE_POC.md`; offline checks:
  `PYTHONPATH=src venv/bin/python -m pytest tests/test_native_deck_poc.py -q`
  and `node --check deck-manager-bridge/poc/probe.js` followed by
  `node --test deck-manager-bridge/poc/probe.test.cjs`. Read polling allows a
  temporary native UI rebuild but retains service identity; writes still require
  Decks open. Snapshot comparison treats only null/empty descriptions as equivalent.
- `src/mtga_tracker/deckfinder_api.py`: background jobs for the integrated dashboard Deck Finder.
- `src/mtga_deck_downloader/providers/base.py`: constructs each scraper lazily
  on first use, under a per-provider lock. Site/source picker metadata must not
  import scraper libraries, create HTTP clients, or fetch remote decks. Dynamic
  scraper imports are covered by the packaging spec's package-wide collection.
  The dashboard's provider cards use compact subtitles with full descriptions
  in tooltips, bundled site icons on tinted backgrounds, and a responsive grid
  sized for all seven sites on desktop. Provider cards have subtle site-colored
  fills, stronger on hover and selection; the picker omits the redundant Site
  label. Surprise Me sits beside the section collapse control in the Browse
  Decks heading. AetherHub uses a 228px asset; Magic.gg
  uses a vector Planeswalker mark. Results use a 40/60 browser/selected-deck
  layout that stacks on narrow screens. Detail results open the first deck;
  the main-deck count sits beside the format, and filter pills hover in the
  provider's selection color. Deck names and titles share that provider hue,
  with a subtle matching selected-row tint and darker text in the light theme.
  Source and Export to Arena sit together at the far right of the deck-name
  row. Add to Arena and Save to collection sit below the description in a
  fieldset whose legend links to Deck Manager, styled in its orange accent; a
  right-aligned accent pill notes that Arena must be on Decks, filled in after that failure. The heading wraps on narrow screens.
  Stale hydration responses cannot replace a newer selection or clear its
  loading state. `ui/src/deckFinderImport.ts` parses import text for display,
  retaining separate Deck/Sideboard/Commander/Companion sections; clipboard
  export uses the original text. Unrecognized imports fall back to raw text.
  The Deck Finder route skips the Overview snapshot request in `ui/src/App.tsx`.
  Deck Finder reads Arena status (`/api/deck-manager/native`) only while a deck is
  open and the tab is visible (`usePageVisible`), and the saved library only when
  the collection picker first opens. Dashboard pollers skip hidden tabs.
  `native_deck_bridge.availability()` locates Frida with `find_spec` and must not
  import it; only an attach loads its native library.
- `src/mtga_deck_downloader/providers/youtube.py` + `scrapers/youtube.py` /
  `youtube_decklist.py`: YouTube creator decks from the latest 15 Videos-tab
  entries sorted by Latest. Use keyless filtered player metadata, three worker
  sessions, and a watch-page fallback; never download media or require cookies
  from a signed-in browser. HGG/Sloth are defaults in `YouTubeCreators`; preserve
  these entries when old settings payloads omit `youtube`. Normalize Deck/Decklist
  headings to `Deck`; a complete 60-card list without a heading can also be
  imported when it contains at least ten card rows. Headerless Brawl lists are
  skipped because the commander cannot be identified. Strip title emoji with
  the bundled `emoji` dependency.
  Reuse the existing 10-minute dashboard memory cache; failed/partial fetches
  show warnings and are not cached. UI uses a simple loading message, no progress
  bar. The README covers creator setup; regression fixtures live in
  `tests/deck_downloader/fixtures/youtube/`.
- `ui/src/components/BuyPaperDialog.tsx` + `cardPrices.ts` / `paperDeck.ts` /
  `paperVendors.ts` / `scryfallQueue.ts` / `storePrices.ts`: Buy on Paper (no
  schema). A green button sits between Source and Export to Arena in Deck Finder,
  in the Deck Manager deck dialog header, and in the deck page's Deck List section heading.
  Prices are Scryfall TCGplayer-market prices: one collection pass, then batched
  `(!"A" or !"B")` searches sorted by `usd`, with basics searched separately.
  Scryfall allows 2 requests per second on search/collection and locks the caller
  out after a 429 (seen as a CORS error in the browser), so every price call
  goes through `scryfallFetch`, which spaces calls and backs off for a minute.
  Never add per-card requests. Settled results cache in localStorage for 24 h.
  Card Kingdom and Mana Pool price from their own public lists:
  `src/mtga_tracker/paper_prices.py` downloads each (50–70 MB) on a background
  thread at most daily. It stream-parses with ijson, keeps the cheapest in-stock
  copy per name and face, and caches the result in `<data dir>/paper_prices/`;
  `GET /api/paper-prices` answers ready/loading/error and never blocks. The
  dialog loads both lists when it opens, for the store list. That list is the
  only store picker (no dropdown) and shows each store's total. A store shows only
  its own prices, never another store's as a stand-in: unlisted cards and a list
  that failed to load show a dash and stay out of totals. A store we can't price
  (SCG/CSI: `priceSource: null`, `comingSoon`) shows "Coming soon" and can't be
  chosen; a saved choice of one falls back to TCGplayer. Stores are listed
  alphabetically; TCGplayer is the default.
  Tests (`tests/test_paper_prices.py`) never download.
  Settings → Buy on Paper (after In-game overlay; `settings.json`
  `buy_on_paper.enabled`, default on) is the off switch. Off hides every button
  (`BuyPaperButton` reads `ui/src/buyOnPaperSetting.ts`), cancels downloads
  through a generation counter, makes lookups answer 403, and deletes the price
  folder. The folder holds one index per store plus at most one capped download
  each; every refresh sweeps leftovers. Keep it bounded.
  Store links follow EDHREC/Cube Cobra formats; SCG and CSI keep a dormant
  copy-and-open handoff for when they can be priced. Empty `AFFILIATE` values mean plain links, and the commission
  disclosure shows only for a store with a code. Never track a paper collection.
  See `docs/BUY_ON_PAPER.md`.
- `src/mtga_tracker/collection_api.py` / `collection_export.py` / `inventory.py`: explicit
  collection-export jobs, macOS/Windows process-memory readers, and local card metadata.
- `src/mtga_tracker/overlay_state.py` / `overlay_launcher.py`: library-composition odds
  and the separate overlay process manager; enabled by default when the binary is available.
  The manager recognizes an already-running Tauri singleton by its exact executable path;
  a successful second-instance handoff must not be treated as the overlay quitting or change
  `overlay.enabled` to false. Exit code 23 is reserved for an explicit **Quit overlay** action.
  On macOS, `overlay/src-tauri/src/arena.rs` parses `lsappinfo` one property line at a time;
  macOS 27 returns extra properties even with `-only`, so never parse everything after the first
  equals sign or Arena will be treated as never frontmost and the overlay will hide itself.
- `src/mtga_tracker/deck_downloader_launcher.py`: launches the bundled Deck Finder in a sized
  terminal window via `POST /api/deck-downloader/launch`; frozen builds invoke the same
  tracker executable with `--deck-finder`. The menu item opens dashboard `#/deckfinder`.
- `src/mtga_deck_downloader/`: the bundled Deck Finder (vendored copy of MTGA-DeckDownloader).
  Treat it as a companion tool: keep its internals as-is except where integration requires.
  Its creator config is `deckfinder_config.json` at the repo top level; its tests live in
  `tests/deck_downloader/` and run as part of the normal pytest suite.
- `tests/test_tracker_combat_winner.py`: broad regression coverage for tracker behavior.

## Commands

Use the repo virtualenv unless there is a clear reason not to. In a sandbox without one,
create it first (`python3 -m venv venv && venv/bin/pip install -e '.[dev,gui]'`) or drop the
`venv/bin/` prefix and use the ambient interpreter.

```bash
# Setup
python3 -m venv venv && venv/bin/pip install -e '.[dev,gui]'   # add ,build for PyInstaller

# Full Python suite as CI/agents run it (menu app needs a display; one env-specific deselect):
venv/bin/python -m pytest tests -q --ignore=tests/test_menu_app.py \
  --deselect "tests/test_log_parser.py::test_find_log_path_error_handling"
venv/bin/python -m pytest tests/test_tracker_combat_winner.py -q

# Run
venv/bin/python -m mtga_tracker.app                 # tracker + dashboard + menu bar
venv/bin/python -m mtga_tracker.app --no-gui        # same, headless in one terminal
venv/bin/python -m mtga_tracker.main
venv/bin/python -m mtga_tracker.dashboard           # http://127.0.0.1:8765 (--port to change)
venv/bin/python -m mtga_deck_downloader

# Inspect / maintain
venv/bin/python -m mtga_tracker.db_audit
venv/bin/python -m mtga_tracker.db_audit --repair
venv/bin/python -m mtga_tracker.draw_quality --card "Llanowar Elves"
venv/bin/python -m mtga_tracker.payload_dump "<game_id>"

# Frontend
(cd ui && npm ci)
(cd ui && npx vitest run)
(cd ui && npx tsc -b && npm run lint)
(cd ui && npm run build)
(cd ui && npm run dev)      # Vite proxies /api to 127.0.0.1:8765 for hot-reload work
```

The full suite is fast; run it after tracker changes. It includes `tests/deck_downloader/`.
UI changes require vitest, tsc, lint, and a fresh `npm run build` (the dashboard serves
`ui/dist`, which is gitignored — rebuild and redeploy `dist` alongside source changes).

## Packaging and Releases

- `scripts/build_macos_app.sh` → `dist/MTGA Tracker.app`; `scripts/build_macos_installer.sh`
  → DMG; `scripts/build_windows_app.ps1` → Windows zip AND `MTGA-Tracker-<ver>-setup.exe`
  (Inno Setup via `packaging/windows_installer.iss`; skipped with a warning when ISCC is
  not installed — CI runs `choco install innosetup`). All go through
  `packaging/mtga_tracker.spec` and `packaging/entrypoint.py`, and embed the
  tag-derived package version in the artifact name. Never change the installer's `AppId`
  GUID — it is what makes newer setups upgrade in place.
- The macOS bundle filename and executable remain `MTGA Tracker` for upgrade
  compatibility, while `CFBundleName`/`CFBundleDisplayName` are `Tapps Tracker`,
  the stable bundle identifier is `com.travispatton.mtgatracker`, and
  `LSUIElement=true` declares the app as a menu-bar utility. A terminal source
  run still belongs to the Python interpreter; use `build_macos_app.sh --fast`
  when testing current source with its native app identity. The fast build is
  for local iteration only and must not be used for a release.
- The macOS BUNDLE and Windows folder each ship one tracker executable; Deck Finder's
  terminal UI is its `--deck-finder` mode. After a build, verify the tracker executable,
  integrated Deck Finder provider list, and terminal mode. Do not expect or add a second
  `MTGA Deck Downloader` executable.
- The build scripts prefer the repo venv and fall back to `$PYTHON`; they build `ui/dist`
  as part of the bundle, so UI changes must be built before packaging.
- The in-game overlay is built by `scripts/build_overlay.sh` / `.ps1` (called from the app
  build scripts) into `overlay/build-out/` — a `Tapps Overlay.app` on macOS, a
  `tapps-overlay.exe` on Windows. The spec ships Windows overlay data under `overlay/`;
  `build_macos_app.sh` copies the macOS app into `Contents/Helpers/` after PyInstaller.
  Linux staging exists in the overlay script, but the spec does not yet bundle it.
  No Rust toolchain → the overlay is skipped with a warning and the Settings
  page reports "not in this build"; CI sets `OVERLAY_REQUIRED=1` so releases always carry
  it. `overlay_launcher.overlay_binary_candidates()` lists every location the tracker looks
  in (env `MTGA_TRACKER_OVERLAY_BIN` overrides). `scripts/build_overlay.sh --fast` (`-Fast`)
  uses the incremental `fast` cargo profile for iteration — seconds instead of a fat-LTO
  relink; never ship it. The macOS shell build scripts source `scripts/node_env.sh`, which
  loads the user's nvm default when Node is absent from a noninteractive shell's `PATH`.
  The overlay's frontend and Rust tests:
  `cd overlay && npm test && cargo test --manifest-path src-tauri/Cargo.toml`.
- `.github/workflows/release.yml` builds both OS artifacts and attaches them to a **draft**
  GitHub Release on a `v*` tag. Manual branch runs upload Actions artifacts; manual tag
  runs use the draft-release path. Publishing the draft is the human "go" button; ordinary
  pushes never run it. There is no separate Python/frontend test workflow in this checkout.
  See `docs/RELEASING.md`.

## Local Paths

Do not hardcode user-specific absolute paths in code or docs intended for general output. The app displays redacted home paths as `~` on macOS/Linux and `%USERPROFILE%` on Windows (`rendering.display_path_without_username`).

Common runtime files:

- Arena log: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log` (macOS) or
  `%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log` (Windows)
- Analytics DB: `data/mtga_tracker.sqlite3` from source; the installed app uses
  `~/Library/Application Support/MTGA Tracker` (macOS) or `%LOCALAPPDATA%\MTGA Tracker`
  (Windows)
- Desktop + Deck AI settings: `settings.json` at the repo top level from source, or the
  installed app data folder for frozen builds
- Deck Finder creators: `deckfinder_config.json` at the repo top level
- Unhandled annotation log: `data/mtga_tracker_unhandled_annotations.log`
- Local card DB source: MTGA `Raw_CardDatabase_*.mtga` under the MTGA install/download folders, or `MTGA_DATA_DIR`.
  On Windows this means every Steam library from `libraryfolders.vdf` plus Epic installs, not
  just the default Program Files path — resolve it through `paths.py`, never a hardcoded root.

Windows is a first-class target: use `pathlib`, quote paths for `cmd`, and prefer pasteable
`%USERPROFILE%`/`%LOCALAPPDATA%` forms over POSIX-only examples in user-facing output.
Background Windows subprocesses launched by the frozen GUI must use
`CREATE_NO_WINDOW`; periodic console tools such as `tasklist` otherwise flash a window above
the user's applications on every poll.

The unified launcher must pass its selected `--db` path to both `CardTracker` and the dashboard.
Never allow those components to silently use separate default databases.

## Tracker Invariants

Preserve these behaviors unless the user explicitly changes requirements:

- Never stop or restart the active tracker or desktop app without explicit user approval. The
  user may be in a live game even when the latest persisted log line appears idle.
- The unified launcher is single-instance across source and installed launches for the same OS
  user. Acquire its OS-owned guard before starting the dashboard, tracker, or tray; keep the
  legacy Qt lock as a cross-version backstop, and never apply the guard to Deck Finder mode.
- On macOS, rely on the tray icon's registered native context menu; manually popping that same
  menu from the activation callback creates a duplicate overlapping menu.
- Perform database inspection read-only first. Use SQLite's online backup API before a live
  repair, and keep the tracker running unless the user explicitly authorizes downtime.
- Restore migrations temporarily enable SQLite WAL mode on the staged snapshot. Before replacing
  the live database, checkpoint the staged WAL and return it to `journal_mode=DELETE`; deleting
  sidecars while leaving a WAL-mode header makes the first read-only summary fail with zero games.
- Console output should be readable and consistent: no emoji/icons in turn log lines or summaries.
- Turn headers are the section boundary; individual log lines should use elapsed match time, not repeated turn labels.
- Stack output should distinguish spells/abilities put on the stack from `[resolved]`, `[countered]`, or inferred no-resolution states.
- Do not show normal single-item stack resolves if they add noise; show stack details when another item is added above an existing item or a spell/ability does not resolve normally.
- Opening hand should be captured whenever a full visible hand is available before gameplay begins, then persisted to `game_opening_hand_cards`.
- SQLite analytics should support future dashboards. Prefer structured tables over stuffing summary text into one blob.
- Game Detail marks Flood for more than 50% post-opening land draws, statistically unusual
  total lands, at least four consecutive land draws, or at least six lands within eight draws.
- The homepage Recent Games table uses that same Flood calculation, shows total turns, and
  combines Lands Seen with a whole-number percentage rounded upward; it does not show
  player/opponent average-turn columns. Its deck colors, and those in All Games and opponent
  history, come from that game's submitted `game_deck_cards` snapshot; deck-level pages use
  the newest submitted revision for the named deck.
- Overview Win Rate Trend uses one compact selector for 1/7/30/60/90 days, all
  time, or the last 10/25/50/100 games (default: 30 days), independent of the
  overview Period and From/To filters. It uses a rolling window of 30 finished
  games, loading earlier history for game-count views; deck and format filters
  apply to both. All time includes the complete recorded history, and axis
  dates show years. Average Win Rate uses only games in the chosen range;
  Low % / High % use complete 30-game rolling windows, with only the
  low, high, latest, and hovered points marked to avoid clutter. The center
  axis label counts only the selected range's games, wins, and losses.
- The Formats table defaults to case-insensitive Format A–Z order. Midweek Magic and Momir are
  excluded in both backend responses and the UI as a safeguard against stale dashboard processes.
- Best Deck = most total wins among decks with a winning record (>=50% WR, min 8 decided
  games); win rate breaks ties. A small hot sample only surfaces when nothing has more wins.
  Rendered as a full-width bar below the overview metric cards, not a metric card.
- The Overview Decks table has no total deck cap: return every deck with recorded
  games matching the current filters, including decks later removed from Arena.
  Arena's active-deck slot limit never truncates tracker history. The UI pages
  ten rows at a time and searches/sorts the complete returned set.
  Decks, All Games and Sessions opt into `SortableTable`'s full pagination controls:
  numbered pages with ellipses, first/last navigation and a validated page jump.
  All Games retains 30 rows per page; sorting and filter changes reset the page.
  Sessions returns every runtime session with games matching the current filters,
  with no total row cap, newest first and 15 rows per page. Its Play / Draw column
  (teal/purple counts of `went_first`) sits before Win Rate and sorts by the draw share.
- Games where the tracker attached mid-game (turn > 1 at first sight) are shown live but never
  persisted (`mid_game_attach` gates `_is_untracked_match`). Midweek Magic and bot matches are
  likewise never persisted.
- Opponent colors come from `cards.color_identity` (backfilled from Arena's local card DB
  at startup and after each game). In Brawl, use the recorded opponent commander identity
  from `participant_commanders` when known, including partner commanders; otherwise use
  revealed cards from `game_card_summary`. Other formats use revealed cards. Combo names
  come from `colors.py`; color summaries omit games with neither source available.
- Arena "Imported Deck" placeholder names are canonicalized at startup to the real deck name
  when another game shares the exact maindeck (`canonicalize_imported_deck_names`).
- Card Drill-Down persistently uses the same Scryfall full-card image loader as card hover
  previews; deck thumbnails continue using cropped artwork.
- Mana costs: Arena's log never states them, so the PRIMARY source is Arena's local card DB —
  `CardDatabase.mana_cost_index_by_name()` probes the Cards table for a cost column (schema
  varies; `parse_arena_mana_cost` handles GRE pip text `o2oBoB`, old-school `2BB`, and braced
  forms, refusing rather than guessing) and `AnalyticsStore.backfill_card_mana` fills
  `cards.mana_cost`/`mana_value` at startup and game end, exactly like color identities.
  Payloads ship a `card_mana` name→cost map (deck + game); the UI seeds its cache from it and
  only falls back to Scryfall's batched `/cards/collection` for gaps (`ui/src/manaCosts.ts`,
  localStorage-cached, dash when unresolvable). Symbols render OFFLINE from the bundled
  mana-font package (class = braces/slashes stripped, lowercased: `{G/W}` → `ms-gw`) — never
  hotlink symbol images. The deck page's Mana column, type-count boxes, and both pages'
  "Mana value / card played" + "Mana spent / turn" rows (Combat & Resources → Cards;
  printed costs, lands excluded, X = 0) build on this; the deck payload also ships raw
  per-seat inputs via `played_mana` (play totals + turns from `games.player_turns`/
  `opponent_turns`). `scripts/probe_mtga_card_db.py` verifies the cost column/format against
  a real Arena install. Printed power/toughness follow the same pattern
  (`CardDatabase.stats_index_by_name` → `AnalyticsStore.backfill_card_stats`, both call
  sites): the console-label parser never sees a 0-power creature (Arena encodes a zero stat
  as `{}`; `_extract_stat_value`/`stat_value` read that as 0), so never rely on display
  names for stats, and replay rows for creatures carry `power`/`toughness`.
- The product's display name is **Tapps Tracker** (`ui/src/branding.ts`, `PRODUCT_NAME`);
  the sidebar brand uses the dashboard heading typography, links to the very top of Overview,
  and displays local vector W/U/B/R/G mana symbols rather than upscaled raster icons. Browser
  tab titles use `Tapps Tracker – <page>`. App bundle names, commands, and data folders still
  say `MTGA Tracker` on purpose (renaming them moves users' data).
- Scry stats persist for both seats (`scries`, `scry_cards`, `scry_top`, `scry_bottom`)
  and `game_library_events`; `affectedIds` contains card instance IDs, so resolve the
  scrying seat from the ability controller or observed card owners. Opponent card names
  stay hidden. Migration 29 backfills historical event counts only. Surveil columns remain
  NULL until a handler exists. The overlay does not condition odds on scry top/bottom order.
- Replay: readers of printed history (`game_detail` timeline, `live_api` events, backfills,
  audit) filter `game_events.visible = 1`; silent rows never reach the console or the
  timeline. Every game with events gets a replay (recorded or reconstructed); mid-game
  attaches and untracked modes get none. The capture hook adds no parsing pass and no
  per-row commit, and must never block live tracking.
- Unhandled annotations go to the text diagnostics log, not SQLite.
- AI deck identification starts at most ONE identification job per game, only after the game
  completes, only for tracked matches, and always on a background thread. Normally it makes
  one request; the existing OpenAI token-starvation retry is the sole exception. The result lands in
  `participants.deck_archetype`; Game Detail shows it as the Opponent Deck Type with the plain
  color label as fallback. Keep calls cheap — no extra calls, no retries beyond the existing
  token-starvation retry.
- Brawl: commanders for both seats persist to `participant_commanders`; starting life is 25.
  Queue labels: Play_Brawl_Historic → "Historic Brawl", Brawl_Ladder → "Brawl (Ranked)",
  Play_Brawl → "Standard Brawl"; MWM_Brawl resolves to Midweek Magic FIRST (untracked). A
  queue identifier always outranks deck metadata: a deck's Format ATTRIBUTE
  ("HistoricBrawl"/"HistoricBrawlRanked") describes the deck, not the queue, and must never
  relabel a match whose format already normalizes to a Brawl queue.
- Cube event IDs such as `CubeDraft_Powered_20260908` are authoritative queue metadata,
  normalize to **Powered Cube**, and count as explicit non-Brawl formats even when Arena exposes
  a populated command zone. They outrank the deck's generic `Draft` format attribute.
- The Overview's Brawl section (record strip, Best Commander / Toughest Opponent Commander
  art boxes, Your/Faced Commanders tables paged at 8) is always rendered with an empty state
  and has its own nav entry. Brawl is recognized from the match format, never from deck size.
  The commander is absent from Arena's submitted maindeck, so deck pages and exports add it
  back (`Commander` export section; Games Seen 100%). The Formats table groups per-set
  limited entries ("Premier Draft - MSH") under an expandable base row.
- Expected Lands uses the decklist submitted for that game; a game without one borrows the
  same deck's nearest submitted list (`land_rate_source: deck_history`); only a deck with no
  list anywhere falls back to the size heuristic (`estimate`, labelled "est." in the UI).
  The deck page's ratio is the newest decklist's lands / size.
- Opponent mulligans come from Arena's `players[].mulliganCount`, which is reported for both
  seats (`_observe_player_mulligans`, `GameState.mulligan_count_by_seat`); the opponent's
  count persists to `participants.mulligans` and the game page shows "Mulligans (You / Opp)".
  The player's own count still comes from the mulligan-prompt tracking.
- Opponents: `top_opponents`, `opponents_list`, and the opponent page count a Bo3 match once
  (grouped by `match_id`, `SUM(mw > ml)`); the UI rolls Bo3 games into one expandable row.
- Constructed Ranked lifetime and season match stats include `Brawl_Ladder` (Competitive
  Brawl), because its rank changes are constructed rank snapshots. Unranked Brawl queues
  remain excluded; a Bo3 match still counts once.
- Format quick filters are two-tier (`ui/src/quickFilters.ts`: `FORMAT_FAMILIES` with
  refinements; legacy ids normalized by `normalizeQuickFilterId`). Recent Games and All Games
  share `FormatQuickFilters`; All Games has no format dropdown or deck search box.

## MTGA Log Gotchas

Arena logs are not a simple chronological event stream. Be careful with inferred ordering and ownership.

- Local player seat can be stale or unknown early in a match. A complete visible hand identifies the local player; opponent hand is hidden.
- Seat IDs can change between games. Never assume the local player is seat 1.
- Re-resolve the format for every game from the latest active match-room metadata. Never carry
  a scene/event hint across games or map missing format metadata to a guessed queue.
- Unknown event identifiers from match-room `eventId`, EventLanding context, or the outgoing
  `EventSetDeckV3` request are authoritative: preserve the raw id, derive a readable fallback label,
  and never let deck attributes, `DeckUpsert`, or command-zone inference replace it. Persist
  `matches.queue`/`event_name` only from that authoritative event signal.
- Winner detection must validate against the local player seat. Concession/disconnect messages are especially easy to invert.
- Partial `PlayerStatus_InGame` diffs never identify a winner. Read every GRE
  message in a batch; explicit terminal game results outrank LossOfGame
  annotations, which outrank terminal PendingLoss status hints. A valid
  LossOfGame annotation identifies the losing seat and can close a game without
  the usual final result. Life totals must not reverse an identified winner;
  unresolved positive-life endings stay Unknown. Apply broad defeat/forfeit
  text heuristics only to non-JSON entries so card names cannot end a game.
- Costs can appear before/after the ability text in raw log order. For activated abilities, paid costs such as discard/tap should be associated with the activation.
- MTGA uses last-in-first-out stack resolution. A card can be cast/activated, then another spell/ability can be added above it and resolve first.
- State-based actions may appear as zone transfers with categories like zero toughness or zero loyalty. These should be user-visible when they explain a death/removal.
- Some effects are only visible through zone movement and object snapshots, not through clear English annotations.
- Copy/transform state may require tracking object state changes, not only card names. Example: `Likeness Looter` can become a copy of a graveyard creature.
- Brawl queues are indistinguishable in match-room metadata: Arena stamps every
  Historic-pool Brawl match's room with eventId `Play_Brawl_Historic` regardless of the
  queue that created it. The authoritative queue signal is the `EventSetDeckV3` join
  (`EventName: Brawl_Ladder` for cBrawl), and Arena's deck attributes use "HistoricBrawl*"
  naming everywhere — never infer the queue from them (substring 'historicbrawl' inside
  'HistoricBrawlRanked' has mislabeled real cBrawl matches twice).
- Log timestamps are locale-formatted: day-first locales write `dd/mm/yyyy`. The parser
  (`log_timestamp.py`) learns the order from unambiguous entries with a system-locale
  fallback; storage is always ISO. Never parse a log date with a fixed `%m/%d` order
  (pre-0.5.5 did, and migration v21 repairs the month/day-swapped rows it stored).
- The deck a game is attributed to comes from course-candidate scoring, and the decklist
  actually submitted to the game is the trump card: a candidate that contradicts the
  submitted 60 must never win (a tracker launched mid-queue after a deck switch once
  stamped games with the previous deck's name). Leaving the deck unresolved beats
  guessing wrong.
- A land that chooses a basic land type as it enters (Multiversal Passage) logs
  `AnnotationType_ChoiceResult` from the land (`Choice_Domain` 9, `Choice_Value` an
  Arena SubType enum) one message before its PlayLand; the land object then carries
  the choice in `subtypes` (`SubType_Mountain`) and has no `color`. The tracker
  remembers the chooser (`GameState.land_type_choosers`) and reads the type from
  `subtypes`, so printed land types (Sacred Foundry) are never shown as a choice.
- Arena's SBA death annotations reference instance ids that do NOT match declared
  attacker/blocker ids (verified against real logs) — combat deaths cannot be told apart
  from burn kills at SBA time, which is why lethal-damage deaths are excluded from
  "lost to removal" and why attackers_lost/blockers_lost membership checks miss.

## Analytics DB

Keep schema changes backward-compatible. Use nullable columns and migration helpers when possible.

Important tables:

- `tracker_sessions`: one tracker runtime session, from launch to quit; a new match
  starting the session break (Settings → Sessions, `settings.json` `sessions.break_hours`,
  default 4, 0 = off; measured in log time) after the last game, or after launch when
  nothing has been played, starts a new one (`tracker_lifecycle._start_new_session_after_break`).
  Game 2+ of a Bo3 never starts one.
- `matches`: match grouping within a session.
- `games`: one game result, duration, total turns, player/opponent turn counts, winner/outcome.
- `participants`: player/opponent seat, deck metadata, life, opening hand size, mulligans.
- `game_opening_hand_cards`: one row per card in the player's opening hand.
- `game_drawn_cards`: one row per visible player/opponent drawn card identity when Arena exposes it.
- `game_deck_cards`: authoritative per-game submitted main-deck and sideboard quantities from Arena.
- `game_card_summary`: cards played by each participant.
- `game_library_events`: per-seat scry choices, destination counts, source card, and
  visible player card-name lists; see `docs/MTGA_LOG_FORMAT.md`.
- `game_participant_stats`: combat, damage/life, cards drawn/discarded/milled/exiled, stack
  stats, plus nullable interaction columns added over time — removal/wipes/bounce/counters
  played+drawn, creatures/non-creatures removed and bounced, spells_countered, lands
  lost/replaced, tokens created/destroyed/sacrificed/exiled, poison_added. Convention:
  NULL means "not tracked when this game was recorded" and renders as a dash — a backfill
  or the live tracker writes real zeros. Opponent `*_drawn` columns stay NULL forever
  (hidden information).
- `game_turns`: observed turn start/end timestamps and duration by active seat; `timing_source`
  distinguishes exact `live` rows, exact `recovered_previous_turn_logs` rows restored from
  durable console headers, and `estimated_header_events` historical backfills.
- `game_events`: the per-game event log. Printed rows (`visible = 1`) are the console
  lines; recorded games (`games.replay_version = 1`) also carry structured replay fields
  (`event_subtype` kind, `object_id`/`target_object_id` root instance ids, `arena_id`,
  `controller_seat`, zones, `amount`, `payload_json`) and silent replay-only rows
  (`visible = 0`, `game_id` only). Migration 32 makes the session index partial over
  printed rows. See `docs/REPLAY_FORMAT.md`.
- `console_logs`: rendered console log lines for later dashboard/query work. Also feeds the
  dashboard's Live Scoreboard page (`/api/live` in `live_api.py`, `since` = `console_logs.id`).
- `live_status`: single-row (id=1) "what is happening right now" snapshot the tracker upserts
  with every console line plus a ~5s idle heartbeat; drives the Live Scoreboard. Stopping the
  tracker calls `mark_live_status_stopped` (rewinds `updated_at`, `in_game=0`) so the
  dashboard flips to off at once; `last_game_json` freezes the final in-game snapshot so the
  previous game's scoreboard survives reloads until the next game starts. `overlay_json`
  persists the library state served by `/api/overlay`; it stays current in untracked modes too.
  The old Qt log
  window is a buried debug fallback (`MTGA_TRACKER_QT_LOG=1`).
- `participant_commanders`: Brawl commander(s) per participant (both seats).
- Indexes: besides the `(game_id, participant_id)` pairs, the per-card tables carry
  `participant_id`-only indexes, `game_deck_cards(participant_id, deck_zone)`,
  `game_card_summary(participant_id)`, `participants(role, deck_name)`, and `games(match_id)`.
  They live in the schema baseline (`CREATE INDEX IF NOT EXISTS`), so existing databases
  pick them up at the next launch. A dashboard query that filters by `participant_id` or
  `match_id` alone must use them — that was the difference between 800 ms and 200 ms on the
  overview at ~1000 games.
- `raw_game_payloads`: sanitized raw payload archive. `payload_json` is stored
  **zlib-compressed** (migration v11 converted legacy rows) — always read it through
  `payload_codec.decode_payload`, or use `python -m mtga_tracker.payload_dump <game_id>`;
  raw SQL shows blobs. Payloads are lossless while retained, but startup maintenance
  prunes this diagnostic archive after 30 days; never assume arbitrary old raw games exist.
- `rank_snapshots`: constructed and limited rank changes by season, with optional ranked match/game linkage.
- `game_annotations`: user notes and comma-joined tags per game, written by
  `POST /api/game/annotation`. Analytics query endpoints remain read-only GETs.
  `POST /api/db/reset` is destructive, requires `{"confirm": "RESET"}`, and backs up first.
  Other existing POSTs are `/api/settings/*` (settings and overlay actions),
  `/api/deckfinder/*` (fetch/variants/hydrate/surprise jobs),
  `/api/deck-downloader/launch` (terminal launcher), and `/api/collection/export`
  (explicit memory scan/export job). Do not describe the entire dashboard as read-only.
- `schema_migrations`: numbered one-time migrations applied by `AnalyticsStore.apply_pending_migrations`
  (baseline is version 1; add new migrations there rather than ad-hoc ALTERs when possible).

When adding stats, persist both player and opponent perspectives when the log can support it.

Shared draw-quality math (hypergeometrics, land runs, per-game metrics) lives in `draw_quality.py`
and is decklist-aware; the dashboard and CLI must both use it rather than reimplementing rates.

Use `format_normalizer.py` for queue labels and best-of inference. Do not duplicate string-matching format logic in tracker mixins or reports.

Run `mtga_tracker.db_audit` after suspected tracker inconsistencies. Safe repairs currently include format/queue mismatches, turn-count aggregate mismatches, reconstruction of completed games missing their core row, timestamp-based game-event reassignment, and deletion of empty unknown-result game artifacts; unresolved deck names and `Card #...` labels are reported for manual follow-up.

The analytics writer uses WAL mode, a busy timeout, and bounded retries so dashboard reads or
development-time reloads do not drop end-game writes. Missing exact turn timings are recovered
from persisted `Previous Turn` console headers at startup and by `db_audit --repair`.

## Testing Expectations

Add or update regression tests for every parser/state-machine bug. Prefer focused tests that build minimal game-state payloads rather than replaying huge logs.

For dashboard UI changes, run both the Python tests and the frontend test/build commands. Keep the frontend app isolated under `ui/`; do not move tracker runtime behavior into the frontend.

For overlay changes, run `cd overlay && npm test && npm run build` and `cargo test` in
`overlay/src-tauri`; `node scripts/screenshots.mjs` renders the rail/panel/flyout states
against fixture payloads for a visual check (`overlay/shots/`, gitignored). The macOS and
Windows-specific Rust (`arena.rs`, the `cfg(target_os)` blocks) only compiles on those
platforms — CI builds both.

High-risk areas needing tests:

- Winner/loss/concession detection.
- Opening hand and mulligan capture, especially stale seat correction.
- Draw/discard/mill/exile/life/damage stats for both sides.
- Stack ordering, countered/fizzled spells, and ability costs.
- Per-turn timing and final player/opponent time totals.
- State-based actions and zone transfers.
- Copy-state/transform handling.
- SQLite persistence for new summary fields.

## Coding Guidance

- Keep changes localized; `tracker.py` should remain a thin composition class. Put behavior in the focused `tracker_*` mixin that owns that responsibility.
- Avoid recreating a new monolith. If a tracker module grows well past ~800 lines, split it by responsibility before adding more behavior.
- Prefer robust inference from MTGA data over string matching console output.
- Preserve existing user-facing formatting unless the user requested a change.
- When adding a new event type, update summary stats and DB persistence if it affects analytics.
- If a log annotation is unknown, write a diagnostic to `data/mtga_tracker_unhandled_annotations.log` and avoid noisy UI output.
- Do not introduce network dependencies for normal card resolution when the local MTGA card DB can provide the data.
- Python is formatted with black at line length 100 (`[tool.black]` in `pyproject.toml`) and
  targets Python 3.9+; avoid syntax newer than that. TypeScript must pass `tsc -b` and eslint.
- Record user-visible changes in `CHANGELOG.md` under the release being prepared — the
  changelog is part of the release, not an afterthought. Never bump a version in code: the
  `v*` tag is the version, and only the user cuts one.
- Never commit generated or local-only files: `ui/dist/`, `data/*.sqlite3*`, `config.py`,
  `settings.json`, and `.claude/` are all gitignored on purpose.
