# 03 — Auto-update: how it plugs into the Tapps Tracker codebase

Scope: in-repo integration only. The per-OS swap/relaunch (`install_and_restart()`) and the
industry survey are covered by other reports; here they are a black box with a defined
contract. All references are to the `auto-update` branch at `7071c74`
(the repository root). No repo files were modified.

---

## 0. Findings that change the brief

1. **The launcher class is `UnifiedLauncher`, not `TrackerApplication`**
   (`src/mtga_tracker/app.py:51`). It already exposes everything the hand-off needs:
   `start_dashboard` (93-123), `stop_tracker` (204-213, which calls
   `mark_live_status_stopped` via `_mark_tracker_stopped` 192-202), `stop_dashboard` (215-226),
   and `shutdown` (228-230). It is also passed to the dashboard as `tracker_control`
   (`dashboard.py:6799-6825`). Backup restore already uses it to pause tracking
   (`backup.py:713-760`).
2. **There are two single-instance locks, not one.** `SingleInstanceGuard`
   (`single_instance.py:23-114`, acquired at `app.py:283-309`, released in `finally` at
   `app.py:324-325`) **and** the legacy Qt `QLockFile` (`menu_app.py:120-131`, held for
   the event loop at `menu_app.py:593-607`). A relaunched process started before the old one
   has fully exited hits "already running" and exits (`app.py:296-309`) or shows the
   "wait a few seconds" box (`menu_app.py:594-605`). So `--after-update` must **wait and
   retry** both locks, not just parse a flag (see §5).
3. **A tracker restart drops the log gap.** `tracker_runtime.py:116-117` starts from the
   current end of `Player.log` (`self.parser.reset_position()`), then checks for a mid-game
   attach. Any match that starts during the restart is a mid-game attach and is never
   persisted (AGENTS "mid_game_attach gates `_is_untracked_match`"). A deck submission
   (`EventSetDeckV3`) sent during the gap is also lost, which weakens deck attribution. So
   **unattended auto-install must require Arena to not be running**, not only `in_game = 0`
   (§4).
4. **`live_status.in_game` is not a match-level flag.** It is
   `in_match and game_start_time and not match_complete` (`tracker_analytics.py:150`), and
   it is only written with console lines/snapshots. The heartbeat (`analytics.py:3233-3248`)
   bumps `updated_at` only. It can read 0 between Bo3 games. Hence the ">= 2 min idle" rule
   plus the Arena-process check.
5. **The upcoming release carries four new migrations.** v0.6.5.3 stops at migration 31
   (`git show v0.6.5.3:src/mtga_tracker/analytics.py`). Unreleased adds 32 (an index rebuild
   over `game_events`, `analytics.py:1419-1430`) and 33/34/35 (the Deck Manager tables,
   `analytics.py:733-736`). It also adds four `ensure_table_column` calls on `game_events`
   for replay capture (`analytics.py:566-576`). The first auto-updated hop will run all of
   them, so the pre-update snapshot (§6) is not optional.
6. **The updater cannot reach existing installs.** 0.6.5.3 users still poll
   `api.github.com` from the browser (`ui/src/updateCheck.ts:3`). They must install the first
   updater-capable release by hand. Keep the GitHub release page and `releases/latest`
   semantics stable so their "Update vX available →" link keeps working.
7. **The settings writers are not uniform.** `settings._write_document` is atomic
   (`settings.py:105-116`). `backup.write_settings_document` is a plain `write_text`
   (`backup.py:93-97`), and `backup.update_settings_section` is read-modify-write without a
   lock (`backup.py:100-110`). If a 6-hourly background thread rewrote `last_check` in
   `settings.json`, it could race a user's Settings save and drop it. **Recommendation: keep
   the user preferences in `settings.json` under `updates`, and keep runtime state
   (`last_check`, ETag, last error, download journal) in `DATA_DIR/updates/state.json`.**
   §2 gives both shapes.
8. **The existing `/api/settings` POST path has no Origin or Content-Type guard.** Only the
   Deck Manager branch has one (`dashboard.py:5880-5893`). Because `install` restarts the
   app, the new `/api/update/*` POSTs must use the Deck Manager style guard.
9. **The `tasklist` helpers lack `CREATE_NO_WINDOW`.** The Arena PID helpers in
   `collection_export.py:263-302` (`_find_pid_macos` / `_find_pid_windows`) do not pass it.
   A periodic Arena probe from the frozen GUI would flash a console window on every poll
   (AGENTS "Background Windows subprocesses ... must use `CREATE_NO_WINDOW`"). Reuse
   `overlay_launcher._detached_kwargs()` (`overlay_launcher.py:491-497`) in a new shared
   probe.

---

## 1. Replace the browser GitHub poll with `GET /api/update`

### What exists

- `ui/src/updateCheck.ts:1-69` calls `https://api.github.com/repos/pattont/MTGA-Tapps/releases/latest`
  from the browser once a day. It caches in localStorage (`mtga-update-check`) and compares
  only the `X.Y.Z` triplet (`versionTriplet`, 13-19). As a result `0.6.5.3` vs `0.6.5.4`
  compare equal, and `0.6.3rc8` counts as `0.6.3`. **This is a real bug today:** four-part
  hotfix tags are never offered.
- `AppShell.tsx:48` imports it. The effect at `AppShell.tsx:219-243` fetches `/api/version`
  once, then calls `checkForUpdate` in PROD builds only.
- Render: the expanded footer `<div className="sidebar-bottom">` (`AppShell.tsx:459-495`)
  shows `<a className="sidebar-update" href={update.url} target="_blank">Update {tag} available →</a>`
  first, then the Replay / Deck Finder / Deck Manager launchers, then `<span className="sidebar-version">v{version}</span>`.
  The collapsed footer `sidebar-bottom sidebar-bottom-mini` (`AppShell.tsx:435-457`) has only
  the three icon launchers: **no version and no update affordance**.
- CSS: `.sidebar-update` pill (`ui/src/styles.css:3616-3638`), `.sidebar-bottom`
  (`styles.css:4051-4062`), `.sidebar-bottom-mini` (`styles.css:4151-4157`).
- Poll cadence in the shell: tracker state via `fetch('/api/live?status=1')` every
  **10 s**, skipped while `document.hidden` (`AppShell.tsx:186-217`). Pages poll at 20 s
  (`App.tsx:186 SNAPSHOT_REFRESH_MS`, the detail pages), the Live page at 500 ms
  (`LiveLogPage.tsx:22`), and Deck Finder jobs at 700 ms (`DeckFinderPage.tsx:25`).
- `/api/version` is served at `dashboard.py:6333-6343` with `Cache-Control: no-store`.
- No toast component exists in `ui/src` (grep for "toast" finds nothing).

### Proposal

- Delete `ui/src/updateCheck.ts`. Add `ui/src/updateStatus.ts`, which holds the types, the
  `fetchUpdateStatus`, `postUpdateAction`, and `saveUpdateSettings` helpers (or put these in
  `ui/src/api.ts` next to `saveStartupSettings` at `api.ts:1992-2002`, reusing
  `deckFinderJson` at `api.ts:1481-1495`). It also holds a pure `updatePillModel(status)`
  for testable presentation logic.
- Add `ui/src/components/UpdateIndicator.tsx` (`collapsed: boolean` prop) and a
  `useUpdateStatus()` hook. Polling cadence:
  - **15 s** while idle/available/ready, with the same `document.hidden` skip as the tracker
    dot (`AppShell.tsx:208-212`). The endpoint is in-memory, so it is cheap.
  - **1 s** while `downloading` or `installing`, so the progress bar moves.
  - While `installing`, also poll `/api/version` every 2 s. When the version differs from the
    one first seen, call `window.location.reload()`. `index.html` revalidates by
    Last-Modified and assets are content-hashed and immutable (AGENTS dashboard note), so a
    reload loads the new UI. If the port changed (8765 busy, so it fell back to port 0,
    `app.py:108-113`), the tab cannot recover. The tray notification covers that case (§5).
- AppShell changes:
  - Remove the import (48), the `update` state (183), and the `checkForUpdate` branch
    (226-233). Keep the `/api/version` fetch for the `v{version}` label.
  - Expanded footer: replace the `{update ? <a className="sidebar-update"…> : null}` block
    (461-471) with `<UpdateIndicator collapsed={false} />`. It stays the first child of
    `.sidebar-bottom`, which is the bottom-left slot the brief asks for.
  - Collapsed footer: insert `<UpdateIndicator collapsed />` as the first child of
    `.sidebar-bottom-mini` (436). It renders a 32 px icon button using lucide `ArrowUpCircle`
    or `Download`, plus an SVG progress ring while downloading. It is hidden unless the state
    is `available`, `downloading`, `ready`, `installing`, or `error`. It carries
    `aria-label`/`title` text such as "Restart to update to v0.6.6".
