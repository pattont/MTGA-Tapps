# Scry tracking

The tracker records scry choices for both seats, shows them in the game
timeline and Live Scoreboard, and aggregates them on game and deck pages.
The implementation is in `tracker_event_abilities.py`, with focused
payload fixtures in `tests/test_scry_tracking.py`.

## Log evidence and seat attribution

`AnnotationType_Scry` contains `topIds` and `bottomIds` in its details;
an empty destination may have a key with no value. `affectedIds` contains
the **card instance IDs**, not the scrying seat. The ability identified by
`affectorId` supplies `controllerSeatId`; the tracker falls back to the
looked-at cards' owner seat if necessary. Objects may have appeared in an
earlier packet, so resolution uses retained object snapshots.

Player card identities are included when visible. Opponent choices show
counts without exposing hidden card names. Example timeline lines:

```text
You: scried 2 — kept [Opt] on top, bottomed [Plains]
Opponent: scried 2 — 1 top, 1 bottom
```

The dedicated `scry` style renders with a Scry badge in the dashboard.

## Persistence and presentation

Migration 29 adds nullable per-seat `game_participant_stats` columns:
`scries`, `scry_cards`, `scry_top`, and `scry_bottom`. `game_library_events`
stores the game/participant, turn/time, kind, looked/kept/bottomed/graveyard
counts, source card, and JSON card-name lists. The game API returns these
events as `library_events`.

Game and deck pages show a **Scry** group beneath Cards in Combat &
Resources: Scried, Cards scried, Scried Top, and Scried Bottom. The last
two include their shares of cards scried. Deck values are per-game
averages. Per-event names are stored but there is no bottomed-most card
list on the deck page or `bottomed_most` field in its API.

The migration recovers historical scry event counts from existing timeline
rows. Historical card totals remain NULL because the old events did not
record amounts or destinations; games without timelines keep unknown
counts too. NULL means unavailable, not zero.

Surveil columns (`surveils`, `surveil_cards`, `surveil_graveyard`) exist but
remain NULL; there is no surveil handler. Opponent scry handling is covered
by synthetic hidden-card fixtures, while the player fixtures are based on
captured packets.

The overlay displays unconditional library-composition odds. It does not
model the known top/bottom order after scry; those percentages are not a
prediction conditioned on the card Arena just showed the player.
