#!/usr/bin/env bash
# Build the in-game overlay (overlay/, a Tauri v2 app) and stage its
# executable in overlay/build-out/, where packaging/mtga_tracker.spec picks
# it up and ships it inside the tracker bundle.
#
# Needs Node 18+ and a Rust toolchain (https://rustup.rs). Without cargo the
# overlay is skipped with a warning and the tracker builds without it —
# set OVERLAY_REQUIRED=1 (CI does) to fail instead.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY_DIR="$ROOT_DIR/overlay"
OUT_DIR="$OVERLAY_DIR/build-out"

if ! command -v cargo >/dev/null 2>&1; then
  if [[ "${OVERLAY_REQUIRED:-0}" == "1" ]]; then
    echo "cargo not found and OVERLAY_REQUIRED=1 — install Rust from https://rustup.rs" >&2
    exit 1
  fi
  echo "!! cargo not found — the in-game overlay is skipped (install Rust from https://rustup.rs to include it)"
  exit 0
fi

cd "$OVERLAY_DIR"
npm ci
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

case "$(uname -s)" in
  Darwin)
    # A real .app so the overlay has a bundle identifier, an icon, and a seal
    # of its own inside the tracker bundle. The tracker's codesign --deep
    # re-signs it together with everything else.
    npm run tauri -- build --bundles app
    cp -R "src-tauri/target/release/bundle/macos/Tapps Overlay.app" "$OUT_DIR/"
    echo "Built: $OUT_DIR/Tapps Overlay.app"
    ;;
  *)
    npm run tauri -- build --no-bundle
    cp "src-tauri/target/release/tapps-overlay" "$OUT_DIR/"
    echo "Built: $OUT_DIR/tapps-overlay"
    ;;
esac
