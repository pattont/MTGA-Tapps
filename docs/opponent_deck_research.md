# Opponent Deck Research — implementation plan

Identify *which* deck an opponent was actually playing by matching the cards
they revealed against a locally cached corpus of real meta decklists — with a
confidence score, links to the source lists, and an honest fallback when the
evidence isn't there.

## Product behavior (what the user sees)

A **"Likely Deck"** panel at the top of the game page's Opponent Deck section
(and aggregated on the opponent head-to-head page):

1. **Matched list** (best case): "Mono-Black Demons — untapped.gg variant #3,
   **21 of 23 seen cards fit** (2 unaccounted), meta share 4.1%", linking to
   the exact source decklist. Show the top 2–3 candidates when scores are
   close, with matched / missing / contradicting card breakdowns on expand.
2. **Archetype only** (medium case): evidence narrows to an archetype but no
   single variant stands out → "Looks like Mono-Black Demons (archetype
   match); no specific list matched" with the archetype page link.
3. **Fallback** (explicitly requested): nothing scores above threshold →
   show the AI-identified archetype's *top* meta deck, **clearly labeled**:
   "No close list found — showing the most-played Mono-Black Demons deck
   instead. This is NOT matched to their cards." Never dress the fallback up
   as a match.

Confidence must be visible and honest everywhere: cards seen, cards that fit,
cards the candidate doesn't play. 8 cards seen ≠ 25 cards seen.

## What already exists (reuse, don't rebuild)

- **Evidence**: `game_card_summary` records every identified opponent card
  with played/drawn/discarded/milled/exiled counts (lower bounds on copies);
  0.5.7 added per-copy played turns. Colors come from `cards.color_identity`,
  mana costs from `cards.mana_cost`.
- **Corpus fetching**: `mtga_deck_downloader` ships working scrapers:
  `scrapers/untapped.py` walks untapped.gg's meta pages (Bo1 + Bo3), lists
  archetypes with meta stats, enumerates **per-archetype variants**
  (`fetch_archetype_variants`), and decodes deckstrings to full lists via
  `UntappedDeckstringDecoder`. aetherhub / magic.gg / MTGO scrapers exist for
  breadth later. mtgdecks.net would be a NEW scraper (plain HTML, feasible)
  — phase 4, not required for v1.
- **Archetype label**: `participants.deck_archetype` (AI deck ID) gives the
  fallback category and can pre-filter candidates.

## Phase 1 — Meta-deck corpus (local, cached)

New module `src/mtga_tracker/meta_decks.py` + tables in the analytics DB:

```
meta_snapshots(id, source, format, fetched_at, note)
meta_decks(id, snapshot_id, archetype, variant_name, source_url,
           meta_share, matches, win_rate, colors)
meta_deck_cards(deck_id, card_name, quantity, board)  -- board: main/side
```

- Refresh via `scripts/refresh_meta_decks.py` (manual) and a menu action /
  dashboard button ("Update meta decks"); auto-refresh at most weekly, always
  in a background thread, silent no-op offline. Keep the last 2 snapshots per
  source/format and prune older (disk hygiene).
- Scope v1 to **Standard Bo1 + Bo3 from untapped.gg** (top ~30 archetypes ×
  up to ~10 variants each ≈ a few thousand rows — trivial for SQLite).
- Card names normalized exactly like tracker names (front face for DFCs,
  `_clean_card_name` conventions) at ingest time, so matching is a plain
  string join.
- **ToS care**: untapped.gg has no public API; we already scrape it for Deck
  Finder with polite rate limits — reuse that session/backoff code, cache
  hard, and never fetch during a match.

## Phase 2 — The matcher

New module `src/mtga_tracker/deck_matcher.py`, pure functions, no I/O:

**Evidence extraction** (per match, not per game): union of the opponent's
identified cards across the match's games with max observed copies per card.
Weight game 1 fully; discount cards seen only in games 2–3 by ~0.5 (could be
sideboard). Basic lands carry almost no signal on their own but their *count
and colors* still gate candidates.

**Scoring a candidate list** against evidence:

