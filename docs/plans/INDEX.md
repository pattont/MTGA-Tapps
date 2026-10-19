# Active implementation plans

Reviewed against the source on 2026-09-10. This folder contains unfinished
work; the root README describes delivered behavior and links to reference
or operational documentation only.

| Plan | Current status | Remaining work |
| --- | --- | --- |
| [Replay](REPLAY.md) | Built 2026-10-07: one enriched `game_events` stream (capture + builder), text reconstructor for older games, `GET /api/replay`, three.js replay page with turn scrubber, action log, felt/sleeve colors, and entry points (sidebar tile, list, Game Detail, row icons, Live, console link, menu). Contract: `docs/REPLAY_FORMAT.md` Phase 4 built 2026-10-10: in-browser MP4 export (WebCodecs + mp4-muxer), cards exiled by a permanent tucked under it, hover list and pictures of a stack, printed stats from Arena's card DB; validated on live recorded games. | Overlay "Watch replay" button, optional local image cache |
| [Deck Manager](DECK_MANAGER.md) | Researched 2026-10-06; proposal only. Windows native local-deck precedent found; current local Mac Arena is IL2CPP | Current-build/platform feasibility, durable deck library, exact capture, verified store/restore, full-slot swaps, and an optional native collection section |
| [Backups and carrying history between computers](BACKUP_AND_SYNC.md) | Phases 1–2 shipped: `.tappsbackup` export/restore/merge, synced-folder picks, previews with confirmation, undo, delete and open-location (Settings → Backup & restore) | Automatic post-session backups; Google Drive by API only if the folder route proves insufficient |
| [Deck Manager](DECK_MANAGER.md) | Local library plus native dashboard bulk backup/move/restore, account guards, transfer progress, collapsible collections and migrations 33–34 implemented on `deck-manager`; integrated live roster refresh and 94-deck backup passed; [Mac POC](deck-manager/NATIVE_POC.md) proves disk restoration | Integrated move/restore validation through isolated live dashboard, persistent native collection/tiles, installed-bundle permissions and Windows support |
| [In-app auto-update](AUTO_UPDATE.md) | Built 2026-10-18 on `auto-update`: signed `latest.json` + `manifest` CI job, `ditto` macOS zip, Inno `/WAITPID`/`/RELAUNCH` hand-off, `UpdateManager` with `GET/POST /api/update*`, sidebar pill, tray item, Settings → Updates (check / auto-download / opt-in auto-install), pre-update `.tappsbackup`, per-migration transactions; research in [`auto-update/`](auto-update/) | Real-machine validation on the Mac Studio and the Windows 11 machine (first release candidate), Linux hand-off, beta channel |
| [Linux support](linux_implementation.md) | Not implemented as a supported distribution | Prefix discovery/rotation, tray-free controller, overlay, packaging and desktop validation |
| [Install discovery](MTGA_INSTALL_DISCOVERY.md) | Unity-header discovery and Settings path display implemented | Editable overrides/validation; evidence-driven platform fallbacks |
| [Surveil and scry validation](SCRY_TRACKING.md) | Scry implemented, migration 29 present | Surveil log capture/handler/UI and real opponent-scry validation |
| [Opponent deck matching](opponent_deck_research.md) | Proposal; no corpus/matcher tables or modules | Evidence-aware matching against cached decklists; review observed-copy assumptions first |
| [Format legality](valid_cards_per_format.md) | Proposal; no legality cache/filter | Revalidate data source and historical legality semantics before implementation |

The completed release plan was replaced by [the release guide](../RELEASING.md).
The completed YouTube creator plan was replaced by the
[YouTube creator guide](../DECK_FINDER_YOUTUBE.md).
The completed overlay plan was removed; [the overlay guide](../../overlay/README.md)
and changelog describe the actual implementation. The old plan included
superseded choices (off by default, its own tray, no card art, known-top
odds) and unverified performance targets; those are not outstanding promises.
Original `overlay-mockup.html` and `overlay-mockup.png` remain as historical
visual assets, not implementation specifications.
The approved Deck Finder previews in `deck-finder-style/` also remain as
historical visual assets; the implemented layout is described in the
[Deck Finder guide](../DECK_FINDER_YOUTUBE.md#browsing-and-deck-details).

When a plan is completed, move durable behavioral information into the
appropriate reference, record the delivered feature in the changelog, remove
the obsolete plan, and update this index and its incoming links. Partially
completed plans should describe only the remaining work and link to the
current behavior for context.
