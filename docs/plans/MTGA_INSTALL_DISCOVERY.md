# Remaining Arena install-discovery work

Status reviewed 2026-09-10: **log-derived discovery is implemented**. The
current resolver and troubleshooting instructions are documented in
[Finding Arena's card database](../MTGA_INSTALL_DISCOVERY.md). This plan
contains only the remaining work; it does not describe shipped settings.

## Settings override and validation

Add a user-facing log/card-folder override, coordinated with the
[Linux plan](linux_implementation.md), so there is one precedence contract
and one implementation in `paths.py` across platforms.

- Accept a raw database folder, `Raw_CardDatabase_*.mtga` file, install
  root, or macOS app bundle; normalize to a validated raw folder.
- Preserve explicit CLI/environment priority. Show an invalid saved path
  with a clear error instead of silently choosing a different install.
- Persist only deliberate user overrides; inferred paths must be re-resolved
  when Arena moves or downloads new data. Do not introduce a stale cache
  that defeats `CardDatabase`'s retry/recheck behavior.
- Show the resolved path and validation result in dashboard Settings. Those
  paths already appear there; the missing part is editing/validation.
- Apply path changes at the next tracker start. Do not restart live tracking
  automatically. Browser text input and any desktop file picker must use
  the same validation rules.

## Optional breadth, driven by failure evidence

The resolver already recognizes Windows localization-load headers, including
mixed separators and custom drive installs. Tests cover this signal; there
is no need to wait for a Windows Mono header to implement the remaining UI.

Only add these fallback tiers if logs/overrides still leave real failures:

- Windows Epic `.item` manifests with validated `InstallLocation`.
- Windows uninstall registry entries (both views and user/machine hives),
  handling missing `InstallLocation` and cautiously deriving from `DisplayIcon`.
- macOS unique case-insensitive component resolution and optional Spotlight
  discovery. Missing/disabled Spotlight must not break startup.

No recursive whole-disk search or network dependency for card resolution.
Ensure folder provenance survives file selection: the current card DB
loader sorts files from all candidate folders by mtime, so adding a fallback
must not cause an unrelated newer install to displace the selected one.
Linux prefix selection and Wine path translation belong to the Linux plan.

## Verification

Use temporary directories, fake registry/manifest/Spotlight results, and
short header fixtures. Cover all accepted input levels, invalid overrides,
permissions, stale paths, multiple installs, missing-then-downloaded DBs,
Steam libraries, and malformed manifests. Keep existing Windows/macOS tests
passing. Validate the real Settings interaction and run the Python and UI
checks from AGENTS.md when implemented.
