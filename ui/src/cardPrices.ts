/**
 * Paper prices for the Buy on Paper dialog, from Scryfall in the browser —
 * the same dependency the mana-cost and card-art lookups already have.
 *
 * Two passes so the dialog fills in fast and then sharpens:
 * 1. One /cards/collection request per 75 names says which cards exist and
 *    gives a first price from Scryfall's default printing.
 * 2. Searches for many cards at once, sorted by price, find each card's
 *    cheapest English paper printing, and its price replaces the first one.
 *
 * Every request goes through scryfallQueue (2 per second, with a back-off),
 * so a 60-card deck costs a handful of requests, not one per card.
 *
 * Arena-only cards (Alchemy designs, digital reprint sets) have no paper
 * printing and are reported as such. Rebalanced "A-" cards map to the paper
 * original, which has the pre-rebalance text, and are flagged so the UI can
 * say so. Scryfall's USD prices are TCGplayer market prices, refreshed once
 * a day, so finished results are cached in localStorage for a day.
 */

import { frontFaceName } from './manaCosts';
import { isBasicLand } from './paperDeck';
import { scryfallFetch } from './scryfallQueue';

export type PaperStatus = 'paper' | 'digital_only' | 'not_found';

export interface PaperPrinting {
  set: string;
  set_name: string;
  collector_number: string;
  /** Lowest listed USD price across finishes, or null when none is listed. */
  usd: number | null;
  finish: 'nonfoil' | 'foil' | 'etched' | null;
}

export interface PaperCardInfo {
  status: PaperStatus;
  /** Scryfall's canonical paper name ("Fire // Ice"); null when not found. */
  name: string | null;
  printing: PaperPrinting | null;
  /** The Arena card is a rebalanced "A-" version; paper has the original text. */
  rebalanced: boolean;
  /** True once the cheapest-printing pass has settled this card. */
  cheapest: boolean;
}

const STORAGE_KEY = 'mtga-tracker-paper-prices-v1';
const COLLECTION_URL = 'https://api.scryfall.com/cards/collection';
const SEARCH_URL = 'https://api.scryfall.com/cards/search';
const CHUNK_SIZE = 75;
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
/** Names per price search, and a cap on its query length. */
const SEARCH_BATCH = 20;
const SEARCH_QUERY_CHARS = 900;
/** Result pages read per search before keeping the first-pass prices. */
const SEARCH_MAX_PAGES = 5;
const SEARCH_FILTERS = 'game:paper lang:en -is:oversized -set_type:memorabilia';

interface CacheEntry {
  info: PaperCardInfo;
  at: number;
}

const cache = new Map<string, CacheEntry>();
let storageLoaded = false;

function loadStorage(): void {
  if (storageLoaded) return;
  storageLoaded = true;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Record<string, CacheEntry>;
    const now = Date.now();
    for (const [key, entry] of Object.entries(parsed)) {
      if (entry?.info && typeof entry.at === 'number' && now - entry.at < CACHE_TTL_MS && entry.info.cheapest) {
        cache.set(key, entry);
      }
    }
  } catch {
    // Cache is best-effort only.
  }
}

function persistStorage(): void {
  try {
    const now = Date.now();
    const fresh = Array.from(cache.entries()).filter(([, entry]) => entry.info.cheapest && now - entry.at < CACHE_TTL_MS);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(fresh)));
  } catch {
    // Cache is best-effort only.
  }
}

/** Test hook: forget everything cached in memory. */
export function resetPaperPriceCache(): void {
  cache.clear();
  storageLoaded = false;
}

/** "A-Name" is Arena's rebalanced version of the paper card "Name". */
export function paperLookupName(arenaName: string): { name: string; rebalanced: boolean } {
  const front = frontFaceName(arenaName.trim());
  const match = front.match(/^A-(.+)$/u);
  return match ? { name: match[1], rebalanced: true } : { name: front, rebalanced: false };
}

function cacheKey(arenaName: string): string {
  return arenaName.trim().toLowerCase();
}

interface ScryfallPrices {
  usd?: string | null;
  usd_foil?: string | null;
  usd_etched?: string | null;
}

interface ScryfallCard {
  name?: string;
  set?: string;
  set_name?: string;
  collector_number?: string;
  games?: string[];
  prices?: ScryfallPrices;
  card_faces?: { name?: string }[];
}

