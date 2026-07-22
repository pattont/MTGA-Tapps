"""Path configuration module.

Automatically detects project paths and provides global variables for file locations.
"""

import os
import platform
import sys
from pathlib import Path
from typing import List, Optional


def get_mtga_raw_card_db_folders(override_dir: Optional[str] = None) -> List[Path]:
    """Return folders to search for Raw_CardDatabase_*.mtga, in order of preference.

    Uses the current user's home (no hardcoded usernames). If override_dir or
    MTGA_DATA_DIR env is set, that path is the only candidate.

    Platform defaults:
    - macOS: Steam install first (most up to date), then Epic (com.wizards.mtga)
    - Windows: common Steam/Wizards install locations under MTGA_Data/Downloads/Raw

    Returns:
        List of existing directory Paths to search; caller globs for Raw_CardDatabase_*.mtga.
    """
    out: List[Path] = []
    if override_dir:
        p = Path(override_dir)
        if p.is_dir():
            return [p]
        return []
    env = os.getenv("MTGA_DATA_DIR")
    if env:
        p = Path(env)
        if p.is_dir():
            return [p]
        return []
    if platform.system() == "Darwin":
        # Steam (most up to date) then Epic
        steam = Path.home() / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "MTGA" / "MTGA_Data" / "Downloads" / "Raw"
        if steam.is_dir():
            out.append(steam)
        epic = Path.home() / "Library" / "Application Support" / "com.wizards.mtga" / "Downloads" / "RAW"
        if epic.is_dir():
            out.append(epic)
    elif platform.system() == "Windows":
        windows_candidates = [
            Path(r"C:\Program Files (x86)\Steam\steamapps\common\MTGA\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files (x86)\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw"),
        ]
        for candidate in windows_candidates:
            if candidate.is_dir():
                out.append(candidate)
    return out


def _find_project_root() -> Path:
    """Find the project root directory by looking for common markers.
    
    Returns:
        Path to the project root directory.
    """
    # Start from this file's directory
    current = Path(__file__).resolve().parent
    
    # Look for project markers (pyproject.toml, README.md, etc.)
    markers = ['pyproject.toml', 'README.md', '.git']
    
    # Walk up the directory tree
    for parent in [current] + list(current.parents):
        if any((parent / marker).exists() for marker in markers):
            return parent
    
    # Fallback: assume we're in src/mtga_tracker, go up 2 levels
    return current.parent.parent


# Detect project root
PROJECT_ROOT = _find_project_root()


def _installed_app_data_dir() -> Path:
    """Return a writable per-user data directory for a frozen desktop build."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "MTGA Tracker"
    if system == "Windows":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "MTGA Tracker"
        return Path.home() / "AppData" / "Local" / "MTGA Tracker"
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "mtga-tracker"
    return Path.home() / ".local" / "share" / "mtga-tracker"


def _default_data_dir() -> Path:
    override = os.getenv("MTGA_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return _installed_app_data_dir()
    return PROJECT_ROOT / "data"


# Common paths. Frozen builds must never write inside the signed application bundle.
DATA_DIR = _default_data_dir()
LOGS_DIR = DATA_DIR / "logs" if getattr(sys, "frozen", False) else PROJECT_ROOT / "logs"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# String versions for compatibility
DATA_DIR_STR = str(DATA_DIR)
LOGS_DIR_STR = str(LOGS_DIR)
