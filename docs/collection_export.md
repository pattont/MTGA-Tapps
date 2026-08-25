# Collection Export — Plan

Add "Export MTGA Collection" to the Settings page (above Database Health):
three buttons — **Export to .json**, **Export to .csv**, and **Export to
.txt** — producing files importable into Moxfield and similar sites. The
extraction technique is adapted from NthPhantom10's
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

### What we reuse instead of porting — the cleanup map

Roughly 60 % of mtg.py duplicates infrastructure MTGA-Tapps already has.
Piece by piece:

| mtg.py piece (lines) | Fate | Replaced by |
| --- | --- | --- |
| `DatabaseLoader._find_mtga_raw_path` (~60 lines of per-OS path guessing) | **drop** | `paths.py` already resolves Raw_CardDatabase across Steam/Epic/macOS/Windows incl. multi-drive Steam libraries — strictly better than the original's |
| `DatabaseLoader._parse_sqlite` + `_load_localizations` (~90 lines) | **drop** | `card_database.py` already opens the Arena DB, probes schema variants, and joins Localizations_enUS; we add one method (below) instead of a second parser |
| `DatabaseLoader._fetch_scryfall` + ETag cache + `requests` session/retry (~120 lines, 200 MB bulk download) | **drop** | `card_database.py`'s existing per-card Scryfall fallback over `urllib` — only ids the local DB misses get fetched, no bulk file on disk |
| `MacOSMem` (Mach VM reader) | **port** | kept nearly verbatim in `collection_export.py` (it's already pure ctypes) |
| `pymem` usage (Windows) | **rewrite** | ~60 lines of ctypes (`OpenProcess`/`VirtualQueryEx`/`ReadProcessMemory`) mirroring the macOS reader's interface — drops the dependency |
| `psutil` PID lookup (macOS) | **rewrite** | `pgrep -x MTGA` via subprocess (already the stdlib-only pattern used elsewhere in the repo) |
| `AnchorManager` interactive prompts + fuzzy matching + saved-anchor file (~120 lines) | **drop** | automatic anchors from `game_deck_cards` playsets (see above) |
| `MemoryScanner` scan/extract/score/validate core (~300 lines) | **port** | the valuable part — kept faithful, refactored into pure functions so it's unit-testable |
| `ProgressBar`/`ScanProgressBar` + ANSI console handling (~90 lines) | **drop** | progress goes through the job-status endpoint; the web UI renders it |
| `CollectionWriter._aggregate` + `A-` normalization + blank-set merge | **port** | same logic, minus the interactive `include_descriptions` prompt |
| JSON / txt / Moxfield-CSV writers | **port (3 of 6)** | Deckbox, Goldfish, Cardsphere CSVs and the stats file dropped; writer stays table-driven for later additions |
| `main()` argparse CLI, auto-open-explorer, log files | **drop** | replaced by the API endpoints; a minimal `python -m mtga_tracker.collection_export --scan-json <file>` entry remains solely as the elevated macOS helper |

Net effect: mtg.py's 1,578 lines become roughly 400 new lines here, none
of them third-party, and the card metadata comes from the same database
the rest of the tracker already trusts.

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

**Primary source: the shared `arena_cards` table** from the format-legality
plan (`valid_cards_per_format.md`) — Scryfall's `default_cards` bulk file,
ingested once in the background, gives `arena_id → (name, set_code,
collector_number)` for every Arena printing. That's exactly the export
index, already maintained, with a Force Refresh button on Settings.

Fallback when the bulk ingest hasn't run yet (fresh install, offline):
`card_database.py`'s Raw_CardDatabase lookup for names (set/collector may be
blank on those lines — Moxfield matches by name regardless). `A-` prefix
normalization kept (default on, as in v3.4).

### Formats — three buttons

- **`.json`** — same shape as the original's JSON (export_date, totals,
  cards[] with count/name/set/collector_number/rarity/arena_ids). It's a
  good format; keeping it means files from either tool interchange, and it
  is the lossless record the other two derive from.
- **`.csv`** — the Moxfield CSV dialect, column-for-column what the
  original's `_write_moxfield` emits ("Count", "Name", "Edition",
  "Collector Number" — the columns Moxfield's collection importer maps
  automatically). One dialect only: Moxfield is the target site, and its
  CSV also imports into most other tools. The writer table stays
  format-keyed, so a Deckbox/Goldfish/Cardsphere dialect later is a
  ~15-line function each, not a redesign.
