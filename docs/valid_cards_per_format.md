# Format Legality — Plan (`valid_cards_per_format.md`)

Teach the tracker which cards are legal in which Arena formats, and use it to
tighten **"Opponent Could Have Played It"**: a card banned in Standard should
not count your 500 Standard games as "possible" just because the opponent had
the colors — only the 50 Timeless games where the card is actually legal.

**Feasibility: yes.** Verified live against the motivating example — Scryfall's
per-card `legalities` object covers Arena's formats, and Vivi Ornitier returns
exactly the situation described:

```json
{"standard": "banned", "timeless": "legal", "standardbrawl": "legal",
 "gladiator": "legal", "alchemy": "not_legal", "historic": "not_legal", "brawl": "not_legal"}
```

## Data source

**Scryfall is the only viable source.** Arena's local `Raw_CardDatabase` has no
banlist or legality tables — it describes cards, not formats. Scryfall's
`legalities` map includes every Arena format under stable keys (`standard`,
`alchemy`, `historic`, `timeless`, `brawl` = Historic Brawl, `standardbrawl`,
`gladiator`, `explorer`) with four statuses: `legal`, `not_legal`, `banned`,
`restricted` (plus Arena `suspended` cards show as `banned`). We already fetch
from Scryfall per-card over `urllib` in `card_database.py`, so no new
dependency and no new host beyond the already-allowlisted `api.scryfall.com`.

Bulk download (~150 MB oracle file) is rejected: the tracker only ever needs
legality for cards that actually appear in tracked games — a few thousand at
most — so incremental per-card fetches with caching fit the project's
footprint far better.

## Storage

Two new columns on the existing `cards` table (via the `ensure_table_column`
pattern, no migration needed):

- `legalities` TEXT — the raw Scryfall legalities JSON, stored verbatim so a
  future format (or key rename) needs no schema change.
- `legalities_checked_at` TEXT — when it was last fetched, driving refresh.

## Backfill & refresh

A background thread in the tracker's startup backfill family (next to
`_backfill_card_colors`), rate-limited to Scryfall's ~10 req/s guidance:

1. Select cards appearing in `game_card_summary` or `game_deck_cards` where
   `legalities IS NULL` — first run fetches the full recorded pool once
   (a few minutes in the background), later runs only touch new cards.
2. Refresh cards whose `legalities_checked_at` is older than **21 days** —
   ban announcements land roughly monthly, so stale data self-heals within
   a announcement cycle. (A future "refresh legalities now" button on the
   Settings page is trivial once the column exists.)
3. Name matching reuses the existing Scryfall lookup path: exact first, the
   `" // "` front face for split/room cards, fuzzy as a last resort. Cards
   Scryfall doesn't know (brand-new set lag) simply stay NULL.
4. **Alchemy rebalances**: `A-Name` cards are Arena-only and absent from
   Scryfall's named lookup. Strip the `A-` prefix for the fetch, then
   override: the `A-` version is by definition an Alchemy/Historic card —
   mark `standard`/`timeless` as `not_legal` and inherit the rest. (Same
   normalization the exporter plan already does for names.)

All failures are silent-and-NULL: a card with unknown legality is treated as
"don't filter", never as "banned".

## Mapping tracker formats → legality keys

`format_normalizer.normalize_match_format(raw).family` already classifies
every recorded queue. One small pure function maps family → Scryfall key:

| Tracker family | Scryfall key |
| --- | --- |
| `standard` | `standard` |
| `alchemy` | `alchemy` |
| `historic` | `historic` |
| `timeless` | `timeless` |
| `explorer` | `explorer` |
| `brawl`, `historic_brawl` | `brawl` |
| `standard_brawl` | `standardbrawl` |
| `draft`, `sealed` | **none — never filter** (any card can be opened in Limited) |
| `event` | probe the raw queue string for a format token — `QualifierPlayIn_Bo1_Timeless_…` contains `timeless`; no token → no filter |
| `direct_challenge`, `midweek_magic`, `unknown`, everything else | **none — never filter** (fail open) |

The `event` probe matters in practice: Travis's own Timeless games are
recorded as `QualifierPlayIn_Bo1_Timeless_20260822`, which classifies as
family `event` — without the probe those games would just fail open (harmless
but loose); with it they filter correctly as Timeless.

## The query change

`_card_opponent_playable` already receives each game via `games g` — add
`JOIN matches m ON m.id = g.match_id` and pull `m.format`. Per game:

```
counts as possible ⇔ played_it
                     OR (castable_by_colors AND legal_in_that_game's_format)
```

where `legal_in_that_game's_format` is: no legality data, or no mappable
format, or status == `legal`/`restricted` → True; `banned`/`not_legal` →
False. **`played_it` deliberately overrides legality** — if the opponent
actually cast it, that's ground truth (and it quietly self-corrects the
historical-ban problem: pre-ban Standard games where the card really was
played still count).

The legality map for the card is loaded once per request (one small JSON
parse), and the family classification per distinct raw format string is
memoized — the loop stays O(games).

### Payload & UI

- Add `games_excluded_illegal` to the `opponent_playable` payload.
- Card page note line when it's > 0: *"N games excluded — this card isn't
  legal in that game's format."* — sits under the existing description, so
  Vivi's page reads "Games Possible: 50" with "500 excluded" context instead
  of a silently smaller number.
- Optional cheap win while legality is in hand: a "Legal in" chip row on the
  card page header (Standard ✕ · Timeless ✓ · Brawl ✓ …). Listed as a
  stretch item, not required for the fix.

## Known limitations (stated, accepted)

- **Current legality, not historical.** Scryfall reports today's banlist; a
  game played before a ban is judged by post-ban rules. Partially offset by
  the `played_it` override; fully correct historical banlists would need a
  dated banlist archive and are out of scope.
- **Scryfall lag on brand-new sets** — unknown cards fail open until the
  next refresh picks them up.
- **Alchemy-rebalance inheritance is approximate** (base-card legalities plus
  the `A-` override) — Scryfall has no first-class record for `A-` cards.

## Tests

- Mapper: every tracker family → expected key, event-raw probing, fail-open
  families.
- `_card_opponent_playable` with a seeded legality JSON: banned-in-Standard
  card across Standard + Timeless games (the Vivi scenario: colors match in
  both, only Timeless counts), `played_it` overriding a ban, NULL legalities
  filtering nothing, and `games_excluded_illegal` arithmetic.
- Backfill: `A-` prefix handling and the 21-day refresh window, with the
  Scryfall client stubbed.

## Effort

Small-to-medium: ~40 lines of backfill (mirroring `_backfill_card_colors`),
one pure mapping function, a 3-line query join plus the per-game check, one
payload field, one UI note line, and tests. No new dependencies, no new
hosts, no schema migration. Fits naturally in **0.5.9** alongside the
collection export.
