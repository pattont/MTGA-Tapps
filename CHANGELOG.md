# Changelog

## 0.7.5

### Updates

- In-app updates. The tracker checks GitHub Releases for a newer version (every six
  hours and shortly after start), downloads it in the background, verifies it against a
  signed manifest, and then offers **Restart to update** in a banner at the top of the
  dashboard, at the bottom left of the sidebar, and in the tray menu. **Settings →
  Tracker → Check for updates**, beside the version, checks on demand and says when
  you are on the latest version. Nothing installs mid-game: the restart waits for the
  current game, with an "Install after this game" option, and a pre-update backup of
  your game history is written to the data folder's `backups` first. **Settings →
  Updates** controls the check, the automatic download, and an opt-in fully automatic
  install that only runs while Arena is closed. Windows installs upgrade silently through
  the installer; macOS swaps the app bundle in place. The portable Windows zip and source
  runs link to the release instead. **This release must be installed by hand; releases
  after it update in place.**
- Database migrations now run one transaction each, so a failed migration rolls back
  only itself and is retried on the next launch.

### Buy on Paper

- New **Buy on Paper** button in Deck Finder, a saved deck in Deck Manager, and
  a deck page's Deck List section. It prices every card and updates the total
  as you untick cards or boards you already own. Then choose TCGplayer, Card
  Kingdom or Mana Pool to open the list in that store. StarCityGames and
  CoolStuffInc are listed as coming soon. Arena-only cards are marked and left
  out.
- Each store prices the cart from its own list: TCGplayer market prices via
  Scryfall, and Card Kingdom's and Mana Pool's published price lists, which the
  tracker downloads at most once a day. The store list is also the store
  picker: it shows every store's total side by side, in alphabetical order,
  and marks the lowest among stores that price every card. Switching stores
  animates each price and the total to the new values. A store only ever shows
  its own prices: a card it doesn't list shows a dash and is left out of its
  total. TCGplayer is the default.
- Settings has a **Buy on Paper** switch after In-game overlay. It explains the
  store price downloads (about 120 MB a day at most, a summary of about 16 MB
  kept). Turning it off hides the button everywhere, stops downloads and
  deletes the saved price lists.
- Mana Pool links now carry Tapps Tracker's referral code, so choosing Mana
  Pool shows a note that buying there earns Tapps Tracker a small commission at
  no cost to you, which helps support its development. The other stores still
  open plain links.

### Deck Finder

- **Add to Arena** no longer stays greyed out after you free deck slots in
  Arena. Full slots are only known from the last time the tracker read Arena,
  so Deck Finder now shows that as a note and lets you click: the add reads
  Arena again and stops with the same message only if the slots really are
  full. Any Arena read, even one that stops early, now updates the saved status.

### Replay

- Creatures with flying hover just above the table, casting a soft shadow
  beside them. Flying tokens and creatures given a flying counter hover too.
- Summoning-sick creatures carry a purple "Zzz" badge above the card until
  they can attack or tap, and hovering one says so. New games use Arena's own
  flag, which already accounts for haste, including haste from other cards.
  Older games estimate it from when each creature entered and whether it has
  haste printed, so haste given by another card can be missed there.
- A card you may cast from exile because of its own text sits beside your hand
  with a "From exile" chip, the way Arena shows it: Emrakul, the Exigent Doom
  and the rest of its cycle after they exile themselves from your hand, and
  Eternal Scourge or Squee wherever they were exiled from.
- Arena writes a very large update to its log as a summary with no details.
  A card cast during one used to show up later as an unknown face-down card
  while its old copy stayed in exile. It now returns from exile as itself
  (marked inferred), and the replay notes the gap. Earlier games are fixed too.
- The "inferred" tag under a face-down card reads normally instead of
  mirrored.
- A card that also had a token copy made of it during the game (Emrakul, the
  Exigent Doom copied by Three Steps Ahead) shows its own art, not a token's
  from the same set.
- Exported videos end on the same Victory / Defeat card as the replay, with
  final life totals, turns and length. The ending was missing because each
  frame could be drawn a step before the table caught up. That also made
  frames show the previous action.
- The export dialog gives its file size as an upper limit and says the
  browser's encoder decides the final size. Firefox keeps its own quality
  whatever the Quality setting, so its files can be much smaller than the
  estimate. The finished export now names its codec (H.264 or VP9).
- Tokens created attacking (Mobilize's Warriors) appear as the tokens they are,
  instead of face-down "inferred" cards attacking from nowhere.
- Tokens show their own token art. They used to show whichever card shared the
  token's number in its set: a Mobilize Warrior showed Furious Forebear, a Pest
  showed Ascendant Dustspeaker.
- Every card that exiles something "until this leaves the battlefield"
  (Banishing Light, Sheltered by Ghosts, Deep-Cavern Bat, Perilous Snare,
  Solitary Cell and the rest) now keeps what it exiled tucked under it. It
  used to work only when Arena still held the exiling trigger, which was
  rarely: most exiles landed in the exile pile. Earlier games are fixed too.
- A card put onto the battlefield together with its own enters trigger
  (Repurposing Bay fetching Pinnacle Starcage) no longer appears from nowhere
  with an "inferred" outline, and a land play Arena reports twice no longer
  moves the land again. Earlier games are fixed too.
- A noncreature artifact or enchantment that has exiled more than two cards
  (Pinnacle Starcage can take a whole board) shows them as a neat pile with an
  "N under" badge on its corner instead of a tall fan; hover the card to see
  them all. One or two cards, and anything under a creature, still fan out.
- Identical tokens and lands stack in one slot, the rest showing as edges under
  the top one with a ×N count, so a board of Spirits, Treasures or Mountains
  fits the table. Tapped ones stack apart from untapped ones.
- The same ability triggering several times in a row shows as one stack card
  with a bold ×N count and the copies fanned behind it (three Belladonna Took
  triggers are one card, not three).
- Attack arrows point at the planeswalker being attacked instead of the player,
  at full brightness. Arrows for effects on your own side (a trigger handing
  out counters) are dimmed, so the ones aimed at the opponent stand out.
- Arrows from a spell on the stack start at its card. With only a card or two
  on the stack they used to start in empty space above it.
- Stepping through a spell resolving while paused no longer bumps its card up
  half a card and back down when it was the only thing on the stack.
- Dragging the replay's position bar can no longer lift it off its track: the
  browser used to start a drag-and-drop, then the playhead jumped somewhere
  else. A drag the browser interrupts now stays where it was dragged to.
- A resolved ability's card and its effects leave the table when play moves to
  the next step, so combat damage no longer shows the last trigger as
  "Resolved".
- A tapped card's power/toughness and counter chips stay above and below it
  instead of running into the cards beside it.
- Every counter shows its name and count ("plan ×1", "oil ×3"), never a number
  like "counter_211".

### Deck page

- The Save to collection button beside Copy Arena Deck is gone. Save decks from
  Deck Finder or Deck Manager instead.

### Live Scoreboard

- Today's Games marks each game with a tiny teal Play or purple Draw pill beside the
  deck name.

### Dashboard

- In Deck Finder, hovering a card in the selected deck shows the card's image, so
  you can size up a card before adding the deck. Images load only on hover.
- A pink Buy me a coffee button sits below Deck Manager in the sidebar, for anyone who
  wants to support the tracker. It opens the Buy Me a Coffee page in your browser.
- The Sessions table has a Play / Draw column before Win Rate, counting the games you
  were on the play (teal) and on the draw (purple).
- A session now also ends after a long break: a match that starts four hours or more
  after your last game opens a new session, so leaving the app running for days no longer
  piles every night's games into one record. Settings → Sessions sets the break (1 to 12
  hours, or only when the app opens). A Best-of-3 match always stays in one session.

### Deck AI

- Grok is now a Deck AI provider: pick **xAI (Grok)** in Settings → Deck AI and paste
  an xAI API key. Its default model skips hidden reasoning, so each identification
  stays a small request.
- The Model field is now a dropdown of the models your key can use, loaded from the
  provider when you open Settings or enter a key. A link beside it opens the
  provider's own model page. If the list can't load, you can still type a model name.
- Providers are labelled **OpenAI (ChatGPT)**, **Anthropic (Claude)**,
  **Google (Gemini)** and **xAI (Grok)**.
- New default models: GPT-6 Luna for OpenAI, Claude Haiku 5.5 for Anthropic and
  Gemini 3.5 Flash-Lite for Google. The old Gemini 2.0 Flash default has been shut
  down and Claude 3.5 Haiku is no longer offered, so Deck AI with either had stopped
  naming decks; GPT-4o mini shuts down in January 2027. If you never picked a model,
  you move to the new default automatically. A model you chose yourself is kept.

### Fixes

- An opponent's draw could be logged as yours ("You: drew a card"), counted in your
  draws and shown as an unknown card in your hand in the replay. Arena had reused the
  id of an ability you started and then cancelled, and the tracker still remembered
  that ability under it.
- The in-game overlay could outlive the tracker: after the tracker crashed, was
  ended from Task Manager, or was uninstalled, the overlay kept showing over Arena
  until the next restart. The overlay now quits on its own a few seconds after the
  tracker that started it is gone, and the Windows uninstaller stops both before
  removing their files.
- When Windows Smart App Control blocks the overlay (error 4551), Settings and the
  tracker menu now say so instead of showing the raw Windows error.
- Collection export counted Alchemy-rebalanced cards twice: since Arena reverted
  its rebalances on 22 September 2026, cards such as Orcish Bowmasters exported
  as 8 copies instead of 4. Arena gives you the rebalanced version of every card
  you own, so the collection lists both; the export now counts the pair once.

## 0.7.1

### Replay

