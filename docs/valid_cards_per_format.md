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
`restricted` (plus Arena `suspended` cards show as `banned`).

**Delivery: Scryfall's bulk file, not per-card fetches.** Checked live against
[the bulk-data endpoint](https://scryfall.com/docs/api/bulk-data): Scryfall now
publishes **JSONL** variants of every bulk file, which removes the old memory
objection — the file is one card per line, so ingest streams it through
stdlib `gzip` + `json.loads` line-by-line with constant memory, never holding
a giant array. Current real sizes (gzipped): `oracle_cards` **24.5 MB**,
`default_cards` **77.5 MB**, refreshed daily, served from `data.scryfall.io`
(one new host beside `api.scryfall.com`; both matter for anyone running
behind an allowlist).

**We take `default_cards`**, not the smaller oracle file, for one reason: it
carries **per-printing `arena_id`s**, which is exactly the
arena-id → (name, set, collector number) index the 0.5.9 collection export
needs. One downloaded file feeds both features — the exporter plan's
"extend card_database + per-card Scryfall fallback" section collapses into
"read the shared bulk index". Legalities are oracle-level, so any printing's
row answers the legality question; ~77 MB once every few weeks, and Scryfall
explicitly *prefers* bulk downloads over API hammering.

## Storage

One ingest pass over the JSONL stream writes two things, then deletes the
downloaded file:

- **`cards.legalities`** (new TEXT column via `ensure_table_column`) — the raw
  Scryfall legalities JSON for every name present in the tracker's `cards`
  table, stored verbatim so a future format key needs no schema change. Plus
  `cards.legalities_checked_at`.
- **`arena_cards` (new table)** — `arena_id INTEGER PRIMARY KEY, name TEXT,
  set_code TEXT, collector_number TEXT, legalities TEXT` for every entry with
  an `arena_id` (tens of thousands of rows, a few MB): the collection
  exporter's whole metadata problem, and a legality answer even for cards the
  tracker has never seen played.
- **`meta` (new key/value table)** — the bulk file's bookkeeping:
  `scryfall_bulk_type`, `scryfall_bulk_updated_at` (Scryfall's stamp),
  `scryfall_bulk_ingested_at`, `scryfall_bulk_size`. (The DB rather than
  `settings.json` because this is cache state, not a user preference — but
  it surfaces on the Settings page either way, see below.)

## Download & refresh

A background thread at tracker startup (same family as
`_backfill_card_colors`):

1. Hit `api.scryfall.com/bulk-data` (a ~2 KB endpoint) at most once a day.
   If Scryfall's `updated_at` for `default_cards` is newer than our
   `scryfall_bulk_updated_at` **and** our copy is older than **14 days** —
   ban announcements land roughly monthly — download the `.jsonl.gz` to a
   temp file, stream-ingest, swap, delete. First run (no copy at all)
   downloads immediately.
2. **Settings page**: a "Card Data" line in the tracker-info block —
   *"Scryfall card data: updated Aug 24, downloaded Aug 25 (77 MB)"* — with a
   **Force Refresh** button (`POST /api/settings/refresh-card-data`) that
   re-runs the download-and-ingest as a background job with the same
   spinner/status treatment as the collection export, ignoring the 14-day
   window. That's the lever for "a ban just dropped, update now."
3. Failures (offline, partial download, malformed line) leave the previous
   ingest untouched — the temp file is discarded and the meta stamps keep
   their old values; individual bad lines are skipped, not fatal.
4. **Alchemy rebalances**: `A-Name` entries do appear in `default_cards`
   (they're real Arena objects in Scryfall's data); where one is missing,
   fall back to the base name's legalities with the `A-` override — the `A-`
   version is by definition an Alchemy/Historic card, so `standard` and
   `timeless` are forced to `not_legal`.

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
- **Alchemy-rebalance inheritance is approximate** where an `A-` entry is
  missing from the bulk file (base-card legalities plus the `A-` override).
- **Disk/bandwidth**: ~77 MB download every couple of weeks, a few MB of new
  SQLite rows; the downloaded file itself is deleted after ingest.

## Tests

- Mapper: every tracker family → expected key, event-raw probing, fail-open
  families.
- `_card_opponent_playable` with a seeded legality JSON: banned-in-Standard
  card across Standard + Timeless games (the Vivi scenario: colors match in
  both, only Timeless counts), `played_it` overriding a ban, NULL legalities
  filtering nothing, and `games_excluded_illegal` arithmetic.
- Ingest: a fixture `.jsonl.gz` (a dozen hand-picked lines incl. an `A-`
  card, a split card, an entry with no `arena_id`, and one malformed line)
  through the streaming parser → `cards.legalities`, `arena_cards`, and
  `meta` all land; the 14-day window and Force Refresh bypass with the
  bulk-data endpoint stubbed; a failed download leaves the previous ingest
  untouched.

## Effort

Medium-small: the download-and-ingest job (~120 lines: bulk-data check,
gz stream, line parser, three writes, meta stamps), one pure mapping
function, a 3-line query join plus the per-game check, one payload field,
the Settings "Card Data" line + Force Refresh endpoint, and tests. No new
dependencies; one new host (`data.scryfall.io`). The same ingest deletes a
chunk of the collection-export plan's work — `arena_cards` **is** its
metadata index — so 0.5.9 ships both features off one download.
