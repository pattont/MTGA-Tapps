# In-app auto-update

Status: proposal, researched 2026-10-11 against `auto-update` @ `7071c74`. Nothing is
implemented yet. The three research reports this plan distills live in
[`auto-update/`](auto-update/): the industry survey and trust model
([01](auto-update/01-industry-research.md)), the per-OS install and relaunch mechanics
with the tested macOS swap helper ([02](auto-update/02-platform-mechanics.md),
[`tapps_mac_swap.sh`](auto-update/tapps_mac_swap.sh)), and the file-by-file codebase
integration ([03](auto-update/03-codebase-integration.md)). Each report labels its
claims as verified against a cited source, tested on this machine, or inferred.

## 1. The answer

**Build our own small updater in Python and keep today's packaging.** Every GitHub
Release gets a static, signed manifest (`latest.json` + `latest.json.sig`). The app
fetches it from `https://github.com/pattont/MTGA-Tapps/releases/latest/download/latest.json`,
which is not the REST API (no 60 requests/hour limit) and never serves drafts or
prereleases. The update payload is the installer users already download: the Inno
`setup.exe` on Windows, run silently after the app has exited, and on macOS a new
`ditto` zip of the `.app` that a detached helper swaps into place after the app exits.
Linux later reuses the macOS path with an AppImage or tarball.

The user sees this:

| Moment | Dashboard (bottom-left of the sidebar) | Tray menu |
| --- | --- | --- |
| Newer release published | "Update v0.6.6 available", download starts by itself | "Update available: v0.6.6…" |
| Downloading | "Downloading v0.6.6 — 42 %" with a progress bar | "Downloading update… 42 %" |
| Downloaded and verified | **"Restart to update"** (accent pill) | "Restart to Update (v0.6.6)" + one notification |
| Clicked during a game | "Finish your game first" with "Install after this game" | same, as a dialog |
| Installing | "Restarting…"; the tab reloads itself when the new version answers | "Restarting…" |
| First launch after | "Updated to v0.6.6 · What's new" once | notification |

Nothing is installed until the file is fully downloaded, its size and SHA-256 match the
signed manifest, and (macOS) the staged bundle passes `codesign --verify`. The hand-off
itself takes seconds: the old process stops its services and exits, the helper waits for
the PID to vanish, swaps or runs the installer, and relaunches. Settings → Updates gets
two toggles: **Check for updates** (default on) and **Install updates automatically when
no game is running** (default off). The second is the explicit approval the
"never restart the tracker without approval" invariant requires.

### Why this and not an off-the-shelf updater

