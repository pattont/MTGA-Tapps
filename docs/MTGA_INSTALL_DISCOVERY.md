# Finding Arena's Install (and its Card DB) Without a Launcher

Plan for locating `Raw_CardDatabase_*.mtga` when Arena was installed by the standalone
Wizards installer instead of Steam or Epic — including installs on a non-system drive.
Nothing here is implemented yet.

## The report

A user installed MTGA with the standalone installer from Wizards, on `G:\`. The tracker
printed `Local Card DB: not found`, so every card rendered as `Card #NNNN`. Their
`Player.log` was found fine — only the card database was missing.

That split is the whole problem, and it points at the fix.

## Why the log is found but the install is not

`Player.log` lives in the user profile, at a path that has nothing to do with where the
game was installed:

- Windows: `%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log`
- macOS: `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log`

The card database does not. On Windows it lives *inside the install*:

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

## The key idea: ask the log where the game is

Arena is a Unity game, and Unity writes its own install path into the first few lines of
`Player.log` at startup:

```
Mono path[0] = 'G:/MTGA/MTGA_Data/Managed'
Mono config path[0] = 'G:/MTGA/MTGA_Data/MonoBleedingEdge/etc'
```

If that holds, the install root is `Path(mono_path).parent.parent` — the parent of
`MTGA_Data` — and the raw folder is `<root>/MTGA_Data/Downloads/Raw`. That single signal
covers every case at once: any drive letter, any directory, standalone or Steam or Epic,
Windows or macOS, with no registry reads, no launcher-specific manifests, and no scanning.
It is also self-correcting — if the user moves or reinstalls the game, the next log says so.

We already read this file. We already know its path. We just aren't reading the top of it.

