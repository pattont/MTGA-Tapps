# Tapps Overlay

The in-game overlay for Tapps Tracker: a Tauri v2 app (Rust shell, Preact
page) that sits beside MTG Arena and shows the turn, the chance of a land on
the next draw, the library count, and — in its panel — the full decklist
with per-card draw odds. It reads the tracker's local `GET /api/overlay`
and nothing else. Design and behaviour: `docs/plans/OVERLAY_TRACKER_PLAN.md`.

## Layout

- `src/` — the page. `App.tsx` wires the rail, the panel, the ⚙ flyout and
  the poll loop; `model.ts` is the pure view-model (grouping, sorting,
  odds); `poll.ts` the ETag/backoff poller; `tauri.ts` the door to the Rust
  side (with a browser stand-in for tests and `vite dev`).
- `src-tauri/` — the shell. `lib.rs` owns the window (rail ↔ panel sizing,
  docking, hotkeys, tray, click-through), `dock.rs` the pure geometry,
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

`scripts/build_overlay.sh` (macOS/Linux) or `scripts/build_overlay.ps1`
(Windows) at the repository root builds the release binary and stages it in
`overlay/build-out/`, where `packaging/mtga_tracker.spec` picks it up. The
tracker's own build scripts call them; with no Rust toolchain installed they
skip the overlay and the tracker still builds (the Settings page then says
the overlay is not in this build).