- Export video no longer fails with "decoderConfig is null" in browsers whose
  H.264 encoder leaves out the stream description (seen in Firefox on Windows);
  such browsers now export VP9 in the MP4 instead.
- When two creatures damage each other (a fight), each arrow keeps its own lane in
  its player's color, and arrows stop beside a card's damage number instead of
  covering it.
- Every interaction shows on the table while its action lasts. A spell or ability
  that resolved stays in the stack preview, and arrows run from it (or from the
  permanent that acted) to everything it hit.
- Players: damage and life changes appear at that player's side of the table and
  beside their life total, red for a loss and green for a gain, so Lightning Helix
  shows −3 on its target and +3 for its caster.
- Removal: a destroyed, dying, exiled, bounced or sacrificed permanent stays in its
  spot, dimmed and labelled (Destroyed, Died, Exiled, Returned to hand, Sacrificed),
  until the next action, then moves to where it went. Countered and fizzled spells
  stay stamped in the stack preview, with an arrow from the counterspell.
- Smaller effects: counters and power/toughness changes pop up on the card (+2/+2,
  −1/−1, +3/+0), and cards tapped by a spell, discarded or milled are marked.
- New recordings note which card caused each removal, so replays draw it from the
  right source even when several effects resolve together.
- Multiversal Passage shows the basic land type chosen for it: a chip in that land's
  color in the replay, and "played [Multiversal Passage (Land)] as a Mountain" in
  the tracker log.

### Live Scoreboard

- Today's Games shows a one-letter W/L result pill (the full result on hover), leaving
  more room for deck names.

### Deck Finder

- YouTube: complete lists are found even when a creator omits the Deck/Decklist
  heading.
