import { describe, expect, it } from 'vitest';
import type { PaperCardInfo, PaperPriceMap } from './cardPrices';
import {
  applyStorePrices, buildCart, isBasicLand, managedDeckSections, paperDeckFromSections, withoutPrices, type BoardId,
} from './paperDeck';

const paper = (name: string, usd: number | null, set = 'FDN'): PaperCardInfo => ({
  status: 'paper', name, rebalanced: false, cheapest: true,
  printing: { set, set_name: 'Foundations', collector_number: '1', usd, finish: usd === null ? null : 'nonfoil' },
});

const allBoards = new Set<BoardId>(['commander', 'companion', 'main', 'sideboard']);

describe('paperDeckFromSections', () => {
  it('maps import sections to boards, merges repeats and orders commander first', () => {
    const rows = paperDeckFromSections([
      { name: 'Deck', cards: [{ quantity: 2, name: 'Opt' }, { quantity: 1, name: 'Opt' }, { quantity: 20, name: 'Island' }] },
      { name: 'Sideboard', cards: [{ quantity: 2, name: 'Negate' }] },
      { name: 'Commander', cards: [{ quantity: 1, name: 'Niv-Mizzet, Parun' }] },
    ]);
    expect(rows.map((row) => [row.board, row.quantity, row.name])).toEqual([
      ['commander', 1, 'Niv-Mizzet, Parun'],
      ['main', 3, 'Opt'],
      ['main', 20, 'Island'],
      ['sideboard', 2, 'Negate'],
    ]);
  });

  it('reads Deck Manager card rows', () => {
    const sections = managedDeckSections({ deck: { cards: [
      { section: 'Deck', quantity: 4, name: 'Opt' },
      { section: 'Sideboard', quantity: 1, name: 'Negate' },
      { section: 'Deck', quantity: 2, name: 'Island' },
    ] } });
    expect(sections).toEqual([
      { name: 'Deck', cards: [{ quantity: 4, name: 'Opt' }, { quantity: 2, name: 'Island' }] },
      { name: 'Sideboard', cards: [{ quantity: 1, name: 'Negate' }] },
    ]);
  });
});

describe('buildCart', () => {
  const rows = paperDeckFromSections([
    { name: 'Deck', cards: [
      { quantity: 4, name: 'Opt' }, { quantity: 2, name: 'Negate' }, { quantity: 10, name: 'Island' },
      { quantity: 2, name: 'Alchemy Only' }, { quantity: 1, name: 'Mystery Card' },
    ] },
    { name: 'Sideboard', cards: [{ quantity: 2, name: 'Negate' }] },
  ]);
  const prices: PaperPriceMap = new Map<string, PaperCardInfo | null>([
    ['Opt', paper('Opt', 0.25)],
    ['Negate', paper('Negate', 0.1)],
    ['Island', paper('Island', null)],
    ['Alchemy Only', { status: 'digital_only', name: 'Alchemy Only', printing: null, rebalanced: false, cheapest: true }],
    ['Mystery Card', null],
  ]);

  it('totals known prices, merges boards and leaves out Arena-only cards', () => {
    const cart = buildCart(rows, prices, { boards: allBoards, excluded: new Set(), skipBasics: false });
    expect(cart.total).toBe(1.4); // 4 × 0.25 + 4 × 0.10
    expect(cart.cardCount).toBe(19);
    expect(cart.unpricedCount).toBe(11); // Islands + the card whose lookup failed
    expect(cart.unavailableCount).toBe(2);
    expect(cart.lines).toEqual([
      { name: 'Opt', quantity: 4, set: 'FDN', collector_number: '1' },
      { name: 'Negate', quantity: 4, set: 'FDN', collector_number: '1' },
      { name: 'Island', quantity: 10, set: 'FDN', collector_number: '1' },
      { name: 'Mystery Card', quantity: 1, set: null, collector_number: null },
    ]);
  });

  it('updates with boards, row toggles and the basic-land option', () => {
    const cart = buildCart(rows, prices, {
      boards: new Set<BoardId>(['main']), excluded: new Set(['main:opt']), skipBasics: true,
    });
    expect(cart.total).toBe(0.2);
    expect(cart.lines.map((line) => [line.name, line.quantity])).toEqual([['Negate', 2], ['Mystery Card', 1]]);
  });
});

describe('store prices', () => {
  const rows = paperDeckFromSections([{ name: 'Deck', cards: [
    { quantity: 4, name: 'Opt' }, { quantity: 2, name: 'Negate' }, { quantity: 2, name: 'Alchemy Only' },
  ] }]);
  const scryfall: PaperPriceMap = new Map<string, PaperCardInfo | null>([
    ['Opt', paper('Opt', 0.25)],
    ['Negate', paper('Negate', 0.5)],
    ['Alchemy Only', { status: 'digital_only', name: 'Alchemy Only', printing: null, rebalanced: false, cheapest: true }],
  ]);
  const names = ['Opt', 'Negate', 'Alchemy Only'];
  const options = { boards: allBoards, excluded: new Set<string>(), skipBasics: false };

  it('never fills a card the store doesn’t list with another store’s price', () => {
    const store = new Map([['Opt', {
      name: 'Opt', usd: 0.1, set: 'DOM', set_name: 'Dominaria', collector_number: '60',
      finish: 'nonfoil' as const, in_stock: true, url: null,
    }]]);
    const prices = applyStorePrices(names, scryfall, store);
    expect(prices.get('Negate')).toMatchObject({ status: 'paper', printing: null, not_listed: true });
    const cart = buildCart(rows, prices, options);
    expect(cart.total).toBe(0.4);
    expect(cart.pricedCount).toBe(4);
    expect(cart.notListedCount).toBe(2);
    expect(cart.unpricedCount).toBe(2);
    expect(cart.unavailableCount).toBe(2);
    expect(cart.lines.map((line) => line.name)).toEqual(['Opt', 'Negate']);
  });

  it('has no prices at all for a store without a price list', () => {
    const cart = buildCart(rows, withoutPrices(names, scryfall), options);
    expect(cart.total).toBe(0);
    expect(cart.pricedCount).toBe(0);
    expect(cart.cardCount).toBe(6);
    expect(cart.unavailableCount).toBe(2);
  });
});

describe('isBasicLand', () => {
  it('knows basics and snow basics', () => {
    expect(isBasicLand('Forest')).toBe(true);
    expect(isBasicLand('Snow-Covered Island')).toBe(true);
    expect(isBasicLand('Wastes')).toBe(true);
    expect(isBasicLand('Breeding Pool')).toBe(false);
  });
});
