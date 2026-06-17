# MTGA Tracker Dashboard UI

React/Vite frontend for the local MTGA tracker dashboard. The Python tracker and SQLite analytics code remain in `src/mtga_tracker`; this app only consumes the local dashboard API.

## Commands

```bash
npm install
npm run dev
npm test
npm run lint
npm run build
```

During development, Vite proxies `/api` requests to `http://127.0.0.1:8765`. Start the Python dashboard server from the repo root when testing against real data:

```bash
venv/bin/python -m mtga_tracker.dashboard
```

## Production Serving

`npm run build` writes static assets to `ui/dist`. When that directory exists, `mtga_tracker.dashboard` serves the built app and exposes `/api/snapshot` from the local SQLite database.

Deck visuals are local-only. The API chooses representative card metadata from tracker tables and does not fetch remote card images.
