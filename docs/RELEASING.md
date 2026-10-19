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
updates a **draft** GitHub Release with macOS and Windows artifacts, then
the `manifest` job adds the signed update manifest (see below). The
maintainer reviews the artifacts and notes, then publishes the draft.
Every run also uploads the builds as Actions artifacts; manual runs on a
branch produce only those, while a run on a tag follows the tag-release
path. Ordinary branch pushes do not build installers. There is currently
no separate Python/frontend test workflow; run the checks below before
release.

A tag containing a hyphen (`v0.6.7-rc.1`) is created as a **prerelease**
with `make_latest: false`. GitHub never serves drafts or prereleases from
`releases/latest`, which is where the in-app updater looks, so a release
candidate can never be offered to users. Keep "Set as a pre-release"
checked when publishing one.

Immutable releases are enabled for the repository (repository Settings,
Releases section, "Enable release immutability"; or
`gh api -X PUT repos/pattont/MTGA-Tapps/immutable-releases`, checked with
`gh api repos/pattont/MTGA-Tapps/immutable-releases`). It applies to
releases created after it was turned on. Once a release is published,
its assets and tag can no longer change; only the title, notes and
prerelease/latest flags stay editable. Everything must therefore be on
the draft before publishing, and a bad release is fixed by a new bug-fix
version, never by replacing an asset.

## Build locally

Run from the repository root. Install Python, Node/npm, and Rust first;
use the repo virtualenv for Python. The scripts install Python build
dependencies, build the dashboard and overlay, and run PyInstaller.

```bash
python3 -m venv venv
scripts/build_macos_app.sh       # dist/MTGA Tracker.app
scripts/build_macos_installer.sh # dist/MTGA-Tracker-<version>.dmg + -macos.zip
```

The installer script also writes `MTGA-Tracker-<version>-macos.zip`, the
in-app updater's payload. It is made with
`ditto -c -k --norsrc --noextattr --noacl --noqtn --keepParent`: only
`ditto` preserves the bundle's symlinks and signature (`zip -r` and Python's
`zipfile` break it), and those flags keep quarantine and other extended
attributes out of the archive.

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
different identity (a SHA-1 hash or common name), and `MACOS_SIGN_KEYCHAIN`
optionally names the keychain that holds it. The script verifies the
signature, prints the designated requirement, and does not notarize.
Windows builds have no code-signing step. Install guidance is in
[QUICKSTART.md](../QUICKSTART.md).

Release builds are signed with one stable **self-signed** identity, "Tapps
Tracker Code Signing", created once with
`scripts/create_macos_signing_identity.sh` and stored as the
`MACOS_SIGNING_P12` / `MACOS_SIGNING_P12_PASSWORD` secrets. CI imports it
into a temporary keychain for the build and deletes the keychain
afterwards; without the secrets it builds ad-hoc and logs a warning. The
stable certificate makes the designated requirement
`identifier "com.travispatton.mtgatracker" and certificate leaf = H"…"`
the same in every release, so macOS privacy (TCC) grants such as Automation
survive an update; with ad-hoc signing the requirement is a per-build
cdhash and every update re-prompts. Gatekeeper does not trust a
self-signed certificate, so first-install behavior is the same as ad-hoc
(the Privacy & Security "Open Anyway" flow). Never regenerate the
identity: a new certificate costs every user one round of re-granted
permissions. Back up the `.p12` and its password offline.

## Update manifest and signing

After both builds succeed, the `manifest` job (tags only) downloads the
Actions artifacts and runs
[`scripts/make_update_manifest.py`](../scripts/make_update_manifest.py). It

- requires all four assets (`MTGA-Tracker-<v>.dmg`, `-macos.zip`,
  `-setup.exe`, `-windows.zip`) and fails if any filename's version
  differs from the tag's PEP 440 form (`v0.6.3-rc.8` → `0.6.3rc8`);
- writes `latest.json` (schema 1: version, tag, release time, notes URL,
  `minimum_version`, `mandatory`, and each asset's platform, arch, kind,
  tag-pinned URL, size and SHA-256), and `SHA256SUMS`;
- signs the exact bytes of `latest.json` with Ed25519 (`openssl pkeyutl
  -sign -rawin`) into `latest.json.sig`, one line of base64;
- re-verifies that signature against the public key embedded in the app
  (`src/mtga_tracker/updater.py`), so a wrong secret fails the release
  instead of shipping a manifest no client accepts;
- attaches `latest.json`, `latest.json.sig` and `SHA256SUMS` to the same
  draft and uploads them as the `update-manifest` artifact.

The app fetches
`https://github.com/pattont/MTGA-Tapps/releases/latest/download/latest.json`
and its `.sig`, so the names never change between releases.
`minimum_version` and `mandatory` are the kill switches for a release
whose hand-off changed; set them with the script's `--minimum-version` /
`--mandatory` flags (edit the `manifest` job for that one release).
Run `python3 scripts/make_update_manifest.py --self-test` after changing
the script; it signs dummy assets with a throwaway key and verifies them.

