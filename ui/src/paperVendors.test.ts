import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CartLine } from './paperDeck';
import { AFFILIATE, PAPER_VENDORS, openVendorRequest, selectableVendor, vendorById } from './paperVendors';

const lines: CartLine[] = [
  { name: 'Fable of the Mirror-Breaker // Reflection of Kiki-Jiki', quantity: 4, set: 'NEO', collector_number: '141' },
  { name: 'Lightning Bolt', quantity: 2, set: null, collector_number: null },
];

const request = (id: string, setCodes = false) => vendorById(id)!.buildRequest(lines, { setCodes });
const link = (id: string, setCodes = false) => {
  const built = request(id, setCodes);
  if (built.kind !== 'link') throw new Error('expected a link');
  return new URL(built.url);
};

afterEach(() => {
  AFFILIATE.tcgplayer = '';
  AFFILIATE.cardkingdom = '';
  AFFILIATE.manapool = '';
  vi.unstubAllGlobals();
});

describe('paper store requests', () => {
  it('lists every store once, alphabetically, with its bundled icon', () => {
    expect(PAPER_VENDORS.map((vendor) => vendor.name)).toEqual(['Card Kingdom', 'CoolStuffInc', 'Mana Pool', 'StarCityGames', 'TCGplayer']);
    // Stores without their own price list never borrow another store's prices.
    expect(vendorById('starcitygames')!.priceSource).toBeNull();
    expect(vendorById('coolstuffinc')!.priceSource).toBeNull();
    // ...and can't be chosen until there's a way to price them.
    expect(PAPER_VENDORS.filter((vendor) => vendor.comingSoon).map((vendor) => vendor.id)).toEqual(['coolstuffinc', 'starcitygames']);
    expect(selectableVendor('starcitygames')).toBeUndefined();
    expect(selectableVendor('tcgplayer')?.id).toBe('tcgplayer');
    PAPER_VENDORS.forEach((vendor) => expect(vendor.icon).toMatch(/\/stores\/[a-z]+\.(png|ico)$/u));
  });

  it('builds TCGplayer Mass Entry, with set codes on request and the Impact wrapper when configured', () => {
    expect(link('tcgplayer').searchParams.get('c')).toBe('4 Fable of the Mirror-Breaker||2 Lightning Bolt');
    expect(link('tcgplayer', true).searchParams.get('c')).toBe('4 Fable of the Mirror-Breaker [NEO] 141||2 Lightning Bolt');

    AFFILIATE.tcgplayer = 'https://partner.tcgplayer.com/c/123/1830156/21018';
    const wrapped = link('tcgplayer');
    expect(wrapped.origin + wrapped.pathname).toBe('https://partner.tcgplayer.com/c/123/1830156/21018');
    const target = new URL(wrapped.searchParams.get('u')!);
    expect(target.origin + target.pathname).toBe('https://store.tcgplayer.com/massentry');
    expect(target.searchParams.get('c')).toBe('4 Fable of the Mirror-Breaker||2 Lightning Bolt');
  });

  it('builds Card Kingdom and Mana Pool links, adding partner codes only when set', () => {
    const plain = link('cardkingdom');
    expect(plain.searchParams.get('c')).toBe('4 Fable of the Mirror-Breaker\n2 Lightning Bolt');
    expect(plain.searchParams.has('partner')).toBe(false);
    AFFILIATE.cardkingdom = 'tapps';
    expect(link('cardkingdom').searchParams.get('partner')).toBe('tapps');

    const pool = link('manapool');
    expect(pool.origin + pool.pathname).toBe('https://manapool.com/add-deck');
    expect(atob(pool.searchParams.get('deck')!)).toBe('4 Fable of the Mirror-Breaker\n2 Lightning Bolt');
    expect(pool.searchParams.has('ref')).toBe(false);
    AFFILIATE.manapool = 'TAPPS';
    expect(link('manapool').searchParams.get('ref')).toBe('TAPPS');
  });

  it('copies the list, then opens stores that cannot take it in a link', async () => {
    const order: string[] = [];
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async (text: string) => { order.push(`copy:${text}`); }) } });
    const open = vi.spyOn(window, 'open').mockImplementation((url) => { order.push(`open:${String(url)}`); return null; });

    const built = request('starcitygames');
    expect(await openVendorRequest(built)).toEqual({ copied: true });
    expect(order).toEqual([
      'copy:4 Fable of the Mirror-Breaker\n2 Lightning Bolt',
      'open:https://starcitygames.com/shop/deck-builder/',
    ]);
    expect(await openVendorRequest(request('tcgplayer'))).toEqual({ copied: null });
    expect(open).toHaveBeenCalledTimes(2);
    open.mockRestore();
  });
});