- Pill states (`updatePillModel`):

| backend `state` | expanded pill | action |
| --- | --- | --- |
| `available` (`can_install`) | "Update v0.6.6 available" | POST `/api/update/download` (or no-op when auto-download is already running) |
| `available` (`!can_install`: source/portable/unsupported) | "Update v0.6.6 available →" | link to `notes_url` (today's behavior) |
| `downloading` | "Downloading v0.6.6 — 42%" + `<progress>` | none (title shows bytes) |
| `ready` | **"Restart to update"** (accent) | POST `/api/update/install`. On 409 `game-in-progress`, show "Finish your game first" with an "Install after this game" choice (`{"when": "idle"}`) |
| `installing` | "Restarting…" (spinner) | none |
| `error` | "Update failed — retry" | POST `/api/update/check` |
| `up_to_date`, `idle`, `checking`, `disabled`, `unsupported` | nothing (version label only) | — |

- "Just updated" notice: when `just_updated` is present in the payload, render a dismissible
  line above the version label: "Updated to v0.6.6 · What's new". It links to `notes_url`,
  and dismissing calls POST `/api/update/acknowledge`. Acknowledgement is stored server-side,
  so it shows once per install and not once per browser.

### `GET /api/update` payload

```json
{
  "state": "ready",
  "current_version": "0.6.5.3",
  "latest_version": "0.6.6",
  "notes_url": "https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.6",
  "released_at": "2026-10-20T18:00:00Z",
  "mandatory": false,
  "below_minimum": false,
  "install_kind": "macos-app",
  "can_install": true,
  "reason": null,
  "progress": {"received": 48234496, "total": 114849792, "fraction": 0.42},
  "error": null,
  "last_check": "2026-10-11T14:02:11Z",
  "skipped": false,
  "auto_install": false,
  "pending_install": false,
  "blocked_by": ["game-in-progress"],
  "just_updated": null
}
```

Field notes:

- `state` is one of `idle | checking | up_to_date | available | downloading | ready | installing | error | disabled | unsupported`.
- `install_kind` is one of `macos-app | windows-installer | windows-portable | source | linux | unknown`.
- `reason` is non-null only when `can_install` is false: `"source"`, `"portable"`,
  `"dashboard-only"`, `"unsupported-platform"`, or `"unknown-version"`.
- `progress` is non-null only while downloading.
- `error`, when set, has the shape `{"code": "sha256-mismatch", "message": "…"}`.
- `pending_install` is true when the user chose "install after this game".
- `blocked_by` lists what currently prevents an install. Values: `game-in-progress`,
  `arena-running`, `deck-transfer`, `collection-export`, `backup-restore`.
- `just_updated`, when set, has the shape
  `{"from": "0.6.5.3", "to": "0.6.6", "notes_url": "…", "ok": true}`.

---

## 2. Settings plumbing

### What exists

- `settings.py`:
  - Path: frozen builds use `DATA_DIR/settings.json`; source runs use the repo top level
    (`settings.py:21-27`).
  - Default document has the `live_log_window`, `dashboard`, and `startup` sections
    (`71-84`).
  - Frozen `AppSettings` dataclass (`60-68`).
  - Validators `_bounded_dimension`/`_boolean` (`87-94`).
  - Tolerant `_read_document` (`97-102`) and atomic `_write_document` (`105-116`).
  - `load_app_settings(path=None, create=True)` (`119-167`).
  - `save_startup_settings(*, start_at_login, open_dashboard_on_launch, path=None)`
    (`170-186`) type-checks, rewrites only `startup`, and returns a reloaded `AppSettings`.
- `settings_api.py`:
  - `handle_get("/api/settings", db_path)` returns `tracker`, `deck_ai`, `deck_finder`,
    `platform`, `startup`, `overlay` (`232-250`).
  - `handle_post` maps `/api/settings/{deck-ai,deck-finder,startup,overlay}` and turns
    `ValueError`/`TypeError` into 400 and anything else into 500 (`253-269`).
  - `_save_startup` validates partial payloads key by key and merges with current values
    (`180-209`). `_platform_info()` provides `system` (`149-158`).
- UI:
  - `SettingsPage.tsx` loads everything with one `fetchTrackerSettings()` (`291-315`) and
    renders `<Section id="settings-startup">` (`332-345`).
  - `StartupForm` (`429-519`) uses `settings-check` checkbox labels plus `settings-hint`
    paragraphs. It saves each toggle immediately via `saveStartupSettings(change)` and shows
    a saved/error status line.
  - Types live in `api.ts:1756-1771`.
- `backup.py:61` `LOCAL_SETTINGS_SECTIONS = ("backup", "dashboard", "live_log_window")`
  lists sections that never travel with a `.tappsbackup` (export strips them at `407-409`;
  restore keeps the local copy via `_merge_settings` at `702-710`).

### New `updates` section (in `settings.json`)

```json
"updates": {
  "check": true,
  "auto_install": false,
  "channel": "stable",
  "skipped_version": null
}
```

- Defaults are `DEFAULT_UPDATE_CHECK = True`, `DEFAULT_AUTO_INSTALL = False`, and
  `DEFAULT_UPDATE_CHANNEL = "stable"`. Add them to `_default_document()`.
- Add these fields to `AppSettings`: `update_check: bool`, `auto_install_updates: bool`,
  `update_channel: str` (validated against `("stable",)`; unknown values become `"stable"`;
  `"beta"` is a Phase 4 hook), and `skipped_update_version: Optional[str]` (must match the
  version regex, otherwise None).
- `load_app_settings` reads `document.get("updates")` exactly like `startup`
  (`settings.py:140-142`).
- New function:
  `save_update_settings(*, check: bool, auto_install: bool, channel: str = "stable", skipped_version: Optional[str] = None, path: Optional[Path] = None) -> AppSettings`.
  It mirrors `save_startup_settings`: raise `TypeError` on non-bools, replace only
  `document["updates"]`, and write through `_write_document`.
- **Add `"updates"` to `backup.LOCAL_SETTINGS_SECTIONS`** (`backup.py:61`). Auto-install is
  a per-machine choice; restoring a laptop backup on the desktop must not silently enable it.
- Runtime state is **not** stored in `settings.json` (see finding 7). It goes in
  `DATA_DIR/updates/state.json`, written atomically by `updater.py`:
  ```json
  {"last_check": "2026-10-11T14:02:11Z", "etag": "W/\"…\"", "latest": { …parsed manifest… },
   "download": {"version": "0.6.6", "path": "…/MTGA-Tracker-0.6.6-macos.zip", "sha256": "…", "verified": true},
   "acknowledged_version": "0.6.6", "last_result": {"from": "0.6.5.3", "to": "0.6.6", "ok": true, "at": "…"}}
  ```
  If the maintainer insists on `last_check` in `settings.json`, write it only through
  `settings._write_document`, under a module lock, and never from more than one thread.
- Add `data/updates/` to `.gitignore` (next to `data/backups/` at `.gitignore:63`) for
  source runs.

### `settings_api.py` additions

- Add `_updates_payload()` returning
  `{check, auto_install, channel, skipped_version, supported: bool, install_kind}`, and add
  `"updates": _updates_payload()` to the `handle_get` dict (`settings_api.py:238-248`).
- Add `_save_updates(payload)`, a copy of `_save_startup`'s pattern (key-by-key
  `isinstance(bool)` validation, merge with current values). After saving, call
  `updater.get_manager().settings_changed()` so a toggled `check` starts or stops the
  scheduler and a toggled `auto_install` re-evaluates the idle gate immediately.
- Route `if path == "/api/settings/updates": return 200, {"updates": _save_updates(payload)}`
  in `handle_post` (`settings_api.py:253-264`). It is reached through the existing
  `/api/settings` prefix branch in `dashboard.py:5956-5977`. No new dashboard wiring is
  needed for this one route.
- Update the module docstring endpoint list (`settings_api.py:7-13`).

### Settings page

- Add `<Section id="settings-updates" title="Updates" description="…">` between Startup and
  In-game overlay (`SettingsPage.tsx:345-347`), and an `UpdatesForm` built on the
  `StartupForm` pattern (`429-519`):
  - Checkbox "Check for updates automatically" (`check`).
  - Checkbox "Install updates automatically when no game is running" (`auto_install`).
    Disabled unless `check && supported`. The hint text reads: "Only while MTG Arena is
    closed. Your data is backed up first."
  - A live status row from `/api/update`: current version, latest version, a "Check now"
    button (POST `/api/update/check`), a "Restart to update" button when ready, and a
    "Skip this version" / "Un-skip" link.
  - When `!supported`, show a hint: "Running from source — update with git" or "Portable
    copy — download the new zip".
