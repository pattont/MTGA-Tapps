# Log Ingestion Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MTGA log ingestion more reliable by adopting the best Manasight parser patterns for entry buffering, JSON extraction, timestamps, parser health, client actions, and winner parsing.

**Architecture:** Add focused parser modules in front of the existing tracker state machine instead of rewriting tracker behavior. The new flow becomes raw file bytes -> complete log entries -> routed structured events -> existing tracker handlers. Gameplay analytics remain in `tracker.py` initially, but fragile parsing responsibilities move into small testable units.

**Tech Stack:** Python 3, pytest, SQLite, current `mtga_tracker` package, existing `tests/test_tracker_combat_winner.py` regression suite.

---

## Why This Is Better Than What We Have

Current tracker behavior is powerful but fragile because `tracker.py` receives reconstructed lines and repeatedly calls generic JSON extraction. This makes ordering, timestamps, multiline payloads, and diagnostics harder to reason about.

The proposed flow is better because:

- Complete-entry parsing prevents half-read or incorrectly combined Arena log messages from reaching gameplay logic.
- Depth-aware JSON extraction avoids regex errors when payloads contain nested objects, arrays, or stringified JSON.
- Log timestamps make replay/backfill/database ordering match Arena’s actual event time instead of tracker process time.
- Router health counters expose parser drift after Arena updates instead of burying it in terminal noise.
- Client action parsing turns `MulliganResp`, `SelectNResp`, and `SubmitDeckResp` into first-class events, improving opening-hand, modal-choice, stack, sideboard, and target-selection tracking.
- Winner parsing that prefers the latest game-scoped result reduces stale BO3 result bugs and wrong concede/loss attribution.

## Files

- Create: `src/mtga_tracker/log_entry.py`
- Create: `src/mtga_tracker/log_json.py`
- Create: `src/mtga_tracker/log_timestamp.py`
- Create: `src/mtga_tracker/event_router.py`
- Create: `src/mtga_tracker/client_actions.py`
- Modify: `src/mtga_tracker/log_parser.py`
- Modify: `src/mtga_tracker/tracker.py`
- Modify: `src/mtga_tracker/state.py`
- Test: `tests/test_log_entry.py`
- Test: `tests/test_log_json.py`
- Test: `tests/test_log_timestamp.py`
- Test: `tests/test_event_router.py`
- Test: `tests/test_client_actions.py`
- Test: `tests/test_tracker_combat_winner.py`
- Test: `tests/test_log_replay.py`

---

## Task 1: Complete Log Entry Buffer

**Purpose:** Stop treating every physical line as an independent event. MTGA logs contain headers followed by continuation JSON; the tracker should only parse complete entries.

**Files:**
- Create: `src/mtga_tracker/log_entry.py`
- Modify: `src/mtga_tracker/log_parser.py`
- Test: `tests/test_log_entry.py`
- Test: `tests/test_log_parser.py`

- [ ] Add `LogEntry` dataclass with `header`, `body`, and `first_line`.
- [ ] Add `LineBuffer.push_line(line: str) -> list[LogEntry]`.
- [ ] Recognize these boundaries: `[UnityCrossThreadLogger]`, `[Client GRE]`, `[ConnectionManager]`, `Matchmaking:`, and `DETAILED LOGS:`.
- [ ] Treat date-prefixed `[UnityCrossThreadLogger]` and `[Client GRE]` entries as multiline.
- [ ] Treat non-date `[UnityCrossThreadLogger]`, `[ConnectionManager]`, `Matchmaking:`, and `DETAILED LOGS:` entries as single-line.
- [ ] Add `LineBuffer.flush()`.
- [ ] Update `MTGALogParser.read_new_lines()` to continue yielding strings for backward compatibility, but internally buffer complete entries first.
- [ ] Add tests for multiline GRE, multiline `StartHook`, single-line state changes, and rotation/truncation flush.
- [ ] Run: `venv/bin/python -m pytest tests/test_log_entry.py tests/test_log_parser.py -q`.

**Better than current:** Our current parser reconstructs JSON blobs opportunistically. A formal entry buffer makes the parser deterministic and gives us a single place to fix future Arena log shape changes.

---

## Task 2: Depth-Aware JSON Extraction

**Purpose:** Replace regex JSON extraction with brace/bracket-depth extraction that respects quoted strings.