1. **Hard gates**: candidate colors must cover observed colors; candidate
   format must match the game's format.
2. **Weighted overlap**: each observed card contributes
   `min(observed_copies, candidate_copies) × idf(card)`, where
   `idf(card) = log(total_decks / decks_playing(card))` computed over the
   snapshot — a Swamp is worth ~nothing, a niche rare is worth a lot. This
   directly encodes "20 cards seen → high likelihood it's one specific deck".
3. **Negative evidence**: an observed card the candidate doesn't play at all
   subtracts `idf(card) × 1.5` (mainboard sightings; halved for games 2–3
   sightings, since it may be their sideboard). This is what separates "the
   deck" from "a similar deck".
4. **Prior**: multiply into a small meta-share prior (log-space addition) so
   ties break toward popular lists without letting popularity fake a match.
5. **Normalize** to a 0–100 fit score: achieved weight ÷ maximum achievable
   weight for this evidence set. Report alongside raw counts ("21/23 fit").

**Decision thresholds** (tunable constants, all in one place):

- fit ≥ 80 AND ≥ 10 distinct nonland cards seen → "matched list";
- top archetype's best variants clustered but no clear winner, archetype-sum
  fit ≥ 65 → "archetype match";
- otherwise → fallback (AI archetype's top meta deck, labeled as such);
- < 5 distinct nonland cards seen → don't even guess; show "not enough
  cards seen (N)".

**Special cases**: Brawl → the commander IS the identity; skip list-matching
in v1 (future: match the 99). Limited/draft → feature disabled. Ties between
sources deduped by identical maindeck signature.

## Phase 3 — Dashboard + UI

- `dashboard.py`: `_opponent_deck_match(conn, match_id)` runs the matcher
  on demand (corpus is local, scoring ~thousands of lists is milliseconds;
  cache the result in `opponent_deck_matches(match_id, computed_at, json)`
  and invalidate when a newer snapshot lands). Ship in the game payload as
  `opponent_deck_match` with: verdict (matched/archetype/fallback/insufficient),
  candidates [{name, url, source, fit_score, seen_fit, seen_total,
  contradictions[], meta_share}], and the evidence summary.
- UI: panel in the game page's Opponent Deck section; expandable candidate
  rows showing matched cards (with counts), unaccounted cards, and — for the
  fallback — the explicit "not matched to their cards" banner. Opponent page
  gets the per-match verdicts in its match list.

## Phase 4 — Breadth & polish (later)

- mtgdecks.net scraper as a second corpus source (agreement between sources
  boosts confidence; also covers Explorer/Timeless where untapped is thin).
- Sideboard-aware Bo3 scoring (games 2–3 evidence matched against main+side).
- "Deck evolution": same opponent seen across days → merge evidence.
- Export: "copy this matched list to Deck Finder".

## Testing & verification

- Matcher unit tests on a synthetic corpus: exact-list evidence → matched;
  evidence with 3 swapped cards → still matched with contradictions listed;
  two overlapping archetypes → archetype verdict; 4 cards seen → insufficient;
  off-color card → candidate gated out.
- Golden test against the real replay DB: take a finished game where WE know
  the opponent's deck (e.g. mirror matches or netdeck opponents), assert the
  top candidate.
- Scraper tests with recorded HTML fixtures (same pattern as Deck Finder's
  existing scraper tests). Corpus refresh is never exercised in CI against
  the live site.

## Risks / open questions

- **untapped.gg page drift**: the `__NEXT_DATA__` shape changes occasionally;
  the scraper already handles one fallback path — corpus refresh must fail
  soft (keep last snapshot, surface "meta data is N days old" in the UI).
- **Meta lag**: a week-old snapshot misses brand-new brews; the honest
  confidence display and fallback tier cover this.
- **Name mismatches** (nicknamed archetypes vs AI labels): map by fuzzy color
  + keyword match; fallback tier only needs the AI label to pick a category.
- **Effort**: Phase 1 ≈ a day (mostly plumbing around existing scrapers),
  Phase 2 ≈ a day with tests, Phase 3 ≈ half a day. Phase 4 open-ended.
