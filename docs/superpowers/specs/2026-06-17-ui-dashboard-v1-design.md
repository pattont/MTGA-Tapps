# MTGA Tracker UI Dashboard V1 Design

## Goal

Build a separate frontend app for the MTGA tracker dashboard that looks and feels closer to Magic: The Gathering Arena while keeping the Python tracker focused on log parsing and SQLite analytics persistence.

V1 should replace the current basic local dashboard experience with a polished, dense, sortable dashboard. It should stay local-only and should not introduce network image dependencies.

## Scope

V1 includes:

- A new frontend app under `ui/`.
- A local dashboard data API that reads the existing SQLite analytics database.
- Overview metrics for games, wins, losses, win rate, best deck, and play/draw splits.
- Dashboard sections for decks, formats, play/draw, deck play/draw, draw quality, visible drawn cards, momentum, and recent games.
- Sortable behavior for every list/table column.
- Light and dark mode with a persisted preference.
- MTGA-inspired visual elements: mana color accents, format/outcome badges, compact deck tiles, and card-like deck image placeholders.
- Local-only deck imagery behavior for V1.

Out of scope for V1:

- Network card art from Scryfall or any other external service.
- Extracting or converting MTGA Unity asset bundles into browser-ready images.
- Editing tracker gameplay behavior or analytics schema except where a read-only dashboard API needs query support.
- Authentication, multi-user support, or hosted deployment.

## Architecture

Add a `ui/` directory containing a Vite, React, and TypeScript app. The app is separate from the Python tracker package and can be built, tested, and iterated independently.

Keep the Python tracker modules responsible for collecting and persisting data. Add a small local dashboard API surface, either by extending the existing dashboard server or by adding a focused API module near `src/mtga_tracker/dashboard.py`. The API reads the same SQLite database and returns structured JSON for the frontend.

The existing dependency-free HTML dashboard can remain as a fallback during V1 unless it becomes simpler to route `/` to the built frontend and expose the old renderer only in tests.

## Data Flow

1. The Python tracker writes analytics to `data/mtga_tracker.sqlite3`.
2. The local dashboard API reads aggregate data from SQLite using the existing snapshot queries where practical.
3. The frontend fetches dashboard JSON from the local API.
4. Client-side table components handle sorting without mutating source data.
5. Theme preference is stored in `localStorage`.

## Deck Imagery

V1 must remain local-only.

For each deck, choose a representative local card from existing analytics data. Prefer cards from `game_card_summary` with the highest played count for that deck, then opening-hand or drawn-card records when needed. Use local MTGA metadata such as card name, type category, color identity, and `ArtId` when available.

Because MTGA card art files in the local install are Unity `.mtga` asset bundles rather than browser-ready images, V1 renders a card-like local placeholder instead of attempting bundle extraction. The placeholder should use available local metadata and mana-color styling so deck rows still feel visually tied to the deck.

## UI Design

The first screen should be the usable dashboard, not a landing page.

Use a compact app shell:

- Left sidebar for Overview, Decks, Formats, Draw Quality, and Recent Games.
- Top area with the MTGA Tracker title, current data status, and theme toggle.
- Overview metric strip for high-level performance.
- Dense, readable tables and deck rows suitable for repeated use.

The visual language should reference Arena without copying it literally:

- Dark theme based on deep neutral surfaces with warm gold accents.
- Light theme based on parchment-like neutral surfaces with clear contrast.
- Mana color accents from the existing local icon colors or CSS tokens.
- Outcome colors for win/loss/draw that remain accessible in both themes.
- Cards use border radius of 8px or less.

Avoid decorative clutter. This is an analytics tool, so scanability and sortable tabular data are more important than large hero panels.

## Components

Frontend components:

- `AppShell`: layout, navigation, and theme provider.
- `MetricCard`: compact summary statistics.
- `SortableTable`: reusable table with per-column sorting.
- `DeckPerformance`: deck table with representative card/deck visual.
- `DashboardSection`: consistent section headers and spacing.
- `Badge`: format, outcome, and split badges.
- `ManaAccent`: local mana-color chips or accents.

Backend/API helpers:

- Snapshot/query function that returns the existing aggregate sections as JSON.
- Optional static-file serving for the frontend build.
- Error response for missing or unreadable SQLite DB.

## Error Handling

If the API cannot read the database, the frontend should show a clear empty/error state and keep the shell usable.

If a section has no rows, show a compact empty state in that section rather than hiding the section.

If deck imagery metadata is unavailable, render a neutral card placeholder with the deck name and no broken image.

## Testing

Python tests:

- Verify the dashboard API returns the expected snapshot shape.
- Verify deck representative metadata is local-only and tolerates missing MTGA card metadata.

Frontend tests:

- Verify sortable tables sort strings, numbers, percentages, dates, and blank values.
- Verify theme preference is read from and written to `localStorage`.
- Verify dashboard sections render empty states and populated rows.

Verification commands:

```bash
venv/bin/python -m pytest -q
cd ui && npm test
cd ui && npm run build
```

If the frontend toolchain uses different command names after scaffolding, document the final commands in `AGENTS.md` and `README.md`.
