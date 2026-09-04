# AGENTS.md

Guidance for coding agents working on this MTGA tracker. Keep this file current when tracker behavior, database schema, or test commands change.

This is the single source of truth for agent instructions — there is deliberately no
`CLAUDE.md`; do not add one.

## Project Overview

This is a Python log-only tracker for Magic: The Gathering Arena. It tails MTGA `Player.log`, parses GRE game-state messages, prints a readable console log, and persists dashboard-friendly analytics to SQLite. A React/TypeScript dashboard (`ui/`) is built to static assets and served by the Python dashboard server — there is no separate web backend, no account, and no cloud.

Repo layout:

- `src/mtga_tracker/`: tracker runtime, analytics store, dashboard server, desktop app.
- `src/mtga_deck_downloader/`: the bundled Deck Finder companion tool.
- `ui/`: React/Vite dashboard frontend (built to the gitignored `ui/dist`).
- `tests/`: pytest suite, including `tests/deck_downloader/`. `tests/deprecated/` holds
  non-test debug scripts and is not part of the suite.
- `packaging/` + `scripts/`: PyInstaller specs, entry points, and OS build scripts.
- `docs/`: log-format reference, research notes, and the removal ledger; `docs/plans/` holds
  design and release plans together with their mockups (mockup images live there, not in
  `docs/images/`, which is for README screenshots). `CHANGELOG.md` tracks releases.
  The version comes from the git tag (setuptools-scm writes `_version.py`); there is no
  hand-edited version string anywhere, and a release is cut by pushing a `v*` tag. Never
  bump or invent a version in code.

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
  the tracker thread and the dashboard server, with or without the GUI (`--no-gui`).
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
- `src/mtga_tracker/format_normalizer.py`: single source of truth for raw queue/format labels and best-of inference.
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
- `src/mtga_tracker/live_api.py`: `/api/live` payload — current game, frozen previous-game
  scoreboard, records vs. deck / opponent / opponent commander, local archetype guess.
- `src/mtga_tracker/draw_quality.py`: CLI/report helpers for land flood/screw and repeated-card draw audits.
- `src/mtga_tracker/tracker_summary.py`: end-game and session summary rendering.
- `src/mtga_tracker/tracker_rendering.py`: console formatting, actor labels, mana/text cleanup, runtime strings.
- `src/mtga_tracker/tracker_state_lookup.py`: object snapshots, identity/copy-state, card type, zone/seat lookup helpers.
- `src/mtga_tracker/tracker_diagnostics.py`: unhandled annotation and parser diagnostics text logging.
- `src/mtga_tracker/card_database.py`: MTGA/Scryfall card ID to card name/type resolution, plus
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
- `src/mtga_tracker/settings.py`: shared `settings.json` — top level of the repo next to
  `config.py` for source runs, per-user data dir for frozen builds (legacy `data/settings.json`
  migrates automatically).
- `src/mtga_tracker/settings_dialog.py`: PyQt Settings dialog (menu bar → Settings…) that writes
  the "deck_ai" section of `settings.json`.
