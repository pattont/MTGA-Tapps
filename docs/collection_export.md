# Collection Export — Plan

Add "Export MTGA Collection" to the Settings page (above Database Health):
two buttons — **Export to .json** and **Export to .txt** — producing files
importable into Moxfield and similar sites. The extraction technique is
adapted from NthPhantom10's
[MTGA-collection-exporter](https://github.com/NthPhantom10/MTGA-collection-exporter),
credited in the UI.

## Why this is hard: Arena no longer logs your collection

Verified against a current Player.log (Aug 2026): the log carries deck
lists, inventory currencies (`InventoryInfo`: gems, gold, wildcards), and
GRE game state — but **not** the card collection. The old
`PlayerInventory.GetPlayerCardsV3` map is gone. There is no file on disk
and no sanctioned API that lists what you own.

That leaves reading the collection out of the **running game's process
memory** — which is exactly what NthPhantom10's tool does, and why any
integration inherits its constraints: Arena must be running with the
collection loaded (open the Decks tab once), macOS requires elevated
rights to attach to another process, and a client update can silently
change the memory layout. This is unofficial territory: it never modifies
the game, but antivirus software on Windows sometimes flags process-memory
readers, and it can break without warning after Arena patches.

## Review of mtg.py (v3.4, 1578 lines)

### How it works

1. **Card database** — downloads Scryfall's bulk `default_cards` (with
   ETag caching, 7-day refresh) or parses Arena's local
   `Raw_CardDatabase_*.mtga` SQLite, building `arena_id -> (name, set,
   collector number, rarity, oracle text)`.
2. **Anchors** — interactively asks for 3–10 cards the user owns with
   exact quantities. Each anchor becomes a little-endian byte pattern
   `<arena_id, qty>` to locate the collection in memory.
3. **Memory scan** — attaches to the MTGA process (`pymem` on Windows, a
   hand-rolled Mach VM reader on macOS), pattern-scans readable regions
   for anchor hits, then reads ±4 MB around each hit and walks it at word
   strides 2/3/4 extracting runs of `(plausible arena id, plausible
   quantity)` pairs into candidate blocks.
4. **Scoring & validation** — candidate blocks are scored on known-id
   ratio, exact anchor matches, size, and duplicate-id penalty; the winner
   must pass sanity checks (≥30 % known ids, total quantity ≤ 500 k, low
   duplicates). Anchor quantities are forced back to the user's stated
   values.
5. **Export** — aggregates by (name, set), normalizes Alchemy `A-`
   prefixes, merges blank-set duplicates, and writes JSON, txt, and four
   CSV dialects (Deckbox, MTGGoldfish, Cardsphere, Moxfield) plus a stats
   summary.

### What's genuinely good

- The **anchor idea** is the heart of it and it's clever: user-known
  `(id, qty)` pairs turn an intractable "find a dict in 6 GB of heap"
  problem into a targeted pattern search with built-in ground truth for
  validating what it found.
- The heuristic layers are thoughtful: multiple word strides (Arena has
  changed its container layout across versions), gap tolerance, duplicate
  tracking used as a dirty-block signal (the v3.4 changelog shows real
  lessons learned), and a scoring function that prefers zero-duplicate
  blocks before anything else.
- Solid engineering hygiene for a standalone script: dataclass config,
  proper logging with a verbose flag, ETag-based HTTP caching with retry
  adapter, saved anchors for repeat runs, a live progress UI that
  suppresses log noise while scanning, and clean per-format writers.
- The macOS Mach VM reader is compact and correct-looking (task_for_pid →
  mach_vm_region walk → mach_vm_read), skipping >256 MB regions to keep
  scans bounded.

### Weaknesses (and what we'd change)

- **Interactive by design.** Anchors come from `input()` prompts with
  fuzzy name matching — fine for a terminal tool, unusable behind two
  buttons on a settings page. This is the main thing to redesign.
