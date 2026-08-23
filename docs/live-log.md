# Live Log in the Dashboard

Replace the Python live-log window with a first-class **Live Log** page in the
web UI — the screen a player keeps open on a second monitor while they play.
It shows who you're facing right now, a live scoreboard (life totals, and
commanders in Brawl), your session record in real time, and a running list of
finished games that link straight to their game pages. The Qt terminal-style
window goes away as a user-facing surface; its code stays buried as a debug
fallback.

This page will be the most-looked-at surface in the tracker. It gets real
design attention: no walls of monospace text, no cramped panels, motion where
it communicates (life changes, new events), and the same visual language as
the rest of the dashboard.

---

## 1. What exists today

- **Process shape.** The menu-bar app (`menu_app.py`) runs everything in ONE
  process: `UnifiedLauncher` (app.py) starts the dashboard HTTP server in a
  daemon thread and the tracker (`CardTracker`) in another. The tracker
  renders colored text lines (`tracker_rendering.py`) and emits them via a Qt
  signal into `LiveLogWindow`, which `start()` shows on launch.
- **State already tracked** (in `CardTracker` / `state.GameState`):
  - `game_state.player_life` / `opponent_life` (updated every life event),
    `last_turn_announced` + per-seat turn numbers, `player_seat_id` /
    `opponent_seat_id`, opponent screen name, match id / game number.
  - Brawl: `commanders_by_seat`, `player_commanders`, `opponent_commanders`
    (announced as they're revealed).
  - Session: `session_start_time`, `session_games_played`, `session_wins`,
    `session_losses`, first-player split counters
    (`_session_first_counts`), per-game session stats line already composed
    for the terminal.
  - Every rendered log line already flows through one choke point
    (`_print_line` / `_print_event` with a style name: `life_gain`,
    `life_loss`, `turn`, `combat`, …).

Because tracker and dashboard share a process, no IPC is needed — a shared
in-memory live-state object is enough.

## 2. Architecture

### 2.1 `live_feed.py` — the shared live state (new module)

A small thread-safe singleton the tracker writes to and the dashboard reads:

```python
class LiveFeed:
    seq: int                      # monotonically increasing event counter
    events: Deque[LiveEvent]      # ring buffer, last ~500 structured lines
    snapshot: LiveSnapshot        # current match/game/session state
```

- `LiveEvent`: `{seq, ts, turn, kind, text, style}` — `kind`/`style` reuse
  the terminal renderer's style names so the web feed gets the same color
  semantics (draw, play, combat, life_gain, life_loss, mulligan, result…).
- `LiveSnapshot` (JSON-ready):
  - `tracker`: running | stopped, session start time, log path health.
  - `match`: `in_match`, format label, `opponent_name`, best-of, game number
    within match, match record so far (Bo3), `game_id` once known.
  - `game`: turn number + whose turn, on-play/on-draw, `player_life`,
    `opponent_life`, mulligans, lands played, cards drawn/played counts —
    everything cheap that `GameState` already holds.
  - `brawl`: `player_commanders`, `opponent_commanders` (names; the UI
    resolves art via the existing Scryfall image pipeline used by
    DeckVisual, with the local-DB fallback).
  - `session`: games, wins, losses, win rate, runtime seconds, first-player
    split, and `games: [{game_id, started, deck, opponent, opp_colors,
    outcome, turns, duration}]` — appended as each game finishes.

Tracker integration is deliberately thin:

- `_print_line`/`_print_event` additionally push a `LiveEvent` (one-line
  change at the choke point; the styled text already exists).
- Lifecycle hooks that already update session counters / write games to
  SQLite also update `LiveSnapshot` (match start, game start, life change,
  turn change, commanders announced, game end with its DB `game_id`).

### 2.2 Dashboard endpoint

`GET /api/live?since=<seq>` → `{snapshot, events: [events with seq > since],
seq}`. Plain JSON polling at 1s while the page is visible (pause on
`document.hidden`); the payload after the first call is just the delta of
events plus the (small) snapshot. This stays stdlib-only, works with the
frozen builds, and avoids SSE/chunked-response fragility in
`http.server`. If polling ever feels laggy we can upgrade to SSE later
without changing the page.

When the dashboard runs standalone (`python -m mtga_tracker.dashboard`,
no tracker in-process), `/api/live` returns `{tracker: "not_running"}` and
the page shows a friendly "start the tracker app to go live" state with the
session list backfilled from SQLite (today's games).

## 3. The page — `#/live`, "Live Log"

Entry points: a prominent sidebar entry ("Live" with a pulsing dot while a
game is in progress), and the menu-bar item "Show Live Tracker Log" now
opens `dashboard/#/live` instead of the Qt window.

### 3.1 Layout

Two-column grid (stacks on narrow windows), matching existing section
styling (panels, borders, shadows, 16px gutters):

```
┌────────────────────────────────────────────┬──────────────────────┐
│  MATCH SCOREBOARD (hero panel)             │  SESSION (right rail)│
│  You ⚔ OpponentName · Standard Bo1 · T7    │  ┌─ stat tiles ─┐    │
│  ┌────────────┐        ┌────────────┐      │  │ 12 games     │    │
│  │ [commander]│  20 ♥  │ [commander]│ 14 ♥ │  │ 8-4 · 66.7%  │    │
│  │  card art  │        │  card art  │      │  │ 2h 14m       │    │
│  └────────────┘        └────────────┘      │  │ Play 58%     │    │
│  on the play · 0 mulligans · 3 lands       │  └──────────────┘    │
├────────────────────────────────────────────┤  TODAY'S GAMES       │
│  LIVE FEED (event stream)                  │  ✔ Boros Mouse vs UB │
│  T7 ▸ Opponent casts Sheoldred …           │  ✘ Boros Mouse vs G  │
│  T7 ▸ You draw · You play Mountain         │  ✔ … (links to game) │
│  T6 ▸ Combat: 2 attackers → 6 damage       │                      │
└────────────────────────────────────────────┴──────────────────────┘
```

### 3.2 Scoreboard (the centerpiece)

- **Life totals** are the hero: large numerals (tabular-nums), your side
  accent-colored, opponent neutral. On change, the number ticks with a
  ~250ms scale/fade micro-animation and a green/red flash matching the
  existing `life_gain`/`life_loss` palette. A slim life "bar" under each
  numeral (0–starting-life) gives glanceable state from across the room.
- **Identity row**: your name + deck (DeckVisual signature art as the
  avatar) vs opponent name + detected colors (ColorPips). Turn indicator
  chip ("Turn 7 — Opponent") with a subtle pulse while it's the opponent's
  turn.
- **Brawl mode**: the scoreboard swaps avatars for **commander cards** —
  real card art (Scryfall art-crop, cached like `/card` backdrops) for each
  player's commander(s), name beneath, and a cast-count badge ("cast ×2")
  once we track re-casts. Multiple commanders (partners) stack side by
  side. Until the opponent's commander is revealed, show an elegant
  card-back placeholder, not an empty box.
- **Between games**: the panel becomes a quiet "waiting for a match" state —
  session summary line, last result, soft animated dot — never a blank
  hole.

### 3.3 Live feed

- Structured event rows, newest at the bottom, auto-follow with a "jump to
  latest" pill when the user scrolls up (never yank scroll from them).
- Each row: turn chip (`T7`), icon + tinted left border by event kind
  (draw / play / combat / life / mulligan / result), body text from the
  renderer. Same color semantics as the old terminal legend, but rendered
  as chips and tints on the dashboard's design tokens — dark and light
  theme both.
- Turn boundaries get a small divider header ("Turn 7 — You"), mirroring
  the terminal's turn headers, so the feed scans like innings.
- New rows fade/slide in (120ms); with `prefers-reduced-motion`, no motion.
- Cap in DOM (~300 rows) with the ring buffer as source of truth.

### 3.4 Session rail

- **Stat tiles** (MetricCard style): Games, Record + win rate (WinRateBar),
  Runtime (ticking client-side between polls), Play/Draw split.
- **Running game list**: one row per finished game — outcome badge (✔/✘ in
  the existing badge style), deck, opponent + color pips, turns, duration,
  timestamp — the whole row links to `#/game/<id>`. Newest on top,
  today's/session's games only, "View all games →" link at the bottom.
- A new game slides in at the top with a brief highlight so a finished game
  is noticed even in peripheral vision.

## 4. Retiring the Python window

- `menu_app.start()` no longer shows `LiveLogWindow`; the tray item
  "Show Live Tracker Log" becomes "Live Log" and opens `#/live`.
- `LiveLogWindow` and its wiring stay in the codebase (debug fallback),
  reachable only via a hidden escape hatch: `MTGA_TRACKER_QT_LOG=1`
  environment variable (documented only in AGENTS.md). Startup errors that
  previously surfaced in the log window go to tray notifications + the
  dashboard's "tracker not running" state.
- The Qt window's settings (`live_log_width/height`) stay harmless in
  settings.json; no migration needed.

## 5. Implementation order

1. `live_feed.py` (state + ring buffer + tests) and tracker write-through
   at the existing choke points. Pure Python, easy to unit test with the
   replay harness.
2. `/api/live` endpoint (+ standalone-dashboard fallback) with tests.
3. UI: `#/live` route, scoreboard, feed, session rail; polling hook with
   visibility pause; theme-checked in dark and light.
4. Brawl commander art + placeholders.
5. Menu-bar swap (open `#/live`; hide Qt window behind the env var), docs
   (README/QUICKSTART screenshots), CHANGELOG.
6. Full verification: pytest + vitest + build, replayed-log screenshots of
   Standard Bo1, Bo3 mid-match, and a Brawl game, both themes.

## 6. Open questions (small, non-blocking)

- Session boundary: tracker process lifetime (current definition) vs
  "today" — proposal: keep tracker-session for the rail header, but the
  game list shows today's games so a restart doesn't wipe it.
- Life history sparkline on the scoreboard (tiny, last ~10 changes): nice
  polish, cheap once life events are in the feed — proposed for v1.1.
- Bo3 sideboard timer / "game 2 starting" interstitial: v1.1.
