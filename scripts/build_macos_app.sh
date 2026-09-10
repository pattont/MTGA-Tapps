#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"

cd "$ROOT_DIR/ui"
npm ci
npm run build

# The in-game overlay (skipped with a warning when Rust isn't installed).
"$ROOT_DIR/scripts/build_overlay.sh"

cd "$ROOT_DIR"
"$ROOT_DIR/scripts/create_macos_icon.sh"
"$PYTHON" -m pip install -e '.[gui,build]'
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/mtga_tracker.spec

# Seal the finished bundle with an ad-hoc signature. PyInstaller signs the
# individual binaries, but without a valid seal on the BUNDLE, macOS 15+
# shows the hard "Not Opened / Move to Trash" dialog and never offers the
# Privacy & Security "Open Anyway" escape hatch. An ad-hoc seal restores
# that flow for unsigned distribution. MACOS_SIGN_IDENTITY overrides with a
# real Developer ID when one is available.
APP_PATH="$ROOT_DIR/dist/MTGA Tracker.app"

# The overlay goes in as a real nested app under Contents/Helpers (where
# macOS expects helper apps) rather than through PyInstaller's data tree,
# which mangles a nested .app into "Tapps Overlay__dot__app" with symlinked
# binaries that codesign refuses. overlay_launcher.py looks here first.
OVERLAY_APP="$ROOT_DIR/overlay/build-out/Tapps Overlay.app"
if [[ -d "$OVERLAY_APP" ]]; then
  mkdir -p "$APP_PATH/Contents/Helpers"
  rm -rf "$APP_PATH/Contents/Helpers/Tapps Overlay.app"
  cp -R "$OVERLAY_APP" "$APP_PATH/Contents/Helpers/"
  echo "Overlay: $APP_PATH/Contents/Helpers/Tapps Overlay.app"
elif [[ "${OVERLAY_REQUIRED:-0}" == "1" ]]; then
  echo "overlay/build-out/Tapps Overlay.app is missing and OVERLAY_REQUIRED=1" >&2
  exit 1
fi

codesign --force --deep --sign "${MACOS_SIGN_IDENTITY:--}" "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"
echo "Signed ($([ -n "${MACOS_SIGN_IDENTITY:-}" ] && echo "identity: $MACOS_SIGN_IDENTITY" || echo "ad-hoc")): $APP_PATH"

echo "Built: $APP_PATH"
