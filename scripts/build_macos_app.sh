#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"
# Keep PyInstaller's binary cache with the rest of the ignored build output.
# This avoids depending on a writable ~/Library/Application Support directory
# in sandboxed development environments.
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$ROOT_DIR/build/pyinstaller-cache}"
export PYINSTALLER_CONFIG_DIR
FAST_BUILD=0

# Finder/agent shells do not load nvm from ~/.zshrc. The UI and overlay both
# need the same Node toolchain, so resolve it once before either build starts.
# shellcheck source=node_env.sh
source "$ROOT_DIR/scripts/node_env.sh"
ensure_node_tools

for arg in "$@"; do
  case "$arg" in
    --fast) FAST_BUILD=1 ;;
    *) echo "unknown option: $arg (only --fast)" >&2; exit 2 ;;
  esac
done

cd "$ROOT_DIR/ui"
if [[ "$FAST_BUILD" == "0" ]]; then
  npm ci
fi
npm run build

# The in-game overlay (skipped with a warning when Rust isn't installed).
if [[ "$FAST_BUILD" == "1" ]]; then
  "$ROOT_DIR/scripts/build_overlay.sh" --fast
else
  "$ROOT_DIR/scripts/build_overlay.sh"
fi

cd "$ROOT_DIR"
"$ROOT_DIR/scripts/create_macos_icon.sh"
if [[ "$FAST_BUILD" == "0" ]]; then
  "$PYTHON" -m pip install -e '.[gui,build]'
  "$PYTHON" -m PyInstaller --noconfirm --clean packaging/mtga_tracker.spec
else
  echo "Fast development build: using the existing environment and PyInstaller cache"
  "$PYTHON" -m PyInstaller --noconfirm packaging/mtga_tracker.spec
fi

# Seal the finished bundle with an ad-hoc signature. PyInstaller signs the
# individual binaries, but without a valid seal on the BUNDLE, macOS 15+
# shows the hard "Not Opened / Move to Trash" dialog and never offers the
# Privacy & Security "Open Anyway" escape hatch. An ad-hoc seal restores
# that flow for unsigned distribution. MACOS_SIGN_IDENTITY overrides with a
# real Developer ID when one is available.
APP_PATH="$ROOT_DIR/dist/MTGA Tracker.app"
PLIST_PATH="$APP_PATH/Contents/Info.plist"

assert_plist_value() {
  local key="$1"
  local expected="$2"
  local actual
  actual="$(/usr/libexec/PlistBuddy -c "Print :$key" "$PLIST_PATH")"
  if [[ "$actual" != "$expected" ]]; then
    echo "Unexpected $key in app bundle: expected '$expected', got '$actual'" >&2
    exit 1
  fi
}

# These values give macOS and menu-bar managers a stable application identity.
assert_plist_value "CFBundleIdentifier" "com.travispatton.mtgatracker"
assert_plist_value "CFBundleName" "Tapps Tracker"
assert_plist_value "CFBundleDisplayName" "Tapps Tracker"
assert_plist_value "LSUIElement" "true"

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
if [[ "$FAST_BUILD" == "1" ]]; then
  echo "Development build only. Launch with: open \"$APP_PATH\""
fi
