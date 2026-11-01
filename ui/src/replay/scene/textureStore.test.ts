import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { card } from '../fixtures/streamBuilder';
import { ImageLookupError, ImageQueue, resolvedImageCache, scryfallRateLimiter } from '../images';
import { TextureStore, UNKNOWN_CARD, VISIBLE_PRIORITY } from './textureStore';

const cards = {
  a1: card('Forest', 'Land', { image_url: 'https://cards.scryfall.io/normal/front/a/1/forest.jpg' }),
  a2: card('Bear', 'Creature', { image_url: 'https://cards.scryfall.io/normal/front/b/2/bear.jpg' }),
  a3: card('Elf', 'Creature', { image_url: 'https://cards.scryfall.io/normal/front/c/3/elf.jpg' }),
  'n:Treasure': card('Treasure', 'Artifact', { is_token: true }),
  [UNKNOWN_CARD]: card('Unknown card', 'Unknown'),
};

function deferred() {
  const pending = new Map<string, (value: TexImageSource) => void>();
  const loadImage = vi.fn(
    (url: string) =>
      new Promise<TexImageSource>((resolve) => {
        pending.set(url, resolve);
      }),
  );
  return { pending, loadImage };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('TextureStore', () => {
  beforeEach(() => {
    resolvedImageCache.reset(true);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });
  afterEach(() => vi.restoreAllMocks());

  it('loads visible cards first and caps concurrent image loads', async () => {
    const { pending, loadImage } = deferred();
    const store = new TextureStore(cards, { loadImage, maxConcurrent: 2, queue: new ImageQueue({ resolve: async (u) => u }) });
    store.request(new Map([['a1', 1], ['a2', VISIBLE_PRIORITY], ['a3', 2]]));
    await flush();
    expect(loadImage.mock.calls.map(([url]) => url)).toEqual([
      'https://cards.scryfall.io/normal/front/b/2/bear.jpg',
      'https://cards.scryfall.io/normal/front/c/3/elf.jpg',
    ]);
    expect(store.inFlight).toBe(2);
    pending.get('https://cards.scryfall.io/normal/front/b/2/bear.jpg')!(document.createElement('canvas'));
    await flush();
    expect(loadImage).toHaveBeenCalledTimes(3);
    expect(store.face('a2')).not.toBeNull();
    expect(store.face('a1')).toBeNull();
    store.dispose();
  });

  it('notifies subscribers once per batch and serves large previews from the CDN', async () => {
    const { pending, loadImage } = deferred();
    const store = new TextureStore(cards, { loadImage, queue: new ImageQueue({ resolve: async (u) => u }) });
    const listener = vi.fn();
    store.subscribe(listener);
    store.request(new Map([['a1', VISIBLE_PRIORITY]]));
    await flush();
    pending.get('https://cards.scryfall.io/normal/front/a/1/forest.jpg')!(document.createElement('canvas'));
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.previewUrlNow('a1')).toBe('https://cards.scryfall.io/large/front/a/1/forest.jpg');
    expect(store.previewUrlNow(UNKNOWN_CARD)).toBeNull();
    store.dispose();
  });

  it('uses a generated face for tokens without images and when loading fails', async () => {
    const loadImage = vi.fn(async () => {
      throw new Error('offline');
    });
    const store = new TextureStore(cards, { loadImage, queue: new ImageQueue({ resolve: async (u) => u }) });
    store.request(new Map([['n:Treasure', 1], ['a1', 1], [UNKNOWN_CARD, 3]]));
    expect(store.face('n:Treasure')).not.toBeNull();
    await flush();
    await flush();
    expect(store.face('a1')).not.toBeNull();
    // Unknown cards never load anything: the scene draws a "?" sleeve.
    expect(store.face(UNKNOWN_CARD)).toBeNull();
    store.dispose();
  });

  it('shows a token as its procedural face at once, then the printed token art from the search', async () => {
    const { pending, loadImage } = deferred();
    const art = 'https://cards.scryfall.io/normal/front/t/t/treasure.jpg';
    const resolve = vi.fn(async (url: string) => (url.includes('/search?') ? art : url));
    const store = new TextureStore(cards, { loadImage, queue: new ImageQueue({ resolve }) });
    store.request(new Map([['n:Treasure', VISIBLE_PRIORITY]]));
    const generated = store.face('n:Treasure');
    expect(generated).not.toBeNull();
    await flush();
    await flush();
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(decodeURIComponent(resolve.mock.calls[0][0])).toContain('t:token !"Treasure"');
    pending.get(art)!(document.createElement('canvas'));
    await flush();
    expect(store.face('n:Treasure')).not.toBe(generated);
    expect(store.resolvedUrl('n:Treasure')).toBe(art);
    store.dispose();
  });

  it('shows a named placeholder when a visible card is slow, then the real image', async () => {
    vi.useFakeTimers();
    const { pending, loadImage } = deferred();
    const store = new TextureStore(cards, {
      loadImage,
      placeholderDelayMs: 100,
      queue: new ImageQueue({ resolve: async (u) => u }),
    });
    store.request(new Map([['a2', VISIBLE_PRIORITY]]));
    await vi.advanceTimersByTimeAsync(150);
    const placeholder = store.face('a2');
    expect(placeholder).not.toBeNull();
    pending.get('https://cards.scryfall.io/normal/front/b/2/bear.jpg')!(document.createElement('canvas'));
    await vi.advanceTimersByTimeAsync(10);
    expect(store.face('a2')).not.toBe(placeholder);
    store.dispose();
    vi.useRealTimers();
  });

  it('survives a StrictMode release/retain and disposes after the last release', async () => {
    const store = new TextureStore(cards, { queue: new ImageQueue({ resolve: async (u) => u }) });
    const sleeve = store.sleeve('navy');
    const dispose = vi.spyOn(sleeve, 'dispose');
    expect(store.sleeve('navy')).toBe(sleeve);
    store.retain();
    store.release();
    store.retain();
    await flush();
    expect(store.isDisposed).toBe(false);
    store.release();
    await flush();
    expect(store.isDisposed).toBe(true);
    expect(dispose).toHaveBeenCalled();
  });

  it('shows the generated face while Scryfall is not answering, then retries the card', async () => {
    vi.useFakeTimers();
    const { pending, loadImage } = deferred();
    const art = 'https://cards.scryfall.io/normal/front/6/3/hortimancer.jpg';
    let online = false;
    const resolve = vi.fn(async (url: string) => {
      if (!online) throw new ImageLookupError('Failed to fetch', false);
      return url.includes('/fra/23?') ? art : url;
    });
    const store = new TextureStore(
      { a106248: card('Unflinching Hortimancer', 'Creature', { arena_id: 106248, print: 'fra/23' }) },
      { loadImage, queue: new ImageQueue({ resolve, burst: 10 }), retryDelaysMs: [1000] },
    );
    store.request(new Map([['a106248', VISIBLE_PRIORITY]]));
    await vi.advanceTimersByTimeAsync(10);
    const placeholder = store.face('a106248');
    expect(placeholder).not.toBeNull();
    online = true;
    await vi.advanceTimersByTimeAsync(1000);
    pending.get(art)!(document.createElement('canvas'));
    await vi.advanceTimersByTimeAsync(10);
    expect(store.face('a106248')).not.toBe(placeholder);
    expect(store.resolvedUrl('a106248')).toBe(art);
    store.dispose();
    vi.useRealTimers();
  });

  it('defaults to a queue on the app-wide Scryfall rate limiter', () => {
    const store = new TextureStore(cards);
    expect((store as unknown as { queue: { limiter: unknown } }).queue.limiter).toBe(scryfallRateLimiter);
    store.dispose();
  });

  it('resolves hover previews through its queue instead of handing out API URLs', async () => {
    const resolve = vi.fn(async () => 'https://cards.scryfall.io/large/front/x/y/goblin.jpg');
    const queue = new ImageQueue({ resolve });
    const apiOnly = { ...cards, a9: card('Goblin Guide', 'Creature', { arena_id: 9 }) };
    const store = new TextureStore(apiOnly, { queue });
    expect(store.previewUrlNow('a9')).toBeNull();
    await expect(store.resolvePreview('a9', 'Goblin Guide')).resolves.toBe('https://cards.scryfall.io/large/front/x/y/goblin.jpg');
    expect(resolve).toHaveBeenCalledWith(expect.stringContaining('api.scryfall.com/cards/arena/9'));
    // Cached as the card's large image: the next hover needs no lookup.
    expect(store.previewUrlNow('a9')).toBe('https://cards.scryfall.io/large/front/x/y/goblin.jpg');
    // Name-only hovers (log rows without a card key) also go through the queue.
    await store.resolvePreview(null, 'Lightning Bolt');
    expect(resolve).toHaveBeenLastCalledWith(expect.stringContaining('named?exact=Lightning+Bolt'));
    // A CDN image from the server is used directly.
    expect(store.previewUrlNow('a2')).toBe('https://cards.scryfall.io/large/front/b/2/bear.jpg');
    store.dispose();
  });
});
