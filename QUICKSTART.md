# Quick Start Guide

Get Tapps Tracker running in a few minutes.

> 💬 Questions, bugs, or feature requests? Join the community on
> **[Discord](https://discord.gg/ExfW3HaZgb)**.

## Prerequisites

- MTGA installed and run at least once (the tracker reads Arena's `Player.log`)
- macOS or Windows
- **Detailed Logs (Plugin Support)** enabled: Arena gear icon → Adjust
  Options → Account → check Detailed Logs, then restart Arena before
  starting a tracking session.

## Option 1 — Install the app (recommended)

**From a GitHub Release**: download the installer for your OS from the Releases
page, install, and launch **MTGA Tracker**.

On Windows that's `MTGA-Tracker-<version>-setup.exe` — a normal installer with a Start
Menu entry, an entry in Apps & Features, and in-place upgrades. It installs per-user by
default (no admin prompt); pick "Install for all users" during setup if you want it in
Program Files. Prefer a no-install portable copy? Grab the `-windows.zip` instead and
run `MTGA Tracker.exe` from anywhere.

On macOS it's a DMG — drag **MTGA Tracker** to Applications and you're done. The
**Deck Finder** is built into the dashboard on both platforms (open it from the
menu bar or the sidebar button); there is nothing separate to install.

**Build it yourself on macOS:**

```bash
scripts/build_macos_app.sh          # builds dist/MTGA Tracker.app
open "dist/MTGA Tracker.app"
# or a drag-to-Applications DMG:
scripts/build_macos_installer.sh
```

The app lives in the menu bar: it starts tracking, serves the dashboard locally,
and opens it in your browser. The tracker's status line at the top of the menu
shows a green dot while it's running and red when it's stopped. The menu
has **Live Scoreboard**, **Dashboard**, **Deck Finder**, **Open Data Folder**,
**Start/Stop Overlay**, **Overlay Settings**, **Start/Stop Tracking**,
**Tracker Settings**, and **Quit Tapps Tracker**. The overlay starts enabled
when included in the build. Installed builds keep their database under
`~/Library/Application Support/MTGA Tracker` (macOS) or
`%LOCALAPPDATA%\MTGA Tracker` (Windows).

The macOS build is ad-hoc signed and not notarized by default. If Gatekeeper
blocks a downloaded release you trust, dismiss the dialog, open **System
Settings → Privacy & Security**, and use **Open Anyway** for that app.
See [Apple's instructions](https://support.apple.com/en-ie/102445).

Windows builds are unsigned. For a trusted release, SmartScreen's **More
info → Run anyway** may be available. An antivirus quarantine is a separate
issue: record the version, download source and exact detection from Windows
Security's **Protection history** and report it to the maintainer. A label
such as `Trojan:Win32/Wacatac` alone does not establish that the file is a
false positive, and there is no guaranteed clearance time. See
[Microsoft's Protection History guidance](https://support.microsoft.com/en-us/windows/security/windows-security/protection-history-in-the-windows-security-app).

## Option 2 — Run from source (development)

Install Python and Node/npm first. From the repository root on macOS:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e '.[dev,gui]'
(cd ui && npm ci && npm run build)
mtga-tracker-app
```

In Windows PowerShell:

```powershell
py -m venv venv
venv\Scripts\python -m pip install -e '.[dev,gui]'
Push-Location ui
npm ci
npm run build
Pop-Location
venv\Scripts\python -m mtga_tracker.app
```

The source dashboard requires that frontend build for both the unified app
and dashboard-only mode. For the native overlay, also install Rust and run
`scripts/build_overlay.sh` (macOS) or `scripts\build_overlay.ps1` (Windows).
Without its binary, the source tracker runs with the overlay unavailable.

Once the environment is installed (use `venv\Scripts\python` on Windows):

```bash
venv/bin/python -m mtga_tracker.app --no-gui  # tracker + dashboard, no menu bar or automatic overlay launch
venv/bin/python -m mtga_tracker.main          # console tracker only
venv/bin/python -m mtga_tracker.dashboard     # dashboard only, port 8765
```

These are alternative modes; run only one tracker against a database.

## What to expect

Start the tracker, then play Arena. Open the **Live Scoreboard** — both life
totals with color pips, your record with this deck and against this opponent,
the turn and game clock, your session record, today's games, and a play-by-play
feed (casts, draws, lands, combat, stack resolution, life totals) that reads
just like the per-game timeline. Each eligible finished game is saved to the local
SQLite database. The rest of the dashboard (auto-refreshing) has the overview,
per-deck pages, per-game detail with timeline and draw-quality analysis,
per-card pages, and the opponents you've faced. Everything is local; no
account, no cloud.

Tips:

- Start the tracker before queueing. If it joins mid-game, that game is shown live
  but intentionally not saved. Practice and novelty/event modes listed in the
  README are also excluded from saved statistics.
- The tracker's terminal shows its version and database path at startup.
- Stop the console tracker with Ctrl+C to get a session summary.

## Troubleshooting

**"Log file not found"** — make sure Arena has been run at least once, or point at the
log directly:

```bash
mtga-tracker --log-path /path/to/Player.log
```

**Port 8765 already in use** —

An existing tracker may already be serving the dashboard. Open it from the
tray/menu, or use `--port 8766` for a separate dashboard. If an old instance
needs to quit, use its menu when tracking can safely stop.

**Nothing showing up** — check Detailed Logs first and look at the monitored
log and card database paths in **Tracker Settings**. Start tracking before
queueing, then play a game. For unresolved card names, see
[card database discovery](docs/MTGA_INSTALL_DISCOVERY.md).

More: `README.md` for the full feature tour, `docs/MTGA_LOG_FORMAT.md` for how
Arena's log works, and the Discord for anything else.
