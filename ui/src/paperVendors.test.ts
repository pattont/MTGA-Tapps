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

const shippedAffiliate = { ...AFFILIATE };

afterEach(() => {
  Object.assign(AFFILIATE, shippedAffiliate);
  vi.unstubAllGlobals();
});

/** Mana Pool's add-deck encoding: URL-safe base64, no padding. */
const decodeDeck = (value: string) => {
  const standard = value.replace(/-/gu, '+').replace(/_/gu, '/');
  const bytes = Uint8Array.from(atob(standard), (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
};

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
    expect(decodeDeck(pool.searchParams.get('deck')!)).toBe('4 Fable of the Mirror-Breaker\n2 Lightning Bolt');
    // The shipped referral code rides along as `ref`, after the deck.
    expect([...pool.searchParams.keys()]).toEqual(['deck', 'ref']);
    expect(pool.searchParams.get('ref')).toBe('tappstracker');
    AFFILIATE.manapool = '';
    expect(link('manapool').searchParams.has('ref')).toBe(false);
  });

  it('encodes Mana Pool decks the way its affiliate instructions show', () => {
    const deck = (cards: CartLine[]) => {
      const built = vendorById('manapool')!.buildRequest(cards, { setCodes: false });
      if (built.kind !== 'link') throw new Error('expected a link');
      return new URL(built.url).searchParams.get('deck');
    };
    const card = (name: string, quantity: number): CartLine => ({ name, quantity, set: null, collector_number: null });
    // Their example: "4 Plains [M20] 261" -> deck=NCBQbGFpbnMgW00yMF0gMjYx (a plain name here).
    expect(deck([card('Plains [M20] 261', 4)])).toBe('NCBQbGFpbnMgW00yMF0gMjYx');
    // Standard base64 would be ...YWw/CjQg...IEJvbHQ= : "/" becomes "_" and padding goes.
    expect(deck([card('Question Elemental?', 1), card('Lightning Bolt', 4)])).toBe(
      'MSBRdWVzdGlvbiBFbGVtZW50YWw_CjQgTGlnaHRuaW5nIEJvbHQ',
    );
    // Non-ASCII names survive as UTF-8.
    expect(decodeDeck(deck([card('Jötun Grunt', 2)])!)).toBe('2 Jötun Grunt');
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
