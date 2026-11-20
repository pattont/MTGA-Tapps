# Tapps Overlay

The in-game overlay for Tapps Tracker: a Tauri v2 app (Rust shell, Preact
page) that sits beside MTG Arena and shows the turn, the chance of a land on
the next draw, the library count, and — in its panel — the full decklist
with per-card draw odds. An optional second window, the opponent panel,
docks on the other edge during games with the opponent's played cards and
likely deck. It reads the tracker's local `GET /api/overlay`
and, when you hover a card, that card's image from Scryfall — nothing
else. The tracker enables it by default when its binary is available;
Settings and the tracker menu control its lifecycle.

## Layout

- `src/` — the page. `App.tsx` wires the rail, the panel, the ⚙ flyout and
  the poll loop; `model.ts` is the pure view-model (grouping, sorting,
  odds); `poll.ts` the ETag/backoff poller; `tauri.ts` the door to the Rust
  side (with a browser stand-in for tests and `vite dev`). `OpponentApp.tsx`
  is the opponent window's page (`OpponentRail`, `OpponentPanel`,
  `opponentModel.ts`); `main.tsx` picks it when the shell marks the window
  (`window.__TAPPS_VIEW__`), or for `?view=opponent` in a browser.
- `src-tauri/` — the shell. `lib.rs` owns the windows (rail ↔ panel sizing,
  docking, hotkeys, click-through; no tray of its own — the tracker's menu bar
  drives it by launching a second instance with `--open-settings`, `--show`
  or `--hide`, which the single-instance guard hands over), `parent.rs` the
  `--parent-pid` watchdog that quits the overlay once the tracker that started
  it is gone (a tracker reusing a running overlay hands over its own pid the
  same way), `dock.rs` the pure geometry,
  `settings.rs` the persisted preferences (`overlay.json` in the app config
  dir), `arena.rs` the once-a-second "is Arena in front" probe.

## Develop

```sh
npm ci
npm test               # vitest: model, poller, hotkeys, components
npm run build          # type-check + bundle into dist/
node scripts/screenshots.mjs   # render fixture states with Playwright -> shots/
cargo test --manifest-path src-tauri/Cargo.toml
npm run tauri dev      # the real window, against a tracker on 127.0.0.1:8765
```

`npm run tauri dev -- -- --api http://127.0.0.1:9000` points it at another
port. Preferences live in `overlay.json` under the platform's app-config
directory (`~/Library/Application Support/com.tappstracker.overlay/` on
macOS, `%APPDATA%\com.tappstracker.overlay\` on Windows).

## Build for the tracker

`scripts/build_overlay.sh` (macOS; also has a Linux staging branch) or `scripts/build_overlay.ps1`
(Windows) at the repository root builds the release binary and stages it in
`overlay/build-out/`. The spec includes the Windows executable as data; the
macOS app build copies the overlay app into `Contents/Helpers/` after
PyInstaller finishes. The tracker's own build scripts call them; with no Rust toolchain installed they
skip the overlay and the tracker still builds (the Settings page then says
the overlay is not in this build).

While iterating, pass `--fast` (`-Fast` on Windows): it builds the `fast`
cargo profile — release settings minus fat LTO and the single codegen unit,
incremental, in its own `target/fast/` so it never evicts the release
cache — and stages that binary instead. A rebuild after a CSS or Rust
change then takes seconds rather than a full relink, and Start/Stop Overlay
in the menu bar picks it up as usual. The first `--fast` build compiles
every dependency once. Both scripts also skip `npm ci` unless
`package-lock.json` changed. Ship the plain build.

## Behavior and diagnostics

The panel's pin keeps it open; click-through is a separate preference. The
panel window also covers a transparent gutter beside the panel, where the
hover card, sideboard and settings appear; it passes the mouse to Arena
there unless the sideboard or settings are open. An
unpinned open panel folds to the rail after its return delay. Final library
state remains marked FINAL through Arena's results screen. The shell follows
Arena's display and focus; macOS supports its fullscreen Space, while Windows
exclusive fullscreen can cover the overlay.

The page polls `/api/overlay` every 300 ms in game, 2 s between games, and
10 s while offline, with ETag/304 handling.

The opponent panel is a second window, `opponent`, built while it is on and
destroyed when it is turned off. Which panels are on is the tracker's setting,
not the flyout's: the dashboard's Settings → In-game overlay → Panels (Both,
My deck, Opponent; `settings.json` `overlay.panels`), which the tracker passes
as `--panels both|deck|opponent` on every launch and, on a change, through a
second launch. `overlay.json`'s `deckPanel` / `opponentPanel` only mirror it
(a standalone launch reads them, or takes `--panels` itself). With the deck
panel off its window stays up, empty and click-through: it still holds the
poller and the ⚙ flyout, which the tracker's menu or the opponent panel's ⚙
(shown only then) opens. The opponent panel docks on the edge opposite the
deck panel (the right edge beside a floating one); in opponent-only mode the
Dock setting places the opponent panel instead and the empty deck window takes
the other edge (`dock::pane_docks`). It has its own remembered offset, pin,
open state and hotkey (`Alt+Shift+O`; each panel's toggle is registered only
while that panel is on). It has no poller: the deck
page hands each new `/api/overlay` body to the shell (`share_payload`), which
forwards it to the opponent page and shows that window only while the body
carries an `opponent` block, that is, while a game is on screen. Scale,
background, rows, card-name colour, the Lands setting, the return delay and
click-through when pinned are shared with the deck panel. Its list mirrors the
Stream Kit's opponent widget (`ui/src/stream/liveView.ts` `groupSeen`). Library odds use remaining card
composition; they do not condition on known scry top/bottom order. The
tracker publishes state even for game modes excluded from saved history.

The tracker passes `--api` with its actual dashboard address and writes
`overlay.log` and `overlay-stderr.log` in its data directory. A standalone
launch can use `--log <path>` for shell diagnostics. The preference file is
separate from the tracker's `settings.json` `overlay.enabled` flag.

The shell currently has macOS and Windows Arena probes. Its Linux probe is a
stub and Linux staging is not a complete packaged or validated integration.
