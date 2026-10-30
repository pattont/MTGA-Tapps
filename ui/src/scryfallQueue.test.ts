import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ScryfallUnavailable, resetScryfallQueue, scryfallFetch } from './scryfallQueue';

describe('scryfallFetch', () => {
  beforeEach(() => {
    resetScryfallQueue();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('backs off for a minute after a 429 and leaves unlimited endpoints alone', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 429 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(scryfallFetch('https://api.scryfall.com/cards/search?q=x')).rejects.toBeInstanceOf(ScryfallUnavailable);
    await expect(scryfallFetch('https://api.scryfall.com/cards/collection')).rejects.toBeInstanceOf(ScryfallUnavailable);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    await scryfallFetch('https://api.scryfall.com/sets');
    expect(fetchMock).toHaveBeenCalledTimes(2);

    vi.advanceTimersByTime(60_000);
    const later = scryfallFetch('https://api.scryfall.com/cards/search?q=y');
    await vi.runAllTimersAsync();
    expect((await later).status).toBe(200);
  });
});