- Types: `UpdateSettings` and `UpdateStatus` in `api.ts`. Add `updates: UpdateSettings` to
  `TrackerSettings` (`api.ts:1764-1771`), plus `saveUpdateSettings()`.

---

## 3. Background job pattern, new modules, and the scheduler

### Existing patterns

- `collection_api.py`: module `_JOBS` dict plus `_JOBS_LOCK` (`31-32`), `_set()` field
  updates under the lock (`54-58`), and `start_export` creating a job and a
  `threading.Thread(..., daemon=True)` (`75-107`). The 202 response returns
  `{job, ...payload}` (`425-434`). Status is polled with `GET ?job=`
  (`437-448`, `451-466`), and old jobs are pruned by TTL.
- `deckfinder_api.py:357-392`: the same structure (`_start_job(runner, note)`).
- `overlay_launcher.py:500-510`: a **process-wide singleton** `get_manager()` that both the
  tray and the dashboard share, with `add_listener` and `_notify` (`246-297`). The update
  manager should copy this shape. There is exactly one update at a time, so a job dict keyed
  by id is the wrong model.
- HTTP fetches use stdlib `urllib.request.urlopen` with a User-Agent and a timeout
  (`card_database.py:91-94`, `deck_llm.py:278`). `requests` (and therefore `certifi`) is
  already a runtime dependency (`pyproject.toml:21`). Frozen macOS Python's default OpenSSL
  CA path is unreliable, so build the context with
  `ssl.create_default_context(cafile=certifi.where())` and fall back to the default context.

### `src/mtga_tracker/updater.py`: pure logic plus the manager (stdlib only)

```python
MANIFEST_URL = "https://github.com/pattont/MTGA-Tapps/releases/latest/download/latest.json"
ALLOWED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com")
FIRST_CHECK_DELAY_S = 90        # after startup; never during tracker startup maintenance
CHECK_INTERVAL_S = 6 * 3600
IDLE_REQUIRED_S = 120
UPDATES_DIR = DATA_DIR / "updates"

# --- versions (PEP 440 subset; setuptools-scm output and our tag spellings) ---
@dataclass(frozen=True, order=True)
class ParsedVersion:
    release: Tuple[int, ...]          # zero-padded to 4 for comparison: 0.6.5 == 0.6.5.0
    pre: Tuple[int, int]              # (rank, n): a=0,b=1,rc=2, final=(3,0)
    post: int                         # -1 if none
    dev: Tuple[int, int]              # dev releases sort before everything: (0,n) dev, (1,0) none
    local: str                        # ignored in ordering; non-empty => "development build"

def parse_version(text: str) -> Optional[ParsedVersion]
    # accepts "v0.6.5.3", "0.6.3rc8", "0.6.3-rc.8", "0.7.0.dev3+g1a2b3c", "0.6.5.post1";
    # returns None for "0.0.0+unknown" or garbage
def is_newer(candidate: str, current: str) -> bool        # False if either unparsable
def is_release_build(version: str) -> bool               # no dev, no local segment

# --- manifest ---
@dataclass(frozen=True)
class UpdateAsset: platform: str; arch: str; kind: str; name: str; url: str; size: int; sha256: str
@dataclass(frozen=True)
class Manifest: schema: int; version: str; tag: str; notes_url: str; released_at: Optional[str];
               minimum_version: Optional[str]; mandatory: bool; assets: Tuple[UpdateAsset, ...]
class ManifestError(ValueError): ...
def parse_manifest(document: Dict[str, Any]) -> Manifest   # strict: schema==1, https URLs on
                                                           # ALLOWED_DOWNLOAD_HOSTS, 64-hex sha256,
                                                           # size>0, version parses
def detect_install_kind(*, frozen: bool = ..., executable: Path = ..., platform: str = ...) -> str
    # macos-app: frozen and startup._macos_app_bundle() is not None
    # windows-installer: frozen and (exe_dir / "unins000.exe").is_file()   (Inno Setup)
    # windows-portable: frozen win32 without the uninstaller
    # source: not frozen; linux / unknown otherwise
def select_asset(manifest: Manifest, *, platform: str, arch: str, install_kind: str) -> Optional[UpdateAsset]
    # preference table per install_kind, e.g. macos-app -> ("app-zip", "dmg")   <- mechanics hook
    #                                         windows-installer -> ("inno-setup",)

# --- network (injectable opener for tests) ---
def fetch_manifest(*, url: str = MANIFEST_URL, etag: Optional[str] = None,
                   opener: Callable[..., Any] = urllib.request.urlopen, timeout: float = 15.0
                   ) -> Tuple[Optional[Manifest], Optional[str]]     # (None, etag) on 304; 404 => None
def download_asset(asset: UpdateAsset, dest_dir: Path, *, progress: Callable[[int, int], None],
                   cancelled: Callable[[], bool], opener=..., chunk: int = 1 << 20) -> Path
    # writes <name>.part, resumes with Range: bytes=<size>- when the server answers 206
    # (restarts on 200), checks free space (shutil.disk_usage >= 2*size), streams hashlib.sha256,
    # verifies size+sha256, os.replace(part, final). Mismatch => delete + raise DownloadError("sha256-mismatch")
def verify_file(path: Path, sha256: str, size: int) -> bool  # re-run right before install

# --- state machine + scheduler ---
class UpdateManager:
    def __init__(self, *, current_version: str = __version__, install_kind: Optional[str] = None,
                 state_dir: Path = UPDATES_DIR, clock=time.time, opener=None): ...
    def configure(self, *, db_path: Path, launcher: Any, request_exit: Callable[[], None]) -> None
    def start(self) -> None          # daemon thread "mtga-updater"; no-op unless frozen & check on
    def stop(self) -> None
    def settings_changed(self) -> None
    def status(self) -> Dict[str, Any]          # the GET /api/update payload
    def check_now(self) -> Dict[str, Any]       # runs in the worker; returns status immediately
    def download(self) -> Dict[str, Any]
    def request_install(self, *, force: bool = False, when: str = "now") -> Dict[str, Any]
        # when="idle" sets pending_install; raises UpdateBlocked(codes) unless force
    def skip(self, version: Optional[str]) -> Dict[str, Any]
    def acknowledge(self) -> Dict[str, Any]
    def add_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None   # tray mirror
    def busy_reasons(self) -> List[str]          # §4

_manager: Optional[UpdateManager] = None
def get_manager() -> UpdateManager               # same singleton pattern as overlay_launcher
```

State transitions (guarded by one `threading.Lock`; `_notify()` after each):

```
idle -> checking -> up_to_date | available | error
available -(auto: check on & can_install)-> downloading -> ready | error
ready -(user / auto gate passes)-> installing -> (process exits)
any -(settings: check=false)-> disabled ;  not frozen/unsupported -> unsupported (check allowed manually, download never)
error -(next tick or POST check)-> checking
```

Rules:

- Download happens automatically once a newer version is available and installable. The
  brief says "downloads ... fully in the background", so a separate opt-in is not needed;
  auto-install remains opt-in. `skipped_version == latest` suppresses the pill and the
  auto-download but keeps "Check now" honest.
- On startup, re-validate `state.json["download"]`. If the file exists, the version is
  newer, and the hash verifies, go straight to `ready`. Otherwise delete stale files.
- `below_minimum`: if `current < minimum_version`, set `can_install = false` with reason
  `"manual-required"` and keep the link-out. This is the escape hatch for a release whose
  hand-off changed incompatibly.
- Never offer a downgrade. `releases/latest` can point at an older line if an old hotfix is
  published later (§7).
- Logging: append one line per transition to `LOGS_DIR / "updater.log"` (`paths.py:284`).
  Also write a short line to the launcher's `output_stream` when a download completes or an
  install starts, so it shows in the console / Qt log.

### `src/mtga_tracker/update_api.py`: HTTP glue (mirrors `collection_api`/`settings_api`)

```python
def handle_get(path: str, query: Dict[str, List[str]]) -> Optional[Tuple[int, Dict[str, Any]]]
    # "/api/update" -> 200, get_manager().status()
def handle_post(path: str, payload: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]
    # "/api/update/check"       -> 202 status
    # "/api/update/download"    -> 202 status | 409 {"error","code":"not-available"|"unsupported"}
    # "/api/update/install"     -> 202 status | 409 {"error","code":"game-in-progress"|...,"blocked_by":[...]}
    #                              | 409 "not-ready"; {"force": true} bypasses game/arena gates but
    #                              never the sha256 re-verify or the pre-update backup
    #                              {"when": "idle"} -> 202, sets pending_install
    # "/api/update/skip"        -> {"version": "0.6.6"|null}
    # "/api/update/acknowledge" -> 200
```

### Dashboard wiring (exact insertion points)

