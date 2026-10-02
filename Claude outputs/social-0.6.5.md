# X / Twitter

Tapps Tracker 0.6.5 is out: startup controls, correct Powered Cube/new-event labels, accurate historical deck colors, safer restore, duplicate-instance protection, and macOS overlay/menu-bar fixes.

Download: https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.5

# Reddit

## Suggested title

Tapps Tracker 0.6.5 — startup controls and a batch of reliability fixes

## Post

Hi! Tapps Tracker 0.6.5 is available for Windows and macOS.

This is mostly a reliability release built from issues people reported while actually using the tracker.

### What's fixed

- **Independent startup options:** Tapps can start with Windows/macOS in the tray or menu bar without opening the dashboard in your browser.
- **Unknown events no longer become Brawl:** Arena's queue/event identifier now wins over deck metadata and command-zone guesses.
- **Powered Cube is labeled correctly:** existing affected matches are repaired automatically.
- **Generic events are filterable:** names such as `Constructed_Event_2026` display as **Constructed Event** and appear under **Events** in Recent Games and All Games.
- **Historical deck colors stay correct:** previous draft games use the deck snapshot submitted for that game instead of the colors of your newest draft deck.
- **Restore reports the restored history correctly:** fixed successful restores briefly appearing to contain zero games.
- **Only one tracker instance runs:** duplicate Windows and macOS launches are blocked without preventing Deck Finder from opening.
- **Overlay fixes:** newer macOS versions no longer make the overlay disappear when Arena is in front, an existing overlay no longer switches itself off after a tracker restart, and the minimal-rail settings scrollbar is gone.
- **Better macOS identity:** the installed app identifies itself as Tapps Tracker to macOS and menu-bar managers while keeping the existing app filename and data location for upgrades.

Your existing games and settings carry over normally.

Download 0.6.5:\
https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.5

Full changes:\
https://github.com/pattont/MTGA-Tapps/compare/v0.6.4...v0.6.5