**Files:**
- Create: `src/mtga_tracker/log_json.py`
- Modify: `src/mtga_tracker/log_parser.py`
- Test: `tests/test_log_json.py`
- Test: `tests/test_log_parser.py`

- [ ] Add `extract_json_text(body: str) -> str | None`.
- [ ] Skip bracket log headers before searching for `{` or `[`.
- [ ] Track nesting depth for `{}` and `[]`.
- [ ] Track string/escape state so braces inside strings do not close the payload.
- [ ] Add `parse_json_from_body(body: str) -> dict | list | None`.
- [ ] Add `parse_nested_json_field(value: dict, field: str) -> dict | list | None` for stringified `payload` and `request`.
- [ ] Replace `MTGALogParser.parse_json_from_line()` internals with this helper while preserving the public method name.
- [ ] Add tests for nested objects, arrays, braces inside strings, header-prefixed JSON, no JSON, and malformed JSON.
- [ ] Run: `venv/bin/python -m pytest tests/test_log_json.py tests/test_log_parser.py -q`.

**Better than current:** Regex extraction can grab too much or too little. Depth-aware parsing gives us the exact JSON object Arena wrote, including nested payloads.

---

## Task 3: Log Timestamp Parsing and Event Time

**Purpose:** Attach Arena log timestamps to parsed entries/events so elapsed time, DB rows, and replay ordering can use source time instead of wall-clock processing time.

**Files:**
- Create: `src/mtga_tracker/log_timestamp.py`
- Modify: `src/mtga_tracker/log_entry.py`
- Modify: `src/mtga_tracker/log_parser.py`
- Modify: `src/mtga_tracker/tracker.py`
- Test: `tests/test_log_timestamp.py`
- Test: `tests/test_log_replay.py`

- [ ] Add `parse_log_timestamp(text: str) -> datetime | None`.
- [ ] Support US 12-hour, US 24-hour, ISO date, slash ISO date, European slash date, German dot date, ISO `T`, epoch milliseconds, and .NET ticks.
- [ ] Add `extract_entry_timestamp(body: str) -> datetime | None`.
- [ ] Store timestamp on `LogEntry`.
- [ ] Expose timestamp from `MTGALogParser` alongside entry text without breaking existing tracker calls.
- [ ] In `tracker.py`, use entry timestamp for event time when present; fall back to `datetime.now()` only when missing.
- [ ] Keep match elapsed display based on match start timestamp plus event timestamp.
- [ ] Add replay test proving event order and elapsed time are stable when replaying historical log lines quickly.
- [ ] Run: `venv/bin/python -m pytest tests/test_log_timestamp.py tests/test_log_replay.py -q`.

**Better than current:** If the tracker pauses, reconnects, or replays a log, `datetime.now()` lies. Arena timestamps preserve what actually happened.

---

## Task 4: Router and Parser Health Counters

**Purpose:** Add a small routing layer that classifies complete entries before tracker interpretation and records parser health.

**Files:**
- Create: `src/mtga_tracker/event_router.py`
- Modify: `src/mtga_tracker/log_parser.py`
- Modify: `src/mtga_tracker/tracker.py`
- Modify: `src/mtga_tracker/state.py`
- Test: `tests/test_event_router.py`
- Test: `tests/test_tracker_combat_winner.py`

- [ ] Add `RouterStats` with `routed_count`, `unknown_count`, `timestamp_failure_count`, and `malformed_json_count`.
- [ ] Add event categories: `gre`, `client_action`, `match_state`, `deck_collection`, `connection`, `metadata`, and `unknown`.
- [ ] Route complete entries in this order: metadata, GRE, client action, match state, deck collection, connection, unknown.
- [ ] Keep unknown entries out of the UI.
- [ ] Write unknown summaries to `data/mtga_tracker_unhandled_annotations.log` or a sibling parser diagnostics file.
- [ ] Add optional session summary line or debug command output for parser health counts.
- [ ] Add tests proving known entries are routed and unknown entries increment counters without crashing.
- [ ] Run: `venv/bin/python -m pytest tests/test_event_router.py tests/test_tracker_combat_winner.py -q`.

**Better than current:** We currently notice parser misses only when gameplay output looks wrong. Router stats give a measurable warning when Arena starts writing new shapes.

---

## Task 5: Client Action Normalization

**Purpose:** Parse client-to-GRE actions as first-class events so the tracker knows what the player chose, not only what later appeared in game state.

