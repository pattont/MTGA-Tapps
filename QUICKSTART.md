# Quick Start Guide

Get started with MTGA Tracker in 5 minutes!

## Prerequisites

- Python 3.9 or higher installed
- MTGA installed and has been run at least once
- Basic command line knowledge

## Installation

### 1. Set up virtual environment

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install the package (development mode)

```bash
pip install -e .
```

## Running the Tracker

### Method 1: Using the installed command

```bash
mtga-tracker
```

### Method 2: Using Python module

```bash
python -m mtga_tracker.main
```

### Method 3: Direct execution

```bash
python src/mtga_tracker/main.py
```

## Running the Dashboard

Start the local analytics dashboard:

```bash
python -m mtga_tracker.dashboard
```

Open `http://127.0.0.1:8765/` in your browser.

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

## What to Expect

When you run the tracker, you'll see:

```
======================================================================
MTGA Card Tracker
======================================================================
Monitoring log file: /path/to/Player.log
Starting from current position (new events only)...
Press Ctrl+C to stop
======================================================================

```

Then as you play MTGA, you'll see card events logged to the console:

```
[14:23:45] Player played card ID: 74567
[14:24:12] Opponent played card ID: 68234
[14:24:30] Player played card ID: 72341
```

## Tips

1. **Start the tracker before starting a match** for best results
2. **Press Ctrl+C** to stop the tracker and see a summary
3. The tracker only monitors new events, not historical data
4. Card IDs will be shown until we implement the card database (coming soon!)

## Troubleshooting

### "Log file not found" error

Make sure:
- MTGA is installed
- You've run MTGA at least once
- You're running on macOS or Windows (Linux not supported yet)

You can specify a custom log path:
```bash
mtga-tracker --log-path /path/to/Player.log
```

### Nothing is showing up

- Make sure you start the tracker BEFORE playing cards in MTGA
- The tracker only shows NEW events from when it starts
- Try playing a card in MTGA to test

### Permission errors

Make sure the tracker has permission to read the MTGA log file.

## Next Steps

- Check out `docs/FUTURE_DEVELOPMENT.md` for upcoming features
- Read `docs/MTGA_LOG_FORMAT.md` to understand the log format
- Contribute! See issues or create your own

## Getting Help

- Check the main README.md
- Review the documentation in `docs/`
- Open an issue on GitHub
