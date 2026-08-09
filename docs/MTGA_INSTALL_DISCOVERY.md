# Finding Arena's Card Database

Plan for locating `Raw_CardDatabase_*.mtga` when Arena was installed by the standalone
Wizards installer instead of Steam or Epic — including installs on a non-system drive.

**Status: Phase 1 is implemented and verified against a real Player.log.**
`paths.mtga_raw_dir_from_player_log()` parses the Unity header and is threaded through
`CardDatabase`; the log-derived folder is checked before every platform guess. Phases 2–4
(Settings folder picker, registry/Epic-manifest fallbacks, macOS cleanups) remain open.

## Two different databases — do not confuse them

| | Our analytics DB | Arena's card DB |
|---|---|---|
| File | `mtga_tracker.sqlite3` | `Raw_CardDatabase_*.mtga` |
| Owner | Us | Wizards |
| Access | Read-write | **Read-only, always** |
| Purpose | Tracking games we observed | Card names, types, colors for gameplay |
| Location | `data/` from source; `%LOCALAPPDATA%\MTGA Tracker` (Windows) or `~/Library/Application Support/MTGA Tracker` (macOS) installed | Inside Arena's install on Windows; `~/Library/Application Support/com.wizards.mtga/Downloads/RAW` on macOS |
| Finding it | Solved. We choose the path | **The problem this document solves** |

Our SQLite database has nothing to do with this problem. We put it where we like, and
`paths.py` already handles that. Arena's card database is somebody else's file in somebody
else's directory, we only ever read it, and we cannot reliably find it. That is the entire
issue.

Nothing in this plan writes to Arena's install, ever.

## The report

A user installed MTGA with the standalone installer from Wizards, on `G:\`. The tracker
printed `Local Card DB: not found`, so every card rendered as `Card #NNNN`. Their
`Player.log` was found fine — only the card database was missing.

That split is the whole problem, and it points at the fix.

## Why the log is found but the card DB is not

`Player.log` lives in the user profile, at a path that has nothing to do with where the game
was installed:

