import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  lookupPaperPrices, paperLookupName, resetPaperPriceCache, type PaperLookupProgress, type PaperPriceMap,
} from './cardPrices';
import { resetScryfallQueue } from './scryfallQueue';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const card = (name: string, extra: Record<string, unknown> = {}) => ({
  name, set: 'fdn', set_name: 'Foundations', collector_number: '10', games: ['paper', 'arena'],
  prices: { usd: '1.50', usd_foil: '3.00' }, ...extra,
});

describe('paperLookupName', () => {
  it('maps rebalanced and double-faced Arena names to the paper lookup name', () => {
    expect(paperLookupName('A-Sorcerous Squall')).toEqual({ name: 'Sorcerous Squall', rebalanced: true });
    expect(paperLookupName('Fable of the Mirror-Breaker // Reflection of Kiki-Jiki'))
      .toEqual({ name: 'Fable of the Mirror-Breaker', rebalanced: false });
  });
});

describe('lookupPaperPrices', () => {
  const store = new Map<string, string>();

  beforeEach(() => {
    resetPaperPriceCache();
    resetScryfallQueue();
    store.clear();
    vi.useFakeTimers();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('prices first, then finds every card’s cheapest printing in one paged search', async () => {
    const searches: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/cards/collection')) {
        return json({
          data: [
            card('Opt'), card('Sorcerous Squall'), card('Forest', { prices: { usd: '0.10' } }),
            card('Fable of the Mirror-Breaker // Reflection of Kiki-Jiki', { prices: { usd: '6.00' } }),
            card('Alchemy Thing', { games: ['arena'], prices: {} }),
          ],
          not_found: [{ name: 'Not A Card' }],
        });
      }
      if (url.includes('page=2')) {
        return json({ data: [card('Fable of the Mirror-Breaker // Reflection of Kiki-Jiki', { set: 'neo', prices: { usd: '5.10' } })], has_more: false });
      }
      const query = new URL(url).searchParams.get('q') ?? '';
      searches.push(query);
      if (query.includes('Forest')) {
        return json({ data: [card('Forest', { set: 'm21', prices: { usd: '0.02' } })], has_more: false });
      }
      return json({
        data: [
          card('Opt', { set: 'xln', set_name: 'Ixalan', collector_number: '65', prices: { usd: '0.15' } }),
          card('Opt', { prices: { usd: '0.25' } }),
          card('Sorcerous Squall', { prices: { usd: '0.40' } }),
        ],
        has_more: true,
        next_page: 'https://api.scryfall.com/cards/search?page=2',
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const updates: [PaperPriceMap, PaperLookupProgress][] = [];

    const names = ['Opt', 'A-Sorcerous Squall', 'Forest', 'Fable of the Mirror-Breaker', 'Alchemy Thing', 'Not A Card'];
    const done = lookupPaperPrices(names, (map, progress) => updates.push([map, progress]));
    await vi.runAllTimersAsync();
    const result = await done;

    expect(updates[0][0].get('Opt')).toBeNull();
    expect(updates[1][0].get('Opt')?.printing?.usd).toBe(1.5);

    // One search for every non-basic card (two pages), then one for basics.
    expect(searches).toEqual([
      '(!"Opt" or !"Sorcerous Squall" or !"Fable of the Mirror-Breaker // Reflection of Kiki-Jiki" or !"Alchemy Thing" or !"Not A Card") game:paper lang:en -is:oversized -set_type:memorabilia',
      '(!"Forest") game:paper lang:en -is:oversized -set_type:memorabilia',
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(4);

    expect(result.get('Opt')).toMatchObject({ status: 'paper', cheapest: true, printing: { set: 'XLN', usd: 0.15 } });
    expect(result.get('A-Sorcerous Squall')).toMatchObject({ status: 'paper', name: 'Sorcerous Squall', rebalanced: true });
    expect(result.get('Fable of the Mirror-Breaker')).toMatchObject({ printing: { set: 'NEO', usd: 5.1 } });
    expect(result.get('Forest')).toMatchObject({ status: 'paper', cheapest: true, printing: { set: 'M21', usd: 0.02 } });
    expect(result.get('Alchemy Thing')).toMatchObject({ status: 'digital_only', printing: null });
    expect(result.get('Not A Card')).toMatchObject({ status: 'not_found' });
    expect(updates.at(-1)?.[1]).toEqual({ pending: 0, interrupted: false });
    expect(store.get('mtga-tracker-paper-prices-v1')).toContain('Ixalan');

    // A second lookup is served from the cache.
    fetchMock.mockClear();
    resetPaperPriceCache();
    const cached = await lookupPaperPrices(['Opt'], () => {});
    expect(cached.get('Opt')?.printing?.usd).toBe(0.15);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('spaces Scryfall requests and stops, keeping first prices, when a search fails', async () => {
    const times: number[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      times.push(Date.now());
      if (String(input).endsWith('/cards/collection')) return json({ data: [card('Opt')] });
      throw new TypeError('Failed to fetch'); // How a CORS-less 429 looks in a browser.
    }));
    const updates: PaperLookupProgress[] = [];
    const done = lookupPaperPrices(['Opt'], (_map, progress) => updates.push(progress));
    await vi.runAllTimersAsync();
    const result = await done;
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(550);
    expect(result.get('Opt')).toMatchObject({ status: 'paper', cheapest: false, printing: { usd: 1.5 } });
    expect(updates.at(-1)).toEqual({ pending: 0, interrupted: true });
    expect(store.get('mtga-tracker-paper-prices-v1')).toBe('{}');
  });
});
