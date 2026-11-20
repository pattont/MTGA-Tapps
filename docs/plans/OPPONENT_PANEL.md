# Opponent panel (in-game overlay)

Status: built 2026-11-10 (steps 1 to 4 and 6; the rail's cells and defaults
below are as built), checked with tests and fixture screenshots only. Left:
step 5, the live check on macOS and Windows 11 during real games, including
the second window's memory and CPU (the "Cost" table is still unmeasured).

## Goal

Give the local player what the Stream Kit `opponent` widget gives a stream: what
the opponent has played this game and what deck that points to, in a second
overlay panel on the opposite side of the screen from the deck panel.

It must be easy to keep out of the way. Many players leave the deck panel folded
and look only on purpose, so the opponent panel gets the same three states (off,
folded to a rail, open) and the same hover, pin and return rules.

Rules it keeps:

- **Public information only.** Cards the opponent played, and later cards both
  players were shown. Never the opponent's hand or library. The deck name is a
  guess and is always worded as one.
- **No new work while it is off.** No window, no extra request, no extra query.
- **Never takes a click meant for Arena.** The same gutter rule as the deck panel.
- The tracker's live path is untouched: the tracker already writes everything
  this panel reads.

## What already exists

| Piece | Where | Note |
| --- | --- | --- |
| Opponent's played cards (name, type, cost, times played, 40 at most) | `live_status.opponent_seen`, written by `tracker_analytics._live_opponent_seen` | Already written on every update for the stream widget |
| Opponent colours, lands played, commanders | `live_status.opponent_colors`, `opponent_lands`, overlay state `opponent_commanders` | |
| Deck guess from your own history | `live_api._archetype_guess` | Needs past opponents labelled by Deck AI; one join over every labelled opponent's cards per call |
| Record against the guess, the colours, the commander | `_archetype_guess`, `_color_record`, `_commander_record` | Served on `/api/live` today |
| Grouping by type, lands folded to one line, new-card highlight | `ui/src/stream/liveView.ts` (`groupSeen`, `opponentDeck`), `OpponentWidget.tsx` | React; the overlay is Preact and imports nothing from `ui/` |
| Rail, panel, gutter, hover card, pin, return delay, click-through | `overlay/src/`, `overlay/src-tauri/src/lib.rs`, `dock.rs` | Built around one window, `main` |

None of this is on `/api/overlay`, and the shell has one window and one
`Runtime`. Those are the two real pieces of work.

## What the player sees

### Open: the opponent panel

The deck panel's width, look, Scale, background and density. Top to bottom:

1. **Header.** "Opponent" (or the name, as the deck panel shows it) with the
   head-to-head record, a pin, and a chevron to fold it.
2. **Deck line.** The best label available, in this order: commander(s) in
   Brawl; the history guess ("Likely Rakdos Midrange · 4 cards match"); the
   colour name ("Rakdos"); "Not revealed yet". Colour pips beside it.
3. **Record line.** Your wins and losses against that deck, colours or
   commander, when there are any.