- Windows: `%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log`
- macOS: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log`

Arena's card database does not. On Windows it lives *inside the install*:

```
<install root>\MTGA_Data\Downloads\Raw\Raw_CardDatabase_*.mtga
```

So `paths.get_mtga_raw_card_db_folders()` has to guess an install root, and today it guesses
from a fixed list: Steam libraries walked out of `libraryfolders.vdf`, plus six hardcoded
`C:\Program Files*` paths for Steam, Wizards, and Epic. A standalone install on `G:\MTGA`
matches none of them, and no amount of adding hardcoded paths ever will.

**macOS does not have this problem.** There, the standalone and Epic builds both keep
downloaded card data under a user-scoped, install-independent path:

```
~/Library/Application Support/com.wizards.mtga/Downloads/RAW/
```

`paths.py` already checks it (it is labelled "Epic" in the current code, but it is really
"anything that isn't the macOS Steam build"). A standalone macOS install on an external
volume still writes its card data to that same folder in the home directory. macOS needs
tidying and a fallback, not a rescue — see [macOS](#macos-mostly-already-works) below.

## The approach: ask Player.log where Arena is

Arena is a Unity game, and Unity writes its own install path into the first few lines of
`Player.log` at startup. **Verified against a real log** (macOS Steam build, Unity
2022.3.62f2): current Arena is an IL2CPP build and prints **no `Mono path[0]` line at
all** — the original draft's assumed marker does not exist anymore. What IS there, on line
4 of both `Player.log` and `Player-prev.log`, is the `[Subsystems]` line:

```
[Subsystems] Discovering subsystems at path <unity data dir>/UnitySubsystems
```

On Windows the Unity data dir is `<install>\MTGA_Data`, so the card DB folder is its own
`Downloads\Raw`. On the macOS Steam build the data dir is inside the app bundle
(`MTGA.app/Contents/Resources/Data`) while `MTGA_Data` sits next to the bundle — the
implementation walks up the ancestors and looks beside each one, which handles both shapes
with one rule. `Mono path[0]` is still matched as a secondary pattern for older builds.
This is the primary mechanism, not one heuristic among many, because it is the only signal
that is *authoritative* rather than a guess:

- **Arena itself reported it.** Every other tier infers a location from a launcher's
  bookkeeping or from where installers usually put things.
- **It covers every case at once** — any drive letter, any directory, standalone or Steam or
  Epic, Windows or macOS — with no registry reads, no launcher-specific manifests, and no
  scanning.
- **It self-corrects.** Move the game, reinstall it, switch drives, and the next log says so.
  A cached or hardcoded path silently goes stale; this one cannot.
- **It costs one read of a file we already have open.**

We already read this file. We already know its path. We just aren't reading the top of it.

> **Confirmed.** A real macOS Steam `Player.log` was inspected: the `[Subsystems]` line is
> present in the head of both `Player.log` and `Player-prev.log`, and the `Mono path[0]`
> line the first draft assumed is absent on current builds. Two answers for the record:
> the tracker always knows where `Player.log` is because Unity writes it to a fixed
> per-user location (LocalLow on Windows, `~/Library/Logs` on macOS) that is independent of
> the install drive — which is exactly why the log was found while the card DB was not. And
> `log_sanitize.py` does not interfere: it scrubs text we *archive*, not the raw file we
> *read* — discovery reads the raw head directly and never persists it.

## Resolution order

Three questions, in order. Stop at the first folder that actually contains a
`Raw_CardDatabase_*.mtga`.

**1. Do we already have it?**

| Source | Notes |
|---|---|
| `MTGA_DATA_DIR` env / `mtga_data_dir` argument | Existing behavior; an explicit override wins over everything |
| `mtga_data_dir` in `settings.json` | New. What the user picked, or what we resolved last time |

A stored path is re-validated on use. If the folder vanished — uninstall, moved drive — it
falls through instead of failing.

**2. Ask Player.log.** The Unity header above. This is where a standalone `G:\` install gets
found.

**3. Fall back, then ask.**

| Source | Platform | Notes |
|---|---|---|
| macOS Application Support | macOS | `com.wizards.mtga/Downloads/RAW`; already implemented |
| Steam `libraryfolders.vdf` | both | Already implemented; keep |
| Epic manifests | Windows | Replaces the hardcoded Epic paths |
| Registry uninstall keys | Windows | Catches a standalone install with no usable log |
| Static default paths | both | Already implemented; cheap backstop |
| Ask the user | both | Folder picker; the answer persists to `settings.json` |

The fallbacks matter less than they did in the previous draft of this plan. They exist for
the case where the log header is missing or stale — not as the main event. If verification
shows the header is reliable, the Windows-specific tiers (registry, Epic manifests) become
optional polish rather than required work.

## Implementation

The integration points already exist, which is most of why this is cheap.

`CardDatabase.__init__` already accepts `log_path` and stores it as `self.log_path` — it is
passed in for card-name extraction. But `_find_mtga_card_database_paths()` calls:

```python
get_mtga_raw_card_db_folders(self._mtga_data_dir)
```

and drops the log on the floor. The change is to thread it through:

```python
get_mtga_raw_card_db_folders(self._mtga_data_dir, log_path=self.log_path)
```

with a new helper in `paths.py` — all path logic belongs there, per `AGENTS.md`:

```python
def mtga_raw_dir_from_player_log(log_path) -> Optional[Path]:
    """Derive Arena's card-DB folder from the Unity header at the top of Player.log."""
