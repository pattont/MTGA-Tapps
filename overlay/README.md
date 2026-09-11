# Tapps Overlay

The in-game overlay for Tapps Tracker: a Tauri v2 app (Rust shell, Preact
page) that sits beside MTG Arena and shows the turn, the chance of a land on
the next draw, the library count, and — in its panel — the full decklist
with per-card draw odds. It reads the tracker's local `GET /api/overlay`
and, when you hover a card, that card's image from Scryfall — nothing
else. The tracker enables it by default when its binary is available;
Settings and the tracker menu control its lifecycle.

## Layout

- `src/` — the page. `App.tsx` wires the rail, the panel, the ⚙ flyout and
  the poll loop; `model.ts` is the pure view-model (grouping, sorting,
  odds); `poll.ts` the ETag/backoff poller; `tauri.ts` the door to the Rust
  side (with a browser stand-in for tests and `vite dev`).
- `src-tauri/` — the shell. `lib.rs` owns the window (rail ↔ panel sizing,
  docking, hotkeys, click-through; no tray of its own — the tracker's menu bar
  drives it by launching a second instance with `--open-settings`, `--show`
  or `--hide`, which the single-instance guard hands over), `dock.rs` the pure geometry,
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

The panel's pin keeps it open; click-through is a separate preference. An
unpinned open panel folds to the rail after its return delay. Final library
state remains marked FINAL through Arena's results screen. The shell follows
Arena's display and focus; macOS supports its fullscreen Space, while Windows
exclusive fullscreen can cover the overlay.

The page polls `/api/overlay` every 300 ms in game, 2 s between games, and
10 s while offline, with ETag/304 handling. Library odds use remaining card
composition; they do not condition on known scry top/bottom order. The
tracker publishes state even for game modes excluded from saved history.

The tracker passes `--api` with its actual dashboard address and writes
`overlay.log` and `overlay-stderr.log` in its data directory. A standalone
launch can use `--log <path>` for shell diagnostics. The preference file is
separate from the tracker's `settings.json` `overlay.enabled` flag.

The shell currently has macOS and Windows Arena probes. Its Linux probe is a
stub and Linux staging is not a complete packaged or validated integration.
