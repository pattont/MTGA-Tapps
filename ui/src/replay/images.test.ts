import { afterEach, describe, expect, it, vi } from 'vitest';
import { card } from './fixtures/streamBuilder';
import {
  IMAGE_CACHE_KEY,
  IMAGE_CACHE_LIMIT,
  ImageQueue,
  TokenBucket,
  cardImageCandidates,
  generatedTokenFace,
  resolveCardImage,
  resolvedImageCache,
  scryfallResolver,
  searchImageUrl,
  tokenSearchCandidates,
} from './images';

const API = 'https://api.scryfall.com/cards';

/** Most requests started inside any half-open one-second window. */
function maxInAnySecond(times: number[]): number {
  let max = 0;
  for (const start of times) {
    max = Math.max(max, times.filter((t) => t >= start && t < start + 1000).length);
  }
  return max;
}
const CDN = 'https://cards.scryfall.io/normal/front/a/b/x.jpg';
const TOKEN_CDN = 'https://cards.scryfall.io/normal/front/t/t/token.jpg';

class FakeTime {
  now = 0;
  timers: Array<{ at: number; cb: () => void; id: number }> = [];
  private id = 0;
  schedule = (cb: () => void, ms: number) => {
    const id = this.id++;
    this.timers.push({ at: this.now + ms, cb, id });
    return () => {
      this.timers = this.timers.filter((t) => t.id !== id);
    };
  };
  async advance(ms: number): Promise<void> {
    const end = this.now + ms;
    for (;;) {
      await flush();
      this.timers.sort((a, b) => a.at - b.at);
      const due = this.timers[0];
      if (!due || due.at > end) break;
      this.timers.shift();
      this.now = due.at;
      due.cb();
    }
    this.now = end;
    await flush();
  }
}

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

function okResponse(url: string): Response {
  return { ok: true, status: 200, url } as Response;
}

afterEach(() => {
  resolvedImageCache.reset(true);
  vi.restoreAllMocks();
});

describe('cardImageCandidates', () => {
  it('prefers the direct link, then the Arena id, then the front-face name', () => {
    const dfc = card('Delver of Secrets // Insectile Aberration', 'Creature', { arena_id: 77, image_url: CDN });
    expect(cardImageCandidates(dfc, 'normal')).toEqual([
      CDN,
      `${API}/arena/77?format=image&version=normal`,
      `${API}/named?exact=Delver%20of%20Secrets&format=image&version=normal`,
    ]);
    expect(cardImageCandidates(dfc, 'large')[0]).toBe(CDN.replace('/normal/', '/large/'));
  });

  it('asks for the back image of a back face', () => {
    const back = card('Summon: Esper Maduin', 'Creature', { arena_id: 96052, back_face: true });
    expect(cardImageCandidates(back, 'normal')).toEqual([
      `${API}/arena/96052?format=image&version=normal&face=back`,
      `${API}/named?exact=Summon%3A%20Esper%20Maduin&format=image&version=normal&face=back`,
    ]);
  });

  it('searches the token sets for tokens, never the named lookup, and nothing for unknown cards', () => {
    const treasure = cardImageCandidates(card('Treasure', 'Artifact', { is_token: true }), 'normal');
    expect(treasure).toEqual([
      `${API}/search?unique=art&order=released&dir=desc&q=${encodeURIComponent('t:token !"Treasure" -is:dfc')}#size=normal`,
    ]);
    expect(cardImageCandidates(card('Unknown card', 'Unknown'), 'normal')).toEqual([]);
    const saproling = cardImageCandidates(card('Saproling', 'Creature', { is_token: true, arena_id: 5 }), 'normal');
    expect(saproling[0]).toBe(`${API}/arena/5?format=image&version=normal`);
    expect(saproling).toHaveLength(2);
    expect(saproling.some((url) => url.includes('/named?'))).toBe(false);
  });
});

describe('tokenSearchCandidates', () => {
  it('pins power, toughness and colors first, then falls back to the name alone', () => {
    const soldier = card('Soldier', 'Creature', { is_token: true, power: '1', toughness: '1', color_identity: 'W' });
    const urls = tokenSearchCandidates(soldier, 'large');
    expect(urls).toHaveLength(2);
    expect(decodeURIComponent(urls[0])).toContain('q=t:token !"Soldier" pow=1 tou=1 c=w -is:dfc');
    expect(urls[0].endsWith('#size=large')).toBe(true);
    expect(decodeURIComponent(urls[1])).toContain('q=t:token !"Soldier" -is:dfc');
    expect(tokenSearchCandidates(card('Unknown card', 'Unknown', { is_token: true }), 'normal')).toEqual([]);
    // "*" power (Treefolk tokens etc.) is not a Scryfall number: leave it out.
    expect(tokenSearchCandidates(card('Treefolk', 'Creature', { is_token: true, power: '*', toughness: '4' }), 'normal')).toHaveLength(2);
  });
});