- **`do_GET`**: add a branch next to `/api/version` (`dashboard.py:6333`):
  ```python
  if request_path == "/api/update":
      from . import update_api
      handled = update_api.handle_get(request_path, parse_qs(parsed.query))
      if handled is not None:
          status, body = handled
          _send_bytes(self, status, json.dumps(body).encode("utf-8"),
                      "application/json; charset=utf-8", {"Cache-Control": "no-store"})
          return
  ```
- **`do_POST`**: add a branch immediately after the Deck Manager branch
  (`dashboard.py:5879-5899`, before the `/api/deckfinder/` branch at 5900). It copies the
  Deck Manager Origin and Content-Type guard (5883-5886) and its bounded read:
  ```python
  if parsed.path.startswith("/api/update/"):
      from . import update_api
      origin = urlparse(self.headers.get("Origin") or "")
      if (origin.hostname and origin.hostname not in {"localhost", "127.0.0.1", "::1"}) or \
         self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
          _send_bytes(self, 403, b'{"error":"Use the local dashboard to update."}', "application/json")
          return
      try:
          length = int(self.headers.get("Content-Length") or 0)
          payload = json.loads(self.rfile.read(length).decode("utf-8")) if 0 < length <= 4096 else {}
      except (ValueError, UnicodeError):
          payload = {}
      handled = update_api.handle_post(parsed.path, payload if isinstance(payload, dict) else {})
      status, body = handled or (404, {"error": "Unknown update action."})
      _send_bytes(self, status, json.dumps(body).encode("utf-8"),
                  "application/json; charset=utf-8", {"Cache-Control": "no-store"})
      return
  ```
  Conventions this preserves:
  - `do_POST` sets `self.close_connection = True` (`5873`).
  - `_send_bytes` always sends Content-Length and adds `Connection: close` (`5735-5756`).
  - Responses are `no-store`.
  - `clear_response_cache()` already runs on every POST (`5876`).
  - The UI's `fetch` must send `Content-Type: application/json` and a JSON body (even `{}`).
- **The `/api/settings/updates` save** needs no new branch (see §2).
- Install is asynchronous. `POST /api/update/install` must return its 202 **before** the
  dashboard is torn down, so `request_install` hands the sequence to the updater thread,
  which waits ~0.5 s. Calling `server.shutdown()` from a handler thread would block that
  request until `serve_forever` exits, and the response would never flush.

### Where the periodic timer lives: recommendation

**A daemon thread owned by `UpdateManager`, started by `UnifiedLauncher`.** It is not in the
tracker loop and not in a Qt `QTimer`.

- **Not the tracker runtime loop** (`tracker_runtime.py:126-144`). The tracker can be
  stopped by the user ("Stop Tracking", `menu_app.py:519-525`), by a backup restore
  (`backup.py:752-760`), or by a startup error (`app.py:166-170`). Updates must keep working
  in all of those cases. A 6-hour network call has no place inside a 250 ms loop, and the
  loop runs on the **main thread** in `--no-gui` mode (`app.py:245`).
- **Not the menu-app `QTimer`.** The menu is optional (`--no-gui`, missing `gui` extra), and
  the dashboard must be the single source of truth. The tray only mirrors state through
  `add_listener`, exactly like the overlay (`menu_app.py:353-357`).
- **Not inside the dashboard server.** `dashboard.main()` (`dashboard.py:6828-6843`) is the
  `mtga-tracker-dashboard` source-only entry point. It is not shipped frozen and has no
  launcher to restart. In that mode `/api/update` reports `state: "unsupported", reason:
  "dashboard-only"`. A dashboard is also not the owner of the process lifetime.
- **`UnifiedLauncher` is the one object present in both shipped modes.** It owns the
  process, the db path, and the stop/start primitives the install needs. Add:
  ```python
  def start_updater(self, request_exit: Callable[[], None]) -> None:
      from .updater import get_manager
      manager = get_manager()
      manager.configure(db_path=self.db_path, launcher=self, request_exit=request_exit)
      manager.start()     # no-op unless frozen and settings.updates.check
  ```
  Call it from `MenuBarController.start()` after `start_dashboard()` (`menu_app.py:403-406`)
  and from `_run_without_gui` after `start_dashboard()` (`app.py:241`). Do not call it from
  `start_dashboard()` itself, because tests create launchers freely (`tests/test_app.py:52-115`).
  Add `MTGA_TRACKER_DISABLE_UPDATES=1` as a kill switch for CI and preview scripts
  (`scripts/preview_deck_manager.py` must never update).
- **Deck Finder mode is excluded structurally.** `main()` returns at `app.py:253-259` before
  any launcher exists. Never start the manager at import time.
- Cadence: the first check runs `FIRST_CHECK_DELAY_S` (90 s) after start, so it never
  competes with tracker startup maintenance (`tracker_runtime.py:99-108`). After that it runs
  every 6 h with ±10 % jitter, using `If-None-Match` with the stored ETag. The worker wakes
  every 15 s **only** while `ready` with auto-install or `pending_install`, to evaluate the
  idle gate (§4). Otherwise it sleeps on a `threading.Event` that `stop()` sets.

---

## 4. Game-in-progress gate and "idle"

### What exists

- Table: `live_status(id=1, session_id, updated_at, in_game, ...)` (`analytics.py:405-425`).
- Writers:
  - `_upsert_live_status` runs with each console line (`analytics.py:3187-3195`).
  - `write_live_status` (`3225-3231`).
  - The heartbeat `touch_live_status` updates `updated_at` only (`3233-3248`).
  - `mark_live_status_stopped` rewinds `updated_at` by 120 s and sets `in_game = 0`
    (`3250-3262`).
- `in_game` is computed in `tracker_analytics.py:150`.
- Readers:
  - `live_api._tracker_state` returns `offline` when `updated_at` is older than
    `OFFLINE_AFTER_SECONDS = 20` (`live_api.py:40`, `146-152`), else `live` or `idle`.
  - `deck_native_api.game_in_progress(db_path)` opens a read-only URI connection and reads
    `in_game` (`deck_native_api.py:29-40`). This is the existing "never touch Arena during a
    game" guard.
  - `backup.tracker_active` is the heartbeat-recency check (`backup.py:595-619`).
- Arena process probes:
  - `collection_export._find_pid_macos("MTGA")` / `_find_pid_windows("MTGA.exe")`
    (`collection_export.py:263-302`, names at `519-522`). These lack `CREATE_NO_WINDOW`.
  - The overlay's Rust probe uses `pgrep -x MTGA`, then `lsappinfo` by bundle id
    `com.wizards.mtga` (`overlay/src-tauri/src/arena.rs:60-90`). It is not reachable from
    Python.

### Recommendation

Read the DB, not an in-process callback. The tracker may be stopped while the app keeps
running, the DB row is what every other guard already uses, and the read is a single
read-only `SELECT`. An in-process hook would also need thread-safe access to
`CardTracker.game_state`, which the tracker thread mutates.

1. **Shared helpers** go in `live_api.py`, a cheap module the dashboard already imports:
   ```python
   def game_activity(db_path: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
       """{'tracker': 'live'|'idle'|'offline', 'in_game': bool, 'updated_at': str|None,
           'last_game_ended_at': str|None}"""   # one ro connection: live_status + MAX(games.ended_at)
   ```
   `deck_native_api.game_in_progress` then becomes a thin wrapper over this function, so the
   logic is not duplicated.
2. **Arena probe**: add `paths.arena_process_running() -> Optional[bool]`. AGENTS says OS
   checks belong in `paths.py`.
   - macOS: `pgrep -x MTGA`.
   - Windows: `tasklist /FI "IMAGENAME eq MTGA.exe"` with `CREATE_NO_WINDOW`.
   - Returns None when the probe itself fails, which counts as "unknown → not idle".
   Repoint `collection_export` to it later. That is optional, but it fixes the console-flash
   gap.
3. **Updater idle evaluation** (`UpdateManager._idle_for_install()`) has two sampled inputs:
   - `last_in_game_seen`: the in-memory monotonic time the worker last observed
     `in_game = 1`, sampled every 15 s.
   - `last_game_ended_at` from the DB.

   `busy_reasons()` returns a list. Install proceeds only when it is empty:
   - `game-in-progress`: `in_game` is 1, **or** a game was seen or ended less than
     `IDLE_REQUIRED_S` (120 s) ago. This covers Bo3 sideboarding, where `in_game` reads 0.
   - `arena-running`: blocks **auto-install only**. A manual "Restart to update" with Arena
     open is allowed, with a confirm: "Arena is open. The tracker will be offline for ~10 s;
     don't start a match until it's back." This rule follows from finding 3.
   - `deck-transfer`: a native Deck Manager job is active (`deck_native_api._ACTIVE` at
     `deck_native_api.py:22`, set at `444-449`). Expose it as
     `deck_native_api.job_active() -> bool`. Killing mid-transfer leaves an "uncertain"
     journal (AGENTS Deck Manager). Durable pending journals are fine across a restart.
   - `collection-export`: any `collection_api._JOBS` entry with `state == "running"`. Expose
     it as `collection_api.job_running() -> bool`.
   - `backup-restore`: a restore or merge is in flight. Add a module-level `threading.Lock`
     or flag in `backup_api` around `restore_backup`/`merge_backup`.
