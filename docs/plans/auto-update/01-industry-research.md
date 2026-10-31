# Tapps Tracker auto-update: industry research and recommendation

Research date: 2026-10-11. Repo: `pattont/MTGA-Tapps` (checked at `auto-update` branch, clean).
No repo files were modified.

Evidence labels used throughout:

- **[V]** verified against the cited URL (docs, source code, or vendor page).
- **[T]** tested directly from this machine (macOS 27.0.1) with curl/python/gh; the command and
  result are described inline.
- **[I]** my inference or engineering judgment; not stated by a source. Treat as a hypothesis
  to confirm in a spike.

---

## 0. TL;DR

**Recommend: a hand-rolled Python updater driven by a signed static manifest
(`latest.json` + `latest.json.sig`, Ed25519) attached to each GitHub Release and fetched from
`https://github.com/pattont/MTGA-Tapps/releases/latest/download/latest.json`.** The updater
reuses the **existing install artifacts** as the update payloads: the Inno Setup `setup.exe`
on Windows (run silently once the app has exited), the DMG on macOS (mounted read-only, the
`.app` copied to a sibling staging path, then swapped by a detached helper after exit), and
later the AppImage on Linux. Download and verify (size, SHA-256, signature) in the background.
Then show **Restart to update** in the dashboard sidebar. Optional fully automatic mode applies
only when the tracker reports no live game. It can also apply on quit.

Why this one:

1. It keeps today's packaging (PyInstaller + Inno + DMG), AppId, install paths and the
   draft-release gate intact. That means no install-location migration and no new toolchain
   (.NET) in CI.