function lowestPrice(prices: ScryfallPrices | undefined): Pick<PaperPrinting, 'usd' | 'finish'> {
  const options: [PaperPrinting['finish'], string | null | undefined][] = [
    ['nonfoil', prices?.usd],
    ['foil', prices?.usd_foil],
    ['etched', prices?.usd_etched],
  ];
  let best: Pick<PaperPrinting, 'usd' | 'finish'> = { usd: null, finish: null };
  for (const [finish, raw] of options) {
    const value = raw == null ? NaN : Number(raw);
    if (Number.isFinite(value) && (best.usd === null || value < best.usd)) {
      best = { usd: value, finish };
    }
  }
  return best;
}

function printingOf(card: ScryfallCard): PaperPrinting {
  return {
    set: (card.set ?? '').toUpperCase(),
    set_name: card.set_name ?? '',
    collector_number: card.collector_number ?? '',
    ...lowestPrice(card.prices),
  };
}

function namesOf(card: ScryfallCard): string[] {
  const names = new Set<string>();
  if (card.name) {
    names.add(card.name.toLowerCase());
    card.name.split(' // ').forEach((part) => names.add(part.trim().toLowerCase()));
  }
  card.card_faces?.forEach((face) => face.name && names.add(face.name.toLowerCase()));
  return Array.from(names);
}

export type PaperPriceMap = Map<string, PaperCardInfo | null>;

export interface PaperLookupProgress {
  /** Cards still being checked. */
  pending: number;
  /** Scryfall refused or failed a request; unsettled cards keep first-pass prices. */
  interrupted: boolean;
}

/** One price search: `(!"A" or !"B" …) <filters>`, cheapest printing first. */
function searchBatches(names: string[]): string[][] {
  const batches: string[][] = [];
  let batch: string[] = [];
  let length = 0;
  for (const name of names) {
    const term = `!"${name.replace(/"/gu, '')}"`.length + 4;
    if (batch.length && (batch.length >= SEARCH_BATCH || length + term > SEARCH_QUERY_CHARS)) {
      batches.push(batch);
      batch = [];
      length = 0;
    }
    batch.push(name);
    length += term;
  }
  if (batch.length) batches.push(batch);
  return batches;
}

function searchUrl(names: string[]): string {
  const terms = names.map((name) => `!"${name.replace(/"/gu, '')}"`).join(' or ');
  const params = new URLSearchParams({ q: `(${terms}) ${SEARCH_FILTERS}`, unique: 'prints', order: 'usd', dir: 'asc' });
  return `${SEARCH_URL}?${params}`;
}

/**
 * Resolve paper info for Arena card names. `onUpdate` receives the full map
 * (keyed by the original names; null = still looking) every time something
 * changes, so the UI can update totals live. Resolves when both passes end.
 */