| Option | Verdict | Reason |
| --- | --- | --- |
| **Hand-rolled Python + signed manifest** (chosen) | Do it | Keeps PyInstaller, Inno (`AppId`, install paths), DMG and the draft-release gate. No new toolchain. The manifest signature is the only authenticity check available to an app with no Apple Developer ID and no Authenticode certificate. Roughly 1.5–3 focused weeks including real-machine testing. |
| Velopack (has a Python SDK, deltas) | No | Verifies only a hash from the same feed, no signature (velopack #975). Would move Windows installs off Inno to its own layout. Its GitHub source uses the rate-limited API; the API-free mode loses deltas. macOS + PyInstaller is unproven. Needs .NET in CI. |
| tufup (TUF) | No | Copies files over the install directory in place, which Apple advises against and which bypasses Inno. TUF metadata expires and must be re-signed periodically. One maintainer. |
| Sparkle + WinSparkle | No | Two native frameworks inside PyInstaller, nothing for Linux, UI outside our dashboard. |
| Tauri updater via the overlay | No | It updates the bundle containing the Tauri binary, i.e. the nested overlay, not the tracker. Needs SemVer. We copy its manifest + signature idea only. |
| Electron-style (Squirrel, electron-updater) | No | Electron-only and require a signed macOS app. |
| PyUpdater | No | Archived in 2022. |

No MTG Arena tracker is a self-updating Python app (Untapped and MTGA Pro are Electron,
17Lands uses ClickOnce on Windows and `pip` on Mac, Arena Tutor is Overwolf), so there is
no direct model to copy. The closest prior art for Windows is VS Code, which also
self-updates by running the next Inno `setup.exe` silently.

## 2. Findings that shaped the design

These came out of the code and from experiments, and several contradict assumptions in
the request.

- **The existing browser check misses hotfix versions.** `ui/src/updateCheck.ts` compares
  only `X.Y.Z`, so 0.6.5.3 and 0.6.5.4 compare equal and rc suffixes are ignored. The new
  updater compares PEP 440 versions (`packaging.version`, present in the environment
  today only transitively, so it must become a declared dependency).
- **The browser cannot do the check anyway.** `github.com` release-download redirects
  carry no CORS header, so the check must move to the Python process, which also makes
  it the single source of truth for every open tab and the tray.
- **Existing installs cannot auto-update.** Users on 0.6.5.3 still run the browser
  check. The first updater-capable release must be installed by hand; later ones update
  in place. Keep the release page and asset names stable so their link keeps working.
- **A restart drops the log gap.** The tracker resumes from the end of `Player.log`, so
  a match that starts during the restart is a mid-game attach and is never saved, and a
  deck submission sent in the gap weakens attribution. Unattended auto-install therefore
  requires **Arena not running**, not just "no game". A manual restart with Arena open
  gets a confirmation.
- **`live_status.in_game` is per game.** It reads 0 between best-of-three games. The gate
  also requires no game seen or ended in the last 120 s and, from in-process state,
  `arena_match_over` for Bo3.
- **Two instance locks.** `SingleInstanceGuard` and the legacy Qt `QLockFile`. A relaunch
  that races the old process shows "already running". The relaunched process must retry
  both for up to 60 s when started with `--after-update`.
- **Migrations are not atomic as a group.** `apply_pending_migrations` commits once at the
  end, but DDL autocommits, `executescript` commits first, and several migrations commit
  internally. A failing migration leaves earlier ones committed, startup is refused, and
  the next launch retries. There is no downgrade path. **The pre-update backup is the only
  recovery path.** The next release carries migrations 32–35, so this matters now.
- **Downloads carry no OS warning.** Files written by Python get no `com.apple.quarantine`
  (tested on macOS 27) and no Windows Mark-of-the-Web, and `CreateProcess` ignores
  SmartScreen. Updates will install with **no Gatekeeper or SmartScreen prompt at all**.
  Good for UX, but it means that without our own signature a compromised GitHub account
  could push code to every running copy silently. A checksum in the same release only
  catches corruption.
- **macOS zip, not DMG, and only `ditto`.** `ditto -c -k --norsrc --noextattr --noacl
  --noqtn --keepParent` round-trips the ad-hoc signature and all 63 symlinks of the bundle
  with zero quarantine attributes. Python's `zipfile` and plain `zip` drop the symlinks
  and break the signature. The DMG works as a fallback (`hdiutil attach -readonly
  -nobrowse`), but leaves mount state to clean up.
- **The overlay lives inside the thing being replaced** (`_internal\overlay\` on Windows,
  `Contents/Helpers/` on macOS). It must be stopped before the swap, without persisting
  `enabled=false` (exit code 23 is reserved for the user's own Quit). On macOS a stale
  overlay's argv path would name the new bundle after the swap and the new tracker would
  adopt it as its own.
- **Windows all-users installs are 32-bit mode.** The installer lacks
  `ArchitecturesInstallIn64BitMode`, so they live in `Program Files (x86)` with the HKLM
  uninstall key in the `WOW6432Node` view, and a silent upgrade there still needs a UAC
  consent. Per-user installs (the default) upgrade fully silently.
- **Ad-hoc signatures change every build.** The designated requirement is the cdhash, so
  any macOS TCC grant (Terminal automation for Deck Finder, folder access for backups) is
  re-prompted after each update. The overlay needs no TCC grant. Signing every release
  with one stable self-signed certificate through the existing `MACOS_SIGN_IDENTITY` hook
  fixes this; it is a separate change.
- **`tasklist` helpers lack `CREATE_NO_WINDOW`.** The Arena probe the updater needs must
  use the overlay launcher's detached kwargs or it will flash a console on every poll.

## 3. Release side

### 3.1 Manifest

`latest.json`, attached to every release, same name every time (the `latest/download`
URL selects by name). Payload URLs are pinned to the tag so manifest and payloads always
come from one release even if "latest" moves mid-download.

```json
{
  "schema": 1,
  "version": "0.6.6",
  "tag": "v0.6.6",
  "released_at": "2026-10-20T18:00:00Z",
  "notes_url": "https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.6",
  "minimum_version": null,
  "mandatory": false,
  "assets": [
    {"platform": "macos",   "arch": "arm64", "kind": "app-zip",      "name": "MTGA-Tracker-0.6.6-macos.zip",   "url": "https://github.com/pattont/MTGA-Tapps/releases/download/v0.6.6/MTGA-Tracker-0.6.6-macos.zip",   "size": 0, "sha256": "…"},
    {"platform": "macos",   "arch": "arm64", "kind": "dmg",          "name": "MTGA-Tracker-0.6.6.dmg",         "url": "…", "size": 0, "sha256": "…"},
    {"platform": "windows", "arch": "x64",   "kind": "inno-setup",   "name": "MTGA-Tracker-0.6.6-setup.exe",   "url": "…", "size": 0, "sha256": "…"},
    {"platform": "windows", "arch": "x64",   "kind": "portable-zip", "name": "MTGA-Tracker-0.6.6-windows.zip", "url": "…", "size": 0, "sha256": "…"}
  ]
}
```

`latest.json.sig` is a detached Ed25519 signature over the exact manifest bytes.
`minimum_version` ("below this, link out instead of installing") and `mandatory`
(sticky pill, no skip) are the kill switches for a release whose hand-off changed.

### 3.2 CI changes (`.github/workflows/release.yml`, build scripts)

1. `build_macos_installer.sh`: after the DMG, create
   `dist/MTGA-Tracker-<ver>-macos.zip` with the `ditto` command above and add it to the
   macOS artifact glob.
2. Both build legs: `prerelease: ${{ contains(github.ref_name, '-') }}` and
   `make_latest` false for such tags, so an rc can never become `releases/latest`. Always
   upload Actions artifacts too, because a draft's assets cannot be downloaded back by tag.
3. New job `manifest` (`needs: build`, tags only): download both artifact sets,
   run `scripts/make_update_manifest.py` (stdlib only, imports `parse_version` from the
   app so CI and client agree, fails if any asset filename's version differs from the
   tag), and attach `latest.json` and `SHA256SUMS` to the same draft.
4. New maintainer script `scripts/sign_update_manifest.py`: downloads the draft's
   `latest.json` and assets with `gh`, recomputes every hash, refuses on mismatch, signs
   with the private key kept **off GitHub** (passphrase-protected file or hardware
   token), uploads `latest.json.sig`. Then the maintainer publishes. This turns the
   existing human "publish" gate into a cryptographic one.
5. Turn on GitHub **immutable releases** for the repo: once published, assets and the tag
   cannot change. It fits the draft-then-publish flow and costs nothing.
6. `docs/RELEASING.md` gains the step "sign the manifest, check `latest.json` and
   `SHA256SUMS` are on the draft, then publish".

Manual (non-tag) runs never produce a manifest; their `X.Y.Z.devN+g…` versions make the
client report "development build" and never auto-update.

### 3.3 Signing

- Key: Ed25519. Generate with `openssl genpkey -algorithm ed25519`; sign with
  `openssl pkeyutl -sign -rawin`. Embed the primary public key plus an offline backup key
  in the app (`updater.py`), so the key can be rotated; losing both means existing users
  can never auto-update again (Tauri's documented failure mode).
- Verification: the frozen bundle has neither `cryptography` nor PyNaCl. Vendor a
  verification-only pure-Python RFC 8032 implementation (about 100 lines on
  `hashlib.sha512`; roughly half a second per verify, once every six hours on the
  updater thread) with the RFC test vectors and an `openssl`-cross-checked fixture in
  the tests. Adding `cryptography` instead costs about 8–10 MB per artifact; decide in
  the spike.
- Verify the signature **before** parsing the manifest. Verify size and SHA-256 after
  the download **and again immediately before** the hand-off, from a directory only the
  user can write.

## 4. Client side

### 4.1 Modules

| File | Role |
| --- | --- |
| `src/mtga_tracker/updater.py` (new) | Pure logic and the singleton `UpdateManager`: PEP 440 comparison, manifest parsing (strict: schema 1, https URLs on the host allow-list `github.com` / `objects.githubusercontent.com` / `release-assets.githubusercontent.com`, 64-hex sha256, size > 0), Ed25519 verify, `detect_install_kind`, `select_asset`, resumable download with streaming SHA-256, state machine, scheduler thread, busy gate, the install sequence (§6) |
| `src/mtga_tracker/update_install.py` (new) | `install_and_restart(plan)` per OS: Windows detached `setup.exe` spawn and registry detection, macOS stage + helper spawn, Linux later |
| `src/mtga_tracker/update_api.py` (new) | `GET /api/update`, `POST /api/update/{check,download,install,skip,acknowledge}` |
| `src/mtga_tracker/settings.py`, `settings_api.py` | `updates` section, `POST /api/settings/updates` |
| `src/mtga_tracker/backup.py` | `pre-update` safety backup tag, `"updates"` in `LOCAL_SETTINGS_SECTIONS` |
| `src/mtga_tracker/live_api.py`, `paths.py`, `deck_native_api.py`, `collection_api.py`, `backup_api.py` | `game_activity()`, `arena_process_running()` (with `CREATE_NO_WINDOW`), `job_active()` / `job_running()` / restore-in-flight flag for the gate |
| `src/mtga_tracker/app.py`, `single_instance.py`, `menu_app.py` | `UnifiedLauncher.start_updater`, `--after-update` / `--updated-from` / `--update-failed`, lock retry, tray item + notification, Qt-thread exit request |
| `src/mtga_tracker/dashboard.py` | GET branch beside `/api/version`; POST branch after the Deck Manager branch, copying its Origin + Content-Type guard (the `/api/settings` POSTs have none, and this one restarts the app) |
| `ui/src/updateStatus.ts`, `ui/src/components/UpdateIndicator.tsx`, `AppShell.tsx`, `SettingsPage.tsx`, `styles.css` | sidebar pill (expanded footer slot, collapsed footer icon with progress ring), Settings → Updates form, reload-on-version-change; `ui/src/updateCheck.ts` is deleted |
| `scripts/make_update_manifest.py`, `scripts/sign_update_manifest.py` | release side |
| `packaging/windows_installer.iss` | `/WAITPID`, silent relaunch, failure relaunch, `CloseApplicationsFilter` (§5.1) |

Where the timer lives: a daemon thread inside `UpdateManager`, started by a new
`UnifiedLauncher.start_updater()` from both the menu app's `start()` and
`_run_without_gui`. Not the tracker loop (the user can stop the tracker, and in
`--no-gui` the loop is the main thread), not a Qt timer (the menu is optional; the tray
only mirrors state through a listener, like the overlay), not the dashboard server (the
dashboard-only entry point reports `unsupported`). Deck Finder mode returns before a
launcher exists. `MTGA_TRACKER_DISABLE_UPDATES=1` is the kill switch for CI and
`scripts/preview_deck_manager.py`.

Cadence: first check 90 s after start (clear of startup maintenance), then every 6 h with
jitter, with `If-None-Match`. The worker wakes every 15 s only while a verified update is
ready and auto-install or "install after this game" is armed. Source runs, portable
Windows zips, moved installs, and translocated or DMG-mounted macOS bundles show the
link-out pill (today's behavior) and never download.

### 4.2 State machine

```
idle -> checking -> up_to_date | available | error
available -(newer, installable, not skipped)-> downloading -> ready | error
ready -(user click, or auto gate passes)-> installing -> process exits
check=false -> disabled ; not frozen / portable / dashboard-only -> unsupported
error -> checking on the next tick or POST /api/update/check
```

`GET /api/update` returns `state`, `current_version`, `latest_version`, `notes_url`,
`install_kind`, `can_install` + `reason`, `progress {received,total,fraction}`, `error
{code,message}`, `blocked_by [...]`, `pending_install`, `auto_install`, `skipped`,
`just_updated {from,to,notes_url,ok}`. On startup the manager re-validates a cached
download and goes straight to `ready` if the file still verifies. A downgrade is never
offered. The UI polls every 15 s (skipped while the tab is hidden), every 1 s while
downloading or installing, and while installing also polls `/api/version` and reloads
when the version changes.

### 4.3 Settings

`settings.json` gets user preferences only; runtime state (`last_check`, ETag, download
journal, acknowledged version, last result) goes in `<data dir>/updates/state.json`,
because `backup.update_settings_section` is a non-atomic read-modify-write and a
background thread must not race a user's Settings save.

```json
"updates": {"check": true, "auto_install": false, "channel": "stable", "skipped_version": null}
```

`"updates"` joins `backup.LOCAL_SETTINGS_SECTIONS` so restoring a laptop backup on a
desktop never switches auto-install on. The Settings page gets a section between Startup
and the overlay with the two checkboxes, a status row (current / latest, Check now,
Restart to update, Skip this version), and a hint explaining the unsupported cases.
Phase 1 ships with the auto-install checkbox hidden and treated as false.

## 5. Hand-off per OS

### 5.1 Windows (Inno Setup, installed copies only)

Detect the install by reading the uninstall key
`…\Uninstall\{1F54E322-28D9-4929-8292-F5AAAA12CB5F}_is1` in HKCU, then HKLM in the
32-bit and 64-bit views, and checking `InstallLocation` against the running exe's folder.
No match means portable zip, moved install, or source: link out. The hive found decides
`/CURRENTUSER` or `/ALLUSERS`; passing the wrong one creates a second install, and
`/DIR` is never passed because `UsePreviousAppDir` reuses the location.

Command (built as one string, run with `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`,
breaking away from any job, after `SetDllDirectoryW(None)` and with `_PYI_*` stripped and
`PYINSTALLER_RESET_ENVIRONMENT=1` in the child environment, retrying briefly on a
sharing violation from antivirus):

```
"<data>\updates\MTGA-Tracker-<new>-setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL
    /CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /LOG="<data>\updates\install-<new>.log"
    /CURRENTUSER|/ALLUSERS /WAITPID=<pid> /RELAUNCH=1 /UPDATEDFROM=<old> /RELAUNCHEXE="<running exe>"
```

`packaging/windows_installer.iss` changes (full listing in report 02):

- `CloseApplicationsFilter=*.exe,*.dll,*.pyd,*.chm` so Restart Manager also sees the
  extension modules; it stays a fallback for stragglers (a leftover overlay or a Deck
  Finder console), never the primary mechanism.
- `[Code] InitializeSetup` opens `/WAITPID` with `OpenProcess(SYNCHRONIZE)` and waits up
  to 60 s for it to exit **before** `[InstallDelete]` removes `_internal`. That deletion
  is not rolled back on failure, so waiting is mandatory.
- A second `[Run]` entry: `Parameters: "--after-update --updated-from {param:UPDATEDFROM}"`,
  `Flags: nowait runasoriginaluser skipifnotsilent`, `Check: RelaunchRequested`
  (`/RELAUNCH=1`). The existing entry keeps `skipifsilent`.
- `DeinitializeSetup`: if the install started and did not reach `ssPostInstall`, relaunch
  `/RELAUNCHEXE` with `--update-failed` so the user is not left without a tracker.
  Whether `ExecAsOriginalUser` works there is unverified; the guard makes it a no-op
  otherwise.
- `AppId` never changes.

Older setups ignore unknown `/NAME=` switches, so the version doing the updating only
needs to pass them; **the first auto-updating release must ship the new `.iss`**. All-users
installs show a UAC consent even in silent mode: do not auto-install those, show "Windows
will ask for permission" and run the same command on click. Smart App Control machines
likely cannot run the unsigned app at all; treat a launch failure as "download manually".

### 5.2 macOS (`.app` swap)

Download the `-macos.zip`, verify, extract with `/usr/bin/ditto -x -k --noqtn` into
`<data dir>/updates/stage/` (same APFS volume as `/Applications` on a default Mac; if
`st_dev` differs, stage in a hidden sibling directory next to the target), then
`codesign --verify --deep --strict` on the staged bundle and check its
`CFBundleIdentifier` and `CFBundleShortVersionString`. Refuse when the running bundle is
under `/Volumes/` (running from the DMG), contains `/AppTranslocation/`, or its parent is
not writable (standard user): show "Move Tapps Tracker to Applications, then update" or
the release page.

On Restart, spawn [`tapps_mac_swap.sh`](auto-update/tapps_mac_swap.sh) detached
(`start_new_session=True`, written from a string embedded in `update_install.py`, never
from the download). It waits for the parent PID, terminates any leftover overlay, validates
the staged bundle again, moves the old bundle to `updates/rollback/` (not `/Applications`,
where Launchpad would show two apps), moves the new one in, restores the old one if that
fails, and relaunches with `open -n … --args --after-update --updated-from <old>` (or
`--update-failed` on any failure). It is tested on dummy signed bundles including a
tampered one; the real `open -n` relaunch is not yet exercised. Renaming a running
bundle is safe, but the swap only happens after exit because PyInstaller imports lazily
by path and the dashboard serves `ui/dist` by path. The new version deletes the rollback
copy after it has run healthy for about a minute. Start-at-login survives: the
LaunchAgent stores the bundle path and runs Apple's `open`.

### 5.3 Linux (later)

Same flow: download the AppImage next to `$APPIMAGE`, verify, `chmod +x`, `rename()` over
it after exit, relaunch; or the macOS swap for a tarball install under
`~/.local/share/tapps-tracker`. Never self-update a distro package or Flatpak. Optionally
publish `.zsync` files so external AppImageUpdate users get deltas. The Arena probe must
look for the Wine/Proton `MTGA.exe` process and returns unknown (blocks auto) until
validated.

## 6. The install sequence (one place, `UpdateManager._perform_install`)

1. State must be `ready`; re-verify size and SHA-256 (macOS: and `codesign`). Unless the
   user forced it after a confirm, `busy_reasons()` must be empty. Set `installing` and
   notify the pill and tray.
2. Write `updates/pending.json` `{from, to, asset, sha256, pid, install_kind, started_at}`.
3. **Pre-update backup, mandatory:** `backup.export_backup(db, <data>/backups,
   tag="pre-update-<from>", record=False)` through SQLite's online backup API, pruned to
   the last 2. It is a normal `.tappsbackup`, restorable from Settings → Backup & restore
   with the existing schema check and undo. Taken in the old process, because the new
   process migrates on its first connect. A backup failure (disk full) aborts here.
4. `launcher.stop_tracker(timeout=5)` (commits, marks `live_status` stopped so every
   dashboard and overlay flips to offline). If the thread is still alive, abort and
   restart it; never hard-exit mid-write.
5. Release dashboard read handles (`live_api.reset_poll_connections`,
   `clear_response_cache`) and `PRAGMA wal_checkpoint(TRUNCATE)` so the DB is one file
   while the app is down.
6. `overlay_launcher.get_manager().stop()` without touching `overlay.enabled`.
7. `install_and_restart(plan)`: spawn the detached helper or installer with our PID. If
   it raises, restart the tracker and overlay and set `error`.
8. Request exit on the host: the menu app via a queued Qt signal to `app.quit`
   (`aboutToQuit` runs the normal shutdown and lock release); `--no-gui` by returning
   from the foreground tracker. `os._exit(0)` after 20 s as a backstop; the helper waits
   at most 60 s, so a hung exit means "update aborted", never a half-written install.

The relaunched version, started with `--after-update`, retries both instance locks for
up to 60 s instead of showing "already running", runs migrations on connect as today,
reconciles `pending.json` (version matches: record success, delete the download, show
"Updated to X"; mismatch: record `install-not-applied`, keep the asset for a retry),
writes `updates/healthy-<version>` once the dashboard serves, re-asserts start-at-login
registration if the setting says enabled, and deletes the macOS rollback copy.

`POST /api/update/install` answers 202 **before** any of this starts, because shutting
the server down from a request thread would block the response.

## 7. Safety gate

`busy_reasons()` returns a list; install proceeds only when it is empty.

| Reason | Source | Blocks |
| --- | --- | --- |
| `game-in-progress` | in-process `game_state` when the tracker is running (`in_match && game_start_time && !match_complete`, Bo3 `!arena_match_over`, mid-game attach wait, queued event with a staleness timeout), else `live_status.in_game` with a fresh heartbeat; plus "a game was seen or ended less than 120 s ago" | manual and auto |
| `arena-running` | `paths.arena_process_running()` (`pgrep -x MTGA` / `tasklist` with `CREATE_NO_WINDOW`; probe failure = unknown = blocked) | **auto only**; manual gets a confirm: "Arena is open. The tracker will be offline for about 10 s; don't start a match until it's back." |
| `deck-transfer` | `deck_native_api.job_active()` or a pending transfer | both |
| `collection-export` | `collection_api.job_running()` | both |
| `backup-restore` | restore or merge in flight | both |

Auto-install fires when the setting is on, the state is `ready`, the file re-verifies,
and the list is empty, so Arena must be closed. The natural moments are a login start
before Arena is opened, after Arena is closed for the night, and on Quit ("install and
quit", no relaunch). `force` only exists for an explicit user click after the confirm;
it bypasses the game and Arena gates, never the re-verify or the backup.

## 8. Security model

| Layer | Protects against |
| --- | --- |
| HTTPS with certificate verification (`requests` + `certifi`; bare `urllib` failed TLS on python.org's macOS Python) and a redirect host allow-list | network tampering |
| Size + SHA-256 in the manifest, checked after download and again before hand-off | corruption, truncated resumes, local tampering |
| Ed25519 signature over the manifest, public keys embedded in the app, private key off GitHub | a compromised GitHub account, token, or workflow publishing a malicious release |
| Version inside the signed manifest, never install at or below the current version | downgrade to an old signed build |
| macOS `codesign --verify --deep --strict` on the staged bundle | a partial or modified copy (ad-hoc, so integrity only) |
| GitHub immutable releases | post-publish asset or tag swaps |

Residual risk is the maintainer's signing key and machine. There is no OS trust layer
(Gatekeeper, SmartScreen) in this flow at all, which is exactly why the signature is not
optional.

## 9. Failure handling

| Failure | Result |
| --- | --- |
| Manifest 404, bad signature, unknown schema, host not allowed | logged, state `up_to_date`/`error`, nothing downloaded |
| Download interrupted | resumed with `Range` + `If-Range` from the `github.com` URL (the redirect URL expires); a 200 restarts; three attempts |
| SHA-256 mismatch | file deleted, `error: sha256-mismatch`, retry on next check |
| Not enough disk space (asset × 1.1, DB size for the backup, about 3× install size on the app drive) | `error`, pill says so |
| Pre-update backup fails | abort before anything stops |
| Hand-off spawn fails | tracker and overlay restarted, `error` |
| Old process hangs | helper gives up after 60 s, `os._exit` backstop at 20 s; nothing is touched |
| Inno fails mid-install | log in `updates/install-<ver>.log`, `--update-failed` relaunch of the old exe (unverified), user told to run setup manually |
| macOS move fails (permissions, App Management) | old bundle restored, `--update-failed` relaunch, link-out shown |
| Migration fails on first start | app refuses to start as today; "update failed" UI offers **Restore pre-update backup** through the existing restore flow |
| User rolls back to an older build | a new downgrade guard logs "DB newer than this app" and `/api/update` surfaces it; the app still starts |

## 10. Phases

### Phase 0: spikes (before writing the production code)

1. macOS, admin and standard accounts, macOS 14 through 27, DMG-installed
   (provenance-tagged) copy: full zip → stage → swap → `open -n` relaunch. Confirm no
   Gatekeeper or App Management prompt, the lock hand-over, the overlay restart, and
   rollback.
2. Windows per-user and all-users installs: `setup.exe /VERYSILENT … /WAITPID /RELAUNCH=1`
   from a just-exited tracker. Confirm the wait, no leftover `_internal` locks, the
   correct Apps & Features version, the Run key, the UAC behavior and decline exit code,
   and the `DeinitializeSetup` relaunch. Watch Defender on a clean Windows 11 VM with
   cloud protection on.
3. Verifier choice: pure-Python Ed25519 timing vs the `cryptography` size cost.
4. Confirm the Inno uninstall value names and the `WOW6432Node` location on a real
   all-users install.

### Phase 1: check, download, verify, manual "Restart to update"

Everything in §3–§6 and §8 except the auto-install toggle: the release job and signing
script, the `.iss` changes, the macOS zip, `updater.py` / `update_install.py` /
`update_api.py`, settings plumbing, the sidebar pill and tray item, the pre-update
backup, `--after-update` lock retry, tests and docs. Ships with auto-install hidden.
Its changelog entry says "install this release manually; later releases update in place".

### Phase 2: opt-in auto-install

Enable the Settings checkbox and the 15 s idle wake, "Install after this game" for pill
and tray, "Install update and quit", `mandatory` and `minimum_version` handling, the
`healthy-<version>` marker and rollback watchdog. Optionally make each migration
transactional (`with conn:` around each step, replacing `executescript` in v33/v34) so a
failure rolls back exactly one migration. Optionally sign macOS releases with one stable
self-signed identity so TCC grants survive.

### Phase 3: Linux and a beta channel

AppImage/tarball hand-off once `linux_implementation.md` produces an artifact; a
`latest-beta.json` on a fixed release or Pages, because `releases/latest` ignores
prereleases; optional delta downloads if size complaints appear.

## 11. Tests

- `tests/test_updater.py`: PEP 440 table (`0.6.5.4 > 0.6.5.3`, `0.6.3rc8 == v0.6.3-rc.8`,
  `0.6.3 > 0.6.3rc8`, dev and local segments, garbage → None); signature verify with RFC
  8032 vectors and a tampered manifest; strict manifest parsing (http, foreign host, bad
  hex, size 0); asset selection per install kind and arch; `detect_install_kind` with a
  fake tree; `fetch_manifest` 200/304/404/timeout with a fake opener; download against a
  local `http.server` (full, mismatch, resume 206, restart 200, disk space, cancel);
  state machine with injected clock (unsupported, disabled, skipped, downgrade refused,
  below-minimum, cached download → ready, corrupted cache deleted); busy gate against a
  temp `live_status`; install orchestration with fakes asserting the exact order
  backup → stop tracker → release handles → stop overlay → hand-off → exit, backup
  failure aborting early, hand-off exception restarting; `pending.json` reconciliation.
- `tests/test_update_api.py`: real server on port 0 with a fake manager; `no-store` and
  Content-Length on GET; 403 on foreign Origin or non-JSON; 409 `game-in-progress` with
  `blocked_by`; 202 on force; 409 `not-ready`; 404 unknown action; `Connection: close`.
- Extend `test_settings.py` (default document, invalid channel), `test_backup.py`
  (`updates` stripped on export, kept on restore, pre-update retention of 2 without
  touching pre-restore files), `test_app.py` (`--after-update` retry, quiet exit on a
  held lock, `--login-start` unchanged), `test_live_api.py` (`game_activity`),
  `test_paths.py` (`arena_process_running` passes `CREATE_NO_WINDOW`).
- Vitest: `updateStatus.test.ts` (pill model per state), `UpdateIndicator.test.tsx`
  (expanded/collapsed, install POST, 409 → "Install after this game", progress bar,
  poll cadence switch, just-updated notice, reload loop), Settings → Updates form, and
  `App.test.tsx` tolerating an unexpected `/api/update` shape.
- The usual commands: the full pytest line from AGENTS.md, then `npx vitest run`,
  `npx tsc -b`, `npm run lint`, `npm run build`.

## 12. Docs and changelog when it ships

AGENTS.md (new code-path bullets, a Tracker Invariant "never auto-install while Arena is
running or within 2 minutes of a game; a restart needs the user's click or their opted-in
auto-install", the new POST routes, the packaging section), `docs/RELEASING.md`
("Updates and user data" rewritten, the signing and manifest checklist),
`QUICKSTART.md` (an Updates paragraph; revisit the Gatekeeper and SmartScreen text once
the spikes confirm no prompts), `README.md` (network requests list), `CHANGELOG.md`
Unreleased, and this plan's row in `INDEX.md`.

## 13. Decisions (made 2026-10-18)

1. **Signing key custody: GitHub Actions.** The Ed25519 private key is an Actions secret
   (`UPDATE_SIGNING_KEY`, PEM). The `manifest` job signs `latest.json` after both builds.
   The maintainer keeps the same PEM offline as the backup. Public key embedded in
   `updater.py`.
2. **Verifier: vendored pure-Python Ed25519** (RFC 8032, verification only, stdlib
   `hashlib`). No `cryptography` in the bundle.
3. **Stable macOS signing identity: yes**, in the first updater release, through the
   existing `MACOS_SIGN_IDENTITY` hook with a self-signed certificate in a CI secret.
4. **Per-migration transactions: yes**, same release, plus the "DB newer than this app"
   guard.
5. **Download behavior is a setting.** Settings → Updates gets three toggles: Check for
   updates (on), Download updates automatically (on), Install automatically when no game
   is running (off). With automatic download off, the pill reads "Update vX available —
   Download" and installs only after the download the user started finishes.
6. **Auto-install timing** as in §7: Arena closed, no game seen for 120 s, no job running,
   plus "Install update and quit".
7. **One release** ships manual Restart to update and the opt-in auto-install together.
8. **Windows edge cases accepted:** all-users installs get a UAC prompt and never
   auto-install; portable zips link out.
9. **Immutable releases: on.** A published release is never edited; fixes are new
   bug-fix versions, which is already the maintainer's practice.
10. **Test hardware:** a Mac Studio with Arena installed (admin account; standard
    accounts are out of scope) and a Windows 11 machine. The macOS relaunch spike and the
    Windows silent-upgrade spike run there on the first release candidate, with a separate
    data directory. No launches of the app are made on the development machine.
