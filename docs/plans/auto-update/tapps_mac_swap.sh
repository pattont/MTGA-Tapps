#!/bin/bash
# Tapps Tracker macOS update helper. Spawned detached by the running app,
# which then exits. Usage:
#   tapps_mac_swap.sh <parent_pid> <staged_app> <target_app> <rollback_dir> <old_ver> <new_ver> [bundle_id]
# Exit codes: 0 swapped+relaunched, 10 parent never exited, 11 staged bundle
# invalid, 12 cross-volume, 13 could not move old aside, 14 could not move new
# in (rolled back), 15 overlay helper still running.
set -u
PARENT_PID="$1"; STAGED="$2"; TARGET="$3"; ROLLBACK_DIR="$4"
OLD_VER="$5"; NEW_VER="$6"; BUNDLE_ID="${7:-com.travispatton.mtgatracker}"
WAIT_SECONDS="${TAPPS_SWAP_WAIT_SECONDS:-60}"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
PLISTBUDDY=/usr/libexec/PlistBuddy

log() { printf '%s %s\n' "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

relaunch() {  # $1 = extra args after --args
  [ -n "${TAPPS_SWAP_NO_LAUNCH:-}" ] && { log "relaunch suppressed: $*"; return 0; }
  "$LSREGISTER" -f "$TARGET" >/dev/null 2>&1 || true
  /usr/bin/open -n "$TARGET" --args "$@"
}

# 1. Wait for the old process to be fully gone (all files closed).
deadline=$(( $(/bin/date +%s) + WAIT_SECONDS ))
while /bin/kill -0 "$PARENT_PID" 2>/dev/null; do
  if [ "$(/bin/date +%s)" -ge "$deadline" ]; then
    log "parent $PARENT_PID still running after ${WAIT_SECONDS}s; not swapping"; exit 10
  fi
  /bin/sleep 0.2
done
log "parent $PARENT_PID exited"

# 2. The overlay helper lives inside the bundle being replaced. The app stops
#    it before exiting; anything left is terminated so the new tracker does not
#    mistake a stale overlay (whose argv path now names the NEW bundle) for its own.
OVERLAY_EXE="$TARGET/Contents/Helpers/Tapps Overlay.app/Contents/MacOS/tapps-overlay"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  pids=$(/usr/bin/pgrep -f "^$OVERLAY_EXE" || true)
  [ -z "$pids" ] && break
  /bin/kill -TERM $pids 2>/dev/null || true
  /bin/sleep 0.3
done
if [ -n "$(/usr/bin/pgrep -f "^$OVERLAY_EXE" || true)" ]; then
  # Nothing was touched yet: bring the old version back instead of leaving no app.
  log "overlay still running"; relaunch --update-failed "$NEW_VER"; exit 15
fi

# 3. Validate the staged bundle (signature, identity, version).
if ! /usr/bin/codesign --verify --deep --strict "$STAGED" 2>/dev/null; then
  log "staged bundle fails codesign verification"; relaunch --update-failed "$NEW_VER"; exit 11
fi
sid=$("$PLISTBUDDY" -c 'Print :CFBundleIdentifier' "$STAGED/Contents/Info.plist" 2>/dev/null)
sver=$("$PLISTBUDDY" -c 'Print :CFBundleShortVersionString' "$STAGED/Contents/Info.plist" 2>/dev/null)
if [ "$sid" != "$BUNDLE_ID" ] || [ "$sver" != "$NEW_VER" ]; then
  log "staged bundle identity mismatch: $sid $sver"; relaunch --update-failed "$NEW_VER"; exit 11
fi
/usr/bin/xattr -dr com.apple.quarantine "$STAGED" 2>/dev/null || true

# 4. Renames must stay on one volume to be atomic.
/bin/mkdir -p "$ROLLBACK_DIR"
if [ "$(/usr/bin/stat -f %d "$STAGED")" != "$(/usr/bin/stat -f %d "$(/usr/bin/dirname "$TARGET")")" ] || \
   [ "$(/usr/bin/stat -f %d "$ROLLBACK_DIR")" != "$(/usr/bin/stat -f %d "$(/usr/bin/dirname "$TARGET")")" ]; then
  log "staging/rollback dir not on the target volume"; relaunch --update-failed "$NEW_VER"; exit 12
fi

# 5. Swap: old -> rollback, staged -> target. Roll back on failure.
ROLLBACK_APP="$ROLLBACK_DIR/$(/usr/bin/basename "$TARGET")"
/bin/rm -rf "$ROLLBACK_APP"
if ! /bin/mv "$TARGET" "$ROLLBACK_APP"; then
  log "cannot move old bundle aside (permissions/App Management?)"; relaunch --update-failed "$NEW_VER"; exit 13
fi
if ! /bin/mv "$STAGED" "$TARGET"; then
  log "cannot move new bundle into place; restoring old"
  /bin/mv "$ROLLBACK_APP" "$TARGET"
  relaunch --update-failed "$NEW_VER"; exit 14
fi
/usr/bin/touch "$TARGET"
log "swapped $OLD_VER -> $NEW_VER"

# 6. Relaunch the new version. The rollback copy is deleted by the new
#    version once it has started cleanly (or on the next update).
relaunch --updated-from "$OLD_VER"
exit 0
