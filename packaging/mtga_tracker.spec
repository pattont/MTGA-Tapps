# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path.cwd()
ui_dist = project_root / "ui" / "dist"
app_icon = project_root / "packaging" / "assets" / "MTGATracker.icns"
runtime_assets = project_root / "src" / "mtga_tracker" / "assets"
if not (ui_dist / "index.html").is_file():
    raise SystemExit("ui/dist is missing. Run `cd ui && npm run build` first.")
if not app_icon.is_file():
    raise SystemExit("App icon is missing. Run `scripts/create_macos_icon.sh` first.")

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

app = BUNDLE(
    collection,
    name="MTGA Tracker.app",
    icon=str(app_icon),
    bundle_identifier="com.travispatton.mtgatracker",
    info_plist={
        "CFBundleName": "MTGA Tracker",
        "CFBundleDisplayName": "MTGA Tracker",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": False,
        "NSHighResolutionCapable": True,
    },
)
