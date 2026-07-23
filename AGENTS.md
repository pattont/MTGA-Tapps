# AGENTS.md

Guidance for coding agents working on this MTGA tracker. Keep this file current when tracker behavior, database schema, or test commands change.

## Project Overview

This is a Python log-only tracker for Magic: The Gathering Arena. It tails MTGA `Player.log`, parses GRE game-state messages, prints a readable console log, and persists dashboard-friendly analytics to SQLite.

Primary code paths:

- `src/mtga_tracker/main.py`: CLI entry point.
- `src/mtga_tracker/log_parser.py`: JSON extraction and ordered game-state/client-message parsing.
- `src/mtga_tracker/tracker.py`: thin `CardTracker` composition/init class. Keep it small.
- `src/mtga_tracker/tracker_runtime.py`: startup banner, live polling loop, stop/cleanup.
- `src/mtga_tracker/tracker_lifecycle.py`: game start/end, match lifecycle, winner/outcome handling.
- `src/mtga_tracker/tracker_events.py`: core GRE event orchestration and annotation dispatch.
- `src/mtga_tracker/tracker_event_*.py`: focused event helpers for abilities, client actions, life, targets, and turns.
- `src/mtga_tracker/tracker_zone_transfers.py`: zone-transfer handling for draw/discard/mill/exile/destroy/return/play/cast.
- `src/mtga_tracker/tracker_stack.py`: stack lifecycle tracking and resolution/fizzle/counter display.
- `src/mtga_tracker/tracker_combat.py`: attack/block/combat damage handling.
- `src/mtga_tracker/tracker_opening_deck.py`: opening hand, mulligan, format, commander, deck metadata.
- `src/mtga_tracker/tracker_analytics.py`: SQLite persistence helpers.
- `src/mtga_tracker/format_normalizer.py`: single source of truth for raw queue/format labels and best-of inference.
- `src/mtga_tracker/db_audit.py`: SQLite consistency audit and safe repair CLI.
- `src/mtga_tracker/dashboard.py`: dependency-free local SQLite dashboard.
- `src/mtga_tracker/draw_quality.py`: CLI/report helpers for land flood/screw and repeated-card draw audits.
- `src/mtga_tracker/tracker_summary.py`: end-game and session summary rendering.
- `src/mtga_tracker/tracker_rendering.py`: console formatting, actor labels, mana/text cleanup, runtime strings.
- `src/mtga_tracker/tracker_state_lookup.py`: object snapshots, identity/copy-state, card type, zone/seat lookup helpers.
- `src/mtga_tracker/tracker_diagnostics.py`: unhandled annotation and parser diagnostics text logging.
- `src/mtga_tracker/card_database.py`: MTGA/Scryfall card ID to card name/type resolution.
- `tests/test_tracker_combat_winner.py`: broad regression coverage for tracker behavior.

## Commands

Use the repo virtualenv unless there is a clear reason not to.

```bash
venv/bin/python -m pytest -q
venv/bin/python -m pytest tests/test_tracker_combat_winner.py -q
venv/bin/python -m mtga_tracker.main
venv/bin/python -m mtga_tracker.db_audit
venv/bin/python -m mtga_tracker.db_audit --repair
venv/bin/python -m mtga_tracker.dashboard
venv/bin/python -m mtga_tracker.draw_quality --card "Llanowar Elves"
cd ui && npm install
cd ui && npm test
cd ui && npm run build
```

The full suite is fast; run it after tracker changes.

## Local Paths

Do not hardcode user-specific absolute paths in code or docs intended for general output. The app should display redacted home paths with `~`.

Common runtime files:

- Arena log: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log`
- Analytics DB: `data/mtga_tracker.sqlite3`
- Desktop settings: `data/settings.json` from source or the installed app data folder
- Unhandled annotation log: `data/mtga_tracker_unhandled_annotations.log`
- Local card DB source: MTGA `Raw_CardDatabase_*.mtga` under the MTGA install/download folders, or `MTGA_DATA_DIR`.

The unified launcher must pass its selected `--db` path to both `CardTracker` and the dashboard.
Never allow those components to silently use separate default databases.

## Tracker Invariants

Preserve these behaviors unless the user explicitly changes requirements:

- Never stop or restart the active tracker or desktop app without explicit user approval. The
  user may be in a live game even when the latest persisted log line appears idle.
- Perform database inspection read-only first. Use SQLite's online backup API before a live
  repair, and keep the tracker running unless the user explicitly authorizes downtime.
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
- Re-resolve the format for every game from the latest active match-room metadata. Never carry
  a scene/event hint across games or map missing format metadata to a guessed queue.
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
- `games`: one game result, duration, total turns, player/opponent turn counts, winner/outcome.
- `participants`: player/opponent seat, deck metadata, life, opening hand size, mulligans.
- `game_opening_hand_cards`: one row per card in the player's opening hand.
- `game_drawn_cards`: one row per visible player/opponent drawn card identity when Arena exposes it.
- `game_card_summary`: cards played by each participant.
- `game_participant_stats`: combat, damage/life, cards drawn/discarded/milled/exiled, stack stats.
- `game_turns`: observed turn start/end timestamps and duration by active seat; `timing_source`
  distinguishes exact `live` rows from `estimated_header_events` historical backfills.
- `game_events`: structured event history where available.
- `console_logs`: rendered console log lines for later dashboard/query work.
- `raw_game_payloads`: raw payload persistence when enabled/available.
- `rank_snapshots`: constructed rank changes by season, with optional ranked match/game linkage.

When adding stats, persist both player and opponent perspectives when the log can support it.

Use `format_normalizer.py` for queue labels and best-of inference. Do not duplicate string-matching format logic in tracker mixins or reports.

Run `mtga_tracker.db_audit` after suspected tracker inconsistencies. Safe repairs currently include format/queue mismatches, turn-count aggregate mismatches, reconstruction of completed games missing their core row, timestamp-based game-event reassignment, and deletion of empty unknown-result game artifacts; unresolved deck names and `Card #...` labels are reported for manual follow-up.

## Testing Expectations

Add or update regression tests for every parser/state-machine bug. Prefer focused tests that build minimal game-state payloads rather than replaying huge logs.

For dashboard UI changes, run both the Python tests and the frontend test/build commands. Keep the frontend app isolated under `ui/`; do not move tracker runtime behavior into the frontend.

High-risk areas needing tests:

- Winner/loss/concession detection.
- Opening hand and mulligan capture, especially stale seat correction.
- Draw/discard/mill/exile/life/damage stats for both sides.
- Stack ordering, countered/fizzled spells, and ability costs.
- Per-turn timing and final player/opponent time totals.
- State-based actions and zone transfers.
- Copy-state/transform handling.
- SQLite persistence for new summary fields.

## Coding Guidance

- Keep changes localized; `tracker.py` should remain a thin composition class. Put behavior in the focused `tracker_*` mixin that owns that responsibility.
- Avoid recreating a new monolith. If a tracker module grows well past ~800 lines, split it by responsibility before adding more behavior.
- Prefer robust inference from MTGA data over string matching console output.
- Preserve existing user-facing formatting unless the user requested a change.
- When adding a new event type, update summary stats and DB persistence if it affects analytics.
- If a log annotation is unknown, write a diagnostic to `data/mtga_tracker_unhandled_annotations.log` and avoid noisy UI output.
- Do not introduce network dependencies for normal card resolution when the local MTGA card DB can provide the data.
