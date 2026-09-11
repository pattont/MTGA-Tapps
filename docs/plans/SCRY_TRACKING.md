# Remaining surveil and scry validation work

Status reviewed 2026-09-10: **scry is implemented** in the tracker, schema,
game/deck statistics, and timeline/Live Scoreboard styling. See the
[current scry reference](../SCRY_TRACKING.md). The remaining feature is
surveil; retain this plan until its evidence and implementation are complete.

## Capture evidence before choosing a handler

- Capture sanitized player surveil and opponent surveil packets, including
  the earlier object snapshots and subsequent library-to-graveyard transfer.
- Confirm annotation type, detail keys, controller attribution, ordering,
  and which card identities are visible. Do not assume surveil has scry's
  keys or that `affectedIds` identifies a seat.
- Capture an opponent scry example to validate the synthetic hidden-card
  fixtures against a real log. Player scry fixtures already have that basis.

## Implement only after the payload shape is established

Reuse `tracker_event_abilities.py`, annotation helpers and focused persistence
helpers. Migration 29 already reserved nullable `surveils`, `surveil_cards`,
and `surveil_graveyard` columns plus `game_library_events` with a `kind` and
`to_graveyard` field. Check the captured shape before deciding whether that
schema is sufficient; do not promise no further migration.

Count events and destinations for both seats, recording only visible
identities. Determine how destination card names fit the event schema rather
than silently using `bottom_names` to mean graveyard cards. Keep library exit
and `cards_milled` accounting owned by the existing zone-transfer path so the
annotation cannot count the same movement twice. Preserve turn placement and
avoid duplicate processing if the annotation is repeated.

Add explicit surveil fields to game/deck API projections and UI rows; they
are not currently in the dashboard's scry projections. Use a clear timeline
style without emoji. Keep old values NULL unless actual historical evidence
can recover them; a real tracked zero is different from unknown history.

## Acceptance

Focused tests cover top-only, graveyard-only, mixed and empty outcomes;
player/opponent seats and hidden IDs; delayed object snapshots; repeated
annotations; no double-counted milling; migration compatibility; event
persistence; and API/UI rendering. Run the full Python suite and frontend
checks from AGENTS.md. Add current behavior to the scry reference/changelog
and remove this plan when complete.

Overlay known-top/bottom ordering remains outside this work. Its current
odds use library composition, not conditioning on revealed order.
