"""Launch the bundled Deck Downloader terminal UI from the tracker.

The Deck Downloader is an interactive Rich console app, so it needs a real
terminal window — the tracker's read-only live-log window cannot host it.
This module builds the right launch command for the current platform and
install style (frozen app vs source checkout) and opens it in a terminal
sized for the TUI.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import List, Optional, Tuple

from .paths import PROJECT_ROOT

#: Terminal geometry the Rich tables render comfortably in.
TERMINAL_COLUMNS = 140
TERMINAL_ROWS = 42

#: Import name → pip name for the downloader's runtime dependencies.
_REQUIRED_MODULES = {
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "cloudscraper": "cloudscraper",
    "rich": "rich",
}


def _frozen_executable() -> Optional[Path]:
    """Return the bundled 'MTGA Deck Downloader' binary when frozen."""
    if not getattr(sys, "frozen", False):
        return None
    folder = Path(sys.executable).resolve().parent
    for name in ("MTGA Deck Downloader.exe", "MTGA Deck Downloader"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def missing_dependencies() -> List[str]:
    """Return pip names of downloader dependencies absent from this env."""
    return [
        pip_name
        for module_name, pip_name in _REQUIRED_MODULES.items()
        if find_spec(module_name) is None
    ]


def deck_downloader_command() -> Optional[List[str]]:
    """Return the command that runs the Deck Downloader, or None if absent."""
    frozen = _frozen_executable()
    if frozen is not None:
        return [str(frozen)]
    if getattr(sys, "frozen", False):
        return None  # frozen build without the companion binary
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
            "Deck Downloader is not available in this install. From a source "
            "checkout run: pip install -e ."
        )
    # Frozen builds bundle everything; source runs need the tracker's own
    # dependencies installed (they ship with `pip install -e .`).
    if not _frozen_executable():
        missing = missing_dependencies()
        if missing:
            return False, (
                "Deck Downloader dependencies are missing: "
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
        return False, f"Could not launch the Deck Downloader: {exc}"
    return True, "Deck Downloader opened in a terminal window."


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


def _launch_windows_console(command: List[str]) -> None:
    """Open a new console sized for the TUI."""
    command_line = subprocess.list2cmdline(command)
    sized = f"mode con: cols={TERMINAL_COLUMNS} lines={TERMINAL_ROWS} & {command_line}"
    subprocess.Popen(
        ["cmd", "/c", sized],
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
        return False, "No terminal emulator found to host the Deck Downloader."
    subprocess.Popen([terminal, "-e", shell_command], cwd=str(PROJECT_ROOT))
    return True, ""
