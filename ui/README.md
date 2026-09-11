# Tapps Tracker Dashboard UI

React/Vite frontend for the local MTGA tracker dashboard. The Python tracker and SQLite analytics code remain in `src/mtga_tracker`; this app only consumes the local dashboard API.

## Commands

```bash
npm ci
npm run dev
npm test
npx tsc -b
npm run lint
npm run build
```

During development, Vite proxies `/api` requests to `http://127.0.0.1:8765`. Start the Python dashboard server from the repo root when testing against real data:

```bash
venv/bin/python -m mtga_tracker.dashboard
```

## Production Serving

`npm run build` writes static assets to `ui/dist`. When that directory exists, `mtga_tracker.dashboard` serves the built app and exposes `/api/snapshot` from the local SQLite database.

The API chooses representative card metadata from local tracker tables. The browser
fetches card art from Scryfall and uses its batched API for missing mana costs,
seeding its cache from the local `card_mana` payload first. Mana symbols are bundled
for offline rendering. The browser also checks GitHub Releases for updates; see
the root README's Data & privacy section for the full network behavior.

Settings, annotations, Deck Finder jobs, collection export, and database reset
have explicit POST actions; analytics reads use GET endpoints. Rebuild `ui/dist`
after frontend changes because the Python server serves these generated assets.