export async function lookupPaperPrices(
  arenaNames: string[],
  onUpdate: (map: PaperPriceMap, progress: PaperLookupProgress) => void,
  signal?: AbortSignal,
): Promise<PaperPriceMap> {
  loadStorage();
  const wanted = Array.from(new Set(arenaNames.map((name) => name.trim()).filter(Boolean)));
  const result: PaperPriceMap = new Map();
  wanted.forEach((name) => result.set(name, cache.get(cacheKey(name))?.info ?? null));
  const missing = wanted.filter((name) => result.get(name) === null);
  let pending = missing.length;
  let interrupted = false;
  const emit = () => onUpdate(new Map(result), { pending, interrupted });
  emit();
  if (!missing.length) return result;

  const settle = (name: string, info: PaperCardInfo) => {
    result.set(name, info);
    cache.set(cacheKey(name), { info, at: Date.now() });
    pending -= 1;
  };

  // Pass 1: which cards exist, plus a first price.
  const lookups = new Map(missing.map((name) => [name, paperLookupName(name)]));
  for (let start = 0; start < missing.length; start += CHUNK_SIZE) {
    if (signal?.aborted) return result;
    const chunk = missing.slice(start, start + CHUNK_SIZE);
    try {
      const response = await scryfallFetch(COLLECTION_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifiers: chunk.map((name) => ({ name: lookups.get(name)!.name })) }),
        signal,
      });
      if (!response.ok) continue;
      const payload = (await response.json()) as { data?: ScryfallCard[] };
      const byName = new Map<string, ScryfallCard>();
      (payload.data ?? []).forEach((card) => namesOf(card).forEach((key) => byName.set(key, card)));
      for (const name of chunk) {
        const lookup = lookups.get(name)!;
        const card = byName.get(lookup.name.toLowerCase());
        if (!card) continue;
        const onPaper = card.games?.includes('paper') ?? false;
        result.set(name, {
          status: onPaper ? 'paper' : 'digital_only',
          name: card.name ?? lookup.name,
          printing: onPaper ? printingOf(card) : null,
          rebalanced: lookup.rebalanced,
          cheapest: false,
        });
      }
      emit();
    } catch {
      if (signal?.aborted) return result;
      // Offline or rate limited: pass 2 would fail the same way.
      interrupted = true;
      pending = 0;
      emit();
      return result;
    }
  }

  // Pass 2: cheapest English paper printing, many cards per search. Basic
  // lands get their own search: their hundreds of cent-priced printings
  // would otherwise push every pricier card onto later result pages.
  const toSearch = missing;
  const searchName = (name: string) => result.get(name)?.name ?? lookups.get(name)!.name;
  const basics = toSearch.filter((name) => isBasicLand(searchName(name)));
  const others = toSearch.filter((name) => !isBasicLand(searchName(name)));
  const batches = [...searchBatches(others.map(searchName)), ...searchBatches(basics.map(searchName))];
  for (const batch of batches) {
    if (signal?.aborted || interrupted) break;
    const arenaFor = new Map<string, string[]>();
    toSearch.forEach((name) => {
      const key = searchName(name).toLowerCase();
      if (batch.some((entry) => entry.toLowerCase() === key)) arenaFor.set(key, [...(arenaFor.get(key) ?? []), name]);
    });
    const batchArena = Array.from(arenaFor.values()).flat();
    const priced = new Map<string, ScryfallCard>();
    const unpriced = new Map<string, ScryfallCard>();
    let url: string | null = searchUrl(batch);
    let complete = false;
    for (let page = 0; url && page < SEARCH_MAX_PAGES; page += 1) {
      let payload: { data?: ScryfallCard[]; has_more?: boolean; next_page?: string };
      try {
        const response = await scryfallFetch(url, { signal });
        if (response.status === 404) { complete = true; break; }
        if (!response.ok) { interrupted = true; break; }
        payload = await response.json();
      } catch {
        if (!signal?.aborted) interrupted = true;
        break;
      }
      // Sorted by nonfoil price, unpriced last: a card's first priced
      // appearance is its cheapest printing.
      for (const card of payload.data ?? []) {
        const priceKnown = lowestPrice(card.prices).usd !== null;
        for (const key of namesOf(card)) {
          for (const arenaName of arenaFor.get(key) ?? []) {
            if (priceKnown && !priced.has(arenaName)) priced.set(arenaName, card);
            else if (!priceKnown && !unpriced.has(arenaName)) unpriced.set(arenaName, card);
          }
        }
      }
      if (batchArena.every((name) => priced.has(name))) break;
      if (!payload.has_more || !payload.next_page) { complete = true; break; }
      url = payload.next_page;
    }
    if (signal?.aborted) break;
    for (const name of batchArena) {
      const lookup = lookups.get(name)!;
      const first = result.get(name);
      const found = priced.get(name) ?? unpriced.get(name);
      if (found) {
        settle(name, {
          status: 'paper', name: found.name ?? first?.name ?? lookup.name,
          printing: printingOf(found), rebalanced: lookup.rebalanced, cheapest: true,
        });
      } else if (complete) {
        // Every paper printing was listed and none was this card.
        settle(name, {
          status: first ? 'digital_only' : 'not_found', name: first?.name ?? null,
          printing: null, rebalanced: lookup.rebalanced, cheapest: true,
        });
      } else {
        pending -= 1; // Keep the first-pass price; not cached, so it's retried next time.
      }
    }
    emit();
  }
  if (interrupted && !signal?.aborted) {
    pending = 0;
    emit();
  }
  persistStorage();
  return result;
}
