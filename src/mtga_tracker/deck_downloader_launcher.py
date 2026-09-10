"""Launch the bundled Deck Downloader terminal UI from the tracker.

The Deck Downloader is an interactive Rich console app, so it needs a real
terminal window — the tracker's read-only live-log window cannot host it.
This module builds the right launch command for the current platform and
install style (frozen app vs source checkout) and opens it in a terminal
sized for the TUI.

Packaged builds have no second executable for it: the tracker binary run
with ``--deck-finder`` *is* the Deck Finder (``run_deck_finder`` below), so
the install folder holds one program. On Windows that binary is a windowed
app with no console of its own, so the mode first attaches to the console
the launcher opened for it (or allocates one) and points the interpreter's
streams at it.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from importlib.util import find_spec
from typing import Any, Callable, List, Optional, Tuple

from .paths import PROJECT_ROOT

#: Terminal geometry the Rich tables render comfortably in.
TERMINAL_COLUMNS = 140
TERMINAL_ROWS = 42

#: The tracker executable's switch that turns it into the Deck Finder.
DECK_FINDER_FLAG = "--deck-finder"

#: Import name → pip name for the downloader's runtime dependencies.
_REQUIRED_MODULES = {
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "cloudscraper": "cloudscraper",
    "rich": "rich",
}


def missing_dependencies() -> List[str]:
    """Return pip names of downloader dependencies absent from this env."""
    return [
        pip_name
        for module_name, pip_name in _REQUIRED_MODULES.items()
        if find_spec(module_name) is None
    ]


def deck_downloader_command() -> Optional[List[str]]:
    """Return the command that runs the Deck Downloader, or None if absent."""
    if getattr(sys, "frozen", False):
        # The packaged tracker carries the Deck Finder inside itself.
        return [sys.executable, DECK_FINDER_FLAG]
    if find_spec("mtga_deck_downloader") is None:
        return None
    return [sys.executable, "-m", "mtga_deck_downloader"]


def launch_deck_downloader() -> Tuple[bool, str]:
    """Open the Deck Downloader in a terminal window.

    Returns (ok, message) — the message is user-facing either way.
    """
    command = deck_downloader_command()
    if command is None:
        return False, (
            "Deck Finder is not available in this install. From a source "
            "checkout run: pip install -e ."
        )
    # Frozen builds bundle everything; source runs need the tracker's own
    # dependencies installed (they ship with `pip install -e .`).
    if not getattr(sys, "frozen", False):
        missing = missing_dependencies()
        if missing:
            return False, (
                "Deck Finder dependencies are missing: "
                + ", ".join(missing)
                + ". Run: pip install -e .  (from the MTGA-Tapps folder)"
            )

    try:
        if sys.platform == "darwin":
            _launch_macos_terminal(command)
        elif sys.platform == "win32":
            _launch_windows_console(command)
        else:
            ok, message = _launch_linux_terminal(command)
            if not ok:
                return False, message
    except Exception as exc:  # pragma: no cover - depends on host environment
        return False, f"Could not launch the Deck Finder: {exc}"
    return True, "Deck Finder opened in a terminal window."


def _launch_macos_terminal(command: List[str]) -> None:
    """Open Terminal.app with a window sized for the TUI."""
    shell_command = (
        f"cd {shlex.quote(str(PROJECT_ROOT))} && clear && "
        + " ".join(shlex.quote(part) for part in command)
        + " && exit"
    )
    escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    applescript = "\n".join(
        [
            'tell application "Terminal"',
            f'  set ddTab to do script "{escaped}"',
            "  try",
            f"    set number of columns of ddTab to {TERMINAL_COLUMNS}",
            f"    set number of rows of ddTab to {TERMINAL_ROWS}",
            "  end try",
            "  activate",
            "end tell",
        ]
    )
    subprocess.Popen(["osascript", "-e", applescript])


def _windows_console_command_line(command: List[str]) -> str:
    """Build the cmd.exe line that sizes the console and runs the command.

    cmd does NOT understand the backslash-escaped quotes Popen produces for
    argument lists, so a quoted path like "MTGA Deck Downloader.exe" got
    mangled into fragments ('deck downloader.exe is not recognized...').
    Instead pass ONE raw string using cmd's own rule: with /S /C the first
    and last quote of the tail are stripped, so wrapping the whole compound
    command in quotes keeps the inner quoted paths intact.
    """
    quoted = " ".join(f'"{part}"' if " " in part else part for part in command)
    return (
        f'cmd /S /C "mode con: cols={TERMINAL_COLUMNS} lines={TERMINAL_ROWS} & {quoted}"'
    )


def _launch_windows_console(command: List[str]) -> None:
    """Open a new console sized for the TUI."""
    subprocess.Popen(
        _windows_console_command_line(command),
        cwd=str(PROJECT_ROOT),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
    )


def _launch_linux_terminal(command: List[str]) -> Tuple[bool, str]:
    """Best-effort launch in a common Linux terminal emulator."""
    shell_command = " ".join(shlex.quote(part) for part in command)
    terminal = next(
        (
            t
            for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm")
            if shutil.which(t)
        ),
        None,
    )
    if terminal is None:
        return False, "No terminal emulator found to host the Deck Finder."
    subprocess.Popen([terminal, "-e", shell_command], cwd=str(PROJECT_ROOT))
    return True, ""


# --- the Deck Finder itself, when the tracker binary is run as it ----------


def run_deck_finder(argv: Optional[List[str]] = None) -> int:
    """Run the Deck Finder terminal UI in this process (``--deck-finder``).

    ``argv`` is what follows the flag (``--diagnose`` works as it always
    has). Windows gets a console attached first; everywhere else the
    launcher already runs this inside a terminal.
    """
    if sys.platform == "win32":
        _attach_windows_console()
    from mtga_deck_downloader.__main__ import main as deck_finder_main

    return int(deck_finder_main(list(argv or [])))


#: Win32 constants for the console dance below.
_ATTACH_PARENT_PROCESS = 0xFFFFFFFF
_STD_HANDLES = {"stdin": -10, "stdout": -11, "stderr": -12}


def _attach_windows_console(
    kernel32: Any = None, open_streams: Optional[Callable[[Any], None]] = None
) -> bool:
    """Give this windowed process a console and wire Python's streams to it.

    The launcher opens a new console with cmd.exe and runs the tracker
    binary from it; a windowed (``console=False``) executable does not
    inherit that console, so attach to the parent's. When there is none —
    cmd already gone, or the flag typed at a prompt — allocate a fresh one.
    Returns False when neither worked (the TUI would then be invisible).
    """
    if kernel32 is None:  # pragma: no cover - Windows only
        import ctypes

        kernel32 = ctypes.windll.kernel32
    if not kernel32.AttachConsole(_ATTACH_PARENT_PROCESS) and not kernel32.AllocConsole():
        return False
    (open_streams or _open_windows_console_streams)(kernel32)
    return True


def _open_windows_console_streams(kernel32: Any) -> None:  # pragma: no cover - Windows only
    """Point sys.stdin/stdout/stderr (and the Win32 standard handles Rich
    reads) at the console this process is now attached to, then size it."""
    import msvcrt

    streams = {
        "stdin": open("CONIN$", "r", encoding="utf-8", errors="replace"),
        "stdout": open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1),
        "stderr": open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1),
    }
    for name, stream in streams.items():
        setattr(sys, name, stream)
        kernel32.SetStdHandle(_STD_HANDLES[name], msvcrt.get_osfhandle(stream.fileno()))
    kernel32.SetConsoleTitleW("Tapps Tracker — Deck Finder")
    os.system(f"mode con: cols={TERMINAL_COLUMNS} lines={TERMINAL_ROWS}")
