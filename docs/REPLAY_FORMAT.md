# Replay data contract

This document is the single contract between the three parts of the Replay
feature. Each part is built independently against it:

1. **Capture** (tracker mixins): writes structured `game_events` rows for new
   games (`replay_version = 1`).
2. **Serving** (dashboard): turns rows into the replay stream JSON, or
   reconstructs a stream from text rows for older games.
3. **Playback** (`ui/src/replay/`): reduces the stream into board states and
   renders them.

The [README's Replay section](../README.md#replay-beta) covers the viewer;
[smaller follow-ups](plans/INDEX.md#smaller-follow-ups) are tracked separately.
Change this file first whenever
any field below changes; bump `replay_version` / `stream.version` when the
change is not additive.

Terminology: **seat** is Arena's `seatId` (1 or 2, never assume the local
player is seat 1); **role** is `player` or `opponent`. **Object** is one card
instance on the table; **card** is its printed identity.

## 1. Capture: `game_events` rows for `replay_version = 1`

Existing columns (unchanged meaning): `id, session_id, match_id, game_id,
event_time, elapsed_seconds, turn_number, phase, step, participant_id,
seat_id, actor_role, event_type, event_subtype, text, source_card_id,
target_card_id, amount, zone_from, zone_to, player_life, opponent_life,
payload_json`.

Columns added for replay (already in `ensure_schema`): `object_id INTEGER`,
`target_object_id INTEGER`, `arena_id INTEGER`, `controller_seat INTEGER`,
`visible INTEGER NOT NULL DEFAULT 1`; and `games.replay_version INTEGER`.

### Row kinds

- **Printed rows** (`visible = 1`): exactly the rows written today by
  `_record_game_event` from `_print_event`. The console text, the Game Detail
  timeline and the Live Scoreboard feed must not change. For `replay_version
  = 1` games these rows additionally carry the structured fields below.
- **Silent rows** (`visible = 0`): replay-only facts the console never
  prints. They store `game_id` only: **empty-string `session_id` (the column is
  NOT NULL), NULL `match_id` and `participant_id`** (purge and merge work by `game_id`; the one
  session-keyed reader filters `visible = 1`, and migration 32 makes the
  session index partial over printed rows), plus a short machine text (for
  example `untap 5`). Untaps are **one row per untap step**, never one per
  permanent. Measured cost after this change is about 34 KB per game
  (111 silent rows plus payloads on printed rows).
- Every reader of printed history (`game_detail` timeline, `live_api`
  events, `events_backfill`, `db_audit`, the previous-turn recovery) filters
  `visible = 1` or is verified to be unaffected by silent rows.

### Field semantics (both row kinds)

| Column | Meaning |
| --- | --- |
| `event_subtype` | The replay **kind** (table below). Required on every row of a `replay_version = 1` game, printed or silent. Rows the tracker cannot classify get `note`. |
| `seat_id` | Acting seat: the owner of a moved card, the player gaining or losing life, the attacking seat, the controller of a stack item. Keep the current `_infer_event_actor` fallback for printed rows. |
| `actor_role` | `player` / `opponent` for `seat_id`. |
| `object_id` | Arena instance id of the primary object, **after** root resolution through the tracker's `ObjectIdChanged` map (`instance_roots`): the id a card had when it first appeared is the id it keeps for the whole game. Hidden cards (opponent hand, library) have instance ids too; record them. |
| `target_object_id` | Secondary object: damage target, attach target, blocked attacker, spell target (first target). |
| `arena_id` | grpId of the primary object; NULL when hidden or unknown. For transformed/copied objects, the **current** face's grpId. |
| `controller_seat` | Controller of the primary object at event time (differs from `seat_id` for stolen permanents). |
| `zone_from`, `zone_to` | Normalized zone names: `library`, `hand`, `battlefield`, `graveyard`, `exile`, `stack`, `command`, `limbo` (Arena `Pending`/`Limbo`/`Revealed`/unknown). |
| `amount` | Damage dealt, life delta (signed), counter delta (signed), cards looked at for scry, hand size for mulligan. |
| `source_card_id`, `target_card_id` | `cards.id` when cheaply known; optional, the builder prefers `arena_id` and names. |
| `payload_json` | Kind-specific JSON object (below). NULL when the kind needs nothing extra. |
| `text` | Printed line, or short machine text for silent rows. |

### Kinds and payloads

| `event_subtype` | Row kind | Fields used | `payload_json` |
| --- | --- | --- | --- |
| `turn` | printed (`event_type = turn`) | `turn_number`, `seat_id` = active seat | `{"active_seat": 1}` |
| `phase` | silent | `phase`, `step`, `turn_number` | — |
| `life` | printed (`life_gain`/`life_loss`) | `seat_id`, `amount` (signed), `player_life`, `opponent_life` | `{"source_object_id": 123}` when known |
| `mulligan` | silent | `seat_id`, `amount` = new hand size | `{"from_size": 7, "to_size": 6}` |
| `move` | printed (`draw`, `land`, `zone`) or silent | `object_id`, `arena_id`, `seat_id` = owner, `controller_seat`, `zone_from`, `zone_to` | `{"reason": "draw" \| "play_land" \| "cast" \| "resolve" \| "destroy" \| "exile" \| "sacrifice" \| "discard" \| "mill" \| "bounce" \| "counter" \| "sba" \| "put" \| "token_create" \| "token_cease" \| "shuffle_in" \| "unknown", "name": "Card Name", "type": "Creature", "token": true, "owner": 2, "with": 318, "by": 400, "chosen": "Mountain", "power": 0, "toughness": 2}` — `name` and `type` are included whenever known so the builder never needs a lookup; `power`/`toughness` on every row whose object is a creature (its current stats when the row was written, `0` kept: Arena encodes a zero stat as an empty object), so the stream's card entry gets printed stats from the first such row and never depends on the `cards` table (which only learns stats from console labels, and a 0-power creature never earned one); `owner` only on a printed row whose text names another seat (`[X] returned [Y] to opponent's hand`), since printed rows keep the text's seat; `with` only on a move into exile: the root id of the battlefield permanent whose ability (Arena's `affectorId`, an ability object whose `parentId` is its source) or static effect exiled the card, so the viewer can tuck it under that host (Deep-Cavern Bat, Pinnacle Starcage); absent when a spell or a source no longer on the battlefield did it; `by` on any move except draws, land plays, casts, resolutions and state-based deaths: the root id of the spell or of the ability's source permanent whose effect moved it (Arena's `affectorId`, an ability resolved to its `parentId`), omitted when Arena names none or the card moved itself (a cost it paid); `chosen` on a move onto the battlefield of a land that chose a basic land type as it entered (Multiversal Passage): Arena logs `AnnotationType_ChoiceResult` from the land with `Choice_Domain` 9 (basic land types) before the play, and the entering object's `subtypes` hold the type (`SubType_Mountain`); the console line ends `as a Mountain` |
| `tap` / `untap` | silent | `seat_id` = controller | `{"object_ids": [1, 2, 3]}` |
| `sick` / `unsick` | silent (`replay_version` 2+) | `seat_id` = controller | `{"object_ids": [1, 2]}` — Arena's `hasSummoningSickness` on a battlefield gameObject turned on / off (it is absent when false). Arena sets it only on creatures that can't attack or use {T} abilities yet, and already leaves it off for haste, printed or granted; it clears at the controller's next upkeep. Batched per message and seat like taps; leaving the battlefield forgets it without a row |
| `counter` | silent | `object_id`, `amount` (signed) | `{"type": "+1/+1", "total": 3}` |
| `pt` | silent | `object_id` | `{"power": 3, "toughness": 3}` — current printed-or-modified values |
| `attach` | silent | `object_id`, `target_object_id` (NULL = unattached) | — |
| `identity` | printed (`ability` "became") or silent | `object_id`, `arena_id` = new face | `{"name": "New Name", "type": "Creature", "power": 2, "toughness": 2, "face_down": false}` |
| `stack_push` | printed (`cast`, `stack`, `ability`) | `object_id` = spell/ability source, `arena_id`, `seat_id` = controller, `zone_from` = `hand`/`graveyard`/… for spells | `{"stack_id": "s17", "stack_kind": "spell" \| "trigger" \| "activated", "name": "...", "text": "ability text", "targets": [45, 46], "power": 2, "toughness": 2}` (`power`/`toughness` for a creature spell, as on `move`) |
| `stack_resolve` / `stack_fizzle` / `stack_countered` | printed (`stack_resolve`, `stack_fail`, `counter`) | — | `{"stack_id": "s17"}` |
| `attack` | printed (`attack`) | `seat_id` = attacking seat | `{"object_ids": [1, 2], "target_seat": 2}` (or `"target_object_id"` for a planeswalker/battle) |
| `block` | silent (also printed when the tracker prints blocks) | `seat_id` = blocking seat | `{"pairs": [{"blocker": 9, "attacker": 1}]}` |
| `damage` | printed (`combat_damage`, `damage`) | `object_id` = source, `target_object_id` or `seat_id` of the damaged player, `amount` | `{"combat": true, "target_seat": 2}` |
| `reveal` | silent | `object_id`, `arena_id`, `seat_id` = owner | `{"name": "...", "type": "..."}` |
| `scry` | printed (`scry`) | `seat_id`, `amount` = looked | `{"top": [ids], "bottom": [ids], "top_names": [], "bottom_names": []}` |
| `shuffle` | silent | `seat_id` | — |
| `game_end` | silent | `seat_id` = winner or NULL | `{"reason": "..."}` |
| `note` | printed | — | — |

Stack ids are per-game strings `s<n>` assigned by the capture code when an
item is pushed, so resolve/fizzle/counter rows can name the item even when
same-named spells are on the stack.

### Gating and lifecycle

- Rows are written only when the tracker already writes printed rows: known
  game start, not `_is_untracked_match()`. Mid-game attaches never persist.
- `games.replay_version` is set when the game's row is persisted at
  game end (`replay_capture.REPLAY_VERSION`: 1, then 2 once `sick`/`unsick`
  rows are captured). Older games keep NULL. Readers treat any non-NULL
  version as recorded.
- `_purge_ghost_game_breadcrumbs` deletes silent rows with the rest.
- Every capture hook is exception-safe (`replay_capture.replay_safe`): a
  failure drops that fact and logs one line per hook to the diagnostics text
  log; the console line and its printed row are unaffected. If a message's
  batch insert fails, printed rows are retried on their own (once for a lock
  or I/O error, row by row for a row-level error), so only the bad rows are
  lost.
- Cost: no extra parsing passes over the message; the mixin that already
  handles an annotation emits the row. Batch per message where natural.

## 2. Serving: `GET /api/replay?id=<game_id>`

Query-style id like `/api/game`. 400 without `id`, 404 for an unknown game,
404 with `{"error": "replay_unavailable", "reason": "..."}` for a game that
has no events. Served through `cached_response`.

Source selection: `games.replay_version IS NOT NULL` → **builder** from rows
(`fidelity: recorded`); otherwise rows exist → **reconstructor** from text
(`fidelity: reconstructed`, printed rows only). Both return the stream below.

### Availability on game rows

Every endpoint that returns game rows (`/api/game`, All Games, overview
recent games, deck page history, opponent page history, `/api/live` games)
adds:

```
"replay": {"state": "recorded" | "reconstructed" | "unavailable", "reason": null | "no events" | "mid-game attach" | ...}
```

Computed set-based (one grouped `EXISTS`/`LEFT JOIN`), never per row.
Game Detail `timeline` rows carry `id` (their `game_events.id`) so a row can
deep-link to the stream events with that `row_id`.

### Stream JSON

```
{
  "version": 1,
  "fidelity": "recorded" | "reconstructed",
  "replay_version": 1 | null,
  "limitations": ["..."],                 // human sentences; for recorded, only estimates (summoning sickness before version 2)
  "game": {
    "id": "...", "started_at": "ISO", "ended_at": "ISO|null", "format": "Standard Ranked",
    "best_of": 1 | 3, "game_number": 1, "outcome": "win"|"loss"|"draw"|"unknown",
    "outcome_reason": "...|null", "winner_seat": 1 | 2 | null,
    "total_turns": 12, "duration_seconds": 540
  },
  "player_seat": 1,                        // the local player's seat
  "seats": {
    "1": {"role": "player", "name": "You", "deck_name": "...", "starting_life": 20,
           "went_first": true, "commanders": ["Name"], "deck_size": 60, "colors": "WB"},
    "2": {"role": "opponent", ...}
  },
  "cards": {
    "<card_key>": {"name": "...", "arena_id": 12345 | null, "type_line": "Creature — Vampire" | null,
                   "primary_type": "Creature" | "Land" | ..., "power": "2" | null, "toughness": "2" | null,
                   "mana_cost": "{1}{B}" | null, "color_identity": "B" | null, "is_token": false,
                   "image_url": "https://cards.scryfall.io/normal/front/x/y/<id>.jpg" | null,
                   "faces": [{"name": "...", "type_line": "..."}],
                   "keywords": ["flashback"], "back_face": false,
                   "token_print": "ttdm/13" | null}
  },
  "turns": [{"turn": 1, "seat": 1, "first_seq": 0, "last_seq": 41, "started_at": "ISO|null",
             "duration_seconds": 32.0 | null}],
  "events": [ { "seq": 0, "t": 0.0, "turn": 1, "phase": "Phase_Main1" | null, "step": "Step_Upkeep" | null,
                "kind": "...", "log": {"text": "...", "segments": [...]} | null, ...kind fields } ]
}
```

- `keywords` and `back_face` come from Arena's local card DB
  (`CardDatabase.replay_card_facts`, by name, for recorded and reconstructed
  streams alike; `[]`/`false` without an Arena install). `keywords` lists only
  the replay-relevant ones, matched by Arena's language-independent ability
  base id: `flashback` (35), `escape` (199), `disturb` (215), `harmonize` (362)
  cast the card from its owner's graveyard; `plot` (328) casts it from exile
  after it was plotted from the hand; `cast_from_exile` and `cast_while_exiled`
  are not keyword abilities but the card's own English rules text
  (`card_database.CAST_FROM_EXILE_TEXT`): "You may cast this card from exile."
  (Eternal Scourge, Squee) lets it be cast from exile whatever put it there, and
  "Exile this card from your hand: ... You may cast this card for as long as it
  remains exiled." (Emrakul, the Exigent Doom's cycle) only once it exiled itself
  from the hand; `flying` (ability id 8, its own ability
  with BaseId 0) makes a creature hover on the battlefield; `haste` (ability
  id 9) only refines the summoning sickness estimate. A token's keywords
  come from its Arena id, since token names ("Bird", "Spirit") come with and
  without flying. `back_face` marks a double-faced card's
  back face (Cards.LinkedFaceType 1 transform, 9 modal): its `image_url` uses
  Scryfall's `/back/` path and the viewer adds `face=back` to its API lookups.
  Streams built before these fields existed omit them; readers default them.
- `card_key`: `"a<arena_id>"` when the Arena id is known, else
  `"n:<name>"`, else `"unknown"`. `image_url` is set only when the server can
  resolve a direct Scryfall CDN link without a network call (the collection
  exporter's `data/scryfall_id_cache.json` keyed `set|collector`, via the
  Arena card DB's set and collector number); otherwise the UI resolves it.
  Tokens never get `image_url`: Arena files a token under its card set's code
  with the token's own number (the Mobilize Warrior is TDM 13), which that cache
  resolves to the set's card 13 (Furious Forebear). Instead `token_print` is
  the token's Scryfall `set/number` (Scryfall numbers a set's tokens the same
  way under the code with a leading `t`: `ttdm/13`), and the viewer tries
  `api.scryfall.com/cards/<token_print>?format=image` first, caching the result
  under its own key so art cached before the field existed is not reused.
- Object ids `obj` are strings: the Arena root instance id for recorded
  games, `"r:<n>"` for reconstructed ones. A hidden object has `card: null`.
- `t` is elapsed seconds as a float, monotonic non-decreasing.
- `log.segments` uses the Game Detail timeline shape:
  `{"text": "..."}` or `{"card_name": "...", "card_type": "..."}`.

### Event kinds (stream)

| kind | fields |
| --- | --- |
| `game_start` | `seats_hand_sizes: {"1": 7, "2": 7}`, `library_sizes: {"1": 53, "2": 53}` |
| `turn` | `turn`, `active_seat` |
| `phase` | `phase`, `step` |
| `life` | `seat`, `life` (new total), `delta`, `source_obj: string|null` |
| `mulligan` | `seat`, `from_size`, `to_size`, `bottomed: [obj]` |
| `move` | `obj`, `card: card_key|null`, `from`, `to`, `owner`, `controller`, `reason`, `inferred: bool`, `index: int|null`, `with: obj|null` (exile only: the battlefield permanent that exiled it, recorded games), `by: obj|null` (what moved it, recorded games: the removal's source), `chosen: string|null` (onto the battlefield: the basic land type it chose, e.g. Multiversal Passage's `Mountain`; reconstructed games read it from the `as a Mountain` console suffix) (position within destination zone when known, used for library/stack order) |
| `tap` / `untap` | `objs: [obj]` |
| `sick` / `unsick` | `objs: [obj]` — summoning sickness began / ended (battlefield objects) |
| `counter` | `obj`, `type`, `delta`, `total` |
| `pt` | `obj`, `power`, `toughness` |
| `attach` | `obj`, `to: obj|null` |
| `identity` | `obj`, `card: card_key`, `face_down: bool` |
| `stack_push` | `stack_id`, `obj: obj|null` (source object), `card: card_key|null`, `stack_kind: spell|trigger|activated` (named `stack_kind` because `kind` is the event discriminator), `controller`, `text`, `targets: [obj]` |
| `stack_resolve` / `stack_fizzle` / `stack_countered` | `stack_id` |
| `attack` | `seat`, `objs: [obj]`, `target_seat: int|null`, `target_obj: obj|null` |
| `block` | `seat`, `pairs: [{"blocker": obj, "attacker": obj}]` |
| `damage` | `source: obj|null`, `target_obj: obj|null`, `target_seat: int|null`, `amount`, `combat: bool` |
| `reveal` | `obj`, `card` — only for an object already on the board (reveals of Arena's proxy objects nobody placed are dropped) |
| `scry` | `seat`, `top: [obj]`, `bottom: [obj]`, `looked: int` |
| `shuffle` | `seat` |
| `game_end` | `winner_seat: int|null`, `reason` |
| `note` | (only `log`) |
| every kind | optional `row_id: int\|null` — the `game_events.id` the event was derived from (several events can share one; `null` for synthesized setup/finish events) |

Rules the producers guarantee so the reducer can stay simple:

1. The first event is `game_start`; `move` events with `from: "library"`,
   `to: "hand"` and `reason: "draw"` for each opening-hand card follow it
   (hidden for the opponent). Library sizes already exclude those cards.
2. A `move` never references an object that does not exist yet unless `from`
   is `limbo` or `library`/`hand` with `card: null` (hidden objects are
   created on first reference). A `token_create` move has `from: "limbo"`.
   Recorded games: Arena can create tokens and declare them attackers in one
   message (Mobilize), and the printed attack rows are written before the
   silent creation rows, so the builder moves each `token_create` row ahead of
   the first row of the same turn that names its object. The viewer clears
   `inferred` on a `token_create` move (older streams introduced such tokens
   as inferred first).
3. A spell cast is `move hand→stack` **then** `stack_push`; resolution is
   `stack_resolve` **then** `move stack→battlefield|graveyard`. Countered:
   `stack_countered` then `move stack→graveyard|exile`. Triggers and
   activated abilities are `stack_push` with `obj` = source permanent and no
   move.
4. Life events carry the new total; the reducer never computes life from
   damage.
5. `turns` covers every `turn` event; `first_seq`/`last_seq` are inclusive.
   The builder places a turn's untap/tap/unsick/sick/phase/P/T/counter rows that were
   captured before its lazily printed header after the `turn` event.
6. Summoning sickness: `replay_version` 2+ streams carry the captured
   `sick`/`unsick` rows only. Older recorded games and reconstructed ones are
   estimated (`replay_sickness.estimate_summoning_sickness`, run before
   `build_turns`, `seq` renumbered): a non-inferred move onto the battlefield
   of a creature without printed `haste` (card facts keyword, Arena ability
   id 9) is followed by `sick`; `unsick` follows its controller's next `turn`
   event, or comes just before an `attack` that names it. Such a stream adds
   `SICKNESS_ESTIMATE_LIMITATION` to `limitations`.
7. Lost arrivals (recorded games): Arena logs a message with more than 50
   objects or annotations only as a summary ("Message summarized because
   ..."), so a card cast in one (Emrakul, the Exigent Doom cast from exile)
   turns up later under a new id that no row moved, first named by a row that
   needs it on the battlefield. Its Arena id is the one on the first row it is
   the source (`object_id`) of; objects with an `identity` row are left alone.
   When exactly one card with that Arena id sits in the same seat's exile (moved
   there with no `with` host) and no later row names it, the builder
   (`_reconnect_lost_arrivals`) renames the newcomer to it everywhere and puts
   a `move exile→battlefield`, `reason: "unknown"`, `inferred: true`, before its
   first row, followed by `sick` when the first sickness row for it is `sick`;
   the stream adds `LOST_ARRIVAL_LIMITATION` to `limitations`. Otherwise the
   newcomer is introduced from `limbo` as usual, but with that card rather
   than `card: null`. `inferred` may therefore be set on a move that is not
   from `limbo`.

## 3. Playback: `ui/src/replay/` module API

Pure modules first; React and three.js only in `components/`.

| Module | Exports |
| --- | --- |
| `types.ts` | `ReplayStream`, `ReplayEvent` (discriminated union on `kind`), `ReplayCard`, `ReplaySeat`, `ReplayTurn`, `ReplayAvailability`, zone and reason string unions. |
| `reducer.ts` | `BoardState { seats: Record<seat, SeatState>, stack: StackItem[], turn, activeSeat, phase, step, life: Record<seat, number>, attackers: Map<obj, obj|null> (attacker → the planeswalker or battle it attacks, null for a player; arrows aim at it), blocks: Map<obj, obj>, lastEvent: ReplayEvent|null }`; `SeatState { zones: Record<Zone, obj[]> (ordered), handSize, librarySize }`; `ObjectState { obj, card: card_key|null, owner, controller, zone, tapped, counters: Record<string, number>, power, toughness, attachedTo, faceDown, inferred, revealedAt, chosen?, sick? }` (`chosen`: the basic land type from its move onto the battlefield, kept while it stays there; `sick`: set by `sick`/`unsick` on a battlefield object, kept by a battlefield-to-battlefield move, gone once it leaves) kept in `objects: Map<obj, ObjectState>`; `createInitialState(stream)`, `applyEvent(state, event): BoardState` (returns a new top-level object; may share untouched substructures), `buildTimeline(stream): ReplayTimeline` (keyframe at every `turn` event), `stateAt(timeline, seq): BoardState` (nearest keyframe + replay, memoized for the last result). |
| `effects.ts` | The effect window: `BoardState.effects: EffectWindow { source, objects: Map<obj, ObjectMarks>, seats: Map<seat, SeatMarks>, held: Map<obj, HeldCard>, exits: StackExitMark[] }`, filled by `noteEffects(draft, event)` before each event applies and emptied by `clearsEffects(event)` (turn, phase, stack push, attack, block, game end, or a cast/land/draw move), so one action's effects stay shown until the next action at any playback speed. A `stack_resolve` makes that item the window's `source` (kept after it left the stack) and records its exit; `stack_countered` records the countered item with the item targeting it as its source; `stack_fizzle` records the fizzle. `ObjectMarks { damage, combat, removed: RemovalKind\|null, counters (non-loyalty deltas per type), pt (an effect's net P/T change), tapped, source }`: `damage` sums damage events (no source during combat counts as combat damage); a battlefield exit becomes `removed` (`destroyed`, `died` for an `sba`/`token_cease` creature or planeswalker, `exiled`, `returned`, `sacrificed`, `graveyard`, `library`) and is held as `HeldCard { object, seat, index }`; a return to the battlefield in the same window releases it; a hand discard is `discarded`. Sources: the event's own (`damage.source`, `life.source_obj`, `move.by`), where the window's item stands in for its own object; a death takes its damage's source; a sacrifice takes the window's item only when an opponent controls it (an edict, not a cost); everything else takes the window's item. P/T marks only come from a resolving item, never for an object entering or the item's own object, and counters replace them. `tap` marks only the resolving item's targets. `SeatMarks { life, damage, milled, combat, source }`. `shownExits(window)` lists the exits the preview keeps. |
| `layout.ts` | Table units: felt depth `TABLE_DEPTH` (6.4) fixed, rail `RAIL_WIDTH` (0.3) around it, width from `opts.tableWidth` (clamped to 7.2–22; it follows the stage aspect, see `scene/cameraFit.ts`), origin at table center, +y toward the opponent, z up. Per seat, Arena-style: creatures in front with non-creature planeswalkers to their right (after a gap, full size), a clear gap, then a back row of lands followed (after another gap) by other permanents; the hand on an apron just past the near rail (off the felt, overlapping the rail a little, floating above it) at `opts.handScale` (`HAND_SCALE_MIN` 1.0 to `HAND_SCALE_MAX` 1.7, chosen by the stage; `handY(scale)`, `apronDepth(scale)` for the apron the camera frames past each rail), a crowded hand overlapping to `HAND_MIN_VISIBLE` 55% visible, then shrinking to `HAND_SCALE_FLOOR` 0.6, then overlapping further, centered within the table width less 0.5 at each side; library/graveyard/exile (and command in commander formats, `usesCommandZone(stream)`) piles stacked in a lane on the left (opponent top-left, player bottom-left, mirrored opponents' piles turned but kept there). Rows center on the table, use the free span when wider, and overlap only on overflow (lands first). Auras/equipment tuck under their host, and so do cards a permanent exiled (`move.with`) while that host is on the battlefield; those leave the exile pile. The tucked cards fan upward on screen for both seats (toward the opponent's lands on their side), one title strip (`attachStep(count, attachRoom(opponent))`: 0.17 per card; the fan must stay inside the clear gap before the next row, 0.32 toward the opponent's lands or 0.48 toward the center for the player, so the host first slides up to 0.2 away from its fan and then the strips compress) and a 0.05 nudge to the viewer's right per card. A noncreature artifact or enchantment (row `other`) holding more than `TUCKED_FAN_MAX` (2) cards it exiled, and no auras or equipment, shows them as a pile instead (Pinnacle Starcage): `PILE_EDGES` (2) thin edges like a token stack, the rest squared up behind them, each one `stackedUnder` the host, and the host gets `CardPlacement.tuckedCount`, a teal-edged `N under` badge (label tone `tucked`) on its upper right corner; the hover preview lists them all. Creatures always fan. The in-scene stack is a small column at the right edge under the DOM stack preview, kept as the motion anchor. Side cards, Arena style: a seat's graveyard cards with a graveyard-cast keyword and its exile cards with `plot` or `cast_while_exiled` that came straight from the hand (`ObjectState.fromHand`), and its exile cards with `cast_from_exile` however they got there, sit just to the right of its hand (`row: 'castable'`, gap `SIDE_GAP` 0.35, each next one `SIDE_STEP` 0.6 of a card along), the hand and side cards centered together and the hand fitting into what is left; `CardPlacement.castable` is the keyword (`plot` for plotted, `cast_from_exile` for both exile-cast keywords), drawn with a dashed blue outline or a gold glow and a chip naming it (`Flashback`, `Plotted`, `From exile`, …, label tone `castable`). They still count on their pile, which shows the card under them. Framing is Arena style: the player's whole hand rises `HAND_FELT_OVERLAP` (0.3) onto the felt's empty strip below their lands (`handY(scale)`, `apronDepth(scale)`), floating above the tallest pile (`PILE_MAX_CARDS` 60 × `PILE_CARD_DEPTH` 0.004, + 0.02) so it covers the library beside it; the opponent's, drawn at `opts.opponentHandScale` (`OPPONENT_HAND_SCALE` 0.75 when omitted, larger on a tall high-resolution stage, see `cameraFit.fitTableForView`; `seatHandScale`), keeps the usual depth stretch and is placed for it: its stretched inner edge starts at `OPPONENT_HAND_INNER`, just past their land names as stretched (`FAR_ROW_STRETCH` 1.3), and the far framing covers it at `OPPONENT_HAND_STRETCH` (1.35, at least cameraFit `FAR_STRETCH`; `handY(scale, true)`, `opponentApronDepth(scale)`, `cameraFit.framedFarDepth`). The battlefield is about a fifth larger than when both hands sat wholly past the rails; the opponent's back-row fans rise under their hand. Identical tokens and lands (a land by name, whatever its printing; same card, controller, tapped state, stats, counters, combat role and current-action marks; not damaged, targeted, blocking, blocked, removed or carrying attachments) stack under the first of them (thin edges, `STACK_EDGE_DY`, spread capped at `STACK_MAX_SPREAD`, the top card never sliding), tapped ones apart from untapped ones: it gets `CardPlacement.stackCount` (shown as a `×N` chip in its lower left corner) and each one under it `stackedUnder` (drawn as an edge, no labels of its own). Labels sit in a card's upright frame: on a tapped card they stay above and below it within its sideways footprint rather than turning to its left and right edges. A battlefield object with `ObjectState.sick` (not held as removed) sets `CardPlacement.sick` and stacks apart from identical ready tokens. A face-up creature with flying (card `keywords`, or a `flying` counter; `hasFlying`) sets `CardPlacement.flying` and is raised `FLYING_LIFT` (0.25) above the felt, its tucked cards with it; the renderer casts its shadow further (down and to the right) with a tighter, darker texture. Effects (see `effects.ts`): every placement carries the current action's `marks` (`ObjectMarks` or null); a damaged battlefield card gets `highlight: 'damaged'`, `CardPlacement.damage`, and a red `damage` label (`−6`) that pops in. A permanent removed this action (`effects.held`) stays in its battlefield slot, as it last stood there (unattached), with `CardPlacement.removed` set, drawn dimmed under a chip; it is left out of every other zone (its pile shows the card under it, a bounced card is not yet drawn in the hand) until the action ends, then flies to where it went. A discarded card on top of its graveyard gets `removed: 'discarded'`. `Layout.seatMarks: SeatMarkPlacement[] { seat, marks: SeatMarks, x, y }` places each seat's life change at the middle of its rail. `layoutBoard(state, opts: { mirrorOpponent, hindsight, playerSeat, tableWidth?, handScale?, opponentHandScale?, commandZone? }): Layout { cards: CardPlacement[], piles: PilePlacement[], table: TableGeometry, seatMarks: SeatMarkPlacement[] }`; `CardPlacement { obj, card, faceUp, x, y, z, rotZ (90° when tapped), rotY (180° mid-flip handled by the renderer), scale, zone, seat, row: 'lands'|'creatures'|'planeswalkers'|'other'|'hand'|'castable'|'stack'|'pile'\|'creatures'\|'planeswalkers'\|'other'\|'hand'\|'stack'\|'pile', highlight: 'attacking'\|'blocking'\|'damaged'\|'targeted'\|null, inferred, counters, power, toughness, commander, under: UnderCard[] }` (`commander` marks a seat's commander, the card the seat info names, wherever it is: rules-wise it is an ordinary permanent and Arena keeps it in the creature row, so the layout only marks it; `under` is what is tucked under this host, `{ obj, card, zone }` bottom first, empty elsewhere; the hover preview lists it under the card image and pictures each distinct card beside it, `scene/hoverStore.ts` `underPictures`/`previewPosition`); `PilePlacement { seat, zone: 'library'\|'graveyard'\|'exile'\|'command', count, topCard: card_key\|null, x, y, scale, rotZ }`; `TableGeometry { width, depth, rowLeft, rowRight, stackX, handScale, opponentHandScale }`. Deterministic; same input gives identical output. |
| `scrub.ts` | `openingEndIndex(events)` / `openingEndSeq(stream)`: the first turn header, where playback begins (the opening deal and mulligans before it are applied, never shown; `PlaybackClock` clamps to it, `firstSeq`/`startSeq`); `initialSeq(stream, at, row)` for deep links; `scrubSegments(stream)`: one segment per turn over that navigable range. |
| `scene/cameraFit.ts` | Frames the felt, its rails and both hand aprons (`framedHalfDepth(depth, handScale)`), plus `farAllowance(handScale)` beyond the far apron in the table preset for the stretched far hand (`framedExtent(table, u)`). The fit projects the framed region's corners at the felt and at the hands' floating height (`layout.HAND_Z`), since a raised hand projects further up the screen. `fitTableForView(view, margins, preset, depth?, pixelRatio?): { width, handScale, opponentHandScale }`: the widest felt at which the framed depth (smallest hands) still binds at the 30° tilt, so the table fills the stage height and extra width (a collapsed panel) becomes free felt; a stage too narrow for the minimum felt binds on the width, and the hands grow into the spare height (`HAND_SCALE_STEP` 0.05 steps). The opponent's hand starts from `opponentHandBase(stage height × devicePixelRatio)`: `OPPONENT_HAND_SCALE` 0.75 up to `OPPONENT_HAND_SMALL_STAGE_PX` (1200 device px, a 1080p/1440p monitor at 100%), rising in 0.05 steps to `OPPONENT_HAND_SCALE_LARGE` 1.0 at `OPPONENT_HAND_LARGE_STAGE_PX` (1800, a tall Retina/5K stage), and grows with the player's hand on a narrow stage (`opponentHandScaleFor`); the far apron (`framedFarDepth(depth, opponentHandScale)`) frames it. `tableWidthForView(view, margins, preset, depth?, handScale?, opponentHandScale?)` is the width half of that; `fitPerspective`/`fitOrthographic(view, margins, table)`. |
| `scene/motion.ts`, `scene/motionRegistry.ts` | Card motion (damped poses, flight arcs, spawn points). `depthStretch(viewer, x, y, z)`: the camera's foreshortening of the table plane at a point (view ray length over its drop; 1 straight down, capped at `MAX_STRETCH` 2.5). `MotionRegistry.setViewer(cameraPosition)` scales every mesh along world y by it (`stretchedScale`, exact at right angles, so a tapped card stretches along its width) so cards project in true proportion from the tilted camera; `stretchOf(obj)` lets stat labels follow the stretched edge. Under the orthographic top-down camera the viewer is null and nothing is stretched. `fixedStep`/`tick()` let a video export drive one fixed step per frame while R3F's own invalidations advance nothing. |
| `export/videoPlan.ts` | `buildVideoPlan(events, { speed, pacing, fps?, fromIndex?, toIndex?, tailSeconds? }): VideoPlan { fps, frames: Int32Array (event index per frame), seconds, fromIndex, toIndex, truncated }` — each event holds for `player.holdMs` at the chosen speed (the video plays like the viewer), the last frame for `EXPORT_TAIL_SECONDS`, capped at `MAX_EXPORT_FRAMES` (20 min at 30 fps); `exportFileName(stream)`. Pure. |
| `export/frameComposer.ts` | `frameLayout(sceneWidth, sceneHeight, targetWidth)`: video size (even, at most 3× the stage) with a HUD band above and a caption band below the table; `composeFrame(ctx, layout, input)` paints the rendered table plus the overlays redrawn in Canvas 2D (pile/stat/loyalty/counters badges, the stack column with card art via `stackRects`, arrows via `arrows.arrowShape`, the ending screen) and, with `frameLayout(..., log = true)`, the actions log as a `LOG_PX` (340 CSS px) column at the right in the site's row style (turn headers, actor bars, card names in gold, wrapped text, the current row highlighted at 58% height) in place of the caption band; `FrameInput` carries everything in stage CSS px. Pure drawing. |
| `export/mp4Encoder.ts` | `supportsVideoExport()` (WebCodecs present); `createMp4Encoder({ width, height, fps, quality? })` picks H.264 (High/Main/Baseline) or VP9 via `VideoEncoder.isConfigSupported`, hardware encoder first, at `bitrateFor(width, height, fps, quality)` (`small` 0.02 / `balanced` 0.04 / `best` 0.09 bits per pixel per frame, capped at 2.5 / 5 / 12 Mbps; `estimateBytes` for the dialog), muxes with mp4-muxer (fast start, in memory), `addFrame(canvas, index)` with bounded queue, `finish(): Blob`, `cancel()`. |
| `components/ExportDriver.tsx`, `components/VideoExport.tsx` | Inside the R3F canvas, `ExportDriver` runs a job: waits for card art (`TextureStore.request`, 30 s cap), then per frame steps the clock with `flushSync` (one event at a time, so cards animate), `registry.tick()` + R3F `advance()` with a priority-1 `useFrame` that renders and composes, encodes, reports progress, and restores the clock. A hold frame with nothing in motion (same event, registry idle) re-encodes the last composed canvas without rendering. `useVideoExport(stream, clock, index)` is the state machine (idle/dialog/running/done/error) and `VideoExportPanel` the dialog, progress and download UI. |
| `scene/arrows.ts`, `scene/stackView.ts` | `sceneArrows(state, layout)`: stack item → each target (a permanent, or a spell on the stack for counterspells), the current action's effects from their sources (`effect:<obj>` to a permanent it damaged, removed, changed, tapped or made its owner discard; `effect-seat:<seat>` to a player who lost life; `countered:<stack_id>` from the counterspell; a source is drawn from its permanent when placed, else from its stack-preview card, live or kept; combat damage and the deaths it causes are left to the attack/block arrows; a sacrifice paid as a cost has no source), attackers → the planeswalker or battle they attack (`BoardState.attackers` value; tone `strike`, full brightness), else the defending player (tone `attack`, dim), blockers → attacker (dim); an effect on the acting seat's own permanent is tone `support` (dim), on another seat's `target`, harm `damage`; colored by the acting seat's sleeve (`neonColors(SLEEVE_COLORS[id].accent)`); quadratic Bézier helpers (`arrowControlPoint`, `arrowShape`). `stackView(state)`: stack items top first for the DOM preview, identical abilities next to each other (same kind, card, text and controller, no targets, not targeted) grouped into one item (`groupStack`: `count`, `stackIds`; drawn as one card with a `×N` badge and edges behind it); `foldResolved(items, exits)` folds a just-resolved copy into its still-waiting group (`resolved`, its stack id added so its effect arrows start there), on the page and in the video export; `stackExit` tells resolved/countered/fizzled apart; `effectExits(state)`: the items kept in the preview for the current action (`effects.shownExits`: countered, fizzled, or resolved with an effect on the table, at most two), drawn static and dimmed under their stamp, beside the stack while it is not empty, and registered as arrow sources; the video export draws them stamped below the live stack. `scene/labels.ts`: `sceneLabels(layout, cards)` builds the DOM labels: pile counts, and for every face-up battlefield card a `stat` badge across its lower edge (current power/toughness, `emphasis` when it differs from the printed card) or a `loyalty` badge (the `loyalty` counter total; recorded games only, a planeswalker without one gets no badge), plus a `counters` chip across its upper edge for the other counters, or a `commander` chip ("Commander", then its counters) on a seat's commander, led by a land's chosen basic land type (`CardPlacement.chosen`), alone in its mana color (`land-plains`, `land-island`, `land-swamp`, `land-mountain`, `land-forest`); a command-zone pile keeps its "Command" label and slot while empty, so the viewer sees the commander is out; a `sick` sleep badge (`SICK_BADGE` "Zzz", purple) centered just above the top edge of a `CardPlacement.sick` card, clear of its name, drawn by the video export too, and the hover preview adds `HoverInfo.note` (`SICK_NOTE`). Effect labels (the current action, see `effects.ts`): a `removed` chip on a held or discarded card (`REMOVAL_LABELS`: Destroyed, Died, Exiled, Returned to hand, Sacrificed, To graveyard, To library, Discarded), a `buff`/`debuff` change above the art (`changeLabel`: `+2/+2`/`−1/−1` from counters, other counters as `+1 shield`, else an effect's `+3/+0`), an `effect` chip for `Tapped` and `Milled N` (over the graveyard), and the seat number at each rail (`seatNumber`: the net life change, else the damage taken; `life-loss` red `−3`, `life-gain` green `+3`), which the HUD also shows beside the life total. |
| `player.ts` | `class PlaybackClock { constructor(timeline, opts: { now?: () => number, schedule?: (cb, ms) => cancel }) ; subscribe(fn); get seq; play(); pause(); toggle(); setSpeed(0.5\|1\|2\|4\|8); setPacing('paced'\|'realtime'); step(+1\|-1); seek(seq); seekTurn(turn); nextTurn(); prevTurn(); dispose() }`. Paced mode: hold = max(600 ms, min(2500 ms, gap × 250 ms)) / speed. Real time: gap × 1000 / speed. |
| `images.ts` | `cardImageCandidates(card: ReplayCard, size: 'normal'\|'large'): string[]`; `ImageQueue` with `load(url, priority): Promise<string>`, max 6 in flight, token bucket 8/s (burst 1, so no one-second window exceeds 8) for `api.scryfall.com`, one bucket shared by every page's queue; hover previews resolve through the same queue, no limit for `cards.scryfall.io`; `resolvedImageCache` in localStorage key `mtga-replay-images-v1` mapping card key → final URL; an exact token printing (`token_print`) before the Arena-id lookup; `tokenSearchCandidates(card, size)` for tokens (`is_token`): two `api.scryfall.com/cards/search` URLs (`t:token !"Name" pow= tou= c=` then the name alone, `-is:dfc`, newest printing first; the size rides in the URL fragment) whose JSON names the CDN image, so Arena tokens get their printed token art while the procedural face stands in; `ImageLookupError.permanent` — the queue caches only 404/400/422 failures, a 429/5xx/network error is retried on the next request; `generatedTokenFace(card)` for cards without any image. |
| `prefs.ts` | `FELT_COLORS` (`green` default, `blue`, `burgundy`, `charcoal`, `camel`, `purple`), `SLEEVE_COLORS` (`navy` default for the player, `crimson` default for the opponent, plus `forest`, `charcoal`, `violet`, `gold`), `ReplayPrefs { felt, playerSleeve, opponentSleeve, camera: 'table'\|'topdown', mirrorOpponent, hindsight, pacing, speed, logCollapsed }`, `loadPrefs()`, `savePrefs(p)`, `subscribePrefs(fn)`; localStorage key `mtga-replay-prefs`, every access in try/catch. |
| `materials.ts` | `createFeltCanvas(color)`, `createSleeveCanvas(color)`, `createTokenFaceCanvas(card)` returning `HTMLCanvasElement` (procedural, no bundled images); guarded so importing under jsdom does not throw. |
| `routes.ts` (app) | `parseReplayRoute(hash)`: `#/replay` → `{ gameId: null }`, `#/replay/<id>?at=<seq>&row=<game_events.id>&return=<hash>` → `{ gameId, at, row, returnHash }`; `replayRouteHash(gameId?, { at?, row?, returnHash? })`. `row` (Game Detail timeline deep links) opens at the first event whose `row_id` matches; `at` wins when both are present; an unknown row opens at the start. |
| `api.ts` (app) | `fetchReplay(gameId): Promise<ReplayStream>`; `ReplayAvailability` on game row types. |

### Rendering and performance requirements

- `@react-three/fiber` `Canvas` with `frameloop="demand"`; `invalidate()` on
  state change and during animations only. Default camera preset is
  `table` (30° tilt, 24° field of view); the stage is measured with a
  `ResizeObserver` and the felt's width follows its aspect, so the table
  fills the stage height. At 1440×900 a creature in your front row is about
  80 px wide with the Actions panel open and about 91 px with it (or the
  sidebar) collapsed. `topdown` is orthographic.
- DOM overlays over the canvas, positioned without React on rendered
  frames: pile and stat labels, an SVG layer of targeting arrows (curved,
  glowing in the acting seat's sleeve color, animated dash flow while the
  item is on the stack; combat arrows dimmer), and the stack preview — large
  card images in a column at the right edge, top of the stack first, the
  newest sliding in and leaving items stamped Resolved/Countered/Fizzled.
  Only the preview's cards take pointer events. The Actions panel collapses
  to a slim rail (the sidebar's « » control; `logCollapsed` pref).
- One mesh per visible object keyed by `obj`; textures from a shared cache
  (`THREE.TextureLoader`, `colorSpace = SRGBColorSpace`, anisotropy from the
  renderer's max), disposed on page unmount. Hidden objects share one sleeve
  texture per seat.
- Movement animates by lerping toward the layout target in `useFrame`;
  React state never updates per frame. Target 60 fps with 60 cards on an
  integrated GPU; seek under 16 ms for a 2,000-event game (measured in the
  built page, 500 random scrub seeks on a 439-event game: about 1.5–2 ms
  average, p95 about 4 ms).
- The action log renders memoized rows; only the active row re-renders on
  tick; auto-scroll uses `scrollIntoView({ block: 'nearest' })`.
- Minimum width 900 px: entry points carry the `replay-wide-only` class
  (hidden below 900 px) and the replay page shows a notice instead of the
  canvas below that width.
- Teal token `--replay` (dark `#2bb3a3`, light `#0f8f82`) is used only for
  replay affordances.

## 4. Reconstruction from text (older games)

Input: the game's `game_events` rows ordered by `event_time, id`,
`game_opening_hand_cards`, `game_mulligan_hands`, `game_drawn_cards`,
`game_deck_cards`, `game_turns`, `participants`, `participant_commanders`,
`cards`. Output: the same stream with `fidelity: reconstructed`, synthetic
`r:<n>` object ids, and `limitations` listing at least: blocks, taps,
counters, tokens entering, opponent hand contents, instants and sorceries
reaching the graveyard are inferred, same-named copies indistinguishable,
and (when any creature entered) estimated summoning sickness (§2 rule 6).

Grammar (regular because the tracker generated the text; `[Name (Type P/T)]`
brackets are the anchor):

| `event_type` | Text shape | Stream events |
| --- | --- | --- |
| `turn` | `Turn N - YOUR TURN` / `OPPONENT'S TURN` | `turn` |
| `land` | `You: played [X (Land)]` | `move hand→battlefield play_land` |
| `cast` | `You: cast [X (Type)]` (optional `-> [Target]`, `(on stack)`) | `move hand→stack cast`, `stack_push spell` |
| `draw` | `drew [X]` / `drew a card` | `move library→hand draw` (hidden when unnamed) |
| `stack_resolve` | `Stack: [X ...] [resolved]` | `stack_resolve`, then `move stack→battlefield` for permanents or `stack→graveyard` for instants/sorceries (type from the bracket suffix, else `cards.primary_type`); triggers/abilities resolve with no move |
| `stack_fail` | `[left stack without resolving - inferred]` | `stack_fizzle`, `move stack→graveyard` for spells |
| `counter` | `[X] was countered` | `stack_countered`, `move stack→graveyard` |
| `ability` / `stack` | `[X] - text` / `(triggered, on stack)` | `stack_push trigger` (resolved by the next matching `stack_resolve`); `[A] became [B]` → `identity` |
| `zone` | `was destroyed/exiled/sacrificed/discarded`, `was put into graveyard (lethal damage)`, `milled [X]`, `returned [X] to hand`, `put [X] onto battlefield`, `put [X] into … hand`, `sacrificed as cost` | `move` with the matching reason; source zone from current tracking (battlefield first, then stack, hand, graveyard) |
| `attack` | `You attacking [opponent] with [X (P/T)]` | `attack` (+ `pt` from the bracket) |
| `combat_damage` / `damage` | `dealt N damage to [Y]`, `[X] (your) took N damage` | `damage` |
| `life_gain` / `life_loss` | any | `life` from the row's life columns |
| `scry` | `scried N — …` | `scry` (names resolved to objects when in the player's library) |
| other | — | `note` |

Seeding: player's library = submitted maindeck (`game_deck_cards`,
`deck_zone = 'deck'`) minus the kept hand, else `deck_size − 7` hidden
objects; opening hand from `game_opening_hand_cards`; mulligans from
`game_mulligan_hands`; opponent: 7 hidden hand objects, `deck_size` (or 60 /
100 for Brawl) hidden library objects. Opponent hand size never goes below 0.
Card facts (`rows["card_facts"]`, see §2 `keywords`): a `cast` of a card
with a graveyard-cast keyword comes from that seat's graveyard, and one with
`plot` from its exile, before the hidden hand (a copy known to be in the hand
still wins); `[X] was exiled` for a plot card with no tracked object leaves
the hand. `put [B] onto battlefield` where `B` is a transforming card's back
face (fact `front`) is the front-face object (exile, stack, graveyard,
battlefield, then hand): `identity` to `B`, then `move →battlefield put`, not
inferred and never a token (Esper Origins → Summon: Esper Maduin).
A name in the card facts is a real card for either seat (never an inferred
token), and its `type_line`, `power` and `toughness` fill in cards the rows
never described. `returned [X] to battlefield` (optionally `[Source] …`) is a
`move →battlefield put`, not inferred; before the tracker printed it, the same
recursion read `returned [X] to hand`, so that line is a return to the
battlefield when an ability on the stack this turn targets X with text
containing "return … to the battlefield". An ability whose text has a sentence
starting `Create <n> [P/T] <words> token(s)` (no "for each"/"equal to")
creates that many tokens on resolution (`grammar.created_tokens`). Damage
lines with the same printed timestamp hit distinct same-named permanents.
Tokens: on first mention, `move limbo→battlefield token_create` with
`inferred: true` immediately before the referencing event. `Card #N` →
hidden object named "Unknown card".

## 5. Where replay links appear

Sidebar tile above Deck Finder (`#/replay`), the Replay list page, Game
Detail header button, row icons on Recent Games / All Games / deck and
opponent histories / Live "Today's Games", the Live previous-game chip and
ended-game banner, the console `Replay: <url>` line after persistence, and
menu-bar items. All hidden below 900 px.
