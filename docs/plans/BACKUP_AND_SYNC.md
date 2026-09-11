# Backup, restore, and carrying your history between computers

Status: Phases 1 and 2 shipped 2026-09-11 (`src/mtga_tracker/backup.py`, `backup_api.py`, the Settings card: export, restore, merge, delete, open location); automatic backups and phase 3 open. Owner: Travis.

## The problem

Everything Tapps Tracker knows lives in one SQLite file plus three small
settings files, all on one computer. There is no way to get it onto another
computer, and no protection against losing it. The concrete scenario:

> I play at home on the desktop. I travel for a week with the laptop and want
> my decks, records, and settings there. When I get home I want the week's
> games back on the desktop, and the desktop to be the one true copy again.

Two needs hide inside that: a **backup** (a copy of everything, somewhere
that is not this disk) and a **hand-off** between two computers, in both
directions, without losing games recorded on either.

## The answer to "should this be Google Drive OAuth?"

Not first. The thing that makes the scenario work is a well-defined **backup
file** and a careful **import** — where the file travels is the easy part,
and Google Drive's desktop client (like iCloud, Dropbox, and OneDrive) already
carries any file in a folder to every computer that signs in. So:

1. **Phase 1 — a backup file, and a backup folder.** Export writes one
   `.tappsbackup` file; import reads one. The Settings page has a *Backup*
   card with a folder picker that offers the cloud-synced folders it finds on
   the machine (Google Drive, iCloud Drive, Dropbox, OneDrive). Exporting into
   `My Drive/Tapps Tracker/` on the desktop puts the file on the laptop's
   Drive folder with no code that talks to Google at all. This is the whole
   travel scenario, and it also works with a USB stick, AirDrop, or an email.
2. **Phase 2 — merge on import.** Import adds the games the file has that
   this computer lacks instead of replacing the database, so the order of
   hand-offs stops mattering and a game played on either machine is never
   lost. Phase 1 ships with *replace* plus a guard that refuses to silently
   discard local games; merge removes the guard's reason to exist.
3. **Phase 3 — Google Drive by API, if it earns its place.** OAuth
   (PKCE, loopback redirect), the `drive.file` scope, a Google Cloud project
   with a published consent screen, refresh tokens on disk, an upload with
   progress, and a *Sign in with Google* button on the Settings page. Worth it
   only for people without a desktop sync client — the Linux plan is the
   realistic case, since there is no Google Drive client for Linux — or if
   users ask for it after Phase 1. It is a destination for the same file, so
   nothing in phases 1–2 is thrown away.

Why the API is not first: it adds a Google Cloud project to maintain, an OAuth
consent screen that needs the site's privacy policy and a verification review
if the scope ever widens, an embedded client id in an open-source app, token
storage and refresh, quota and error handling, and an "unverified app" screen
until the consent screen is published — all to reproduce what Drive for
desktop does with a folder. The backup-file design has to exist either way.

## What a backup contains

One zip, extension `.tappsbackup`, named
`TappsTracker-<machine>-<YYYYMMDD-HHMMSS>.tappsbackup`:

| Entry | What | Notes |
| --- | --- | --- |
| `manifest.json` | format version, app version, schema version (`schema_migrations` max), machine name, an install id, export time (UTC), game count, newest game's start time, every game id (about 40 KB for a thousand games — what the preview's adds/drops count comes from), what is included | Enough to describe a backup in the UI without opening the database, and to detect "this file is older than what you have". |
| `tracker.sqlite3` | a consistent snapshot of the analytics database | Taken with SQLite's online backup API (`Connection.backup`) or `VACUUM INTO` — never a file copy, which the docs already forbid for a live WAL database. `raw_game_payloads` is dropped from the snapshot (a 30-day diagnostics buffer, nothing reads it back) and `live_status` is emptied. Roughly 115 MB → ~30 MB zipped for a thousand games; `console_logs` is the biggest table and stays, the Live Feed's history reads it. |
| `settings.json` | the app settings | Contains the Deck AI API key. The export dialog has *Include API keys* (default on — the point is a full restore — with the file marked private in the UI text). |
| `deckfinder_config.json` | Deck Finder creators | |
| `overlay.json` | overlay preferences | From the Tauri app-data dir (`com.tappstracker.overlay`); optional, skipped when absent. |
| `scryfall_id_cache.json` | Archidekt export id cache | Optional, small, saves a re-fetch. |