- **Three third-party dependencies** (`requests`, `psutil`, `pymem`).
  MTGA-Tapps is stdlib-only by policy. All three are replaceable:
  `urllib` (we already fetch Scryfall that way), `pgrep`/direct PID scan,
  and a small ctypes reader on Windows (`OpenProcess` /
  `VirtualQueryEx` / `ReadProcessMemory` — the same ~60 lines the macOS
  side already hand-rolls).
- **Redundant card database.** It maintains its own Scryfall bulk cache
  (~200 MB download) and its own Raw_CardDatabase parser. The tracker
  already resolves the Arena card DB path, parses names/costs/colors from
  it, and has a Scryfall per-card fallback — we reuse ours and add only
  what's missing (set code + collector number for export lines).
- **Anchor quantities are trusted absolutely** — a typo'd quantity both
  weakens the scan (wrong pattern) and corrupts the output (the typo is
  force-written into the export). Deriving anchors from data instead of
  typing removes this class of error.
- **Whole-block force-overwrite of anchors, memory-layout assumptions
  (little-endian u32 pairs), and a flat 8 MB read window** are all fine
  pragmatics, but each deserves a comment-level caveat; none is a bug.
- Minor: `re.escape` on the packed pattern is applied for pymem but not
  needed for the byte-`find` path; the txt header block means the .txt is
  not directly paste-importable until you skip 5 lines (Moxfield tolerates
  it, but a clean "4 Name (SET) 123" body is safer); `process_id`
  attribute is read off `pymem.Pymem` slightly differently across pymem
  versions.

**Verdict:** well-built for what it is — a power-user CLI. The extraction
core (steps 3–4) is worth adapting nearly as-is; the packaging around it
(deps, interactivity, its own card DB, CSV zoo) is what we replace.

## Integration plan for MTGA-Tapps

### New module: `src/mtga_tracker/collection_export.py`