4. **Auto-install fires when** all of these hold: `auto_install` is on, the state is `ready`,
   the file re-verifies, and `busy_reasons()` is empty. Since `arena-running` is a busy
   reason here, Arena must also be closed. The most common hit is a login start
   (`--login-start`) before the user opens Arena, or after Arena is closed for the night.
   **Mandatory** releases use the same gate; they only make the pill sticky (no skip).
   `force` bypasses the game and Arena gates only for an explicit user click after a
   confirm dialog. It never applies to auto-install.

---

## 5. Restart / hand-off hooks

### What exists

- `UnifiedLauncher` primitives, as above.
- `_run_without_gui` runs the tracker in the foreground and calls `launcher.shutdown()` in
  `finally` (`app.py:233-248`).
- `main()` parses args (`261-274`). It acquires the guard, or exits quietly for
  `--login-start` (`283-309`). It releases the guard in `finally` (`324-325`).
- Menu app shutdown chain:
  - `quit_action` calls `app.quit` (`menu_app.py:369-371`).
  - `aboutToQuit` calls `MenuBarController.shutdown` (`382`).
  - `shutdown` stops the overlay timer, then `overlay.stop()`, then `launcher.shutdown()`,
    then `tray.hide()` (`572-580`).
  - `run_menu_app` returns `app.exec()` (`616`), so `main`'s `finally` releases the guard,
    and `QLockFile` is released when the process exits.
- The overlay is stopped only by the menu controller, not by `launcher.shutdown()`. On
  Windows its exe lives inside the install tree (`overlay/tapps-overlay.exe`), and on macOS
  inside `Contents/Helpers/` (AGENTS packaging). **It must be stopped before any file swap.**
  `OverlayManager.stop()` (`overlay_launcher.py:404-432`) kills owned and external overlay
  PIDs and does not touch the `enabled` preference. That is correct: the overlay restarts
  after the update.
- The Inno installer has `CloseApplications=yes`, `RestartApplications=no`, and a
  `[Run] postinstall nowait skipifsilent` entry (`packaging/windows_installer.iss:39-40,61-62`).
  A silent install therefore will **not** relaunch by itself. The relaunch is the
  helper's job, or the mechanics agent can add a `[Run]` entry gated on a `/RELAUNCH`
  parameter.

### Sequence that `UpdateManager._perform_install()` drives (in-process, updater thread)

1. **Pre-flight.** The state must be `ready`. `verify_file(path, sha256, size)` must pass
   again. Unless forced, `busy_reasons()` must be empty. Set `state = installing` and
   `_notify()`, so the tray and pill switch to "Restarting…".
2. **Journal.** Atomically write `UPDATES_DIR/pending.json`:
   `{from, to, asset, path, sha256, started_at, pid, install_kind}`.
3. **Pre-update snapshot (mandatory).** Call `backup.export_backup(db_path, db_path.parent /
   "backups", tag=f"pre-update-{from}", record=False)`, then prune pre-update copies with
   `keep=2` (§6). On failure: `state = error (code "backup-failed")`, delete `pending.json`,
   and abort. Never update without a snapshot.
4. **Quiesce the tracker.** Call `launcher.stop_tracker(timeout=5.0)` (`app.py:204-213`). It
   calls `tracker.request_stop()`, joins the thread, and runs `mark_live_status_stopped` so
   every dashboard and overlay flips to offline at once. In `--no-gui` the tracker is on the
   main thread: `stop_tracker` only requests the stop (`tracker_thread` is None), and
   `start_tracker(background=False)` then returns, which is the desired exit path.
5. **Release read handles.** Call `live_api.reset_poll_connections()` and
   `dashboard.clear_response_cache()` (the same `before_swap` the backup restore uses,
   `dashboard.py:5930-5934`). Then run a best-effort
   `PRAGMA wal_checkpoint(TRUNCATE)` on a short-lived connection, so the DB is a single file
   while the app is down.
6. **Stop the overlay** with `overlay_launcher.get_manager().stop()`. Leave
   `overlay.enabled` as is.
7. **Hand off.** Call `install_and_restart(plan)` (the black box) with:
   ```python
   InstallPlan(asset_path=Path, asset_kind=str, install_kind=str, from_version=str, to_version=str,
               parent_pid=os.getpid(), app_path=Path,          # .app bundle / install dir
               relaunch_args=["--after-update", "--updated-from", from_version, "--no-browser"],
               log_path=LOGS_DIR / "updater.log")
   ```
   Contract: it spawns the detached helper (`CREATE_NO_WINDOW` / `DETACHED_PROCESS` on
   Windows) that waits for `parent_pid` to exit, swaps or installs, and relaunches. It
   returns quickly. If it raises, resume with `launcher.start_tracker()` and restart the
   overlay if it was enabled, then `state = error`, then delete `pending.json`.
8. **Exit the process** by calling the host-provided `request_exit()`:
   - Menu app: `QMetaObject.invokeMethod(app, "quit", QueuedConnection)`, or an
     `AppSignals.update_exit` signal connected to `app.quit`. Qt calls must be made on the GUI
     thread. This runs the normal `aboutToQuit`, then `shutdown()`, then
     `launcher.shutdown()` (which includes `stop_dashboard`), and the guard release.
   - `--no-gui`: `request_exit` is `launcher.stop_tracker`. That was already done in step 4,
     so the foreground tracker returns, `_run_without_gui`'s `finally` shuts down the
     dashboard, and `main` releases the guard.
   - If the process has not exited 20 s after the request, `os._exit(0)` as a last resort.
     The helper is waiting on the PID.

### Menu app (tray mirror)

- Add `update_changed = pyqtSignal(dict)` to `AppSignals` (`menu_app.py:138-141`).
- Add `self.update_action = QAction("Restart to Update", self)`. Insert it **directly after
  the two status lines** (`menu_app.py:302-308`) so it is the first actionable item, and set
  `setVisible(False)` by default.
- Subscribe with `get_update_manager().add_listener(self.signals.update_changed.emit)` and
  connect it to `_sync_update_action(status)`, mirroring the overlay wiring at `353-354`.
- Texts:
  - available: "Update available: v0.6.6…" (opens `#/settings` at the Updates section).
  - downloading: "Downloading update… 42%".
  - ready: "Restart to Update (v0.6.6)".
  - installing: "Restarting…" (disabled).
- On the transition to `ready`, call `tray.showMessage("Tapps Tracker", "Update v0.6.6 is
  ready. Restart from this menu when you're done playing.", Information, 8000)`. The
  pattern is at `menu_app.py:536-542`.
- Click handler: `manager.request_install()`. On `UpdateBlocked(["game-in-progress"])`,
  show a `QMessageBox` with "Install after this game" (sets `when="idle"`) / "Cancel". For
  `arena-running`, ask for confirmation, then `request_install(force=True)`.
- `start()` calls `self.launcher.start_updater(request_exit=self._request_quit_from_any_thread)`.
- `shutdown()` adds `get_update_manager().stop()` before `launcher.shutdown()`.

### `--after-update` / `--updated-from` in `app.main()`

- Add two arguments after `--login-start` (`app.py:273`), suppressed from help:
  - `parser.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)`
  - `parser.add_argument("--updated-from", default=None, help=argparse.SUPPRESS)`
- Guard acquisition: when `args.after_update` is set, retry `instance_guard.acquire()` every
  0.5 s for up to 60 s before treating a held guard as "already running". This is a new
  `acquire_with_retry(guard, timeout)` helper in `single_instance.py`. In `run_menu_app`,
  use `QLockFile.tryLock(30000)` instead of `tryLock(0)` when `args.after_update` is set
  (`menu_app.py:126-131` gains a timeout parameter). If the guard is still held after the
  timeout, exit quietly (like `--login-start`) and log it. Never show the "already running"
  dialog to a user who just clicked Restart.
- Outcome recording runs once the dashboard is up, in `UpdateManager.start()`:
  - If `pending.json` exists, compare `__version__` with its `to` field.
  - On a match, write `state.json.last_result = {from, to, ok: true, at}`, delete
    `pending.json`, delete the downloaded asset and any `.part`, and set `just_updated` (shown
    until acknowledged).
  - On a mismatch (the helper relaunched the old app, or the install was cancelled), record
    `ok: false` with `error.code = "install-not-applied"`. Keep the asset so the user can
    retry.
  - Log "Updated from X to Y" to `updater.log` and the console.
  - If `pending.json` exists but `--after-update` is absent (a crash mid hand-off), apply the
    same comparison.
  - Write `UPDATES_DIR/healthy-<version>` after the dashboard is serving and the DB has
    opened and migrated. This is the hook for the mechanics agent's rollback watchdog.
