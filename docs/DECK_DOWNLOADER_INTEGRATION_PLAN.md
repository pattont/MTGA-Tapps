# Deck Downloader Integration Plan

Plan for merging the separate **MTGA-DeckDownloader** project
(`github.com/pattont/MTGA-DeckDownloader`) into MTGA-Tapps as a first-class
feature. Written 2026-08-05; plan only — no implementation yet.

## What the deck downloader is today

A standalone Python console app (~4,900 lines, Rich terminal UI) that finds
playable Arena decklists from public sources and produces Arena import text:

- **Providers:** magic.gg, mtga.untapped.gg (with deckstring decoding),
  aetherhub.com (tournament + meta tabs + creator feeds), moxfield.com
  (creator profiles), mtgo.com (league/tournament decklists), tcgplayer.com.
- **Dependencies:** `requests`, `beautifulsoup4`, `cloudscraper`, `rich`
  (the tracker itself currently has zero runtime deps outside the stdlib,
  plus PyQt6 for the menu app).
- **Config:** `config.json` with creator lists (`MoxfieldNames`,
  `AtherhubCreators`, `TcgplayerCreators`).
- **Tests:** mocked provider/scraper suite (no live network in CI).
- **Packaging:** its own PyInstaller setup — redundant after the merge.

## Decision: merge, don't link

Merge into this repo rather than pointing users at a separate download.
Rationale: same audience and product story ("track your games, find your
next deck"), one installer, one release pipeline, one update pill, one repo
to maintain. A separate app doubles release chores and forecloses the
dashboard integration in Phase 4. The only argument for staying separate —
independent release cadence for scraper hotfixes — is served just as well by
monorepo patch releases.

## Phase 1 — Repo merge

1. **Layout:** code lands as its own package, `src/mtga_deck_downloader/`,
   alongside `src/mtga_tracker/`. Tests move to `tests/deck_downloader/`.
   The imported repo's `packaging/`, `app.py` shim, and CI are dropped.
2. **History:** either `git subtree` merge (preserves the downloader's
   commit history — first run the same Claude-Session trailer-stripping
   filter used on this repo before importing), or import squashed as a
   single commit and archive the old repo as the historical record.
   Squashed import is simpler and recommended.
3. **Dependencies:** new optional extras group in `pyproject.toml`, e.g.
   `decks = ["requests", "beautifulsoup4", "cloudscraper", "rich"]`.
   Core tracker keeps its stdlib-only property for pip users; the `gui` /
   frozen builds include the extras. Keep the `mtga-deck-downloader`
   console-script entry point.
4. **Config:** default config ships inside the package
   (`default_config.json`); the user's editable config moves to the
   tracker's data dir (`DATA_DIR/deck_downloader.json`) so the tray's
   "Open Data Folder" exposes it. On first run, migrate/read the legacy
   `config.json` if present.
5. **License:** imported code falls under this repo's AGPL-3.0. Verify the
   old repo's license is compatible (it is Travis's own code).

## Phase 2 — Menu bar launch

1. Add a **"Find Decks…"** QAction to the tray menu (near "Open Dashboard").
2. The downloader is an interactive terminal UI, so it needs a real
   terminal — the live-log window is read-only and cannot host it.
   - **From source:** macOS launches via
     `osascript -e 'tell app "Terminal" to do script "…"'`; Windows via a
     new console (`start cmd /k` / `CREATE_NEW_CONSOLE`).
   - **Frozen builds:** the PyInstaller spec gains a second, console-mode
     executable built from the same bundle (onedir shares libraries, so
     size cost is a few MB). Windows: `MTGA Deck Downloader.exe` next to
     the tracker exe. macOS: a console binary inside the .app that the
     menu item opens in Terminal.
3. PyInstaller caveat: `cloudscraper`/`bs4` typically need hidden-import
   entries in the spec; validate on both OSes.

## Phase 3 — Release and docs

1. `release.yml` conceptually unchanged — artifacts already glob; the spec
   simply produces both binaries inside the same dmg/zip.
2. The downloader's mocked tests join the normal `pytest tests` run in CI.
3. README gains a "Finding decks" section; QUICKSTART mentions the menu
   item.
4. Archive the old GitHub repo with a "moved into MTGA-Tapps" pointer in
   its README; leave old releases up.

## Phase 4 — Dashboard integration (later, separate effort)

The reason merging beats linking. Once in-repo:

1. Run providers server-side behind the stdlib dashboard server; add a
   **Find Decks** dashboard page — browse ranked lists, one-click copy of
   Arena import text. Terminal UI remains for power users.
2. Cross-reference with tracker data:
   - "You are 2–8 vs this color combo / archetype — here are current lists
     that beat it."
   - Auto-name imported decks: when a deck found here is imported and then
     played, the tracker already knows its name and source.
3. Provider results cached in the analytics DB so the page is fast and
   works offline after a refresh.

## Effort and risks

- Phases 1–3: an evening or two, plus one build validation each on real
  Windows and macOS hardware.
- Phase 4: its own project; plan separately when reached.
- Standing risk: scrapers rot when sites change markup. Post-merge, fixes
  ride ordinary patch releases (the update pill tells testers).