Stdlib-only port of the scanner core, with attribution in the module
docstring ("Extraction technique adapted from NthPhantom10's
MTGA-collection-exporter, MIT — https://github.com/NthPhantom10/MTGA-collection-exporter"):

- `ProcessMemory` — platform reader. macOS: the Mach VM approach as-is
  via ctypes (needs elevation, see below). Windows: ctypes
  `ReadProcessMemory` walk (replaces pymem). PID discovery via
  `pgrep -x MTGA` / `tasklist` — no psutil.
- `extract_blocks(data, ...)` — the stride-walk block extractor, ported
  faithfully (strides 2/3/4, gap 64, duplicate tracking). This function is
  pure bytes-in/dict-out, so it gets real unit tests with synthetic
  memory images — something the original can't easily do.
- `score_and_validate(blocks, anchors, known_ids)` — the v3.4 scoring
  function unchanged in spirit.

### Anchors without typing: derive them from our own database

The tracker already knows cards the user provably owns:

1. **Playset prior** — cards appearing as 4-ofs in the newest submitted
   decklists (`game_deck_cards`) are almost always owned at exactly 4.
   Rank by how many distinct decks agree; take the top ~8 as candidate
   anchors `(arena_id, 4)`.
2. **Scan with candidates in sequence** exactly like the original's
   multi-anchor loop — one good anchor suffices, and validation (known-id
   ratio + cross-checking the *other* candidates' ids appear in the block)
   rejects false positives.
3. **Fallback**: if no candidate lands, run the block extractor across all
   readable regions (slower — tens of seconds — but automatic) and accept
   only a block passing a stricter validation bar (≥60 % known ids,
   ≥500 entries).
4. Unlike the original we do **not** force anchor quantities into the
   result — our 4-of prior is a good locator but not ground truth (a card
   can be owned 4× while a deck runs 4×... or the user owns more copies of
   a basic-land-adjacent card). The scanned quantities stand on their own.

No prompts, no saved-anchors file, nothing to configure.

### macOS elevation

`task_for_pid` fails without rights. Running the whole tracker as root is
out of the question. Instead the scan runs as a **separate short-lived
helper process**: the dashboard invokes
`osascript -e 'do shell script "<python> -m mtga_tracker.collection_export --scan-json <tmpfile>" with administrator privileges'`,
which shows the native macOS password dialog, runs only the scanner
elevated, and writes the raw `{arena_id: qty}` JSON to a temp file the
(unprivileged) dashboard then reads, maps, and formats. Windows needs no
elevation for same-user `PROCESS_VM_READ`. The Settings UI explains the
prompt before it appears.

### Card metadata for export lines

Extend `card_database.py` with one more cached index:
`export_index_by_arena_id() -> {arena_id: (name, set_code, collector_number)}`
from Raw_CardDatabase (`Cards` joined to `Localizations_enUS`; set and
collector columns exist across client versions under a couple of names —
probe like the existing color/cost columns). Scryfall per-card fallback
only for ids the local DB misses. `A-` prefix normalization kept
(default on, as in v3.4).

### Formats — exactly two buttons

- **`.json`** — same shape as the original's JSON (export_date, totals,
  cards[] with count/name/set/collector_number/arena_ids). It's a good
  format; keeping it means files from either tool interchange.
- **`.txt`** — Arena/Moxfield deck-line format, no header:
  `4 Lightning Helix (STA) 42` (set/number only when known). Header and
  stats move into the JSON and the UI, so the txt pastes clean into any
  importer.

The CSV dialects (Deckbox/Goldfish/Cardsphere) are dropped for now; the
writer stays table-driven so adding one later is a 15-line function.

### API + Settings UI

- `POST /api/collection/export` `{format: "json"|"txt"}` — starts a scan
  in a background thread (a scan takes seconds to a minute); returns a job
  id. `GET /api/collection/export?job=<id>` — `{state: running|done|error,
  detail, file?}`. Output written to `DATA_DIR/exports/mtga_collection_<date>.<ext>`.
- `GET /api/collection/download?file=<name>` — serves the finished file
  (name validated against the exports dir).
- **Settings page**: new "Export MTGA Collection" section above Database
  Health. Two buttons with the existing fetch-spinner treatment, a status
  line ("Scanning Arena's memory…", "Exported 1,842 unique cards →
  download"), a requirements note ("Arena must be running — open the Decks
  tab once so the collection is loaded"), and the credit line:
  "Extraction technique by
  [NthPhantom10's MTGA-collection-exporter](https://github.com/NthPhantom10/MTGA-collection-exporter)."
- Errors surface as plain sentences: Arena not running / permission
  declined / no valid collection block found (with the open-Decks-tab
  hint).

### Files touched

| File | Change |
| --- | --- |
| `src/mtga_tracker/collection_export.py` | new — reader, extractor, anchors, formats, CLI entry for the elevated helper |
| `src/mtga_tracker/card_database.py` | `export_index_by_arena_id()` |
| `src/mtga_tracker/dashboard.py` | route the three endpoints |
| `ui/src/components/SettingsPage.tsx` | Export section + credit |
| `ui/src/api.ts` | export/status/download clients |
| `tests/test_collection_export.py` | new — extractor on synthetic memory, scoring, format writers, endpoint round-trip with a stubbed scanner |

### Verification

1. Unit: synthetic memory images (clean block, dirty block with
   duplicates, stride-3 layout, garbage) through `extract_blocks` +
   `score_and_validate`; format writers against a fixture collection;
   endpoints with the scanner stubbed.
2. Live on Travis's Mac: Arena running → both buttons → import the .txt
   into Moxfield and spot-check ~10 known quantities (including an
   Alchemy `A-` card and a card owned >4×).
3. Failure paths: Arena closed; password prompt cancelled; Arena on the
   login screen (collection not in memory yet).

### Effort / risk

The extractor port and formats are mechanical (~400 lines + tests). The
two real risks are the macOS elevation flow (needs on-machine testing;
`osascript` is the standard pattern but SIP configurations vary) and the
inherent fragility of memory layout across Arena patches — mitigated by
the multi-stride extractor and by failing loudly with a clear message
rather than exporting garbage. Windows support ships in the same module
but can only be smoke-tested when a Windows machine is available.
