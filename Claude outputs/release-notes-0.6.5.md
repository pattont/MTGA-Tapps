## Tapps Tracker 0.6.5

**A reliability release for startup, overlays, event names and game history.** Tapps is better at starting before your first queue, staying running, and preserving what Arena actually reported about each game.

### Startup controls

Open **Settings → Startup** for two independent options:

- **Start with Windows/macOS** launches Tapps Tracker in the system tray or menu bar when you sign in, so tracking is ready before you queue.
- **Open dashboard on launch** controls whether startup also opens the dashboard in your browser. Turn it off to start tracking quietly in the background.

You can now use **Start with Windows/macOS: On** and **Open dashboard on launch: Off** together.

Tapps also prevents a second tracker process from starting for the same user. A second manual launch tells you Tapps is already running; a duplicate login launch exits quietly. Deck Finder remains independently launchable from the running app.

### Event and game-history fixes

- **New Arena events no longer turn into Brawl.** Arena's queue/event identifier now outranks deck metadata and command-zone guesses. Unknown events keep a readable version of Arena's own name instead of being mislabeled.
- **Powered Cube is recognized correctly.** `CubeDraft_Powered_*` displays as **Powered Cube**, even when Arena exposes a populated command zone. Existing affected matches are repaired automatically.
- **Generic event names appear under Events.** Identifiers such as `Constructed_Event_2026` display as **Constructed Event**, appear in the **Events** filter in Recent Games and All Games, and repair older rows stored as Standard or Brawl.
- **Historical deck colors stay historical.** Recent Games, All Games and opponent history now use the submitted deck snapshot from that specific game. Editing or redrafting a deck no longer repaints older games with the newest deck's colors.

### Backup and restore

- Fixed a restore completing successfully but immediately reporting zero games. Restored databases are now finalized into a single-file state before the live database is replaced, so the first dashboard read sees the restored history correctly.

### Overlay and macOS reliability

- Fixed the overlay disappearing on newer macOS versions because a changed foreground-app response made Arena look permanently unfocused.
- Fixed Settings changing **In-game overlay** to off after an already-running overlay handled a second launch. Only **Quit overlay** now disables automatic overlay launches.
- Removed the unnecessary scrollbar from Overlay Settings when it opens beside the minimal rail.
- macOS app bundles now identify themselves as **Tapps Tracker** to the system and menu-bar managers while retaining the existing bundle identifier and filenames for upgrades.
- macOS builds now find Node installations managed by nvm when launched from a noninteractive shell.

### Installing

- **Windows:** run `MTGA-Tracker-0.6.5-setup.exe` (or extract the `-windows.zip` into a fresh folder for a portable installation). The build is unsigned, so SmartScreen may show *More info → Run anyway*.
- **macOS:** open the DMG and drag MTGA Tracker to Applications.
- Your games and settings live outside the application folder and carry over when upgrading.

**Full comparison:** https://github.com/pattont/MTGA-Tapps/compare/v0.6.4...v0.6.5
