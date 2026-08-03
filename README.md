# MTGA Tracker

Track your Magic: The Gathering Arena games locally — a real-time tracker that
tails Arena's log, a SQLite analytics store, and a full dashboard UI. No
account, no cloud: everything stays on your machine.

## Features

- Real-time game tracking from Arena's log: casts, draws, lands, combat,
  life totals, stack resolution, and a full per-game timeline
- Menu-bar app (macOS) with live tracker log, dashboard launcher, and
  start/stop control
- Local analytics dashboard: win rate trends, ranked progress, per-deck
  drill-downs (card performance, mulligans, decklist versions, land
  statistics with flood/screw classification, win/loss streaks, Bo3
  sideboarding), game detail pages with draw-quality analysis and life
  charts, and per-card pages
- Opponent analysis: revealed-card tracking, deck color identification with
  community combo names (Dimir, Jeskai, …), and win rates vs each color combo
- Mulligan history including bottomed cards, session habits & fatigue splits,
  session logs, and a database health audit with self-repair
- Deck recognition from Arena's submitted decklists, split/room card
  unification, and startup data-hygiene migrations
- Compressed raw-payload archive that enables retroactive backfills as the
  tracker improves

## Releasing & alpha testing

See `docs/RELEASE_PLAN.md` for the macOS/Windows packaging plan, the
GitHub-Releases update flow, and the alpha readiness checklist.

## Installation

### Prerequisites

- Python 3.9 or higher
- MTGA installed (macOS or Windows)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd MTGA-Tapps
```

2. Create a virtual environment:
```bash
python -m venv venv

# macOS/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e '.[dev,gui]'
```

## Usage

On macOS, build and launch the native application for normal daily use:

```bash
scripts/build_macos_app.sh
open "dist/MTGA Tracker.app"
```

The native `.app` supplies the `MTGA Tracker` bundle and Dock identity plus the adaptive menu-bar icon. Direct source launches execute through the Python interpreter and may expose Python runtime metadata in macOS.

For source development or other platforms, run the tracker and dashboard together with:

```bash
pip install -e '.[gui]'
mtga-tracker-app
```

The application starts tracking, opens the Live Tracker Log window, serves the dashboard locally, and opens it in your default browser. Its menu includes **Open Dashboard**, **Show Live Tracker Log**, **Start/Stop Tracking**, **Open Data Folder**, and **Quit**. The live-log window shows the same running event output as the console tracker.

For a one-terminal launcher without the native menu bar:
```bash
mtga-tracker-app --no-gui
```

The original tracker-only console command remains available:
```bash
mtga-tracker
```

Audit the analytics database for suspicious rows:
```bash
python -m mtga_tracker.db_audit
python -m mtga_tracker.db_audit --repair
```

Audit recent draw quality from opening hands and known visible draws:
```bash
python -m mtga_tracker.draw_quality --card "Llanowar Elves" --land-rate 0.37
```

### Local dashboard UI

The tracker includes a separate frontend app in `ui/`. Build it once, then run the Python dashboard server:

```bash
cd ui && npm install && npm run build
cd ..
venv/bin/python -m mtga_tracker.dashboard
```

Open `http://127.0.0.1:8765`. During UI development, run the Python dashboard API and the Vite dev server separately:

```bash
venv/bin/python -m mtga_tracker.dashboard
cd ui && npm run dev
```

The dashboard reads only the local SQLite tracker database. The browser may request Scryfall art URLs for deck and card visuals when a card name is available; the tracker itself does not depend on network card resolution.

Dashboard routes and endpoints:

- `#/deck/<deck name>`: deck drill-down with card performance, opening hands, mulligans, formats, recent games, and filtered trends.
- `#/game/<game id>`: game detail with draw quality/flood detection, life chart, opening hand, drawn cards, played cards, and timeline filter.
- `#/card/<card name>`: card drill-down with by-deck performance and opening-hand impact.
- `GET /api/snapshot?deck=&format=&days=`: dashboard aggregates, matches, sessions, trend, and filter options.
- `GET /api/cards?q=&limit=`: partial-name search across cards used by either side in tracked games.
- `GET /api/deck?name=&format=&days=`, `GET /api/game?id=`, and `GET /api/card?name=`: detail payloads for the hash routes.