- **`.txt`** — Arena/Moxfield deck-line format, no header:
  `4 Lightning Helix (STA) 42` (set/number only when known). The
  original's txt leads with a 5-line stats banner; ours doesn't — the
  stats live in the JSON and the UI status line, so the txt pastes clean
  into any importer.

All three run through the same pipeline — scan once, aggregate once,
format last — so clicking two buttons back-to-back reuses the scan result
(cached in memory for ~5 minutes, see the API section) instead of
attaching to Arena twice.

### API

- `POST /api/collection/export` `{format: "json"|"csv"|"txt"}` — starts a
  scan in a background thread (a scan takes seconds to a minute); returns
  a job id. `GET /api/collection/export?job=<id>` —
  `{state: running|done|error, detail, file?, unique?, total?}` so the UI
  can show live phase text ("Attaching to Arena…", "Scanning memory…",
  "Mapping 1,842 cards…").
- The raw scan result (`{arena_id: qty}`) is cached in the dashboard
  process for ~5 minutes: exporting a second format inside that window
  formats from cache instantly — no second attach, no second macOS
  password prompt. `{refresh: true}` forces a rescan.
- Output written to `DATA_DIR/exports/mtga_collection_<date>.<ext>`;
  `GET /api/collection/download?file=<name>` serves it (name validated
  against the exports dir, no path traversal).

### Settings UI — the box itself

New "Export MTGA Collection" section above Database Health:

- **Intro line**: "Read your full card collection from the running game
  and export it for Moxfield and similar sites."
- **Requirements callout** (always visible, styled like the existing
  helper notes): "MTG Arena must be running, and your collection must be
  loaded — open the **Decks** tab in Arena once before exporting."
- **macOS warning** (shown only when the dashboard detects macOS — the
  server includes `platform` in the settings payload): "macOS will show an
  **administrator password prompt** when you export — reading another
  app's memory requires elevated access. The password is used only to run
  the scan; nothing is installed or changed." Shown in the box *and*
  repeated in the status line at the moment the prompt is about to appear,
  so it never feels like a surprise dialog.
- **Fine-print caveats** (small muted text): "Unofficial: Arena doesn't
  expose your collection, so this reads it from the game's memory — the
  game is never modified. An Arena update can temporarily break this
  until the tool is adjusted. Quantities come straight from the game's
  own data."
- **Three buttons**: "Export to .json", "Export to .csv", "Export to
  .txt" — existing fetch-spinner treatment; all three disabled while a
  job runs; status line beneath ("Scanning Arena's memory…", "Exported
  1,842 unique cards (7,310 total) → Download"), with the Download link
  pointing at `/api/collection/download`.
- **Credit line**: "Extraction technique by
  [NthPhantom10's MTGA-collection-exporter](https://github.com/NthPhantom10/MTGA-collection-exporter)."
- Errors surface as plain sentences mapped from the job's error code:
  Arena not running → "MTG Arena isn't running — launch it and open the
  Decks tab, then try again."; permission declined → "The administrator
  prompt was cancelled — the scan can't run without it."; no valid block →
  "Couldn't find the collection in Arena's memory — open the Decks tab in
  Arena so it loads, then try again."

### Files touched

| File | Change |
| --- | --- |
| `src/mtga_tracker/collection_export.py` | new — memory readers, extractor, auto-anchors, scan cache, json/csv/txt writers, CLI entry for the elevated macOS helper |
| `src/mtga_tracker/card_database.py` | `export_index_by_arena_id()` (name, set code, collector number by arena id) |
| `src/mtga_tracker/settings_api.py` | include `platform` in the settings payload (drives the macOS warning) |
| `src/mtga_tracker/dashboard.py` | route the export/status/download endpoints |
| `ui/src/components/SettingsPage.tsx` | Export section: callouts, macOS warning, three buttons, status line, credit |
| `ui/src/api.ts` | export/status/download clients + settings platform field |
| `tests/test_collection_export.py` | new — extractor on synthetic memory, scoring, all three format writers, endpoint round-trip with a stubbed scanner, scan-cache reuse |

### Verification

1. Unit: synthetic memory images (clean block, dirty block with
   duplicates, stride-3 layout, garbage) through `extract_blocks` +
   `score_and_validate`; format writers against a fixture collection;
   endpoints with the scanner stubbed.
2. Live on Travis's Mac: Arena running → all three buttons → import the
   .txt and the .csv into Moxfield and spot-check ~10 known quantities
   (including an Alchemy `A-` card and a card owned >4×); confirm the
   second export inside the cache window skips the password prompt.
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