- `--no-browser` is passed on relaunch: the old tab reloads itself (§1). After a manual
  restart from the tray with no tab open, the tray toast "Updated to v0.6.6" is enough.
- `--login-start` semantics are unchanged. `startup.py` registers the bundle path
  (`startup.py:36-58`), and on Windows the exe path. Both stay stable across in-place
  updates, so login registration needs no change. The mechanics agent must keep the
  `.app`/exe path identical.

---

## 6. DB safety at upgrade

### How migrations behave today

- `AnalyticsStore.connect()` opens the DB, sets WAL, `busy_timeout`, and
  `synchronous=NORMAL`, then runs `ensure_schema`, which ends in `apply_pending_migrations`
  then `canonicalize_imported_deck_names` (`analytics.py:50-62`, `566-578`).
- `apply_pending_migrations` (`685-760`) runs each pending migration in order and inserts its
  `schema_migrations` row with **no per-migration transaction**. There is one
  `conn.commit()` at the end (`749`). Some migrations commit internally (`with conn:`, 10
  uses in the file; `_delete_games_and_recompute_sessions`). Python's sqlite3 runs DDL inside
  the implicit transaction. The result is that **a failing migration leaves earlier
  migrations committed or uncommitted depending on whether a later step committed. It is not
  atomic.** The design relies on every migration being idempotent (comment at `731-733`).
- On failure, the exception propagates out of `connect()`. `UnifiedLauncher.start_dashboard`
  calls `store.connect()` first (`app.py:98-100`), so startup fails:
  - Menu: `QMessageBox.critical` (`menu_app.py:411-414`).
  - `--no-gui`: a traceback.
  - The app does not run with a half-migrated DB. It refuses to start, and the next launch
    retries the pending migrations.
- There is no "DB newer than this build" check on open. An older build opening a newer DB
  simply ignores the unknown migration rows. Backups do have `supported_schema_version()`
  (`backup.py:522-541`), and restore refuses a newer schema (`backup.py:735-741`).
- VACUUM runs after the commit when 11/28 ran (`751-756`). That is not relevant to 32-35.

### Existing backup machinery to reuse

- `backup.snapshot_database()` uses SQLite's online `source.backup(dest)` from a read-only
  URI. It sets the copy to `journal_mode=DELETE`, truncates `raw_game_payloads` and
  `live_status`, and runs VACUUM (`backup.py:277-309`).
- `export_backup(db_path, folder, *, tag=..., record=False)` zips the snapshot, settings,
  Deck Finder config, overlay prefs, and Scryfall cache, and never overwrites
  (`backup.py:354-456`).
- The safety copy convention is the folder `db_path.parent / "backups"` (`SAFETY_DIR_NAME`,
  `backup.py:52`), tag `pre-restore` (`53`), pruned to `keep=2` by
  `_prune_safety_backups(folder, keep=2)`, which globs `*-{SAFETY_TAG}*` (`622-632`). Restore
  and merge already use this (`backup.py:767-780`, `1027`).

### Recommendation

- Generalize the prune helper to `_prune_safety_backups(folder, keep=2, tag=SAFETY_TAG)` and
  add `PRE_UPDATE_TAG = "pre-update"`. Take the snapshot in step 3 of §5 with
  `export_backup(db_path, db_path.parent / SAFETY_DIR_NAME, tag=f"{PRE_UPDATE_TAG}-{from_version}", record=False)`,
  then call `_prune_safety_backups(folder, keep=2, tag=PRE_UPDATE_TAG)`. Benefits:
  - It uses the online backup API (WAL-safe while the tracker still runs, and it runs before
    the tracker stops so the wait stays short).
  - It is a normal `.tappsbackup`, restorable from Settings → Backup & restore, including
    the schema check and undo.
  - It shares retention with the existing convention.
  - Cost: the 30-day `raw_game_payloads` diagnostics are dropped from that copy. That is
    acceptable, since they are not history.
- Ordering: snapshot → stop tracker → hand off. Take the snapshot **in the old process**,
  because the new process's first `connect()` runs the migrations before any of its code
  could copy the DB.
- Add a downgrade guard on open. In `apply_pending_migrations`, if
  `max(applied) > max(known)`, print a warning and set a flag that `/api/update` surfaces as
  `"db_newer_than_app": true`. Do not refuse to start, since migrations are additive. This
  matters if a user rolls back to an older build after an update.
- Optional hardening (separate change): run each pending migration inside
  `with conn:` (`BEGIN … COMMIT`) together with its `schema_migrations` insert. The DDL in
  32-35 is transactional in SQLite, so this works, but it would need an audit of the
  migrations that commit internally.
- What the next release's DB changes mean for the plan:
  - **v32** drops and recreates `idx_game_events_session_time` as a partial index
    (`analytics.py:1419-1430`). This is the only potentially slow step on large DBs. It
    happens in the new process's first `connect()`, before the dashboard listens, so the UI
    tab sees connection refused for a few seconds. The `/api/version` reload loop tolerates
    that.
  - **v33/v34/v35** create the Deck Manager tables, the transfer journal, and collections.
    They are additive. The pre-update snapshot covers them, and `.tappsbackup` already
    carries managed decks.
  - `game_events` gains the `object_id`/`target_object_id`/`arena_id`/`controller_seat`/`visible`
    columns via `ensure_table_column` (`analytics.py:566-576`). These are additive and
    nullable or defaulted.
  - The first updater-capable release is itself the bootstrap (finding 6). Its CHANGELOG
    entry should say "install this one manually".

---

## 7. CI: emitting `latest.json` and `SHA256SUMS`

### What exists (`.github/workflows/release.yml`)

- Matrix build on `macos-latest` (DMG) and `windows-latest` (zip + setup.exe) (`17-33`).
- `SETUPTOOLS_SCM_PRETEND_VERSION=${GITHUB_REF_NAME#v}` on tags (`51-54`).
- Each leg uploads to a **draft** with `softprops/action-gh-release@v3` (`91-96`).
- Manual runs use `upload-artifact` (`98-103`).
- Asset names embed the setuptools-scm-normalized version:
  - macOS: `MTGA-Tracker-<ver>.dmg` (`scripts/build_macos_installer.sh:18-19`).
  - Windows: `MTGA-Tracker-<ver>-windows.zip` and `-setup.exe`
    (`scripts/build_windows_app.ps1:66-69`).
  - So `v0.6.3-rc.8` produces files named `0.6.3rc8`.
- The macOS build is native arm64; the spec sets no `target_arch`.

### Changes

1. **Release-type hygiene in both build legs**:
   - Set `prerelease: ${{ contains(github.ref_name, '-') }}` so `-rc.N` tags can never become
     `releases/latest`.
   - Set `make_latest: ${{ !contains(github.ref_name, '-') }}`, or `legacy`, to avoid an old
     hotfix published later being promoted to latest. The client also refuses downgrades.
2. **Always upload Actions artifacts** (drop the `if: !startsWith(...)` on `98-103`, or add a
   second upload step) so a follow-up job can read the files. **Do not** try to read them
   back from the draft: `GET /releases/tags/{tag}` (used by `gh release download <tag>`) does
   not return drafts.
3. **macOS update-asset hook** (if the mechanics agent prefers a zip):
   - In `build_macos_installer.sh`, after the DMG, run
     `ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ROOT_DIR/dist/MTGA-Tracker-${VERSION}-macos.zip"`.
     `ditto` keeps symlinks, xattrs, and the code signature, which plain `zip` breaks.
   - Add `dist/MTGA-Tracker-*-macos.zip` to the macOS `artifact:` glob (`27`).
4. **New job `manifest`**:
   - Settings: `needs: build`, `if: startsWith(github.ref, 'refs/tags/')`,
     `runs-on: ubuntu-latest`.
   - Steps:
     - `actions/download-artifact@v4` (merge both legs into `dist/`).
     - `python3 scripts/make_update_manifest.py --tag "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --dist dist --out dist`.
       This is a new, stdlib-only script that writes `latest.json` and `SHA256SUMS`.
     - `softprops/action-gh-release@v3` with `draft: true`, the same `prerelease`, and
       `files: dist/latest.json dist/SHA256SUMS`. It attaches to the same draft by tag.
   - Script logic:
     - `version` is the tag without `v`, normalized with the same parser as
       `updater.parse_version`. Import it from `src/mtga_tracker/updater.py` with
       `PYTHONPATH=src` so CI and client cannot disagree.
     - Assert that the normalized version equals the version embedded in every asset
       filename. Fail the job otherwise; this catches the "dirty version" problem the
       workflow comment at `46-50` describes.
     - Each asset's `url` is
       `https://github.com/<repo>/releases/download/<tag>/<name>`. The URL is tag-pinned, so
       it stays valid after newer releases. It returns 404 until the draft is published, so
       the manifest goes live only on publish.
     - `sha256` and `size` are computed from the files. `SHA256SUMS` uses the
       `sha256sum` format (`<hex>  <name>`).
     - `notes_url` is `https://github.com/<repo>/releases/tag/<tag>`. `released_at` is the job
       time.
     - `minimum_version` and `mandatory` come from optional repo variables or a
       `release-meta.json` in the repo (default `null` / `false`).