4. **Cards played**, grouped by type with mana cost and ×count, ordered by mana
   value. A card new this poll is highlighted for four seconds. Lands fold to
   one line at the foot (the deck panel's Lands setting applies).
5. Hovering a row shows the card image in the gutter, on the board side.

No draw odds, no sort buttons, no sideboard, no session footer.

### Folded: the opponent rail

A rail as wide as the deck rail and shorter, with three cells in the deck
rail's label-over-value style:

| Cell | Shows | Why it earns a place |
| --- | --- | --- |
| Colours | The colour pips shown so far, stacked; an empty ring before the first card | The one fact worth a glance all game |
| Seen | Distinct nonland cards played | Tells you whether opening the panel will show anything new |
| Vs | Your record against the deck line's subject, "3–1"; a dash with no history | The matchup at a glance |

Then the open arrow. The rail's tooltip is the deck line in words. When the
opponent plays a card not seen before, the Seen cell pulses for four seconds:
a folded panel still tells you when there is something to look at.

Between games the opponent rail is hidden; it has nothing to show, and the
deck rail already marks the tracker as running. It returns when a game starts.

Candidates left out of the rail on purpose: the deck name (does not fit 44 px),
lands played (visible on the board), a commander thumbnail (a network image on
an always-on surface). Settle the cells from fixture screenshots before
building (step 1).

### Off

No window exists. This is the default in the first release that has it.

### Hover, pin, hotkey

The deck panel's rules, kept per panel: on and pinned comes back at game start;
on and unpinned unfolds when its rail is hovered and folds after the return
delay; a game ending folds it. A third hotkey toggles the opponent panel
(default `Alt+Shift+O`). The hide/show hotkey and the tracker menu's Show/Hide
act on both windows together.

### Where it sits

Opposite the deck panel: deck docked left puts the opponent on the right edge,
and the other way round. With the deck panel floating, the opponent docks to
the right edge. It keeps its own remembered vertical position. The right side
is where Arena draws the stack and its main button, so the default height needs
a look in a real game.

## Design

### Tracker: one more block on `/api/overlay`

`build_overlay_payload` adds `opponent`, null outside a game:

```
"opponent": {
  "colors": "BR",
  "lands": 4,
  "deck": {"label": "Rakdos Midrange", "source": "history", "matched_cards": 4},
  "record": {"wins": 3, "losses": 1},
  "seen": [{"name": "...", "type": "Creature", "mana_cost": "{1}{B}", "mana_value": 2, "count": 2}]
}
```

`deck.source` is `commander`, `history`, `colors` or `none`, so the page words
the label without guessing how it was made. The label order lives here, in one
place; the stream widget's `opponentDeck` can read the same field later.

- Read from the live row during a game and from the frozen last game on the
  results screen (`_frozen_game`), like the footer's rank and deck chips.
- The memo key in `overlay_response` gains `opponent_seen`, `opponent_colors`
  and `opponent_lands`. The body then changes when the opponent plays a card,
  which is when the state changes anyway.
- **The history guess must not scan history per card.** `_archetype_guess`
  joins every labelled opponent's card rows each call. `/api/live` only pays
  that while a Live Scoreboard or stream page is open; on `/api/overlay` every
  overlay user would pay it for every card an opponent plays. Build the
  archetype-to-cards map once, keyed on the labelled opponents (their count and
  newest row), and answer a guess from memory. Time it on a
  `scripts/build_scaled_db.py` copy before and after.
- A page from an older tracker has no `opponent` field: the opponent window
  shows nothing and its rail stays hidden.

No schema change, no new tracker write, no new endpoint.

### Shell: a second window

A second Tauri window, `opponent`, loading the same bundle with
`index.html?view=opponent`. It is created only while the setting is on and
destroyed when it is turned off.

Rejected: one transparent window across the whole screen. It would lie over the
entire board and depend on click-through being right every 100 ms; a bug there
blocks the game. Two small windows fail small.

`lib.rs` (1,128 lines) assumes `MAIN_WINDOW` and one `Runtime`. Split it first,
with no behaviour change:

- **Per window:** layout, content height, last placement and its time, drag in
  progress, cursor-on-overlay, click-through, rail-hover arming, what is flown
  out.
- **Shared:** hidden by the user, hidden for Arena, force-show, the monitor,
  the Arena probe's last answer.

The per-window state and its geometry, cursor watch and click-through move to
their own module; `dock.rs` gains the opposite-edge position and keeps its pure
tests. The cursor watch stays one 100 ms loop that checks both windows.

### Page

`main.tsx` picks the view from the query string. New: `OpponentPanel.tsx`,
`OpponentRail.tsx`, and `opponentModel.ts` (grouping and label wording, a copy
of the stream's `groupSeen` logic with its own tests). The stream `opponent`
widget and this panel become a mirrored pair, like the `overlay` widget and the
deck panel: a change to one is a change to both, and AGENTS.md says so when
this ships.

**One poller.** The deck page keeps the only `/api/overlay` poller and hands
each new body to the opponent page through a shell event; the opponent page
asks for the latest body when it mounts. Both windows then always show the same
moment, and the feature adds no HTTP requests.

### Settings

`overlay.json` gains `opponentPanel` (`off` / `on`, default `on`, decided 2026-11-15),
`opponentOpen`, `opponentPinned`, `positions.opponentY` and a third hotkey.
The struct already defaults absent fields, so no `SETTINGS_VERSION` bump.

Changed 2026-11-17: the on/off left the ⚙ flyout, which had grown long. The
dashboard's Settings → In-game overlay → Panels now picks **Both**, **My deck**
or **Opponent** (`settings.json` `overlay.panels`), and the tracker hands it to
the overlay as `--panels`. Opponent only is new: the deck window stays up empty
(it holds the poller and the flyout) and the opponent panel gets the ⚙ and the
Dock side. `overlay.json` gains `deckPanel` as the mirror. Not yet checked in a
running overlay. Scale, background,
density, name colour, return delay and click-through when pinned are shared.

## Cost

| | Expected | Check |
| --- | --- | --- |
| Feature off | Nothing: no window, no extra field work beyond a few bytes in the body | `footprint` and CPU equal to the 2026-11-08 baseline (overlay about 115 MB over four processes, 0.7 % CPU) |
| Feature on, memory | One more web-content process on macOS; WebView2's share on Windows unknown | To measure in step 3, both systems |
| Feature on, CPU | One more window in the 100 ms cursor watch; a re-render when the opponent plays a card | To measure over a real game |
| Tracker | No new writes; one memoised guess per new opponent card | Scaled-copy timing of `/api/overlay` |

If the second window costs more than is reasonable for an optional panel, stop
after step 2 and reconsider (the fallback is a tab inside the deck panel, which
needs no window but cannot show both at once).

## Steps

1. **Mock-ups.** Fixture payloads and `overlay/scripts/screenshots.mjs` shots of
   the opponent rail and panel (Standard with a guess, colours only, Brawl,
   nothing played yet). Settle the rail's cells and the default from them.
2. **Tracker payload.** The `opponent` block, the memo key, the in-memory
   archetype map. Tests in `tests/test_overlay.py` and `tests/test_live_api.py`:
   label order, null outside a game, frozen game on the results screen, a new
   card changes the ETag, the heartbeat does not. Scaled-copy timing.
3. **Shell split.** Per-window state, no behaviour change; `cargo test` and a
   manual pass of the deck panel on macOS and Windows 11. Then a bare second
   window to measure memory before any page work.
4. **Opponent window.** Rail, panel, hover card, pin, return delay, hotkey,
   settings group, hidden between games, forwarded payload. Vitest for the model
   and components; `cargo test` for opposite-edge geometry and click-through.
5. **Live check**, macOS and Windows 11, during real games: both dock sides and
   float, Arena fullscreen, a second monitor, Brawl, a Bo3, the feature off.
   Clicks through the gutter reach Arena in every state.
6. **Docs.** AGENTS.md (overlay section, the mirrored pair), `overlay/README.md`,
   the README's overlay section, `CHANGELOG.md`, this index.

## After the first version

- **Earlier this match.** In game 2 or 3 of a Bo3, a second list of what they
  showed in the earlier games (`game_card_summary` by `match_id`). Likely the
  most useful addition for Bo3 players.
- **Shown, not played.** Cards milled, discarded, exiled or revealed to both
  players (`GameState.revealed_card_events`), under their own heading.
- **A real deck match.** The history guess only exists for players who run
  Deck AI and have met the deck before; everyone else gets a colour name.
  [Opponent deck matching](opponent_deck_research.md) (seen cards against cached
  meta lists, with a stated confidence) is what would make the deck line good
  for every player, and would add "what they likely still have". This panel is
  where that result would show during a game. That plan currently targets the
  game page after the match; an in-game use needs its matcher to run from
  memory in a few milliseconds.

## Open questions

1. ~~Default off (planned) or on for players who already use the overlay?~~ On (2026-11-15):
   it shows whenever the overlay does, and ⚙ → Opponent panel turns it off.
2. The rail's three cells: Colours / Seen / Vs, or something else in place of Vs?
3. Hide the opponent rail between games (planned), or keep it up?
4. Arena's terms: this reads the same log as the rest of the tracker and shows
   only cards the opponent made public. Read Wizards' current third-party tool
   policy before release; it has not been checked for this plan.