- `src/mtga_tracker/deck_downloader_launcher.py`: launches the bundled Deck Finder in a sized
  terminal window (menu bar item and `POST /api/deck-downloader/launch` from the dashboard).
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
cd ui && npm install
cd ui && npx vitest run
cd ui && npx tsc -b && npm run lint
cd ui && npm run build
cd ui && npm run dev        # Vite proxies /api to 127.0.0.1:8765 for hot-reload work
```

The full suite is fast; run it after tracker changes. It includes `tests/deck_downloader/`.
UI changes require vitest, tsc, lint, and a fresh `npm run build` (the dashboard serves
`ui/dist`, which is gitignored — rebuild and redeploy `dist` alongside source changes).

## Packaging and Releases

- `scripts/build_macos_app.sh` → `dist/MTGA Tracker.app`; `scripts/build_macos_installer.sh`
  → DMG; `scripts/build_windows_app.ps1` → Windows zip AND `MTGA-Tracker-<ver>-setup.exe`
  (Inno Setup via `packaging/windows_installer.iss`; skipped with a warning when ISCC is
  not installed — CI runs `choco install innosetup`). All go through
  `packaging/mtga_tracker.spec` and the `packaging/*_entrypoint.py` shims, and embed the
  `pyproject.toml` version in the artifact name. Never change the installer's `AppId`
  GUID — it is what makes newer setups upgrade in place.
- The macOS BUNDLE embeds BOTH executables ("MTGA Tracker" and "MTGA Deck Downloader")
  in `MTGA Tracker.app/Contents/MacOS/` — the DMG intentionally shows one app and the
  Deck Finder ships inside it. After a macOS build, verify both binaries are present
  (`ls "dist/MTGA Tracker.app/Contents/MacOS/"`) and that the menu-bar Deck Finder
  launch opens a Terminal with all providers listed.
- The build scripts prefer the repo venv and fall back to `$PYTHON`; they build `ui/dist`
  as part of the bundle, so UI changes must be built before packaging.
- `.github/workflows/release.yml` builds both OS artifacts and attaches them to a **draft**
  GitHub Release on a `v*` tag or manual dispatch. Publishing the draft is the human "go"
  button; ordinary pushes never run it. See `docs/plans/RELEASE_PLAN.md`.

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

The unified launcher must pass its selected `--db` path to both `CardTracker` and the dashboard.
Never allow those components to silently use separate default databases.

## Tracker Invariants

Preserve these behaviors unless the user explicitly changes requirements:

- Never stop or restart the active tracker or desktop app without explicit user approval. The
  user may be in a live game even when the latest persisted log line appears idle.
- On macOS, rely on the tray icon's registered native context menu; manually popping that same
  menu from the activation callback creates a duplicate overlapping menu.
- Perform database inspection read-only first. Use SQLite's online backup API before a live
  repair, and keep the tracker running unless the user explicitly authorizes downtime.
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
  player/opponent average-turn columns.
- The Formats table defaults to case-insensitive Format A–Z order. Midweek Magic and Momir are
  excluded in both backend responses and the UI as a safeguard against stale dashboard processes.
- Best Deck = most total wins among decks with a winning record (>=50% WR, min 8 decided
  games); win rate breaks ties. A small hot sample only surfaces when nothing has more wins.
  Rendered as a full-width bar below the overview metric cards, not a metric card.
- Games where the tracker attached mid-game (turn > 1 at first sight) are shown live but never
  persisted (`mid_game_attach` gates `_is_untracked_match`). Midweek Magic and bot matches are
  likewise never persisted.
- Opponent deck colors come from `cards.color_identity` (backfilled from Arena's local card DB
  at startup and after each game) aggregated over `game_card_summary`; combo names come from
  `colors.py`. Color tables drop the bucket for games with no revealed opponent cards.
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
  a real Arena install.
- The product's display name is **Tapps Tracker** (`ui/src/branding.ts`, `PRODUCT_NAME`);
  the sidebar brand uses the dashboard heading typography, links to the very top of Overview,
  and displays local vector W/U/B/R/G mana symbols rather than upscaled raster icons. Browser
  tab titles use `Tapps Tracker – <page>`. App bundle names, commands, and data folders still
  say `MTGA Tracker` on purpose (renaming them moves users' data).
- Unhandled annotations go to the text diagnostics log, not SQLite.
- AI deck identification makes at most ONE provider call per game, only after the game
  completes, only for tracked matches, and always on a background thread. The result lands in
  `participants.deck_archetype`; Game Detail shows it as the Opponent Deck Type with the plain
  color label as fallback. Keep calls cheap — no extra calls, no retries beyond the existing
  token-starvation retry.
- Brawl: commanders for both seats persist to `participant_commanders`; starting life is 25.
  Queue labels: Play_Brawl_Historic → "Historic Brawl", Brawl_Ladder → "Brawl (Ranked)",
  Play_Brawl → "Standard Brawl"; MWM_Brawl resolves to Midweek Magic FIRST (untracked). A
  queue identifier always outranks deck metadata: a deck's Format ATTRIBUTE
  ("HistoricBrawl"/"HistoricBrawlRanked") describes the deck, not the queue, and must never
  relabel a match whose format already normalizes to a Brawl queue.
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
- Format quick filters are two-tier (`ui/src/quickFilters.ts`: `FORMAT_FAMILIES` with
  refinements; legacy ids normalized by `normalizeQuickFilterId`). Recent Games and All Games
  share `FormatQuickFilters`; All Games has no format dropdown or deck search box.

## MTGA Log Gotchas

Arena logs are not a simple chronological event stream. Be careful with inferred ordering and ownership.

- Local player seat can be stale or unknown early in a match. A complete visible hand identifies the local player; opponent hand is hidden.
- Seat IDs can change between games. Never assume the local player is seat 1.
- Re-resolve the format for every game from the latest active match-room metadata. Never carry
  a scene/event hint across games or map missing format metadata to a guessed queue.
- Winner detection must validate against the local player seat. Concession/disconnect messages are especially easy to invert.
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
- Arena's SBA death annotations reference instance ids that do NOT match declared
  attacker/blocker ids (verified against real logs) — combat deaths cannot be told apart
  from burn kills at SBA time, which is why lethal-damage deaths are excluded from
  "lost to removal" and why attackers_lost/blockers_lost membership checks miss.

## Analytics DB

Keep schema changes backward-compatible. Use nullable columns and migration helpers when possible.

Important tables:

- `tracker_sessions`: one tracker runtime session.
- `matches`: match grouping within a session.
- `games`: one game result, duration, total turns, player/opponent turn counts, winner/outcome.
- `participants`: player/opponent seat, deck metadata, life, opening hand size, mulligans.
- `game_opening_hand_cards`: one row per card in the player's opening hand.
- `game_drawn_cards`: one row per visible player/opponent drawn card identity when Arena exposes it.
- `game_deck_cards`: authoritative per-game submitted main-deck and sideboard quantities from Arena.
- `game_card_summary`: cards played by each participant.
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
- `game_events`: structured event history where available.
- `console_logs`: rendered console log lines for later dashboard/query work. Also feeds the
  dashboard's Live Scoreboard page (`/api/live` in `live_api.py`, `since` = `console_logs.id`).
- `live_status`: single-row (id=1) "what is happening right now" snapshot the tracker upserts
  with every console line plus a ~5s idle heartbeat; drives the Live Scoreboard. Stopping the
  tracker calls `mark_live_status_stopped` (rewinds `updated_at`, `in_game=0`) so the
  dashboard flips to off at once; `last_game_json` freezes the final in-game snapshot so the
  previous game's scoreboard survives reloads until the next game starts. The old Qt log
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
  raw SQL shows blobs. Lossless, so historical backfills stay possible.
- `rank_snapshots`: constructed and limited rank changes by season, with optional ranked match/game linkage.
- `game_annotations`: user notes and comma-joined tags per game, written by the dashboard's
  `POST /api/game/annotation` endpoint — the only endpoint that writes analytics data. The
  dashboard's other POSTs are `POST /api/db/reset` (destructive; requires a
  `{"confirm": "RESET"}` body and takes a backup first) and
  `POST /api/deck-downloader/launch` (spawns the Deck Finder locally). Everything else the
  dashboard serves is read-only GET; keep it that way.
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