Not included: `logs/`, the unhandled-annotations log, the raw-payload archive,
`exports/`, and any `*.backup.*` files. Paths are not included: the import
side never trusts a path from the file.

The install id is generated once per data directory and lives in
`settings.json`, so a backup made on the same machine it is restored to is
recognised as such ("this is your own backup from Tuesday").

## Phase 1 — export and import

### Where it lives

*Settings → Backup* (a card above Deck AI):

- **Backup folder** — a text field and a row of quick picks
  for the synced folders found on this machine. Detection is a list of
  well-known paths, checked for existence:
  - Google Drive: `~/Library/CloudStorage/GoogleDrive-*/My Drive` (macOS),
    `%USERPROFILE%\My Drive` or a `G:\My Drive`-style mount (Windows; the
    drive letter is read from Drive's registry key when present);
  - iCloud Drive: `~/Library/Mobile Documents/com~apple~CloudDocs`;
  - Dropbox: `~/Dropbox` (or `info.json` under `~/.dropbox`);
  - OneDrive: `~/OneDrive` / `%OneDrive%`.
  The tracker appends a `Tapps Tracker` subfolder. Stored in `settings.json`
  as `backup.folder`; no folder means *Export* asks for a location each time.
- **Back up now** — writes the file, shows a progress line (snapshot → zip →
  done) and the result: file name, size, games, newest game. Errors are
  shown in the card, not a toast.
- **Backups in this folder** — a table of `.tappsbackup` files there, newest
  first: date, machine, games, newest game, size, and a *Restore…* button
  per row. Each row's facts come from the manifest, so listing is cheap.
- **Restore from file…** — the same flow for a file anywhere else.
- **Last backup** — "Tuesday 21:14 from this computer, 974 games" or
  "never", from `settings.json`.

The menu-bar / tray app gets *Back Up Now…* under the Deck Finder entry; it
just opens the Settings card.

### Restore flow (replace)

1. Read the manifest; refuse a format version this build does not know,
   and a *schema* version newer than this build's migrations ("update the
   tracker first").
2. Show a preview before anything happens: machine and time of the backup,
   its game count and newest game, this computer's game count and newest
   game, and the verdict line — *"This backup is newer than what is here"*,
   *"This backup is older: restoring would drop 12 games played since
   Tuesday"* (computed from game ids in the local database missing from the
   snapshot), or *"Same games"*. The dangerous case needs a typed `REPLACE`,
   the same way `/api/db/reset` needs `RESET`.
3. Stop the tracker (the menu app already knows how; a source run without
   the GUI is told to stop the tracker thread). The dashboard stays up.
4. Write a local safety backup of the current state first, always, into
   `data/backups/pre-restore-<time>.tappsbackup` (kept until the next
   restore; the card shows it with an *Undo restore* button).
5. Replace the database: unpack to a temp file, run
   `AnalyticsStore.apply_pending_migrations` on it (a backup from an older
   build comes forward the same way a start-up does), then swap it into
   place with the WAL/SHM files removed. Replace the settings files, except
   the values that belong to this machine: `backup.folder`, the install id,
   the dashboard port, and the Live Log window size are kept.
6. Restart the tracker. The card shows "Restored from … — 981 games".

### Endpoints and code

- `GET /api/backup` → the card's state: folder, detected folders, last
  backup, the listing.
- `POST /api/backup/export` `{folder?: string, include_keys: bool}` →
  writes the file, returns the manifest.
- `POST /api/backup/inspect` `{path}` → manifest plus the local comparison
  (the preview).
- `POST /api/backup/restore` `{path, confirm?: "REPLACE"}` → the restore.
- `POST /api/settings/backup` `{folder}`.
- A new module `src/mtga_tracker/backup.py` owns the file format, snapshot,
  detection and restore; `python -m mtga_tracker.backup export|inspect|restore`
  exposes the same for the terminal and for tests. The dashboard handler
  stays thin, like `db_audit` and `reset_database`.
- Stopping and restarting the tracker around a restore goes through the
  same request channel the overlay start/stop uses between the dashboard
  and the menu app.

### What Phase 1 does not do

Merge. If you play on the desktop while the laptop is away, or forget to
export before leaving, one side's games are behind — the guard makes that
loud and reversible (the pre-restore backup), not silent.

## Phase 2 — merge on import

Every game is recorded exactly once, on the computer whose `Player.log`
carried it, under an id built from that tracker session's start time and
match ordinal. Two computers therefore never produce the same game id, and
"merge" reduces to: **copy into the local database every game the backup
has that the local database does not, with everything that hangs off it.**
No conflict rules for games are needed. The preview becomes "adds 37 games
from the laptop (Sept 3–10); 12 games here stay".

