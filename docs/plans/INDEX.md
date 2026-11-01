# Open work and research

Current features are documented in the [README](../../README.md) and technical
references. This folder holds only unfinished work, research that needs fresh
validation, and native Deck Manager test evidence. Completed mockups and
implementation walkthroughs have been removed.

| Detailed plan | Remaining work |
| --- | --- |
| [Linux support](linux_implementation.md) | Discovery, controller, overlay, packaging and desktop validation. |
| [Install discovery](MTGA_INSTALL_DISCOVERY.md) | Editable overrides and evidence-driven platform fallbacks; [current behavior](../MTGA_INSTALL_DISCOVERY.md) is documented separately. |
| [In-app auto-update](AUTO_UPDATE.md) | Built and validated 2026-10-31: a real 0.7.5rc1 → rc2 update ran end to end on macOS (bundle swap, relaunch, pre-update backup) and Windows 11 (silent installer hand-off) from a signed test feed. Remaining: confirm the first public updater release on both systems after it ships, the remaining [checklist](auto-update/VALIDATION.md) cases (in-game block, rollback, all-users UAC), portable self-update, the Linux hand-off and a beta channel. Research reports live in [`auto-update/`](auto-update/). |
| [Opponent deck matching](opponent_deck_research.md) | Evidence-aware matching against cached decklists. The proposed thresholds and timings still need validation. |
| [Streaming](STREAMING.md) | Phase 1, the Stream Kit (OBS browser-source widgets served by the dashboard), is built; it needs a live check in OBS during real games. Planned after it: a local Twitch chat bot with a static shareable deck page, vertical clip export from replays, and a Twitch panel extension only if streamers ask for one. |
| [Flood impact](FLOOD_IMPACT.md) | Estimate whether extra lands hurt a game from what the player did (lands tapped, lands stuck in hand) and the deck's own history, never from printed card costs. Needs a hand review of real games first; may not ship if it doesn't hold up. |

## Smaller follow-ups

- **Replay:** Consider an overlay entry point after a game and a bounded local
  cache of card-image bytes for offline playback. [Current behavior](../../README.md#replay-beta)
  and the [data contract](../REPLAY_FORMAT.md) are documented separately.
- **Deck Manager:** A persistent collection inside Arena, a guarded full-slot
  swap and automatic backups remain future work.
  Native removal must follow a verified local archive; interrupted operations
  must reconcile without repeating a write. Keep the [native proof of concept](deck-manager/NATIVE_POC.md)
  as evidence, not a release support claim. [Current behavior](../../README.md#deck-manager-beta) is in the README.
- **Backup and sync:** An opt-in automatic backup after completed sessions
  should reuse the existing online SQLite snapshot and `.tappsbackup` format,
  with bounded retention and visible failure status. Direct cloud APIs need a
  separate design only if sync-client folders prove insufficient.
- **Surveil:** Capture and display surveil choices with the same seat,
  visibility and destination rules as scry. Validate opponent scry attribution
  against more real logs. Until then, surveil columns remain NULL.
- **Format legality:** No legality cache or filter is implemented. Before
  building one, recheck the source and historical legality rules, avoid
  rewriting historical games from current banlists, and treat unknown Alchemy
  legality as unknown. The old bulk-data sizes and format assumptions were
  time-sensitive research, so they are not a current implementation spec.

The [release guide](../RELEASING.md) covers builds and publishing. The
[overlay guide](../../overlay/README.md) documents the shipped overlay.
