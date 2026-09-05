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
    ],
    hiddenimports=[],
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

# Companion console tool: the Deck Downloader terminal UI. Built from the
# same dependency pool and collected into the same folder/.app so the menu
# app can launch it in a terminal window.
dd_analysis = Analysis(
    [str(project_root / "packaging" / "deck_downloader_entrypoint.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (
            str(project_root / "src" / "mtga_deck_downloader" / "default_config.json"),
            "mtga_deck_downloader",
        ),
    ],
    # The provider/scraper modules are loaded dynamically (pkgutil) and are
    # invisible to PyInstaller's static analysis — collect every submodule or
    # the frozen Deck Finder starts with "No providers found".
    hiddenimports=["cloudscraper", "bs4"] + collect_submodules("mtga_deck_downloader"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
dd_pyz = PYZ(dd_analysis.pure)

dd_exe = EXE(
    dd_pyz,
    dd_analysis.scripts,
    [],
    exclude_binaries=True,
    name="MTGA Deck Downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # packed executables trip AV heuristics; the size win is not worth it
    console=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon) if (is_windows and app_icon) else None,
    version=_windows_version_info(
        app_version,
        file_description="Tapps Tracker Deck Finder",
        original_filename="MTGA Deck Downloader.exe",
    ),
)

collection = COLLECT(
    exe,
    dd_exe,
    analysis.binaries,
    dd_analysis.binaries,
    analysis.datas,
    dd_analysis.datas,
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