5. **Manifest shape (`schema: 1`)**:
   ```json
   {
     "schema": 1,
     "version": "0.6.6",
     "tag": "v0.6.6",
     "released_at": "2026-10-20T18:00:00Z",
     "notes_url": "https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.6",
     "minimum_version": null,
     "mandatory": false,
     "assets": [
       {"platform": "macos",   "arch": "arm64", "kind": "app-zip",            "name": "MTGA-Tracker-0.6.6-macos.zip",   "url": "…", "size": 0, "sha256": "…"},
       {"platform": "macos",   "arch": "arm64", "kind": "dmg",                "name": "MTGA-Tracker-0.6.6.dmg",         "url": "…", "size": 0, "sha256": "…"},
       {"platform": "windows", "arch": "x64",   "kind": "inno-setup",         "name": "MTGA-Tracker-0.6.6-setup.exe",   "url": "…", "size": 0, "sha256": "…"},
       {"platform": "windows", "arch": "x64",   "kind": "portable-zip",       "name": "MTGA-Tracker-0.6.6-windows.zip", "url": "…", "size": 0, "sha256": "…"}
     ],
     "signature": null
   }
   ```
   `signature` is a reserved hook for a detached ed25519/minisign signature over the
   canonical manifest bytes, if the industry report recommends one. The trust anchor
   otherwise is GitHub TLS plus the host allowlist.
6. **Facts about `releases/latest/download/latest.json`**:
   - It redirects (302) to the newest published, non-draft, non-prerelease release's asset,
     then to the `*.githubusercontent.com` CDN. The client must follow redirects and keep the
     host allowlist.
   - A published release that lacks `latest.json` makes the URL 404. The client treats 404 as
     "no information", not as an error toast.
   - Add a publish checklist item to `docs/RELEASING.md`: "the draft has `latest.json` and
     `SHA256SUMS`; spot-check one hash".
7. Manual (non-tag) runs keep producing artifacts and never produce a manifest. Their
   versions are `X.Y.Z.devN+g…`, and `is_release_build()` makes those frozen builds report
   `reason: "unknown-version"`. They never auto-update.

---

## 8. Tests

Python conventions:

- Plain pytest functions with `tmp_path` and `monkeypatch`, e.g. `tests/test_settings.py`
  (`load_app_settings(settings_path)` with explicit paths) and `tests/test_app.py:180-230`
  (fake guard classes monkeypatched onto `app`).
- Real-server tests with `create_dashboard_server("127.0.0.1", 0, db_path=…)`, a thread, and
  `HTTPConnection` (`tests/test_deck_manager.py:424-445`).
- `tests/test_menu_app.py` needs a display and is excluded from the agent run.

**`tests/test_updater.py`** (new; pure, offline, no real network):

