# macOS Debug: App Icon "Shudders" but Never Launches

## Reported symptom

> It doesn't come up at all. The app icon "shudders" a little bit but then
> nothing happens. It doesn't show up in the activity monitor either.

The user later got it working by bypassing the app icon:

> I went to show package contents -> MacOS -> MTGA Tracker exec file. I guess
> there is something broken where the application icon doesn't run the
> executable for some reason.

## Diagnosis

The pattern — icon bounces once, no dialog, no process in Activity Monitor,
but the raw executable inside `Contents/MacOS` runs fine — is the classic
signature of macOS refusing the **bundle** at launch while the binary itself
is still fine.

The build is a PyInstaller app sealed with an ad-hoc signature
(`scripts/build_macos_app.sh` runs `codesign --force --deep --sign -`), and
that setup fails in exactly this silent way when something invalidates the
seal.

### The mechanism

Double-clicking the icon goes through LaunchServices/Gatekeeper, which
validates the whole bundle's resource seal before letting it launch. If the
seal doesn't match the contents, macOS 14/15 will often kill it instantly
with no UI at all — just the one dock bounce.

Double-clicking the executable inside `Contents/MacOS` bypasses the bundle
check entirely (it launches via Terminal and only the binary's own signature
matters), which is why the workaround works.

### How the seal gets broken for an ad-hoc-signed app

- It was transferred in a way that altered the bundle: a zip made without
  `ditto`, AirDrop, some extraction tools, or cloud-drive sync mangling
  extended attributes or symlinks.
- The user "repaired" or touched anything inside the `.app`.
- An ad-hoc signature plus a quarantine flag on a strict macOS 15 install.

One thing ruled out: the frozen build writes all its data to
`~/Library/Application Support/MTGA Tracker`, never inside the bundle
(`src/mtga_tracker/paths.py`), so the app is not breaking its own seal at
runtime.

## Confirm and fix

Have the user run:

```sh
codesign --verify --deep --strict "/Applications/MTGA Tracker.app"
```

If that prints "resource fork, Finder information, or similar detritus not
allowed" or "code signature invalid," that's the whole story. The repair is
either re-sealing in place:

```sh
xattr -cr "/Applications/MTGA Tracker.app"
codesign --force --deep -s - "/Applications/MTGA Tracker.app"
```

…or just rebuilding/re-downloading the app.

If codesign verifies clean, the fallback suspect is a stale LaunchServices
registration, and running:

```sh
open "/Applications/MTGA Tracker.app"
```

from Terminal will at least print the real error instead of failing silently.

## Durable fixes if this keeps coming up

- Distribute a proper `ditto`-made zip or a DMG so the bundle survives
  transfer intact.
- Eventually, a real Developer ID + notarization, which makes Gatekeeper
  behave predictably instead of silently killing the app.
