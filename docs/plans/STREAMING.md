# Streaming

Status: phase 1 (Stream Kit) built 2026-10-31 and checked with sample data; it still
needs a live check in OBS during real games (see below). Later phases are planned,
not built.

## Goal

Make Tapps Tracker the tracker MTGA streamers recommend: useful on stream for
viewers, easy to set up, and visible enough that viewers find it. Keep the
product's rules: local, no account, no cloud service, nothing that blocks live
tracking.

## What exists elsewhere

Untapped.gg's Twitch extension (researched 2026-10-31) gives viewers a deck
tracker with remaining cards, deck export, hover tooltips on cards on the
battlefield and in hand, a zone browser (libraries, graveyards, exile) and a
`!deck` chat bot. Setup needs an Untapped account, their companion app, an
extension key pasted into Twitch, and a chat-bot role.

Two constraints make full parity expensive for us:

- **Board hover needs screen positions.** Viewers hovering a card on the video
  means knowing where Arena draws each card. Arena's log has no screen
  positions; we would have to rebuild Arena's layout for every resolution and
  window size. Not planned.
- **Any Twitch extension needs a server.** Twitch accepts live extension
  messages (Send Extension PubSub Message) only when signed with the
  extension's shared secret, which can't ship in a desktop app. That means a
  relay (EBS) we run, Twitch review for every extension version, 5 KB messages
  and rate limits. It would be the product's first server and first account
  link.

## Phases

### 1. Stream Kit: OBS browser-source widgets (built)

A second page of the dashboard build, `stream.html`, served by the tracker's
own dashboard server at `http://127.0.0.1:8765/stream.html?widget=<name>`.
It has no app shell and a transparent background, so streamers add each
widget as an OBS or Streamlabs Browser source. Each widget reads the
endpoints the dashboard already serves; there is no new tracker work.

| Widget | Shows | Source |
| --- | --- | --- |
| `overlay` | The in-game overlay's panel: deck, format, opponent and head-to-head, turn, land-drop odds (next, in 2, in 3), play/draw, library, every card with copies left and next-draw odds, the Lands and Sideboard rows, and the sideboard itself | `GET /api/overlay` (ETag) |
| `deck` | Deck name, library size, land odds, every card with copies left and next-draw odds | `GET /api/overlay` (ETag) |
| `record` | Session record and win rate, rank, today's record with the current deck | `GET /api/live?events=0` |
| `games` | Today's games, newest first, as on Live Scoreboard (result, Play/Draw, deck, opponent, turns, length; no replay links or clock time), 1–25 of them (`count`, default 10), under the session record (`record=0` hides it) | `GET /api/live?events=0` (its `games`, up to 40) |
| `matchup` | Opponent, revealed colors, archetype guess, head-to-head, play/draw, game number, turn | `GET /api/live?events=0` |
| `spotlight` | A large image of the latest card cast, for a few seconds | `GET /api/live?since=` |

Rules:
- Options live in the URL (`scale`, `bg=solid|glass|none`, `brand=0`,
  per-widget `sort`, `lands`, `who`, `seconds`, `opponent=0`, `idle=show`,
  and the full overlay's `opacity=0..100`, `sideboard=right|left|below|off`,
  `names=type|white`, and recent games' `count=1..25` and `record=0`),
  so OBS keeps them and the tracker stores nothing. Settings → Streaming builds
  the URLs, copies them, and remembers the choices in browser localStorage.
- `demo=1` shows sample data so streamers can place and size sources without a
  game running; `preview=1` paints a checkerboard behind the widget in a
  normal browser tab.
- The full overlay copies the in-game panel's rules and pixel sizes
  (`stream/overlayView.ts` mirrors `overlay/src/model.ts`; keep them in step)
  and is enlarged with CSS `zoom`. Its background is the overlay's own slider
  curve, not the shared `bg`. Nobody on stream can hover or click, so the
  controls go, the sort shows as a label, there is no hover card (the spotlight
  covers card art), and the sideboard stays open beside the panel, level with
  its foot like the in-game flyout, or below it. Lands show as one row or each
  land. A long singleton (Brawl) list is taller than any source and is clipped.
- Game-scoped widgets (`overlay`, `deck`, `matchup`) hide between games unless
  `idle=show`; the record and recent-games widgets always show while
  the tracker runs.
- The spotlight never replays history: on load and after a reconnect it
  catches up silently to the newest event, then shows only casts that arrive
  later. Card images come from Scryfall's named-card image URL, one request per
  cast; a failed image falls back to the card name.
- Widgets stop polling while the page is hidden. Poll rates: deck 500 ms in
  game, 2 s otherwise; record and matchup 2 s; spotlight 1 s; 5 s after an
  error.
- A small "Tapps Tracker" credit shows on each widget; `brand=0` hides it.
- `/api/live` gains `events=0`, which skips the event feed for widgets that
  don't need it.

Remaining validation, on the Mac Studio and the Windows machine with a real
game: each widget as an OBS Browser source at the suggested size; the full
overlay side by side with the in-game overlay (same numbers, sideboard in a Bo3),
and its `zoom` scaling in OBS's browser on both systems; the deck widget's odds
against the overlay's; the spotlight for both players' casts,
split and Alchemy (`A-`) names, and a reload mid-game (it must not replay the
game so far); hide/show between games and in a Bo3; the record across a
session break.

Not in this phase: dashboard access from another computer (two-PC streaming).
The server listens on 127.0.0.1 only and has destructive POST routes (reset,
update install). Opening it to the LAN needs a separate listener that serves
only `stream.html`, its assets and the two read-only GETs, off by default, with
the address shown in Settings.

### 2. Chat bot and shareable deck page

- **Deck page.** A static page (GitHub Pages, no backend) that renders a deck
  from the URL fragment, which browsers never send to a server. Encoding Arena
  card ids as varints keeps a 60-card deck near 150 characters, under Twitch's
  500-character chat limit. The page shows card hover images, Copy to Arena,
  Buy on Paper and a Tapps Tracker download link. It also works for Discord and
  Reddit links from the dashboard.
- **Chat bot.** Inside the tracker, signed in with Twitch's device-code flow
  (public client, no secret, the streamer enters a code at twitch.tv/activate).
  Commands: `!deck` (the deck page link), `!record`, `!rank`, `!winrate`,
  `!card <name>` (Scryfall link). Off by default; the token stays in the local
  data folder; replies are rate-limited; it never runs in Deck Finder mode.
- Open questions: the public client id and its Twitch app registration; token
  storage (OS keychain or settings file); whether a bot account or the
  streamer's own account posts.

### 3. Clips for YouTube, TikTok and Shorts

The replay MP4 export already takes a start and end. Add a vertical 9:16
preset and a "Clip the last game" shortcut on Live Scoreboard and the game
page.

### 4. Twitch panel extension (only if streamers ask)

A panel sits below the video, so it needs no screen positions: current deck,
session record, export button. It still needs the relay server from "What
exists elsewhere" and Twitch review, so it waits for demand from streamers
using phases 1–2.

## Growth

- The widget credit and the deck page footer are the main discovery paths.
- Pitch: no account, private and local, native macOS, replays with video
  export, Deck Finder and Deck Manager.
- Recruit a few small and mid-size MTGA streamers (macOS especially) before
  building phase 2, and ask what they want on screen.
