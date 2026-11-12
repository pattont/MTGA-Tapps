# Windows code signing (SignPath Foundation)

**Status:** not applied yet. The README's [Code signing policy](../../README.md#code-signing-policy)
section is published so the application can point to it.

## Why

Windows builds are unsigned. Windows tracks the reputation of an unsigned file
by its exact hash, so every release starts from zero:

- **Smart App Control** (on for some clean installs of Windows 11 22H2+)
  blocks unsigned files that have no reputation. It blocked the 0.7.7.1 setup's
  unpacked `MTGA-Tracker-0.7.7.1-setup.tmp` during an in-app update, and it
  already blocks the overlay for some users (error 4551). A valid Authenticode
  signature from a trusted CA lets a file through.
- **SmartScreen** warns about downloads from an unknown publisher. A
  signature builds reputation on the certificate instead of on each file, so
  it carries over to later releases. A new certificate still needs some time.
- Machine-learning antivirus engines treat unsigned PyInstaller programs with
  suspicion (one VirusTotal flag, Deep Instinct, on a 0.7.7.x build). The
  bootloader is already compiled from source to help with Defender
  (`scripts/build_windows_app.ps1`).

The next release's in-app updater brings the old version back when Setup is
blocked (`update_install.windows_watch_command`) and says Smart App Control
did it, but only signing lets the update install.

## Why SignPath Foundation

It is free for open-source projects. The certificate is issued to SignPath
Foundation, so Windows shows **SignPath Foundation** as the publisher, not the
author. The private key stays on SignPath's HSM; the build sends files to
SignPath.io and gets them back signed, after a person approves each release.

Fallbacks if the application is refused: Certum's open-source code-signing
certificate (paid yearly, in the author's name, key in Certum's cloud), or
Azure Artifact Signing ($9.99 a month; individuals only in the US and Canada).

## Eligibility check (signpath.org/terms, read 2026-11-12)

| Condition | State |
| --- | --- |
| OSI-approved license for every component, no proprietary code | AGPL-3.0-or-later. Bundled Python packages: MIT, BSD, Apache-2.0, MPL-2.0 (certifi), PSF-2.0, GPL-3.0 (PyQt6), LGPL-3.0 (Qt), wxWindows 3.1 (Frida). Dashboard and overlay npm packages: MIT, ISC, Apache-2.0. Overlay crates: Tauri, serde, windows-rs, objc2 (MIT/Apache-2.0). Deck Finder ships site logos (trademarks, not code). |
| Released, actively maintained, documented on the download page | Yes (GitHub Releases, README, tappstracker.com). |
| Verifiable build from source, manual approval per release | GitHub Actions builds a draft release on a `v*` tag; publishing it is already a manual step. |
| Product name and version on every signed file | The PyInstaller spec sets `VSVersionInfo`, Tauri and Inno set theirs. Check the overlay's product name matches the project name SignPath enforces. |
| No hacking tools (nothing that circumvents security measures of its environment) | **Risk.** Deck Manager attaches to Arena with Frida; collection export reads Arena's memory. See the application text. |
| Respect privacy; announce system changes; provide uninstall | No telemetry or account. Network use is listed in the README's Data & privacy section. Start with Windows is an opt-in setting. Inno provides an uninstaller. |
| MFA for every team member on GitHub and SignPath | To do: confirm GitHub MFA is on. |
| Team roles named | In the README section (one maintainer holds every role). |
| "Code signing policy" on the home page and on download/release pages | README done. To do: tappstracker.com's download page, and a link in each release's notes. |
| Verifiable reputation for downloadable programs | 14 stars, 2 forks, about 5,000 release asset downloads, public since 2025-11-19 (checked 2026-11-12). May be borderline. |

## Application (signpath.org/apply)

Answer the form's questions from this text; keep it plain and complete,
including the process-attachment features.

> **Tapps Tracker** (repository `pattont/MTGA-Tapps`, home page
> tappstracker.com) is a free, open-source (AGPL-3.0-or-later) desktop
> companion for Magic: The Gathering Arena on Windows and macOS. It reads the
> game's own log file to record matches, shows statistics in a local
> dashboard served on 127.0.0.1, and draws an in-game overlay with the
> player's remaining library. Everything stays on the user's computer: no
> account, no telemetry. Network use is listed in the README's Data & privacy
> section (card images from Scryfall, a signed update manifest from GitHub
> Releases, public decklist sites the user browses, and an optional AI deck
> identification the user enables with their own API key).
>
> Windows releases are built by GitHub Actions from tagged commits
> (`.github/workflows/release.yml`) with PyInstaller (Python), Tauri (the
> overlay) and Inno Setup (the installer). We would sign `MTGA Tracker.exe`,
> `tapps-overlay.exe` and the setup. Unsigned releases are being blocked by
> Smart App Control, including in-place updates, which is why we are applying.
>
> Two optional features interact with the running Arena client, and only when
> the user starts them from the dashboard: Deck Manager backs up and restores
> the player's own decks by calling Arena's deck functions through Frida in
> the user's own session (no game or network traffic changes, no cheating
> functionality), and collection export reads Arena's process memory once,
> read-only, to list the cards the player owns. On Windows neither needs
> administrator rights. Neither one bypasses Windows security features, scans
> for vulnerabilities or changes the game's files.
>
> The project has had about 5,000 release downloads since November 2025 and
> ships regular releases (CHANGELOG.md).

## Build integration (after approval)

SignPath's GitHub action submits a GitHub Actions artifact, waits for the
approval, and downloads the signed result. Two requests per release:

1. **Binaries.** Split `build_windows_app.ps1` so it can stop after PyInstaller
   and the overlay build. Upload `MTGA Tracker.exe` and `tapps-overlay.exe`,
   sign, put the signed files back into `dist/`.
2. **Installer.** Build the portable zip and run ISCC from the signed files,
   then sign `MTGA-Tracker-<version>-setup.exe`.

Then the `manifest` job hashes the signed setup as it does today (the
signature changes the hash, so signing must come before `latest.json`).

To confirm on Windows before the first signed release:

- **Inno's unpacked `.tmp`** (the file Smart App Control blocked) must carry a
  valid signature after signing the setup from outside Inno. If it doesn't,
  sign through Inno's own `SignTool` directive with a command that sends each
  file to SignPath, so the embedded setup program is signed before it is
  packed.
- Signed files pass with Smart App Control on, on a clean Windows 11 install.
- The in-app update from the previous release still installs and relaunches.

## After signing works

- README: replace "moving to" with the final wording and drop the "unsigned"
  notes in Quick start and QUICKSTART.md for Windows.
- `docs/RELEASING.md`: approving the signing request becomes a release step,
  and release notes link the Code signing policy.
- `overlay_launcher.py`'s error 4551 message can stop suggesting a restart.
- Keep the updater's Smart App Control message: older unsigned versions stay
  in the wild.