```

It reads the first ~40 lines, matches `Mono path[0] = '<path>'`, walks up from `MTGA_Data`,
and returns `<root>/MTGA_Data/Downloads/Raw` only if that directory exists. Then
`get_mtga_raw_card_db_folders` inserts the result immediately after the override checks and
before the Steam walk.

Guard rails:

- **Accept forward slashes.** Unity writes POSIX-style separators even on Windows.
- **Fail closed.** Only return a path whose `Downloads/Raw` exists. A stale header pointing
  at a since-removed drive must fall through, not poison the result.
- **Never raise.** A missing, unreadable, or truncated log returns `None`. Card-DB discovery
  must never be able to crash startup.
- **Read `Player-prev.log` as a fallback.** Arena truncates `Player.log` on each launch, so
  the header is normally at the top of the current file — but if the tracker attached to a
  partially-written one, the previous log has the same install path.
- **Do not persist the raw header line.** It can contain the user's home directory;
  `log_sanitize.scrub_raw_log` must keep applying to anything archived.

### Caching, without breaking re-resolution

`_resolve_mtga_db_path()` deliberately re-resolves after a miss, because Arena can download
or update `Raw_CardDatabase_*.mtga` while the tracker is running. Caching must not defeat
that.

So: cache the **folder**, never a specific DB file. The resolved folder can go into
`settings.json` as `mtga_data_dir` so the derivation is paid for once, while
`_find_mtga_card_database_paths()` keeps globbing that folder for the newest file on every
resolve. Existing behavior is unchanged; it just starts from a folder we know.

### Normalize forgivingly

A stored or user-picked path invites picking the wrong level. Accept any of these and
resolve to the same place:

```
G:\MTGA
G:\MTGA\MTGA_Data
G:\MTGA\MTGA_Data\Downloads
G:\MTGA\MTGA_Data\Downloads\Raw
```

## Windows fallbacks

Only needed if verification shows the log header is unreliable, or for users whose log
predates a move.

### Epic manifests

Epic records real install locations as JSON, so this handles Epic-on-`G:` too:

```
C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item
```

Each `.item` is JSON with `InstallLocation` and `DisplayName`. Match the Arena entry and use
its `InstallLocation`. This strictly supersedes the two hardcoded
`...\Epic Games\MagicTheGathering\...` entries in the current static list.

### Registry uninstall keys

The standalone installer registers an uninstall entry. Enumerate subkeys of:

```
HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall
HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
```

Match `DisplayName` against MTGA / "Magic: The Gathering Arena", or `Publisher` against
Wizards of the Coast, then read `InstallLocation`. If that value is empty — installers often
leave it blank — derive the directory from `DisplayIcon` or `UninstallString` instead.

Open keys with an explicit WOW64 view (`KEY_READ | KEY_WOW64_64KEY`, then the `32KEY`
variant) rather than relying on the bitness of whichever Python is running; a frozen 32-bit
build would otherwise see a mirrored view of the registry. Wrap it in the same broad
`except Exception` that `_windows_steam_roots()` already uses.

`HKCU\Software\Wizards Of The Coast\MTGA` (Unity PlayerPrefs) is worth probing as a
diagnostic only — it proves Arena has run but carries no install path, so it can distinguish
"Arena isn't installed" from "Arena is installed and we can't find it".

### Drive scanning — deliberately not doing this

A recursive walk of a large `G:\` takes minutes, spins up sleeping disks, and looks like the
app has hung. It can never run at startup.

If the log header, the launcher tiers, and a folder picker all fail, the honest answer is to
ask the user, not to search their computer. Should it ever prove necessary, bound it hard —
fixed drives only, a short list of plausible roots per drive at depth ≤ 2, behind an explicit
"Search my drives" button with progress and cancel. It stays out of scope here.

## macOS — mostly already works

The standalone macOS install writes card data to
`~/Library/Application Support/com.wizards.mtga/Downloads/RAW/`, which the current code
already checks, so the reported failure should not reproduce there. Three cleanups are still
worth doing:

- **Glob case-insensitively.** The code hardcodes `Downloads/RAW` on macOS and
  `Downloads\Raw` on Windows. That works on a default case-insensitive APFS volume and
  breaks on a case-sensitive one. Resolve the child directory by case-folded comparison
  instead of assuming either spelling.
- **Add the app bundle as a fallback**, for the case where card data really does live inside
  the bundle. Spotlight answers this in one call, including external volumes:

  ```bash
  mdfind "kMDItemCFBundleIdentifier == 'com.wizards.mtga'"
  ```

  With `/Applications/MTGA.app` and `~/Applications/MTGA.app` as static fallbacks in case
  Spotlight indexing is disabled. Inside a Unity `.app`, the data root is
  `Contents/Resources/Data`, not `MTGA_Data`, so the suffix differs from Windows — do not
  reuse `_MTGA_RAW_SUFFIX` blindly. The same caveat applies to the log-derived path on macOS.
- **Relabel the "Epic" comment**, which describes the shared non-Steam path and misleads
  anyone reading `paths.py` for the standalone case.

## Failure UX

Discovery will still miss sometimes. Missing well is worth more than one more heuristic.

**Make the miss message actionable.** The banner in `tracker_runtime.py` currently names the
`MTGA_DATA_DIR` env var, which is the least discoverable option we offer. It should say
where we looked and point at the picker:

```
 ⚠️  Local Card DB: not found — cards will appear as 'Card #NNNN'.
     Searched: Player.log install hint, Steam libraries, Epic manifests, registry,
               C:\Program Files\Wizards of the Coast\MTGA
     Fix: Settings… → Locate Arena, and pick your MTGA folder (the one containing
          MTGA_Data). Or set MTGA_DATA_DIR.