Stop the dashboard from the terminal where it is running:
```text
Ctrl+C
```

If port `8765` is already in use, choose another port:
```bash
python -m mtga_tracker.dashboard --port 8766
```

### macOS application and installer

Build the menu-bar `.app` bundle:

```bash
scripts/build_macos_app.sh
open "dist/MTGA Tracker.app"
```

Build a drag-to-Applications DMG:

```bash
scripts/build_macos_installer.sh
open dist/MTGA-Tracker.dmg
```

Release builds compile `ui/dist`, install the GUI/build dependencies, and package the Python tracker and dashboard together. Installed builds store the database and logs under `~/Library/Application Support/MTGA Tracker`. Do not run the source and packaged launchers simultaneously.

The installed app has an independent database and does not modify the repository database. Migrating existing history requires a deliberate cutover while both tracker versions are stopped: preserve the existing installed database, copy the repository database with SQLite's backup API, validate it, then launch the installed app. Never copy or replace the live database while either tracker owns it.

The generated application is currently unsigned. macOS distribution outside the development machine will require an Apple Developer ID signature and notarization.

If you lost the terminal running the dashboard on macOS, stop the process using the port:
```bash
lsof -ti tcp:8765 | xargs kill
```

Common SQL reports live in `data/_queries`, for example:
```bash
sqlite3 data/mtga_tracker.sqlite3 < data/_queries/WinRateByDeck.sql
```

## Project Structure

```
MTGA-Tapps/
├── src/
│   └── mtga_tracker/
│       ├── __init__.py
│       ├── main.py           # Entry point
│       ├── log_parser.py     # MTGA log file parser
│       ├── tracker.py        # Thin CardTracker composition class
│       ├── db_audit.py       # SQLite consistency audit/repair command
│       ├── dashboard.py      # Dependency-free local analytics dashboard
│       └── format_normalizer.py # Queue/format label normalization
├── tests/                    # Unit tests
├── data/                     # Data files and cache
├── logs/                     # Application logs
├── requirements.txt          # Python dependencies
└── README.md
```

## How It Works

MTGA writes detailed game logs to:
- **Windows**: `%APPDATA%\LocalLow\Wizards Of The Coast\MTGA\Player.log`
- **macOS**: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log`

This tracker monitors the log file in real-time and parses card play events.

### Local card database (optional)

The tracker loads card names from MTGA’s local SQLite file so it can resolve card IDs without the network. It looks for any file named **`Raw_CardDatabase_*.mtga`** (no hardcoded filenames) in these folders, in order:

- **macOS (Steam):** `~/Library/Application Support/Steam/steamapps/common/MTGA/MTGA_Data/Downloads/Raw`
- **macOS (Epic):** `~/Library/Application Support/com.wizards.mtga/Downloads/RAW`
- **Override:** set `MTGA_DATA_DIR` in `config.py` or the `MTGA_DATA_DIR` env var to the folder that contains the file

The Steam path is checked first (most up to date); the newest matching file is used.

### Desktop settings

The menu-bar app creates `settings.json` in its writable data folder. Use **Open Data Folder**
from the menu-bar menu to find it. The live tracker window size can be changed and takes effect
the next time the app starts:

```json
{
  "live_log_window": {
    "width": 1400,
    "height": 1020
  }
}
```

When running from source, the file is `data/settings.json`. Installed macOS builds use
`~/Library/Application Support/MTGA Tracker/settings.json`.

## Future UI Considerations

The project is designed to support a GUI in the future. Recommended options:
- **PyQt6/PySide6**: Native Python, cross-platform, professional look
- **Web-based**: FastAPI/Flask backend + modern web frontend

## Development

Install development dependencies:
```bash
pip install -e ".[dev]"
```

Run tests:
```bash
pytest
```

Format code:
```bash
black src/ tests/
```

## License

MIT
