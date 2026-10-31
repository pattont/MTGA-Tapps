# Auto-update: real-machine validation checklist

Run this on the Mac Studio (admin account, Arena installed) and the Windows 11
machine before publishing the first updater-capable release. Everything here
needs two builds: the **previous** release (the one users have, built from the
`auto-update` branch so it carries the updater) and a **newer** one with a higher
tag. Use a separate data directory for every run (`MTGA_TRACKER_DATA_DIR=<scratch>`), never
the real tracker database, and never while a match is in progress.

Record outcomes inline (date, OS version, pass/fail, log excerpt). Anything that
fails goes back to the plan's §9 failure table.

## 0. Build two release candidates

1. Tag an rc on `auto-update`, e.g. `v0.7.0-rc.1`, and let CI build it. Check the
   draft release has all seven assets: `.dmg`, `-macos.zip`, `-setup.exe`,
   `-windows.zip`, `latest.json`, `latest.json.sig`, `SHA256SUMS`, and that the
   `manifest` job logged a verified signature.
2. Tag `v0.7.0-rc.2` the same way. **Rc tags are prereleases and never become
   `releases/latest`**, so the client under test must be pointed elsewhere. The simple
   route: create a throwaway repository (for example `pattont/MTGA-Tapps-updtest`),
   download rc.2's seven assets from the draft with `gh release download`, rebuild and
   sign the manifest locally for that repository
   (`scripts/make_update_manifest.py --tag v0.7.0-rc.2 --repo pattont/MTGA-Tapps-updtest
   --dist <assets> --out <out> --sign-key ~/.config/tapps-tracker/update-signing-key.pem`),
   publish them as a normal release there, and on each test machine launch rc.1 with
   `MTGA_TRACKER_UPDATE_MANIFEST_URL=https://github.com/pattont/MTGA-Tapps-updtest/releases/latest/download/latest.json`.
   The signature check stays on, so this proves the real trust path. Note which route
   was used.

## 1. macOS (Mac Studio)

Install rc.1 from the DMG into `/Applications`, launch it once so it is
provenance-tagged, then:

- [ ] Sidebar shows "Update v… available" within ~2 minutes, then "Downloading",
      then **Restart to update**; the tray shows the same and one notification.
- [ ] Settings → Updates shows current/latest, Check now works, Skip hides the pill,
      Un-skip brings it back.
- [ ] Start a practice match in Arena, click Restart to update: "Finish your game
      first" with **Install after this game**; choose it; finish or concede the game;
      within ~2 minutes of the game ending the install runs by itself.
- [ ] With Arena open but no game: Restart to update asks for confirmation, then
      installs.
- [ ] Hand-off: the app quits, `~/Library/Application Support/MTGA Tracker/updates/`
      has `pending.json` and the helper log, the old bundle lands in
      `updates/rollback/`, the new app launches with **no Gatekeeper or App
      Management prompt**, the old browser tab reloads on its own and shows
      "Updated to v… · What's new" once.
- [ ] `backups/` contains a `pre-update-…tappsbackup`; Settings → Backup & restore
      lists it and a restore preview opens.
- [ ] `codesign --display --requirements - "/Applications/MTGA Tracker.app"` shows
      the same designated requirement before and after (stable identity); Deck
      Finder's "open in Terminal" does not re-prompt for Automation.
- [ ] The overlay restarts after the update and still follows Arena.
- [ ] Start at login survives: the LaunchAgent plist still points at the bundle.
- [ ] Rollback: tamper with the staged zip (flip a byte after download) and confirm
      the SHA-256 mismatch is reported and nothing is swapped; tamper with the
      staged bundle's Info.plist and confirm the helper restores the old bundle and
      relaunches it with `--update-failed`, and the dashboard shows the failure.
- [ ] Auto-install: enable the toggle, quit Arena, restart the app with a ready
      update; it installs without a click. With Arena running it does not.
- [ ] "Install update and quit": with a ready update choose Quit from the tray,
      answer Yes; the install runs and the app does **not** relaunch.

## 2. Windows 11

Install rc.1 with the per-user setup (default), then:

- [ ] Same pill/tray/Settings checks as macOS.
- [ ] Hand-off: the app exits, `%LOCALAPPDATA%\MTGA Tracker\updates\install-<ver>.log`
      shows the `/WAITPID` wait and "installation finished", `_internal` is fully
      replaced, Apps & Features shows the new version, the Run key (Start with
      Windows) still points at the same exe, the app relaunches un-elevated with
      no SmartScreen prompt, and no console window flashes at any point.
- [ ] Windows Security / Defender: no detection during download, install or relaunch
      (check Protection history). Record the Defender definitions version.
- [ ] All-users install (run rc.1's setup, choose "Install for all users"): the pill
      says Windows will ask for permission, clicking it shows the UAC consent, Yes
      upgrades, No leaves the old version running and the dashboard reports it.
      Auto-install never fires for this install.
- [ ] Portable zip: unzip rc.1 anywhere and run it; the pill is a download link only.
- [ ] Rollback: kill the installer during the file copy (or tamper with the
      downloaded setup.exe before the hash re-check): the SHA mismatch is reported,
      or the `--update-failed` relaunch brings the old tracker back.
- [ ] Deck Finder console open (`--deck-finder`) during an update: Restart Manager
      closes it or the update reports what blocked it; nothing is left half-installed.

## 3. Both

- [ ] Migration failure recovery: before the hand-off, copy the scratch DB; after the
      update restore a pre-update backup through Settings → Backup & restore and
      confirm games and settings match.
- [ ] Log gap: start a match immediately after clicking Restart; confirm the tracker
      reports the mid-game attach and the next match is tracked normally.
- [ ] Network off: Check now reports the error and a previously ready update stays
      ready and installable.
- [ ] Kill the app during a download; relaunch resumes the `.part` file.

## Notes from the first Mac run (2026-10-31)

- `MTGA_DATA_DIR` is Arena's card-database folder, not the tracker's data folder.
  Setting it to a scratch folder makes the card DB "not found" and leaves the
  tracker on its real database. The tracker's own folder is `MTGA_TRACKER_DATA_DIR`.
- The relaunched version inherits the old process's environment (the swap helper
  and `open` pass it through), so test overrides carry across the update.
- The pill was missed because it only lived at the bottom of the sidebar. The ready
  state now also shows a banner at the top of every page, a background tab refreshes
  the moment it is shown, and the first check runs 30 s after launch.
