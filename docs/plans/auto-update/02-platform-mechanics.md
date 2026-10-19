# Auto-update: per-OS mechanics for Tapps Tracker

Research date: 2026-10-11. Repo state: branch `auto-update` @ 7071c74. No repo files were modified.
Legend: **[verified]** = confirmed in official docs or by a local experiment (described inline);
**[doc-inferred]** = follows from the docs but has not been exercised; **[UNVERIFIED]** = must be tested on a real machine before release.

---

## 0. Findings from the repo that shape the design

| Fact | Where | Consequence for the updater |
|---|---|---|
| Installer AppId `{1F54E322-28D9-4929-8292-F5AAAA12CB5F}`, `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed=dialog`, `CloseApplications=yes`, `RestartApplications=no`, `[InstallDelete] {app}\_internal` | `packaging/windows_installer.iss` | Silent upgrade is feasible; `_internal` deletion **requires the app to be fully exited** first |
| **No `ArchitecturesInstallIn64BitMode`** → 32-bit install mode | same | All-users installs go to **`C:\Program Files (x86)\MTGA Tracker`** and the HKLM uninstall key is in the **32-bit registry view** (`WOW6432Node`). Per-user installs go to `%LOCALAPPDATA%\Programs\MTGA Tracker` with the key under HKCU (not redirected) [doc-inferred from https://jrsoftware.org/ishelp/topic_32vs64bitinstalls.htm: "The Uninstall key is created in the 32-bit view of the registry", "{commonpf} is equivalent to {commonpf32}"] |
| Windows overlay ships as `{app}\_internal\overlay\tapps-overlay.exe` (PyInstaller `datas` → `overlay/`) | `packaging/mtga_tracker.spec` | The overlay **also locks files inside `_internal`**; it must be stopped before setup runs |
| macOS overlay is a nested bundle `Contents/Helpers/Tapps Overlay.app` | `scripts/build_macos_app.sh` | It must be stopped before the swap. `OverlayManager._overlay_process_ids` matches overlays by the *argv path*; after a swap, a stale overlay's argv names the **new** bundle path, so the new tracker would adopt it as "already running" and never start the new overlay |
| Ad-hoc signature: designated requirement is `cdhash H"…"` | verified locally: `codesign -d -r- "/Applications/MTGA Tracker.app"` → `designated => cdhash H"12df8375…"` | Every update changes the code identity, so any TCC grant becomes stale (see §6) |
| Single-instance guards: named mutex `Local\TappsTracker.UnifiedLauncher` (Windows) / `flock` on `$TMPDIR/tapps-tracker-<uid>.instance.lock` (POSIX), plus the legacy `QLockFile` `$TMPDIR/mtga-tracker-<uid>.lock` | `single_instance.py`, `menu_app.py` | The OS releases all of them when the process exits. `QLockFile` detects a dead owner PID as stale. A relaunch that races the old process shows the "already running" dialog. The helper must therefore **wait for the PID to exit**, and the new process should retry the guard for about 10 s when started with `--updated-from` |
| Tracker tails Player.log **from EOF** on start (`parser.reset_position()`), and the Brawl queue's authoritative signal is the `EventSetDeckV3` join | `tracker_runtime.py`, AGENTS.md | A restart **while queued or between Bo3 games** loses match-room/queue metadata for the next game. Gate on more than `in_game` (§11) |
| `live_status.in_game = in_match and game_start_time and not match_complete`; `match_complete` flips **per game** | `tracker_analytics.py:150`, `tracker_lifecycle.py` | `in_game` is 0 between Bo3 games. Use `GameState.arena_match_over` for match-level completion |
| Release assets already expose `digest: sha256:…` via the GitHub API | verified: `GET /repos/pattont/MTGA-Tapps/releases/latest` → `MTGA-Tracker-0.6.5.3-setup.exe … sha256:657d0282…` | A free, server-side SHA-256 source exists. A CI `SHA256SUMS.txt` is still recommended |
| Release assets support HTTP Range | verified: `curl -r 0-1023` → 302 to `release-assets.githubusercontent.com` (signed, short-lived URL) → `206`, `accept-ranges: bytes`, `etag` | Resume is possible, but re-request the github.com URL for every attempt because the redirect URL expires. Use `If-Range: <etag>` |
| `ui/src/updateCheck.ts` compares only `major.minor.patch` | `versionTriplet()` | **Bug:** the current release is `v0.6.5.3`, so `0.6.5.3` vs `0.6.5.2` compares equal and no update is shown. The Python updater must use PEP 440 ordering (`packaging.version.Version`, which is **not** currently a dependency; add it or vendor a comparator). Tags like `v0.6.3-rc.8` normalize to `0.6.3rc8` |
| `backup.py` already has `snapshot_database()` (sqlite3 `Connection.backup`, then `journal_mode=DELETE`, truncates `raw_game_payloads`/`live_status`, then `VACUUM`), `_prune_safety_backups(keep=2)`, `SAFETY_DIR_NAME="backups"`, `tracker_active()` | `src/mtga_tracker/backup.py` | Reuse for the pre-update backup (§10) |

---

## WINDOWS

### 1. Silent upgrade with the existing setup.exe

#### Command line (built as a string, not a list, so quoting is exact)

```
"<updates>\MTGA-Tracker-<new>-setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL
    /CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS
    /LOG="%LOCALAPPDATA%\MTGA Tracker\updates\install-<new>.log"
    /CURRENTUSER | /ALLUSERS            <- exactly one, matching the hive of the existing install (see below)
    /WAITPID=<our pid> /RELAUNCH=1 /UPDATEDFROM=<old> /RELAUNCHEXE="<full path of running exe>"
```

Switch semantics (all **[verified]** from https://jrsoftware.org/ishelp/topic_setupcmdline.htm):

- `/VERYSILENT`: no wizard and no progress window. `/SUPPRESSMSGBOXES` only works with silent modes and picks defaults: Yes for "keep newer file", No for overwrite confirmation, **Abort for Abort/Retry**, Cancel for Retry/Cancel. Message boxes from `MsgBox` in `[Code]` are **not** suppressible; only `SuppressibleMsgBox` is. The existing `CurUninstallStepChanged` MsgBox is uninstall-only, so it is fine.
- `/NORESTART`: never reboots. `/SP-`: skips the "This will install…" prompt. `/NOCANCEL`: disables Cancel.
- `/LOG="file"`: overwrites that file. If the log can't be created, Setup aborts. The quoted value is needed because the data dir contains a space.
- `/CLOSEAPPLICATIONS` / `/NORESTARTAPPLICATIONS`: override the directives. RestartApplications only restarts apps registered with `RegisterApplicationRestart` (https://jrsoftware.org/ishelp/topic_setup_restartapplications.htm). We don't register, and we exit before setup runs, so relaunch is done by our own `[Run]` entry (below).
- `/DIR`: **do not pass it.** `UsePreviousAppDir=yes` (default) reuses the previous install location from the uninstall key (https://jrsoftware.org/ishelp/topic_setup_usepreviousappdir.htm). Passing `/DIR` can only cause a second install.
- `/ALLUSERS` / `/CURRENTUSER`: available because `dialog` implies `commandline`. "When one of the command line parameters is used then Setup will not ask the user" (https://jrsoftware.org/ishelp/topic_setup_privilegesrequiredoverridesallowed.htm).
- Without either switch, `UsePreviousPrivileges=yes` (default, effective because `dialog` is allowed) reuses the previous install mode without asking (https://jrsoftware.org/ishelp/topic_setup_usepreviousprivileges.htm). Passing the switch explicitly is still recommended, because **passing the wrong one forces a second install in the other location**. Derive it from the registry hive where the key was found (§2).

#### Per-user vs all-users and UAC
- Per-user install (HKCU key, `%LOCALAPPDATA%\Programs\MTGA Tracker`): fully silent, no UAC, because the installer manifest is `asInvoker` under `PrivilegesRequired=lowest`. **[doc-inferred]**
- All-users install (HKLM 32-bit-view key, `Program Files (x86)`): administrative install mode needs admin rights, so **a UAC consent prompt appears even with /VERYSILENT**. Silent mode can't suppress UAC. **[UNVERIFIED]** The Inno docs don't describe the self-elevation mechanism for `lowest` + `/ALLUSERS`, or the exit code when the user declines UAC. The 6.7.0 notes say "none of Setup's processes are elevated" with `lowest` unless started via Run as administrator (https://jrsoftware.org/files/is6-whatsnew.htm). This must be tested on a real machine. Recommended UX: for an HKLM install, don't auto-install. Show "Windows will ask for permission", then launch the same command (or launch interactive setup with `/SP-` only).
- Don't launch setup with `ShellExecute(runas)` yourself. That would make the `[Run]` relaunch elevated unless `runasoriginaluser` is used (it is, below).

#### Exit codes [verified] (https://jrsoftware.org/ishelp/topic_setupexitcodes.htm)
0 success · 1 failed to initialize (also our `InitializeSetup` returning False **[doc-inferred]**) · 2 cancelled before install · 3 fatal error preparing next phase · 4 fatal error during install · 5 cancelled during install / Abort chosen at Abort-Retry-Ignore (the **/SUPPRESSMSGBOXES default for locked files**) · 6 debugger terminated · 7 Preparing-to-Install says it can't proceed · 8 same as 7 and a restart is needed.
The app has exited by then, so nobody reads the code directly. Our `[Code]` writes the outcome to the log, and the relaunched app reads `install-<new>.log` to show success or failure.

#### CloseApplications / Restart Manager when our app spawned the installer
- With `CloseApplications=yes`, silent Setup "will automatically close and restart such applications" for files that `[Files]` **or `[InstallDelete]`** will update, using the Restart Manager (https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm). Only files matching `CloseApplicationsFilter` are checked. **The default is `*.exe,*.dll,*.chm`** (https://jrsoftware.org/ishelp/topic_setup_closeapplicationsfilter.htm), so the `.pyd` extension modules in `_internal` are ignored. `python3XX.dll` and the Qt DLLs still match.
- The Restart Manager closes GUI apps by sending `WM_QUERYENDSESSION`/`WM_ENDSESSION` with `ENDSESSION_CLOSEAPP` and then `WM_CLOSE`. Console apps get `CTRL_C_EVENT`. Only a *forced* shutdown terminates (https://learn.microsoft.com/en-us/windows/win32/rstmgr/guidelines-for-applications). A tray-only PyQt app has only hidden top-level windows, and how Qt reacts to `ENDSESSION_CLOSEAPP` is untested. **Don't rely on it.**
- **Design: our app exits by itself, and the installer waits for our PID before touching files** (`/WAITPID`, `[Code]` below). Then the Restart Manager finds nothing to close in the normal case. `CloseApplications` stays as a safety net for stragglers: a leftover `tapps-overlay.exe`, or a Deck Finder console window (`MTGA Tracker.exe --deck-finder`), which receives `CTRL_C_EVENT`.
- Before spawning, the updater should list other processes whose image is under `{app}`: `tasklist /FI "IMAGENAME eq MTGA Tracker.exe"` minus our PID, plus `tapps-overlay.exe`. Ask the user to close Deck Finder, or opt into `/FORCECLOSEAPPLICATIONS`, which is acceptable for those two processes.
- Locked-file failure mode if something survives: `DeleteFile failed; code 5/32` → Abort/Retry/Ignore → `/SUPPRESSMSGBOXES` picks **Abort** → exit code 5. `[InstallDelete]` of `_internal` may already have run, which can leave **a broken install** (Inno rolls back `[Files]`, but `[InstallDelete]` removals are not backed up **[doc-inferred]**). Waiting for the PID is therefore mandatory, not optional.

#### Relaunch after a silent install: exact `.iss` changes

```ini
[Setup]
; ...existing directives unchanged (AppId!)...
CloseApplications=yes
RestartApplications=no
; Make Restart Manager also see the Python extension modules in _internal.
CloseApplicationsFilter=*.exe,*.dll,*.pyd,*.chm

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent
; In-app update: relaunch after a successful SILENT install only when the app asked for it.
; runasoriginaluser keeps the tracker un-elevated even if an all-users update elevated Setup.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--updated-from ""{param:UPDATEDFROM|unknown}"""; \
    Flags: nowait runasoriginaluser skipifnotsilent; Check: RelaunchRequested

[Code]
const
  SYNCHRONIZE = $00100000;
  WAIT_OBJECT_0 = 0;

function OpenProcess(dwDesiredAccess: DWORD; bInheritHandle: BOOL; dwProcessId: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle: THandle; dwMilliseconds: DWORD): DWORD;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

var
  InstallStarted, InstallSucceeded: Boolean;

function RelaunchRequested: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function InitializeSetup: Boolean;
var
  Pid: Integer;
  H: THandle;
begin
  Result := True;
  { The tracker passes its own PID and exits. Wait until it is really gone
    (all DLLs in _internal unmapped) before [InstallDelete] runs. }
  Pid := StrToIntDef(ExpandConstant('{param:WAITPID|0}'), 0);
  if Pid > 0 then
  begin
    H := OpenProcess(SYNCHRONIZE, False, Pid);
    if H <> 0 then   { 0 = already exited (or not ours to open) }
    begin
      if WaitForSingleObject(H, 60000) <> WAIT_OBJECT_0 then
      begin
        Log(Format('Tracker PID %d still running after 60s; aborting update.', [Pid]));
        Result := False;
      end;
      CloseHandle(H);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then InstallStarted := True;
  if CurStep = ssPostInstall then InstallSucceeded := True;
end;

procedure DeinitializeSetup;
var
  Exe: String;
  Code: Integer;
begin
  { Install began but failed: try to bring the (possibly old) tracker back so the
    user is not left without it. {app} may be undefined here, so the app passes
    its own path. }
  if RelaunchRequested and InstallStarted and (not InstallSucceeded) then
  begin
    Exe := ExpandConstant('{param:RELAUNCHEXE|}');
    if (Exe <> '') and FileExists(Exe) then
      ExecAsOriginalUser(Exe, '--update-failed', '', SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
{ ...existing body unchanged... }
```

Notes:
- `{param:Name|Default}` reads `/Name=Value` (https://jrsoftware.org/ishelp/topic_consts.htm). Flags are from https://jrsoftware.org/ishelp/topic_runsection.htm. `runasoriginaluser` is only the default *with* `postinstall`, so it must be stated explicitly on the silent entry. `skipifnotsilent` keeps interactive installs on the existing checkbox entry.
- `ExecAsOriginalUser` "can be called during installation but not at uninstall time" (https://jrsoftware.org/ishelp/topic_isxfunc_execasoriginaluser.htm). Calling it from `DeinitializeSetup` is **[UNVERIFIED]**. The docs also don't say whether `DeinitializeSetup` runs after `InitializeSetup` returns False (https://jrsoftware.org/ishelp/topic_scriptevents.htm). The `InstallStarted` guard makes that case a no-op anyway, because the old app may still be running.
- An older installer ignores unknown `/PARAM=` switches, so new switches are safe. Only setups built with these changes honor `/WAITPID` and relaunch. **The first auto-updating release must ship the new .iss.** Its predecessor (the version doing the update) only has to pass the switches.
- A changed install path can't happen when we omit `/DIR` and pass the matching mode. If the user moved the folder manually, the uninstall key is stale. Detect `InstallLocation ≠ running exe dir` and fall back to the download page (§2).
- `[InstallDelete] {app}\_internal` keeps working once the PID wait guarantees exit. The data dir is outside `{app}`, so it is untouched.

#### Detached spawn from Python (Windows)

```python
import ctypes, os, subprocess, sys
from pathlib import Path

DETACHED_PROCESS          = 0x00000008
CREATE_NEW_PROCESS_GROUP  = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
# CREATE_NO_WINDOW is ignored together with DETACHED_PROCESS and is irrelevant
# for setup.exe (a GUI-subsystem exe); /VERYSILENT is what hides the UI.

def _clean_child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # PyInstaller >= 6.9
    app_dir = str(Path(sys.executable).resolve().parent).lower()
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                  if p and not p.lower().startswith(app_dir))
    return env

def spawn_inno_update(setup_exe: Path, log: Path, *, all_users: bool,
                      old: str, new: str) -> None:
    # The bootloader's SetDllDirectoryW(_internal) is inherited by children (and by
    # what *they* spawn, i.e. the relaunched tracker). Undo it first.
    ctypes.windll.kernel32.SetDllDirectoryW(None)
    exe = str(Path(sys.executable).resolve())
    cmd = (f'"{setup_exe}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL '
           f'/CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /LOG="{log}" '
           f'{"/ALLUSERS" if all_users else "/CURRENTUSER"} '
           f'/WAITPID={os.getpid()} /RELAUNCH=1 /UPDATEDFROM={old} /RELAUNCHEXE="{exe}"')
    kwargs = dict(cwd=str(setup_exe.parent), env=_clean_child_env(), close_fds=True,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for attempt in range(5):           # AV may briefly hold the fresh exe (ERROR_SHARING_VIOLATION)
        try:
            try:
                subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError as exc:      # job forbids breakaway -> ERROR_ACCESS_DENIED (5)
                if getattr(exc, "winerror", None) != 5:
                    raise
                subprocess.Popen(cmd, creationflags=flags, **kwargs)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) != 32 or attempt == 4:
                raise
            import time; time.sleep(0.5 * (attempt + 1))
```
After this returns, run the shutdown sequence from §9 and exit 0. `CREATE_BREAKAWAY_FROM_JOB` matters if a launcher put us in a job with `KILL_ON_JOB_CLOSE`; without breakaway, setup would die with us. `SetDllDirectoryW` and `PYINSTALLER_RESET_ENVIRONMENT` are from https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html **[verified]**.

### 2. Detecting an Inno install vs the portable zip

```python
import os, sys, winreg
from pathlib import Path
_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{1F54E322-28D9-4929-8292-F5AAAA12CB5F}_is1"
# NB: the .iss writes AppId={{1F54...}; the doubled brace is Inno escaping. The key name has one brace.

def inno_install_for_running_exe():
    """Return ('user'|'admin', install_dir) when THIS exe is the Inno-installed copy, else None."""
    exe_dir = Path(sys.executable).resolve().parent
    views = ((winreg.HKEY_CURRENT_USER, 0, "user"),
             (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "admin"),   # 32-bit-mode installer
             (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "admin"))   # future 64-bit mode
    for hive, view, mode in views:
        try:
            with winreg.OpenKey(hive, _KEY, 0, winreg.KEY_READ | view) as key:
                location = winreg.QueryValueEx(key, "InstallLocation")[0]   # has a trailing "\"
        except OSError:
            continue
        try:
            if os.path.samefile(location, exe_dir):
                return mode, exe_dir
        except OSError:
            continue
    return None
```
If this returns None, the app is a portable zip, an install moved by hand, or a source run (`not sys.frozen`). In that case **don't swap in place**: show "Update available" with the release page link (the current behavior). The useful value names are `InstallLocation`, `Inno Setup: App Path`, `DisplayVersion`, `UninstallString`, and `Inno Setup: Setup Version`. These standard Inno value names are **[doc-inferred]**; confirm on a real install with `reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{1F54E322-28D9-4929-8292-F5AAAA12CB5F}_is1"`.

### 3. SmartScreen / Mark-of-the-Web / AV
- **MotW:** only MotW-aware clients write `Zone.Identifier` (browsers via `IAttachmentExecute` or directly). curl, WinINET, WinHTTP and script downloads don't, by design. Python urllib/requests also don't (they use plain sockets). Source: Eric Lawrence (former IE/Edge PM), https://textslashplain.com/2016/04/04/downloads-and-the-mark-of-the-web/ **[verified-by-reference]**.
- **SmartScreen:** the same source says "The CreateProcess API does not care about the MotW". SmartScreen reputation prompts happen on the ShellExecute/Explorer path. Launching setup.exe with `subprocess.Popen` (CreateProcess) on a file without MotW shows **no SmartScreen prompt**. (`os.startfile` is ShellExecute; don't use it.)
- **Defender Block-at-First-Sight** "only uses the cloud protection backend for executable files … downloaded from the Internet, or that originate from the Internet zone" (https://learn.microsoft.com/en-us/defender-endpoint/configure-block-at-first-sight-microsoft-defender-antivirus) **[verified]**. Normal real-time scanning and ML heuristics still scan the file on write and execute. An unsigned PyInstaller app that downloads an unsigned exe into `%LOCALAPPDATA%` and runs it silently looks like a dropper and can be flagged (`Wacatac!ml`-style), even though the bootloader is rebuilt from source. Mitigations: download over HTTPS from github.com only; keep a visible user action or notification; write the log; never use `-WindowStyle Hidden` PowerShell or cmd helpers (very high heuristic weight; the plan above uses none); verify SHA-256; and above all **code-sign** both the app and setup.exe (Azure Trusted Signing or similar), which is the only durable fix.
- **Smart App Control** (Win 11): "If a file can't be verified or isn't properly signed, Smart App Control blocks it" (https://support.microsoft.com/en-US/Windows/Security/Threat-Malware-Protection/smart-app-control-has-blocked-part-of-this-app). Users with SAC on presumably can't run the unsigned tracker at all, so the updater won't be the first thing blocked. **[UNVERIFIED]** whether SAC evaluates a no-MotW unsigned child exe; assume yes.

### 4. Download location, cleanup, space, resume
- Stage in `DATA_DIR / "updates"` = `%LOCALAPPDATA%\MTGA Tracker\updates\` (frozen `DATA_DIR` per `paths._installed_app_data_dir`). It is never inside `{app}`, so `[InstallDelete]` can't hit it, and it survives the upgrade. The uninstaller's optional DelTree of `{localappdata}\MTGA Tracker` also cleans it.
- Write to `<name>.part`, fsync, verify SHA-256, then `os.replace` to the final name. Re-hash right before spawning (cheap at about 38 MB).
- Keep only the current target. Delete other `*-setup.exe`, `*.part` and `install-*.log` files older than the previous one when a newer version starts successfully (the `--updated-from` launch).
- Free-space check with `shutil.disk_usage`: on the updates drive, need ≥ asset size × 1.1. On the `{app}` drive (normally the same), need ≥ about 3× the installed size (old `_internal` deletion, new files, Inno temp in `%TEMP%`). On the data drive, need ≥ the DB size for the pre-update backup.
- Resume: optional. Assets are 38–51 MB. Range works (verified above), but the 302 target is a signed short-lived URL. If resume is implemented, always start from the `github.com/.../releases/download/...` URL and send `Range: bytes=<n>-` plus `If-Range: <etag from first response>`. A `200` instead of `206` means start over. Simpler acceptable alternative: retry the whole download up to 3 times with backoff.

---

## MACOS

### 5. Replacing a running ad-hoc signed .app

**Recommendation: CI should publish a zip of the .app for updates, next to the DMG.** It is created with:
```bash
# in build_macos_installer.sh (or a new step), after codesign --verify passes
cd dist && ditto -c -k --norsrc --noextattr --noacl --noqtn --keepParent \
    "MTGA Tracker.app" "MTGA-Tracker-${VERSION}-macos.zip"
shasum -a 256 "MTGA-Tracker-${VERSION}-macos.zip"
```
and extracted by the app with **`/usr/bin/ditto -x -k --noqtn <zip> <stagedir>`**.

Local experiments on macOS 27.0.1 (APFS), using a copy of the installed `/Applications/MTGA Tracker.app` (90 MB, 63 symlinks):
- `ditto -c -k --sequesterRsrc --keepParent` round trip: `codesign --verify --deep --strict` → *valid on disk / satisfies its Designated Requirement*, 63 symlinks kept. **But it also carried the source's `com.apple.quarantine` on 370 inner files** (stored in `__MACOSX`).
- `ditto -c -k --norsrc --noextattr --noacl --noqtn --keepParent` round trip: signature valid, **0 quarantine xattrs, no `__MACOSX`**. This is the recommended form.
- `/usr/bin/zip -r` (no `-y`) + `unzip`: **0 symlinks, signature broken** ("In subcomponent: …QtNetwork.framework").
- **Python `zipfile.extractall`** on the good zip: **0 symlinks, signature broken.** The app must extract with `ditto`, never with `zipfile`/`shutil.unpack_archive`.

Swap mechanics:
- **A running app's bundle can be renamed.** Verified: renamed a bundle while its Mach-O executable was running; the process kept running and exited 0. Open files and mapped images keep their vnodes. But **the old process must not keep running after the swap**: PyInstaller's onedir loads modules lazily from `Contents/Frameworks`/`Resources` by path, and the dashboard serves `ui/dist` by path. Both would silently read the *new* version's files. So the helper swaps **only after the PID has exited.**
- **Same volume:** on this Mac, `/Applications`, `/tmp` and `~/Library/...` are all on `disk3s5` (the Data volume), so `rename(2)` is atomic. Stage under `~/Library/Application Support/MTGA Tracker/updates/`. If `st_dev` differs (home on another volume), stage in a hidden directory next to the target instead (`/Applications/.tapps-update-<ver>/`). `renamex_np(RENAME_SWAP)` exists for a true atomic swap ("Source and target need not be of the same type", from `man 2 rename`) but has no CLI. Two `mv`s with rollback is fine for a 0-ms window.
- **Where the app may live:** derive the bundle with `startup._macos_app_bundle()`. Refuse in-place update when the path is under `/Volumes/` (running from the DMG), contains `/AppTranslocation/` (Gatekeeper App Translocation; path begins `/private/var/folders/`), or the parent dir is not writable (`os.access(parent, os.W_OK)`). `~/Applications` is fine. For a refused path, show "Move Tapps Tracker to Applications, then update" or open the release page.
- **Permissions:** `/Applications` is `drwxrwxr-x root:admin` (verified), so admin-group users can rename entries in it and standard users can't. The bundle itself is owned by whoever installed it. For standard users, fall back to the release page. An `osascript … with administrator privileges` path is possible (the collection exporter already uses that pattern) but not recommended for auto-update.
- **App Management (macOS 13+): [UNVERIFIED]** Ventura added a TCC-style "App Management" protection that blocks modifying app bundles by code not from the same developer team, unless allowed via `NSUpdateSecurityPolicy` (https://lapcatsoftware.com/articles/AppManagement.html, https://redcanary.com/blog/mac-application-bundles/). Public material discusses notarized/Developer-ID apps. I could not confirm how an **ad-hoc, team-less** app updating **its own** bundle is treated, or whether renaming the *whole* bundle (a directory-entry change in `/Applications`) counts as modification. The helper below renames whole bundles and never writes inside one. It also treats an `mv` failure (`EPERM`, "Operation not permitted") as "fall back to manual update" and restores the old bundle. **Test on macOS 14, 15, 26 and 27 with a DMG-installed (provenance-tagged) copy before shipping.**

#### Helper script (tested)
Spawn it detached from the app, then exit:
```python
import os, subprocess, sys
env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_")}
env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
subprocess.Popen(["/bin/bash", str(script), str(os.getpid()), str(staged_app), str(target_app),
                  str(rollback_dir), old_version, new_version, "com.travispatton.mtgatracker"],
                 stdin=subprocess.DEVNULL, stdout=log_fh, stderr=subprocess.STDOUT,
                 start_new_session=True, close_fds=True, env=env, cwd="/")
```
Write the script into `DATA_DIR/updates/` from a string embedded in the Python module, not from the download, and run it from there.

```bash
#!/bin/bash
# Tapps Tracker macOS update helper. Spawned detached by the running app,
# which then exits. Usage:
#   tapps_mac_swap.sh <parent_pid> <staged_app> <target_app> <rollback_dir> <old_ver> <new_ver> [bundle_id]
# Exit codes: 0 swapped+relaunched, 10 parent never exited, 11 staged bundle
# invalid, 12 cross-volume, 13 could not move old aside, 14 could not move new
# in (rolled back), 15 overlay helper still running.
set -u
PARENT_PID="$1"; STAGED="$2"; TARGET="$3"; ROLLBACK_DIR="$4"
OLD_VER="$5"; NEW_VER="$6"; BUNDLE_ID="${7:-com.travispatton.mtgatracker}"
WAIT_SECONDS="${TAPPS_SWAP_WAIT_SECONDS:-60}"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
PLISTBUDDY=/usr/libexec/PlistBuddy

log() { printf '%s %s\n' "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

relaunch() {  # $@ = args after --args
  [ -n "${TAPPS_SWAP_NO_LAUNCH:-}" ] && { log "relaunch suppressed: $*"; return 0; }
  "$LSREGISTER" -f "$TARGET" >/dev/null 2>&1 || true
  /usr/bin/open -n "$TARGET" --args "$@"
}

# 1. Wait for the old process to be fully gone (all files closed).
deadline=$(( $(/bin/date +%s) + WAIT_SECONDS ))
while /bin/kill -0 "$PARENT_PID" 2>/dev/null; do
  if [ "$(/bin/date +%s)" -ge "$deadline" ]; then
    log "parent $PARENT_PID still running after ${WAIT_SECONDS}s; not swapping"; exit 10
  fi
  /bin/sleep 0.2
done
log "parent $PARENT_PID exited"

# 2. The overlay helper lives inside the bundle being replaced. The app stops
#    it before exiting; anything left is terminated so the new tracker does not
#    mistake a stale overlay (whose argv path now names the NEW bundle) for its own.
OVERLAY_EXE="$TARGET/Contents/Helpers/Tapps Overlay.app/Contents/MacOS/tapps-overlay"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  pids=$(/usr/bin/pgrep -f "^$OVERLAY_EXE" || true)
  [ -z "$pids" ] && break
  /bin/kill -TERM $pids 2>/dev/null || true
  /bin/sleep 0.3
done
if [ -n "$(/usr/bin/pgrep -f "^$OVERLAY_EXE" || true)" ]; then log "overlay still running"; exit 15; fi

# 3. Validate the staged bundle (signature, identity, version).
if ! /usr/bin/codesign --verify --deep --strict "$STAGED" 2>/dev/null; then
  log "staged bundle fails codesign verification"; relaunch --update-failed "$NEW_VER"; exit 11
fi
sid=$("$PLISTBUDDY" -c 'Print :CFBundleIdentifier' "$STAGED/Contents/Info.plist" 2>/dev/null)
sver=$("$PLISTBUDDY" -c 'Print :CFBundleShortVersionString' "$STAGED/Contents/Info.plist" 2>/dev/null)
if [ "$sid" != "$BUNDLE_ID" ] || [ "$sver" != "$NEW_VER" ]; then
  log "staged bundle identity mismatch: $sid $sver"; relaunch --update-failed "$NEW_VER"; exit 11
fi
/usr/bin/xattr -dr com.apple.quarantine "$STAGED" 2>/dev/null || true

# 4. Renames must stay on one volume to be atomic.
/bin/mkdir -p "$ROLLBACK_DIR"
if [ "$(/usr/bin/stat -f %d "$STAGED")" != "$(/usr/bin/stat -f %d "$(/usr/bin/dirname "$TARGET")")" ] || \
   [ "$(/usr/bin/stat -f %d "$ROLLBACK_DIR")" != "$(/usr/bin/stat -f %d "$(/usr/bin/dirname "$TARGET")")" ]; then
  log "staging/rollback dir not on the target volume"; relaunch --update-failed "$NEW_VER"; exit 12
fi

# 5. Swap: old -> rollback, staged -> target. Roll back on failure.
ROLLBACK_APP="$ROLLBACK_DIR/$(/usr/bin/basename "$TARGET")"
/bin/rm -rf "$ROLLBACK_APP"
if ! /bin/mv "$TARGET" "$ROLLBACK_APP"; then
  log "cannot move old bundle aside (permissions/App Management?)"; relaunch --update-failed "$NEW_VER"; exit 13
fi
if ! /bin/mv "$STAGED" "$TARGET"; then
  log "cannot move new bundle into place; restoring old"
  /bin/mv "$ROLLBACK_APP" "$TARGET"
  relaunch --update-failed "$NEW_VER"; exit 14
fi
/usr/bin/touch "$TARGET"
log "swapped $OLD_VER -> $NEW_VER"

# 6. Relaunch the new version. The rollback copy is deleted by the new
#    version once it has started cleanly (or on the next update).
relaunch --updated-from "$OLD_VER"
exit 0
```
Tested (with `TAPPS_SWAP_NO_LAUNCH=1`) on dummy ad-hoc-signed bundles in `/tmp`. Happy path: waited for a live 3-second parent, swapped 1.0.0→1.1.0, kept the rollback, exit 0. Tampered bundle (Info.plist edited after signing): rejected with exit 11, target untouched. The `open -n`/`lsregister` relaunch path was **not** exercised against the real app. The script is at [`tapps_mac_swap.sh`](tapps_mac_swap.sh) beside this report.

Caveats:
- `codesign --verify` only proves internal consistency. Anyone can ad-hoc sign. **Authenticity comes from the SHA-256 of the downloaded zip**, so verify it before extracting.
- Keep the rollback copy in `updates/rollback/`, not in `/Applications`, where Spotlight/Launchpad would show two apps. The new version deletes it after it has run about 60 s healthy.
- Pass `--updated-from` only on success. Both new flags (`--updated-from`, `--update-failed`) must be declared in `app.main()`'s argparse, which currently `error()`s on unknown flags. That is safe because only an updater-capable version ever spawns the helper or installer, so the *old* binary that receives `--update-failed` on rollback (and the new one that receives `--updated-from`) both know the flags. Never pass them to a version older than the first updater-capable release.

### 6. Quarantine, Gatekeeper, TCC, login item
- **Quarantine:** unsandboxed apps don't quarantine files they create unless their Info.plist sets `LSFileQuarantineEnabled=true` (default false) or CoreTypes' exception list names them (https://eclecticlight.co/2025/12/08/who-decides-to-quarantine-files/; Apple key reference https://developer.apple.com/documentation/bundleresources/information-property-list/lsfilequarantineenabled). Our spec doesn't set the key. **Verified locally:** a file downloaded with Python `urllib.request.urlretrieve` had **no** `com.apple.quarantine` (only `com.apple.provenance`). The defensive `xattr -dr com.apple.quarantine` in the script still matters for one case: building the zip with `--sequesterRsrc` from a quarantined bundle (shown above) would carry quarantine inside.
- **Provenance:** `com.apple.provenance` is attached to files written by a provenance-tracked app (one that passed Gatekeeper first-run). It identifies the writer, is not a Gatekeeper trigger, and can't be stripped (https://eclecticlight.co/2025/12/05/quarantine-macl-and-provenance-what-are-they-up-to/, https://eclecticlight.co/2023/05/10/how-macos-now-tracks-the-provenance-of-apps/). Expect it on the staged bundle. It is harmless.
- **Gatekeeper:** with no quarantine xattr, launching the replaced ad-hoc app via `open` gets no first-run assessment or "Open Anyway" dialog. **[doc-inferred; UNVERIFIED on macOS 26/27 end-to-end]** If quarantine were present, an ad-hoc non-notarized app would hit the hard "Not Opened" dialog, which is why the zip must be built with `--noqtn` and the script strips it.
- **TCC: grants do NOT survive an ad-hoc update.** The designated requirement is `cdhash H"…"` (verified above). TCC stores the client's code requirement, so a new build fails the match. System Settings may still show the toggle on while access is denied (community reports: https://github.com/pathorsAI/parley/issues/75, https://github.com/shlgd/SuperDictate/issues/19, https://github.com/YARC-Official/YARG/issues/1695; no Apple doc found). Impact here:
  - **Overlay:** designed to need **no** TCC permission (`arena.rs`: `lsappinfo`, and CGWindowList bounds without window names). `global-hotkey` on macOS uses Carbon `RegisterEventHotKey`, which needs no Accessibility **[doc-inferred]**. **No overlay impact today.** Any future feature needing Accessibility or Screen Recording would re-prompt after every update.
  - **Tracker:** Deck Finder's "open in Terminal" uses `osascript` → Terminal (Automation/AppleEvents TCC), which re-prompts after each update. A user-chosen backup folder under `~/Documents`, `~/Desktop` or `~/Downloads` (Files & Folders TCC) also re-prompts. Native Deck Manager (Frida attach) and collection export (`task_for_pid` via an admin `osascript` helper) should be re-tested after an update **[UNVERIFIED]**.
  - **Fix:** sign every release with one **stable self-signed (or Developer ID) certificate** via the existing `MACOS_SIGN_IDENTITY` hook. The DR becomes `identifier "com.travispatton.mtgatracker" and certificate leaf = H"…"`, which survives updates. CI needs the p12 as a secret. A self-signed certificate is not trusted by Gatekeeper, so first-install UX should equal ad-hoc **[UNVERIFIED]**. Stale TCC rows can be cleared with `tccutil reset All com.travispatton.mtgatracker`.
- **Login item:** `startup.py` writes `~/Library/LaunchAgents/com.travispatton.mtgatracker.startup.plist` with `ProgramArguments=[/usr/bin/open, -g, <bundle path>, --args, --login-start]`. The bundle path is unchanged by an in-place swap, so the **registration survives**. The executable there is Apple's `/usr/bin/open`, so the cdhash change doesn't matter. (Windows: the HKCU `Run` value stores the exe path, also unchanged.) As a safety net, on `--updated-from` the new version should re-assert registration if `settings.startup` says enabled but `registration_status().registered` is False.

### 7. DMG vs zip
**Prefer the zip** (above): one `ditto -x` and no mount state to clean up.
DMG fallback for releases without a zip (works; ad-hoc DMG, no SLA):
```bash
MNT=$(mktemp -d "$UPDATES/mnt.XXXX")
hdiutil attach -nobrowse -noautoopen -noverify -readonly -mountpoint "$MNT" "$DMG" -quiet
ditto --noqtn "$MNT/MTGA Tracker.app" "$STAGE/MTGA Tracker.app"
hdiutil detach "$MNT" -quiet || hdiutil detach "$MNT" -force -quiet
```
(`-nobrowse` hides it from Finder; `-noverify` is fine because we SHA-256 the DMG first. Flags checked against local `man hdiutil`.) Risks: detach failures from open handles (Spotlight/mds) and leftover mounts after a crash.

---

## LINUX (forward-looking)

### 8. Where an updater fits the Linux plan
`docs/plans/linux_implementation.md` §7 plans a **onedir tarball first, then an AppImage**, a no-root install into `~/.local/share/tapps-tracker` with a `~/.local/bin` launcher and `.desktop` entry, published SHA256 checksums, and "refuse to replace an active running installation without a user-directed shutdown".
- **Tarball install:** reuse the macOS design: download, SHA-256, extract with `tar` (preserves symlinks and modes), stage in `~/.local/share/tapps-tracker.update-<ver>/` (same filesystem), wait for the PID, `mv` the old dir to `updates/rollback`, `mv` the new one in, then relaunch via the launcher script. Children must use `LD_LIBRARY_PATH_ORIG` (PyInstaller).
- **AppImage:** the running AppImage is FUSE-mounted from its inode, so writing `new.AppImage.part` next to `$APPIMAGE`, `chmod +x`, and `rename()` over it is atomic and safe. Then relaunch `$APPIMAGE`. AppImageUpdate/zsync is optional. `appimagetool -u "gh-releases-zsync|pattont|MTGA-Tapps|latest|tapps-tracker-*-x86_64.AppImage.zsync"` embeds update info and generates `.zsync` for delta updates. By default AppImageUpdate writes a new file rather than overwriting, and with overwrite it keeps `*.zs-old` and "will never overwrite a file before all validation mechanisms report success" (https://docs.appimage.org/packaging-guide/optional/updates.html). Recommendation: do a full-file download plus SHA-256 plus rename in-app (one code path for all OSes); publish `.zsync` too, so users of external AppImage updaters get deltas for free.
- Never self-update distro packages or a Flatpak build. Detect via `$APPIMAGE`, `$FLATPAK_ID`, or install-dir ownership.

---

## CROSS-PLATFORM

### 9. Process handoff ordering

Run on the Qt main thread, as `MenuBarController.apply_update()`. The GUI-less `--no-gui` path never auto-installs.
1. **Gate** (§11): refuse if a game, match, queue, native deck transfer, or collection export is active.
2. **Lock the UI:** `self._updating = True`; disable the menu; set the tray tooltip to "Updating…".
3. **Re-verify the artifact:** SHA-256 again; on macOS, the staged bundle `codesign --verify` (fast fail before stopping anything).
4. **Stop the overlay:** `self.overlay.stop()` (SIGTERM / TerminateProcess). **Don't** persist `enabled=False`. Exit code 23 is reserved for the user's own "Quit overlay"; a SIGTERM exit isn't 23, so `refresh()` won't flip the setting, and the new version restarts the overlay because `overlay.enabled` is still true. On macOS this also prevents the stale-argv-path adoption problem (§0).
5. **Stop the tracker:** `self.launcher.stop_tracker(timeout=5)`. The tracker thread's `finally: self.analytics.close()` commits, and `mark_live_status_stopped` runs. If the thread is still alive after the timeout, abort the update and restart the tracker; never hard-exit mid-write.
6. **Stop the dashboard:** `self.launcher.stop_dashboard()`. This kills `/api/overlay` polling and request threads.
7. **Checkpoint and back up the DB** (§10): `PRAGMA wal_checkpoint(TRUNCATE)` on a fresh connection, then the online-backup copy. If the backup fails (disk full), abort and restart the services.
8. **Spawn the detached installer/helper** with our PID (Windows `spawn_inno_update`, macOS bash helper). If the spawn fails, restart the services and report the error.
9. **Release the guards early** (optional; the OS does it at exit anyway): `app._mtga_instance_lock.unlock()`. The `SingleInstanceGuard` is released by `app.main()`'s `finally`.
10. **Exit 0:** `QApplication.exit(0)`. `aboutToQuit` runs `shutdown()`, which is idempotent (`_shutting_down`). `run_menu_app` returns 0 and `main()` releases the guard. Also arm a daemon `threading.Timer(15, os._exit, (0,))` as a backstop in case some non-daemon thread (Deck Finder or collection jobs) keeps the interpreter alive. The installer/helper wait is bounded at 60 s, so a hung exit means "update aborted" rather than corruption.
11. **New version starts with `--updated-from <old>`:** retry `SingleInstanceGuard.acquire()` and `QLockFile.tryLock` for up to 10 s instead of showing the "already running" box. Migrations run inside `AnalyticsStore.connect()`. Then delete the rollback copy and old downloads after about 60 s of healthy runtime, and show "Updated to X".

Pitfalls:
- **Windows onedir:** the running process maps `MTGA Tracker.exe`, `python3XX.dll`, Qt DLLs and `.pyd` files from `_internal`. `[InstallDelete] {app}\_internal` fails with sharing violations unless the process (and the overlay, and any `--deck-finder` console) is gone. The `/WAITPID` wait in `InitializeSetup` runs **before** `[InstallDelete]`. The Restart Manager is only a fallback.
- **Don't relaunch with `sys.executable` directly** from the old process. On Windows the installer's `[Run]` does it, and on macOS `open` does. If you ever must, set `PYINSTALLER_RESET_ENVIRONMENT=1` and strip `_PYI_*` (PyInstaller ≥ 6.9 requirement, see the URL above).
- **Wait-for-PID per OS:** Windows: `OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject` inside Inno (PID reuse can't fool a handle opened while the old process still exists; if it has already exited, `OpenProcess` fails and we proceed). macOS/Linux: a `kill -0` loop. PID reuse within the 60 s window is theoretically possible; check `ps -p $PID -o comm=` matches `MTGA Tracker` for extra safety.
- Releasing the mutex or flock early doesn't make file replacement safe. Only full process exit does.

### 10. Pre-update DB safety
Existing code to reuse (`src/mtga_tracker/backup.py`):
- `snapshot_database(db_path, dest)`: read-only URI source plus `busy_timeout`, `source.backup(dest)` (sqlite3 online backup API), then `journal_mode=DELETE`. It also **empties `raw_game_payloads` and `live_status` and VACUUMs** (meant for portable backups).
- `_prune_safety_backups(folder, keep=2)`: keeps the 2 newest `*-pre-restore*.tappsbackup` by name. `restore_backup()` writes a `pre-restore` safety backup to `DATA_DIR/backups`.
- `tracker_active()`: live_status heartbeat within 20 s.
- `dashboard.py:3609`: the reset path also uses `conn.backup(...)`.

Proposed helper (a new function in `backup.py`; full fidelity, so no truncation):
```python
def pre_update_backup(db_path: Path, old: str, new: str, keep: int = 2) -> Path:
    folder = Path(db_path).parent / SAFETY_DIR_NAME            # DATA_DIR/backups
    folder.mkdir(parents=True, exist_ok=True)
    need = Path(db_path).stat().st_size * 1.2
    if shutil.disk_usage(folder).free < need:
        raise BackupError("Not enough disk space for the pre-update backup", "disk-space")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = folder / f"pre-update-{stamp}-{old}-to-{new}.sqlite3"   # timestamp first => name sort = age sort
    tmp = dest.with_suffix(".sqlite3.part")
    src = sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=30.0)
    try:
        src.execute("PRAGMA busy_timeout = 30000")
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
            out.execute("PRAGMA journal_mode = DELETE")
            if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise BackupError("Pre-update backup failed its integrity check", "backup-corrupt")
        finally:
            out.close()
    finally:
        src.close()
    os.replace(tmp, dest)
    for stale in sorted(folder.glob("pre-update-*.sqlite3"), reverse=True)[keep:]:
        stale.unlink(missing_ok=True)
    return dest
```
(Or call `export_backup(..., tag=f"pre-update-{old}-to-{new}", record=False)` to get a restorable `.tappsbackup` that the existing Restore UI already understands. **Recommended**, because recovery then goes through the existing, tested restore flow. Note it drops the 30-day raw payload archive, which is acceptable.)

**How `apply_pending_migrations` behaves on failure** (`analytics.py:685`):
- The loop runs `migrate(conn)`, then `INSERT OR IGNORE INTO schema_migrations`, with **one `conn.commit()` at the end**. It looks atomic but **is not**:
  - Python's `sqlite3` legacy transaction control implicitly opens a transaction only before INSERT/UPDATE/DELETE/REPLACE. DDL issued while no transaction is open autocommits immediately.
  - `executescript()` **commits any pending transaction first** (used by v33 and v34).
  - Several migrations commit internally (`conn.commit()` at lines 889, 922, 957; `with conn:` at line 2062).
  - So a failure in migration N leaves migrations < N (and parts of N) committed, without N's `schema_migrations` row. N re-runs next launch, which is why each migration must be idempotent (AGENTS.md already demands this for v33–35).
- The exception propagates out of `AnalyticsStore.connect()` → `UnifiedLauncher.start_dashboard()` → `MenuBarController.start()` catches it and shows a critical message box. The uncommitted remainder rolls back when the process exits.
- **No downgrade path:** an older build ignores unknown higher `schema_migrations` versions and runs against the newer schema (additive columns usually work, but data migrations can't be undone). `backup.inspect_backup` refuses snapshots newer than `supported_schema_version()`. **The pre-update backup is the only recovery path.** Surface it in the "update failed" UI: "Restore pre-update backup", which opens the existing restore flow with that file. Retention 2 = the last two updates.
- Optional hardening (separate change): run each migration as `conn.execute("BEGIN")` … `commit()` with `isolation_level=None`, and replace `executescript` in v33/v34 with individual `execute` calls. Then a failure rolls back exactly one migration.

### 11. "Is a game in progress?" and gating the restart
The dashboard runs **in the same process** as the tracker under `app.py`, which passes `tracker_control=self` (the `UnifiedLauncher`) to `create_dashboard_server`. Prefer in-memory state and use the DB as a fallback.

```python
UPDATE_SETTLE_SECONDS = 90
def update_block_reason(launcher, db_path) -> str | None:
    t = launcher.tracker
    if t is not None:
        g = t.game_state
        if g.in_match and g.game_start_time and not g.match_complete:
            return "A game is in progress."
        if g.in_match and g.match_type == "best_of_3" and not g.arena_match_over:
            return "Between games of a best-of-three match."
        if getattr(t, "waiting_for_next_game", False):
            return "Tracker attached mid-game; waiting for it to finish."
        if g.authoritative_event_id and not g.in_match:     # queued / event joined, match not started
            return "Queued for a match."                     # (needs a staleness timeout, ~10 min)
        ended = g.game_end_time
        if ended and (t._now() - ended).total_seconds() < UPDATE_SETTLE_SECONDS:
            return "A game just ended; waiting for results to be saved."
    # DB fallback (also what a standalone dashboard process would use)
    from .deck_native_api import game_in_progress, status as native_status
    if game_in_progress(db_path) and backup.tracker_active(db_path):
        return "A game is in progress."
    if native_status(db_path).get("busy") or native_status(db_path).get("pending_transfers"):
        return "A Deck Manager transfer is running."
    # + collection export job running (collection_api) -> block
    return None
```
- `live_status.in_game` + `updated_at` freshness (< 20 s, `live_api.OFFLINE_AFTER_SECONDS` / `backup.TRACKER_ACTIVE_WITHIN_SECONDS`) is the DB signal; `deck_native_api.game_in_progress()` already reads it read-only. A stale `in_game=1` with an old heartbeat means the tracker is dead, so it doesn't block.
- **`in_game` alone is insufficient:** it is 0 between Bo3 games, and the tracker restarts from EOF, so a restart there loses match-room/queue metadata. Hence the `arena_match_over` and queued checks. The `authoritative_event_id` lifecycle (when it is cleared) should be confirmed in `tracker_lifecycle.py` before relying on it.
- **Menu-app gating:** a `QTimer` (5 s) calls `update_block_reason()`. If it returns None, "Restart to update to vX" is enabled; otherwise it is disabled with the reason as the label suffix. With auto-install opted in, or after the user clicks "Install when safe", arm `_pending_install` and start the §9 sequence when the reason has been None for 2 consecutive ticks. Best moments to auto-apply: **(a) at app start**, before `start_tracker()`, if a verified staged update exists and Arena's process isn't running; **(b) on Quit** ("Install update and quit" without relaunch). Both avoid interrupting a session.
- Expose the reason in an `/api/update/status` payload so the dashboard banner shows the same state. The install trigger should be a POST that only *requests* installation; the Qt thread performs it.

---

## Open items to verify on real hardware
1. Inno: a silent `/ALLUSERS` upgrade of an HKLM install: UAC prompt shown? Exit code when declined? Does `DeinitializeSetup` + `ExecAsOriginalUser` work after a mid-install failure? Does `InitializeSetup=False` give exit code 1?
2. Inno: confirm the uninstall value names and that HKLM lands in `WOW6432Node` (32-bit mode).
3. Windows Defender reaction to the download-and-silent-run pattern on a clean Win 11 VM with cloud protection on; Smart App Control behavior.
4. macOS App Management: can the ad-hoc, team-less app (via its bash helper) rename `/Applications/MTGA Tracker.app` on macOS 14, 15, 26 and 27 when the bundle is provenance-tagged from a DMG install?
5. macOS: an end-to-end `open -n` relaunch of a swapped ad-hoc bundle produces no Gatekeeper prompt; LaunchServices picks up the new version (`lsregister -f`).
6. TCC: Automation re-prompt for Deck Finder's Terminal launch after an update; Frida native deck attach and collection export after an update.
7. Self-signed stable identity: first-install Gatekeeper UX is no worse than ad-hoc.
