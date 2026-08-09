"""Path configuration module.

Automatically detects project paths and provides global variables for file locations.
"""

import os
import platform
import re
import sys
from pathlib import Path
from typing import List, Optional


#: Relative path from a game install root to Arena's raw card database folder.
_MTGA_RAW_SUFFIX = Path("MTGA_Data") / "Downloads" / "Raw"

#: Unity announces its own data directory in the head of Player.log at startup.
#: Current Arena (Unity 2022.3, IL2CPP) prints the "[Subsystems]" line — verified
#: against a real macOS Steam log; older Mono-backend builds printed "Mono path[0]".
#: Either one is Arena reporting its own install location, which covers ANY drive
#: and ANY installer (standalone .msi on G:\, Steam, Epic) with zero guessing.
_LOG_INSTALL_PATTERNS = (
    re.compile(r"Discovering subsystems at path (.+?)[/\\]UnitySubsystems\s*$"),
    re.compile(r"Mono path\[0\] = '(.+?)[/\\]Managed'"),
)


def _unity_data_dirs_from_log_head(head_text: str) -> List[Path]:
    """Extract Unity data-directory paths announced in a Player.log head."""
    found: List[Path] = []
    for line in head_text.splitlines():
        for pattern in _LOG_INSTALL_PATTERNS:
            match = pattern.search(line)
            if match:
                path = Path(match.group(1).strip())
                if path not in found:
                    found.append(path)
    return found


def _raw_dir_near_unity_data_dir(data_dir: Path) -> Optional[Path]:
    """Map a Unity data dir to the MTGA_Data/Downloads/Raw folder near it.

    Windows: the data dir IS `<install>\\MTGA_Data`, so its own Downloads\\Raw.
    macOS Steam: the data dir is inside `MTGA.app/Contents/Resources/Data` while
    the downloads live in `MTGA_Data` NEXT TO the app — so walk up the ancestors
    and look beside each one. Only returns a folder that exists.
    """
    for base in (data_dir, *data_dir.parents):
        candidates = [base / "MTGA_Data" / "Downloads" / "Raw"]
        if base.name == "MTGA_Data":
            candidates.insert(0, base / "Downloads" / "Raw")
        for candidate in candidates:
            try:
                if candidate.is_dir():
                    return candidate
            except OSError:
                continue
    return None


def mtga_raw_dir_from_player_log(log_path) -> Optional[Path]:
    """Derive Arena's card-DB folder from the Unity header in Player.log.

    Player.log always lives in the user profile (LocalLow / ~/Library/Logs)
    regardless of where the game is installed — which is why the tracker can
    find the log but not the install. The log head fixes that: Arena states
    its own install path there. Also reads Player-prev.log in case the
    current log was truncated mid-write. Never raises; returns None on miss.
    """
    if not log_path:
        return None
    log_file = Path(log_path)
    for candidate_log in (log_file, log_file.parent / "Player-prev.log"):
        try:
            with open(candidate_log, "r", encoding="utf-8", errors="ignore") as handle:
                head = handle.read(65536)
        except OSError:
            continue
        for data_dir in _unity_data_dirs_from_log_head(head):
            raw = _raw_dir_near_unity_data_dir(data_dir)
            if raw is not None:
                return raw
    return None


def _parse_steam_library_paths(vdf_text: str) -> List[str]:
    """Extract library folder paths from Steam's libraryfolders.vdf.

    The VDF format stores them as `"path"  "D:\\\\SteamLibrary"` entries with
    doubled backslashes. A full VDF parser is overkill for two keys.
    """
    values = re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', vdf_text)
    return [value.replace("\\\\", "\\") for value in values]


def _steam_mtga_raw_dirs(steam_root: Path) -> List[Path]:
    """Return existing MTGA raw-DB folders across ALL of a Steam install's
    libraries — games regularly live on a different drive than Steam itself."""
    libraries = [steam_root]
    for vdf in (
        steam_root / "steamapps" / "libraryfolders.vdf",
        steam_root / "config" / "libraryfolders.vdf",
    ):
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for library in _parse_steam_library_paths(text):
            path = Path(library)
            if path not in libraries:
                libraries.append(path)
    out: List[Path] = []
    for library in libraries:
        candidate = library / "steamapps" / "common" / "MTGA" / _MTGA_RAW_SUFFIX
        if candidate.is_dir() and candidate not in out:
            out.append(candidate)
    return out


def _windows_steam_roots() -> List[Path]:
    """Steam install roots on Windows: both Program Files plus the registry."""
    roots: List[Path] = []
    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.getenv(env_name)
        if base:
            roots.append(Path(base) / "Steam")
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        if steam_path:
            roots.append(Path(str(steam_path)))
    except Exception:
        pass
    deduped: List[Path] = []
    for root in roots:
        if root.is_dir() and root not in deduped:
            deduped.append(root)
    return deduped


def get_mtga_raw_card_db_folders(
    override_dir: Optional[str] = None, log_path: Optional[str] = None
) -> List[Path]:
    """Return folders to search for Raw_CardDatabase_*.mtga, in order of preference.

    Uses the current user's home (no hardcoded usernames). If override_dir or
    MTGA_DATA_DIR env is set, that path is the only candidate.

    Resolution order after the overrides:
    1. The install path Arena itself announces in the Player.log head (when
       log_path is given) — the only signal that works for ANY install
       location, including a standalone .msi install on a non-system drive.
    2. Platform defaults: every Steam library (libraryfolders.vdf), Epic,
       and the static Program Files locations.

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
    # Arena's own report of where it lives beats every guess below — this is
    # what finds a standalone .msi install on G:\ or any other custom location.
    log_derived = mtga_raw_dir_from_player_log(log_path) if log_path else None
    if log_derived is not None:
        out.append(log_derived)
    if platform.system() == "Darwin":
        # Steam (most up to date, any library drive) then Epic/standalone
        for found in _steam_mtga_raw_dirs(
            Path.home() / "Library" / "Application Support" / "Steam"
        ):
            if found not in out:
                out.append(found)
        epic = Path.home() / "Library" / "Application Support" / "com.wizards.mtga" / "Downloads" / "RAW"
        if epic.is_dir() and epic not in out:
            out.append(epic)
    elif platform.system() == "Windows":
        # Steam first: walk every configured Steam library (libraryfolders.vdf),
        # not just the default C: install — game libraries on other drives are
        # common and were previously reported as "Local Card DB: not found".
        for steam_root in _windows_steam_roots():
            for found in _steam_mtga_raw_dirs(steam_root):
                if found not in out:
                    out.append(found)
        static_candidates = [
            Path(r"C:\Program Files (x86)\Steam\steamapps\common\MTGA\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files\Steam\steamapps\common\MTGA\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files (x86)\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files\Epic Games\MagicTheGathering\MTGA_Data\Downloads\Raw"),
            Path(r"C:\Program Files (x86)\Epic Games\MagicTheGathering\MTGA_Data\Downloads\Raw"),
        ]
        for candidate in static_candidates:
            if candidate.is_dir() and candidate not in out:
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
