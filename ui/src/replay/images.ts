/**
 * Card image resolution for the replay table (docs/REPLAY_FORMAT.md §3).
 *
 * `api.scryfall.com/cards/...?format=image` answers with a redirect to the
 * `cards.scryfall.io` CDN. The queue learns that final URL with one HEAD
 * request (no image body is downloaded), rate-limited to Scryfall's guidance,
 * and caches it per card so later visits go straight to the CDN, which is not
 * rate-limited and is cached by the browser.
 */
import { frontFaceName } from '../manaCosts';
import { scryfallFetch } from '../scryfallQueue';
import { createTokenFaceCanvas } from './materials';
import type { CancelTimer, ScheduleFn } from './player';
import type { CardKey, ReplayCard } from './types';

export type ImageSize = 'normal' | 'large';

const API_HOST = 'api.scryfall.com';
const API_BASE = `https://${API_HOST}/cards`;

export function isRateLimitedUrl(url: string): boolean {
  try {
    return new URL(url).host === API_HOST;
  } catch {
    return false;
  }
}

/**
 * Scryfall search URLs for a token's printed art: Arena tokens have no
 * Scryfall arena id, but every token type is a Scryfall "card" in a token set
 * (`t:token`). The strict query pins power/toughness and colors so "Soldier
 * 1/1 white" does not come back as a 4/4 red one; the loose query is the name
 * alone. Newest printing first; two-faced tokens are skipped so the front is
 * the token itself. The size rides in the fragment (never sent to Scryfall).
 */
export function tokenSearchCandidates(card: ReplayCard, size: ImageSize): string[] {
  const name = frontFaceName(card.name ?? '').trim();
  if (!name || name === 'Unknown card') return [];
  const quoted = `!"${name.replace(/"/g, '')}"`;
  const refinements: string[] = [];
  if (card.power !== null && /^\d+$/.test(card.power)) refinements.push(`pow=${card.power}`);
  if (card.toughness !== null && /^\d+$/.test(card.toughness)) refinements.push(`tou=${card.toughness}`);
  const colors = (card.color_identity ?? '').toUpperCase().replace(/[^WUBRG]/g, '');
  if (colors) refinements.push(`c=${colors.toLowerCase()}`);
  const query = (terms: string[]) =>
    `${API_BASE}/search?unique=art&order=released&dir=desc&q=${encodeURIComponent(
      ['t:token', quoted, ...terms, '-is:dfc'].join(' '),
    )}#size=${size}`;
  const urls = [query(refinements)];
  if (refinements.length) urls.push(query([]));
  return urls;
}

