# Release Plan: Alpha Distribution for macOS & Windows

How to get MTGA Tracker into alpha testers' hands, and how to keep shipping
updates through GitHub afterward.

## Where we are today

Already in the repo:

- `packaging/mtga_tracker.spec` — PyInstaller spec packaging the tracker,
  dashboard, and prebuilt `ui/dist` together.
- `scripts/build_macos_app.sh` — builds `dist/MTGA Tracker.app` (menu-bar app).
- `scripts/build_macos_installer.sh` — builds a drag-to-Applications DMG.
- Windows support in code: `log_parser.py` finds
  `%APPDATA%\LocalLow\Wizards Of The Coast\MTGA\Player.log`, and `paths.py`
  maps the data dir to `%LOCALAPPDATA%\MTGA Tracker` and knows Windows
  Steam/Wizards card-database locations.
- Installed builds use their own database under the OS app-data dir — testers
  never touch the repo database.

Missing for alpha: a Windows build script, CI that produces both installers,
code signing, and a first-run/feedback story.

## Q: Do we need to build installers on every push?

**No.** Build installers only when cutting a release — a pushed **tag**
(`v0.3.0`) triggers the build workflow; ordinary pushes just run tests.
GitHub Actions builds both platforms and attaches the artifacts to a GitHub
Release. Testers download from the Releases page; that page *is* the update
channel.

Release cadence: bump `src/mtga_tracker/__init__.py` `__version__`, commit,
`git tag v0.3.0 && git push origin main v0.3.0`, and CI does the rest.

## Step 1 — Windows build (1–2 sessions of work)

1. ~~Add `scripts/build_windows_app.ps1`~~ **Done** — builds `ui/dist`, runs
   PyInstaller, and zips `dist/MTGA-Tracker-<version>-windows.zip`. The spec is
   platform-conditional (`.icns`/BUNDLE on macOS, `.ico` on Windows —
   `packaging/assets/MTGATracker.ico` is committed) and reads the app version
   from `__version__`. Validated on Linux (same non-mac code path).
2. Verify on a real Windows machine (or VM) with Arena installed:
   log tailing, card database discovery, dashboard, data dir. This is the one
   step that genuinely needs Windows hardware — the code paths exist but have
   likely never been exercised.
3. Installer options, simplest first:
   - **Alpha: plain `.zip`** of the PyInstaller folder — testers extract and
     run `MTGA Tracker.exe`. Zero extra tooling; fine for a handful of testers.
   - **Beta+: Inno Setup** (`iss` script, free) for a proper
     `MTGA-Tracker-Setup.exe` with Start Menu entry and uninstaller.

## Step 2 — GitHub Actions release workflow

`.github/workflows/release.yml`, roughly:

```yaml
name: Release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:

jobs:
  build:
    strategy:
      matrix:
        include:
          - os: macos-latest
            build: scripts/build_macos_installer.sh
            artifact: dist/MTGA-Tracker-*.dmg
          - os: windows-latest
            build: pwsh scripts/build_windows_app.ps1
            artifact: dist/MTGA-Tracker-*-windows.zip
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e '.[gui,build]'
      - run: ${{ matrix.build }}
      - uses: softprops/action-gh-release@v2
        with:
          files: ${{ matrix.artifact }}
          draft: true
```

Publishing the drafted release on github.com is the human "go" button.
A separate `test.yml` running `pytest` + `vitest` on every push keeps main
honest without paying for installer builds each time.

## Step 3 — Code signing (decide per platform)

- **macOS:** unsigned apps trigger Gatekeeper. For a small alpha you can ship
  unsigned and tell testers: *right-click → Open → Open* (or
  `xattr -dr com.apple.quarantine "/Applications/MTGA Tracker.app"`). For
  anything wider, enroll in Apple Developer ($99/yr), then
  `codesign --options runtime`, `notarytool submit`, `stapler staple` — one
  afternoon to wire into the build script, and CI can hold the cert as a
  repo secret.
- **Windows:** unsigned exes get a SmartScreen warning ("More info → Run
  anyway"). Acceptable for alpha; an OV/EV signing cert (~$100–400/yr) is a
  beta/public concern, not an alpha blocker.

## Step 4 — Updates via GitHub

Alpha-simple: release notes on the GitHub Release + testers re-download.
The sidebar already shows `v{__version__}`, so "what version are you on?" is
answerable.

Nice upgrade (small, later): on dashboard load, fetch
`https://api.github.com/repos/pattont/MTGA-Tapps/releases/latest` once per
day, compare `tag_name` to the running version, and show a subtle
"Update available →" link in the sidebar pointing at the release page.
No auto-updater needed at this scale — that's a post-beta problem (Sparkle
on macOS / winget or an updater exe on Windows, all sign-first).

## Alpha readiness checklist

Product:
- [ ] Fresh-install first run: launch with no database, no Arena running —
  menu-bar app should guide, not stack-trace. Test on a clean user account.
- [ ] Windows validation pass (Step 1.2) — the only truly unknown platform.
- [ ] Repo is public (or testers invited to the private repo) so Releases
  are reachable.
- [ ] `data/_queries`, `docs/`, dev scripts excluded from the packaged app.

Testers:
- [ ] GitHub Issues enabled with a short bug template (version, OS, what
  happened, tracker terminal output).
- [ ] A README section for testers: install steps per OS, the Gatekeeper /
  SmartScreen workaround, where their data lives, how to update.
- [ ] Privacy note: everything is local SQLite; logs are scrubbed of tokens
  and personal paths before storage (`log_sanitize.py`); the only network
  calls are Scryfall card art from the browser.

Expectations to set in release notes:
- Arena patches can change log formats; tracking may lag an Arena update.
- Mid-game joins are shown live but not saved (by design).
- Unsigned alpha builds require the one-time OS override.

## Suggested order

1. Windows build script + validation on real Windows (the long pole).
2. `test.yml` CI (pytest + vitest on push) — cheap and immediate.
3. `release.yml` + tag `v0.3.0-alpha.1` as a dry run with a draft release.
4. README tester section + issue template.
5. Invite 3–5 testers (ideally ≥2 on Windows). Iterate on their first-run
   pain before widening.
6. Decide on Apple Developer enrollment once alpha feedback justifies it.
