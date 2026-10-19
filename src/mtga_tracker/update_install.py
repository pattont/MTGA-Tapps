"""Per-OS update hand-off: detect how this copy was installed, stage the
verified payload, and spawn a detached installer/helper that waits for this
process to exit before it touches any file.

- Windows (Inno Setup installs only): the next `setup.exe` runs silently with
  `/WAITPID=<our pid>`; the installer's own `[Run]` entry relaunches the app.
- macOS (`.app` bundles): the zip is extracted with `ditto`, verified with
  `codesign`, and an embedded bash helper swaps the bundles after we exit.
- Everything else links out to the release page.

Nothing here runs at import time, and the updater calls into this module
only after the user (or their opted-in auto-install) asked for an install.
See docs/plans/auto-update/02-platform-mechanics.md.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .updater_manifest import is_release_build, versions_equal

BUNDLE_ID = "com.travispatton.mtgatracker"
INNO_APP_ID = "{1F54E322-28D9-4929-8292-F5AAAA12CB5F}"
_UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
INNO_UNINSTALL_KEY = _UNINSTALL_ROOT + "\\" + INNO_APP_ID + "_is1"

_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

#: Relaunch flags the next version understands (declared in app.main()).
AFTER_UPDATE_FLAG = "--after-update"
UPDATED_FROM_FLAG = "--updated-from"
UPDATE_FAILED_FLAG = "--update-failed"


class InstallError(Exception):
    def __init__(self, message: str, code: str = "install-failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InstallInfo:
    """How this running copy was installed, and whether it can self-update."""

    kind: str  # macos-app | windows-installer | windows-portable | source | linux | unknown
    can_install: bool
    reason: Optional[str] = None
    app_path: Optional[Path] = None
    executable: Optional[Path] = None
    #: Windows Inno install mode: "user" (HKCU) or "admin" (HKLM, needs UAC).
    install_mode: Optional[str] = None

    @property
    def needs_elevation(self) -> bool:
        return self.install_mode == "admin"


@dataclass(frozen=True)
class InstallPlan:
    asset_path: Path
    asset_kind: str  # app-zip | dmg | inno-setup
    install_kind: str
    from_version: str
    to_version: str
    parent_pid: int
    updates_dir: Path
    app_path: Optional[Path] = None
    executable: Optional[Path] = None
    log_path: Optional[Path] = None
    #: False for "Install update and quit": swap/install, do not relaunch.
    relaunch: bool = True
    all_users: bool = False
    bundle_id: str = BUNDLE_ID
    #: Filled by prepare_install on macOS.
    staged_app: Optional[Path] = None
    staged_version: Optional[str] = None
    rollback_dir: Optional[Path] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# --- detection ------------------------------------------------------------------


RegistryReader = Callable[[str, str], Optional[str]]


def _windows_registry_reader(hive: str, view: str) -> Optional[str]:
    """InstallLocation from the Inno uninstall key in one hive/view."""
    import winreg  # type: ignore[import-not-found]

    hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    views = {
        "default": 0,
        "32": getattr(winreg, "KEY_WOW64_32KEY", 0x0200),
        "64": getattr(winreg, "KEY_WOW64_64KEY", 0x0100),
    }
    try:
        with winreg.OpenKey(
            hives[hive], INNO_UNINSTALL_KEY, 0, winreg.KEY_READ | views[view]
        ) as key:
            value = winreg.QueryValueEx(key, "InstallLocation")[0]
    except OSError:
        return None
    return str(value) if value else None


#: (hive, registry view, install mode) in lookup order: per-user first, then
#: the 32-bit HKLM view the current installer writes, then a future 64-bit one.
_INNO_LOOKUPS = (("HKCU", "default", "user"), ("HKLM", "32", "admin"), ("HKLM", "64", "admin"))


def _same_dir(left: Any, right: Path, samefile: Callable[[Any, Any], bool]) -> bool:
    try:
        return bool(samefile(str(left).rstrip("\\/") or str(left), str(right)))
    except OSError:
        return False


def inno_install_mode(
    executable: Path,
    *,
    reader: Optional[RegistryReader] = None,
    samefile: Callable[[Any, Any], bool] = os.path.samefile,
) -> Optional[str]:
    """Return "user"/"admin" when THIS exe is the Inno-installed copy, "moved"
    when an install is registered somewhere else, or None when no install is
    registered at all (a portable zip)."""
    reader = reader or _windows_registry_reader
    exe_dir = Path(executable).resolve().parent
    seen_other = False
    for hive, view, mode in _INNO_LOOKUPS:
        location = reader(hive, view)
        if not location:
            continue
        if _same_dir(location, exe_dir, samefile):
            return mode
        seen_other = True
    return "moved" if seen_other else None


def macos_bundle_refusal(
    bundle: Path, *, access: Callable[[Any, int], bool] = os.access
) -> Optional[str]:
    """Why an in-place swap of `bundle` is impossible, as a status `reason`
    (a DMG-mounted copy reports "translocated": both mean "move the app to
    Applications first"), or None."""
    from .paths import macos_bundle_location_issue

    issue = macos_bundle_location_issue(bundle, access=access)
    return "translocated" if issue == "dmg-mounted" else issue


def detect_install(
    *,
    frozen: Optional[bool] = None,
    executable: Optional[Path] = None,
    platform: Optional[str] = None,
    version: Optional[str] = None,
    registry_reader: Optional[RegistryReader] = None,
    access: Callable[[Any, int], bool] = os.access,
    samefile: Callable[[Any, Any], bool] = os.path.samefile,
) -> InstallInfo:
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = Path(executable or sys.executable)
    if platform is None:
        from .paths import current_platform_key

        platform = current_platform_key()
    if version is None:
        from . import __version__ as version
    if not frozen:
        return InstallInfo("source", False, "source", executable=executable)
    if platform == "darwin":
        from .startup import _macos_app_bundle

        bundle = _macos_app_bundle(executable)
        if bundle is None:
            return InstallInfo("unknown", False, "unsupported-platform", executable=executable)
        reason = macos_bundle_refusal(bundle, access=access)
        if reason is None and not is_release_build(version):
            reason = "unknown-version"
        return InstallInfo("macos-app", reason is None, reason, bundle, executable)
    if platform == "win32":
        mode = inno_install_mode(executable, reader=registry_reader, samefile=samefile)
        app_dir = Path(executable).resolve().parent
        if mode is None:
            return InstallInfo("windows-portable", False, "portable", app_dir, executable)
        if mode == "moved":
            return InstallInfo("windows-portable", False, "moved-install", app_dir, executable)
        reason = None if is_release_build(version) else "unknown-version"
        return InstallInfo(
            "windows-installer", reason is None, reason, app_dir, executable, install_mode=mode
        )
    if platform.startswith("linux"):
        return InstallInfo("linux", False, "unsupported-platform", executable=executable)
    return InstallInfo("unknown", False, "unsupported-platform", executable=executable)


# --- child environment ------------------------------------------------------------


def clean_child_env(
    environ: Optional[Mapping[str, str]] = None, *, app_dir: Optional[Path] = None
) -> Dict[str, str]:
    """The environment for a detached child: PyInstaller's private variables
    stripped (PyInstaller >= 6.9 resets via PYINSTALLER_RESET_ENVIRONMENT),
    and the bundle's own folder removed from PATH."""
    source = dict(os.environ if environ is None else environ)
    env = {key: value for key, value in source.items() if not key.startswith("_PYI_")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for key in ("PYTHONPATH", "PYTHONHOME", "_MEIPASS2"):
        env.pop(key, None)
    if app_dir is not None:
        prefix = str(app_dir).lower()
        path_value = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(
            part
            for part in path_value.split(os.pathsep)
            if part and not part.lower().startswith(prefix)
        )
    return env


# --- Windows --------------------------------------------------------------------


def windows_command(plan: InstallPlan) -> str:
    """The exact setup.exe command line (a string, so quoting is exact)."""
    log = plan.log_path or (plan.updates_dir / f"install-{plan.to_version}.log")
    executable = plan.executable or Path(sys.executable)
    parts = [
        f'"{plan.asset_path}"',
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL",
        "/CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS",
        f'/LOG="{log}"',
        "/ALLUSERS" if plan.all_users else "/CURRENTUSER",
        f"/WAITPID={plan.parent_pid}",
    ]
    if plan.relaunch:
        parts.append("/RELAUNCH=1")
    parts.append(f"/UPDATEDFROM={plan.from_version}")
    parts.append(f'/RELAUNCHEXE="{executable}"')
    return " ".join(parts)


def _reset_dll_directory() -> None:
    """The PyInstaller bootloader's SetDllDirectoryW(_internal) is inherited
    by children (and their children: the relaunched tracker). Undo it."""
    try:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)  # type: ignore[attr-defined]
    except Exception:
        pass


def spawn_windows_installer(
    plan: InstallPlan,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    reset_dll_directory: Callable[[], None] = _reset_dll_directory,
    environ: Optional[Mapping[str, str]] = None,
) -> Any:
    reset_dll_directory()
    command = windows_command(plan)
    app_dir = Path(plan.executable).resolve().parent if plan.executable else None
    kwargs = dict(
        cwd=str(Path(plan.asset_path).parent),
        env=clean_child_env(environ, app_dir=app_dir),
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    attempts = 5
    for attempt in range(attempts):
        try:
            try:
                return popen(command, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError as exc:
                # A job that forbids breakaway answers ERROR_ACCESS_DENIED.
                if getattr(exc, "winerror", None) != 5:
                    raise
                return popen(command, creationflags=flags, **kwargs)
        except OSError as exc:
            # Antivirus may briefly hold the fresh exe (ERROR_SHARING_VIOLATION).
            if getattr(exc, "winerror", None) != 32 or attempt == attempts - 1:
                raise
            sleep(0.5 * (attempt + 1))
    raise InstallError("Could not start the installer")  # pragma: no cover


# --- macOS ----------------------------------------------------------------------

#: The swap helper, written to the updates folder from this string (never
#: from a download) and run detached. Copied from
#: docs/plans/auto-update/tapps_mac_swap.sh; the only change is the success
#: relaunch, which adds --after-update so the new version waits for the old
#: one's instance locks instead of reporting "already running".
MAC_SWAP_SCRIPT = r"""#!/bin/bash
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

relaunch() {  # $1 = extra args after --args
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
if [ -n "$(/usr/bin/pgrep -f "^$OVERLAY_EXE" || true)" ]; then
  # Nothing was touched yet: bring the old version back instead of leaving no app.
  log "overlay still running"; relaunch --update-failed "$NEW_VER"; exit 15
fi

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
relaunch --after-update --updated-from "$OLD_VER"
exit 0
"""

SWAP_SCRIPT_NAME = "tapps_mac_swap.sh"
STAGE_DIR_NAME = "stage"
ROLLBACK_DIR_NAME = "rollback"
#: Hidden folders beside the bundle, used only when the data folder is on
#: another volume: `.tapps-update-<version>` (stage) and the rollback one.
SIBLING_PREFIX = ".tapps-update-"
SIBLING_ROLLBACK_NAME = SIBLING_PREFIX + "rollback"
APP_BUNDLE_NAME = "MTGA Tracker.app"

Runner = Callable[..., Any]


def _run(run: Runner, args: Sequence[str], *, timeout: float = 600.0) -> Any:
    try:
        return run(list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"{args[0]} failed: {exc}", "stage-failed") from None


def _device(path: Path) -> Optional[int]:
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def macos_work_dirs(
    plan: InstallPlan, *, device: Callable[[Path], Optional[int]] = _device
) -> tuple:
    """(stage_dir, rollback_dir) on the same volume as the bundle. The data
    folder normally is; otherwise hidden siblings of the bundle are used."""
    assert plan.app_path is not None
    target_parent = Path(plan.app_path).parent
    updates_dir = Path(plan.updates_dir)
    updates_dir.mkdir(parents=True, exist_ok=True)
    if device(updates_dir) == device(target_parent):
        return updates_dir / STAGE_DIR_NAME, updates_dir / ROLLBACK_DIR_NAME
    return (
        target_parent / f"{SIBLING_PREFIX}{plan.to_version}",
        target_parent / SIBLING_ROLLBACK_NAME,
    )


def _find_app(folder: Path) -> Path:
    preferred = folder / APP_BUNDLE_NAME
    if preferred.is_dir():
        return preferred
    apps = [entry for entry in folder.iterdir() if entry.suffix == ".app" and entry.is_dir()]
    if len(apps) != 1:
        raise InstallError("The update archive does not contain one app bundle", "bad-archive")
    return apps[0]


def _extract_dmg(dmg: Path, stage_dir: Path, run: Runner, *, scratch_dir: Path) -> None:
    import tempfile

    mount = Path(tempfile.mkdtemp(prefix="mnt.", dir=str(scratch_dir)))
    attached = False
    try:
        result = _run(
            run,
            [
                "/usr/bin/hdiutil",
                "attach",
                "-nobrowse",
                "-noautoopen",
                "-noverify",
                "-readonly",
                "-mountpoint",
                str(mount),
                str(dmg),
                "-quiet",
            ],
        )
        if getattr(result, "returncode", 1) != 0:
            raise InstallError("Could not open the update disk image", "stage-failed")
        attached = True
        source = _find_app(mount)
        result = _run(run, ["/usr/bin/ditto", "--noqtn", str(source), str(stage_dir / source.name)])
        if getattr(result, "returncode", 1) != 0:
            raise InstallError("Could not copy the app from the disk image", "stage-failed")
    finally:
        if attached:
            detach = _run(run, ["/usr/bin/hdiutil", "detach", str(mount), "-quiet"], timeout=60)
            if getattr(detach, "returncode", 1) != 0:
                _run(
                    run, ["/usr/bin/hdiutil", "detach", str(mount), "-force", "-quiet"], timeout=60
                )
        shutil.rmtree(mount, ignore_errors=True)


def verify_staged_bundle(app: Path, expected_version: str, *, run: Runner, bundle_id: str) -> str:
    """codesign plus identity checks; returns the bundle's version string."""
    result = _run(run, ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
    if getattr(result, "returncode", 1) != 0:
        raise InstallError("The downloaded app failed codesign verification", "codesign-failed")
    try:
        with open(app / "Contents" / "Info.plist", "rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        raise InstallError(f"The downloaded app has no readable Info.plist: {exc}", "bad-archive")
    if info.get("CFBundleIdentifier") != bundle_id:
        raise InstallError("The downloaded app is not Tapps Tracker", "bad-archive")
    version = str(info.get("CFBundleShortVersionString") or "")
    if not versions_equal(version, expected_version):
        raise InstallError(
            f"The downloaded app is version {version or '?'}, expected {expected_version}",
            "bad-archive",
        )
    return version


def stage_macos_bundle(plan: InstallPlan, *, run: Runner = subprocess.run) -> InstallPlan:
    if plan.app_path is None:
        raise InstallError("The running app bundle is unknown", "unsupported")
    stage_dir, rollback_dir = macos_work_dirs(plan)
    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    if plan.asset_kind == "app-zip":
        result = _run(
            run, ["/usr/bin/ditto", "-x", "-k", "--noqtn", str(plan.asset_path), str(stage_dir)]
        )
        if getattr(result, "returncode", 1) != 0:
            raise InstallError("Could not unpack the update", "stage-failed")
    elif plan.asset_kind == "dmg":
        _extract_dmg(Path(plan.asset_path), stage_dir, run, scratch_dir=Path(plan.updates_dir))
    else:
        raise InstallError(f"Cannot install a {plan.asset_kind} on macOS", "unsupported")
    staged = _find_app(stage_dir)
    version = verify_staged_bundle(staged, plan.to_version, run=run, bundle_id=plan.bundle_id)
    return replace(plan, staged_app=staged, staged_version=version, rollback_dir=rollback_dir)


def remove_stage_dirs(updates_dir: Path, app_path: Optional[Path]) -> List[Path]:
    """Delete staging folders this updater created: `<updates>/stage` and
    `.tapps-update-<version>` beside the bundle. Never the bundle itself,
    never a symlink, and not the rollback copy (removed once the new version
    has run healthy). Returns what was removed."""
    removed: List[Path] = []
    candidates = [Path(updates_dir) / STAGE_DIR_NAME]
    if app_path is not None:
        parent = Path(app_path).parent
        try:
            candidates += sorted(parent.glob(SIBLING_PREFIX + "*"))
        except OSError:
            pass
    live = Path(app_path).resolve() if app_path is not None else None
    for folder in candidates:
        try:
            if folder.name == SIBLING_ROLLBACK_NAME or folder.is_symlink() or not folder.is_dir():
                continue
            if live is not None and folder.resolve() == live:
                continue
        except OSError:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        removed.append(folder)
    return removed


def write_swap_helper(updates_dir: Path) -> Path:
    updates_dir = Path(updates_dir)
    updates_dir.mkdir(parents=True, exist_ok=True)
    script = updates_dir / SWAP_SCRIPT_NAME
    temporary = script.with_suffix(".tmp")
    temporary.write_text(MAC_SWAP_SCRIPT, encoding="utf-8")
    os.chmod(temporary, 0o700)
    os.replace(temporary, script)
    return script


def macos_swap_command(plan: InstallPlan, script: Path) -> List[str]:
    assert plan.staged_app is not None and plan.app_path is not None
    return [
        "/bin/bash",
        str(script),
        str(plan.parent_pid),
        str(plan.staged_app),
        str(plan.app_path),
        str(plan.rollback_dir or (Path(plan.updates_dir) / ROLLBACK_DIR_NAME)),
        plan.from_version,
        plan.staged_version or plan.to_version,
        plan.bundle_id,
    ]


def spawn_macos_swap(
    plan: InstallPlan,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    environ: Optional[Mapping[str, str]] = None,
) -> Any:
    script = write_swap_helper(plan.updates_dir)
    env = clean_child_env(environ)
    if not plan.relaunch:
        env["TAPPS_SWAP_NO_LAUNCH"] = "1"
    log_path = plan.log_path or (Path(plan.updates_dir) / f"swap-{plan.to_version}.log")
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        return popen(
            macos_swap_command(plan, script),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=env,
            cwd="/",
        )
    finally:
        log_handle.close()


# --- entry points ---------------------------------------------------------------


def install_log_path(plan: InstallPlan) -> Path:
    if plan.log_path is not None:
        return Path(plan.log_path)
    name = "install" if plan.install_kind == "windows-installer" else "swap"
    return Path(plan.updates_dir) / f"{name}-{plan.to_version}.log"


def prepare_install(plan: InstallPlan, *, run: Runner = subprocess.run) -> InstallPlan:
    """Everything that can fail before any service is stopped: the payload
    exists, and on macOS it is unpacked and passes codesign."""
    if not Path(plan.asset_path).is_file():
        raise InstallError("The downloaded update is missing", "missing-download")
    plan = replace(plan, log_path=install_log_path(plan))
    if plan.install_kind == "macos-app":
        return stage_macos_bundle(plan, run=run)
    if plan.install_kind == "windows-installer":
        if plan.asset_kind != "inno-setup":
            raise InstallError(f"Cannot install a {plan.asset_kind} on Windows", "unsupported")
        return plan
    raise InstallError(f"In-place updates are not supported for {plan.install_kind}", "unsupported")


def install_and_restart(
    plan: InstallPlan,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    run: Runner = subprocess.run,
) -> Any:
    """Spawn the detached installer/helper. Returns quickly; the child waits
    for `plan.parent_pid` to exit before touching anything."""
    if plan.install_kind == "macos-app":
        if plan.staged_app is None:
            plan = prepare_install(plan, run=run)
        return spawn_macos_swap(plan, popen=popen)
    if plan.install_kind == "windows-installer":
        if plan.log_path is None:
            plan = replace(plan, log_path=install_log_path(plan))
        return spawn_windows_installer(plan, popen=popen)
    raise InstallError(f"In-place updates are not supported for {plan.install_kind}", "unsupported")
