#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"

cd "$ROOT_DIR/ui"
npm ci
npm run build

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
codesign --force --deep --sign "${MACOS_SIGN_IDENTITY:--}" "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"
echo "Signed ($([ -n "${MACOS_SIGN_IDENTITY:-}" ] && echo "identity: $MACOS_SIGN_IDENTITY" || echo "ad-hoc")): $APP_PATH"

echo "Built: $APP_PATH"
