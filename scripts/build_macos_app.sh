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

echo "Built: $ROOT_DIR/dist/MTGA Tracker.app"
