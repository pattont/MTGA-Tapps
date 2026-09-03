# Changelog

## 0.6.1

- **Renamed to Tapps Tracker** everywhere you see it (menu bar, dashboard,
  window titles). App bundles, commands, and data folders are unchanged, so
  nothing moves on your machine.
- **Brawl: commanders everywhere.** Game pages open with a commander-vs-
  commander strip and the Opening Hand names your commander (hover for the
  card); deck pages use the commander as the deck's signature art, add a slim
  commander banner above the decklist, and list the Opponent Commanders you've
  faced with your record against each. The overview's Brawl section is always
  visible (own nav entry) with Best Commander and Toughest Opponent Commander
  boxes backed by card art.
- **Brawl: decklists include the commander.** Arena's submitted maindeck
  leaves the commander out, so a Brawl list now shows all of its cards; Arena
  exports gain a `Commander` section, and the commander's Games Seen is 100%
  — it is in the command zone every game. Scoreboard colors seed from the
  commander the moment it is revealed. (Brawl is recognized from Arena's
  match format, never from deck size.)
- **Fixed: Expected Lands used a flat 40% heuristic** on the game page and an
  older decklist version on the deck page. The game page now uses the
  decklist submitted for that game (or the deck's nearest one); the deck page
  uses the newest decklist's land ratio; the label says `est.` only when no
  decklist exists at all.
- **Draw Quality reworked.** Game page: Total Cards Drawn, Total Cards Seen,
  Lands Drawn, Lands Seen, Expected Lands, Longest Land Streak, Draw Status on
  one line, land percentages in the labels. The 8-draw-window and low-land-
  drought boxes are gone — the flood/screw evidence line already says it in
  words. Deck page shows per-game land averages with the share beside each
  label.
- **Opponent mulligans are tracked.** Arena reports mulligans for both seats;
  the game page Mulligans box reads You / Opp. Games tracked before this
  release show a dash for the opponent.
- **Bo3 matches count once** in opponent counts and the opponents list; the
  opponent page rolls each match into one expandable row with a Matches card.
  All Opponents is its own page with a back link, a search box that shows the
  count, and gold focus rings on every filter control.
- **Two-tier format filters** on Recent Games and All Games: family pills
  (Standard, Historic, Modern, Pioneer, Timeless, Limited, Brawl, Events) with
  fly-out queue and Bo1/Bo3 refinements. All Games drops the redundant format
  dropdown and search box, widens the deck picker, and shows 30 rows.
- **Deck AI transparency.** Settings, the Settings dialog, and the README now
  state exactly what the API key is used for: one small request per completed
  game, after the game ends, containing only the names of the cards your
  opponent revealed — never your deck, account, or log. Scoreboard colors and
  the mid-game deck label are computed locally and never use the key.
- Live Log is now **Live Scoreboard**; the scoreboard keeps the previous game
  up across reloads with a "Waiting for next match…" pill; Stop Tracking shows
  as stopped immediately; Deck Finder pills stay lit for the current results.
- **Fixed: blank opponent color pips** — the color index no longer caches an
  empty result when the analytics database is busy at startup, and it reads
  Arena's renamed Localizations table.
- Release workflow actions bumped to their Node 24 majors; `macos-debug.md`
  documents the macOS "icon shudders and quits" launch failure and its fix.

## 0.6.0

- **Live Scoreboard.** During a game the `/live` page shows your lifetime and
  today's record with the current deck, head-to-head record against the
  opponent, lands played per side, a ramp-aware draw-quality strip, a per-turn
  timer, your rank on ranked queues, and a best guess at the opponent's
  archetype from their revealed cards (matched locally against earlier
  identified games — no network). Between games the previous game's final
  scoreboard stays up with a Previous Game chip showing the result.
- **Opponents.** New Opponents section on the overview: your five most-faced
  opponents with records, plus your record by opponent color combination —
  and a searchable Opponents page listing everyone you've ever been paired
  against.
- **Fixed: a handful of games recorded you as your own opponent.** A
  migration cleans up the historical rows.
- **Removal accuracy overhaul.** Removal, wipe, bounce, and counter
  classification audited against the card pool: edicts count as removal,
  graveyard hate and hand disruption do not, land destruction is excluded,
  temporary exile counts, and conditional sweepers are judged by outcome (a
  board wipe only when they actually cleared the board). Three migrations
  recount every historical game; `docs/REMOVAL_CLASSIFICATION.md` records
  every ruling.
- Play/Draw and mulligan badges replace the old Mulligans column on Recent
  Games and All Games; All Games gains a Colors column; single gold focus
  rings on filter controls; consistent section spacing throughout.
- **Fixed:** stopping the tracker from the menu bar now flips the dashboard's
  tracker state to off immediately; the All Opponents page no longer errors
  on load.
- Restart the tracker after updating — migrations run at startup.

## 0.5.9.2

- **Fixed: exports could grab a deck instead of your collection.** Arena keeps
  deck objects in memory that look exactly like a collection block, and the
  scanner could return one (34 cards exported instead of thousands). Candidate
  blocks are now gathered across all of Arena's memory and the largest valid
  one wins; deck-sized blocks are rejected outright.
- **Fixed: missing set codes on non-default installs.** The export now finds
  Arena's card database via the install path Arena announces in its own log,
  so set codes fill in on any install location — and if the database still
  can't be found, the export says so instead of quietly shrinking.
- **New: Export for Archidekt.** A fourth export format whose Scryfall ID
  column removes all import ambiguity (Moxfield reads it too). IDs resolve
  through Scryfall's batch API with fallbacks for Arena's mismatched
  collector numbers (Alchemy sets, special prints), then cache locally so
  repeat exports are instant and offline.
- Card names no longer carry Arena's `<nobr>` markup in exports.

## 0.5.9.1

- **Fixed: collection export crashed on Windows** with "int() argument must
  be a string … not 'NoneType'". Windows reports the first memory region at
  address zero, which the scanner mishandled before reading a single byte —
  the export never worked on Windows until now. macOS was unaffected.
- **Release versions now come from the git tag** (setuptools-scm). The app,
  installers, and dashboard all derive their version from the `v*` tag the
  release was built from — no hand-edited version strings anywhere.

## 0.5.9

- **Ramped and searched lands now count in Lands Seen.** A land pulled from
  your library straight onto the battlefield — Lumbering Worldwagon fetching a
  basic, Cultivate, fetch lands, and the like — used to vanish from every land
  count because it was never "drawn." It now shows up in Total Lands Seen for
  both live games and, via a one-time backfill of your history, past ones.
- **Fetched lands no longer read as flood, but still protect against screw.**
  A land you searched out on purpose was not drawn against your will, so it is
  excluded from the flood side of the flood/screw math — ramp-heavy decks stop
  reading as flooded just for doing what they do. Screw keeps those lands,
  because a land you have (even a fetched one) is still mana in play and makes
  a mana-screw reading correctly less likely.
- **Export your MTGA collection** from the Settings page — three buttons
  (`.json`, `.csv`, `.txt`) that read your full card collection out of the
  running game and write a file you can import into Moxfield and similar
  sites. Arena must be running with the collection loaded (open the Decks
  tab once); on macOS an administrator prompt appears, since reading another
  app's memory needs elevated access. Anchors are derived automatically from
  your own tracked decklists — nothing to type — and a second export within
  a few minutes reuses the first scan (no repeat prompt). Extraction
  technique adapted from
  [NthPhantom10's MTGA-collection-exporter](https://github.com/NthPhantom10/MTGA-collection-exporter).

## 0.5.8

- **Live Log is now the Scoreboard** — the old Qt play-by-play window is
  replaced by a live page in the dashboard (`#/live`): a hero scoreboard with
  both life totals, color pips, and deck name, a friendly format chip, the turn
  and game clock, and Brawl commander art with hover previews. Below it, a Live
  Feed that renders through the exact same timeline component as the `/game`
  page (so it reads identically), the current game's play-by-play, a retained
  "Previous Game" between matches with a closing "Game ended" banner, a session
  rail (record, runtime, live/ready status), and a scrolling Today's Games list.
  The Qt window is now a buried debug fallback (`MTGA_TRACKER_QT_LOG=1`).
- **Deck Finder moved into the dashboard** — no more separate terminal window.
  Pick a site then a format, browse a per-site results table (win rates for
  untapped.gg, event placings for tournament sites, and so on), open any deck to
  export it to Arena or jump to the source, or hit "Surprise Me". Creator lists
  moved to the Settings page.
- **Settings is now a dashboard page** (`#/settings`, gear icon on every page):
  Deck AI configuration, Deck Finder creators, a tracker-status readout
  (monitoring/card DB/log DB/version), a single sun/moon theme toggle, and the
  Database Health link — all in the web UI. The old Qt dialog remains as a
  fallback.
- **Colorless is a color**: the colorless diamond ("C") now shows wherever
  colors do — Recent Games, the Decks table, deck and game pages, and the live
  scoreboard — for decks and opponents whose known cards are all colorless
  (Eldrazi, artifact decks), instead of showing nothing.
- **Sidebar & navigation**: a Live Log entry above Overview that turns green
  while the tracker runs and red when it's stopped, an icon on every nav item
  (icon-only when the rail is collapsed), a Deck Finder button with a magnifier,
  and a global search that finds cards or decks.
- **Deck colors everywhere**: color pips on the deck page header, a Colors
  column on the overview Decks table, and a Colors column in Recent Games
  (between Deck and Format). Colors are judged lands-first from real casting
  requirements — land identities carry double weight, hybrid pips ({U/B})
  never force a color, a single off-color card never counts, and decks
  tracked before decklist capture fall back to the cards they were seen
  playing, so every deck gets pips.
- **Card page overhaul**: sections reordered (Summary, Opening Hand Impact,
  opponent impact, Played By Side, Repeat Draws, Opponent Repeat Draws, Your
  Decks), an Avg Per Game metric, the same ambient card-art backdrop as the
  deck page, and a new **"Opponent Could Have Played It"** panel — games
  where the opponent's revealed colors could cast the card, how often they
  actually did, and the appearance rate. Computed live from existing data,
  no backfill.
- **Recent Games**: the Match Record column is gone from the top level (a
  win is a win) — expanding a Bo3 match shows "Match record: 2–1" in the
  flyout instead.
- **Deck page polish**: hero-sized signature art (with a by-name Scryfall
  fallback for new sets whose Arena-ID mapping hasn't landed yet), the Copy
  Arena Deck button moved into the topbar beside the card search, and
  Decklist Changes moved down between Vs Opponent Colors and Recent Games.
- **Overview**: the deck page's Land Statistics (Normal/Flood/Screw split
  across all classified games) now heads the land section, Opponent Meta
  pages at 10 rows instead of silently cutting at 15, and the Decks table
  dropped Life Gained / Game to stop horizontal scrolling.
- **Fit and finish**: Combat & Resources "(N drawn)" counts render as small
  muted one-line suffixes instead of wrapping, the card-search focus ring is
  a single clean accent border, pages scroll clear of the Back to top pill,
  official card-type symbols (chalice, claw mark, sunrise…) with singular
  labels in the deck-list type boxes, and "Imported Deck" games retitle
  themselves the moment the renamed deck's first game lands instead of
  waiting for a tracker restart.

## 0.5.7

Rolls up everything since 0.5.5 (including the 0.5.6 beta's date repair).

- **Mana columns everywhere cards are listed**: the deck page's Deck List &
  Sideboard, and the game page's Opening Hand, Drawn Cards, Cards Played, and
  Opponent Deck tables all show each card's cost with official symbols.
- **Opponent Deck on the game page** replaces "Opponent Revealed Cards", split
  into Opponent Played Cards (with the turn(s) each copy hit, like your own
  Cards Played table) and Opponent Revealed Cards (visible draws, discards,
  mills, exiles).
- **Table totals**: proper totals rows on the deck list and sideboard, and on
  the game page's Drawn Cards, Cards Played, and Opponent Deck tables.
- **Mana costs on the deck list**: a new Mana column (between Card and Type) shows
  each card's cost with the official MTG symbols — hybrid, twobrid, Phyrexian, X,
  the lot — rendered from a bundled icon font (mana-font), no network needed.
  Costs come from Arena's own local card database (backfilled into the tracker's
  `cards` table at startup and after each game, like color identities already
  were), with a browser-cached Scryfall lookup as fallback for anything Arena's
  DB doesn't cover. Works for every deck retroactively.
- **Deck list at a glance**: MTGA-style card-type count boxes (Planeswalkers →
  Lands) above the deck list, plus "N cards total" lines under the main deck and
  sideboard tables.
- **Mana-value stats in Combat & Resources** on both the game and deck pages:
  "Mana value / card played" and "Mana spent / turn" for you vs the opponent,
  computed from printed costs (lands excluded, X = 0) — a low cards-played count
  with high mana spent per turn reads very differently from four one-drops.
- **Repaired dates stored month/day-swapped by pre-0.5.5 versions** for day-first
  locales: games recorded before the locale-aware parser (e.g. 9 August read as
  8 September) landed months in the future and scrambled every date-sorted view.
  A one-time migration swaps them back using each tracker session's system-clock
  start time as the anchor — conservative by design, ambiguous rows are left
  untouched. Covers games, matches, turns, events, console logs, rank snapshots,
  and the payload archive. No database reset needed.

## 0.5.5

### Brawl

- **Brawl is now a first-class format**: commander win-rate tables on the Overview
  (your commanders and the ones you faced), an overall and per-queue record strip,
  Brawl queue labels plus commander matchup rows in Recent Games, and the commander
  tables page at 8 rows. The Competitive Brawl queue keeps its label even when
  Arena's deck attributes disagree, and Standard/Historic/ranked Brawl stay distinct
  everywhere.

### Per-game combat & resource stats

- **New tracked categories on the game page** — Removal (spot removal and board
  wipes played, with your drawn counts folded in, plus creatures/non-creatures lost
  to removal), Bounce (bounce cards played, permanents bounced to hand), Land
  Destruction (lands destroyed, successfully replaced by a land drop, lost for
  good, and the replacement rate), Counter Magic (counters played, and — from the
  actual stack outcome — how many landed vs failed), Tokens (created / destroyed /
  sacrificed / exiled per seat), and Poison counters. Card roles are classified
  from Arena rules text, so removal counts from the first game a card is drawn.
- **Historical games are backfilled automatically**: a one-time migration recomputes
  the behavioral stats (removed/bounced permanents, lands, countered spells) for
  every old game from its recorded timeline, and `scripts/backfill_card_role_stats.py`
  fills the classification-based columns using the local Arena card database.
  Stats that genuinely cannot be reconstructed (tokens, poison, opponents' draws)
  show a dash rather than a fake zero.
- Outcome reasons now detect **decked, poisoned, and timeout** endings that were
  previously labeled as concessions, and concede labels are short ("Opponent
  conceded" / "You conceded").

### Deck page

- **Combat & Resources on the deck page**: every game-page category as per-seat,
  per-game averages, in the identical column layout (the game and deck pages now
  share one deterministic arrangement instead of height-balanced masonry).
- New **Turn Timing** (average your/opponent turn time per game and per turn) and
  **Draw Quality** (average cards and lands seen/drawn, expected land rate)
  sections; **Formats** became win-rate rectangles per queue with BO1/BO3 labels;
  **Vs Opponent Colors** opens with Best Against / Worst Against highlight cards.
- The page picks up an ambient background tinted from the signature card's art,
  and metric cards across the deck and game pages gained icons.
- **Deck identity can no longer be misattributed**: the decklist actually submitted
  to a game now arbitrates which deck the game belongs to, fixing games recorded
  under a previously-played deck's name when the tracker launched mid-queue.

### Overview

- **Match-level records everywhere**: a Bo3 counts once — top row shows Matches /
  Wins / Losses / Win Rate / longest streaks with icons, Wins vs Losses splits are
  colored and Wins-first, and How Games End presents per-reason percentages in
  side-by-side Wins and Losses tables.
- **Constructed Ranked** section with lifetime match stats, a season dropdown,
  the rank chart, and per-season stats (constructed queues only — ranked Brawl
  tracks separately). New BO1-Ranked / BO3-Ranked quick filters, a searchable
  Deck filter, and the win-rate trend now covers the last 30 games.
- **Log timestamps are locale-safe**: day/month order is learned from unambiguous
  entries (with a system-locale fallback), fixing "today's games" sorting between
  older dates for day-first locales, and dates render in the viewer's locale.

### Game page

- Cards Played shows the turn(s) each card was played, Opponent Revealed Cards
  shows the reveal turn, Drawn Cards pages at 10 turns, and the Repeat Draws card
  view always shows the 3 and 4+ buckets — including the opponent's repeat draws.

### Fixes & maintenance

- **Fixed DB Health falsely reporting `GAME_EVENT_ASSIGNMENT_MISMATCH`** for post-game tail
  events (Bo3 sideboarding gaps, rank updates, summary lines) — on a real database every
  flagged row was a tail and none were misassigned. The old repair also *detached* those
  rows, deleting real timeline entries. The finding and repair now only act on events whose
  timestamp falls inside a different game's window, and the reassignment runs automatically
  at tracker startup (a new index takes the pass from 4.4s to ~150ms) so nobody needs
  `db_audit --repair` by hand.
- **Stopped tracking Welcome Deck Duels** (pre-made deck vs pre-made deck, e.g.
  "Welcome Deck Duels HOB"); migration v15 removes already-saved games of this mode and
  recomputes session stats. The README's "What isn't tracked" list and the dashboard's
  format filter are updated to match.
- **A new set's card database is picked up mid-session**: after each game the tracker allows
  one re-scan for a newer `Raw_CardDatabase`, so set-release day no longer needs a restart
  when Arena drops the new DB alongside the old one. Arena's card DB is now always opened
  strictly read-only, so the tracker can never create or modify files in Arena's folder.
- A concede during the opening mulligan decision is recorded as a real game instead of
  being skipped as a ghost.
- Database hygiene: new indexes on the game-events timeline and payload archive,
  `PRAGMA optimize` each launch, and `scripts/delete_untelemetered_games.py` (which now
  VACUUMs after deleting) to drop early games recorded without combat telemetry.

## 0.5.4

- **Proper Windows installer**: releases now ship `MTGA-Tracker-<version>-setup.exe`
  (Inno Setup) with a Start Menu entry, an Apps & Features uninstaller, and in-place
  upgrades. Installs per-user by default (no admin prompt) with an optional
  all-users/Program Files mode; uninstall asks before touching your tracked-game data.
  The portable `-windows.zip` is still published alongside it.
- **Multi-target spells show every target**: Arena sends one TargetSpec annotation per
  chosen target, and the tracker kept only the last one — Ram Through showed only the
  creature taking damage, not the attacker dealing it. Targets now merge in selection
  order. BlockerDeclared annotations got the same hardening (every affected id is
  treated as a blocker).
- The install-discovery log parser gained a second, Windows-verified marker (Arena's
  localization line names a file inside `Downloads\Raw` directly) and now normalizes
  Arena's mixed forward/back slashes.
- The "Resolved N previously unknown card label(s)" message no longer repeats on every
  launch: duplicate-name placeholder rows are folded into the real card's row once,
  and only actual changes are counted.
- Startup output tidied: Detailed Logs state prints only on changes, and one-time
  maintenance messages appear inside the startup banner instead of after it.

## 0.5.3

- **Arena installs are now found anywhere** — standalone (.msi) installs on any drive
  included. The tracker reads the install path Arena itself announces in the head of
  `Player.log` (the Unity `[Subsystems]` header, verified against a real log) and derives
  the card-database folder from it, ahead of the Steam-library and Program Files guesses.
- **Databases recorded without the card DB heal completely.** The startup backfill that
  rewrites `Card #N` placeholders now also covers mulligan-hand rows, labels with no
  matching `cards` row, and duplicate-name collisions — so a user whose install was
  previously unfindable gets their full history renamed on the first launch after updating.
  The DB Health finding for these labels now explains that restart-to-fix in plain language.
- Builds no longer use UPX compression, which was tripping antivirus heuristics on the
  unsigned Windows executables.
- Docs: `AGENTS.md` expanded and corrected as the single agent guide (no `CLAUDE.md`);
  added `docs/MTGA_INSTALL_DISCOVERY.md`.

## 0.5.2

- **Fixed the Deck Finder button on Windows** flashing a console that instantly closed
  ("...is not recognized as an internal or external command"): cmd.exe cannot parse the
  backslash-escaped quotes Popen produces for argument lists, so the spaced exe path was split
  apart. The launcher now builds a single cmd /S /C line using cmd's own quoting rules.
  Double-clicking the exe always worked; only the menu-bar/dashboard launch was affected.

## 0.5.1

- **Fixed "Local Card DB: not found" on Windows** (cards showing as `Card #NNNN`): the tracker
  now reads Steam's `libraryfolders.vdf` and checks every configured Steam library on every
  drive (root located via Program Files and the registry), plus Epic Games install paths — on
  Windows and macOS. When the DB still can't be found, the startup banner explains the
  consequence and the `MTGA_DATA_DIR` override.
- **Fixed the packaged Deck Finder starting with "No providers found"**: its provider modules
  load dynamically, so PyInstaller never bundled them. The build now collects every submodule
  and the registry has a frozen-build fallback list guarded by a drift test.
- Windows path display now uses `%USERPROFILE%` instead of `~`, so locations in the startup
  banner paste straight into Explorer or cmd.
- The AI deck guess no longer prints a stray console line after "Ready for next game..." — it
  lands silently in the game record and shows on Game Detail.

## 0.5.0

- Bundled the **Deck Finder** (MTGA Deck Downloader) as a companion tool: launch it from the
  menu bar or the dashboard sidebar, browse creator decklists (Moxfield, AetherHub, TCGplayer,
  magic.gg, MTGO, Untapped) in a sized terminal window, and copy lists in Arena import format.
  Its dependencies install with the tracker; creator lists live in `deckfinder_config.json` at
  the project top level.
- Added **AI opponent-deck identification**: with an OpenAI, Anthropic, or Gemini key, one
  small background call after each completed game names the opponent's archetype by its
  dominant colors and strategy. Shown as the Opponent Deck Type on Game Detail (color label as
  fallback); it never blocks live tracking.
  Reasoning-class OpenAI models are asked for low effort and retried once on token-starved
  empty replies; failures now surface a real error via `scripts/test_deck_ai.py`.
- Added a **Settings… dialog** to the menu bar app for the AI provider, key, and model, plus a
  Deck AI status line in the tracker startup banner.
- Moved `settings.json` to the project top level next to `config.py` (installed builds keep it
  in the app data folder; the old `data/settings.json` migrates automatically) and anchored the
  `.gitignore` `config.py` pattern so the Deck Finder's config module is tracked.
- Fixed finished games being overwritten by the next game's data when Arena re-sent a match's
  final GameOver state after the summary reset.

## Unreleased

### Fable optimizations branch

- Overhauled the light theme with a warm off-white palette: distinct panel/surface/raised
  elevations in both themes, per-theme tint tokens, light-mode timeline chip colors, deeper
  accessible accents, `prefers-color-scheme` support with live OS-follow, and an inline pre-paint
  script that removes the dark flash for light-theme users.
- Added a numbered schema migration runner: migration 2 backfills `cards.arena_id` from submitted
  decklists (exact card-image lookups), migration 3 backfills `game_card_summary.drawn_count` and
  adds drawn-only summary rows, migration 4 creates `game_annotations`.
- Unified the two divergent draw-quality implementations into `draw_quality.py` with
  decklist-exact land rates; the CLI and dashboard now agree, and the dashboard reports the land
  rate source per game.
- Surfaced `game_participant_stats` end to end: dashboard Combat section with per-deck aggression
  profiles and wins-vs-losses splits, deck Combat Profile cards, per-game seat comparison, and a
  corrected `damage_taken` (externally inflicted life loss instead of duplicating `life_lost`).
- Added decklist-aware deck analytics: per-card composition with seen-vs-expected draws and
  win-rate-when-seen vs not-seen (dead-weight report), decklist version history with diffs, and
  Bo3 game-1 vs post-board records with most-boarded cards.
- Added repeat-draw multiplicity analysis on the card page (copies seen per game vs hypergeometric
  expectation, win rate by multiplicity) and Land Availability on curve (N lands by turn N) on the
  dashboard and deck pages, plus a draws-by-turn strip on the game page.
- Added Habits & Schedule (weekday/time-of-day win rates, session fatigue), Streaks & Outcomes
  (run lengths, outcome reasons, kept-opener land counts), rank season selection with historical
  seasons, limited-rank capture, and a minimum-sample floor for Best Deck.
- Added Opponent Meta: a cards-that-beat-you leaderboard and deck-vs-archetype matchup records;
  wired the previously orphaned `deck_llm` module so opt-in LLM archetype identification fills
  `participants.deck_archetype` at game end.
- UI/UX pass: custom date-range filters everywhere (including `/api/card` and `/api/opponent`,
  which previously ignored all filters), URL-synced shareable filters, pagination and CSV export
  on every table, sort persistence, chart hover tooltips with accessible table fallbacks and
  colorblind-safe life lines, stale-data banners with retry on detail pages, visibility-paused
  polling, restored focus outlines, skip-to-content, and a consolidated collapsible Section used
  on every page.
- Added per-game Notes & Tags backed by the dashboard's first write endpoint
  (`POST /api/game/annotation`), a DB Health page at `#/audit` surfacing `db_audit` findings, a
  global search covering cards, decks, and opponents, and a `/` keyboard shortcut for search.
- Added a validated `dashboard.port` setting in `data/settings.json` and stopped tracking live DB
  WAL/SHM files and local backups.

- Added an adaptive macOS menu-bar template icon, transparent app artwork, canonical icon generation, a native `MTGA Tracker` Dock identity, and explicit packaged-app launch guidance.
- Saved the deferred full-card hover preview design in `docs/CARD_HOVER_PREVIEW_PLAN.md`.
- Prevented the macOS menu-bar controller from opening a second overlapping copy of its menu.
- Prevent repeated turn-one state messages from creating duplicate timing rows, and coalesce duplicate timing segments defensively during persistence.
- Made SQLite analytics resilient to concurrent dashboard reads with WAL, busy waits, and bounded
  write retries; exact missing turn durations now recover from durable console headers at startup
  and through the database audit repair.
- Prevent optional analytics failures from removing completed games and recover missing Recent Games rows from local event and console history.
- Prevent source and packaged desktop launchers from running simultaneously; the packaged app supplies the native MTGA Tracker identity while source launches retain Python runtime metadata.
- Added user-editable `settings.json` sizing for the desktop live-log window and increased its default size to 1400 by 1020.
- Enlarged the desktop live-log window, enabled its colored event output by default, and made menu-bar icon clicks open only the menu instead of relaunching the dashboard.
- Fixed live event rows using the previous game's analytics ID, added timestamp-based historical event reassignment, and made DB repair remove empty unknown-result game artifacts.

### Dashboard UI

- Ranked Best Deck by confidence-adjusted win rate instead of raw win rate alone, and exposed the
  selected deck's win rate, record, and game count on the overview metric.
- Sorted Formats alphabetically by default and defensively removed Midweek Magic/Momir rows and
  filter options from stale dashboard responses.
- Added exact submitted deck snapshots, deck-membership-aware Card Performance that excludes
  temporarily controlled opponent cards, and one-click MTG Arena deck export on Deck Detail.
- Modernized the sidebar wordmark to match dashboard heading typography, made the full brand link
  to Overview, and replaced low-resolution mana pips with crisp local vector symbols.
- Made the `MTGA Tracker` logo reliably return to the very top of Overview and standardized
  browser titles as `MTGA Tracker – <page>`.
- Enlarged Card Drill-Down imagery and persistently loaded the full card through the same
  Scryfall image path used by card hover previews.
- Added lazy full-card hover and keyboard-focus previews to every card link, plus linked yellow Timeline brackets and compact inline card-type chips.
- Removed the obsolete analytics eyebrow from every page header, realigned titles with the header controls, and standardized `Performance Overview` title casing.
- Removed redundant turn-start event rows from the Game Detail Timeline because each turn header already shows the turn boundary and active player.
- Added links from validated card references in Game Detail Timeline events to Card Detail, with return-to-Timeline navigation.
- Changed Game Detail flood indicators from red danger styling to the existing blue draw-quality styling.
- Added game detail routes with life charts, opening hand, drawn cards, played cards, and filterable event timeline.
- Added card drill-down routes with card art, by-deck performance, and opening-hand impact.
- Added filter-aware deck routes, sidebar scrollspy, deck/card table search, match recap rows, session recap rows, and empty-dashboard setup guidance.
- Extended the local dashboard API with `/api/game`, `/api/card`, filtered `/api/deck`, match/session snapshot data, and larger deck/card result limits.
- Added global tracked-card search with usage-ranked autocomplete results and direct card detail navigation.
- Expanded card analytics to include player and opponent usage, with compact side-by-side and deck tables.
- Added per-game draw totals, land-draw percentage, and Flood detection for games above 50% land draws.
- Expanded Flood detection to include total-land probability, consecutive land streaks, and six-land eight-draw windows, with the triggering evidence shown in Game Detail.
- Preserved dashboard section context when opening a game so Back returns to the originating table and scroll position.
- Merged Draw Quality into Recent Games and moved Recent Games directly below Win Rate Trend in dashboard navigation.
- Reordered dashboard content so its top-to-bottom section sequence exactly matches sidebar navigation.
- Consolidated Play / Draw and Momentum into Overview and replaced intersection-based navigation highlighting with position-based scroll tracking.
- Added game length and average turn pace to Recent Games and deck history, plus sortable per-turn timing with player/opponent totals and live/estimated provenance in Game Detail.
- Moved individual turn durations from the Game Detail timing table into Timeline turn headers while retaining the timing summary metrics.
- Added top-right collapse controls to every Game Detail section.
- Added every identified opponent card to Game Detail with played, revealed-draw, discarded, milled, and exiled counts.
- Added linked opponent names to Game Detail with a sortable head-to-head game history for each Arena player.
- Clarified card drill-down analytics with your record and loss rate when the opponent actually played the card, excluding revealed-only appearances.
- Added current-season constructed rank tracking and a Bronze-to-Mythic progress chart shared by ranked Standard Best-of-1 and Best-of-3, including existing-log backfill.

### Desktop Launcher

- Added a unified tracker/dashboard launcher with automatic browser opening and free-port fallback.
- Added a macOS menu-bar controller with tracker status, start/stop controls, dashboard access, a bounded live tracker log, and clean coordinated shutdown.
- Added PyInstaller app-bundle and DMG build scripts with bundled frontend assets and per-user Application Support storage.
- Added original card-analytics app and menu-bar icons, corrected the native application display name, and made the Live Tracker Log window open automatically with the dashboard.
- Added matching ICO, PNG, and Apple touch favicons to the web dashboard.
- Fixed custom database selection so the tracker and dashboard always read and write the same SQLite file.

## v0.4.0 - Complete Game Tracking & Auto-Summary (2025-11-19)

### Major Features

**Starting Hand & Mulligan Tracking**
- ✅ Shows your opening hand with card names
- ✅ Detects mulligans automatically
- ✅ Counts number of mulligans
- ✅ Tracks hand size (7, 6, 5, etc.)
- ✅ Displayed at start and in game summary

**Combat Tracking**
- ⚔️ Attacker declarations with power/toughness
- 🛡️ Blocker declarations showing what blocks what
- 💢 Combat damage tracking
- 💥 Creature deaths in combat
- Shows which player's creatures

**Spell Targeting**
- ✅ Shows what card/permanent was targeted
- ✅ Shows ownership of target (your vs opponent's)
- ✅ Example: "Lightning Bolt targeting Tarmogoyf (opponent's)"
- Works with removal, auras, counters, etc.

**Game Timer**
- ⏱️  Tracks game duration from start to end
- Shows minutes and seconds
- Displayed in final summary

**Auto Game Detection**
- ✅ Detects game start automatically
- ✅ Detects game end automatically
- ✅ Shows summary when game ends (no manual stop needed)
- ✅ Resets state for next game
- ✅ Tracker runs continuously through multiple games

**Improved Life Tracking**
- ✅ Fixed: Now accurately tracks between turns
- ✅ Only announces actual changes (not initial values)
- ✅ Only shows changes after turn 1
- ✅ Shows current life after change

**Enhanced Game Summary**
- 🏁 Automatic at game end
- ⏱️  Game duration
- 🎴 Starting hand displayed
- 🎉/💀 Win/loss detection
- 📊 All cards played by both players
- Shows card counts

### Game Flow Example

```
🎮 GAME STARTED

🎴 Your Starting Hand (6 cards):
   (After 1 mulligan)
   • Lightning Bolt
   • Mountain x2
   • Goblin Guide
   ...

⚔️  Turn 1 - YOUR TURN

🎯 You cast Lightning Bolt targeting Tarmogoyf (opponent's)
💥 Tarmogoyf (opponent's) was destroyed

⚔️ You attacking with Goblin Guide (2/2)
🛡️ Opponent blocking with Wall (0/4)

🏁 GAME ENDED
⏱️  Game Duration: 8m 42s
🎉 You won!
```

### Files Added
- `docs/COMPLETE_GAME_TRACKING.md` - Complete feature documentation

### Files Modified
- `src/mtga_tracker/tracker.py` - Major expansion of tracking features
- All new tracking systems implemented

### Breaking Changes
None - fully backwards compatible

## v0.3.0 - Instant Detection & Interaction Tracking (2025-11-19)

### Major Improvements

**Instant Detection Fixed**
- ✅ Instants are now properly tracked
- ✅ Added support for "PlaySpell" category (in addition to "CastSpell")
- ✅ All spell types now detected reliably

**Interaction Tracking**
- ✅ Destruction effects show ownership: "Serra Angel (your) was destroyed"
- ✅ Multiple removal types tracked:
  - 💥 Destroy
  - 🚫 Exile
  - ⚰️ Sacrifice
  - 🗑️ Discard
  - 🚫 Counter
- ✅ Shows which player's card was affected

**Additional Game Events**
- ✅ Card draw tracking: `📥 You drew a card`
- ✅ Scry tracking: `🔮 You scried`
- ✅ Mill tracking: `🌊 You milled Brainstorm`
- ✅ Sacrifice tracking with ownership

**Debug Tools**
- ✅ debug_annotations.py - Analyzes all annotation categories in log
- ✅ Shows instant/sorcery detection
- ✅ Shows destruction/removal patterns
- ✅ Recommends which categories to track

### Files Added
- `debug_annotations.py` - Comprehensive annotation analyzer
- `docs/INTERACTION_EXAMPLES.md` - Examples of all tracked interactions

### Files Modified
- `src/mtga_tracker/tracker.py` - Expanded annotation processing
- `docs/EXAMPLE_OUTPUT.md` - Updated with new features

### Examples

**Before:**
```
🎯 You cast Lightning Bolt (Instant)
💥 Vampire Nighthawk was destroyed
```

**After:**
```
🎯 You cast Lightning Bolt (Instant)
💥 Vampire Nighthawk (opponent's) was destroyed
   Opponent lost 3 life (17)
```

**Now also tracks:**
```
👤 Opponent cast Thoughtseize (Sorcery)
🗑️ Force of Will (your) was discarded

🎯 You cast Opt (Instant)
🔮 You scried
📥 You drew a card
```

## v0.2.1 - Player Detection & Life Tracking Fixes (2025-11-19)

### Bug Fixes

**Player vs Opponent Detection**
- 🐛 Fixed: Player/opponent showing backwards
- ✅ Auto-detects player seat ID from log
- ✅ Scans matchGameRoomStateChangedEvent for seat assignments
- ✅ Shows detected seat on startup

**Life Total Tracking**
- 🐛 Fixed: Life totals not updating correctly
- ✅ Uses detected seat IDs for life mapping
- ✅ Prevents false announcements at game start
- ✅ Only announces changes after match begins

### Files Added
- `debug_seats.py` - Seat ID detection analyzer
- `docs/TROUBLESHOOTING.md` - Common issues and solutions

## v0.2.0 - Narrative Output & Card Name Resolution (2025-11-19)

### Major Improvements

**Card Name Resolution**
- ✅ Actual card names instead of IDs using Scryfall API
- ✅ Local caching to minimize API calls (stored in `data/card_cache.json`)
- ✅ Automatic card lookup on first encounter

**Game State Tracking**
- ✅ Life total tracking with change notifications
- ✅ Turn number and active player display
- ✅ Match start/end detection
- ✅ Clear turn boundaries with life totals

**Better Output**
- ✅ Narrative-style output that tells the story of the game
- ✅ Visual icons for quick identification (🎯 You, 👤 Opponent, 💥 Destroyed)
- ✅ Card type information (Creature 2/3, Instant, etc.)
- ✅ Event deduplication (no more duplicate announcements)
- ✅ Improved summary with card counts

**Code Architecture**
- ✅ New `CardDatabase` class for card name lookups
- ✅ `GameState` class to track match state
- ✅ Cleaner event processing with proper filtering
- ✅ Removed duplicate/noisy output

### Files Added
- `src/mtga_tracker/card_database.py` - Card name resolution
- `docs/EXAMPLE_OUTPUT.md` - Example of improved output
- `CHANGELOG.md` - This file

### Files Modified
- `src/mtga_tracker/tracker.py` - Complete rewrite of event handling
- `src/mtga_tracker/log_parser.py` - Improved JSON parsing (by user)

### Breaking Changes
None - backwards compatible

## v0.1.0 - Initial Release (2025-11-19)

### Features
- Basic log file monitoring
- Cross-platform support (macOS, Windows)
- Card ID tracking
- Console output
- Player vs opponent tracking
