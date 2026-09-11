# Linux implementation plan

Status: **not implemented**. Reviewed against this checkout on 2026-09-10.
The parser and analytics are portable, but Linux auto-discovery, a usable
tray-free desktop controller, the Arena overlay probe, and release packaging
still need work. Explicit `--log-path` and `MTGA_DATA_DIR` can bypass discovery
for source experiments; this is not a validated Linux distribution.

The original plan was a useful outline, but was not ready to implement as
written: it named nonexistent functions, used PySide6 instead of PyQt6,
assumed Linux overlay packaging already existed, overstated XWayland and
AppImage compatibility, and treated Xvfb as desktop validation. The contracts
and gates below replace those assumptions. All new behavior described here
is proposed; nothing in this document is a claim that Linux support ships.

## 1. Scope and support contract

Run the tracker natively on Linux, reading the Windows Arena client's logs
and card database from Steam/Proton or a Wine prefix. Initial release target:
**x86_64, glibc Linux**. ARM builds can exercise portable code but do not prove
Arena/Proton compatibility. Native Wayland overlay integration, collection
memory export, a Flatpak package of the tracker, and Steam Deck Gaming Mode
are outside the first release.

| Environment | Tracker/dashboard/controller | Overlay target |
| --- | --- | --- |
| X11 desktop with compositor | Supported after validation | Follow Arena, dock, hide/show, shortcuts, click-through |
| Wayland desktop with XWayland and Arena using X11 | Supported after validation | Experimental until tested on each compositor; no universal shortcut or stacking guarantee |
| Wayland without a usable X display, or Arena using native Wayland | Supported after validation | Disabled with an explanation; dashboard remains available |
| Headless session | `--no-gui` with explicit inputs | Not launched |
| Steam Deck Desktop Mode | Tester target, not an initial support claim | Validate separately on the actual device |

Primary acceptance targets are Ubuntu 22.04 and 24.04 x86_64 with Steam/
Proton, plus one Lutris/Wine install. Debian 12 is a packaging compatibility
check. Treat other distributions, launchers, and Steam Deck as unverified
until their results are recorded. A tracking-only alpha can precede the
complete release; label its missing overlay support explicitly.

## 2. Current implementation map

| Area | Actual entry point and current gap |
| --- | --- |
| Log discovery | `MTGALogParser._find_log_path()` in `log_parser.py` supports Windows/macOS only; move new path discovery into `paths.py` and delegate from this wrapper |
| Card DB discovery | `paths.get_mtga_raw_card_db_folders()` supports overrides, Unity log headers, Steam libraries, and platform defaults; no Linux branch |
| Header parsing | `_unity_data_dirs_from_log_head()` recognizes subsystem, localization, and older Mono lines; `mtga_raw_dir_from_player_log()` reads 64 KiB and tries `Player-prev.log` |
| Database selection | `CardDatabase._find_mtga_card_database_paths()` sorts all discovered files by mtime; folder precedence alone cannot isolate multiple installs |
| Rotation | `_read_new_entries()` resets only when size shrinks; replacement with a larger file can skip events |
| Data/settings | Frozen tracker data already uses `XDG_DATA_HOME/mtga-tracker` or `~/.local/share/mtga-tracker`; source runs use repo data; `MTGA_TRACKER_DATA_DIR` overrides data location |
| Desktop | `menu_app.py` uses **PyQt6**; assumes a tray, with the old Qt Live Log hidden as a debug fallback; Linux currently gets the monochrome icon |
| Platform payload | `settings_api._platform_info()` returns `other` for Linux; collection export is already disabled there |
| Deck Finder | Dashboard integration is portable; `_launch_linux_terminal()` exists but its `-e` invocation and frozen child environment need real terminal tests |
| Overlay shell | `arena.rs` Linux stub returns `ArenaStatus::default()` (not running); Linux is not a functional follow/focus implementation |
| Overlay staging | `build_overlay.sh` has a non-Darwin build into `build-out/tapps-overlay`; launcher knows that name |
| Overlay packaging | The spec stages **Windows** overlay data only; macOS script copies a nested app into `Contents/Helpers`. Linux inclusion must be added |
| Release | macOS/Windows builds only, one tracker executable with `--deck-finder`; no separate test workflow in this checkout |

No analytics schema change is needed for basic Linux support. Keep existing
app/data identifiers, one selected `--db` for both tracker and dashboard,
and all tracked/untracked-game and hidden-information rules.