> **This must be confirmed against a real Player.log before it is built.** The evidence is
> circumstantial but strong: `log_sanitize.py` already scrubs `Renderer:`, `Vendor:`,
> `VRAM:`, and `Driver:` lines, which are the Unity graphics-init block that sits a few
> lines below `Mono path[0]` in a standard Unity player log. See
> [Verification](#verification-before-any-code) for how to confirm it.

## Proposed resolution order

Cheapest and most authoritative first. Stop at the first hit that actually contains a
`Raw_CardDatabase_*.mtga` file.

| # | Source | Platform | Cost | Notes |
|---|--------|----------|------|-------|
| 0 | Explicit override | both | free | `MTGA_DATA_DIR`, `--mtga-data-dir`, or `settings.json` |
| 1 | Cached resolved path | both | free | Re-validated; falls through if the folder vanished |
| 2 | `Player.log` Unity header | both | ~1 read | The primary fix |
| 3 | macOS Application Support | macOS | free | `com.wizards.mtga/Downloads/RAW` |
| 4 | Steam `libraryfolders.vdf` | both | cheap | Already implemented; keep |
| 5 | Epic manifests | Windows | cheap | Replaces the hardcoded Epic paths |
| 6 | Registry uninstall keys | Windows | cheap | Catches the standalone installer |
| 7 | Static default paths | both | free | Already implemented; keep as a backstop |
| 8 | Bounded drive sweep | Windows | expensive | **Opt-in only.** Never at startup |
| 9 | Ask the user | both | free | Folder picker; persists to `settings.json` |

Every tier stays a pure function returning candidate folders, so `get_mtga_raw_card_db_folders`
keeps its current shape and the caller keeps globbing for the newest DB file.

## Windows

### Tier 2 — the log header

Read the first ~40 lines of `Player.log` (and `Player-prev.log` as a fallback; Arena
truncates `Player.log` on each launch, so the header is at the top of the current file
unless the tracker attached to a partially-written one). Match `Mono path[0] = '<path>'`,
walk up from `MTGA_Data`, and confirm `MTGA_Data\Downloads\Raw` exists underneath.

Guard rails:

- Accept forward slashes; Unity writes POSIX-style separators even on Windows.
- Only trust a path whose `MTGA_Data\Downloads\Raw` exists. A stale header from a
  since-uninstalled drive should fail closed and fall through to the next tier.
- Never persist the raw header line — it contains the user's home directory on some layouts
  and `log_sanitize.scrub_raw_log` must keep applying to anything archived.

### Tier 5 — Epic manifests

Epic records real install locations as JSON, so this handles Epic-on-`G:` too:

```
C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item
```

Each `.item` is JSON with `InstallLocation` and `DisplayName`. Match the Arena entry and use
its `InstallLocation`. This strictly supersedes the two hardcoded
`...\Epic Games\MagicTheGathering\...` entries currently in the static list.

### Tier 6 — registry uninstall keys

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
build would otherwise see a mirrored view of the registry. Wrap the whole thing in the same
broad `except Exception` the existing `_windows_steam_roots()` uses — registry access fails
in enough odd ways that discovery must never be able to crash startup.

Also worth probing while we are in the registry: `HKCU\Software\Wizards Of The Coast\MTGA`,
the Unity PlayerPrefs key. It proves Arena has run but does **not** carry an install path, so
it is useful only as a diagnostic ("Arena is installed, we just can't find where").

### Tier 8 — bounded drive sweep, opt-in only

If everything above misses, we could probe fixed drives. This must never run automatically:
a recursive walk of a large `G:\` takes minutes, spins up sleeping disks, and looks like the
app has hung.

If we build it at all, bound it hard — enumerate fixed drives, then check a short list of
plausible roots per drive at depth ≤ 2:

```
<drive>\MTGA
<drive>\Games\MTGA
<drive>\Program Files\Wizards of the Coast\MTGA
<drive>\SteamLibrary\steamapps\common\MTGA
<drive>\Epic Games\MagicTheGathering
```

Skip removable and network drives. Run it from an explicit "Search my drives" button, with a
progress indication and a cancel — not from the startup path.

Honestly, tier 9 (just ask) beats this on every axis except pride. Build tier 9 first and
see whether anyone still needs tier 8.

## macOS — mostly already works

The standalone macOS install writes card data to
`~/Library/Application Support/com.wizards.mtga/Downloads/RAW/`, which the current code
already checks, so the reported failure should not reproduce there. Three cleanups are still
worth doing:

- **Glob case-insensitively.** The code hardcodes `Downloads/RAW` on macOS and
  `Downloads\Raw` on Windows. That works on a default case-insensitive APFS volume and
  breaks on a case-sensitive one. Resolve the child directory by case-folded comparison
  instead of assuming either spelling.
- **Add the app bundle as a fallback** for the case where card data really does live inside
  the bundle. Spotlight answers this in one call, including external volumes:

  ```bash
  mdfind "kMDItemCFBundleIdentifier == 'com.wizards.mtga'"
  ```

  With `/Applications/MTGA.app` and `~/Applications/MTGA.app` as static fallbacks in case
  Spotlight indexing is disabled. Inside a Unity `.app`, the data root is
  `Contents/Resources/Data`, not `MTGA_Data`, so the suffix differs from Windows — do not
  reuse `_MTGA_RAW_SUFFIX` blindly.
- **Relabel the "Epic" comment**, which describes the shared non-Steam path and misleads
  anyone reading `paths.py` for the standalone case.

## Failure UX — the part that actually matters

Discovery will still miss sometimes. Missing well is worth more than one more heuristic.

**Persist the answer.** Add an `mtga_data_dir` key to `settings.json` (alongside the existing
`deck_ai` section) so a resolved-or-chosen path is paid for once. Re-validate on load and
fall back to discovery if the folder disappeared. Cache the *folder*, never a specific
`Raw_CardDatabase_*.mtga` file — `card_database.py` deliberately re-globs because Arena
updates the DB while the tracker is running.

**Normalize forgivingly.** A folder picker invites picking the wrong level. Accept any of
these and resolve to the same place:

```
G:\MTGA
G:\MTGA\MTGA_Data
G:\MTGA\MTGA_Data\Downloads
G:\MTGA\MTGA_Data\Downloads\Raw
```

**Make the miss message actionable.** The banner in `tracker_runtime.py` currently names the
`MTGA_DATA_DIR` env var, which is the least discoverable option we offer. It should instead
say where we looked, and point at the picker:

```
 ⚠️  Local Card DB: not found — cards will appear as 'Card #NNNN'.
     Searched: Player.log install hint, Steam libraries, Epic manifests, registry,
               C:\Program Files\Wizards of the Coast\MTGA
     Fix: Settings… → Locate Arena, and pick your MTGA folder (the one containing
          MTGA_Data). Or set MTGA_DATA_DIR.
```

**Add "Locate Arena…" to the Settings dialog.** `settings_dialog.py` already writes
`settings.json`; this is one more row with a folder picker, a validation line, and a green
check when a `Raw_CardDatabase_*.mtga` is found. That is the whole feature for the long tail.

## Verification before any code

The log-header approach is the load-bearing assumption. Confirm it first — ideally from the
Discord reporter, since a standalone-on-`G:` install is exactly the case we cannot reproduce:

1. First 40 lines of their `Player.log`, scrubbed of anything personal — looking for
   `Mono path[0]`, and whether the path uses forward or back slashes.
2. `dir /b G:\<their install>\MTGA_Data\Downloads\Raw` — confirms the suffix is identical
   for standalone installs and that the DB file naming matches.
3. The default install directory the standalone installer proposes.
4. `reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f MTGA` —
   confirms whether an uninstall entry with `InstallLocation` exists.

If (1) comes back without a `Mono path` line, tiers 5, 6, and 9 carry the plan on their own
and the ordering above still holds; only the primary fix changes.

## Implementation phases

**Phase 1 — the fix.** Log-header derivation, the `mtga_data_dir` setting with forgiving
normalization, and the improved miss banner. Solves the reported case and most future ones.

**Phase 2 — Windows breadth.** Registry uninstall scan and Epic manifests; retire the
hardcoded Epic paths.

**Phase 3 — the escape hatch.** "Locate Arena…" in the Settings dialog.

**Phase 4 — only if still needed.** Opt-in bounded drive sweep.

**Phase 5 — macOS cleanups.** Case-insensitive resolution, `mdfind` fallback, comment fix.

Phases 1–3 are independent of each other and can land in any order.

## Testing

All of it must be testable on any OS, with no real registry, Spotlight, or Arena install.
`platform.system()`, `winreg`, and `subprocess` all get monkeypatched; every candidate root
is a `tmp_path` fixture.

- Unity header parsing: Windows-style and POSIX-style paths, a missing header, a header
  pointing at a since-deleted drive, and `Player-prev.log` fallback.
- Forgiving normalization: all four input levels above resolve to the same folder; a garbage
  path resolves to nothing rather than raising.
- Registry: a fake `winreg` module with an entry whose `InstallLocation` is empty, so the
  `DisplayIcon` derivation path is covered.
- Epic manifests: a `.item` fixture, plus a malformed one that must be skipped silently.
- Precedence: with several tiers matching at once, the earliest tier wins; with an explicit
  override set, nothing else is consulted.
- Regression: existing Steam `libraryfolders.vdf` behavior is unchanged.
- Discovery never raises. Every tier gets a failure-injection case asserting that startup
  still completes with `Local Card DB: not found` rather than a traceback.

## Non-goals

- Recursive whole-disk scanning at startup, under any circumstances.
- Fetching card data over the network when the local DB is missing. The existing Scryfall
  fallback is unchanged; the "no network dependency for normal card resolution" rule in
  `AGENTS.md` stands.
- Reading anything from the Arena install other than `Raw_CardDatabase_*.mtga`.
- Linux install discovery. Proton/Wine layouts are a separate question and nobody has asked.

## Open questions

- Does the standalone Windows installer ever write card data outside the install root — an
  `%LOCALAPPDATA%` path analogous to the macOS Application Support folder? If so, Windows
  gets a free tier-3 equivalent and most of this plan becomes optional.
- Does `Mono path[0]` survive Arena's own log rotation, or only appear on a cold start?
- Should the resolved path be shown in the dashboard as well as the console banner? Users
  who run the menu-bar app may never look at the startup output.
