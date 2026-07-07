# MTGA Tracker

Track cards played in Magic: The Gathering Arena for analysis and learning.

## Features (MVP)

- Real-time tracking of cards played by you
- Real-time tracking of cards played by opponents
- Console output of card events as they happen

## Planned Features

- GUI interface for better visualization
- Match statistics and analytics
- Deck recognition and tracking
- Win/loss statistics per deck
- Card play frequency analysis

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
pip install -r requirements.txt
```

## Usage

Run the tracker:
```bash
python -m mtga_tracker.main
```

The tracker will monitor your MTGA log file and output card events to the console.

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
- `#/game/<game id>`: game detail with life chart, opening hand, drawn cards, played cards, and timeline filter.
- `#/card/<card name>`: card drill-down with by-deck performance and opening-hand impact.
- `GET /api/snapshot?deck=&format=&days=`: dashboard aggregates, matches, sessions, trend, and filter options.
- `GET /api/deck?name=&format=&days=`, `GET /api/game?id=`, and `GET /api/card?name=`: detail payloads for the hash routes.

Stop the dashboard from the terminal where it is running:
```text
Ctrl+C
```

If port `8765` is already in use, choose another port:
```bash
python -m mtga_tracker.dashboard --port 8766
```

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
