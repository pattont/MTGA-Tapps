/**
 * Client-side mana-cost lookup via Scryfall's batched collection endpoint.
 *
 * The tracker's database stores card names and type categories but not mana
 * costs (MTGA's log never states them), so the deck page enriches its decklist
 * with a one-shot batched fetch — the same Scryfall dependency the card-art
 * backdrop already has. Results are cached in localStorage (mana costs are
 * immutable), and every failure path degrades to "no cost known", which the
 * UI renders as a dash.
 */

export interface CardManaInfo {
  /** Scryfall-notation cost, e.g. "{2}{G}{G}". Empty string = no cost (lands). */
  mana_cost: string;
  /** Mana value / converted cost, used for sorting. */
  cmc: number;
}

const STORAGE_KEY = 'mtga-tracker-mana-costs-v1';
const COLLECTION_URL = 'https://api.scryfall.com/cards/collection';
const CHUNK_SIZE = 75; // Scryfall's per-request identifier limit.

/** null = looked up before and not found; skip refetching. */
const cache = new Map<string, CardManaInfo | null>();
let storageLoaded = false;

function loadStorage(): void {
  if (storageLoaded) {
    return;
  }
  storageLoaded = true;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw) as Record<string, CardManaInfo | null>;
    for (const [name, info] of Object.entries(parsed)) {
      if (info === null || (typeof info.mana_cost === 'string' && typeof info.cmc === 'number')) {
        cache.set(name, info);
      }
    }
  } catch {
    // Cache is best-effort only.
  }
}

function persistStorage(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(cache)));
  } catch {
    // Cache is best-effort only.
  }
}

/** Front face of a "Fire // Ice"-style name; Scryfall matches face names too. */
export function frontFaceName(cardName: string): string {
  return cardName.split(' // ')[0].trim();
}

function normalizeKey(name: string): string {
  return frontFaceName(name).toLowerCase();
}

interface ScryfallCardFace {
  name?: string;
  mana_cost?: string;
}

interface ScryfallCard {
  name?: string;
  mana_cost?: string;
  cmc?: number;
  card_faces?: ScryfallCardFace[];
}

function recordCard(card: ScryfallCard): void {
  const cost =
    (card.mana_cost && card.mana_cost.trim()) ||
    (card.card_faces?.[0]?.mana_cost ?? '').trim();
  const info: CardManaInfo = { mana_cost: cost, cmc: Number(card.cmc ?? 0) };
  const names = new Set<string>();
  if (card.name) {
    names.add(card.name);
    card.name.split(' // ').forEach((part) => names.add(part.trim()));
  }
  card.card_faces?.forEach((face) => {
    if (face.name) {
      names.add(face.name);
    }
  });
  names.forEach((name) => cache.set(name.toLowerCase(), info));
}

/**
 * Resolve mana costs for the given card names. Returns a map keyed by the
 * ORIGINAL display names (not normalized), with null for unresolvable cards.
 * Network failures resolve to whatever the cache already had.
 */
export async function fetchManaCosts(names: string[]): Promise<Map<string, CardManaInfo | null>> {
  loadStorage();
  const wanted = Array.from(new Set(names.filter((name) => name.trim().length > 0)));
  const missing = wanted.filter((name) => !cache.has(normalizeKey(name)));
  if (missing.length > 0) {
    let fetchedAny = false;
    for (let start = 0; start < missing.length; start += CHUNK_SIZE) {
      const chunk = missing.slice(start, start + CHUNK_SIZE);
      try {
        const response = await fetch(COLLECTION_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            identifiers: chunk.map((name) => ({ name: frontFaceName(name) })),
          }),
        });
        if (!response.ok) {
          continue;
        }
        const payload = (await response.json()) as { data?: ScryfallCard[] };
        if (!Array.isArray(payload.data)) {
          continue;
        }
        payload.data.forEach(recordCard);
        // Mark misses so we don't hammer Scryfall on every refresh.
        chunk.forEach((name) => {
          if (!cache.has(normalizeKey(name))) {
            cache.set(normalizeKey(name), null);
          }
        });
        fetchedAny = true;
      } catch {
        // Offline or blocked: leave these unresolved (and un-cached) so a
        // later page load can retry.
      }
    }
    if (fetchedAny) {
      persistStorage();
    }
  }
  const result = new Map<string, CardManaInfo | null>();
  wanted.forEach((name) => {
    result.set(name, cache.get(normalizeKey(name)) ?? null);
  });
  return result;
}

