"""Launch the bundled Deck Downloader terminal UI from the tracker.

The Deck Downloader is an interactive Rich console app, so it needs a real
terminal window — the tracker's read-only live-log window cannot host it.
This module builds the right launch command for the current platform and
install style (frozen app vs source checkout) and opens it in a terminal.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from .paths import PROJECT_ROOT


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


def deck_downloader_command() -> Optional[List[str]]:
    """Return the command that runs the Deck Downloader, or None if absent."""
    frozen = _frozen_executable()
    if frozen is not None:
        return [str(frozen)]
    if getattr(sys, "frozen", False):
        return None  # frozen build without the companion binary
    try:
        import mtga_deck_downloader  # noqa: F401
    except ImportError:
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
            "checkout run: pip install -e '.[decks]'"
        )

    shell_command = " ".join(shlex.quote(part) for part in command)
    try:
        if sys.platform == "darwin":
            # Terminal.app runs the tool and closes the window on exit.
            script = f'cd {shlex.quote(str(PROJECT_ROOT))} && {shell_command} && exit'
            applescript = script.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'tell application "Terminal" to do script "{applescript}"',
                    "-e",
                    'tell application "Terminal" to activate',
                ]
            )
        elif sys.platform == "win32":
            subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
            )
        else:
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
    except Exception as exc:  # pragma: no cover - depends on host environment
        return False, f"Could not launch the Deck Downloader: {exc}"
    return True, "Deck Downloader opened in a terminal window."
