# Quick Start Guide

Get MTGA Tracker running in a few minutes.

## Prerequisites

- MTGA installed and run at least once (the tracker reads Arena's `Player.log`)
- macOS or Windows

## Option 1 — Install the app (recommended)

**From a GitHub Release**: download the installer for your OS from the Releases
page, install, and launch **MTGA Tracker**.

On Windows that's `MTGA-Tracker-<version>-setup.exe` — a normal installer with a Start
Menu entry, an entry in Apps & Features, and in-place upgrades. It installs per-user by
default (no admin prompt); pick "Install for all users" during setup if you want it in
Program Files. Prefer a no-install portable copy? Grab the `-windows.zip` instead and
run `MTGA Tracker.exe` from anywhere.

On macOS it's a DMG — drag **MTGA Tracker** to Applications and you're done. The
**Deck Finder** companion tool is bundled inside the app on both platforms (launch it
from the menu bar or the dashboard sidebar); there is nothing separate to install.

**Build it yourself on macOS:**

```bash
scripts/build_macos_app.sh          # builds dist/MTGA Tracker.app
open "dist/MTGA Tracker.app"
# or a drag-to-Applications DMG:
scripts/build_macos_installer.sh
```

The app lives in the menu bar: it starts tracking, opens the Live Tracker Log window,
serves the dashboard locally, and opens it in your browser. Menu items: **Open
Dashboard**, **Deck Finder**, **Show Live Tracker Log**, **Open Data Folder**,
**Settings…** (AI deck identification), **Start/Stop Tracking**, **Quit**. Installed builds keep their database under
`~/Library/Application Support/MTGA Tracker` (macOS) or
`%LOCALAPPDATA%\MTGA Tracker` (Windows).

Unsigned alpha builds: macOS Gatekeeper will balk the first time. On **macOS 15
(Sequoia) and newer** the dialog only offers "Move to Trash" or "Done" — do this instead:

1. Click **Done** (NOT "Move to Trash").
2. Open **System Settings → Privacy & Security**, scroll down to the Security section —
   you'll see *"MTGA Tracker.app was blocked to protect your Mac"*.
3. Click **Open Anyway** and confirm. This entry only appears for a while after an
   open attempt, so do step 2 right after step 1.

On older macOS, right-click the app → **Open** → **Open** still works. If the
Open Anyway entry never appears, the Terminal fallback always works:

```bash
xattr -cr "/Applications/MTGA Tracker.app"
```

The first Deck Finder launch from a downloaded build may prompt separately (it's its
own executable inside the app) — same Open Anyway dance if so. On Windows, use
SmartScreen's **More info → Run anyway** on the setup.exe or zip.

## Option 2 — Run from source (development)

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -e '.[dev,gui]'

mtga-tracker-app                    # menu-bar app + tracker + dashboard together
mtga-tracker-app --no-gui           # same, one terminal, no menu bar
mtga-tracker                        # console tracker only
```

Dashboard only (needs the frontend built once):

```bash
cd ui && npm install && npm run build && cd ..
venv/bin/python -m mtga_tracker.dashboard      # http://127.0.0.1:8765
```

## What to expect

Start the tracker, then play Arena. The console / Live Tracker Log shows real card
names as the game unfolds — casts, draws, lands, combat, stack resolution, life
totals — and each finished game is saved to the local SQLite database. The dashboard
(auto-refreshing) has the overview, per-deck pages, per-game detail with timeline and
draw-quality analysis, and per-card pages. Everything is local; no account, no cloud.

Tips:

- Start the tracker before queueing. If it joins mid-game, that game is shown live
  but intentionally not saved.
- The tracker's terminal shows its version and database path at startup.
- Stop the console tracker with Ctrl+C to get a session summary.

## Troubleshooting

**"Log file not found"** — make sure Arena has been run at least once, or point at the
log directly:

```bash
mtga-tracker --log-path /path/to/Player.log
```

**Port 8765 already in use** —

```bash
python -m mtga_tracker.dashboard --port 8766
# find a lost dashboard process on macOS:
lsof -ti tcp:8765 | xargs kill
```

**Nothing showing up** — the tracker only reads new log events from when it starts;
play a card in Arena to test.

More: `README.md` for the full feature tour, `docs/TROUBLESHOOTING.md` for seat/log
issues, `docs/MTGA_LOG_FORMAT.md` for how Arena's log works.
