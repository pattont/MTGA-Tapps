"""Console rendering helpers for MTGA tracker."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


ANSI_RESET = "\033[0m"

ANSI_STYLES: Dict[str, str] = {
    "turn": "\033[1;38;5;39m",
    "cast": "\033[38;5;45m",
    "land": "\033[38;5;34m",
    "attack": "\033[1;38;5;196m",
    "block": "\033[1;38;5;201m",
    "combat_damage": "\033[38;5;160m",
    "damage": "\033[38;5;208m",
    "ability": "\033[38;5;141m",
    "stack": "\033[38;5;81m",
    "stack_resolve": "\033[38;5;118m",
    "stack_fail": "\033[1;38;5;214m",
    "zone": "\033[38;5;171m",
    "counter": "\033[1;38;5;220m",
    "draw": "\033[38;5;250m",
    "life_gain": "\033[1;38;5;46m",
    "life_loss": "\033[1;38;5;124m",
}


def should_use_colors() -> bool:
    """Return True when ANSI colors should be emitted."""
    if os.getenv("NO_COLOR") is not None:
        return False
    color_env = (os.getenv("MTGA_TRACKER_COLOR") or "").strip().lower()
    if color_env in ("0", "false", "no", "off"):
        return False
    if color_env in ("1", "true", "yes", "on", "always"):
        return True
    if os.getenv("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def apply_style(
    text: str,
    style: Optional[str] = None,
    *,
    use_colors: bool,
    styles: Optional[Dict[str, str]] = None,
    reset: str = ANSI_RESET,
) -> str:
    """Apply ANSI style if enabled."""
    if not style or not use_colors:
        return text
    prefix = (styles or ANSI_STYLES).get(style)
    if not prefix:
        return text
    return f"{prefix}{text}{reset}"


def display_path_without_username(path_value: Any) -> str:
    """Return a display path with the user's home directory shortened to ~/."""
    if path_value is None:
        return "not found"
    try:
        path = Path(path_value).resolve()
        home = Path.home().resolve()
        if path == home:
            return "~"
        if path.is_relative_to(home):
            # Use the platform separator after ~ so Windows shows
            # ~\AppData\... instead of the mixed ~/AppData\... form.
            return "~" + os.sep + str(path.relative_to(home))
        return str(path).replace(str(home), "~")
    except Exception:
        return str(path_value).replace(str(Path.home()), "~")