**Files:**
- Create: `src/mtga_tracker/client_actions.py`
- Modify: `src/mtga_tracker/log_parser.py`
- Modify: `src/mtga_tracker/tracker.py`
- Test: `tests/test_client_actions.py`
- Test: `tests/test_tracker_combat_winner.py`

- [ ] Add `parse_client_action(data: dict) -> dict | None`.
- [ ] Handle `ClientMessageType_MulliganResp` with normalized decision `keep` or `mulligan`.
- [ ] Handle `ClientMessageType_SelectNResp` with `selected_option_ids` and `selected_object_ids`.
- [ ] Handle `ClientMessageType_SubmitDeckResp` with `deck_cards` and `sideboard_cards`.
- [ ] Handle stringified `payload` values using `parse_nested_json_field`.
- [ ] Claim `ClientToGREUIMessage` as low-value noise so it does not inflate unknown counts.
- [ ] Feed normalized mulligan actions into existing opening-hand/mulligan state.
- [ ] Feed normalized selection actions into existing modal-choice logging.
- [ ] Feed submit-deck actions into BO3 sideboarding/decklist state.
- [ ] Add tests for object payload, stringified payload, keep, mulligan, selected objects, selected options, and submit deck.
- [ ] Run: `venv/bin/python -m pytest tests/test_client_actions.py tests/test_tracker_combat_winner.py -q`.

**Better than current:** The tracker currently infers too much after the fact. Client actions tell us user intent directly: keep/mulligan, selected mode, selected target/card, and submitted sideboarded deck.

---

## Task 6: Safer Winner Parsing

**Purpose:** Make result detection prefer the latest structured game result and avoid stale/ambiguous nested winner keys.

**Files:**
- Modify: `src/mtga_tracker/tracker.py`
- Test: `tests/test_tracker_combat_winner.py`

- [ ] Add helper `_extract_latest_game_result(data: dict) -> dict | None`.
- [ ] Search `gameInfo.results[]` in reverse and return the latest `scope == MatchScope_Game` with `ResultType_WinLoss`.
- [ ] Search `finalMatchResult.resultList[]` in reverse using the same rule.
- [ ] Treat `MatchScope_Match` as fallback only when no game-scoped result exists.
- [ ] Do not allow a generic nested `winningTeamId` to override a structured latest game-scoped result.
- [ ] Keep explicit local `ConcedeReq` handling as high-confidence local loss.
- [ ] Add BO3 tests where Game 1 winner differs from Game 2 and Game 3.
- [ ] Add concession tests for local concede and opponent concede.
- [ ] Add duplicate game-over/match-complete tests to ensure only one game result is recorded.
- [ ] Run: `venv/bin/python -m pytest tests/test_tracker_combat_winner.py -q`.

**Better than current:** Our current winner parsing can find an earlier nested `winningTeamId` before evaluating the result list. In BO3 and duplicate game-over payloads, that can read stale information. The latest game-scoped result is the right source of truth.

---

## Execution Order

1. Entry buffer.
2. JSON extraction.
3. Timestamp parsing.
4. Router stats.
5. Client actions.
6. Winner parsing.
7. Full verification: `venv/bin/python -m pytest -q`.

This order keeps every pass independently useful. Entry buffering and JSON extraction reduce parser risk first. Timestamp and router work then improve observability. Client actions and winner parsing consume the cleaner pipeline.

## Commit Strategy

- Commit after each task passes its focused tests.
- Do not combine parser infrastructure commits with gameplay behavior commits.
- Run the full suite before merging.

## Known Non-Goals

- Do not rewrite the tracker as a Rust parser.
- Do not change UI/dashboard work in this pass.
- Do not add draft-specific parser behavior.
- Do not change SQLite schema unless a task needs a timestamp/parser-health field; if needed, use nullable columns and migrations.
- Do not refactor all of `tracker.py`; only move parsing responsibility out where it directly supports these six tasks.

## Acceptance Criteria

- Full suite passes with `venv/bin/python -m pytest -q`.
- Existing console output remains stable except for improved ordering/timestamps where tests require it.
- Opening-hand, winner, deck-name, stack, modal-choice, and DB persistence tests still pass.
- Parser diagnostics clearly show unknown/malformed entries without UI noise.
- BO1 games are not accidentally promoted to BO3.
- BO3 result parsing uses the latest game result, not stale Game 1 data.