describe('searchImageUrl', () => {
  it('reads the first hit at the fragment size, front face first', () => {
    const body = { data: [{ image_uris: { normal: 'n.jpg', large: 'l.jpg' } }] };
    expect(searchImageUrl('x#size=large', body)).toBe('l.jpg');
    expect(searchImageUrl('x#size=normal', body)).toBe('n.jpg');
    expect(searchImageUrl('x#size=large', { data: [{ card_faces: [{ image_uris: { normal: 'f.jpg' } }] }] })).toBe('f.jpg');
    expect(searchImageUrl('x#size=large', { data: [] })).toBeNull();
    expect(searchImageUrl('x#size=large', null)).toBeNull();
  });
});

describe('scryfallResolver', () => {
  it('reads the final URL from a HEAD request and falls back to GET on 405', async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) =>
      init?.method === 'HEAD' ? ({ ok: false, status: 405, url: '' } as Response) : okResponse(CDN),
    );
    const resolve = scryfallResolver(fetchMock as unknown as typeof fetch);
    await expect(resolve(`${API}/arena/1?format=image&version=normal`)).resolves.toBe(CDN);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await expect(resolve(CDN)).resolves.toBe(CDN);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('resolves a token search from its JSON and marks 404 as permanent, 429 as retryable', async () => {
    const search = `${API}/search?q=${encodeURIComponent('t:token !"Insect"')}#size=normal`;
    const fetchMock = vi.fn<(url: RequestInfo | URL) => Promise<Response>>(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ data: [{ image_uris: { normal: CDN } }] }),
    }) as unknown as Response);
    const resolve = scryfallResolver(fetchMock as unknown as typeof fetch);
    await expect(resolve(search)).resolves.toBe(CDN);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(search);

    const notFound = scryfallResolver((async () => ({ ok: false, status: 404 }) as Response) as unknown as typeof fetch);
    await expect(resolve404(notFound, search)).resolves.toMatchObject({ permanent: true });
    const limited = scryfallResolver((async () => ({ ok: false, status: 429 }) as Response) as unknown as typeof fetch);
    await expect(resolve404(limited, `${API}/arena/1?format=image&version=normal`)).resolves.toMatchObject({ permanent: false });
  });
});

async function resolve404(resolve: (url: string) => Promise<string>, url: string): Promise<unknown> {
  try {
    await resolve(url);
    return null;
  } catch (error) {
    return error;
  }
}

describe('ImageQueue', () => {
  it('dedupes concurrent requests for the same URL', async () => {
    const fetchMock = vi.fn(async () => okResponse(CDN));
    const queue = new ImageQueue({ fetch: fetchMock as unknown as typeof fetch });
    const url = `${API}/arena/1?format=image&version=normal`;
    const [a, b] = await Promise.all([queue.load(url), queue.load(url)]);
    expect(a).toBe(CDN);
    expect(b).toBe(CDN);
    await expect(queue.load(url)).resolves.toBe(CDN);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('caps requests in flight at six', async () => {
    const pending: Array<() => void> = [];
    const fetchMock = vi.fn(
      (url: RequestInfo | URL) => new Promise<Response>((resolve) => pending.push(() => resolve(okResponse(String(url))))),
    );
    const queue = new ImageQueue({ fetch: fetchMock as unknown as typeof fetch, burst: 100 });
    const loads = Array.from({ length: 20 }, (_, i) => queue.load(`${API}/arena/${i}?format=image`));
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(queue.inFlight).toBe(6);
    expect(queue.pending).toBe(14);
    pending.shift()?.();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(7);
    while (pending.length) {
      pending.shift()?.();
      await flush();
    }
    await Promise.all(loads);
    expect(queue.inFlight).toBe(0);
  });

  it('throttles api.scryfall.com to one request every 125 ms (eight per second)', async () => {
    const time = new FakeTime();
    const calledAt: number[] = [];
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
      calledAt.push(time.now);
      return okResponse(String(url));
    });
    const queue = new ImageQueue({ fetch: fetchMock as unknown as typeof fetch, now: () => time.now, schedule: time.schedule });
    const loads = Array.from({ length: 10 }, (_, i) => queue.load(`${API}/arena/${i}?format=image`));
    await time.advance(2000);
    await Promise.all(loads);
    expect(calledAt).toEqual([0, 125, 250, 375, 500, 625, 750, 875, 1000, 1125]);
    expect(maxInAnySecond(calledAt)).toBeLessThanOrEqual(8);
  });

  it('keeps two queues that share a bucket under eight per second combined', async () => {
    const time = new FakeTime();
    const calledAt: number[] = [];
    const resolve = vi.fn(async (url: string) => {
      calledAt.push(time.now);
      return url;
    });
    const limiter = new TokenBucket({ now: () => time.now });
    const a = new ImageQueue({ resolve, limiter, now: () => time.now, schedule: time.schedule });
    const b = new ImageQueue({ resolve, limiter, now: () => time.now, schedule: time.schedule });
    const loads = Array.from({ length: 24 }, (_, i) => (i % 2 ? a : b).load(`${API}/arena/${i}?format=image`));
    await time.advance(4000);
    await Promise.all(loads);
    expect(calledAt).toHaveLength(24);
    expect(maxInAnySecond(calledAt)).toBeLessThanOrEqual(8);
  });

  it('does not throttle the CDN', async () => {
    const time = new FakeTime();
    const resolve = vi.fn(async (url: string) => url);
    const queue = new ImageQueue({ resolve, now: () => time.now, schedule: time.schedule, burst: 1 });
    await Promise.all(Array.from({ length: 30 }, (_, i) => queue.load(`https://cards.scryfall.io/normal/${i}.jpg`)));
    expect(resolve).toHaveBeenCalledTimes(30);
    expect(time.now).toBe(0);
  });

  it('runs higher-priority requests first', async () => {
    const order: string[] = [];
    const resolve = vi.fn(async (url: string) => {
      order.push(url);
      return url;
    });
    const queue = new ImageQueue({ resolve, maxInFlight: 1 });
    const loads = [queue.load('https://cards.scryfall.io/a'), queue.load('https://cards.scryfall.io/b'), queue.load('https://cards.scryfall.io/c', 5)];
    await Promise.all(loads);
    expect(order).toEqual(['https://cards.scryfall.io/a', 'https://cards.scryfall.io/c', 'https://cards.scryfall.io/b']);
  });

  it('rejects queued work on cancel', async () => {
    const queue = new ImageQueue({ resolve: () => new Promise(() => undefined), maxInFlight: 1 });
    void queue.load('https://cards.scryfall.io/a');
    const queued = queue.load('https://cards.scryfall.io/b');
    queue.cancelPending();
    await expect(queued).rejects.toThrow('cancelled');
  });
});

