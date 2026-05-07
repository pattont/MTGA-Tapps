# AGENTS.md

Guidance for coding agents working on this MTGA tracker. Keep this file current when tracker behavior, database schema, or test commands change.

## Project Overview

This is a Python log-only tracker for Magic: The Gathering Arena. It tails MTGA `Player.log`, parses GRE game-state messages, prints a readable console log, and persists dashboard-friendly analytics to SQLite.

Primary code paths:

- `src/mtga_tracker/main.py`: CLI entry point.
- `src/mtga_tracker/log_parser.py`: JSON extraction and ordered game-state/client-message parsing.
- `src/mtga_tracker/tracker.py`: main state machine, console logging, game summary, analytics persistence.
- `src/mtga_tracker/card_database.py`: MTGA/Scryfall card ID to card name/type resolution.
- `tests/test_tracker_combat_winner.py`: broad regression coverage for tracker behavior.

## Commands

Use the repo virtualenv unless there is a clear reason not to.

```bash
venv/bin/python -m pytest -q
venv/bin/python -m pytest tests/test_tracker_combat_winner.py -q
venv/bin/python -m mtga_tracker.main
```

The full suite is fast; run it after tracker changes.

## Local Paths

Do not hardcode user-specific absolute paths in code or docs intended for general output. The app should display redacted home paths with `~`.

Common runtime files:

- Arena log: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log`
- Analytics DB: `data/mtga_tracker.sqlite3`
- Unhandled annotation log: `data/mtga_tracker_unhandled_annotations.log`
- Local card DB source: MTGA `Raw_CardDatabase_*.mtga` under the MTGA install/download folders, or `MTGA_DATA_DIR`.

## Tracker Invariants

Preserve these behaviors unless the user explicitly changes requirements:

- Console output should be readable and consistent: no emoji/icons in turn log lines or summaries.
- Turn headers are the section boundary; individual log lines should use elapsed match time, not repeated turn labels.
- Stack output should distinguish spells/abilities put on the stack from `[resolved]`, `[countered]`, or inferred no-resolution states.
- Do not show normal single-item stack resolves if they add noise; show stack details when another item is added above an existing item or a spell/ability does not resolve normally.
- Opening hand should be captured whenever a full visible hand is available before gameplay begins, then persisted to `game_opening_hand_cards`.
- SQLite analytics should support future dashboards. Prefer structured tables over stuffing summary text into one blob.
- Unhandled annotations go to the text diagnostics log, not SQLite.

## MTGA Log Gotchas

Arena logs are not a simple chronological event stream. Be careful with inferred ordering and ownership.

- Local player seat can be stale or unknown early in a match. A complete visible hand identifies the local player; opponent hand is hidden.
- Seat IDs can change between games. Never assume the local player is seat 1.
- Winner detection must validate against the local player seat. Concession/disconnect messages are especially easy to invert.
- Costs can appear before/after the ability text in raw log order. For activated abilities, paid costs such as discard/tap should be associated with the activation.
- MTGA uses last-in-first-out stack resolution. A card can be cast/activated, then another spell/ability can be added above it and resolve first.
- State-based actions may appear as zone transfers with categories like zero toughness or zero loyalty. These should be user-visible when they explain a death/removal.
- Some effects are only visible through zone movement and object snapshots, not through clear English annotations.
- Copy/transform state may require tracking object state changes, not only card names. Example: `Likeness Looter` can become a copy of a graveyard creature.

## Analytics DB

Keep schema changes backward-compatible. Use nullable columns and migration helpers when possible.

Important tables:

- `tracker_sessions`: one tracker runtime session.
- `matches`: match grouping within a session.
- `games`: one game result, duration, total turns, winner/outcome.
- `participants`: player/opponent seat, deck metadata, life, opening hand size, mulligans.
- `game_opening_hand_cards`: one row per card in the player's opening hand.
- `game_card_summary`: cards played by each participant.
- `game_participant_stats`: combat, damage/life, cards drawn/discarded/milled/exiled, stack stats.
- `game_events`: structured event history where available.
- `console_logs`: rendered console log lines for later dashboard/query work.
- `raw_game_payloads`: raw payload persistence when enabled/available.

When adding stats, persist both player and opponent perspectives when the log can support it.

## Testing Expectations

Add or update regression tests for every parser/state-machine bug. Prefer focused tests that build minimal game-state payloads rather than replaying huge logs.

High-risk areas needing tests:

- Winner/loss/concession detection.
- Opening hand and mulligan capture, especially stale seat correction.
- Draw/discard/mill/exile/life/damage stats for both sides.
- Stack ordering, countered/fizzled spells, and ability costs.
- State-based actions and zone transfers.
- Copy-state/transform handling.
- SQLite persistence for new summary fields.

## Coding Guidance

- Keep changes localized; `tracker.py` is large, so avoid broad refactors unless needed.
- Prefer robust inference from MTGA data over string matching console output.
- Preserve existing user-facing formatting unless the user requested a change.
- When adding a new event type, update summary stats and DB persistence if it affects analytics.
- If a log annotation is unknown, write a diagnostic to `data/mtga_tracker_unhandled_annotations.log` and avoid noisy UI output.
- Do not introduce network dependencies for normal card resolution when the local MTGA card DB can provide the data.

