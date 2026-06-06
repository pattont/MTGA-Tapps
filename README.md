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

Run the local dashboard:
```bash
python -m mtga_tracker.dashboard
```

The dashboard defaults to `http://127.0.0.1:8765` and reads `data/mtga_tracker.sqlite3`.

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