/** Ordered image URLs to try; empty means "use generatedTokenFace". */
export function cardImageCandidates(card: ReplayCard, size: ImageSize): string[] {
  const urls: string[] = [];
  if (card.image_url) {
    urls.push(size === 'large' ? card.image_url.replace('/normal/', '/large/') : card.image_url);
  }
  // The exact token printing ("ttdm/13") when Arena's card DB named it.
  if (card.is_token && card.token_print && /^[a-z0-9]+\/[^/?#\s]+$/i.test(card.token_print)) {
    urls.push(`${API_BASE}/${card.token_print}?format=image&version=${size}`);
  }
  // A back face shares its card with the front; Scryfall serves its picture with face=back.
  const face = card.back_face ? '&face=back' : '';
  // The exact printing ("fra/23"): Scryfall learns a new set's Arena ids late.
  const printed = !card.is_token && card.print ? /^([a-z0-9]+)\/([^/?#\s]+)$/i.exec(card.print) : null;
  if (printed) {
    urls.push(`${API_BASE}/${printed[1]}/${encodeURIComponent(printed[2])}?format=image&version=${size}${face}`);
  }
  if (card.arena_id) {
    urls.push(`${API_BASE}/arena/${card.arena_id}?format=image&version=${size}${face}`);
  }
  if (card.is_token) {
    // Token names ("Treasure", "Goblin") rarely name a real card: search the token sets instead.
    urls.push(...tokenSearchCandidates(card, size));
  } else if (card.name && card.name !== 'Unknown card') {
    const name = encodeURIComponent(frontFaceName(card.name));
    urls.push(`${API_BASE}/named?exact=${name}&format=image&version=${size}${face}`);
  }
  return urls;
}

/**
 * A lookup failure. `permanent` (404: Scryfall has no such card) is cached by
 * the queue so the card is never asked for again; anything else (429, 5xx,
 * network) is retried on the next request for that URL.
 */
export class ImageLookupError extends Error {
  readonly permanent: boolean;

  constructor(message: string, permanent: boolean) {
    super(message);
    this.name = 'ImageLookupError';
    this.permanent = permanent;
  }
}

function isPermanentStatus(status: number): boolean {
  return status === 404 || status === 400 || status === 422;
}

interface ScryfallImageUris {
  normal?: string;
  large?: string;
}

interface ScryfallSearchCard {
  image_uris?: ScryfallImageUris;
  card_faces?: Array<{ image_uris?: ScryfallImageUris }>;
}

/** The first search hit's front image at the size named in the URL fragment. */
export function searchImageUrl(url: string, body: unknown): string | null {
  const size: ImageSize = url.endsWith('#size=large') ? 'large' : 'normal';
  const data = (body as { data?: ScryfallSearchCard[] } | null)?.data;
  const first = Array.isArray(data) ? data[0] : undefined;
  const uris = first?.image_uris ?? first?.card_faces?.[0]?.image_uris;
  return uris?.[size] ?? uris?.normal ?? null;
}

export type ImageResolver = (url: string) => Promise<string>;
export type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

function isSearchUrl(url: string): boolean {
  try {
    return new URL(url).pathname === '/cards/search';
  } catch {
    return false;
  }
}

/**
 * HEAD (falling back to GET) through the redirect; returns the final CDN URL.
 * Token searches are one GET whose JSON names the image instead. A request
 * that never got an answer is a retryable failure: Scryfall's rate-limit
 * lockout carries no CORS header, so the browser reports it as a network error.
 */
export function scryfallResolver(fetchImpl: FetchFn = scryfallFetch): ImageResolver {
  return async (url) => {
    if (!isRateLimitedUrl(url)) return url;
    try {
      return await lookUp(fetchImpl, url);
    } catch (error) {
      if (error instanceof ImageLookupError) throw error;
      throw new ImageLookupError(`Scryfall could not be reached: ${String(error)}`, false);
    }
  };
}

/** One lookup: the final CDN URL, or the search's first image. */
async function lookUp(fetchImpl: FetchFn, url: string): Promise<string> {
  if (isSearchUrl(url)) {
    const response = await fetchImpl(url, { headers: { Accept: 'application/json' } });
    if (!response.ok) {
      throw new ImageLookupError(`Scryfall token search failed (${response.status})`, isPermanentStatus(response.status));
    }
    const found = searchImageUrl(url, await response.json());
    if (!found) throw new ImageLookupError('Scryfall token search found no image', true);
    return found;
  }
  let response = await fetchImpl(url, { method: 'HEAD', redirect: 'follow' });
  if (response.status === 405) {
    response = await fetchImpl(url, { redirect: 'follow' });
    void response.body?.cancel();
  }
  if (!response.ok) {
    throw new ImageLookupError(`Scryfall image lookup failed (${response.status})`, isPermanentStatus(response.status));
  }
  return response.url || url;
}

/** Scryfall asks for 50–100 ms between API requests; 8/s keeps clear of it. */
export const SCRYFALL_RATE_PER_SECOND = 8;

/**
 * Token bucket for api.scryfall.com requests. With the default burst of one
 * token, requests are spaced at least 1000 / rate ms apart, so no one-second
 * window ever holds more than `rate` requests. Queues that share a bucket
 * share that budget.
 */
export class TokenBucket {
  readonly rate: number;
  readonly burst: number;
  private readonly now: () => number;
  private tokens: number;
  private refilledAt: number;

  constructor(opts: { ratePerSecond?: number; burst?: number; now?: () => number } = {}) {
    this.rate = opts.ratePerSecond ?? SCRYFALL_RATE_PER_SECOND;
    this.burst = opts.burst ?? 1;
    this.now = opts.now ?? (() => Date.now());
    this.tokens = this.burst;
    this.refilledAt = this.now();
  }

  private refill(): void {
    const now = this.now();
    this.tokens = Math.min(this.burst, this.tokens + ((now - this.refilledAt) * this.rate) / 1000);
    this.refilledAt = now;
  }

  get available(): boolean {
    this.refill();
    return this.tokens >= 1;
  }

  /** Takes a token when one is available. */
  take(): boolean {
    this.refill();
    if (this.tokens < 1) return false;
    this.tokens -= 1;
    return true;
  }

  /** Milliseconds until the next token. */
  waitMs(): number {
    this.refill();
    return Math.max(1, Math.ceil(((1 - this.tokens) * 1000) / this.rate));
  }
}

/**
 * The one bucket every replay page's queue uses in the app, so the 8/s
 * budget holds across page instances (a quick replay -> replay navigation
 * keeps the old queue's last requests and the new queue's first ones apart).
 */
export const scryfallRateLimiter = new TokenBucket();

export interface ImageQueueOptions {
  maxInFlight?: number;
  /** Sustained api.scryfall.com requests per second (private bucket only). */
  ratePerSecond?: number;
  /** Requests allowed back to back before throttling starts (private bucket only). */
  burst?: number;
  /** Shared bucket; when omitted the queue gets a private one from the options above. */
  limiter?: TokenBucket;
  now?: () => number;
  schedule?: ScheduleFn;
  /** Defaults to `scryfallFetch`, which holds the name and search lookups to Scryfall's 2 per second. */
  fetch?: FetchFn;
  resolve?: ImageResolver;
}

interface Task {
  url: string;
  priority: number;
  order: number;
  limited: boolean;
  promise: Promise<string>;
  resolve: (url: string) => void;
  reject: (error: Error) => void;
}

const defaultSchedule: ScheduleFn = (callback, ms) => {
  const id = setTimeout(callback, ms);
  return () => clearTimeout(id);
};

export class ImageQueue {
  private readonly maxInFlight: number;
  private readonly limiter: TokenBucket;
  private readonly schedule: ScheduleFn;
  private readonly resolver: ImageResolver;
  private readonly tasks = new Map<string, Task>();
  private readonly done = new Map<string, string>();
  private readonly failed = new Map<string, Error>();
  private queue: Task[] = [];
  private active = 0;
  private order = 0;
  private wake: CancelTimer | null = null;

  constructor(opts: ImageQueueOptions = {}) {
    this.maxInFlight = opts.maxInFlight ?? 6;
    this.limiter =
      opts.limiter ?? new TokenBucket({ ratePerSecond: opts.ratePerSecond, burst: opts.burst, now: opts.now });
    this.schedule = opts.schedule ?? defaultSchedule;
    this.resolver = opts.resolve ?? scryfallResolver(opts.fetch ?? scryfallFetch);
  }

  get inFlight(): number {
    return this.active;
  }

  get pending(): number {
    return this.queue.length;
  }

  /** Resolves to the final URL. Higher `priority` runs first (visible cards). */
  load(url: string, priority = 0): Promise<string> {
    const resolved = this.done.get(url);
    if (resolved) return Promise.resolve(resolved);
    const error = this.failed.get(url);
    if (error) return Promise.reject(error);
    const existing = this.tasks.get(url);
    if (existing) {
      existing.priority = Math.max(existing.priority, priority);
      return existing.promise;
    }
    let resolve!: (value: string) => void;
    let reject!: (reason: Error) => void;
    const promise = new Promise<string>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    const task: Task = { url, priority, order: this.order++, limited: isRateLimitedUrl(url), promise, resolve, reject };
    this.tasks.set(url, task);
    this.queue.push(task);
    this.pump();
    return promise;
  }

  /** Rejects everything not yet started (for example when the page unmounts). */
  cancelPending(): void {
    const queued = this.queue;
    this.queue = [];
    this.wake?.();
    this.wake = null;
    for (const task of queued) {
      this.tasks.delete(task.url);
      task.reject(new Error('Image load cancelled'));
    }
  }

  private pick(): Task | null {
    let best: Task | null = null;
    const limitedOk = this.limiter.available;
    for (const task of this.queue) {
      if (task.limited && !limitedOk) continue;
      if (!best || task.priority > best.priority || (task.priority === best.priority && task.order < best.order)) {
        best = task;
      }
    }
    return best;
  }

  private pump(): void {
    while (this.active < this.maxInFlight) {
      const task = this.pick();
      if (!task) break;
      if (task.limited && !this.limiter.take()) break;
      this.queue.splice(this.queue.indexOf(task), 1);
      this.start(task);
    }
    const throttled = this.active < this.maxInFlight && this.queue.some((task) => task.limited);
    if (throttled && !this.wake) {
      const ms = this.limiter.waitMs();
      this.wake = this.schedule(() => {
        this.wake = null;
        this.pump();
      }, ms);
    }
  }

  private start(task: Task): void {
    this.active += 1;
    this.resolver(task.url).then(
      (finalUrl) => {
        this.done.set(task.url, finalUrl);
        task.resolve(finalUrl);
      },
      (reason: unknown) => {
        const error = reason instanceof Error ? reason : new Error(String(reason));
        // Only "no such card" is final; rate limits and outages get another try later.
        if (error instanceof ImageLookupError && error.permanent) this.failed.set(task.url, error);
        task.reject(error);
      },
    ).finally(() => {
      this.active -= 1;
      this.tasks.delete(task.url);
      this.pump();
    });
  }
}

export const IMAGE_CACHE_KEY = 'mtga-replay-images-v1';
export const IMAGE_CACHE_LIMIT = 3000;

/** localStorage map of card key (plus `@large`) -> final image URL, oldest trimmed first. */
class ResolvedImageCache {
  private entries: Map<string, string> | null = null;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;

  private load(): Map<string, string> {
    if (this.entries) return this.entries;
    this.entries = new Map();
    try {
      const parsed: unknown = JSON.parse(localStorage.getItem(IMAGE_CACHE_KEY) ?? '{}');
      if (parsed && typeof parsed === 'object') {
        for (const [key, url] of Object.entries(parsed)) {
          if (typeof url === 'string' && url.startsWith('https://')) this.entries.set(key, url);
        }
      }
    } catch {
      // Best-effort cache.
    }
    return this.entries;
  }

  get(key: string): string | null {
    return this.load().get(key) ?? null;
  }

  set(key: string, url: string): void {
    const entries = this.load();
    if (entries.get(key) === url) return;
    entries.delete(key);
    entries.set(key, url);
    while (entries.size > IMAGE_CACHE_LIMIT) {
      entries.delete(entries.keys().next().value as string);
    }
    this.flushTimer ??= setTimeout(() => this.flush(), 250);
  }

  get size(): number {
    return this.load().size;
  }

  flush(): void {
    if (this.flushTimer) clearTimeout(this.flushTimer);
    this.flushTimer = null;
    try {
      localStorage.setItem(IMAGE_CACHE_KEY, JSON.stringify(Object.fromEntries(this.load())));
    } catch {
      // Best-effort cache.
    }
  }

  /** Drops the in-memory copy (tests) and optionally the stored one. */
  reset(clearStorage = false): void {
    if (this.flushTimer) clearTimeout(this.flushTimer);
    this.flushTimer = null;
    this.entries = null;
    if (clearStorage) {
      try {
        localStorage.removeItem(IMAGE_CACHE_KEY);
      } catch {
        // ignore
      }
    }
  }
}

export const resolvedImageCache = new ResolvedImageCache();

/**
 * Final image URL for a card, or null when Scryfall has no image for it (only
 * a generated face will do). Throws a retryable ImageLookupError when a lookup
 * went unanswered, so the caller can try again later.
 */
export async function resolveCardImage(
  key: CardKey,
  card: ReplayCard,
  queue: ImageQueue,
  opts: { size?: ImageSize; priority?: number } = {},
): Promise<string | null> {
  const size = opts.size ?? 'normal';
  // A token with its exact printing gets its own entry: older pages cached the
  // wrong card's art for tokens (a Warrior token showed Furious Forebear).
  const base = card.is_token && card.token_print ? `${key}~${card.token_print}` : key;
  const cacheKey = size === 'normal' ? base : `${base}@large`;
  const cached = resolvedImageCache.get(cacheKey);
  if (cached) return cached;
  let retryable = false;
  for (const url of cardImageCandidates(card, size)) {
    try {
      const finalUrl = await queue.load(url, opts.priority ?? 0);
      resolvedImageCache.set(cacheKey, finalUrl);
      return finalUrl;
    } catch (error) {
      // Try the next candidate.
      if (!(error instanceof ImageLookupError && error.permanent)) retryable = true;
    }
  }
  if (retryable) throw new ImageLookupError('Scryfall did not answer every lookup; try again later', false);
  return null;
}

const generatedFaces = new Map<string, HTMLCanvasElement>();

/** Shared generated face (name, type, P/T) for cards with no image anywhere. */
export function generatedTokenFace(card: ReplayCard): HTMLCanvasElement {
  const key = [card.name, card.type_line, card.power, card.toughness, card.color_identity, card.is_token].join('|');
  let canvas = generatedFaces.get(key);
  if (!canvas) {
    canvas = createTokenFaceCanvas(card);
    generatedFaces.set(key, canvas);
  }
  return canvas;
}
