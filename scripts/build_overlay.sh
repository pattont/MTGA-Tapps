#!/usr/bin/env bash
# Build the in-game overlay (overlay/, a Tauri v2 app) and stage its
# executable in overlay/build-out/, where packaging/mtga_tracker.spec picks
# it up and ships it inside the tracker bundle.
#
#   scripts/build_overlay.sh          release build (what ships: fat LTO,
#                                     size-optimised; slow to relink)
#   scripts/build_overlay.sh --fast   iteration build: the `fast` cargo
#                                     profile (no LTO, incremental) in its
#                                     own target/fast/ so it never evicts
#                                     the release cache. Same binary layout,
#                                     Start/Stop Overlay picks it up as usual.
#
# npm dependencies are installed only when package-lock.json changed.
#
# Needs Node 18+ and a Rust toolchain (https://rustup.rs). Without cargo the
# overlay is skipped with a warning and the tracker builds without it —
# set OVERLAY_REQUIRED=1 (CI does) to fail instead.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY_DIR="$ROOT_DIR/overlay"
OUT_DIR="$OVERLAY_DIR/build-out"

# (the ${arr[@]+...} form keeps macOS's bash 3.2 happy with an empty array under set -u)
PROFILE=release
CARGO_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --fast) PROFILE=fast; CARGO_ARGS=(-- --profile fast) ;;
    *) echo "unknown option: $arg (only --fast)" >&2; exit 2 ;;
  esac
done

if ! command -v cargo >/dev/null 2>&1; then
  if [[ "${OVERLAY_REQUIRED:-0}" == "1" ]]; then
    echo "cargo not found and OVERLAY_REQUIRED=1 — install Rust from https://rustup.rs" >&2
    exit 1
  fi
  echo "!! cargo not found — the in-game overlay is skipped (install Rust from https://rustup.rs to include it)"
  exit 0
fi

cd "$OVERLAY_DIR"

# `npm ci` wipes node_modules and reinstalls every time (~10 s); only do it
# when the lockfile is newer than what is installed.
if [[ ! -f node_modules/.package-lock.json || package-lock.json -nt node_modules/.package-lock.json ]]; then
  npm ci
else
  echo "node_modules up to date (npm ci skipped)"
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

case "$(uname -s)" in
  Darwin)
    # A real .app so the overlay has a bundle identifier, an icon, and a seal
    # of its own inside the tracker bundle. The tracker's codesign --deep
    # re-signs it together with everything else.
    npm run tauri -- build --bundles app ${CARGO_ARGS[@]+"${CARGO_ARGS[@]}"}
    cp -R "src-tauri/target/$PROFILE/bundle/macos/Tapps Overlay.app" "$OUT_DIR/"
    echo "Built ($PROFILE): $OUT_DIR/Tapps Overlay.app"
    ;;
  *)
    npm run tauri -- build --no-bundle ${CARGO_ARGS[@]+"${CARGO_ARGS[@]}"}
    cp "src-tauri/target/$PROFILE/tapps-overlay" "$OUT_DIR/"
    echo "Built ($PROFILE): $OUT_DIR/tapps-overlay"
    ;;
esac