describe('resolveCardImage', () => {
  it('falls through failed candidates and caches the final URL per card key', async () => {
    const fetchMock = vi.fn(async (url: RequestInfo | URL) =>
      String(url).includes('/arena/')
        ? ({ ok: false, status: 404, url: '' } as Response)
        : String(url).includes('/search?')
          ? ({ ok: true, status: 200, json: async () => ({ data: [{ image_uris: { normal: TOKEN_CDN } }] }) } as unknown as Response)
          : okResponse(CDN),
    );
    const queue = new ImageQueue({ fetch: fetchMock as unknown as typeof fetch, burst: 10 });
    const bears = card('Grizzly Bears', 'Creature', { arena_id: 9 });
    await expect(resolveCardImage('a9', bears, queue)).resolves.toBe(CDN);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolvedImageCache.flush();
    expect(JSON.parse(localStorage.getItem(IMAGE_CACHE_KEY) ?? '{}')).toEqual({ a9: CDN });
    resolvedImageCache.reset();
    await expect(resolveCardImage('a9', bears, queue)).resolves.toBe(CDN);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // Tokens: one search (name only, nothing to pin) answers with the token's own art.
    await expect(resolveCardImage('n:Treasure', card('Treasure', 'Artifact', { is_token: true }), queue)).resolves.toBe(TOKEN_CDN);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[2][0])).toContain('/search?');
  });

  it('retries a rate-limited lookup on the next request but not a missing card', async () => {
    let status = 429;
    const fetchMock = vi.fn(async () => ({ ok: false, status, url: '' }) as Response);
    const queue = new ImageQueue({ fetch: fetchMock as unknown as typeof fetch, burst: 10 });
    const url = `${API}/arena/42?format=image&version=normal`;
    await expect(queue.load(url)).rejects.toThrow('429');
    status = 404;
    await expect(queue.load(url)).rejects.toThrow('404');
    await expect(queue.load(url)).rejects.toThrow('404');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('trims the cache to its size limit, oldest first', () => {
    for (let i = 0; i < IMAGE_CACHE_LIMIT + 5; i += 1) resolvedImageCache.set(`a${i}`, `${CDN}?${i}`);
    expect(resolvedImageCache.size).toBe(IMAGE_CACHE_LIMIT);
    expect(resolvedImageCache.get('a0')).toBeNull();
    expect(resolvedImageCache.get(`a${IMAGE_CACHE_LIMIT + 4}`)).toBe(`${CDN}?${IMAGE_CACHE_LIMIT + 4}`);
  });

  it('ignores corrupt or throwing storage', () => {
    localStorage.setItem(IMAGE_CACHE_KEY, '{oops');
    expect(resolvedImageCache.get('a1')).toBeNull();
    resolvedImageCache.reset();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    resolvedImageCache.set('a1', CDN);
    expect(() => resolvedImageCache.flush()).not.toThrow();
    expect(resolvedImageCache.get('a1')).toBe(CDN);
  });
});

describe('generatedTokenFace', () => {
  it('returns one shared canvas per distinct face', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const token = card('Saproling', 'Creature', { is_token: true, power: '1', toughness: '1' });
    expect(generatedTokenFace(token)).toBe(generatedTokenFace({ ...token }));
    expect(generatedTokenFace(token).width).toBe(488);
  });
});
