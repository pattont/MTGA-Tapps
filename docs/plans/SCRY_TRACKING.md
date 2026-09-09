# Scry and Surveil Tracking — Plan

Today the tracker sees a scry and writes one word about it: the timeline
says "You: scried" with no count, nothing is persisted, and the deck and
game pages have no idea it happened. This plan covers the log, the data,
the game and deck pages, and the Live Scoreboard. The overlay is
deliberately left alone: it stays a decklist with odds, and scry does not
touch it (see §6).

## 1. What the log gives us

Arena reports a scry as its own annotation once the player has made the
choice (not when the ability is put on the stack):

```
{"type":["AnnotationType_Scry"],
 "affectorId": <ability instance id>,
 "affectedIds": [<seat id>],
 "details":[{"key":"topIds","valueInt32":[101]},
            {"key":"bottomIds","valueInt32":[102,103]}]}
```

- `topIds` and `bottomIds` are instance ids of the cards, in their new
  order. Together they are the scry amount. Either list can be empty.
- For the **player's own scry** the instance ids resolve to game objects
  with a `grpId`, so the tracker knows *which* card stayed on top and which
  went under. For the **opponent's** scry the objects are hidden — counts
  only, which is still the stat.
- `AnnotationDetails` (`annotations.py`) already parses `topIds` /
  `bottomIds`; `_handle_scry_annotation` in `tracker_event_abilities.py`
  currently ignores them.
- The scrying seat: `affectedIds[0]` is the seat; the ability's
  `controllerSeatId` agrees. The source card is the ability object's
  `objectSourceGrpId` (Simulacrum Synthesizer, Opt, …).

Two neighbours have to be settled from real logs before coding, because I
have not seen their exact shape in this repo's fixtures:

- **Surveil** ("look at the top N, any number to the graveyard"). Expected
  either as `AnnotationType_Surveil` with the same detail keys, or as a
  scry-shaped annotation whose "bottom" cards then show up as
  `ZoneTransfer` Library → Graveyard with a `Surveil` category. Either way
  the graveyard-bound cards are already counted as milled/left-library by
  the zone-transfer path; the plan must not double count them.
- **Reorder-and-look effects** that are not scry (Ponder, Brainstorm,
  "look at the top card"): these arrive as `RevealedCardCreated` /
  `ZoneTransfer` traffic, not as a scry annotation. Out of scope.

**Step 0 of the work is a log sample of each:** cast Opt, a surveil card
(any "surveil 1"), and get scried against by an opponent, then keep the
three snippets under `tests/fixtures/scry/`.

## 2. Data model

**Per game, per seat** — columns on `game_participant_stats`, nullable like
`poison_added` so an old game reads "not tracked" rather than 0:

| Column | Meaning |
| --- | --- |
| `scries` | Number of scry events |
| `scry_cards` | Cards looked at across those scries (the "scry 2" total) |
| `scry_top` | Cards kept on top |
| `scry_bottom` | Cards sent to the bottom |
| `surveils` | Number of surveil events |
| `surveil_cards` | Cards looked at |
| `surveil_graveyard` | Cards put in the graveyard by surveil |

Same names in `state.py`'s per-seat stats dict, in the upsert in
`tracker_analytics.py`, and in `dashboard._INTERACTION_STAT_COLUMNS` so
the deck page averages them without any further plumbing.

**Per event** — a new table `game_library_events`, because "which cards
did I bottom with this deck" is the question that follows "how often do I
scry", and it cannot be answered from totals:

```
game_library_events(id, game_id, participant_id, turn_number, event_time,
                    kind TEXT ('scry'|'surveil'),
                    looked INTEGER, kept_top INTEGER, bottomed INTEGER, to_graveyard INTEGER,
                    source_card TEXT,          -- the card whose ability scried
                    top_names TEXT,            -- JSON list, player only, in order
                    bottom_names TEXT)         -- JSON list, player only
```

The stats columns are the sums of this table; the table is the source of
truth and makes the timeline text, the game page detail and any future
per-card view ("Bottomed 14 times: Plains ×9, …") cheap.

**Migration**: one version adding the columns and the table, plus a
backfill that counts `scries` for historical games from the existing
"scried" timeline rows (that word is all the old timeline has, so only the
event count is recoverable; the card totals stay NULL for old games).

## 3. Tracker

`_handle_scry_annotation(affected_ids, card_obj)` grows into
`_handle_library_look(annotation, kind)`:

1. Seat from `affectedIds[0]`, falling back to the ability's controller.
2. `details = AnnotationDetails.from_annotation(annotation)`;
   `looked = len(top_ids) + len(bottom_ids)`.