2. With no Apple Developer ID and no Authenticode certificate, **the app's own embedded Ed25519
   key is the only real authenticity check available.** Velopack has none today: it checks only
   SHA-256 from the same feed ([V] velopack#975). Tauri/Sparkle/WinSparkle-style EdDSA is the
   proven pattern, and in Python it is about a hundred lines.
3. The maintainer can sign the manifest **offline after reviewing the draft**. That turns the
   existing human "publish" gate into a cryptographic gate. A compromised GitHub account or a
   malicious workflow then cannot push a malicious update.

Top alternatives, with the reasons for rejecting them, are in section 5. In short: **Velopack**
(good deltas and a real Python SDK, but no signature verification, an install-layout migration
off Inno, and unproven macOS+PyInstaller `.app` handling) and **tufup** (strong TUF security,
but it copies files over the install dir in place, has periodic metadata re-signing burden, and
a single maintainer whose last release was Oct 2025).

---

## 1. Repo facts that shape the design

- The release workflow builds macOS on `macos-latest` and Windows on `windows-latest`. It
  uploads `MTGA-Tracker-<v>.dmg`, `MTGA-Tracker-<v>-setup.exe` and
  `MTGA-Tracker-<v>-windows.zip` to a **draft** release via `softprops/action-gh-release`
  (`.github/workflows/release.yml`). The matrix jobs upload independently, so a manifest that
  covers both platforms needs a **final job with `needs: build`** [V repo].
- Current release `v0.6.5.3` [T `gh api repos/pattont/MTGA-Tapps/releases/latest`]:
  setup.exe 37.9 MB, windows.zip 50.7 MB, DMG 47.5 MB. Each asset already carries GitHub's
  server-computed `digest: sha256:…`. `immutable: false`.
- Inno script: `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed=dialog`,
  `DefaultDirName={autopf}\MTGA Tracker` (per-user `%LOCALAPPDATA%\Programs` unless the user
  picked all-users), `CloseApplications=yes`, `RestartApplications=no`,
  `[InstallDelete] {app}\_internal`. The `[Run]` launch entry is
  `postinstall nowait skipifsilent`, so **a silent update will not relaunch the app** unless
  changed [V repo `packaging/windows_installer.iss`].
- macOS: `scripts/build_macos_app.sh` runs `codesign --force --deep --sign -` and then
  `codesign --verify --deep --strict` on the bundle, after copying `Tapps Overlay.app` into
  `Contents/Helpers/` [V repo]. `target_arch=None` in the spec, so the macOS artifact is the
  runner's arch (arm64 on `macos-latest`) [I].
- **Existing bug in `ui/src/updateCheck.ts`:** `versionTriplet` compares only the first three
  numbers. So `0.6.5.3` is **not** newer than `0.6.5.2`, and four-part hotfix releases are
  never announced. Pre-release suffixes (`0.6.3rc8`) are also ignored [V repo]. The new
  updater must compare **PEP 440** versions, because setuptools-scm emits them (`v0.6.3-rc.8`
  becomes `0.6.3rc8`).
- The browser cannot fetch the release-download URLs: the `github.com` 302 carries **no
  `Access-Control-Allow-Origin`** [T `curl -sI …/releases/latest/download/x.json`]. Update
  checks must therefore move to the Python side (dashboard API). The browser-side
  `api.github.com` call should go away.
- Python HTTP: the app already depends on `requests` (which bundles `certifi`). Plain `urllib`
  under python.org's macOS Python failed TLS verification here
  (`CERTIFICATE_VERIFY_FAILED`) [T]. Use `requests` (or `truststore`), not bare `urllib`.

---

## 2. Survey: how others ship updates

### 2.1 Frameworks

| System | Platforms | Feed / manifest | Integrity / authenticity | Payload & apply | Fit for this app |
|---|---|---|---|---|---|
| **Sparkle 2** | macOS | RSS appcast (`SUFeedURL`), `generate_appcast` builds appcast + `.delta` files | **EdDSA (Ed25519)**: `generate_keys` puts the private key in the Keychain and `SUPublicEDKey` in Info.plist. Optional signed feed (`SURequireSignedFeed`, validated from 2.9). Developer ID + notarization recommended, "if possible" | dmg/zip/tar/pkg; helper tools; deltas checked against a checksum | Native ObjC framework. Ad-hoc signing plus Library Validation can stop Sparkle loading. macOS-only. [V sparkle-project.org/documentation] |
| **WinSparkle** | Windows | Sparkle-compatible appcast | **EdDSA Ed25519**; DSA deprecated | Runs downloaded installer | Has `pywinsparkle` bindings, but pairing it with Sparkle means two native stacks and still nothing for Linux. [V github.com/vslavik/winsparkle] |
| **Squirrel.Mac / Electron `autoUpdater`** | macOS | JSON/RELEASES | "Your application must be **signed** for automatic updates on macOS" (Squirrel.Mac requirement); SHA-256/size check | ShipIt helper installs on terminate | Unusable unsigned. [V electronjs.org/docs/latest/api/auto-updater, github.com/Squirrel/Squirrel.Mac] |
| **Squirrel.Windows** | Windows | `RELEASES` | SHA-1 in RELEASES | `%LOCALAPPDATA%\<app>\app-x.y.z` folders, Update.exe | Repo last pushed 2024-07 [T gh api]; superseded by Velopack. |
| **electron-updater (electron-builder)** | Win/mac/Linux | `latest.yml` / `latest-mac.yml` with `files[]{url, sha512, size}`, `stagingPercentage` | sha512 in the same feed; macOS app must be signed; Windows `verifyUpdateFileAuthenticodeSignature` | NSIS installer `quitAndInstall({isSilent, isForceRunAfter})`; blockmap differential downloads (mac differential since 6.2/6.3) | Electron-only, but **the manifest shape and the "update payload = installer" idea carry over directly**. [V electron.build/docs/features/auto-update] |
| **Tauri v2 updater plugin** | Win/mac/Linux | Static `latest.json`: `version` (SemVer), `notes`, `pub_date`, `platforms["darwin-aarch64"…]{url, signature}`; dynamic servers return 204 for no update | **Signature mandatory**, "cannot be disabled"; `signature` is the `.sig` file *content*; pubkey embedded in config; lost private key means no more updates | macOS `.app.tar.gz`; Windows runs the NSIS/MSI with `installMode` passive/basicUi/quiet ("quiet" works only for per-user installs) | The plugin itself can't update the PyInstaller parent (it would update the nested overlay bundle) [I]. **Copy its manifest + signature model.** It requires SemVer, so 4-part `0.6.5.3` is not accepted as-is [V v2.tauri.app/plugin/updater; I for the 4-part rejection]. |
| **Velopack** (`vpk` + `velopack` PyPI 1.2.161, 2026-09-29) | Win/mac/Linux | `releases.{channel}.json` with full+delta entries (SHA1/SHA256, size) | **Hash only; no package signature.** It does not check the new bundle's code signature. "The unsigned apps that would benefit most from an integrity check get nothing" [V github.com/velopack/velopack/issues/975] | Windows: installs to `%LocalAppData%\{packId}\current` + `Update.exe` + stub exe; whole `current/` replaced; kills locking processes. macOS: `.app` replaced from `~/Library/Caches/velopack/…`; AppleScript admin prompt if not writable; `.pkg` installer | Detailed in section 5.2. [V docs.velopack.io/getting-started/python, …/packaging/operating-systems/{windows,macos}, pypi.org/project/velopack] |
| **tufup** (0.10.0, 2025-10-04) | Win/mac (Linux: "use native packaging") | TUF metadata (root/targets/snapshot/timestamp) + `.tar.gz` archives + patches | TUF: signed metadata with expiry, rollback/freeze protection | Default install copies the archive over the install dir; Windows runs a script in a new process then exits | Section 5.3. [V github.com/dennisvang/tufup, pypi tufup] |
| **PyUpdater** | — | — | — | — | **Archived** (repo `archived: true`, last push 2022-09; last PyPI 4.0 in 2021-04) [T gh api / PyPI JSON]. Dead. |
| **Google Omaha (Chrome)** | Win (Keystone on mac) | Omaha v3 XML protocol; `<package hash_sha256 …>`; server-side decisioning, differential (`hashdiff_sha256`) | Signed binaries + server | Machine-level service | Needs a server. Only the protocol idea is relevant (server-decided rollouts). [V github.com/google/omaha …/ServerProtocolV3.md] |
| **VS Code (Windows)** | Win | Own update service with `sha256hash` | Checks the download checksum before running | **Inno Setup.** On quit it spawns `setup.exe /silent /log /mergetasks=…` detached, with `__COMPAT_LAYER=RunAsInvoker`. Background mode adds custom `/verysilent /update=<flag> /nocloseapplications` plus the `inno_updater.exe` helper to swap files after exit | **Closest prior art for Windows**: an Inno-based app that self-updates by running the next setup.exe silently. [V microsoft/vscode `src/vs/platform/update/electron-main/updateService.win32.ts`; github.com/microsoft/inno-updater] |
| **Discord** | Win | Squirrel-style `packages/` + versioned `app-x.y.z` folders; host + module updates | — | Squirrel Update.exe | Secondary sources only [V-ish: support.discord.com community post; any.run report]. Not relevant. |
| **Obsidian** | all | — | — | Two tiers: auto-updates only the app JS bundle (asar). The "installer" (Electron runtime) is never auto-updated; users are told to reinstall when a minimum installer version is required | Interesting split, but not applicable to a frozen PyInstaller binary [V forum.obsidian.md/t/q-a-why-obsidian-has-two-version-numbers/110663, npmjs obsidian-launcher]. |
| **AppImageUpdate** (Linux) | Linux | Update info embedded in the AppImage: `zsync|<url>` or `gh-releases-zsync|user|repo|latest|App-*x86_64.AppImage.zsync` (`latest` excludes prereleases) | Signature validation for updates "planned but not yet implemented" | zsync block-level delta; writes the new file next to the old one | Option for Linux later [V docs.appimage.org/packaging-guide/optional/updates.html, github.com/AppImage/AppImageSpec draft.md]. |

### 2.2 Other MTG Arena trackers

| App | Stack | Update mechanism | Self-updates? |
|---|---|---|---|
| **17Lands client** | Windows: .NET ClickOnce (`clickonce/setup.exe`). Mac/Linux: Python (`pip install seventeenlands`, Homebrew) | ClickOnce "will prompt you when updates are available". Python users run `pip install --upgrade` / `brew upgrade` manually | Windows prompt-based; Mac/Python manual. [V github.com/rconroy293/mtga-log-client README; 17lands.com/getting_started; x.com/17Lands status 1909053038641234390] |
| **Untapped.gg Companion** | Electron (electron-builder) | `https://companion.untapped.gg/releases/latest.yml` (NSIS web-installer `.nsis.7z` package with `blockMapSize`, sha512) and `mac-releases/latest-mac.yml` (universal zip + dmg, sha512). Own S3/CDN feed, not GitHub | Yes, electron-updater. [T curl of both yml files] |
| **MTGA Pro Tracker / mtgap (Razviar)** | Electron Forge (`maker-squirrel`, `maker-dmg`, `publisher-github`) | `update-electron-app@3.0.0`, i.e. Electron's hosted `update.electronjs.org` over GitHub Releases. Requires a public repo and signed macOS builds | Yes. [T `gh api repos/Razviar/mtgap/contents/package.json`; V electronjs.org/docs/latest/tutorial/updates] |
| **MTGATracker (legacy, mtgatracker org)** | Electron | `electron-gh-releases` against a separate "robots only" GitHub repo `mtgatracker-updates` ("Cheaper than AWS by 100%"), Windows only | Yes on Windows; project inactive since 2020. [T gh api README] |
| **Arena Tutor (Draftsim)** | Overwolf app, Windows-only | Overwolf platform pushes updates via release channels with phased rollout; apps update "every few hours or when Overwolf restarts" | Yes, platform-managed. [V mtg.wiki/page/Arena_Tutor; dev.overwolf.com …/release-management] |
| **Untapped/Draftsim/17Lands, general** | — | None of these ships a PyInstaller app with in-app install | 17Lands' Python client is the only Python one, and it does not self-update. |

Takeaway [I]: everyone with seamless updates is either Electron (Squirrel/electron-updater, a
signed mac app) or platform-managed (Overwolf, ClickOnce). A Python/PyInstaller tracker that
self-updates has no off-the-shelf equivalent in this niche. The pattern to copy is
electron-updater/VS Code: a static manifest plus the real installer, run silently.

---

## 3. GitHub as the update server

### 3.1 Facts

- REST API unauthenticated primary limit: **60 requests/hour, counted per originating IP**
  [V docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api]. Many players
  behind one CGNAT/campus IP can exhaust it. Velopack's `GithubSource` uses this API
  (`/repos/{o}/{r}/releases?per_page=10`). Its source comment says: "Without one, rate limited
  to 60 req/hr per IP" [T `velopack/src/lib-rust/src/sources/github.rs`].
- `https://github.com/<o>/<r>/releases/latest/download/<asset>` "links directly to the
  download" of the latest release's asset [V docs.github.com/…/linking-to-releases].
  "Latest" is "the most recent non-prerelease, non-draft release, sorted by created_at", and
  "Drafts and prereleases cannot be set as latest" (`make_latest`)
  [V docs.github.com/en/rest/releases/releases#get-the-latest-release]. So **draft releases
  are never served by this URL**, and prereleases aren't either.
- Observed redirect chain [T curl, 2026-10-12]:
  1. `github.com/…/releases/latest/download/X` → **302**, `cache-control: no-cache`, to
     `github.com/…/releases/download/v0.6.5.3/X`. The pointer is resolved per request, so a
     newly published release is visible immediately.
  2. → **302**, `no-cache`, to a time-limited signed URL on
     `release-assets.githubusercontent.com` (`se=` expiry about 1 h).
  3. → **206** with `accept-ranges: bytes`, served via Fastly/varnish (`x-cache: HIT`).
     **Range requests work**, so downloads can resume. Re-resolve from step 1 after expiry.
  - A missing asset still 302s at step 1 to the tag URL and 404s later. Treat any non-200 at
    the end as "no manifest".
- These github.com download URLs are not part of the REST API, and the REST doc does not
  count them against the 60/hr limit [I; the doc is silent on release downloads]. They still
  have undocumented abuse limits [I]. One small JSON fetch per client per few hours is
  harmless.
- `raw.githubusercontent.com` serves `cache-control: max-age=300`, ETag, and `ACAO: *`
  [T curl]. That suits a **channel feed** (e.g. beta) committed to a branch, with up to
  5 minutes of staleness.
- Release asset digests: since 2025-06 GitHub computes and exposes SHA-256 `digest` per asset
  in REST/GraphQL/UI. Older assets were not backfilled
  [V github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/;
  T present on v0.6.5.3 assets].
- **Immutable releases** (GA 2025-10-28): once published, assets "can't be added, modified, or
  deleted", and tags "can't be deleted or moved". Title/notes and prerelease/latest flags stay
  editable. Releases get Sigstore attestations. The recommended flow is "create the release as
  a draft → attach all assets → publish", which matches the current draft gate exactly
  [V github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/;
  docs.github.com/…/immutable-releases]. The repo currently shows `immutable: false` [T].
- Renaming assets: the REST "update a release asset" endpoint accepts a new `name` [I from
  general API knowledge; the fetched page did not show it]. This is irrelevant if immutable
  releases are enabled, and it is not needed in the design. **Do not rely on mutating assets
  after publish.** A fix is a new version.

### 3.2 Design consequences

- Use **`…/releases/latest/download/latest.json`** for the stable channel (no API, no auth,
  never drafts). Inside the manifest, **pin payload URLs to the tag**
  (`…/releases/download/v0.6.6/MTGA-Tracker-0.6.6-setup.exe`). The manifest and its payloads
  then always come from the same release, even if "latest" moves mid-download.
- Asset names must be **stable across versions** (`latest.json`, `latest.json.sig`), because
  the `latest/download` path selects by name.
- Beta/rc channel (later): either a `beta.json` committed to a branch and read via `raw.` or
  Pages, updated by a workflow on `release: published`, or the API with ETag-conditional
  requests (304s do not count against the limit if authenticated, but here they'd be
  unauthenticated [I]). Keep v1 stable-only.
- Enable **immutable releases** on the repo. This costs nothing given the draft flow, and it
  stops anyone from swapping an asset of an already-trusted version.
- Poll politely: check at startup (after ~1–2 min) and every 6 h, with jitter. Send a
  `User-Agent: TappsTracker/<ver>`. Use `If-None-Match`/`If-Modified-Since` where the final
  host supports them.

---

## 4. Trust model without Apple Developer ID or Authenticode

### 4.1 What each layer buys

| Layer | Protects against | Does NOT protect against |
|---|---|---|
| HTTPS to github.com (cert validation via certifi/truststore) | Network MITM, captive portals, corrupted proxies | Anything with control of the GitHub repo/release |
| Size + SHA-256 **in the same release** (or GitHub's `digest`) | Truncation/corruption, CDN glitches, partial resumes, local tampering between download and launch | **Repo/account compromise**: whoever can upload a malicious asset can upload a matching checksum/manifest. Integrity only, no authenticity [I; consistent with velopack#975 and Doyensec's "Hashes served alongside an unsigned download would not provide the same guarantee"] |
| **Ed25519 signature over the manifest, public key embedded in the app** (Sparkle `SUPublicEDKey`, Tauri `pubkey`, WinSparkle EdDSA) | Malicious releases from a compromised GitHub account / token / workflow, **if the private key is not in GitHub** | Compromise of the signing key itself; a malicious build signed by the maintainer |
| Version bound inside the signed manifest + "never install ≤ current" | Downgrade/rollback to an old vulnerable but validly signed build [V blog.doyensec.com/2026/02/16/electron-safe-updater.html, "Bind the version into the signed message"] | Freeze attack (serving an old manifest): this only delays updates, which is acceptable here [I] |
| OS code signing (Developer ID + notarization / Authenticode) | Gatekeeper/SmartScreen trust, App Management protection, identity across updates | n/a, **not available here** |
| GitHub immutable releases + attestations | Post-publish tampering with assets/tags | A new malicious release published by an attacker |

### 4.2 Recommended minimum

1. HTTPS only, with certificate verification, and no redirects off an allow-list
   (`github.com`, `release-assets.githubusercontent.com`, `objects.githubusercontent.com`) [I].
2. The manifest carries `version`, `tag`, and per-platform `url`, `size` and `sha256`.
3. A **detached Ed25519 signature** over the exact manifest bytes (`latest.json.sig`). Verify
   it **before parsing** the manifest's contents into decisions. Embed 1–2 public keys in the
   app: a primary key plus an offline backup key for rotation. Tauri warns that losing the
   key means existing users can never update again [V v2.tauri.app/plugin/updater].
   - Format: either raw Ed25519 (sign with `openssl pkeyutl -sign -rawin` or a 20-line Python
     script) or **minisign**, which Tauri uses under the hood
     ([V] Tauri "pubkey" is a minisign key per zenn.dev/monkuma article; I for "under the
     hood"). Verify with `cryptography`'s `Ed25519PublicKey`, PyNaCl, or a vendored
     pure-Python RFC 8032 verifier. Minisign's prehashed mode signs a BLAKE2b-512 digest, and
     `hashlib.blake2b` is in the stdlib [I/V-ish: pypi.org/project/py-minisign,
     pypi.org/project/minisign]. Check whether `cryptography` is already in the frozen
     bundle before adding a dependency.
4. Hash every payload (streaming SHA-256) **after** download and **again immediately before
   execution or swap**, from a directory only the user can write (0700). This narrows TOCTOU
   [V Doyensec, "verification and installation should operate on the same file
   descriptor" and the owner-only temp dirs].
5. On macOS, also run `codesign --verify --deep --strict` on the staged `.app`. An ad-hoc
   signature has no identity, but it still seals the bundle contents. That catches a
   partially copied or modified bundle [I; the repo's build script already uses this check].
6. **Where the private key lives is the whole game:**
   - **Preferred:** the maintainer signs **locally after reviewing the draft**. A script
     downloads the draft's assets with `gh`, recomputes hashes, writes `latest.json`, signs
     it, uploads `latest.json` + `.sig`, and the maintainer then publishes. A GitHub account
     compromise or a poisoned Actions workflow then **cannot** ship an update clients accept.
     This mirrors Sparkle's Keychain-held key [V Sparkle docs].
   - **Acceptable fallback:** the key lives in an Actions secret, scoped to a protected
     environment that requires manual approval. This is weaker, because anyone who controls
     the repo can run a signing workflow [I].
7. Keep a "kill switch": the manifest can carry `"min_version"`/`"blocked": [...]`. Since it's
   signed, it can also force-offer a fix over a broken release [I].

**Does checksum-in-the-same-release help at all?** Yes, but only for integrity: it catches
corruption, truncated or resumed downloads, and CDN issues. It also lets the UI show a
progress-verified state. It adds **zero** authenticity against an attacker who can publish
releases. GitHub's own `digest` field is equivalent and also same-origin [I].

### 4.3 Risk if the GitHub account is compromised

- **Today** (link to a release page): an attacker can publish a malicious release. Users who
  click through, and then Gatekeeper/SmartScreen prompts, run it. The blast radius is limited
  by user action.
- **With an unsigned auto-updater** (hash-only, e.g. Velopack today): the attacker publishes a
  release, and **every running client silently downloads and executes it**. Downloads made by
  a non-browser process carry no quarantine or Mark-of-the-Web (section 6), so **no OS prompt
  appears either**. This is strictly worse than today; it amounts to remote code execution
  for the whole user base [I].
- **With the offline-signed manifest:** the attacker can publish a release, but clients reject
  it because the signature fails. The residual risk is a compromised maintainer machine or key
  (mitigated by keeping the key in a passphrase-protected file or hardware token, with a
  backup key embedded) [I].

---

## 5. Recommendation

### 5.1 Chosen: hand-rolled Python updater + signed static manifest

**Manifest** (`latest.json`, attached to every release; produced by a CI `manifest` job after
both build jobs; signed by the maintainer):

```json
{
  "schema": 1,
  "product": "tapps-tracker",
  "version": "0.6.6",
  "tag": "v0.6.6",
  "pub_date": "2026-10-20T03:00:00Z",
  "notes_url": "https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.6",
  "min_supported_from": "0.6.0",
  "platforms": {
    "macos-arm64":  {"kind": "dmg",      "url": "https://github.com/pattont/MTGA-Tapps/releases/download/v0.6.6/MTGA-Tracker-0.6.6.dmg",          "size": 47474361, "sha256": "…"},
    "windows-x64":  {"kind": "inno",     "url": "https://github.com/pattont/MTGA-Tapps/releases/download/v0.6.6/MTGA-Tracker-0.6.6-setup.exe",   "size": 37883840, "sha256": "…"},
    "windows-x64-portable": {"kind": "zip", "url": "…/MTGA-Tracker-0.6.6-windows.zip", "size": 50697026, "sha256": "…"}
  }
}
```

Plus `latest.json.sig` (Ed25519 over the exact bytes). Versions are PEP 440 strings, compared
with PEP 440 rules (vendor `packaging.version` or a small comparator). This is not SemVer
(that rules out Tauri's plugin as-is).

**Client flow** (new `src/mtga_tracker/updater.py` plus a `updater_apply_*.py` per OS; state
exposed via `/api/update/*`, settings in `settings.json` → `updates`):

1. **Check:** a background thread, ~90 s after startup, then every 6 h with jitter. Disabled
   for source runs (not frozen) and when `MTGA_TRACKER_NO_UPDATE=1` [I]. Fetch `latest.json`
   and `.sig`, verify the signature, compare versions, pick the platform key.
2. **Download:** stream to `<data dir>/updates/<version>/payload.part` (0700) with
   `requests`, Range-resume, and a low-priority, throttle-friendly chunked write. Never block
   the tracker thread.
3. **Verify:** size, then SHA-256; rename `.part` to final. On macOS, additionally mount and
   stage (see below), then `codesign --verify --deep --strict` on the staged app. State
   becomes `ready`.
4. **Offer:** the sidebar bottom-left shows "Update ready: v0.6.6 — Restart to update". In
   `auto` mode the app applies when the **safe-to-restart predicate** holds:
   `live_status.in_game == 0` for ≥ N minutes, no deck transfer job pending or running, no
   collection export, no DB restore, no Deck Finder terminal child. Or it applies **on quit**
   (electron-updater's `autoInstallEvent: "onQuit"` default [V electron.build]). Never apply
   mid-game. AGENTS.md forbids restarting the tracker without user approval, so the opt-in
   setting **is** that approval.
5. **Apply:**
   - **Windows (Inno):** stop the overlay and tracker cleanly
     (`mark_live_status_stopped`), release the single-instance mutex, and spawn the verified
     `setup.exe` detached with
     `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL /LOG="<data>\updates\setup.log" /CURRENTUSER|/ALLUSERS /RELAUNCH=1`.
     Use `CREATE_NO_WINDOW|DETACHED_PROCESS`, and `__COMPAT_LAYER=RunAsInvoker` for per-user
     installs, the same as VS Code [V vscode updateService.win32.ts]. Then exit.
     Inno changes needed:
     - a `[Run]` entry for silent relaunch, gated by a `Check:` on a custom `/RELAUNCH`
       parameter (the existing entry is `skipifsilent`);
     - `[Code] InitializeSetup` waits (with a timeout) for the app's named single-instance
       mutex to disappear (`CheckForMutexes` loop), so file locks are gone before
       "Preparing to install". `CloseApplications=yes` remains the fallback; in silent mode
       Setup "will always close and restart such applications"
       [V jrsoftware.org/ishelp/topic_setup_closeapplications.htm]. Note that this fallback
       would also kill a mid-game tracker if someone runs a silent setup by hand.
     - Pass the install mode explicitly. The updater detects all-users vs per-user from where
       it runs: under `Program Files` means `/ALLUSERS`, which triggers a UAC prompt, so it
       can't be fully silent. Tell the user [V Inno `/CURRENTUSER`, `/ALLUSERS`,
       `UsePreviousPrivileges`; I for detection].
     - **Portable zip** installs (no `unins000.exe` beside the exe): v1 shows "Download"
       only. v2 can swap folders via a helper [I].
   - **macOS (DMG reuse):** `hdiutil attach -nobrowse -readonly -noautoopen -mountrandom <tmp>`
     on the verified DMG, then `ditto` the `.app` to a **sibling staging path on the same
     volume** (e.g. `/Applications/.MTGA Tracker.app.update-0.6.6`), detach, and verify the
     signature. On "Restart", spawn a detached `/bin/sh` helper (an Apple-signed binary) that:
     waits for the old PID to exit; `mv` old → `.old`; `mv` staged → original path (both
     `rename(2)` on one volume, so each step is atomic); removes stray
     `com.apple.quarantine` defensively; `open` the app with an `--updated-from=<ver>` arg;
     deletes `.old`; and rolls back if the new app does not write a "started OK" marker within
     N s [I]. This follows Apple DTS: "create an entirely new copy of the app bundle and then
     replace the old copy" rather than modifying a launched bundle
     [V developer.apple.com/forums/thread/761436]. If the parent dir isn't writable (standard
     user, root-owned `/Applications` copy) or the app is translocated or running from the
     DMG, fall back to "Download update" (or an `osascript … with administrator privileges`
     prompt, as Velopack does [V Velopack macOS docs]).
   - **Linux (later):** download the AppImage next to `$APPIMAGE`, verify, `chmod +x`, rename
     over it after exit, relaunch. Optionally add zsync deltas via AppImageUpdate later
     [V docs.appimage.org updates page].
6. **Post-update:** the new version starts, migrations run as today, the old staging and
   payload are cleaned up, and the dashboard shows "Updated to v0.6.6" with a changelog link.

**CI changes**

- A new `manifest` job (`needs: build`, tag runs only) downloads the draft's assets
  (`gh release download --pattern …`), computes size/SHA-256, writes **unsigned**
  `latest.json`, and uploads it to the draft.
- New `scripts/sign_update_manifest.py` (maintainer, local): pull the draft's `latest.json`
  and assets, recompute and compare hashes, sign, upload `latest.json.sig`, and refuse if
  anything mismatches. Add this step to `docs/RELEASING.md` before "Publish". Optionally
  enable repo **immutable releases**.
- Optional: a CI test that verifies the signature with the embedded public key on the
  published release (smoke).
- No new toolchains. No change to AppId, artifact names, or install paths.

**Effort / reliability (estimate [I])**

- Python updater core (check/download/verify/state machine, settings, API) about 500–800
  lines; per-OS apply about 150–250 lines each; Inno `[Code]`/`[Run]` changes; CI manifest job
  and signing script; sidebar + Settings UI; tests (signature, version compare, manifest
  parsing, resume, safe-to-restart gating, fake-install swap on a temp dir). Roughly **1.5–3
  focused weeks**, including real-OS validation on both platforms.
- Reliability depends mostly on the Windows exit→setup handoff and the macOS swap/relaunch.
  Both use well-trodden primitives (Inno silent install with Restart Manager fallback;
  `rename(2)` plus `open`). Rollback on macOS is straightforward. On Windows, Inno's own
  rollback applies only to files it wrote; `[InstallDelete] {app}\_internal` is not restored
  on failure [I]. Consider removing that `InstallDelete` in favour of Inno's
  `ignoreversion` + an uninstall-previous-files approach, or accept the failure mode and
  tell the user to rerun setup.
- Bandwidth: full payloads of 38–48 MB per update. Background download makes this
  acceptable. Deltas could come later (bsdiff of the PyInstaller tree, or Velopack) if needed.

### 5.2 Alternative A, Velopack (not chosen)

**Pros:** maintained and active (1.2.161, 2026-09-29) [V PyPI]. A real Python SDK
(`UpdateManager(source, options, locator)`, `check_for_updates`, `download_updates`,
`wait_exit_then_apply_updates(update, silent, restart)`) and `GithubSource`/`HttpSource`
[V docs.velopack.io/reference/py/UpdateManager, /Sources]. Delta packages; one real report is
a 79 MB full vs 237 KB delta [V KudcraftsHQ/ntfy-bar-windows PR #2]. Handles Windows
lock-killing and macOS bundle replacement, including an admin prompt.

**Why not:**

1. **No authenticity.** It verifies only the SHA from the feed and has no package signature.
   Issue #975 proposes it as future work [V]. For an unsigned app this gives exactly the
   GitHub-compromise RCE profile in section 4.3. We'd have to bolt our own signature check
   onto Velopack's cache files [I].
2. **Migration off Inno.** Velopack installs to `%LocalAppData%\{packId}\current` with
   `Update.exe` and its own Setup.exe. A machine-wide install needs its MSI path
   [V Velopack Windows docs]. Existing Inno installs (`%LOCALAPPDATA%\Programs\MTGA Tracker`
   or Program Files), the fixed AppId upgrade path, Start-with-Windows Run-key paths, and
   uninstall data would all need a one-time migration and an Inno uninstall [I].
3. **GitHub source uses the REST API** (60/hr/IP) [T source]. The no-API workaround
   (`HttpSource` on `releases/latest/download`) "only works for stable … does not support
   deltas" [V velopack#723 comment], which removes Velopack's main advantage.
4. **macOS + PyInstaller is unproven.** A Feb-2025 report showed Velopack wrapping a
   PyInstaller onedir into `Contents/MacOS`, which broke the bootloader's `.app` mode
   [V github.com/orgs/pyinstaller/discussions/9029]. Velopack now accepts a pre-built `.app`
   as `--packDir` "as-is" [V Velopack macOS docs], which probably avoids that. But signing
   defaults (deep sign, notarization flags), the ad-hoc case, the nested `Tapps Overlay.app`,
   and our `LSUIElement` bundle are untested [I].
5. It adds the .NET SDK (`vpk`) to CI, and `velopack.App().run()` must be the very first call
   in `entrypoint.py` [V Velopack Python docs]. That interacts with the single-instance guard
   and the `--deck-finder` / `--login-start` modes [I].
6. Version format: Velopack's `SemanticVersion` accepts SemVer2 "with an optional 4th
   revision component" [V docs.velopack.io/reference/cs/Velopack/SemanticVersion]. PEP 440
   `0.6.3rc8` would need mapping to `0.6.3-rc.8` [I].

**When to revisit:** if Velopack ships package signing (#975), or if update size becomes a
real complaint.

### 5.3 Alternative B, tufup (TUF) (not chosen)

**Pros:** the strongest security model on paper (python-tuf, signed metadata with expiry,
rollback/freeze protection). Patches with full-archive fallback. Pure Python. It is the
de-facto PyUpdater replacement [V github.com/dennisvang/tufup].

**Why not:**

1. Its default apply **copies archive contents over the install directory**. That is the
   anti-pattern on macOS (modifying a launched bundle; Apple DTS says to build a new copy and
   swap) and it bypasses Inno on Windows, so the Apps & Features version and uninstall data
   go stale [V tufup README; V Apple forum 761436; I for the Inno consequence]. We'd write a
   custom `install` hook anyway, which is most of the work in 5.1.
2. TUF operational burden: four roles and keys, plus metadata `expires`, so timestamp and
   snapshot must be re-signed periodically or clients refuse updates. That is a poor fit for a
   solo maintainer with an irregular release cadence [I, TUF spec semantics].
3. Bus factor and cadence: last release 0.10.0 on 2025-10-04, 19 open issues [T PyPI/GitHub].
   Only top-level roles, no delegations; Linux is explicitly out of scope ("use native
   packaging") [V].

### 5.4 Also considered

- **Sparkle (mac) + WinSparkle (win):** proven EdDSA appcasts, but two native frameworks to
  embed in PyInstaller. Sparkle plus an ad-hoc signature can hit Library Validation
  [V Sparkle docs]. Nothing covers Linux, and the UI lives outside our dashboard [I].
- **Tauri updater plugin via the overlay:** the plugin updates the bundle containing the
  running Tauri binary, which is the nested overlay, not the PyInstaller parent [I]. It also
  needs SemVer. Reuse the *format and ideas* only.
- **electron-updater / Squirrel / update.electronjs.org:** Electron-only, and they need a
  signed macOS app [V].

---

## 6. Gotchas

### 6.1 macOS

- **Quarantine:** downloads made by curl and Python (urllib) get **no `com.apple.quarantine`**
  [T on macOS 27.0.1: both files carried only `com.apple.provenance`].
  [V developer.apple.com/forums/thread/706442 says most Unix-y tools don't quarantine;
  discussions.apple.com/thread/256200611]. Only apps that opt in (`LSFileQuarantineEnabled`)
  or use LaunchServices/WebKit download APIs quarantine their files [I; I found no primary
  doc for `LSFileQuarantineEnabled`]. Consequences:
  - (a) The updated app launches **without** a Gatekeeper prompt. That is good UX, and it
    puts all the security weight on our signature check.
  - (b) **Do not add `LSFileQuarantineEnabled`** to Info.plist. If it is ever added, the
    updater must strip quarantine from the staged bundle, or the new copy gets translocated
    and can't update itself [V caseymrm/menuet PR #63 via search summary].
- **`com.apple.provenance`** (macOS 13+) is attached anyway [T]. It's used for App
  Management/provenance tracking, not Gatekeeper prompts [I].
- **App Translocation:** a quarantined app launched from where it was downloaded (or from the
  DMG) runs from a randomized read-only mount. Updaters then fail with read-only errors.
  Detect via `SecTranslocateIsTranslocatedURL` (private header; load with `dlopen`) or by
  checking for a read-only volume or a `/AppTranslocation/` path, and show "Move to
  Applications" instead of updating [V objective-see.org/blog/blog_0x15.html,
  lapcatsoftware.com/articles/detect-app-translocation.html, GitHub PRs in search results].
  Also refuse updating when running from `/Volumes/…` (inside the DMG) [I].
- **App Management (Ventura+):** Gatekeeper protects **notarized** apps from modification by
  code not signed by the same team or allowed by `NSUpdateSecurityPolicy`
  [V lapcatsoftware.com/articles/AppManagement.html, eclecticlight.co 2022/06/17]. Our app is
  not notarized, so this protection most likely doesn't apply. It would apply after a move to
  Developer ID notarization, where same-team signing makes self-update fine [I]. Ad-hoc
  helpers with no TeamIdentifier that run at changing paths have triggered the App Management
  prompt in other projects; the fix was to have the bundle's own executable or a stable
  helper do the replacement [V search summary of trukhinyuri/codex-superpower PR #7; the page
  itself 404'd for me]. **Verify on a real Mac in the spike.**
- **Replacing a running bundle:** never modify the running bundle's contents. A PyInstaller
  onedir app imports lazily from `sys._MEIPASS` (`Contents/Frameworks` / `Resources`), so
  renaming it away while running breaks later imports [I]. Swap only **after the old process
  has exited**, from a separate helper process.
- **Symlinks:** PyInstaller 6 `.app` bundles use symlinks. `zip` without `-y`, `cp -r`, or
  Python `zipfile` drop them and break the bundle and its signature
  [V pyinstaller.org/en/stable/common-issues-and-pitfalls.html]. Use `ditto` (or tar) for
  copying and extraction.
- **Signing and nesting:** the build uses `codesign --deep`, which Apple DTS calls harmful
  (one set of options for all nested code; misses code in data locations)
  [V developer.apple.com/forums/thread/129980]. Verification with `--deep --strict` is fine.
  For ad-hoc it works today. If Developer ID ever arrives, sign inside-out (the overlay helper
  first) [V same thread]. The updater must copy the **whole** bundle, including
  `Contents/Helpers/Tapps Overlay.app`. Never patch the overlay separately, or the outer seal
  breaks [I].
- **Ad-hoc identity changes every build:** TCC grants keyed to the code signature (e.g.
  Accessibility, if ever needed) can reset after updates. Ad-hoc local builds "lose macOS
  privacy and filesystem grants across rebuilds" [V github.com/lu-zhengda/updater via search
  summary]. Check whether the overlay or tracker relies on any TCC grant [I].
- **TLS roots:** frozen Python must ship CA roots (`certifi` via `requests`, or
  `truststore`). Bare urllib failed here [T].
- **Tauri's own updater bug for reference:** an updated `.app` installed with 0700 temp-dir
  permissions became unlaunchable for other users [V tauri-apps/plugins-workspace#3506 title].
  Make sure the final bundle mode is 0755 even if the staging dir is 0700 [I].

### 6.2 Windows

- **SmartScreen / Mark-of-the-Web:** only browsers and the Attachment Manager add
  `Zone.Identifier`. A setup.exe downloaded by our Python process has no MOTW, so SmartScreen
  does not prompt when we run it [V textslashplain.com/2016/04/04/downloads-and-the-mark-of-the-web/;
  developer test in danswett/ha-desktop PR #23]. The same caveat as macOS applies: our
  signature is the only gate.
- **Smart App Control (Win 11):** it blocks **unsigned** executables without positive
  reputation **regardless of MOTW** [V learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation].
  Users with SAC on probably couldn't install the app at all. Each new setup.exe is a new
  unsigned file and could be blocked during update. Detect a launch failure and fall back to
  "Download manually" [I].
- **AV false positives:** PyInstaller bootloaders that are unsigned are frequently flagged.
  An app that downloads and runs an unsigned exe can look worse heuristically [V
  discuss.python.org/t/pyinstaller-false-positive/43171; I for the heuristic point]. Keep the
  version resource populated (the spec already does) and consider a custom-built bootloader if
  flags appear.
- **Inno silent flags:** `/SILENT` shows progress and `/VERYSILENT` shows nothing.
  `/SUPPRESSMSGBOXES` picks default answers. `/NORESTART`, `/SP-`, `/NOCANCEL`, and
  `/LOG[=file]` are all available. `/CURRENTUSER` and `/ALLUSERS` take effect only when
  `PrivilegesRequiredOverridesAllowed` permits it (ours: `dialog`, which implies command
  line) [V jrsoftware.org/ishelp/topic_setupcmdline.htm,
  topic_setup_privilegesrequiredoverridesallowed.htm]. With `UsePreviousPrivileges=yes`
  (default), Setup reuses the previous install mode [V
  jrsoftware.org/ishelp/topic_setup_usepreviousprivileges.htm]. Still pass it explicitly [I].
- **Restart Manager:** with `CloseApplications=yes`, Setup in silent mode "will always close
  and restart such applications, unless told not to via the command line" [V
  topic_setup_closeapplications.htm]. Our tray process plus the overlay child both hold files
  in `{app}`. The app should exit both itself before Setup starts, with Restart Manager only
  as the fallback. `RestartApplications=no` means relaunch must be done by our own `[Run]`
  entry [I].
- **Elevation:** all-users installs (Program Files) need UAC for every update. Tauri likewise
  notes "quiet" mode "only works for user-wide installs" [V Tauri docs]. VS Code disables
  updates when a user-setup instance runs as Administrator [V search summary of VS Code
  setup docs].
- **Background processes:** keep using `CREATE_NO_WINDOW` for any helper (AGENTS.md rule).
  `setup.exe` itself is GUI, and `/VERYSILENT` hides it.
- **Portable zip:** there is no installer to hand off to. Swapping the folder needs a
  helper that waits for exit. Defer to v2.

### 6.3 Linux (later)

- The AppImage runtime sets `$APPIMAGE`, the path of the running file. `AppImageUpdate
  $APPIMAGE` is the documented pattern [V docs.appimage.org updates page]. Our own flow is to
  download the full AppImage, verify the Ed25519 manifest and SHA-256, write it beside the old
  one, rename it over the old one after exit, and relaunch.
- `gh-releases-zsync|pattont|MTGA-Tapps|latest|MTGA-Tracker-*-x86_64.AppImage.zsync` embedded
  via `appimagetool -u` gives zsync deltas [V AppImageSpec]. The GitHub transport likely
  queries the API (rate limits) [I]. AppImageUpdate's own signature validation is "planned but
  not yet implemented" [V], so keep our manifest signature as the gate.

---

## 7. Spikes to run before committing to the plan

1. macOS: on a non-admin and an admin account, run the full DMG → stage → swap → relaunch
   flow on a non-notarized ad-hoc build. Confirm no App Management or Gatekeeper prompt, that
   the single-instance guard hands over cleanly, that the overlay helper relaunches, and that
   rollback works.
2. Windows: run `setup.exe /VERYSILENT … /RELAUNCH=1` from a just-exited tracker for both
   per-user and all-users installs. Confirm the `CheckForMutexes` wait, no leftover locked
   `_internal`, a correct Apps & Features version, and that the Start-with-Windows Run key
   still points to the right exe.
3. Bundle-size impact of the Ed25519 verifier (`cryptography` vs PyNaCl vs pure-Python).
4. Optional: a one-day Velopack spike on macOS with `--packDir "MTGA Tracker.app"` and no
   signing identity, to keep the alternative honest.

---

## 8. Sources

- Velopack: https://docs.velopack.io/getting-started/python · https://docs.velopack.io/packaging/operating-systems/macos · https://docs.velopack.io/packaging/operating-systems/windows · https://docs.velopack.io/reference/py/UpdateManager · https://docs.velopack.io/reference/py/Sources · https://docs.velopack.io/reference/py/Sources/GithubSource · https://docs.velopack.io/reference/cli/content/vpk-osx · https://docs.velopack.io/reference/cs/Velopack/SemanticVersion · https://pypi.org/project/velopack/ · https://github.com/velopack/velopack/issues/975 · https://github.com/velopack/velopack/issues/254 · https://github.com/velopack/velopack/issues/723 · https://github.com/velopack/velopack/issues/726 · https://github.com/velopack/velopack/pull/819 · https://github.com/velopack/velopack/blob/develop/src/lib-rust/src/sources/github.rs · https://github.com/KudcraftsHQ/ntfy-bar-windows/pull/2 · https://github.com/orgs/pyinstaller/discussions/9029
- Tauri: https://v2.tauri.app/plugin/updater/ · https://zenn.dev/monkuma/articles/c947bca541cb48?locale=en · https://github.com/tauri-apps/plugins-workspace/issues/3506 · https://tauri.app/release/updater/all-versions/
- Sparkle / WinSparkle: https://sparkle-project.org/documentation/ · https://github.com/vslavik/winsparkle
- Electron: https://www.electron.build/docs/features/auto-update/ · https://www.electronjs.org/docs/latest/api/auto-updater · https://www.electronjs.org/docs/latest/tutorial/updates · https://github.com/Squirrel/Squirrel.Mac · https://blog.doyensec.com/2026/02/16/electron-safe-updater.html
- VS Code: https://github.com/microsoft/vscode/blob/main/src/vs/platform/update/electron-main/updateService.win32.ts · https://github.com/microsoft/inno-updater
- Omaha: https://github.com/google/omaha/blob/main/doc/ServerProtocolV3.md
- Obsidian: https://forum.obsidian.md/t/q-a-why-obsidian-has-two-version-numbers/110663 · https://npmjs.com/package/obsidian-launcher
- Discord (secondary): https://support.discord.com/hc/it/community/posts/11473545264919 · https://github.com/cordpackers/Wumpdle
- tufup / PyUpdater: https://github.com/dennisvang/tufup · https://pypi.org/project/tufup/ · https://github.com/Digital-Sapphire/PyUpdater (archived)
- MTGA trackers: https://github.com/rconroy293/mtga-log-client · https://www.17lands.com/getting_started · https://x.com/17Lands/status/1909053038641234390 · https://companion.untapped.gg/releases/latest.yml · https://companion.untapped.gg/mac-releases/latest-mac.yml · https://github.com/Razviar/mtgap · https://github.com/mtgatracker/mtgatracker-updates · https://mtg.wiki/page/Arena_Tutor · https://www.overwolf.com/app/Draftsim-Arena-Tutor · https://dev.overwolf.com/ow-native/guides/developers-console/release-management
- GitHub: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api · https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases · https://docs.github.com/en/rest/releases/releases#get-the-latest-release · https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/ · https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/ · https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/immutable-releases
- macOS: https://developer.apple.com/forums/thread/761436 · https://developer.apple.com/forums/thread/129980 · https://developer.apple.com/forums/thread/706442 · https://discussions.apple.com/thread/256200611 · https://lapcatsoftware.com/articles/AppManagement.html · https://eclecticlight.co/2022/06/17/app-security-changes-coming-in-ventura/ · https://mjtsai.com/blog/2022/11/07/ventura-app-management/ · https://objective-see.org/blog/blog_0x15.html · https://lapcatsoftware.com/articles/detect-app-translocation.html · https://github.com/caseymrm/menuet/pull/63 · https://github.com/manaflow-ai/cmux/issues/1341 · https://github.com/lu-zhengda/updater · https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
- Windows: https://jrsoftware.org/ishelp/topic_setupcmdline.htm · https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm · https://jrsoftware.org/ishelp/topic_setup_usepreviousprivileges.htm · https://jrsoftware.org/ishelp/topic_setup_privilegesrequiredoverridesallowed.htm · https://jrsoftware.org/ishelp/topic_setup_appmutex.htm · https://textslashplain.com/2016/04/04/downloads-and-the-mark-of-the-web/ · https://github.com/danswett/ha-desktop/pull/23 · https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation · https://discuss.python.org/t/pyinstaller-false-positive/43171
- Linux: https://docs.appimage.org/packaging-guide/optional/updates.html · https://github.com/AppImage/AppImageSpec/blob/master/draft.md
- Signing libs: https://pypi.org/project/py-minisign · https://pypi.org/project/minisign
