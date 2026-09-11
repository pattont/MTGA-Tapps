# Building and releasing Tapps Tracker

This is the current release procedure. Build logic lives in
[`packaging/mtga_tracker.spec`](../packaging/mtga_tracker.spec), the
[`scripts/`](../scripts/) build scripts, and
[`release.yml`](../.github/workflows/release.yml).

## Version and release trigger

The git tag is the version. `setuptools-scm` generates `_version.py` and
package metadata; never edit a version string for a release. Checkouts
between tags can have development versions. CI fetches full history and
tags, and sets `SETUPTOOLS_SCM_PRETEND_VERSION` from a pushed `v*` tag to
prevent build-time working-tree changes from altering that release's version.

Only the maintainer cuts and pushes a release tag. A tag build creates or
updates a **draft** GitHub Release with macOS and Windows artifacts. The
maintainer reviews the artifacts and notes, then publishes the draft.
Manual workflow runs on a branch upload Actions artifacts instead; a run
on a tag follows the tag-release path. Ordinary branch pushes do not build
installers. There is currently no separate Python/frontend test workflow;
run the checks below before release.

## Build locally

Run from the repository root. Install Python, Node/npm, and Rust first;
use the repo virtualenv for Python. The scripts install Python build
dependencies, build the dashboard and overlay, and run PyInstaller.

```bash
python3 -m venv venv
scripts/build_macos_app.sh       # dist/MTGA Tracker.app
scripts/build_macos_installer.sh # dist/MTGA-Tracker-<version>.dmg
```

```powershell
py -m venv venv
powershell -ExecutionPolicy Bypass -File scripts\build_windows_app.ps1
```

Windows produces `MTGA-Tracker-<version>-windows.zip` and, with Inno Setup
installed, `MTGA-Tracker-<version>-setup.exe`. CI installs Inno Setup. Keep
the installer's `AppId` unchanged so upgrades find the existing install.

The tracker is **one executable**. Deck Finder is available inside the
dashboard and as `MTGA Tracker --deck-finder` (quote the executable path;
Windows uses `MTGA Tracker.exe`). There is no separate Deck Downloader
executable to package.

The macOS build copies `Tapps Overlay.app` into the tracker's
`Contents/Helpers/` after PyInstaller finishes. Windows includes
`overlay/tapps-overlay.exe` in PyInstaller's data tree. The overlay build
scripts stage these in `overlay/build-out/`. Missing Rust skips the overlay
in a local build; CI sets `OVERLAY_REQUIRED=1`, making it a release failure.
Never distribute an overlay built with `--fast` / `-Fast`.

macOS builds are ad-hoc signed by default; `MACOS_SIGN_IDENTITY` selects a
different identity. The script verifies the signature but does not perform
notarization. Windows builds have no code-signing step. Install guidance is
in [QUICKSTART.md](../QUICKSTART.md).

## Checks before publishing

From the repository root on macOS; on Windows use `venv\Scripts\python`
instead of `venv/bin/python`:

```bash
venv/bin/python -m pytest tests -q --ignore=tests/test_menu_app.py \
  --deselect "tests/test_log_parser.py::test_find_log_path_error_handling"
(cd ui && npm ci && npx vitest run && npx tsc -b && npm run lint && npm run build)
(cd overlay && npm ci && npm test && npm run build && cargo test --manifest-path src-tauri/Cargo.toml)
(cd overlay && node scripts/screenshots.mjs)
```

- Verify both platform artifacts on their actual operating systems using a
  separate test data directory. Never stop the user's active tracker to test
  a build without approval.
- Check first launch with no database, missing Arena/log, and Detailed Logs
  disabled. Check a completed game, correct deck/opponent attribution,
  dashboard pages, and the displayed version against the release tag.
- Open Deck Finder from the menu and verify all providers appear. Exercise
  the bundled `--deck-finder` terminal mode too.
- Verify the overlay is inside the artifact, launches, follows Arena, and
  responds to settings/hotkeys. On macOS inspect
  `Contents/Helpers/Tapps Overlay.app/Contents/MacOS/tapps-overlay`.
- Verify Windows setup upgrades in place and preserves the data folder;
  check the portable zip separately. Verify the macOS DMG installs and its
  nested overlay signature passes the build's verification.
- Update `CHANGELOG.md` for the release being prepared. Review draft notes,
  platform requirements, and download filenames before publishing.

## Updates and user data

The dashboard already checks GitHub Releases and links to a newer published
release, caching successful checks for a day (`ui/src/updateCheck.ts`). It
does not install updates. Users download the replacement installer/app.

Installed data stays under `~/Library/Application Support/MTGA Tracker` on
macOS and `%LOCALAPPDATA%\MTGA Tracker` on Windows. Source runs use the
repository's `data/`. Use SQLite's online backup API for any live database
copy; copying only a live `.sqlite3` file can omit WAL data.
