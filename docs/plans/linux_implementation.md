# Linux Support Plan

Goal: Tapps Tracker (tracker + dashboard + menu-bar app + in-game overlay)
on Linux, built and released by the same CI as macOS and Windows, without a
local Linux VM to develop on. The plan is ordered so every phase ships
something usable on its own and can be verified from CI or a container
before anyone has a Linux desktop in front of them.

## The premise that shapes everything

There is no native Linux build of MTG Arena. Linux players run the Windows
client through **Steam / Proton** (Arena is on Steam, app id `2141910`) or a
**Wine prefix** managed by Lutris, Bottles, or plain Wine. So "Linux support"
means: the tracker runs natively, but everything it looks for — `Player.log`,
the card database, the Arena window — lives inside a Windows-shaped tree
under a Wine prefix, and Arena's own log lines describe those files with
Windows paths (`C:/Program Files/…`).

Two consequences drive the design:

1. **Path discovery is prefix discovery.** Find the prefix, and the rest of
   the layout is exactly Windows. Everything under `drive_c` uses real case
   on a case-sensitive filesystem (`users`, `AppData`, `LocalLow`).
2. **Windows paths in the log must be translated.** Arena's Unity header
   says `Loading SqlLocalizationManager from file: C:/Program Files/…` —
   that is `<prefix>/drive_c/Program Files/…` on disk. `Z:\` maps to `/`.

Everything else (the parser, the database, the dashboard, the React UI) is
already platform-neutral Python and runs on Linux today.

## Where Arena's files are

| Install | `Player.log` | Card DB (`Raw_CardDatabase_*.mtga`) |
| --- | --- | --- |
| Steam / Proton | `<steam>/steamapps/compatdata/2141910/pfx/drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log` | `<steam>/steamapps/common/MTGA/MTGA_Data/Downloads/Raw/` (any library in `libraryfolders.vdf`) |
| Lutris (default) | `~/Games/magic-the-gathering-arena/drive_c/users/<user>/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log` | `<prefix>/drive_c/Program Files/Wizards of the Coast/MTGA/MTGA_Data/Downloads/Raw/` |
| Bottles | `~/.var/app/com.usebottles.bottles/data/bottles/bottles/<bottle>/drive_c/…` (Flatpak) or `~/.local/share/bottles/bottles/<bottle>/drive_c/…` | same shape under the bottle's `drive_c` |
| Heroic | `~/Games/Heroic/Prefixes/<name>/pfx/drive_c/users/<user>/AppData/LocalLow/…` | `~/Games/Heroic/<name>/MTGA_Data/Downloads/Raw/` or under the prefix's `drive_c` |
| Plain Wine | `$WINEPREFIX` or `~/.wine` → `drive_c/users/<user>/AppData/LocalLow/…` | `<prefix>/drive_c/Program Files/…` |

`<steam>` is `~/.steam/steam`, `~/.steam/root`, `~/.local/share/Steam`, or
the Flatpak `~/.var/app/com.valvesoftware.Steam/.local/share/Steam`. The
existing `_steam_mtga_raw_dirs()` already walks `libraryfolders.vdf`; it
only needs Linux Steam roots fed to it.

Three things field experience with Linux trackers says not to assume:

- **The Steam app id is not fixed.** Arena added to Steam as a *non-Steam
  game* (a common way to get Proton without the Steam build) lands in
  `compatdata/<random id>/pfx`. Scan every `compatdata/*/pfx` for the
  `Player.log` path rather than only `2141910`.
- **Libraries live on other disks.** Beyond `libraryfolders.vdf`, look for
  a `SteamLibrary/steamapps` (or a bare `steamapps`) directly under
  `/mnt/*`, `/media/*`, and `/run/media/<user>/*` — people mount a games
  drive and never register it with Steam's config.
- **Names vary.** The Steam install folder is `MTGA` but has also shipped
  as `Magic The Gathering Arena`; Lutris prefixes have been seen as
  `~/Games/mtga`, `~/Games/magic-the-gathering-arena`, and
  `~/Games/Magic-The-Gathering-Arena`; the Windows `Program Files (x86)`
  variant appears too. Match by structure (`…/MTGA_Data/Downloads/Raw`
  containing `Raw_CardDatabase_*.mtga`), never by one spelling.

Arena's **Detailed Logs** setting must be on, exactly as on the other
platforms.

## Inventory: what is platform-specific today

| Area | File | Today | Linux |
| --- | --- | --- | --- |
| Log discovery | `log_parser.py` `_find_log_path` | Windows/macOS only; raises "Unsupported operating system" | Prefix search (Phase 1) |
| Card DB discovery | `paths.py` `mtga_card_database_dirs` | Darwin / Windows branches | Linux branch + Wine path translation (Phase 1) |
| Log-derived install dir | `paths.py` `mtga_raw_dir_from_player_log` | Uses the Unity header path as-is | Translate `C:/…` → `<prefix>/drive_c/…` (Phase 1) |
| Data dir | `paths.py` `_installed_app_data_dir` | Already XDG (`~/.local/share/mtga-tracker`) | Done |
| Platform reported to the UI | `settings_api.py` | `"other"` | `"linux"` (Phase 2) |
| Menu-bar app | `menu_app.py` | Qt tray; mac/win icon tweaks | Tray-optional mode (Phase 2) |
| Deck Finder launcher | `deck_downloader_launcher.py` | Has `_launch_linux_terminal` | Done |
| Collection export | `collection_export.py` | mac/win memory readers | Stays unsupported (reads a Wine process) — UI already hides it |
| Overlay: Arena window probe | `overlay/src-tauri/src/arena.rs` | mac (CGWindowList), win (Win32); Linux stub returns "not running" | X11 probe + `/proc` fallback (Phase 3) |
| Overlay: window level | `lib.rs` `raise_above_fullscreen` | mac NSPanel trick; no-op elsewhere | `_NET_WM_STATE_ABOVE` via Tauri is enough on X11 (Phase 3) |
| Overlay: hotkeys | `settings.rs` `hotkeys_macos` / `hotkeys_windows` | Two platforms | Add `hotkeys_linux` (Phase 3) |
| Overlay: launch | `overlay_launcher.py` | `_POSIX_EXECUTABLE = tapps-overlay` already | Add `GDK_BACKEND=x11` env (Phase 3) |
| Build | `scripts/build_*` | mac `.app`, win installer | `build_linux_app.sh` → AppImage + tarball (Phase 4) |
| CI | `.github/workflows/release.yml` | macos / windows matrix | Add ubuntu (Phase 5) |

## Phase 1 — Find the log and the card DB (pure Python, fully testable)

The whole phase is path logic with no desktop dependency, so it can be
developed and tested entirely with `tmp_path` fixtures and the existing
test suite, on any OS.

**`paths.py`**

- `wine_prefix_candidates() -> List[Path]`: in order, `$MTGA_WINE_PREFIX`,
  `$WINEPREFIX`, every `steamapps/compatdata/*/pfx` under every Steam
  library (`2141910` first, then the rest — non-Steam shortcuts get a
  random id), Lutris (`~/Games/*/`, and `~/.local/share/lutris` /
  `~/.var/app/net.lutris.Lutris` for its `drive_c` prefixes), Bottles
  (both install styles), Heroic (`~/Games/Heroic/Prefixes/*/pfx`),
  `~/.wine`. Only existing directories with a `drive_c` are returned.
- `_linux_steam_roots()`: the Steam locations above plus any
  `SteamLibrary/steamapps` or bare `steamapps` found one level under
  `/mnt`, `/media`, and `/run/media/<user>` (mirror of
  `_windows_steam_roots`, which walks `libraryfolders.vdf`).
- `raw_dir_from_prefix_log(log_path) -> Optional[Path]`: the primary
  derivation on Linux, and simpler than translating anything. Walk up
  from the log file to the `drive_c` directory (the prefix), then try the
  known install spots under it (`Program Files/Wizards of the Coast/MTGA`,
  the `(x86)` twin, `MTGA`, `Games/MTGA`), each ending in
  `MTGA_Data/Downloads/Raw`. For a Steam path, cut at
  `/steamapps/compatdata` and look in the sibling `steamapps/common/MTGA`
  (and `Magic The Gathering Arena`) instead — Proton keeps the game
  outside the prefix.
- `wine_path_to_native(path_text, prefix) -> Optional[Path]`: the
  secondary derivation, for a custom install the walk above misses. `C:`
  → `<prefix>/drive_c`, other letters → `<prefix>/dosdevices/<letter>:`
  (a symlink Wine keeps), `Z:` → `/`; backslashes to slashes. Used by
  `mtga_raw_dir_from_player_log` when the Unity header's path looks like
  a Windows path on a non-Windows host, with the prefix found by the same
  walk.
- `mtga_card_database_dirs`: a `Linux` branch — Steam libraries via
  `_steam_mtga_raw_dirs(root)` for each Linux Steam root, then
  `<prefix>/drive_c/Program Files/Wizards of the Coast/MTGA/MTGA_Data/Downloads/Raw`
  and the `(x86)` variant for every prefix candidate.

**`log_parser.py`**

- `_find_log_path`: a `Linux` branch that checks `$MTGA_LOG_PATH` (new,
  all platforms — the settings page's "Arena log" override can back it),
  then for each prefix candidate, `drive_c/users/*/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log`
  (glob the user name: `steamuser` under Proton, the login name under
  Wine). Newest `Player.log` by mtime wins when several prefixes have
  one — a player who moved from Lutris to Steam has two, and the one
  Arena is writing right now is the one that matters.
- Rotation by inode. `MTGALogParser._read_new_entries` detects a new log
  by `size < last_position`. Arena under Wine/Proton, like Arena on macOS,
  *recreates* `Player.log` on launch (the old one becomes
  `Player-prev.log`); a fresh file that has already grown past the old
  offset is missed until it shrinks. On POSIX, remember `st_ino` and treat
  a change as rotation. That is a small, platform-neutral fix worth
  landing first, because macOS benefits today.
- The error message when nothing is found should say where it looked and
  name the override, since on Linux "I installed it somewhere else" is the
  common case.

**Tests** (`tests/test_paths_linux.py`): build fake prefixes under
`tmp_path` for each install style, monkeypatch `Path.home()` /
`platform.system()`, and assert discovery order, the newest-log rule, the
path translation (including `Z:` and a `D:` dosdevices symlink), and that
Windows/macOS behaviour is untouched.

**Ships as:** the tracker and dashboard fully working on Linux from source
(`pip install -e '.[gui]'`, `mtga-tracker`), which is what a Linux alpha
tester needs first.

## Phase 2 — The desktop app (Qt) on Linux

`menu_app.py` runs on Linux as-is with PySide6, with two things to handle:

- **No system tray on stock GNOME.** GNOME dropped tray icons; they need
  the AppIndicator extension, and KDE / XFCE / Cinnamon have one. Check
  `QSystemTrayIcon.isSystemTrayAvailable()` at startup: when false, start
  with the Live Log window open and put the same menu on a window menu bar
  (a `QMenuBar` with one "Tracker" menu holding the existing actions), so
  every action stays reachable. Closing that window then means quit, and
  the window says so once. When a tray exists, behave like Windows
  (left-click opens the menu — already coded for `sys.platform != "darwin"`).
- **Icon:** the coloured `app-icon.png` (the Windows choice) — the
  monochrome template is macOS-only.

Smaller items: `settings_api.platform()` reports `"linux"` so the UI can
word things; the Settings "Tracker" block shows the resolved prefix; the
Deck Finder terminal launcher already handles Linux; collection export
stays off (the UI already gates on `collection_export: false`).

Worth adding for every platform while the Linux branch is open: an
**"Arena log" and "Card database folder" override** on the Settings page,
with a live check mark (file exists, was written in the last N minutes,
Detailed Logs on) next to the detected path. On Linux this is the
difference between a support thread and no support thread, because every
launcher lays the prefix out slightly differently, and the first-run
experience should show what was found and where before the player has to
ask. The environment variables (`MTGA_LOG_PATH`, `MTGA_DATA_DIR`) stay as
the scriptable form of the same overrides.

**Tests:** the tray-less branch with `QT_QPA_PLATFORM=offscreen` in
`tests/test_menu_app.py`, which already runs Qt offscreen.

## Phase 3 — The overlay on Linux (Tauri / WebKitGTK)

Tauri builds on Linux against WebKitGTK; the page needs no changes. The
shell needs four things.

**Display server: X11 only, on purpose.** Wayland has no global window
positions, no "always on top" for ordinary clients, and no global hotkeys —
the three things an overlay is made of. So the overlay runs as an X11
client (native X11, or XWayland on a Wayland session, which every desktop
provides). `overlay_launcher.py` sets `GDK_BACKEND=x11` in the child's
environment on Linux; nothing else changes. Arena under Proton is itself
an X11 (XWayland) window, so the two see the same coordinate space.

Two more environment flags belong beside it, learned the hard way by
WebKitGTK apps in general: `WEBKIT_DISABLE_COMPOSITING_MODE=1` and
`WEBKIT_DISABLE_DMABUF_RENDERER=1`. Without them WebKitGTK's accelerated
path renders a black or blank window on a share of NVIDIA and
Wayland/XWayland setups. The overlay draws a few hundred DOM nodes; it
loses nothing by rendering in software. Set them in the launcher's
environment; the Qt tracker app needs neither (it has no web view).

**Arena window probe** (`arena.rs`, the `not(macos|windows)` module):

- Enumerate top-level windows over X11 (`x11rb`, pure Rust, no C deps):
  read `_NET_CLIENT_LIST` on the root window, then each window's
  `WM_CLASS` and `_NET_WM_NAME`. Wine sets `WM_CLASS` to the exe name, so
  match `mtga.exe` / `MTGA.exe` (case-insensitive) with `MTGA` in the
  title as a fallback. Bounds come from `GetGeometry` + `TranslateCoordinates`
  to root; `_NET_ACTIVE_WINDOW` gives frontmost; `_NET_WM_STATE_FULLSCREEN`
  gives the fullscreen flag; `overlay_frontmost` is the active window
  being our own.
- Fallback when there is no X connection (a pure-Wayland compositor
  without XWayland, or the probe failing): scan `/proc/*/comm` and
  `cmdline` for `MTGA.exe` → `running = true`, `frontmost = true`, bounds
  `None`. The overlay then behaves as if "hide when Arena isn't in front"
  were off, which is the current Linux stub's behaviour, so nothing
  regresses.
- Poll cadence and the rest of `start_arena_poll` are shared.

**Window behaviour.** Transparency needs a compositor (every mainstream
desktop has one; bare window managers get an opaque black background —
document it). `set_always_on_top` maps to `_NET_WM_STATE_ABOVE`, which is
honoured over a *windowed* or *borderless* Arena on every major WM. A
*fullscreen* Arena is a different story: most WMs keep a focused
fullscreen window above "above" windows. That is the same limitation
Windows has with exclusive fullscreen, and gets the same advice in the
Settings card: run Arena windowed or borderless. `raise_above_fullscreen`
stays a no-op on Linux; do not try to fight the WM with override-redirect
windows — they lose input and break click-through.
`set_ignore_cursor_events` (click-through) works on X11 through the input
shape extension, which Tauri already uses.

**Hotkeys.** `settings.rs`: add `hotkeys_linux` (defaults identical to
Windows: `Alt+Shift+T` / `Alt+Shift+H`), returned by `Settings::hotkeys()`
on Linux; the Flyout's platform switch shows the Windows labels. The
global-shortcut plugin registers X11 grabs, which work for an X11 client
under XWayland too.

**Multi-monitor.** `dock::monitor_holding` and Tauri's monitor list are
platform-neutral; X11 reports one big virtual screen, which is what Tauri's
`available_monitors()` splits back up via RandR. No changes expected;
verify in the smoke test with Xvfb's single screen.

**Build.** `scripts/build_overlay.sh` already takes the non-Darwin path
(`tauri build --no-bundle` → `build-out/tapps-overlay`). Build deps on
Debian/Ubuntu: `libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf`
(the appindicator one only because Tauri's default features look for it;
the overlay has no tray). Runtime deps: `libwebkit2gtk-4.1-0 libgtk-3-0`.

## Phase 4 — Packaging

- `scripts/build_linux_app.sh`: builds `ui/dist`, runs `build_overlay.sh`,
  then PyInstaller in **onedir** mode from the same `packaging/mtga_tracker.spec`
  (the spec already ships `overlay/` as data; the POSIX executable name is
  in `overlay_launcher._POSIX_EXECUTABLE`). Output:
  `dist/tapps-tracker-<version>-linux-x86_64.tar.gz` (untar and run
  `tapps-tracker`), plus an **AppImage** built with `appimagetool` from the
  same tree with a `.desktop` file and the app icon. AppImage is the
  format that runs on every distro without a package manager and is what
  Linux Steam players expect; a `.deb` can come later if asked for.
- Build on **ubuntu-22.04** so the binary's glibc floor (2.35) covers
  every distro still receiving updates.
- The `.desktop` file: `Name=Tapps Tracker`,
  `Exec=env GDK_BACKEND=x11 tapps-tracker`, `Icon=tapps-tracker`,
  `Categories=Game;Utility;`, `StartupNotify=false`,
  `Keywords=mtg;magic;arena;tracker;`.
- Ship an `install.sh` inside the tarball (and as a one-liner from the
  repo): copies the tree to `~/.local/share/tapps-tracker`, links
  `~/.local/bin/tapps-tracker`, installs the icon into
  `~/.local/share/icons/hicolor/512x512/apps`, writes the `.desktop` entry
  into `~/.local/share/applications`, and runs
  `update-desktop-database` when present. No root, no package manager,
  and the app shows up in GNOME / KDE / Pop launchers immediately. The
  AppImage is the double-click path for people who want one file; the
  tarball plus installer is what the terminal-first Linux crowd expects,
  and it is also what an AUR `-bin` recipe would wrap later if Arch users
  ask.
- Publish `SHA256SUMS` next to the artifacts; Linux users check them.
- Runtime dependency line for the README:
  `libwebkit2gtk-4.1-0 libgtk-3-0 libxcb-cursor0` (Debian/Ubuntu),
  `webkit2gtk-4.1 xcb-util-cursor` (Arch), `webkit2gtk4.1 xcb-util-cursor`
  (Fedora).
- PyInstaller on Linux bundles Qt's XCB platform plugin; the AppImage must
  carry `libxcb-cursor0`'s dependency chain (the Qt 6.5+ requirement that
  bites first-time Linux packagers). Add `libxcb-cursor0` to the CI apt
  list and check the plugin loads in the smoke test.
- Version/DB/settings paths: already XDG under `~/.local/share/mtga-tracker`.

## Phase 5 — CI

`release.yml` matrix gains:

```yaml
- os: ubuntu-22.04
  build: scripts/build_linux_app.sh
  artifact: |
    dist/*.AppImage
    dist/*.tar.gz
```

with an apt step for
`libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev libssl-dev patchelf libxcb-cursor0 build-essential curl wget file`,
Rust via the same `dtolnay/rust-toolchain` step, and `OVERLAY_REQUIRED=1`
like the others. The release notes step lists the AppImage and tarball
beside the `.dmg` and the installer.

One check the smoke job must make: that the overlay binary has the page
*embedded*. A Tauri binary built without the `custom-protocol` feature
looks fine, links fine, and then opens a window that says
"Could not connect to localhost" because it is trying to reach the Vite
dev server. `scripts/build_overlay.sh` goes through the Tauri CLI, which
sets the feature, but a CI step that runs the binary under Xvfb and greps
its log for `page loaded` turns that class of mistake into a red build
instead of a bug report.

While touching the workflow: the macOS Tauri build is arm64-only on
`macos-latest`. `--target universal-apple-darwin` (with both Apple
targets installed) makes the overlay run on Intel Macs too; whether that
matters depends on whether the PyInstaller app itself is ever built
universal, which today it is not — note it as a follow-up rather than
folding it in here.

## Testing without a Linux VM

This is the part that makes the plan workable now rather than after buying
hardware. Three layers, cheapest first; between them they cover everything
except "the overlay floats over a real Arena on a real desktop".

1. **CI is the VM.** A `linux-smoke` job (on pull requests, not only tags)
   that, on ubuntu-22.04: installs the package, runs the full pytest
   suite; runs the tracker headless against a synthetic prefix
   (`tests/fixtures/wine-prefix/…` with a `Player.log` replayed from an
   existing fixture) and asserts the startup banner names the log and the
   card DB and that games land in the DB; builds the overlay and runs it
   under `xvfb-run` with `--log`, asserting the log reaches
   `page loaded`, `geometry: layout=Rail`, and the probe's fallback line —
   the same smoke run used during development of the overlay on macOS.
   Then builds the AppImage and launches it under Xvfb long enough to see
   the dashboard answer `/api/version`. Every one of these already has a
   working equivalent in the repo or in the development sessions; this
   job only strings them together.
2. **A container on the Mac.** `docker run --rm -it -v "$PWD":/w ubuntu:22.04`
   gives the Phase 1/2/4 loop locally in seconds: path discovery, the Qt
   app offscreen, PyInstaller, the AppImage. Xvfb inside the container
   covers the overlay's shell (window creation, geometry, hotkey
   registration, the X11 probe against a fake `MTGA.exe`-classed window
   created with `xdotool`). This is where the X11 probe gets developed:
   `xvfb-run` + a tiny X client that sets `WM_CLASS=mtga.exe` is a
   complete stand-in for Wine's window as far as the probe can tell.
3. **A real desktop, eventually.** UTM (free) on Apple Silicon runs an
   Ubuntu ARM VM well enough for the desktop pieces (tray or no tray,
   Wayland vs X11 sessions, AppImage double-click) but *cannot* run Arena:
   Arena is x86 Windows, and Wine-on-ARM emulation is not a test of
   anything. The first real end-to-end run — overlay over Arena under
   Proton — needs an x86 Linux box with Steam. The practical route is an
   alpha tester from the Linux Arena community with the AppImage and the
   overlay's `overlay.log`; the diagnostics the overlay already writes
   (geometry, probe results, show/hide decisions) were designed for
   exactly this kind of remote debugging.

## Known limits to state up front (README "Linux" section)

- Arena runs through Steam/Proton or Wine; the tracker finds the usual
  prefixes and `MTGA_LOG_PATH` / `MTGA_WINE_PREFIX` cover the rest.
- The overlay is X11 (XWayland on Wayland desktops); needs a compositor
  for transparency; sits above a windowed or borderless Arena, not a
  fullscreen one.
- No system tray on stock GNOME without the AppIndicator extension — the
  app runs from its Live Log window instead.
- Collection export is not available (it reads Arena's memory).
- The AppImage is unsigned, like the other platforms' builds.
- Steam Deck: works in Desktop Mode (it is an X11/XWayland desktop with
  Steam's compatdata layout); Gaming Mode has no place to put an overlay
  window, so the overlay is a Desktop Mode feature there.

## Order of work

| Step | Scope | Verified by | Effort |
| --- | --- | --- | --- |
| 0 | Inode-based log rotation (POSIX) | pytest | ¼ session |
| 1 | Phase 1 paths + `MTGA_LOG_PATH` + Settings path overrides | pytest, any OS | 1–1½ sessions |
| 2 | Phase 5's `linux-smoke` job (tests + headless tracker) | CI | ½ session |
| 3 | Phase 2 Qt tray-less mode + platform `"linux"` | pytest offscreen, container | ½–1 session |
| 4 | Phase 4 tarball + AppImage + `.desktop`; CI artifact | CI, container | 1 session |
| 5 | Phase 3 overlay: `GDK_BACKEND`, `hotkeys_linux`, `/proc` fallback probe | Xvfb smoke in CI | ½ session |
| 6 | Phase 3 X11 probe with `x11rb` | Xvfb + `xdotool` fake window in container/CI | 1–2 sessions |
| 7 | README / QUICKSTART Linux section, Settings wording | review | ½ session |
| 8 | Alpha tester run over real Arena/Proton; fix what the logs show | tester | open-ended |

Steps 1–5 give a Linux release that tracks games, shows the dashboard and
the menu, and shows the overlay over a windowed Arena, all checked in CI.
Step 6 is what makes "hide when Arena isn't in front" and "follow Arena's
monitor" work on Linux; it is separable and can ship in a later release.

## Acceptance

- Fresh Ubuntu 22.04 + Steam + Arena (Proton): download the AppImage, run
  it, play a game — the game appears in the dashboard with names resolved
  from the card DB, without any configuration.
- Same on a Lutris install.
- Overlay opens over a borderless Arena, docks, hotkeys work, hides when
  Arena quits.
- All existing tests pass on Linux in CI; the Linux smoke job is green;
  the release workflow attaches the AppImage and tarball.
