# On-Screen Deck Overlay Plan (untapped.gg style)

Goal: a floating, always-on-top overlay next to Arena showing the cards left in
your deck, the % chance to draw each one, and the % chance to draw a land — with
a transparency slider, a collapsible body, and the land % visible even when
collapsed.

## Why PyQt6 (and why this costs zero new dependencies)

`menu_app.py` already uses PyQt6, and `UnifiedLauncher` (app.py) already runs
the tracker in a background thread inside that Qt process. The overlay is a new
window in the app we already ship — no new dependency, no new process, no IPC.

## 1. Window

A frameless PyQt6 widget:

- `Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool` — floats above
  Arena, no title bar, hidden from Dock/Cmd-Tab.
- `WA_ShowWithoutActivating` — never steals focus from the game.
- Draggable by its header (mousePress/mouseMove offset tracking); position
  persisted.

macOS caveat: a Qt window can float over Arena in windowed or
fullscreen-windowed mode, but not over true exclusive fullscreen (Arena gets
its own Space). untapped.gg has the same constraint; document it in the README.

## 2. Data flow

The tracker already knows everything needed: the submitted decklist
(grpIds + counts via the `game_deck_cards` machinery), every card that leaves
the library (the hardened zone-transfer handlers), library size, and game
start/end.

New module `overlay_state.py` (pure Python, no Qt):

- `OverlayState` dataclass: `cards: list[OverlayCard(name, copies_left,
  total_copies, type_category, mana_value)]`, `library_size`, `lands_left`,
  `game_active`, `mid_game_attach`.
- Rebuilt by the tracker whenever a zone transfer touches the player's library:
  a multiset subtraction of "left the library" from "submitted deck".
- Published to the UI thread via a Qt signal on the existing `AppSignals`
  pattern (`overlay_state_changed = pyqtSignal(object)`) — the same
  thread-safe bridge the app already uses for log streaming. No polling, no
  files, no sockets.

Math (honest and simple):

- Next-draw chance for card X = `copies_left / library_size`.
- Land chance = `lands_left / library_size`.
- Secondary hover detail: chance within N draws via hypergeometric
  `1 − C(lib−copies, N) / C(lib, N)` (reuse `draw_quality.hypergeom_*`).

## 3. Panel UI

Expanded: compact dark card list — name tinted by type (reuse the mulligan-chip
type colors), "2/4" copies, draw %. Sorted by mana value then name. Rows with 0
copies left are dimmed, not removed, so exhausted cards stay visible. Header:
deck name, library count, land % in bold.

Collapsed: the panel shrinks to a single slim pill — "Land 41% ▸" — same
widget with the list hidden, so position/opacity carry over. Collapse state
persisted.

## 4. Options

`settings.py` `AppSettings` gains `overlay: {enabled, opacity, collapsed, x, y}`.

- Transparency slider (0.3–1.0) in a small Options window reachable from the
  menu bar icon and from a right-click context menu on the overlay itself,
  wired to `setWindowOpacity()` with live preview.
- "Show deck overlay" toggle in the menu bar.

## 5. Lifecycle

- Appears when a deck is submitted (game start); updates per zone event; hides
  a few seconds after game end.
- Mid-game joins show the pill with "joined mid-game" instead of fake
  percentages — never display numbers the tracker can't stand behind.
- Bo3 sideboarding works for free: each game submits a fresh decklist.
- CLI mode (`python -m mtga_tracker.main`) has no Qt event loop; print a
  one-liner pointing at the menu bar app.

## 6. Build order

1. **Phase 1** — `overlay_state.py`: state dataclass + odds math as pure
   functions, fully unit-tested (no UI).
2. **Phase 2** — Qt panel rendering a static state; collapse/expand; dragging.
3. **Phase 3** — settings: opacity slider, persistence, menu toggle.
4. **Phase 4** — polish: dimmed exhausted rows, hover odds, light theme.

The Qt layer stays logic-free so the `test_menu_app.py`-style test exclusions
don't grow; everything decision-making lives in Phase 1 code under pytest.