export interface PlayedCardLike {
  display_name: string;
  type_category?: string | null;
  count: number;
}

export interface PlayedManaStats {
  /** Average mana value of each nonland card played (1 decimal). */
  avg_per_card: number | null;
  /** Total mana value of nonland cards played per turn taken (1 decimal). */
  per_turn: number | null;
}

/**
 * Mana-value profile of a set of played cards. Lands are excluded (playing a
 * land is not a cast), as are cards whose cost Scryfall couldn't resolve.
 * Mana value is the printed cost — cost reductions, X spells (X = 0), and
 * alternative costs aren't visible in the log, so treat this as a curve
 * indicator rather than exact mana spent.
 */
export function playedManaStats(
  cards: PlayedCardLike[],
  mana: Map<string, CardManaInfo | null>,
  turns: number | null | undefined,
): PlayedManaStats {
  let totalManaValue = 0;
  let knownPlays = 0;
  for (const card of cards) {
    if ((card.type_category ?? '').toLowerCase() === 'land') {
      continue;
    }
    const info = mana.get(card.display_name);
    if (!info || card.count <= 0) {
      continue;
    }
    totalManaValue += info.cmc * card.count;
    knownPlays += card.count;
  }
  const round1 = (value: number) => Math.round(value * 10) / 10;
  return {
    avg_per_card: knownPlays > 0 ? round1(totalManaValue / knownPlays) : null,
    per_turn: knownPlays > 0 && turns != null && turns > 0 ? round1(totalManaValue / turns) : null,
  };
}

/** A server-provided cost (Arena card DB via the tracker's cards table). */
export interface ServerManaEntry {
  mana_cost: string;
  mana_value: number;
}

/**
 * Seed the cache with Arena-derived costs from a dashboard payload's
 * `card_mana` map. Server values take precedence over anything Scryfall
 * cached earlier, and seeded names are skipped by fetchManaCosts entirely —
 * with a complete map the page never talks to Scryfall at all.
 */
export function seedManaCosts(
  entries: Record<string, ServerManaEntry> | null | undefined,
): void {
  if (!entries) {
    return;
  }
  loadStorage();
  for (const [name, entry] of Object.entries(entries)) {
    if (!entry || typeof entry.mana_cost !== 'string') {
      continue;
    }
    const info: CardManaInfo = { mana_cost: entry.mana_cost, cmc: Number(entry.mana_value ?? 0) };
    cache.set(name.toLowerCase(), info);
    name.split(' // ').forEach((part) => cache.set(part.trim().toLowerCase(), info));
  }
}

/** Split "{2}{G}{G}" into ["{2}", "{G}", "{G}"]. */
export function manaCostSymbols(cost: string): string[] {
  return cost.match(/\{[^}]+\}/g) ?? [];
}

/**
 * mana-font class for one "{G/W}"-style symbol: braces off, slashes out,
 * lowercased — {G/W} → ms-gw, {2/U} → ms-2u, {B/P} → ms-bp, {10} → ms-10.
 * The font ships every printed cost symbol including hybrid, twobrid,
 * Phyrexian, hybrid-Phyrexian, X, snow, and colorless.
 */
export function manaSymbolClass(symbol: string): string {
  return `ms-${symbol.slice(1, -1).toLowerCase().replace(/\//g, '')}`;
}