- `parse_version` / `is_newer` table:
  - `0.6.5.3 > 0.6.5`, `0.6.5.4 > 0.6.5.3` (the bug in today's triplet compare),
    `0.6.5 == 0.6.5.0`.
  - `0.6.3rc8 == v0.6.3-rc.8`, `0.6.3 > 0.6.3rc8`, `0.6.3rc8 > 0.6.3rc7`,
    `0.6.3rc1 > 0.6.3b2`.
  - `0.7.0.dev3+g1a2b3c < 0.7.0rc1`, `0.6.5.post1 > 0.6.5`.
  - `0.0.0+unknown` and garbage return None, and `is_newer` returns False.
  - Local segments are ignored in ordering.
- `is_release_build`: false for dev and local versions.
- `parse_manifest`:
  - Accepts the schema-1 example.
  - Rejects `http://` URLs, non-allowlisted hosts, bad hex, size 0, unknown schema, and
    unparsable versions.
  - Ignores unknown extra keys.
- `select_asset`:
  - macOS app prefers `app-zip` and falls back to `dmg`.
  - Windows installer picks `inno-setup`, and portable gets None (link-out only).
  - Wrong arch gets None.
- `detect_install_kind` with fake `frozen`/`executable`/`platform` and a tmp tree containing
  or lacking `unins000.exe`, and an `.app` path.
- `fetch_manifest` with a fake opener: 200 + ETag; 304 returns (None, etag); 404 returns
  None; a timeout raises a typed error.
- `download_asset` against a tiny local `http.server` (or a fake opener):
  - Full download with a correct hash produces the final file and no `.part`.
  - Hash mismatch deletes the file and raises `sha256-mismatch`.
  - Resume: a pre-seeded `.part` with a 206 response appends and verifies; a 200 response
    restarts.
  - Insufficient disk space (monkeypatched `shutil.disk_usage`).
  - Cancellation.
- `UpdateManager` state machine with an injected clock, opener, and `state_dir=tmp_path`:
  - Not frozen gives `unsupported` (manual check allowed, no download).
  - Check off gives `disabled`.
  - Available, then auto-download, then ready.
  - A skipped version suppresses the pill and the auto-download.
  - Downgrade is never offered.
  - `below_minimum` gives `can_install = false`.
  - Startup with a valid cached download goes straight to `ready`; a corrupted cache is
    deleted.
- Idle gate (`busy_reasons`) with a temp DB containing `live_status`:
  - `in_game = 1` blocks.
  - `in_game = 0` but a game ended 30 s ago blocks; one that ended 3 min ago passes.
  - Arena running blocks auto but not forced manual.
  - Monkeypatched `deck_native_api.job_active()` / `collection_api.job_running()` block.
- Install orchestration with fakes (launcher, overlay manager, `install_and_restart`,
  `request_exit`) asserts the exact call order:
  `export_backup(tag startswith "pre-update")` → `stop_tracker` →
  `reset_poll_connections` → `overlay.stop` → `install_and_restart(plan)` →
  `request_exit`.
  - A backup failure aborts before `stop_tracker`.
  - A hand-off exception restarts the tracker and sets `error`.
- `pending.json` reconciliation on start: version matches gives `just_updated` and asset
  cleanup; a mismatch gives `install-not-applied`.
- Pre-update retention: three successive snapshots keep 2, and `pre-restore` files are
  untouched (extend `tests/test_backup.py`).

**`tests/test_update_api.py`** (new; real server on port 0, singleton swapped with a fake
manager via monkeypatch):

- `GET /api/update` returns 200, JSON, `Cache-Control: no-store`, and a Content-Length.
- `POST /api/update/install`:
  - With `Content-Type: text/plain`, or with `Origin: https://example.com`, it returns 403
    and the manager is not called.
  - With the fake manager blocked by a game, it returns 409 `game-in-progress` with
    `blocked_by`.
  - With `{"force": true}`, it returns 202.
  - When not ready, it returns 409 `not-ready`.
- `POST /api/update/check` returns 202. An unknown `/api/update/foo` returns 404.
- The response carries `Connection: close` (the POST convention).
- `POST /api/settings/updates` (extend `tests/test_settings.py` / a settings_api test):
  - Rejects non-bools with 400.
  - Saves partial payloads.
  - Preserves `startup` and other sections.
  - Calls `settings_changed()`.
- `GET /api/settings` includes `updates`.

**`tests/test_settings.py`** (extend):

- The default document now includes `updates`. The existing equality assertion at
  `tests/test_settings.py:11-19` must be updated.
- Invalid `channel` falls back to `stable`.
- `save_update_settings` preserves the other sections.

**`tests/test_backup.py`** (extend): `"updates"` is stripped on export and kept locally on
restore (`LOCAL_SETTINGS_SECTIONS`).

**`tests/test_app.py`** (extend):

- `--after-update` retries a held guard. The fake guard returns False twice, then True, and
  `_run_without_gui` runs.
- A guard that stays held exits 0 quietly (no "already running" on stderr).
- `--updated-from` is accepted.
- `--login-start` behavior is unchanged.

**`tests/test_live_api.py`**: `game_activity()` on a DB without `live_status`, one with a
fresh or stale heartbeat, and the `last_game_ended_at` value.

**`tests/test_paths.py`**: `arena_process_running()` with a monkeypatched `subprocess.run`.
On Windows the call must pass `creationflags=CREATE_NO_WINDOW`, and a probe failure returns
None.

**UI (vitest)**, following `ui/src/components/BackupCard.test.tsx` (`render`, `userEvent`,
`vi.stubGlobal('fetch', vi.fn(...))`) and `App.test.tsx:616-630`:

- `ui/src/updateStatus.test.ts`: `updatePillModel` for every state (labels, percent rounding,
  link vs action, the `can_install = false` link-out, hidden states).
- `ui/src/components/UpdateIndicator.test.tsx`:
  - Expanded and collapsed render.
  - "Restart to update" posts `/api/update/install` with a JSON content type.
  - A 409 `game-in-progress` shows the message and the "Install after this game" choice,
    which posts `{"when": "idle"}`.
  - Downloading shows a `progressbar` with the right `aria-valuenow`.
  - The poll interval switches from 15 s to 1 s while downloading (fake timers).
  - The `just_updated` notice and acknowledge.
  - `installing` triggers the `/api/version` reload loop (stub `window.location.reload`).
- `SettingsPage` Updates form: toggles post `/api/settings/updates`; auto-install is disabled
  when `!supported` or `!check`; "Check now".
- `App.test.tsx`: existing fetch stubs return the snapshot for every URL. Make sure
  `/api/update` returning the snapshot shape renders nothing rather than throwing; the pill
  model must tolerate unknown payloads.
- Delete the `updateCheck` usage. There are no existing tests for it.

Commands (AGENTS): the full pytest command line, then `npx vitest run`, `npx tsc -b`,
`npm run lint`, and `npm run build` in `ui/`.

---

## 9. Docs and changelog

- **AGENTS.md**:
  - Add bullets under "Primary code paths" for `updater.py`, `update_api.py`, and
    `scripts/make_update_manifest.py`.
  - The bullets cover: the singleton manager started by `UnifiedLauncher.start_updater` (in
    both GUI and `--no-gui`, never in Deck Finder mode or the dashboard-only entry); "frozen
    only, source shows link-out"; the `updates` settings section versus `updates/state.json`;
    the install gate (game, idle ≥ 120 s, Arena closed for auto, active native deck job or
    collection export or restore); the exact install sequence including the mandatory
    `pre-update` `.tappsbackup` (keep 2); `--after-update` retrying both locks; and
    `MTGA_TRACKER_DISABLE_UPDATES`.
  - Add a Tracker Invariant: "Never auto-install while Arena is running or within 2 minutes
    of a game; never restart the app without either the user's click or their opted-in
    auto-install." This complements "Never stop or restart the active tracker … without
    explicit user approval": opting in is the approval.
  - Add the new POST routes to the "Other existing POSTs are …" list in the
    `game_annotations` paragraph.
  - Update the Packaging section: the `manifest` job, `latest.json` + `SHA256SUMS`,
    `prerelease` for `-` tags, and the optional `-macos.zip`.
- **docs/RELEASING.md**:
  - Rewrite "Updates and user data" (`92-101`). The text "The dashboard already checks
    GitHub Releases … does not install updates" becomes a description of the backend check
    against `latest.json`, the background download and SHA-256 check, Restart to update,
    opt-in auto-install, the pre-update backup in `<data>/backups`, and the fact that
    portable Windows and source runs only link out.
  - Add a "Checks before publishing" item: `latest.json` and `SHA256SUMS` exist on the draft
    and the versions match. Test the update path from the previous release on both OSes with
    a separate data dir.
  - Note that publishing the draft is what makes the manifest live, and that RC tags are
    prereleases.
- **QUICKSTART.md**: in Option 1, after the paragraph on Start with macOS/Windows (`54-57`),
  add a short "Updates" paragraph: Restart to update in the sidebar and tray, the
  Settings → Updates toggles, and the fact that a portable zip needs a manual download.
  Revisit the Gatekeeper and SmartScreen paragraphs (`58-66`) once the mechanics agent
  confirms whether in-app updates trigger them.
- **README.md**: the network-requests list (`381-382`) says "The dashboard checks GitHub
  Releases for updates, caching successful checks for a day". Change it to "The tracker
  downloads a small update manifest from GitHub Releases at startup and every 6 hours (off
  in Settings → Updates), and downloads the new version from GitHub when one is available."
- **CHANGELOG.md `## Unreleased`**: add a Features entry covering in-app updates, Settings →
  Updates, opt-in auto-install, and the pre-update backup. Also add the note "This release
  must be installed manually; later releases can update in place."
- **docs/plans/INDEX.md**: add an "Auto-update" row (status: Proposal; remaining work:
  Phases 1-3) linking to `docs/plans/AUTO_UPDATE.md`, which would distill this report plus
  the mechanics and industry reports. When it ships, move the behavior into
  `docs/RELEASING.md` / AGENTS and remove the plan, per the INDEX rules (`36-40`).

---

## 10. File-by-file plan and phases

### Phase 1: check, download, verify, manual "Restart to update" (macOS app and Windows installer)

| File | Change |
| --- | --- |
| `src/mtga_tracker/updater.py` (new) | version parser, manifest, asset selection, download/verify, `UpdateManager`, `get_manager()` |
| `src/mtga_tracker/update_api.py` (new) | `handle_get` / `handle_post` |
| `src/mtga_tracker/update_install.py` (new, owned by mechanics agent) | `install_and_restart(plan: InstallPlan) -> None` |
| `src/mtga_tracker/dashboard.py` | GET branch at ~6333; POST branch after 5899 (with Origin/JSON guard) |
| `src/mtga_tracker/settings.py` | `updates` defaults, `AppSettings` fields, `save_update_settings` |
| `src/mtga_tracker/settings_api.py` | `updates` in GET; `/api/settings/updates` POST |
| `src/mtga_tracker/backup.py` | `"updates"` in `LOCAL_SETTINGS_SECTIONS`; `PRE_UPDATE_TAG`; `tag` param on `_prune_safety_backups` |
| `src/mtga_tracker/live_api.py` | `game_activity()`; `deck_native_api.game_in_progress` delegates to it |
| `src/mtga_tracker/paths.py` | `arena_process_running()` (CREATE_NO_WINDOW) |
| `src/mtga_tracker/deck_native_api.py`, `collection_api.py`, `backup_api.py` | `job_active()` / `job_running()` / restore-in-flight flag |
| `src/mtga_tracker/app.py` | `UnifiedLauncher.start_updater`; `--after-update`/`--updated-from`; guard retry; call in `_run_without_gui` |
| `src/mtga_tracker/single_instance.py` | `acquire_with_retry(timeout)` |
| `src/mtga_tracker/menu_app.py` | `update_changed` signal, tray item, toast, `start_updater` call, `QLockFile.tryLock(timeout)` on after-update, updater stop in `shutdown` |
| `ui/src/updateCheck.ts` | delete |
| `ui/src/updateStatus.ts` (new), `ui/src/api.ts` | types, fetch/post helpers, pill model |
| `ui/src/components/UpdateIndicator.tsx` (new), `AppShell.tsx` | expanded and collapsed footer slots, just-updated notice, reload-on-version-change |
| `ui/src/components/SettingsPage.tsx` | Updates section and form |
| `ui/src/styles.css` | `.sidebar-update` states (progress, ready accent), mini icon button |
| `scripts/make_update_manifest.py` (new), `.github/workflows/release.yml`, `scripts/build_macos_installer.sh` | manifest job, prerelease flag, optional `-macos.zip` |
| `.gitignore` | `data/updates/` |
| tests and docs | §8 and §9 |

Phase 1 ships with `auto_install` hidden or disabled in the UI and treated as false by the
manager.

### Phase 2: opt-in auto-install

- Enable the Settings checkbox and the worker's 15 s idle-gate wake while `ready`.
- Add "Install after this game" (`when: "idle"`) for both manual and tray clicks.
- Honor `mandatory` (sticky pill, no skip) and `minimum_version` (link-out).
- Add the `healthy-<version>` marker and the rollback hook with the mechanics agent.
- Optionally make migrations per-step transactional (§6).

### Phase 3: Linux

- `install_kind = "linux"` currently reports `unsupported` with the link-out (the spec does
  not bundle Linux yet, AGENTS packaging note). Once `docs/plans/linux_implementation.md`
  produces an AppImage/tarball, add a `platform: "linux"` asset kind in the manifest script
  and a `select_asset` preference.
- On Linux, the Arena probe looks for the Wine/Proton `MTGA.exe` process (via `pgrep -f`). It
  returns None (unknown, so auto-install is blocked) until that is validated.
- Phase 4 hook: a `channel: "beta"` manifest (`latest-beta.json` hosted on a fixed
  `update-channel` release or on Pages), because `releases/latest` ignores prereleases.
