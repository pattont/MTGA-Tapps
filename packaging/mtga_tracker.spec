# -*- mode: python ; coding: utf-8 -*-

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path.cwd()
ui_dist = project_root / "ui" / "dist"
runtime_assets = project_root / "src" / "mtga_tracker" / "assets"
is_macos = sys.platform == "darwin"
is_windows = sys.platform == "win32"

# Version comes from the git tag via setuptools-scm: the build scripts run
# `pip install -e .` first, which writes src/mtga_tracker/_version.py and
# registers the dist metadata — read whichever is available.
def _resolve_app_version() -> str:
    try:
        from importlib.metadata import version

        return version("mtga-tracker")
    except Exception:
        pass
    version_file = project_root / "src" / "mtga_tracker" / "_version.py"
    if version_file.is_file():
        match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", version_file.read_text())
        if match:
            return match.group(1)
    return "0.0.0"


app_version = _resolve_app_version()


def _windows_version_info(version: str, *, file_description: str, original_filename: str):
    """A VERSIONINFO resource for the exe. An executable with no company,
    product, or description is one more thing Windows Defender's heuristics
    hold against an unsigned binary; this is free to add."""
    if not is_windows:
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    match = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    numbers = [int(part or 0) for part in (match.groups() if match else ())]
    numbers = (numbers + [0, 0, 0, 0])[:4]
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=tuple(numbers),
            prodvers=tuple(numbers),
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Travis Patton"),
                            StringStruct("FileDescription", file_description),
                            StringStruct("FileVersion", version),
                            StringStruct("InternalName", original_filename.rsplit(".", 1)[0]),
                            StringStruct("LegalCopyright", "MIT License"),
                            StringStruct("OriginalFilename", original_filename),
                            StringStruct("ProductName", "Tapps Tracker"),
                            StringStruct("ProductVersion", version),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

if not (ui_dist / "index.html").is_file():
    raise SystemExit("ui/dist is missing. Run `cd ui && npm run build` first.")

# The Deck Finder loads its deck-site providers by name at runtime
# (providers.registry -> importlib), which static analysis cannot see, so
# every module of the package is named explicitly. collect_submodules runs
# now, at spec time, when only an installed package is importable — put the
# source tree on the path so the answer does not depend on `pip install -e .`
# having run, and refuse to build a tracker whose Deck Finder would show no
# sites at all.
sys.path.insert(0, str(project_root / "src"))
deck_finder_modules = collect_submodules("mtga_deck_downloader")
if "mtga_deck_downloader.providers.moxfield" not in deck_finder_modules:
    raise SystemExit(
        "mtga_tracker.spec: could not enumerate mtga_deck_downloader's provider modules "
        f"(found {deck_finder_modules}); the packaged Deck Finder would have no sites."
    )

# The in-game overlay is a separate native app staged by
# scripts/build_overlay.{sh,ps1}. Optional: a build without Rust simply
# ships without it (the Settings page says so), so this never fails.
# Windows: the exe rides along as a data file. macOS: NOT here — PyInstaller
# lays data out under Contents/Frameworks with "." in directory names
# mangled to "__dot__" and symlinks from Resources, which breaks a nested
# .app for codesign; scripts/build_macos_app.sh copies the real
# "Tapps Overlay.app" into Contents/Helpers after this build instead.
overlay_out = project_root / "overlay" / "build-out"
overlay_datas = []
if is_windows and (overlay_out / "tapps-overlay.exe").is_file():
    overlay_datas.append((str(overlay_out / "tapps-overlay.exe"), "overlay"))
if is_windows and not overlay_datas:
    print("mtga_tracker.spec: no overlay build in overlay/build-out — packaging without the in-game overlay")

app_icon = None
if is_macos:
    app_icon = project_root / "packaging" / "assets" / "MTGATracker.icns"
    if not app_icon.is_file():
        raise SystemExit("App icon is missing. Run `scripts/create_macos_icon.sh` first.")
elif is_windows:
    app_icon = project_root / "packaging" / "assets" / "MTGATracker.ico"
    if not app_icon.is_file():
        app_icon = None  # build proceeds with PyInstaller's default icon

analysis = Analysis(
    [str(project_root / "packaging" / "entrypoint.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(ui_dist), "ui/dist"),
        (str(runtime_assets), "mtga_tracker/assets"),
        (
            str(project_root / "src" / "mtga_deck_downloader" / "default_config.json"),
            "mtga_deck_downloader",
        ),
        *overlay_datas,
    ],
    # The Deck Finder lives in this executable: the dashboard page and
    # `MTGA Tracker --deck-finder` (the terminal UI) both need every
    # deck-site module (see deck_finder_modules above) plus the scrapers'
    # own runtime-loaded dependencies.
    hiddenimports=["cloudscraper", "bs4"] + deck_finder_modules,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MTGA Tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # packed executables trip AV heuristics; the size win is not worth it
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon) if (is_windows and app_icon) else None,
    version=_windows_version_info(
        app_version,
        file_description="Tapps Tracker for MTG Arena",
        original_filename="MTGA Tracker.exe",
    ),
)

# One executable. The Deck Finder terminal tool used to be a second one
# ("MTGA Deck Downloader") beside it, which on Windows meant two programs at
# the top of the install folder; it is now a mode of this binary
# (`--deck-finder`, see deck_downloader_launcher.run_deck_finder).
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,  # packed executables trip AV heuristics; the size win is not worth it
    upx_exclude=[],
    name="MTGA Tracker",
)

if is_macos:
    app = BUNDLE(
        collection,
        name="MTGA Tracker.app",
        icon=str(app_icon),
        bundle_identifier="com.travispatton.mtgatracker",
        info_plist={
            "CFBundleName": "MTGA Tracker",
            "CFBundleDisplayName": "MTGA Tracker",
            "CFBundleShortVersionString": app_version,
            "LSUIElement": False,
            "NSHighResolutionCapable": True,
        },
    )
