# -*- mode: python ; coding: utf-8 -*-

import re
import sys
from pathlib import Path


project_root = Path.cwd()
ui_dist = project_root / "ui" / "dist"
runtime_assets = project_root / "src" / "mtga_tracker" / "assets"
is_macos = sys.platform == "darwin"
is_windows = sys.platform == "win32"

version_source = (project_root / "src" / "mtga_tracker" / "__init__.py").read_text()
version_match = re.search(r'__version__\s*=\s*"([^"]+)"', version_source)
app_version = version_match.group(1) if version_match else "0.0.0"

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
    upx=True,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon) if (is_windows and app_icon) else None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
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