### Secrets

| Secret | Contents | Used by |
| --- | --- | --- |
| `UPDATE_SIGNING_KEY` | Ed25519 private key, PEM (PKCS#8), from `openssl genpkey -algorithm ed25519` | `manifest` job |
| `MACOS_SIGNING_P12` | base64 of the self-signed identity's `.p12` | macOS build |
| `MACOS_SIGNING_P12_PASSWORD` | that `.p12`'s export password | macOS build |

The maintainer keeps the same PEM and `.p12` offline as backups; they
never go in the repository. Set them with `gh secret set NAME <file` (the
`.p12` as `base64 -i file.p12 | gh secret set MACOS_SIGNING_P12`) and check
with `gh secret list`. The raw public key the app embeds is
`openssl pkey -in key.pem -pubout -outform DER | tail -c 32 | xxd -p -c 64`;
the `--verify-public-key` value in `release.yml` must match it.

### Key rotation

Losing the signing key means installed apps can never verify another
update, so rotate before that can happen:

1. Generate the new key and add its public key to `updater.py` **next to**
   the current one (the app accepts a manifest signed by any listed key).
   Ship that release, still signed with the old key.
2. Once users have updated to it, switch `UPDATE_SIGNING_KEY` and the
   `--verify-public-key` value in `release.yml` to the new key.
3. Remove the old public key from `updater.py` only in a later release.

If the private key leaks, do the same immediately and treat every release
signed after the leak as suspect.

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
- Check the draft carries all seven assets: the DMG, `-macos.zip`,
  `-setup.exe`, `-windows.zip`, `latest.json`, `latest.json.sig` and
  `SHA256SUMS`, and that the `manifest` job printed "Verified
  latest.json.sig against embedded public key". Immutable releases mean
  anything missing at publish time cannot be added afterwards.
- Spot-check a hash: download one asset from the draft and compare
  `shasum -a 256` (Windows: `certutil -hashfile <file> SHA256`) with its
  `SHA256SUMS` line and its `latest.json` entry. Confirm `latest.json`'s
  `version`/`tag` match the release and its URLs name that tag.
- Test the upgrade from the previous published release on a real Mac and
  a Windows 11 machine, each with a separate data directory. Before
  publishing, install the previous release, then upgrade it with this
  draft's artifacts the way the updater does (Windows: the silent
  `setup.exe` command line in the header of `windows_installer.iss`;
  macOS: replace the `.app` with the one from `-macos.zip`, extracted with
  `ditto -x -k --noqtn`), and check it relaunches and keeps data and
  settings. Drafts and prereleases are never offered in-app, so right
  after publishing, confirm on the same machines that the previous version
  offers the update and that Restart to update ends in "Updated to …" with
  a pre-update backup in `<data>/backups`.
- Update `CHANGELOG.md` for the release being prepared. Review draft notes,
  platform requirements, and download filenames before publishing.

## Updates and user data

Installed copies update themselves from the signed manifest
(`src/mtga_tracker/updater.py`; design in
[`docs/plans/AUTO_UPDATE.md`](plans/AUTO_UPDATE.md)):

- The app checks `releases/latest/download/latest.json` shortly after
  start and every few hours, verifies `latest.json.sig` against its
  embedded public key **before** reading the manifest, and ignores drafts,
  prereleases and development builds.
- With "Download updates automatically" on (the default), the matching
  asset downloads in the background: the `-macos.zip` on macOS, the
  `-setup.exe` on Windows. Its size and SHA-256 must match the manifest,
  checked after the download and again just before installing.
- The sidebar and tray then offer **Restart to update**. During a game it
  waits ("Finish your game first"). "Install automatically when no game is
  running" is opt-in and also waits for Arena to close.
- Before handing off, the running version writes a normal `.tappsbackup`
  of the database to `<data>/backups` (the last two are kept), restorable
  from Settings → Backup & restore. Then it stops, the Windows installer
  runs silently (`/WAITPID`, `/RELAUNCH`, see `windows_installer.iss`) or
  a macOS helper swaps the `.app` in place, and the new version starts and
  shows "Updated to …". A failed install relaunches the old version.
- The Windows portable zip, macOS copies outside a writable Applications
  folder (or running from the DMG), all-users Windows installs for
  auto-install, and source runs are not replaced in place: they link to
  the release page instead.
- An app only updates itself from a release built with the updater, so the
  **first updater-capable release must be installed manually**, like any
  release before it. Its predecessors keep the old behavior of linking to
  a newer release (`ui/src/updateCheck.ts`).

Installed data stays under `~/Library/Application Support/MTGA Tracker` on
macOS and `%LOCALAPPDATA%\MTGA Tracker` on Windows. Source runs use the
repository's `data/`. Use SQLite's online backup API for any live database
copy; copying only a live `.sqlite3` file can omit WAL data.