## 3. Phase 0 — Prove the build baseline and test harness

Before substantial GUI work, add a PR/manual Linux validation job, initially
running tests and producing private workflow artifacts. Install the existing
`.[dev,gui,build]` extras, dashboard/overlay npm lockfiles, and Rust lockfile.
Record exact Python, PyQt6/Qt, Node, Rust, WebKitGTK and build-image versions.
Use Python 3.12 as in release CI and a Node version satisfying both lockfiles.

Start with an Ubuntu 22.04 build image. It is a candidate baseline, **not** a
guarantee of compatibility: inspect GLIBC/GLIBCXX requirements of every ELF,
including the installed Qt wheels, PyInstaller runtime, Rust binary, and
WebKit dependencies. Newer wheels can raise the floor even when the build
host is old. If necessary select compatible dependency versions through a
reviewed constraint file or explicitly raise the advertised minimum OS.
Tauri requires an oldest-supported build base that also has WebKitGTK 4.1;
it lists Ubuntu 22.04 and Debian 12 as examples. [Tauri AppImage guidance](https://v2.tauri.app/distribute/appimage/).

Use the distro-specific packages in [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/)
as the starting point: WebKitGTK 4.1 headers, build tools, OpenSSL, libxdo,
AppIndicator, and librsvg. Add `patchelf`, Qt's XCB runtime dependencies,
fonts, Xvfb, a lightweight EWMH window manager, a compositor, D-Bus session
support, and X11 fixture tooling. Determine the final runtime list by ELF
inspection and clean-image launches, not by copying the build apt list.

Gate: Python tests, frontend checks, overlay Rust compilation/tests, and a
minimal native overlay window succeed in CI. This does not yet prove Arena
support. Keep temporary fixtures, settings, DBs, logs, and ports isolated
from developer data. Never stop an active developer tracker for these tests.

## 4. Phase 1 — Discover one coherent Arena installation

### Inputs and precedence

Put discovery and path translation in `paths.py`; callers consume its result.
The proposed `MTGA_LOG_PATH` and `MTGA_WINE_PREFIX` variables do not exist yet.
Define their behavior consistently for console, GUI, and frozen entry points:

1. Explicit CLI `--log-path` wins.
2. Proposed `MTGA_LOG_PATH` wins over a saved Settings log override.
3. Proposed saved log override wins over discovery.
4. An explicit `MTGA_WINE_PREFIX`, then `WINEPREFIX`, restricts automatic
   prefix discovery. Invalid explicit inputs produce an actionable error
   rather than silently tracking a different installation.
5. Without explicit selection, enumerate known roots and select the newest
   readable `Player.log`; ties use deterministic discovery order. Retain the
   selected installation for the session. Never switch logs during a match
   because another prefix's mtime changed.

Keep the existing exclusive `MTGA_DATA_DIR` behavior. A proposed saved card
folder override comes after it and before inferred folders. An explicit
log and explicit prefix that conflict must produce an explanation before
using a guessed translation. Store provenance (explicit/header/Steam/prefix),
log path, prefix, and install roots together so the card database comes from
that installation. Resolve newer set databases **within the selected install**;
do not let an unrelated prefix win the global newest-file sort. Preserve
Windows/macOS behavior with regression fixtures when changing selection.

### Bounded candidates

| Launcher | Candidate roots and relationship |
| --- | --- |
| Steam | `~/.steam/steam`, `~/.steam/root`, `~/.local/share/Steam`, Flatpak `~/.var/app/com.valvesoftware.Steam/.local/share/Steam`; deduplicate resolved symlinks and read `libraryfolders.vdf` |
| Proton | Every registered library's `steamapps/compatdata/2141910/pfx` first, then bounded `compatdata/*/pfx` candidates for non-Steam shortcuts; game installs usually live outside the prefix in `steamapps/common` |
| Lutris | Known prefixes directly under `~/Games`, plus configured roots discovered from launcher metadata when supported; do not treat its application-data directory as a guaranteed prefix |
| Bottles | `~/.local/share/bottles/bottles/*` and `~/.var/app/com.usebottles.bottles/data/bottles/bottles/*` |
| Heroic | `~/Games/Heroic/Prefixes/*/pfx` and configured prefix/install pairs; custom paths use overrides |
| Wine | Explicit prefix, then `~/.wine` |

A prefix must contain `drive_c`. Search `drive_c/users/*/AppData/LocalLow/`
`Wizards Of The Coast/MTGA/Player.log`; do not hardcode `steamuser`. Use
Steam's app manifest install directory where available, with structural
`MTGA_Data/Downloads/Raw` validation for fallbacks. Known Windows install
names under Program Files and Program Files (x86) are candidates, not facts.
Do not scan arbitrary mounted disks or recursively traverse the user's home.
Unregistered libraries use explicit inputs; any later removable-drive search
needs an opt-in, bounded design. Ignore unreadable, missing, and malformed
automatic candidates, deduplicate aliases, and prevent symlink loops.

### Wine path translation

Apply translation to all three existing Unity header patterns. Resolve drive
letters through `<prefix>/dosdevices/<letter>:` first; use `drive_c` for `C:`
only when that mapping is absent. A `Z:` mapping is not guaranteed to be `/`:
use the actual mapping or leave it unresolved. Handle mixed separators,
spaces, Unicode, symlinks, and deleted targets. Reject drive-relative paths
such as `C:foo`, unresolved UNC/device paths, and ambiguous case matches.
For case-insensitive Wine paths on Linux, prefer exact components and then a
unique case-insensitive match; never lowercase the native path wholesale.

Flatpak launcher paths may refer to a sandbox namespace, not the host root.
Map only recognized launcher layouts and verified host paths; an inaccessible
or ambiguous mapping needs a manual override. Do not invoke `winepath` in an
arbitrary prefix, create prefixes, or request root. The tracker is a host
process in this release; a Flatpak **tracker** would need a separate permission
design. [Flatpak filesystem isolation](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

### Rotation and discovery tests

On POSIX, compare `(st_dev, st_ino)` using `fstat()` on the opened file, as
well as the existing shrink check. Reset offsets and the buffered entry on
replacement, even if its size is equal or larger. Tolerate missing-file
windows during rename/recreate. Preserve startup-tail behavior and avoid
replaying a completed game when only discovery is retried.

Add minimal `tmp_path` tests for every launcher, custom libraries, different
Wine usernames, conflicting/stale overrides, multiple installations, missing
card DB then later appearance, ambiguous case, broken drive links, all header
patterns, and `Player-prev.log`. Test append, truncation, equal/larger
replacement, deletion/recreation, and partial multiline JSON at rotation.
Use a synthetic read-only Arena card DB; assert no files are written into it
or into prefixes. Run existing Windows/macOS discovery regressions too.

Gate: source `--no-gui` tracks a synthetic complete match into a temporary DB,
with card names from the selected prefix and no duplicate game after rotation.

## 5. Phase 2 — Desktop control and setup

Use existing **PyQt6**, not a second Qt binding. Detect tray availability.
When absent, show a small persistent controller window exposing Live
Scoreboard, Dashboard, Deck Finder, Open Data Folder, overlay controls,
Start/Stop Tracking, Settings, and Quit. Reuse the same QActions as the tray;
keep the scoreboard in the browser. Closing the sole controller must have
explicit quit semantics and orderly tracker/DB cleanup, never hide the only
way to control a running process. Handle a tray becoming available later
without duplicating controllers. Use the colored icon on Linux.

Report `platform.system: linux` through `_platform_info()` and keep collection
export hidden/unsupported. Expose the chosen log, prefix, card DB, and why
they were selected in Settings, with redacted display paths. Distinguish
missing, unreadable, and stale logs from confirmed absence of Detailed Logs:
an idle log alone cannot prove logging is disabled.

Coordinate log/card-folder override settings with
[remaining install-discovery work](MTGA_INSTALL_DISCOVERY.md). The browser
cannot freely choose an arbitrary native path: define a validated text input
with native picker integration only where available. Show validation errors
and a **takes effect at the next tracker start** notice. Do not restart an
active tracker when saving. Route persistence through the existing settings
API; analytics GET routes stay read-only. With no log, retain the controller
and an actionable status rather than exiting to an invisible failure.

Exercise browser opening, clipboard export, folder opening, and the terminal
Deck Finder in the frozen build. `gnome-terminal`, `konsole`, `xterm`, and
`x-terminal-emulator` do not have interchangeable argument contracts; test
argument vectors and paths with spaces. Dashboard Deck Finder remains usable
if there is no terminal emulator.

Gate: offscreen Qt unit tests cover action wiring and tray absence. Actual
GNOME without a tray extension and KDE with a tray validate reachability,
close/quit behavior, second launch, browser opening, and user data isolation.
Offscreen tests do not establish window-manager behavior.

## 6. Phase 3 — Overlay capabilities and graceful failure

Start with X11. Check that an X display is usable before spawning the overlay;
`DISPLAY` being set is insufficient. Set `GDK_BACKEND=x11` for the overlay
child only, consistently for its first and subsequent control launches.
Without a usable X display, do not launch-loop or invent a process-only
fallback that cannot render a window. Keep the tracker and dashboard running
and expose an unavailable reason in Settings.

Wayland does have a GlobalShortcuts portal; it is incorrect to say global
shortcuts do not exist there. The current `global-hotkey` backend documents
Linux **X11 only**, and an XWayland grab is not a promise of shortcuts while
any native Wayland app has focus. Portal integration is separate work.
[global-hotkey support](https://docs.rs/global-hotkey/latest/global_hotkey/),
[GlobalShortcuts portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html).

### Probe, input and geometry

- Add a Linux-only `x11rb` dependency/module. Read `_NET_CLIENT_LIST`,
  `WM_CLASS`, window title, active window, mapped/minimized state, geometry
  and root coordinates. Handle windows disappearing between requests.
  Prefer an Arena class/process match; title alone is weak evidence and
  must not attach to a browser showing an Arena page.
- Correlate `_NET_WM_PID` where usable. A bounded same-user `/proc` scan can
  distinguish running from absent if the X connection works but no Arena
  window is mapped; handle permission errors, exit races and launcher/helper
  processes. A found process is **not** proof of focus or geometry. Do not
  synthesize `frontmost=true` from process existence. Expose unknown status
  and allow explicit manual floating mode if following is unavailable.
- Specify coordinate conversions: X11 root physical pixels to the units
  expected by `dock.rs`/Tauri. Test negative monitor origins, work areas,
  fractional scale, monitor removal, primary-display changes, and a panel
  changing width. Xvfb's single screen does not validate mixed DPI.
- Probe once per second with bounded work and connection recovery. Existing
  game activity comes from `/api/overlay`, never from the process probe.
  Preserve waiting/final/mid-game states, API port forwarding and ETags.
- Add `hotkeys_linux` with backward-compatible serde defaults; keep existing
  macOS/Windows preferences intact. Surface registration conflicts. Menu/
  controller actions must remain reachable if shortcuts fail, especially
  when click-through is enabled. Pin and click-through remain separate.
- Validate no focus stealing, hovering, dragging, input pass-through,
  transparency and hide/show on the actual desktop. Fullscreen stacking and
  XWayland visibility depend on the compositor; record results and recommend
  windowed mode where necessary. Do not promise all borderless modes work.

Do not unconditionally disable WebKit acceleration. First reproduce blank/
black windows with the shipped WebKitGTK version, then test a narrowly scoped
renderer workaround as an opt-in child environment setting. Measure its
impact on transparent rendering, card previews, CPU and memory. Never disable
WebKit's sandbox as a workaround.

Gate: fake Arena windows under **Xvfb + EWMH WM + compositor + D-Bus** exercise
focus, minimized/closed windows, geometry, hotkey conflicts and reconnects.
A real x86 Linux Arena/Proton session is required before advertising overlay
support. Include an extended session and record resource growth and missed
input; compare idle/playing/hidden states rather than inventing an RSS claim.

## 7. Phase 4 — Frozen package and installation

Build a **onedir tarball first**, then an AppImage from the same verified tree.
Proposed names: `tapps-tracker-<version>-linux-x86_64.tar.gz` and
`tapps-tracker-<version>-linux-x86_64.AppImage`. Preserve the internal
`MTGA Tracker` executable and add a quoted `tapps-tracker` launcher if desired;
Deck Finder stays its `--deck-finder` mode. Add Linux overlay data explicitly
to the PyInstaller spec and verify the launcher locates the extracted binary.
CI must fail if `OVERLAY_REQUIRED=1` and the binary is absent or not executable.

An AppImage container does not automatically collect Qt, WebKitGTK, GTK,
GStreamer/helper processes, schemas or their dependency chains. Define an
AppDir bundling strategy, pinned tools, license notices and an explicit
host-library allowlist. Inspect `ldd`/ELF dependencies and load Qt's platform
plugins and WebKit subprocesses on clean supported systems. Include the Qt
XCB plugin's actual dependencies, including xcb-cursor where required; also
validate the chosen Qt Wayland plugin if the controller uses native Wayland.
Do not claim an AppImage runs on every distribution.

PyInstaller modifies `LD_LIBRARY_PATH`; audit every child launch. Restore the
host environment for system browsers/folder openers/terminals, and construct
an explicit environment for the independently built GTK overlay so bundled
Qt libraries cannot accidentally replace its runtime. Include Qt plugin-path
variables in that audit and test the **frozen** build, not just source runs.
[PyInstaller subprocess environment guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).

Use a no-root installer into a dedicated application directory such as
`~/.local/share/tapps-tracker`, with a launcher under `~/.local/bin`, icon,
and `.desktop` entry. Keep data separate in `mtga-tracker`'s existing XDG
location. Quote `Exec` paths correctly, honor relevant XDG locations, and
set GTK environment flags in the overlay child, not globally in `.desktop`.
Keep the executable permission in archives and show how to enable it for a
downloaded AppImage. Test FUSE mounting and an extraction fallback;
AppImages can need FUSE support and containers often require extraction.
[AppImage FUSE guidance](https://docs.appimage.org/user-guide/troubleshooting/fuse.html).

Define upgrade/uninstall behavior: replace application files only, preserve
DB/settings/exports, remove only owned launchers and icons on uninstall, and
refuse to replace an active running installation without a user-directed
shutdown. Never install over the user data directory. Test paths containing
spaces, read-only AppImage contents, custom `XDG_DATA_HOME`, and two installed
versions against the existing instance lock. Publish SHA256 checksums.

Gate: a fresh user can install, start, track, quit, upgrade, and uninstall
both artifact forms without root or data loss. Missing runtime libraries
produce a diagnostic obtainable outside a terminal-launched session.

## 8. Phase 5 — Release integration and evidence

Add Linux to `release.yml` only after the preceding gates pass. Use the same
full tag history, version-from-tag override and `OVERLAY_REQUIRED=1` as the
other platforms. Tag runs attach artifacts/checksums to a **draft** release;
manual branch runs upload workflow artifacts. Keep publishing a human step.
Run macOS and Windows regressions after shared launcher/path/spec changes.

Required automated checks:

- Existing full Python suite with the documented headless ignore/deselect;
  separate `QT_QPA_PLATFORM=offscreen` menu tests with any needed fixtures.
- Dashboard: `npm ci`, `npx vitest run`, `npx tsc -b`, lint and build.
- Overlay: `npm ci`, tests, build, Rust tests, and screenshot fixtures.
- Prefix replay: sanitized complete-match input, temporary DB, expected
  outcome/seats/deck/card names, and no duplicate history after rotation.
- Frozen tarball and extracted AppImage: `/api/version` and actual dashboard
  assets, custom port, writable data paths, bundled Deck Finder providers,
  overlay API connection and local embedded page with **no Vite server**.
- Overlay smoke: enable diagnostics with `--log <temp-file>`, verify a
  loaded UI and expected fixture content/geometry, then close cleanly.
  A `page loaded` log marker alone is insufficient evidence of a working UI.

Required desktop evidence records distro/release, session/compositor,
launcher/Proton version, GPU/driver, display scaling and artifact hash. Cover
Steam and Lutris, GNOME without tray and KDE with tray, X11 and XWayland,
windowed/borderless/fullscreen, Arena alt-tab/minimize/quit/relaunch, and
mixed-DPI monitors. Flatpak Steam/Bottles require an actual host-path test
before claiming their automatic discovery works. Real desktop results remain
pending until a tester or an x86 Linux host supplies them; CI cannot substitute.

## 9. Delivery order and completion

| Milestone | Deliverable | Exit evidence |
| --- | --- | --- |
| A | Build baseline and PR validation harness | Tested dependency floor; native shell smoke |
| B | Paths, overrides and rotation | Cross-platform unit tests plus coherent-prefix replay |
| C | Tray-free PyQt6 controller and setup | Offscreen tests plus GNOME/KDE control smoke |
| D | X11 overlay and capability fallback | WM-backed CI fixtures plus real Arena/Proton session |
| E | Tarball, AppImage, installer lifecycle | Clean-system launches, upgrade/uninstall and version checks |
| F | Draft release and user documentation | Required platform matrix reviewed; maintainer publishes |

Do not estimate the remaining work solely in coding sessions: dependency
compatibility, compositor behavior and access to a real Arena test host are
release gates with uncertain duration. Pure path/state work can start from
this plan now. Baseline proof precedes packaging commitments; desktop evidence
precedes support claims. Update README/QUICKSTART with Linux instructions only
when the corresponding capability is delivered and verified.