```

**Add "Locate Arena…" to the Settings dialog.** `settings_dialog.py` already writes
`settings.json`; this is one more row with a folder picker, forgiving normalization, and a
green check when a `Raw_CardDatabase_*.mtga` is found. That is the whole feature for the
long tail.

## Verification — done for macOS, one ask left for Windows

Confirmed against a real macOS Steam log: the `[Subsystems]` header exists in both
`Player.log` and `Player-prev.log`, no `Mono path[0]` on current builds (the implementation
matches both patterns and both slash directions anyway).

Still worth collecting from the Discord reporter, since standalone-on-`G:` is the case we
cannot reproduce:

1. The first ~10 lines of their `Player.log` — confirms the `[Subsystems]` line appears on
   Windows standalone builds too, and its exact path shape.
2. `reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f MTGA` — tells
   us how much the Phase 3 registry fallback is worth.

If their log head somehow lacks the line, the Phase 3 fallbacks (registry, Epic manifests)
get promoted; nothing else in this document changes.

## Phases

**Phase 1 — the fix. (DONE)** `mtga_raw_dir_from_player_log()` in `paths.py`, threaded
through `CardDatabase`, with `Player-prev.log` fallback, both header patterns, both slash
directions, ancestor-walk resolution for the Windows and macOS install shapes, and
fail-closed/never-raise guarantees — all under test. Solves the reported case. The
`mtga_data_dir` settings.json cache and forgiving normalization move to Phase 2 with the
picker, since the log read is cheap enough to run every resolve.

**Phase 2 — the escape hatch.** "Locate Arena…" in the Settings dialog.

**Phase 3 — Windows breadth, if still needed.** Registry uninstall scan and Epic manifests;
retire the hardcoded Epic paths.

**Phase 4 — macOS cleanups.** Case-insensitive resolution, `mdfind` fallback, comment fix.

Phases 1 and 2 are independent and can land in either order.

## Testing

All of it must be testable on any OS, with no real registry, Spotlight, or Arena install.
`platform.system()`, `winreg`, and `subprocess` all get monkeypatched; every candidate root
is a `tmp_path` fixture, and Player.log headers are short string fixtures.

- Unity header parsing: Windows-style and POSIX-style paths, a missing header, a header
  pointing at a since-deleted drive, a truncated file, and `Player-prev.log` fallback.
- Precedence: an explicit override beats the log; the log beats the Steam walk; a stored
  `mtga_data_dir` that no longer exists falls through rather than winning.
- Forgiving normalization: all four input levels above resolve to the same folder; a garbage
  path resolves to nothing rather than raising.
- Re-resolution still works: after a miss, a `Raw_CardDatabase_*.mtga` appearing mid-session
  is picked up — the folder cache must not defeat `_resolve_mtga_db_path`'s retry.
- Registry: a fake `winreg` with an entry whose `InstallLocation` is empty, covering the
  `DisplayIcon` derivation path.
- Epic manifests: an `.item` fixture, plus a malformed one that must be skipped silently.
- Regression: existing Steam `libraryfolders.vdf` behavior is unchanged.
- Discovery never raises. Every tier gets a failure-injection case asserting that startup
  still completes with `Local Card DB: not found` rather than a traceback.

## Non-goals

- Writing anything to Arena's install, or reading anything from it other than
  `Raw_CardDatabase_*.mtga`.
- Recursive whole-disk scanning at startup, under any circumstances.
- Fetching card data over the network when the local DB is missing. The existing Scryfall
  fallback is unchanged; the "no network dependency for normal card resolution" rule in
  `AGENTS.md` stands.
- Anything touching our own analytics database. It is unrelated to this problem.
- Linux install discovery. Proton/Wine layouts are a separate question and nobody has asked.

## Open questions

- Does `Mono path[0]` survive Arena's own log rotation, or only appear on a cold start? This
  is question 3 in [Verification](#verification-gates-the-work) and decides how much the
  fallback tiers are worth.
- Should the resolved path be shown in the dashboard as well as the console banner? Users who
  run the menu-bar app may never look at the startup output.