3. For the player's seat, resolve each id through `_lookup_object` →
   `grpId` → card name (skip, don't placeholder, anything that is not a
   `GameObjectType_Card`, per the draw fix).
4. Bump the seat stats; append a `game_library_events` row through the
   analytics store (same best-effort pattern as `record_raw_payload`).
5. Timeline line, actor-formatted like the rest:
   - own: `🔮 You: scried 2 — kept [Llanowar Elves] on top, bottomed [Plains]`
   - own, all one way: `scried 1 — kept [Opt] on top` / `scried 2 — bottomed both`
   - opponent: `Opponent: scried 2 — 1 top, 1 bottom`
   - surveil: `surveiled 2 — [Card] to graveyard, kept 1 on top`
   Style `scry` (new) so the Live Scoreboard and game timeline can badge it
   distinctly from generic abilities; the source card is already on the
   preceding ability line, so it is not repeated.
6. The scry annotation can arrive in the same packet as the ability's
   resolution; keep the current turn-header flush so the line lands under
   the right turn.

## 4. Dashboard

- **Game page** (`GameDetailPage`): a new group in Combat & Resources,
  "Library", after Cards: Scries · Cards scried · Kept on top · Bottomed ·
  Surveils · To graveyard. Same two-column you/opponent layout as the
  other groups. Below it (or in the timeline, which already gets the
  lines) nothing more is needed for v1.
- **Deck page** (`DeckDetailPage`): the same rows appear automatically in
  the per-game averages once the columns are in `_INTERACTION_STAT_COLUMNS`.
  Add one derived figure that is actually decision-useful: **bottom
  rate** = `scry_bottom / scry_cards` ("with this deck you bottom 38 % of
  what you scry" — a high number is a deck that is happy with its top,
  a low one is fishing). And, from `game_library_events`, a small
  "Bottomed most" list (card name × count) for the player's deck — the
  first thing a brewer will look for.
- **API**: game and deck payloads carry the new columns; a
  `library_events` list per game for the game page; `bottomed_most` on
  the deck page (top 10).
- **Overview / opponents**: nothing in v1.

## 5. Live Scoreboard

Nothing structural: it renders `game_events`, so the new lines show up on
their own. Two touches so they read as what they are:

- The new `scry` style gets its own badge (a library-ish blue) next to
  `ability` in `LiveLogPage`'s style map, so "scried 2 — kept [Opt] on
  top, bottomed [Plains]" is not filed under generic abilities.
- The scoreboard's per-side stat chips (the ones that show cards drawn
  and the like mid-game) gain a **Scried n · ⬆ top · ⬇ bottom** chip once
  the first scry happens in the game, fed from the same live seat stats
  the row is written from. Absent until then — most games never scry, and
  an empty chip is noise.

## 6. Overlay — unchanged

Scry is intentionally not modelled in the overlay. The overlay's job is
the decklist and its odds; adding "known top card" logic means a second
set of odds rules, a strip that appears and disappears, tags on rows, and
a shuffle/draw bookkeeping path — all of which have to be right every time
or the overlay is lying, and none of which the player needs, because
Arena already showed them the card they just scried. The overlay keeps
quoting the plain hypergeometric odds, which are correct in expectation
over the remaining library. If that ever changes, it is a separate plan.

## 7. Tests

- `tests/test_annotations.py`: scry with top+bottom, top only, bottom only,
  opponent (hidden ids); surveil shape once captured.
- Tracker: stats increments per seat; timeline text for own/opponent;
  `game_library_events` rows with names for the player and NULL names for
  the opponent; no double count of surveil graveyard cards against
  `cards_milled`.
- Live Scoreboard: the `scry` badge renders; the chip appears only after
  the first scry.
- Migration: columns added NULL, backfill counts "scried" lines only.
- Dashboard API: game payload carries the group; deck payload carries the
  averages, `bottom_rate`, and `bottomed_most`.

## 8. Order and effort

| Step | Scope | Effort |
| --- | --- | --- |
| 0 | Capture the three log samples (Opt, surveil, opponent scry) into fixtures | ½ session, needs a few games |
| 1 | Annotation handler + seat stats + timeline lines + `game_library_events` + migration/backfill | 1 session |
| 2 | Game page group, deck page rows + bottom rate + bottomed-most, API | ½–1 session |
| 3 | Live Scoreboard badge and chip | ¼ session |
| 4 | Surveil, once its shape is confirmed (same handler, second `kind`) | ½ session |

Steps 1–3 are the feature; 4 is the natural extension and ships in a later
release without touching the schema again (surveil columns are created in
step 1 and simply stay NULL until step 4 fills them). About two sessions
in total.
