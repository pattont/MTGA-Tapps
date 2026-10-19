/**
 * One queue for the dashboard's Scryfall API calls.
 *
 * Scryfall allows 2 requests per second on /cards/search, /cards/named,
 * /cards/random and /cards/collection, and answers overages with a 429 that
 * locks the caller out (https://scryfall.com/docs/api/rate-limits). Calls to
 * those endpoints are spaced through this module. The Buy on Paper price
 * lookup uses it; the page-load mana-cost lookup still calls fetch directly.
 *
 * A 429 carries no CORS header, so the browser reports it as a network error
 * rather than a status code. Any failed request to a limited endpoint is
 * treated as a possible lockout: further limited calls fail fast for a minute
 * instead of retrying into a ban.
 */

const LIMITED = /^https:\/\/api\.scryfall\.com\/cards\/(search|named|random|collection)\b/u;
const SPACING_MS = 550;
const BACKOFF_MS = 60_000;

let nextSlot = 0;
let blockedUntil = 0;

export class ScryfallUnavailable extends Error {
  constructor() {
    super('Scryfall is rate limiting requests; try again in a minute.');
    this.name = 'ScryfallUnavailable';
  }
}

function wait(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(signal.reason); }, { once: true });
  });
}

/** fetch() for api.scryfall.com, spaced and backed off for the limited endpoints. */
export async function scryfallFetch(url: string, init?: RequestInit): Promise<Response> {
  if (!LIMITED.test(url)) return fetch(url, init);
  const now = Date.now();
  if (now < blockedUntil) throw new ScryfallUnavailable();
  const start = Math.max(now, nextSlot);
  nextSlot = start + SPACING_MS;
  if (start > now) await wait(start - now, init?.signal);
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (!init?.signal?.aborted) blockedUntil = Date.now() + BACKOFF_MS;
    throw error;
  }
  if (response.status === 429) {
    blockedUntil = Date.now() + BACKOFF_MS;
    throw new ScryfallUnavailable();
  }
  return response;
}

/** Test hook. */
export function resetScryfallQueue(): void {
  nextSlot = 0;
  blockedUntil = 0;
}
