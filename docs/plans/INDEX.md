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
| [Opponent panel](OPPONENT_PANEL.md) | Planned, not built: a second in-game overlay panel on the opposite side showing the opponent's played cards and likely deck, with its own folded rail (colours, cards seen, record against it) and an off state. Needs an `opponent` block on `/api/overlay`, the overlay shell split to run two windows, and memory and CPU measured on both systems. |
| [Streaming](STREAMING.md) | Phase 1, the Stream Kit (OBS browser-source widgets served by the dashboard), is built; it needs a live check in OBS during real games. Six more widgets (scorebug, game result, the opponent's cards, a flood/screw meter, an intermission card, deck stats) are built and need the same live check, with an event-run tracker, session goals and Brawl commanders logged for later. Planned after it: a local Twitch chat bot with a static shareable deck page, vertical clip export from replays, and a Twitch panel extension only if streamers ask for one. |
| [Scaling to large histories](SCALING_LARGE_HISTORIES.md) | Built, needs a live check on Windows (Steps 0 to 3 passed one on macOS): past 32,766 games the Overview and All Games failed on Windows (now fixed); filtered views cost what they show; each finished game's draw quality, colours and land counts are stored once (`game_derived`) and filled for older games by a background pass; the card page finds rows by name and search answers from a per-name summary. On a 38,000-game copy the Overview went from 9.1 s to 2.4 s, All Games from 5.1 s to 0.7 s, a deck page from 4.8 s to 0.4 s, a card page from 2.0 s to 0.3 s, with identical payloads. On macOS the app was being napped (every page about five times slower inside the app than measured); it now opts out (confirmed after a restart: 128 ms in the app against 123 ms in a terminal). A 37,000-game backup merge went from 8 minutes to 34 s. Slow pages asked for lately are rebuilt in the background when a game ends and sent at once past their TTL, so on that copy the Overview opens in 14 ms after a game instead of 5 s. Left: the Windows check and a run of the last step in the real app. Decided to leave: All Games' 22 MB and the event log's growth. |
| [Raw log archive](RAW_LOG_ARCHIVE.md) | Keep each game's original Player.log entries, compressed and bounded (about 200 KB a game), so a future fix can re-derive a game exactly and a reported game can become a fixture. Retention default, opt-in vs default-on and the fate of `console_logs` are open. |
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