Per table:

| Table(s) | Rule |
| --- | --- |
| `games`, `participants`, `matches`, `tracker_sessions` | insert where the id is absent; `matches.games_played` recomputed as the audit does |
| `game_*` (turns, events, card summary, deck cards, drawn cards, opening hands, mulligan hands, participant stats, library events, annotations), `participant_commanders`, `session_participant_stats` | copied for the games / sessions being added |
| `console_logs` | rows for the sessions being added |
| `cards` | insert missing names; on conflict keep the local row unless its `color_identity`/type columns are NULL and the incoming ones are not |
| `rank_snapshots`, `inventory_snapshots` | insert where the natural key (time + format / time) is absent |
| `live_status`, `raw_game_payloads`, `schema_migrations` | never merged |

Both databases are brought to the current schema before merging (the
snapshot is migrated in its temp file first). The merge runs inside one
transaction on the live file with the tracker stopped, exactly like a
replace, and `db_audit` runs afterwards in report mode so a bad merge is
visible immediately. The Phase 1 *replace* remains available as an explicit
choice ("make this computer identical to the backup").

## Automatic backups (cheap once Phase 1 exists)

A checkbox on the card: *Back up automatically after each session* (a
session ends when the tracker stops or Arena closes), into the backup
folder, keeping the newest 5 from this machine. This is the "protect
accumulated history" item from the last documentation review, and with a
synced folder chosen it is also the travel scenario with no button to
remember: leave home, the laptop's Drive already has last night's backup.

## Phase 3 — Google Drive by API (only if needed)

- OAuth 2.0 installed-app flow with PKCE and a loopback redirect on
  `127.0.0.1` (the dashboard's own server can receive it). Scope
  `drive.file` only — the app sees files it created, users see a normal
  *Tapps Tracker* folder in Drive. Non-sensitive scope: no verification
  review, but the consent screen must be published with tappstracker.com's
  privacy policy or every user sees the unverified-app warning.
- A Google Cloud project owned by the author; the client id ships in the
  app (installed-app client secrets are not secret by Google's own
  definition). The refresh token is stored in the data directory with
  file permissions restricted to the user; the keyring is optional.
- Upload with the resumable protocol so the card can show real progress;
  list/download use the same manifest facts (stored as file
  `appProperties`) so the *Backups* table is identical whether the source
  is a folder or Drive.
- Same file format, same import, same preview. Drive is a second row in
  the folder picker, "Google Drive (signed in as …)".

## Order of work and acceptance

1. `backup.py`: manifest, snapshot without `raw_game_payloads`, zip,
   inspect, restore-to-temp + migrate + swap; CLI; tests with a fixture
   database (export → restore round-trips every table except the excluded
   ones; a snapshot from schema v20 migrates on restore; a newer schema is
   refused; the "would drop N games" count is right).
2. Tracker stop/restart around a restore; the pre-restore safety file and
   *Undo restore*.
3. Dashboard endpoints and the Settings card, with the synced-folder
   detection (unit-tested against fake home directories on both
   platforms).
4. Docs: README *Data & privacy* gets a *Backups* paragraph; QUICKSTART gets
   the travel recipe in five lines; CHANGELOG.
5. Phase 2 merge, with its own fixture: two databases with overlapping and
   disjoint games merge to the union, twice (idempotent).
6. Automatic backups.
7. Phase 3 only on demand.

Done when: export on the desktop, import on the laptop, play, export on the
laptop, import on the desktop — and the desktop shows every game from both
weeks, with settings intact and no manual file handling beyond choosing the
folder once.

## Risks and open questions

- **Secrets in the file.** The Deck AI key rides along by default; the card
  says so and offers to leave it out. A backup in a shared folder is the
  user's call.
- **Restoring over a running tracker.** Handled by stopping it, never by
  swapping the file underneath an open connection.
- **Schema drift between machines.** A laptop on an older build restores a
  newer desktop's backup only after updating; the manifest carries the
  schema version so the message is exact.
- **Very large console logs.** `console_logs` is a third of the database;
  if backups get slow the Live Feed history could be capped at N sessions
  in the snapshot. Not needed at today's size.
- **Two trackers on one folder at once.** Two machines exporting into the
  same synced folder is fine (file names carry the machine); two machines
  *restoring* at the same moment is not a real case.
