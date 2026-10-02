## Tapps Tracker 0.6.4

**Backup, restore and merge.** Everything the tracker knows now fits in one file, so your history can survive a dead disk and follow you to another computer.

### Backup & restore

Open **Settings → Backup & restore**.

- **One file holds it all** — a consistent snapshot of your game database, `settings.json`, your Deck Finder creators and the overlay's preferences, zipped into a `.tappsbackup` (about 15 MB for a thousand games). **Include API keys** decides whether your Deck AI key travels with it.
- **Pick a backup folder.** The card offers the Google Drive, iCloud Drive, Dropbox and OneDrive folders it finds on your machine — choose one your sync client mirrors and the backup turns up on your other computer by itself. Nothing in the tracker talks to a cloud service, so a USB stick or an email works just as well. Nothing is created on disk until your first backup lands there.
- **Restore tells you what will change before it changes it** — *adds 7 games this computer does not have*, or *would drop 12 games recorded here*, which makes you type `REPLACE`. It pauses the tracker, saves a copy of the current state first (**Undo** puts it straight back), brings an older backup up to this version's database schema on the way in, and keeps this computer's own dashboard port, window size and backup folder.
- **Merge** is for playing on two computers: it adds a backup's games to the ones already here and removes nothing. Back up once more afterwards and one file holds everything. Merging the same backup twice adds nothing.
- **Every backup in the folder** is listed with its date, computer, game count, newest game and size, with **Open location**, **Restore**, **Merge** and a red **×** on each. Restore, merge and delete all ask first and name the file; the × deletes the backup file, never your database.
- From a terminal: `python -m mtga_tracker.backup export|inspect|restore|merge|delete|list|folders`.

**Travelling:** back up at home into the synced folder, restore on the laptop, play the week, back up there, then merge at home.

### Fixes

- **The Live Scoreboard's color pips never lit.** Colors were looked up under the timeline's display name (`Mountain (Land)`), which no card database matches, so both players' pips stayed blank all game — even though the archetype guess worked. Fixed; a basic land lights the pips on turn one again.

### Docs

- The README, Quick Start and reference guides were reconciled with what the app actually does, and the finished release and overlay plans were replaced by a [release guide](https://github.com/pattont/MTGA-Tapps/blob/main/docs/RELEASING.md) and an [overlay guide](https://github.com/pattont/MTGA-Tapps/blob/main/overlay/README.md).

### Installing

- **Windows:** run `MTGA-Tracker-0.6.4-setup.exe` (or unzip the `-windows.zip` into a *fresh* folder for a portable run). The build is unsigned, so SmartScreen will warn — *More info → Run anyway*.
- **macOS:** open the DMG and drag MTGA Tracker to Applications.
- Your tracked games and settings live outside the install folder and carry over. Upgrading is a good moment to take your first backup.