- TCGPlayer: creator decks (such as Arne Huschenbeth's) load again; TCGPlayer
  retired the listing they came from, which failed with a 404.

### Dashboard

- Fewer background requests: Deck Finder checks Arena's status only while a deck
  is open and reads your collections only when the collection picker opens. Deck
  Manager, Deck Finder and the Overview stop refreshing in a background tab and
  catch up as soon as you return. The tracker no longer loads the Arena transfer
  library until a transfer starts.

## 0.7.0

### Replay (beta)

- A new teal **Replay** tile lists recent games, and each plays back on a 3D table
  with real card images: both hands, libraries, graveyards, exile, the stack with
  targeting arrows, life totals and an action log. A scrub bar segmented by turn
  offers play, step, skip/go to turn, speed and keyboard shortcuts. Playback starts
  at turn 1 with opening hands dealt and ends on a Victory/Defeat/Draw screen with
  the reason, final life totals and game length.
- **Watch replay** appears on Game Detail, Recent Games, All Games, deck and opponent
  histories and the Live Scoreboard; the console prints a replay link after each saved
  game, and each Game Detail timeline time opens the replay at that moment.
- Games already in the database replay as **Reconstructed** from their event log
  (approximate). Games tracked from this release on are **Recorded**, with taps,
  counters, tokens, blocks, attachments and hidden-card counts captured exactly.
- The table shows power/toughness badges (gold when changed), planeswalker loyalty,
  counter chips, real token art, a gold chip on Brawl commanders, and equipment,
  auras and cards exiled under a permanent fanned behind their host. Felt and sleeve
  colors are selectable.
- **Export video** renders a replay to MP4 in the browser (nothing is uploaded), up to
  Full HD, with an optional action log beside the table and a quality setting with a
  size estimate. Replay needs a tablet-width window and WebGL.
- The table is larger and framed like Arena, and cards are sharper on 1080p/1440p
  screens. The opponent's hand is larger on tall high-resolution screens, and both
  hands stay on screen and draw over the library beside them. Scroll over the table to zoom toward the pointer (up to 4x), drag to pan,
  and press `+`/`-`/`0` or Reset zoom; zoomed cards render at full resolution.
- Damage shows as red badges ("−6") on every permanent a spell or attack hit, and
  attack, block and target highlights glow on the felt. Cards castable from outside
  the hand (flashback, escape, disturb, harmonize, plotted) sit beside their owner's
  hand, labelled.

### Deck Manager (beta)

- A new **Deck Manager** page keeps every decklist with revisions, notes and tags in
  named, collapsible collections (Unsorted opens first), with search, sorting, status
  filters, mana-color pips, Trash and permanent deletion. Lists you save or submit in
  Arena are captured from the log automatically.
- **Direct Arena transfers** on Apple Silicon Macs and 64-bit Windows: load Arena's
  decks, back up one, a selection or all of them, move decks out of Arena into a chosen
  collection to free slots, and restore them later. Every transfer is journaled,
  verified and shows progress; bulk jobs can be stopped safely, and an interrupted
  transfer gets a read-only reconcile step instead of a retry. Arena's Decks screen
  redraws afterwards and selects and scrolls to the new deck. Deck Manager only touches
  Arena when asked, never during a game, and refuses Arena builds it hasn't checked.
- **Add to Arena** sends saved text decks through Arena's own importer, and
  **Copy deck list** copies Arena import text with exact printings.
- Tracker backups include the deck library and collections; merging keeps revisions,
  and resetting game data keeps saved decks.

### Deck Finder

- **Add to Arena** sends a found deck straight into Arena with its name, format and
  deck art; **Save to collection** files it in Deck Manager through a searchable
  picker. Doing both keeps one saved entry.
- **YouTube creators**: Hello Good Game (HGG) and Sloth by default, more in Settings.
  Lists come from the latest 15 video descriptions without a login or API key.
- Colored provider cards fit all seven sites on one row, and a larger selected-deck
  panel shows the full list with sideboard, commander and companion sections.
  Opening Deck Finder is faster: scrapers load on first use.

### Dashboard

- Decks, All Games and Sessions have numbered pages, first/last controls and Go to
  page. The Decks table and Sessions include the full history, with no row caps.
- Win Rate Trend has its own range selector (a day; 7/30/60/90 days; all time; or the
  last 10/25/50/100 games), with the range's average, low and high and its game count.
- Live Scoreboard has a tidier header and compact replay icons in Today's Games.
- Pages load faster: built files are cached and connections are reused, and the
  mana-symbol font is much smaller.

### Fixes

- Match results never infer a winner from a partial status update or stale life
  totals, and empty-library losses are recognized.
- 0-power creatures (such as Exhibition Tidecaller, a 0/2) show and print their stats.
- The console no longer logs a card returned from the graveyard to the battlefield as
  "returned to hand".
- Reconstructed replays use Arena's card database for opponent cards seen only by name,
  create tokens from abilities that make them, cast flashback spells from the graveyard,
  and keep transforming cards (Esper Origins) as the same card on their back face.
- Windows: Deck Manager messages no longer show garbled apostrophes, and Deck Finder
  runs on Python 3.9 again.
- Deck Finder loads Moxfield and AetherHub again where Cloudflare refused the
  connection, and Add to Arena accepts a card's other name (such as "Kavaero,
  Mind-Bitten" for "Superior Spider-Man"). When Arena's importer returns a different
  list, the message names the cards that differ.
- A deck added or restored through Deck Manager no longer appears twice in the library.
- When Arena isn't on its Decks screen, Deck Manager and Deck Finder say so plainly.
- Deck Manager shows Arena's formats readably ("Historic Brawl"), and its dialogs no
  longer close from a stray click or drag outside them.

## 0.6.5.3

### Fixes

- Competitive Brawl ranked matches now count toward the Constructed Ranked
  lifetime and season match stats, including wins, losses, win rate, and streaks.
  Their constructed rank changes already appeared in the chart; the stats now
  use the same ranked queue.

## 0.6.5.2

### Fixes

- Brawl games now show the opponent commander's full color identity in Recent
  Games, All Games, Game Detail, and the opponent-color summary. Immediate
  concessions and short games no longer depend on which cards were played,
  when the commander's identity is available in the local card database.

## 0.6.5.1

### Fixes

- Fixed an empty console window flashing above other applications every few
  seconds on Windows. The periodic overlay status check now runs `tasklist`
  without creating a visible window.

## 0.6.5

### Startup reliability

- Added independent **Start with Windows/macOS** and **Open dashboard on
  launch** switches above **In-game overlay** in Settings. Installed apps can
  register per-user login startup while remaining in the system tray or menu
  bar, and automatic browser opening can be disabled without stopping
  tracking. The existing `--no-browser` flag remains a one-run override.
- Windows uses the current user's Run entry and removes it during uninstall;
  macOS uses an app-owned user LaunchAgent. Source checkouts register their
  current virtual environment so the same controls remain available in development.

### Fixes

- Future Arena events no longer require a tracker update to avoid being
  mislabeled. Unknown event IDs from the active match room, EventLanding, or
  the outgoing `EventSetDeckV3` request are preserved as authoritative and humanized for display;
  deck edits, generic deck attributes, and command-zone inference cannot
  replace them. Generic identifiers such as `Constructed_Event_2026` and new
  date-suffixed event names also appear under the dashboard's **Events** filter,
  and a migration repairs existing rows that were stored as Standard or Brawl.
- Fixed Restore successfully replacing the database but reporting zero games
  immediately afterward. Migrated snapshots are now checkpointed and returned
  to single-file journal mode before the swap, so the first read-only summary
  can open them without waiting for SQLite to recreate WAL sidecars.
- Fixed Powered Cube matches being stored as generic Draft or even Brawl when
  Arena supplied `CubeDraft_Powered_*` as both the queue and event name. Cube
  event IDs now outrank deck attributes and command-zone inference, display as
  **Powered Cube**, and a migration repairs affected stored matches.
- Fixed Recent Games, All Games, and opponent history repainting older draft
  games with the colors of the newest revision sharing that deck name. Game
  rows now derive colors from their own submitted `game_deck_cards` snapshot.
- Prevented duplicate tracker processes on Windows and macOS. The unified
  launcher now acquires an OS-owned single-instance guard before starting the
  tracker, dashboard, or tray; a second manual launch reports that Tapps
  Tracker is already running, while a duplicate login launch exits quietly.
  Crashes release the guard automatically, and Deck Finder remains independently
  launchable from the running app.
- Fixed macOS overlay and app builds failing with `npm: command not found`
  when Node is installed through nvm but the build runs from a noninteractive
  shell. The shell build scripts now load the configured nvm default and
  validate the required Node 18+ toolchain before building.
- Fixed the macOS 27 overlay disappearing as soon as it starts. The newer
  `lsappinfo` output can include extra properties or return no frontmost app;
  the overlay now reads the foreground application from macOS's native
  `NSWorkspace` API instead of deciding Arena is never in front and hiding.
- Fixed the Settings page changing the overlay to **off** shortly after a
  tracker restart when an existing overlay singleton handled the new launch.
  The tracker now recognizes that existing process, and only an explicit
  **Quit overlay** action disables future automatic launches.
- Fixed the overlay settings getting an unnecessary vertical scrollbar when
  opened beside the minimal rail. The flyout now receives the full window
  height after the rail's display scaling is removed.
- macOS app bundles now identify themselves to the system and menu-bar
  managers as **Tapps Tracker** and declare their menu-bar-only activation
  policy. The bundle filename, executable name and identifier remain stable
  for upgrades. A new `scripts/build_macos_app.sh --fast` path makes it easier
  to test current source with that native identity; direct terminal launches
  remain Python processes.

## 0.6.4

### Backup & restore

Everything the tracker knows in one file. **Settings → Backup & restore**
writes a `.tappsbackup` and restores, merges or deletes one — made for the
week away from home: back up on the desktop, restore on the laptop, play,
then bring the week's games back.

- **What a backup holds.** A consistent snapshot of the game database
  (taken with SQLite's own backup API, with the raw-payload diagnostics
  buffer left out, then compressed — about 15 MB for a thousand games),
  `settings.json`, your Deck Finder creators and the overlay's
  preferences. **Include API keys** (on by default) decides whether the
  Deck AI key travels in the file.
- **The backup folder.** Any folder works, and the card offers the Google
  Drive, iCloud Drive, Dropbox and OneDrive folders it finds on this
  machine as chips — a chip fills the path in, **Set** remembers it, and
  nothing is created on disk until the first backup lands there. Choose
  one a sync client mirrors and the file turns up on your other computer
  by itself; nothing in the tracker talks to any cloud service.
- **Restore** says what it would do before it does anything — *adds 7
  games this computer does not have*, or *would drop 12 games recorded
  here that the backup lacks*, which needs `REPLACE` typed — then pauses
  the tracker, saves a copy of the current state (an **Undo** button puts
  it straight back), brings the snapshot up to this build's schema, swaps
  it in, and restores your settings while keeping this computer's own
  dashboard port, window size and backup folder. A backup written by a
  newer tracker is refused, with the reason.
- **Merge** is for history recorded on two computers: it adds a backup's
  games to the ones already here and removes nothing, so one more backup
  afterwards holds everything. Games, sessions and matches can never
  collide between machines — their ids come from the tracker session that
  recorded them — so a merge is a plain union; cards are matched by name,
  and merging the same backup twice adds nothing.
- **Backup Files** lists what is in the folder (date, computer, games,
  newest game, size) with **Open location**, **Restore**, **Merge** and a
  red **×** on each. Restore, merge and delete all ask first, naming the
  file and what will happen; only files inside your backup folder can be
  deleted from the card. The field below does the same for a file anywhere
  else on disk.
- Windows: the database swap waits out a file the system still has open
  instead of failing, and never lands a restored database beside the old
  one's write-ahead log.
- From a terminal: `python -m mtga_tracker.backup
  export|inspect|restore|merge|delete|list|folders`.

Automatic backups after each session, and Google Drive over its own API for
machines with no sync client, are the next steps
([remaining work](docs/plans/INDEX.md#smaller-follow-ups)).

### Fixes

- **The Live Scoreboard's color pips never lit.** The tracker's play events
  carry the display name the timeline prints — `Mountain (Land)`,
  `Smaug the Magnificent (Creature 6/6)` — and the scoreboard looked that
  whole string up for its colors, which no card database matches, so both
  players' pips stayed blank for the entire game (the archetype guess,
  which matches cards differently, still worked). Colors are now looked up
  by the bare card name, and a basic land lights the pips on turn one
  again.

### Docs

- README, Quick Start, agent guidance and the log, card-database and scry
  references reconciled with the implementation: the README lists current
  features and reference guides only. The completed release and overlay
  plans are replaced by [the release guide](docs/RELEASING.md) and
  [the overlay guide](overlay/README.md), unfinished plans keep only their
  remaining work behind [an index](docs/plans/INDEX.md), and the Linux plan
  gained discovery, desktop, packaging and real-system validation gates.

## 0.6.3

### In-game overlay

A small always-on-top window beside Arena that shows the library the tracker
knows and the odds of what you draw next. It is on from the first launch,
docked to the left edge; turn it off from **Settings → In-game overlay** or
the menu bar's **Stop Overlay**.

- **The rail.** A slim strip docked to the left or right screen edge (or
  floating) with the app's card mark at the top and three cells — **Turn**,
  **Land** (the chance your next draw is a land) and **Deck** (cards left of
  the deck, with a bar that turns yellow once half the deck is gone and red
  under 15 cards) — plus an arrow that opens the panel and a ⚙ that opens
  the settings beside the rail, without unfolding the panel. When the tracker isn't reachable the card mark greys out and
  carries a warning badge with the reason. The card mark is a vector
  drawing, sharp at any size and display scale.
- **The panel.** The full decklist, one row per card: name over mana cost on
  the left, copies left over next-draw odds centred in a darker band on the
  right. Hover a row for the card itself, beside the panel and nearly the
  width of the gutter, with the odds of drawing it next, within 2 and
  within 3 under the image; the row lights up while the cursor is on it
  and the card goes the moment it leaves — no clicking (the overlay never
  takes focus, so the shell watches the real cursor and tells the page
  where it is). Lands fold into one
  row that opens to indented Basic / Nonbasic rows; in Brawl, drawn
  singletons collapse into a Drawn group; a Sideboard row lists what is
  boarded. Above the list: land-drop odds for the next one, two and three
  draws, and a Play/Draw pill. Sort by odds, mana value or name; toggle
  card names in their colour. Odds are whole percentages. The final library
  stays up through Arena's results screen, marked **FINAL**, and clears
  when you leave it.
- **On, off, pinned.** The arrow (or the hotkey) turns the panel on; its
  chevron turns it off; the pin holds it out. It starts pinned: an opened
  panel stays until you unpin it. Unpinned, the rail is the folded panel:
  hovering the rail unfolds it, and it folds back once the cursor has been
  off it for the return delay. Off, the rail is just a rail. All three are
  remembered game to game and across launches. Between games the panel folds away; a pinned one comes straight
  back when the next game starts.
- **Where it lives.** Only while Arena is running, on Arena's screen — over
  a fullscreen Arena too on macOS — and it steps aside while Arena isn't the
  front window. Flush with the screen edge, with a few pixels of plain
  ground between the text and the edge; drag it up or down the edge and it
  snaps back flush the moment you let go. Windows: exclusive-fullscreen
  covers every overlay; use windowed or borderless.
- **Look and settings** (the ⚙ menu, which opens beside the panel or the
  rail — never over the decklist): a charcoal tint with hairlines between
  rows and no box border. **Scale** from 50 % to 200 %; **Rail opacity**
  (default 90 %) and **Panel opacity** (default 80 %), which drive only the
  tint — text is always solid; **Max panel height** in pixels (default
  800, always capped by the screen; the list scrolls inside); dock;
  click-through; density; the hotkeys — `Alt+Shift+T` / `⌥⇧T` toggles the
  panel, `Alt+Shift+H` / `⌥⇧H` hides the overlay — and a **Restore
  defaults** button that puts every preference back (the window's position
  and the panel's on/pinned state stay).
- **From the tracker.** The Settings page shows one card — *Overlay is on*
  / *Overlay is off*, one sentence, and a **Turn on** / **Turn off** button
  — over the hotkeys; off means nothing runs and nothing starts with the
  tracker until it is turned on again. The menu bar shows an *Overlay: Running / Stopped* line under
  the tracker's, with Start/Stop Overlay and Overlay Settings in their own
  section; the overlay adds no menu-bar icon of its own.
- **Works in every game, tracked or not.** Jump In, Midweek Magic,
  Welcome Deck Duels and practice games against Sparky stay out of your
  stats as before, but the overlay follows them like any other game — the
  library and the odds are just as useful there. (The tracker's live row,
  which the overlay and the Live Scoreboard read, is kept current during
  those games; nothing from them is saved as history.)
- **What it reads and what it costs.** A separate native app (Tauri v2, a
  Preact page, about 5 MB) shipped inside the tracker. It polls this
  tracker's local `GET /api/overlay` three times a second during a game and
  loads card images from Scryfall on hover — nothing else, and never the
  game itself. An unchanged poll is one indexed read on a kept-open
  connection (about 0.05 ms); the tracker reads Arena's log four times a
  second and a check with nothing new costs about 0.01 ms.
- **Building from source** needs Rust: `scripts/build_overlay.sh` (or
  `.ps1`); `--fast` makes an incremental iteration build in seconds.
  Release builds include the overlay.
- **`GET /api/overlay`**: the library the tracker knows (deck minus what has
  left it, from the kept opening hand on), per-card hypergeometric odds,
  land-drop odds, format, opponent, turn, play/draw and the head-to-head
  record — with an ETag so unchanged states answer 304.

### New

- **Scry is tracked.** Every scry is counted per seat — how many scries,
  how many cards they looked at, and how many went to the top vs the
  bottom — for both you and the opponent (Arena lists the card ids even
  when the opponent's cards stay hidden). The timeline line says what
  actually happened instead of a bare "scried": `You: scried 2 — kept
  [Opt] on top, bottomed [Plains]` (the opponent's reads `scried 2 — 1
  top, 1 bottom`), with its own **Scry** badge in the game timeline and
  the Live Feed. The game page and the deck page get a **Scry** group in
  Combat & Resources, under Cards: Scried, Cards scried, Scried Top and
  Scried Bottom, the last two with their share of everything scried
  alongside ("1 (33%)"); Removal moves to lead the next column so the four
  columns stay close to even. Which cards were kept or bottomed is recorded
  per scry but not shown yet. Historical games get their scry count back
  from their timelines (the old lines carry no amounts, so their card
  totals stay blank). Surveil is not yet counted.
- Recent Games, its Bo3 match rows, and Sessions load 30 rows instead of
  25, so the tables' 15-a-page paging shows two full pages.
- **Wins vs Losses** on the Overview gets an **Avg Game Time** column, and
  its blurb (and the empty-state notes on the game and deck pages) no
  longer talk about "telemetry" or what early tracker versions did not
  record.
- The Deck AI description on the Settings page is three sentences instead
  of a wall.

### Fixes

- **The Live Scoreboard lost the previous game at midnight.** Its "today's
  games" list went by calendar day, so a game played at 23:58 had no
  outcome and no record at 00:05 and the Previous Game chip went blank. The
  list now also carries the current tracker session's games and always the
  most recent finished game.
- **"Card #N" rows that never resolve.** A draw could be recorded against an
  ability object standing in for the drawn card, so the deck stats kept a
  `Card #1156`-style row no card database could ever name, and Database
  Health flagged it forever as a manual UNKNOWN_CARD_LABEL. The draw is
  still counted but no longer recorded under a placeholder (a diagnostic
  line says what was seen), and the audit now asks Arena's card database
  whether N is a card at all: ids that are not become repairable, and
  `db_audit --repair` removes those rows. Placeholders for real cards the
  local database has not learned yet still heal themselves on a later
  launch.
- **A stray "OperationalError: unable to open database file" on the Live
  Scoreboard.** A read-only open of the database can lose a race with the
  tracker's own WAL checkpoint, and a Mac app launched from Finder starts
  with only 256 open files for Qt, the dashboard's per-request connections
  and the browser's sockets to share — SQLite reports both as the same
  unhelpful message. Read-only opens now retry once, the app lifts its
  open-file limit at startup, and a failure that survives the retry is
  written to `data/logs/dashboard-errors.log` with the file, WAL and
  descriptor state that explains it.
- **Windows: the tray menu could hide Quit under the taskbar.** A
  right-click on the tray icon opened the menu downward from a cursor at
  the very bottom of the screen. The menu now opens upward (and leftward
  at the right edge) whenever it would not fit.
- **A blank deck-art tile.** The signature-card tile only showed its
  type-colored frame after both art requests had *reported* failure; a
  Scryfall image request that stalls or answers 503 without the browser
  ever raising an error left an empty box with no art and no frame. The
  frame is now the tile's base layer and the art fades in over it once it
  has actually loaded; a request that has neither loaded nor failed after
  six seconds is treated as failed and the by-name fallback is tried.
- **The packaged app's Deck Finder page was blank.** The installed tracker
  did not carry the deck-site modules the Deck Finder loads at runtime
  (only the terminal Deck Finder analysis did), so the dashboard was
  offered no sites and drew an empty page. The installers now include
  them — the build refuses to package a tracker whose Deck Finder would
  have no sites — and if no site can be loaded the page says so, with the
  reason, instead of showing nothing.
- **Windows: the paths on the Settings page could not be opened.** Log DB
  and the other paths hid the username as `~\AppData\...`, which Explorer
  does not understand. They now read `%USERPROFILE%\AppData\...`, which
  still hides the username and pastes straight into Explorer's address bar
  or a Run box.
- **Windows: upgrading left old files in the install folder.** The
  installer only ever added and replaced files, so a program an earlier
  version shipped and the new one does not — `MTGA Deck Downloader.exe`,
  now folded into the tracker — stayed behind, and so did anything stale
  in the bundled runtime folder. Setup now clears `_internal` and that
  executable before installing. Tracked games and settings live outside
  the install folder and are untouched. (Unpacking the zip over an older
  extraction keeps old files the same way; unpack it into a fresh folder.)

### Housekeeping

- **One executable.** The Deck Finder terminal tool no longer ships as a
  second program (`MTGA Deck Downloader`) beside the tracker — on Windows
  that put two `.exe`s at the top of the install folder, and a PyInstaller
  program cannot simply be moved into a subfolder the way the overlay's
  self-contained binary was. It is now a mode of the tracker itself:
  `MTGA Tracker --deck-finder` runs the same terminal UI, which is what
  the dashboard's Deck Finder page launches in a terminal window. The
  install folder is `MTGA Tracker.exe` plus `_internal`, and the download
  is a little smaller for not carrying the second copy.
- **Fewer "unknown log entry" diagnostics.** Arena's ordinary client
  chatter — its own requests (`==> GetFormats …`), the server's answers,
  scene changes, and the connection and startup notes — is now named for
  what it is instead of landing in `mtga_tracker_unhandled_annotations.log`
  and the raw-payload archive on every launch (dozens of entries per
  session, hundreds over a day of tab-switching). Nothing about tracking
  changes: every line was and is still processed; the diagnostic file now
  holds only things the tracker has genuinely never seen. The archive gets
  cleaned up too: a one-time pass drops the chatter already stored (then
  compacts the file), and from now on archived payloads are kept for 30
  days — it is a diagnostics buffer, nothing reads it back after that.
- tappstracker.com rebuilds itself whenever this changelog changes on
  `main`.

### Docs

- Plans for [Linux support](docs/plans/linux_implementation.md) (Arena
  under Steam/Proton or Wine, phased so CI verifies it before a Linux
  desktop exists) and for [scry/surveil tracking](docs/plans/INDEX.md#smaller-follow-ups)
  (the scry half is shipped above).

## 0.6.2

### Windows installer — read this if Defender complains

Windows Defender has been quarantining `MTGA Tracker.exe` from the 0.6.1
installer as **Trojan:Win32/Wacatac.B!ml** (sometimes `.C!ml`). The tracker
is not malware; the `!ml` suffix marks a machine-learning *guess*, not a
match against anything known, and it fires on unsigned PyInstaller apps
constantly. The shape of this one is exactly what the heuristics distrust:
a freshly built, unsigned executable with no publisher that tails another
program's log, runs a local web server, launches helper processes, and — for
the collection exporter — reads Arena's memory.

This release does the two free things that help:

- **The PyInstaller bootloader is compiled from source** on the build
  machine instead of shipping the prebuilt one that every PyInstaller-packed
  trojan also ships, so the exe no longer shares those bytes with them.
- **Both executables carry a real version resource** (company, product,
  description, version) — an anonymous exe scores worse than a described
  one.

Signing the binaries is the only complete cure and it costs money every
year, so it is not happening for a free tool; each release is instead
submitted to Microsoft as a false positive, which clears that build within a
day or two. If Defender has already quarantined your install: **Windows
Security → Protection history → the Wacatac entry → Restore**, then **Allow
on device**, or reinstall after the verdict clears. Details in QUICKSTART.

### Performance

Measured on a ~1000-game database. Numbers are cold loads from the tracker
itself; a warm dashboard is faster still.

- **Overview: 803 ms → 227 ms** (about a quarter of the time). All Games and
  deck pages load in under half the time; the opponent page in about a fifth.
- **Refreshes between games answer in ~8 ms instead of recomputing
  everything.** Read endpoints are memoized against a fingerprint of the
  analytics tables; the tracker's heartbeat doesn't invalidate it, while a
  finished game, a saved note, or an AI archetype landing invalidates it
  immediately (60-second ceiling either way).
- How: six new indexes (participants by game/role/deck, deck cards by
  participant and zone, opening hands and draws by participant, games by
  match), one set-based draw-quality pass for the overview and All Games
  instead of one query per game, and a cached split-card name lookup for
  exports. Existing databases pick up the indexes at their next launch — a
  one-time build of about 0.3 s.

### New

- **Wildcards on the Overview**, beside the deck search: common, uncommon,
  rare, and mythic counts read from the inventory block Arena writes to its
  log at launch and on every event join (gold, gems, and vault progress are
  stored too). Nothing shows until the tracker has seen one.
- **Live Scoreboard shows your lifetime record against the opponent's
  commander** in Brawl, one line per commander, hidden until you've faced it.
- The menu-bar item is now **Live Scoreboard**, matching the page.

### Fixes

- **Opponent colour pips could stay blank until turn 7.** When Arena's card
  database wasn't readable at the moment the tracker built its colour index,
  the index was cached for the session with only cards from earlier games.
  It now keeps retrying Arena's layers until they answer, looks up unknown
  cards on demand, and basic lands light their colour on turn one.
- **The scoreboard's "Looks like…" guess could flip to an impossible
  archetype** (Gruul → Mono-Red after a Forest). Lands no longer count as
  evidence, and a guess whose colours contradict the table is dropped.
- **All Games flood/screw badges disagreed with the game page** for a couple
  dozen games — the list ignored ramped lands and the real land ratio. Both
  now use the same rules.
- **Profile and combat columns were blank for decks past the 40th.** The
  Decks table lists up to 100 decks but its combat telemetry stopped at 40,
  so players with many small decks saw dashes on rows with plenty of games.

### Docs

- README, Quick Start, and AGENTS refreshed; the in-game overlay plan
  rewritten for Tauri v2 with the rail/panel design mockup
  (the completed design is now documented in [the overlay guide](overlay/README.md)).
  The overlay itself shipped subsequently in 0.6.3.

## 0.6.1

- **Renamed to Tapps Tracker** everywhere you see it (menu bar, dashboard,
  window titles). App bundles, commands, and data folders are unchanged, so
  nothing moves on your machine.
- **Brawl: commanders everywhere.** Game pages open with a commander-vs-
  commander strip and the Opening Hand names your commander (hover for the
  card); deck pages use the commander as the deck's signature art, add a slim
  commander banner above the decklist, and list the Opponent Commanders you've
  faced with your record against each. The overview's Brawl section is always
  visible (own nav entry) with Best Commander and Toughest Opponent Commander
  boxes backed by card art.
- **Brawl: decklists include the commander.** Arena's submitted maindeck
  leaves the commander out, so a Brawl list now shows all of its cards; Arena
  exports gain a `Commander` section, and the commander's Games Seen is 100%
  — it is in the command zone every game. Scoreboard colors seed from the
  commander the moment it is revealed. (Brawl is recognized from Arena's
  match format, never from deck size.)
- **Fixed: Expected Lands used a flat 40% heuristic** on the game page and an
  older decklist version on the deck page. The game page now uses the
  decklist submitted for that game (or the deck's nearest one); the deck page
  uses the newest decklist's land ratio; the label says `est.` only when no
  decklist exists at all.
- **Draw Quality reworked.** Game page: Total Cards Drawn, Total Cards Seen,
  Lands Drawn, Lands Seen, Expected Lands, Longest Land Streak, Draw Status on
  one line, land percentages in the labels. The 8-draw-window and low-land-
  drought boxes are gone — the flood/screw evidence line already says it in
  words. Deck page shows per-game land averages with the share beside each
  label.
- **Opponent mulligans are tracked.** Arena reports mulligans for both seats;
  the game page Mulligans box reads You / Opp. Games tracked before this
  release show a dash for the opponent.
- **Bo3 matches count once** in opponent counts and the opponents list; the
  opponent page rolls each match into one expandable row with a Matches card.
  All Opponents is its own page with a back link, a search box that shows the
  count, and gold focus rings on every filter control.
- **Two-tier format filters** on Recent Games and All Games: family pills
  (Standard, Historic, Modern, Pioneer, Timeless, Limited, Brawl, Events) with
  fly-out queue and Bo1/Bo3 refinements. All Games drops the redundant format
  dropdown and search box, widens the deck picker, and shows 30 rows.
- **Deck AI transparency.** Settings, the Settings dialog, and the README now
  state exactly what the API key is used for: one small request per completed
  game, after the game ends, containing only the names of the cards your
  opponent revealed — never your deck, account, or log. Scoreboard colors and
  the mid-game deck label are computed locally and never use the key.
- Live Log is now **Live Scoreboard**; the scoreboard keeps the previous game
  up across reloads with a "Waiting for next match…" pill; Stop Tracking shows
  as stopped immediately; Deck Finder pills stay lit for the current results.
- **Fixed: blank opponent color pips** — the color index no longer caches an
  empty result when the analytics database is busy at startup, and it reads
  Arena's renamed Localizations table.
- Release workflow actions bumped to their Node 24 majors; `macos-debug.md`
  documents the macOS "icon shudders and quits" launch failure and its fix.

## 0.6.0

- **Live Scoreboard.** During a game the `/live` page shows your lifetime and
  today's record with the current deck, head-to-head record against the
  opponent, lands played per side, a ramp-aware draw-quality strip, a per-turn
  timer, your rank on ranked queues, and a best guess at the opponent's
  archetype from their revealed cards (matched locally against earlier
  identified games — no network). Between games the previous game's final
  scoreboard stays up with a Previous Game chip showing the result.
- **Opponents.** New Opponents section on the overview: your five most-faced
  opponents with records, plus your record by opponent color combination —
  and a searchable Opponents page listing everyone you've ever been paired
  against.
- **Fixed: a handful of games recorded you as your own opponent.** A
  migration cleans up the historical rows.
- **Removal accuracy overhaul.** Removal, wipe, bounce, and counter
  classification audited against the card pool: edicts count as removal,
  graveyard hate and hand disruption do not, land destruction is excluded,
  temporary exile counts, and conditional sweepers are judged by outcome (a
  board wipe only when they actually cleared the board). Three migrations
  recount every historical game; `docs/REMOVAL_CLASSIFICATION.md` records
  every ruling.
- Play/Draw and mulligan badges replace the old Mulligans column on Recent
  Games and All Games; All Games gains a Colors column; single gold focus
  rings on filter controls; consistent section spacing throughout.
- **Fixed:** stopping the tracker from the menu bar now flips the dashboard's
  tracker state to off immediately; the All Opponents page no longer errors
  on load.
- Restart the tracker after updating — migrations run at startup.

## 0.5.9.2

- **Fixed: exports could grab a deck instead of your collection.** Arena keeps
  deck objects in memory that look exactly like a collection block, and the
  scanner could return one (34 cards exported instead of thousands). Candidate
  blocks are now gathered across all of Arena's memory and the largest valid
  one wins; deck-sized blocks are rejected outright.
- **Fixed: missing set codes on non-default installs.** The export now finds
  Arena's card database via the install path Arena announces in its own log,
  so set codes fill in on any install location — and if the database still
  can't be found, the export says so instead of quietly shrinking.
- **New: Export for Archidekt.** A fourth export format whose Scryfall ID
  column removes all import ambiguity (Moxfield reads it too). IDs resolve
  through Scryfall's batch API with fallbacks for Arena's mismatched
  collector numbers (Alchemy sets, special prints), then cache locally so
  repeat exports are instant and offline.
- Card names no longer carry Arena's `<nobr>` markup in exports.

## 0.5.9.1

- **Fixed: collection export crashed on Windows** with "int() argument must
  be a string … not 'NoneType'". Windows reports the first memory region at
  address zero, which the scanner mishandled before reading a single byte —
  the export never worked on Windows until now. macOS was unaffected.
- **Release versions now come from the git tag** (setuptools-scm). The app,
  installers, and dashboard all derive their version from the `v*` tag the
  release was built from — no hand-edited version strings anywhere.

## 0.5.9

- **Ramped and searched lands now count in Lands Seen.** A land pulled from
  your library straight onto the battlefield — Lumbering Worldwagon fetching a
  basic, Cultivate, fetch lands, and the like — used to vanish from every land
  count because it was never "drawn." It now shows up in Total Lands Seen for
  both live games and, via a one-time backfill of your history, past ones.
- **Fetched lands no longer read as flood, but still protect against screw.**
  A land you searched out on purpose was not drawn against your will, so it is
  excluded from the flood side of the flood/screw math — ramp-heavy decks stop
  reading as flooded just for doing what they do. Screw keeps those lands,
  because a land you have (even a fetched one) is still mana in play and makes
  a mana-screw reading correctly less likely.
- **Export your MTGA collection** from the Settings page — three buttons
  (`.json`, `.csv`, `.txt`) that read your full card collection out of the
  running game and write a file you can import into Moxfield and similar
  sites. Arena must be running with the collection loaded (open the Decks
  tab once); on macOS an administrator prompt appears, since reading another
  app's memory needs elevated access. Anchors are derived automatically from
  your own tracked decklists — nothing to type — and a second export within
  a few minutes reuses the first scan (no repeat prompt). Extraction
  technique adapted from
  [NthPhantom10's MTGA-collection-exporter](https://github.com/NthPhantom10/MTGA-collection-exporter).

## 0.5.8

- **Live Log is now the Scoreboard** — the old Qt play-by-play window is
  replaced by a live page in the dashboard (`#/live`): a hero scoreboard with
  both life totals, color pips, and deck name, a friendly format chip, the turn
  and game clock, and Brawl commander art with hover previews. Below it, a Live
  Feed that renders through the exact same timeline component as the `/game`
  page (so it reads identically), the current game's play-by-play, a retained
  "Previous Game" between matches with a closing "Game ended" banner, a session
  rail (record, runtime, live/ready status), and a scrolling Today's Games list.
  The Qt window is now a buried debug fallback (`MTGA_TRACKER_QT_LOG=1`).
- **Deck Finder moved into the dashboard** — no more separate terminal window.
  Pick a site then a format, browse a per-site results table (win rates for
  untapped.gg, event placings for tournament sites, and so on), open any deck to
  export it to Arena or jump to the source, or hit "Surprise Me". Creator lists
  moved to the Settings page.
- **Settings is now a dashboard page** (`#/settings`, gear icon on every page):
  Deck AI configuration, Deck Finder creators, a tracker-status readout
  (monitoring/card DB/log DB/version), a single sun/moon theme toggle, and the
  Database Health link — all in the web UI. The old Qt dialog remains as a
  fallback.
- **Colorless is a color**: the colorless diamond ("C") now shows wherever
  colors do — Recent Games, the Decks table, deck and game pages, and the live
  scoreboard — for decks and opponents whose known cards are all colorless
  (Eldrazi, artifact decks), instead of showing nothing.
- **Sidebar & navigation**: a Live Log entry above Overview that turns green
  while the tracker runs and red when it's stopped, an icon on every nav item
  (icon-only when the rail is collapsed), a Deck Finder button with a magnifier,
  and a global search that finds cards or decks.
- **Deck colors everywhere**: color pips on the deck page header, a Colors
  column on the overview Decks table, and a Colors column in Recent Games
  (between Deck and Format). Colors are judged lands-first from real casting
  requirements — land identities carry double weight, hybrid pips ({U/B})
  never force a color, a single off-color card never counts, and decks
  tracked before decklist capture fall back to the cards they were seen
  playing, so every deck gets pips.
- **Card page overhaul**: sections reordered (Summary, Opening Hand Impact,
  opponent impact, Played By Side, Repeat Draws, Opponent Repeat Draws, Your
  Decks), an Avg Per Game metric, the same ambient card-art backdrop as the
  deck page, and a new **"Opponent Could Have Played It"** panel — games
  where the opponent's revealed colors could cast the card, how often they
  actually did, and the appearance rate. Computed live from existing data,
  no backfill.
- **Recent Games**: the Match Record column is gone from the top level (a
  win is a win) — expanding a Bo3 match shows "Match record: 2–1" in the
  flyout instead.
- **Deck page polish**: hero-sized signature art (with a by-name Scryfall
  fallback for new sets whose Arena-ID mapping hasn't landed yet), the Copy
  Arena Deck button moved into the topbar beside the card search, and
  Decklist Changes moved down between Vs Opponent Colors and Recent Games.
- **Overview**: the deck page's Land Statistics (Normal/Flood/Screw split
  across all classified games) now heads the land section, Opponent Meta
  pages at 10 rows instead of silently cutting at 15, and the Decks table
  dropped Life Gained / Game to stop horizontal scrolling.
- **Fit and finish**: Combat & Resources "(N drawn)" counts render as small
  muted one-line suffixes instead of wrapping, the card-search focus ring is
  a single clean accent border, pages scroll clear of the Back to top pill,
  official card-type symbols (chalice, claw mark, sunrise…) with singular
  labels in the deck-list type boxes, and "Imported Deck" games retitle
  themselves the moment the renamed deck's first game lands instead of
  waiting for a tracker restart.

## 0.5.7

Rolls up everything since 0.5.5 (including the 0.5.6 beta's date repair).

- **Mana columns everywhere cards are listed**: the deck page's Deck List &
  Sideboard, and the game page's Opening Hand, Drawn Cards, Cards Played, and
  Opponent Deck tables all show each card's cost with official symbols.
- **Opponent Deck on the game page** replaces "Opponent Revealed Cards", split
  into Opponent Played Cards (with the turn(s) each copy hit, like your own
  Cards Played table) and Opponent Revealed Cards (visible draws, discards,
  mills, exiles).
- **Table totals**: proper totals rows on the deck list and sideboard, and on
  the game page's Drawn Cards, Cards Played, and Opponent Deck tables.
- **Mana costs on the deck list**: a new Mana column (between Card and Type) shows
  each card's cost with the official MTG symbols — hybrid, twobrid, Phyrexian, X,
  the lot — rendered from a bundled icon font (mana-font), no network needed.
  Costs come from Arena's own local card database (backfilled into the tracker's
  `cards` table at startup and after each game, like color identities already
  were), with a browser-cached Scryfall lookup as fallback for anything Arena's
  DB doesn't cover. Works for every deck retroactively.
- **Deck list at a glance**: MTGA-style card-type count boxes (Planeswalkers →
  Lands) above the deck list, plus "N cards total" lines under the main deck and
  sideboard tables.
- **Mana-value stats in Combat & Resources** on both the game and deck pages:
  "Mana value / card played" and "Mana spent / turn" for you vs the opponent,
  computed from printed costs (lands excluded, X = 0) — a low cards-played count
  with high mana spent per turn reads very differently from four one-drops.
- **Repaired dates stored month/day-swapped by pre-0.5.5 versions** for day-first
  locales: games recorded before the locale-aware parser (e.g. 9 August read as
  8 September) landed months in the future and scrambled every date-sorted view.
  A one-time migration swaps them back using each tracker session's system-clock
  start time as the anchor — conservative by design, ambiguous rows are left
  untouched. Covers games, matches, turns, events, console logs, rank snapshots,
  and the payload archive. No database reset needed.

## 0.5.5

### Brawl

- **Brawl is now a first-class format**: commander win-rate tables on the Overview
  (your commanders and the ones you faced), an overall and per-queue record strip,
  Brawl queue labels plus commander matchup rows in Recent Games, and the commander
  tables page at 8 rows. The Competitive Brawl queue keeps its label even when
  Arena's deck attributes disagree, and Standard/Historic/ranked Brawl stay distinct
  everywhere.

### Per-game combat & resource stats

- **New tracked categories on the game page** — Removal (spot removal and board
  wipes played, with your drawn counts folded in, plus creatures/non-creatures lost
  to removal), Bounce (bounce cards played, permanents bounced to hand), Land
  Destruction (lands destroyed, successfully replaced by a land drop, lost for
  good, and the replacement rate), Counter Magic (counters played, and — from the
  actual stack outcome — how many landed vs failed), Tokens (created / destroyed /
  sacrificed / exiled per seat), and Poison counters. Card roles are classified
  from Arena rules text, so removal counts from the first game a card is drawn.
- **Historical games are backfilled automatically**: a one-time migration recomputes
  the behavioral stats (removed/bounced permanents, lands, countered spells) for
  every old game from its recorded timeline, and `scripts/backfill_card_role_stats.py`
  fills the classification-based columns using the local Arena card database.
  Stats that genuinely cannot be reconstructed (tokens, poison, opponents' draws)
  show a dash rather than a fake zero.
- Outcome reasons now detect **decked, poisoned, and timeout** endings that were
  previously labeled as concessions, and concede labels are short ("Opponent
  conceded" / "You conceded").

### Deck page

- **Combat & Resources on the deck page**: every game-page category as per-seat,
  per-game averages, in the identical column layout (the game and deck pages now
  share one deterministic arrangement instead of height-balanced masonry).
- New **Turn Timing** (average your/opponent turn time per game and per turn) and
  **Draw Quality** (average cards and lands seen/drawn, expected land rate)
  sections; **Formats** became win-rate rectangles per queue with BO1/BO3 labels;
  **Vs Opponent Colors** opens with Best Against / Worst Against highlight cards.
- The page picks up an ambient background tinted from the signature card's art,
  and metric cards across the deck and game pages gained icons.
- **Deck identity can no longer be misattributed**: the decklist actually submitted
  to a game now arbitrates which deck the game belongs to, fixing games recorded
  under a previously-played deck's name when the tracker launched mid-queue.

### Overview

- **Match-level records everywhere**: a Bo3 counts once — top row shows Matches /
  Wins / Losses / Win Rate / longest streaks with icons, Wins vs Losses splits are
  colored and Wins-first, and How Games End presents per-reason percentages in
  side-by-side Wins and Losses tables.
- **Constructed Ranked** section with lifetime match stats, a season dropdown,
  the rank chart, and per-season stats (constructed queues only — ranked Brawl
  tracks separately). New BO1-Ranked / BO3-Ranked quick filters, a searchable
  Deck filter, and the win-rate trend now covers the last 30 games.
- **Log timestamps are locale-safe**: day/month order is learned from unambiguous
  entries (with a system-locale fallback), fixing "today's games" sorting between
  older dates for day-first locales, and dates render in the viewer's locale.

### Game page

- Cards Played shows the turn(s) each card was played, Opponent Revealed Cards
  shows the reveal turn, Drawn Cards pages at 10 turns, and the Repeat Draws card
  view always shows the 3 and 4+ buckets — including the opponent's repeat draws.

### Fixes & maintenance

- **Fixed DB Health falsely reporting `GAME_EVENT_ASSIGNMENT_MISMATCH`** for post-game tail
  events (Bo3 sideboarding gaps, rank updates, summary lines) — on a real database every
  flagged row was a tail and none were misassigned. The old repair also *detached* those
  rows, deleting real timeline entries. The finding and repair now only act on events whose
  timestamp falls inside a different game's window, and the reassignment runs automatically
  at tracker startup (a new index takes the pass from 4.4s to ~150ms) so nobody needs
  `db_audit --repair` by hand.
- **Stopped tracking Welcome Deck Duels** (pre-made deck vs pre-made deck, e.g.
  "Welcome Deck Duels HOB"); migration v15 removes already-saved games of this mode and
  recomputes session stats. The README's "What isn't tracked" list and the dashboard's
  format filter are updated to match.
- **A new set's card database is picked up mid-session**: after each game the tracker allows
  one re-scan for a newer `Raw_CardDatabase`, so set-release day no longer needs a restart
  when Arena drops the new DB alongside the old one. Arena's card DB is now always opened
  strictly read-only, so the tracker can never create or modify files in Arena's folder.
- A concede during the opening mulligan decision is recorded as a real game instead of
  being skipped as a ghost.
- Database hygiene: new indexes on the game-events timeline and payload archive,
  `PRAGMA optimize` each launch, and `scripts/delete_untelemetered_games.py` (which now
  VACUUMs after deleting) to drop early games recorded without combat telemetry.

## 0.5.4

- **Proper Windows installer**: releases now ship `MTGA-Tracker-<version>-setup.exe`
  (Inno Setup) with a Start Menu entry, an Apps & Features uninstaller, and in-place
  upgrades. Installs per-user by default (no admin prompt) with an optional
  all-users/Program Files mode; uninstall asks before touching your tracked-game data.
  The portable `-windows.zip` is still published alongside it.
- **Multi-target spells show every target**: Arena sends one TargetSpec annotation per
  chosen target, and the tracker kept only the last one — Ram Through showed only the
  creature taking damage, not the attacker dealing it. Targets now merge in selection
  order. BlockerDeclared annotations got the same hardening (every affected id is
  treated as a blocker).
- The install-discovery log parser gained a second, Windows-verified marker (Arena's
  localization line names a file inside `Downloads\Raw` directly) and now normalizes
  Arena's mixed forward/back slashes.
- The "Resolved N previously unknown card label(s)" message no longer repeats on every
  launch: duplicate-name placeholder rows are folded into the real card's row once,
  and only actual changes are counted.
- Startup output tidied: Detailed Logs state prints only on changes, and one-time
  maintenance messages appear inside the startup banner instead of after it.

## 0.5.3

- **Arena installs are now found anywhere** — standalone (.msi) installs on any drive
  included. The tracker reads the install path Arena itself announces in the head of
  `Player.log` (the Unity `[Subsystems]` header, verified against a real log) and derives
  the card-database folder from it, ahead of the Steam-library and Program Files guesses.
- **Databases recorded without the card DB heal completely.** The startup backfill that
  rewrites `Card #N` placeholders now also covers mulligan-hand rows, labels with no
  matching `cards` row, and duplicate-name collisions — so a user whose install was
  previously unfindable gets their full history renamed on the first launch after updating.
  The DB Health finding for these labels now explains that restart-to-fix in plain language.
- Builds no longer use UPX compression, which was tripping antivirus heuristics on the
  unsigned Windows executables.
- Docs: `AGENTS.md` expanded and corrected as the single agent guide (no `CLAUDE.md`);
  added `docs/MTGA_INSTALL_DISCOVERY.md`.

## 0.5.2

- **Fixed the Deck Finder button on Windows** flashing a console that instantly closed
  ("...is not recognized as an internal or external command"): cmd.exe cannot parse the
  backslash-escaped quotes Popen produces for argument lists, so the spaced exe path was split
  apart. The launcher now builds a single cmd /S /C line using cmd's own quoting rules.
  Double-clicking the exe always worked; only the menu-bar/dashboard launch was affected.

## 0.5.1

- **Fixed "Local Card DB: not found" on Windows** (cards showing as `Card #NNNN`): the tracker
  now reads Steam's `libraryfolders.vdf` and checks every configured Steam library on every
  drive (root located via Program Files and the registry), plus Epic Games install paths — on
  Windows and macOS. When the DB still can't be found, the startup banner explains the
  consequence and the `MTGA_DATA_DIR` override.
- **Fixed the packaged Deck Finder starting with "No providers found"**: its provider modules
  load dynamically, so PyInstaller never bundled them. The build now collects every submodule
  and the registry has a frozen-build fallback list guarded by a drift test.
- Windows path display now uses `%USERPROFILE%` instead of `~`, so locations in the startup
  banner paste straight into Explorer or cmd.
- The AI deck guess no longer prints a stray console line after "Ready for next game..." — it
  lands silently in the game record and shows on Game Detail.

## 0.5.0

- Bundled the **Deck Finder** (MTGA Deck Downloader) as a companion tool: launch it from the
  menu bar or the dashboard sidebar, browse creator decklists (Moxfield, AetherHub, TCGplayer,
  magic.gg, MTGO, Untapped) in a sized terminal window, and copy lists in Arena import format.
  Its dependencies install with the tracker; creator lists live in `deckfinder_config.json` at
  the project top level.
- Added **AI opponent-deck identification**: with an OpenAI, Anthropic, or Gemini key, one
  small background call after each completed game names the opponent's archetype by its
  dominant colors and strategy. Shown as the Opponent Deck Type on Game Detail (color label as
  fallback); it never blocks live tracking.
  Reasoning-class OpenAI models are asked for low effort and retried once on token-starved
  empty replies; failures now surface a real error via `scripts/test_deck_ai.py`.
- Added a **Settings… dialog** to the menu bar app for the AI provider, key, and model, plus a
  Deck AI status line in the tracker startup banner.
- Moved `settings.json` to the project top level next to `config.py` (installed builds keep it
  in the app data folder; the old `data/settings.json` migrates automatically) and anchored the
  `.gitignore` `config.py` pattern so the Deck Finder's config module is tracked.
- Fixed finished games being overwritten by the next game's data when Arena re-sent a match's
  final GameOver state after the summary reset.

## Unreleased

### Fable optimizations branch

- Overhauled the light theme with a warm off-white palette: distinct panel/surface/raised
  elevations in both themes, per-theme tint tokens, light-mode timeline chip colors, deeper
  accessible accents, `prefers-color-scheme` support with live OS-follow, and an inline pre-paint
  script that removes the dark flash for light-theme users.
- Added a numbered schema migration runner: migration 2 backfills `cards.arena_id` from submitted
  decklists (exact card-image lookups), migration 3 backfills `game_card_summary.drawn_count` and
  adds drawn-only summary rows, migration 4 creates `game_annotations`.
- Unified the two divergent draw-quality implementations into `draw_quality.py` with
  decklist-exact land rates; the CLI and dashboard now agree, and the dashboard reports the land
  rate source per game.
- Surfaced `game_participant_stats` end to end: dashboard Combat section with per-deck aggression
  profiles and wins-vs-losses splits, deck Combat Profile cards, per-game seat comparison, and a
  corrected `damage_taken` (externally inflicted life loss instead of duplicating `life_lost`).
- Added decklist-aware deck analytics: per-card composition with seen-vs-expected draws and
  win-rate-when-seen vs not-seen (dead-weight report), decklist version history with diffs, and
  Bo3 game-1 vs post-board records with most-boarded cards.
- Added repeat-draw multiplicity analysis on the card page (copies seen per game vs hypergeometric
  expectation, win rate by multiplicity) and Land Availability on curve (N lands by turn N) on the
  dashboard and deck pages, plus a draws-by-turn strip on the game page.
- Added Habits & Schedule (weekday/time-of-day win rates, session fatigue), Streaks & Outcomes
  (run lengths, outcome reasons, kept-opener land counts), rank season selection with historical
  seasons, limited-rank capture, and a minimum-sample floor for Best Deck.
- Added Opponent Meta: a cards-that-beat-you leaderboard and deck-vs-archetype matchup records;
  wired the previously orphaned `deck_llm` module so opt-in LLM archetype identification fills
  `participants.deck_archetype` at game end.
- UI/UX pass: custom date-range filters everywhere (including `/api/card` and `/api/opponent`,
  which previously ignored all filters), URL-synced shareable filters, pagination and CSV export
  on every table, sort persistence, chart hover tooltips with accessible table fallbacks and
  colorblind-safe life lines, stale-data banners with retry on detail pages, visibility-paused
  polling, restored focus outlines, skip-to-content, and a consolidated collapsible Section used
  on every page.
- Added per-game Notes & Tags backed by the dashboard's first write endpoint
  (`POST /api/game/annotation`), a DB Health page at `#/audit` surfacing `db_audit` findings, a
  global search covering cards, decks, and opponents, and a `/` keyboard shortcut for search.
- Added a validated `dashboard.port` setting in `data/settings.json` and stopped tracking live DB
  WAL/SHM files and local backups.

- Added an adaptive macOS menu-bar template icon, transparent app artwork, canonical icon generation, a native `MTGA Tracker` Dock identity, and explicit packaged-app launch guidance.
- Saved the deferred full-card hover preview design in `docs/CARD_HOVER_PREVIEW_PLAN.md`.
- Prevented the macOS menu-bar controller from opening a second overlapping copy of its menu.
- Prevent repeated turn-one state messages from creating duplicate timing rows, and coalesce duplicate timing segments defensively during persistence.
- Made SQLite analytics resilient to concurrent dashboard reads with WAL, busy waits, and bounded
  write retries; exact missing turn durations now recover from durable console headers at startup
  and through the database audit repair.
- Prevent optional analytics failures from removing completed games and recover missing Recent Games rows from local event and console history.
- Prevent source and packaged desktop launchers from running simultaneously; the packaged app supplies the native MTGA Tracker identity while source launches retain Python runtime metadata.
- Added user-editable `settings.json` sizing for the desktop live-log window and increased its default size to 1400 by 1020.
- Enlarged the desktop live-log window, enabled its colored event output by default, and made menu-bar icon clicks open only the menu instead of relaunching the dashboard.
- Fixed live event rows using the previous game's analytics ID, added timestamp-based historical event reassignment, and made DB repair remove empty unknown-result game artifacts.

### Dashboard UI

- Ranked Best Deck by confidence-adjusted win rate instead of raw win rate alone, and exposed the
  selected deck's win rate, record, and game count on the overview metric.
- Sorted Formats alphabetically by default and defensively removed Midweek Magic/Momir rows and
  filter options from stale dashboard responses.
- Added exact submitted deck snapshots, deck-membership-aware Card Performance that excludes
  temporarily controlled opponent cards, and one-click MTG Arena deck export on Deck Detail.
- Modernized the sidebar wordmark to match dashboard heading typography, made the full brand link
  to Overview, and replaced low-resolution mana pips with crisp local vector symbols.
- Made the `MTGA Tracker` logo reliably return to the very top of Overview and standardized
  browser titles as `MTGA Tracker – <page>`.
- Enlarged Card Drill-Down imagery and persistently loaded the full card through the same
  Scryfall image path used by card hover previews.
- Added lazy full-card hover and keyboard-focus previews to every card link, plus linked yellow Timeline brackets and compact inline card-type chips.
- Removed the obsolete analytics eyebrow from every page header, realigned titles with the header controls, and standardized `Performance Overview` title casing.
- Removed redundant turn-start event rows from the Game Detail Timeline because each turn header already shows the turn boundary and active player.
- Added links from validated card references in Game Detail Timeline events to Card Detail, with return-to-Timeline navigation.
- Changed Game Detail flood indicators from red danger styling to the existing blue draw-quality styling.
- Added game detail routes with life charts, opening hand, drawn cards, played cards, and filterable event timeline.
- Added card drill-down routes with card art, by-deck performance, and opening-hand impact.
- Added filter-aware deck routes, sidebar scrollspy, deck/card table search, match recap rows, session recap rows, and empty-dashboard setup guidance.
- Extended the local dashboard API with `/api/game`, `/api/card`, filtered `/api/deck`, match/session snapshot data, and larger deck/card result limits.
- Added global tracked-card search with usage-ranked autocomplete results and direct card detail navigation.
- Expanded card analytics to include player and opponent usage, with compact side-by-side and deck tables.
- Added per-game draw totals, land-draw percentage, and Flood detection for games above 50% land draws.
- Expanded Flood detection to include total-land probability, consecutive land streaks, and six-land eight-draw windows, with the triggering evidence shown in Game Detail.
- Preserved dashboard section context when opening a game so Back returns to the originating table and scroll position.
- Merged Draw Quality into Recent Games and moved Recent Games directly below Win Rate Trend in dashboard navigation.
- Reordered dashboard content so its top-to-bottom section sequence exactly matches sidebar navigation.
- Consolidated Play / Draw and Momentum into Overview and replaced intersection-based navigation highlighting with position-based scroll tracking.
- Added game length and average turn pace to Recent Games and deck history, plus sortable per-turn timing with player/opponent totals and live/estimated provenance in Game Detail.
- Moved individual turn durations from the Game Detail timing table into Timeline turn headers while retaining the timing summary metrics.
- Added top-right collapse controls to every Game Detail section.
- Added every identified opponent card to Game Detail with played, revealed-draw, discarded, milled, and exiled counts.
- Added linked opponent names to Game Detail with a sortable head-to-head game history for each Arena player.
- Clarified card drill-down analytics with your record and loss rate when the opponent actually played the card, excluding revealed-only appearances.
- Added current-season constructed rank tracking and a Bronze-to-Mythic progress chart shared by ranked Standard Best-of-1 and Best-of-3, including existing-log backfill.

### Desktop Launcher

- Added a unified tracker/dashboard launcher with automatic browser opening and free-port fallback.
- Added a macOS menu-bar controller with tracker status, start/stop controls, dashboard access, a bounded live tracker log, and clean coordinated shutdown.
- Added PyInstaller app-bundle and DMG build scripts with bundled frontend assets and per-user Application Support storage.
- Added original card-analytics app and menu-bar icons, corrected the native application display name, and made the Live Tracker Log window open automatically with the dashboard.
- Added matching ICO, PNG, and Apple touch favicons to the web dashboard.
- Fixed custom database selection so the tracker and dashboard always read and write the same SQLite file.

## v0.4.0 - Complete Game Tracking & Auto-Summary (2025-11-19)

### Major Features

**Starting Hand & Mulligan Tracking**
- ✅ Shows your opening hand with card names
- ✅ Detects mulligans automatically
- ✅ Counts number of mulligans
- ✅ Tracks hand size (7, 6, 5, etc.)
- ✅ Displayed at start and in game summary

**Combat Tracking**
- ⚔️ Attacker declarations with power/toughness
- 🛡️ Blocker declarations showing what blocks what
- 💢 Combat damage tracking
- 💥 Creature deaths in combat
- Shows which player's creatures

**Spell Targeting**
- ✅ Shows what card/permanent was targeted
- ✅ Shows ownership of target (your vs opponent's)
- ✅ Example: "Lightning Bolt targeting Tarmogoyf (opponent's)"
- Works with removal, auras, counters, etc.

**Game Timer**
- ⏱️  Tracks game duration from start to end
- Shows minutes and seconds
- Displayed in final summary

**Auto Game Detection**
- ✅ Detects game start automatically
- ✅ Detects game end automatically
- ✅ Shows summary when game ends (no manual stop needed)
- ✅ Resets state for next game
- ✅ Tracker runs continuously through multiple games

**Improved Life Tracking**
- ✅ Fixed: Now accurately tracks between turns
- ✅ Only announces actual changes (not initial values)
- ✅ Only shows changes after turn 1
- ✅ Shows current life after change

**Enhanced Game Summary**
- 🏁 Automatic at game end
- ⏱️  Game duration
- 🎴 Starting hand displayed
- 🎉/💀 Win/loss detection
- 📊 All cards played by both players
- Shows card counts

### Game Flow Example

```
🎮 GAME STARTED

🎴 Your Starting Hand (6 cards):
   (After 1 mulligan)
   • Lightning Bolt
   • Mountain x2
   • Goblin Guide
   ...

⚔️  Turn 1 - YOUR TURN

🎯 You cast Lightning Bolt targeting Tarmogoyf (opponent's)
💥 Tarmogoyf (opponent's) was destroyed

⚔️ You attacking with Goblin Guide (2/2)
🛡️ Opponent blocking with Wall (0/4)

🏁 GAME ENDED
⏱️  Game Duration: 8m 42s
🎉 You won!
```

### Files Added
- `docs/COMPLETE_GAME_TRACKING.md` - Complete feature documentation

### Files Modified
- `src/mtga_tracker/tracker.py` - Major expansion of tracking features
- All new tracking systems implemented

### Breaking Changes
None - fully backwards compatible

## v0.3.0 - Instant Detection & Interaction Tracking (2025-11-19)

### Major Improvements

**Instant Detection Fixed**
- ✅ Instants are now properly tracked
- ✅ Added support for "PlaySpell" category (in addition to "CastSpell")
- ✅ All spell types now detected reliably

**Interaction Tracking**
- ✅ Destruction effects show ownership: "Serra Angel (your) was destroyed"
- ✅ Multiple removal types tracked:
  - 💥 Destroy
  - 🚫 Exile
  - ⚰️ Sacrifice
  - 🗑️ Discard
  - 🚫 Counter
- ✅ Shows which player's card was affected

**Additional Game Events**
- ✅ Card draw tracking: `📥 You drew a card`
- ✅ Scry tracking: `🔮 You scried`
- ✅ Mill tracking: `🌊 You milled Brainstorm`
- ✅ Sacrifice tracking with ownership

**Debug Tools**
- ✅ debug_annotations.py - Analyzes all annotation categories in log
- ✅ Shows instant/sorcery detection
- ✅ Shows destruction/removal patterns
- ✅ Recommends which categories to track

### Files Added
- `debug_annotations.py` - Comprehensive annotation analyzer
- `docs/INTERACTION_EXAMPLES.md` - Examples of all tracked interactions

### Files Modified
- `src/mtga_tracker/tracker.py` - Expanded annotation processing
- `docs/EXAMPLE_OUTPUT.md` - Updated with new features

### Examples

**Before:**
```
🎯 You cast Lightning Bolt (Instant)
💥 Vampire Nighthawk was destroyed
```

**After:**
```
🎯 You cast Lightning Bolt (Instant)
💥 Vampire Nighthawk (opponent's) was destroyed
   Opponent lost 3 life (17)
```

**Now also tracks:**
```
👤 Opponent cast Thoughtseize (Sorcery)
🗑️ Force of Will (your) was discarded

🎯 You cast Opt (Instant)
🔮 You scried
📥 You drew a card
```

## v0.2.1 - Player Detection & Life Tracking Fixes (2025-11-19)

### Bug Fixes

**Player vs Opponent Detection**
- 🐛 Fixed: Player/opponent showing backwards
- ✅ Auto-detects player seat ID from log
- ✅ Scans matchGameRoomStateChangedEvent for seat assignments
- ✅ Shows detected seat on startup

**Life Total Tracking**
- 🐛 Fixed: Life totals not updating correctly
- ✅ Uses detected seat IDs for life mapping
- ✅ Prevents false announcements at game start
- ✅ Only announces changes after match begins

### Files Added
- `debug_seats.py` - Seat ID detection analyzer
- `docs/TROUBLESHOOTING.md` - Common issues and solutions

## v0.2.0 - Narrative Output & Card Name Resolution (2025-11-19)

### Major Improvements

**Card Name Resolution**
- ✅ Actual card names instead of IDs using Scryfall API
- ✅ Local caching to minimize API calls (stored in `data/card_cache.json`)
- ✅ Automatic card lookup on first encounter

**Game State Tracking**
- ✅ Life total tracking with change notifications
- ✅ Turn number and active player display
- ✅ Match start/end detection
- ✅ Clear turn boundaries with life totals

**Better Output**
- ✅ Narrative-style output that tells the story of the game
- ✅ Visual icons for quick identification (🎯 You, 👤 Opponent, 💥 Destroyed)
- ✅ Card type information (Creature 2/3, Instant, etc.)
- ✅ Event deduplication (no more duplicate announcements)
- ✅ Improved summary with card counts

**Code Architecture**
- ✅ New `CardDatabase` class for card name lookups
- ✅ `GameState` class to track match state
- ✅ Cleaner event processing with proper filtering
- ✅ Removed duplicate/noisy output

### Files Added
- `src/mtga_tracker/card_database.py` - Card name resolution
- `docs/EXAMPLE_OUTPUT.md` - Example of improved output
- `CHANGELOG.md` - This file

### Files Modified
- `src/mtga_tracker/tracker.py` - Complete rewrite of event handling
- `src/mtga_tracker/log_parser.py` - Improved JSON parsing (by user)

### Breaking Changes
None - backwards compatible

## v0.1.0 - Initial Release (2025-11-19)

### Features
- Basic log file monitoring
- Cross-platform support (macOS, Windows)
- Card ID tracking
- Console output
- Player vs opponent tracking
