"""Per-user login startup registration for Windows and macOS launches."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence

LOGIN_ARGUMENT = "--login-start"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_VALUE_NAME = "Tapps Tracker"
MACOS_LAUNCH_AGENT_LABEL = "com.travispatton.mtgatracker.startup"


def _safe_error(exc: OSError) -> str:
    """Keep a registration error useful without exposing the home directory."""
    message = str(exc)
    home = str(Path.home())
    placeholder = "%USERPROFILE%" if sys.platform == "win32" else "~"
    return message.replace(home, placeholder) if home else message


@dataclass(frozen=True)
class StartupRegistrationStatus:
    available: bool
    registered: bool
    error: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _macos_app_bundle(executable: Optional[Path] = None) -> Optional[Path]:
    current = (executable or Path(sys.executable)).resolve()
    for parent in (current, *current.parents):
        if parent.suffix.lower() == ".app":
            return parent
    return None


def _windows_command(arguments: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(arguments))


def _macos_arguments(bundle: Path) -> list[str]:
    return ["/usr/bin/open", "-g", str(bundle), "--args", LOGIN_ARGUMENT]


def _source_arguments() -> list[str]:
    executable = Path(sys.executable).resolve()
    if sys.platform == "win32":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.is_file():
            executable = pythonw
    return [str(executable), "-m", "mtga_tracker.app", LOGIN_ARGUMENT]


def _macos_plist_path(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{MACOS_LAUNCH_AGENT_LABEL}.plist"


def _macos_document(arguments: Sequence[str]) -> dict[str, object]:
    return {
        "Label": MACOS_LAUNCH_AGENT_LABEL,
        "ProgramArguments": list(arguments),
        "RunAtLoad": True,
    }


def _launch_target() -> Optional[tuple[str, list[str]]]:
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            return "windows", [str(Path(sys.executable).resolve()), LOGIN_ARGUMENT]
        return "windows", _source_arguments()
    if sys.platform == "darwin":
        if getattr(sys, "frozen", False):
            bundle = _macos_app_bundle()
            if bundle is None or Path("/Volumes") in bundle.parents:
                return None
            return "macos", _macos_arguments(bundle)
        return "macos", _source_arguments()
    return None


def _windows_registered(arguments: Sequence[str]) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            value, _value_type = winreg.QueryValueEx(key, WINDOWS_VALUE_NAME)
    except FileNotFoundError:
        return False
    return value == _windows_command(arguments)


def _set_windows_registered(arguments: Sequence[str], enabled: bool) -> None:
    import winreg

    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            winreg.SetValueEx(
                key,
                WINDOWS_VALUE_NAME,
                0,
                winreg.REG_SZ,
                _windows_command(arguments),
            )
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            WINDOWS_RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, WINDOWS_VALUE_NAME)
    except FileNotFoundError:
        pass


def _macos_registered(arguments: Sequence[str], *, home: Optional[Path] = None) -> bool:
    path = _macos_plist_path(home)
    try:
        with path.open("rb") as stream:
            return plistlib.load(stream) == _macos_document(arguments)
    except (FileNotFoundError, plistlib.InvalidFileException):
        return False


def _set_macos_registered(
    arguments: Sequence[str], enabled: bool, *, home: Optional[Path] = None
) -> None:
    path = _macos_plist_path(home)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("wb") as stream:
            plistlib.dump(_macos_document(arguments), stream, sort_keys=True)
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def registration_status() -> StartupRegistrationStatus:
    target = _launch_target()
    if target is None:
        return StartupRegistrationStatus(available=False, registered=False)
    platform, arguments = target
    try:
        registered = (
            _windows_registered(arguments)
            if platform == "windows"
            else _macos_registered(arguments)
        )
        return StartupRegistrationStatus(available=True, registered=registered)
    except OSError as exc:
        return StartupRegistrationStatus(
            available=True,
            registered=False,
            error=_safe_error(exc),
        )


def set_start_at_login(enabled: bool) -> StartupRegistrationStatus:
    if not isinstance(enabled, bool):
        raise TypeError("'start_at_login' must be a boolean")
    target = _launch_target()
    if target is None:
        if not enabled:
            return StartupRegistrationStatus(available=False, registered=False)
        raise ValueError("Start at login is available on Windows and macOS.")
    platform, arguments = target
    try:
        if platform == "windows":
            _set_windows_registered(arguments, enabled)
        else:
            _set_macos_registered(arguments, enabled)
    except OSError as exc:
        raise OSError(_safe_error(exc)) from None
    status = registration_status()
    if status.registered != enabled:
        raise OSError("The operating-system startup setting could not be verified.")
    return status
