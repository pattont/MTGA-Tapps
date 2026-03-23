Live watch started 2026-03-22 22:29:33
2026-03-22 22:30:50 Watcher attached to Player.log
2026-03-22 22:30:55 Watcher attached to Player.log
2026-03-22 22:30:58 UserActionTaken with abilityGrpId observed; useful for mapping clicked activations to card abilities.
2026-03-22 22:31:10 ActionType_Cast with manaCost observed in live actions array; useful for cast/resolve correlation.
2026-03-22 22:32:14 ResolutionStart with grpid observed; useful for hidden triggered/resolve text mapping.
2026-03-22 22:36:04 AbilityInstanceCreated observed; useful for correlating clicked abilities to the same source permanent.
2026-03-22 22:37:44 AbilityInstanceDeleted observed; useful for determining when an activated ability lifecycle ends.
2026-03-22 22:39:00 ActionType_Activate with manaCost observed; good signal for activated ability resolution details.
2026-03-22 22:39:45 Match room reservedPlayers observed; useful if opponent name/seat detection becomes available.
2026-03-22 22:40:06 CommandZone metadata observed; if this is non-Brawl, stale commander leakage is a risk.
2026-03-22 22:57:19 MulliganType observed in game info; useful for validating mulligan counting.
2026-03-22 22:57:44 ZoneTransfer action observed; check discard/return/exile chain attribution if this is a known missing event type.
2026-03-22 22:59:43 PhaseOrStepModified observed; useful when turn banners and end-of-turn resolution ordering look off.
