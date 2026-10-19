#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="$ROOT_DIR/dist/MTGA Tracker.app"
DMG_ROOT="$ROOT_DIR/build/dmg"

if [[ "${SKIP_APP_BUILD:-0}" != "1" ]]; then
  "$ROOT_DIR/scripts/build_macos_app.sh"
elif [[ ! -d "$APP_PATH" ]]; then
  echo "Missing app bundle: $APP_PATH" >&2
  exit 1
fi

# Version is derived from the git tag (setuptools-scm) and registered by the
# `pip install -e .` the app build just ran — so read it AFTER that build.
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"
VERSION="$("$PYTHON" -c 'from importlib.metadata import version; print(version("mtga-tracker"))' 2>/dev/null || true)"
DMG_PATH="$ROOT_DIR/dist/MTGA-Tracker-${VERSION:-dev}.dmg"

rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
cp -R "$APP_PATH" "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"
rm -f "$DMG_PATH"

hdiutil create \
  -volname "MTGA Tracker" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "Built: $DMG_PATH"

# The in-app updater's payload: a zip of the .app (docs/plans/AUTO_UPDATE.md).
# Only ditto keeps the bundle's symlinks and code signature intact (zip -r and
# Python's zipfile both break the seal), and these flags leave out resource
# forks, extended attributes, ACLs and quarantine, so a quarantined build
# tree cannot carry com.apple.quarantine into users' updated apps. The app
# unpacks it with `ditto -x -k --noqtn`. Same version stem as the DMG.
ZIP_PATH="$ROOT_DIR/dist/MTGA-Tracker-${VERSION:-dev}-macos.zip"
rm -f "$ZIP_PATH"
ditto -c -k --norsrc --noextattr --noacl --noqtn --keepParent "$APP_PATH" "$ZIP_PATH"
echo "Built: $ZIP_PATH"
shasum -a 256 "$DMG_PATH" "$ZIP_PATH"
