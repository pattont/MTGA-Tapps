# Finding Arena's card database

Current behavior is implemented in [`paths.py`](../src/mtga_tracker/paths.py)
and [`card_database.py`](../src/mtga_tracker/card_database.py), with regression
coverage in `tests/test_paths.py` and `tests/test_card_database.py`.

Arena's `Raw_CardDatabase_*.mtga` supplies card names, types, rules text,
colors, and mana costs. It is separate from the tracker's analytics SQLite
database. A missing Arena card DB does not mean game history is missing.

## Resolution

`get_mtga_raw_card_db_folders()` returns candidate folders:

1. An explicit `CardDatabase(mtga_data_dir=...)` argument, then the
   `MTGA_DATA_DIR` environment variable. Either override is exclusive:
   an invalid folder returns no candidates rather than falling through.
2. Arena's install path from the first 64 KiB of `Player.log`, falling back
   to `Player-prev.log` if necessary. Recognized Unity header lines include
   `Discovering subsystems at path`, `Loading SqlLocalizationManager from
   file`, and the older `Mono path[0]` form. Mixed slash directions are
   normalized. An ancestor walk finds `MTGA_Data/Downloads/Raw` beside the
   macOS app or under the Windows install.
3. Platform defaults: Steam libraries from `libraryfolders.vdf`, macOS
   `com.wizards.mtga/Downloads/RAW`, and Windows Steam/Wizards/Epic default
   install paths. Windows Steam roots also use Steam's registry entry.

`CardDatabase` gathers matching `.mtga` files from these folders and selects
the newest by modification time. **Folder order is not strict database
priority** once multiple folders yield databases. Files ending in
`.mtga.dat` are excluded. The selected database is opened read-only.

The resolver retries after a miss or a vanished database. At game end it
also arms a one-time search for a newer database on the next unknown-card
lookup, covering Arena downloading a set update while the tracker runs.
Normal card-name lookup uses the session cache and local Arena database;
an unresolved ID renders as `Card #<id>` without a network lookup.

## Troubleshooting

The startup banner and dashboard **Settings → Tracker** show the monitored
log, local card DB, and analytics DB paths. Home paths are redacted to `~`
or `%USERPROFILE%`. If the card DB is missing:

- Run Arena so it can finish downloading card data.
- Confirm the tracker is reading the intended `Player.log`; both launchers
  accept `--log-path`.
- For a custom card-data location, set `MTGA_DATA_DIR` to the folder that
  actually contains `Raw_CardDatabase_*.mtga`, not the game executable or
  the tracker's `data/` folder, before launching the tracker.

```bash
MTGA_DATA_DIR="/path/to/MTGA_Data/Downloads/Raw" venv/bin/python -m mtga_tracker.app
```

```powershell
$env:MTGA_DATA_DIR = 'D:\Games\MTGA\MTGA_Data\Downloads\Raw'
venv\Scripts\python -m mtga_tracker.app
```

Apply launch-time overrides at the next safe launch; do not interrupt a
live game. The Settings path display is informational and is not a folder
picker. There is no general Epic-manifest/uninstall-registry scan or
Proton/Wine prefix auto-discovery in the current resolver.
