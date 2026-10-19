import { describe, expect, it } from 'vitest';
import type { PaperCardInfo, PaperPriceMap } from './cardPrices';
import { buildCart, isBasicLand, managedDeckSections, paperDeckFromSections, type BoardId } from './paperDeck';

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

describe('isBasicLand', () => {
  it('knows basics and snow basics', () => {
    expect(isBasicLand('Forest')).toBe(true);
    expect(isBasicLand('Snow-Covered Island')).toBe(true);
    expect(isBasicLand('Wastes')).toBe(true);
    expect(isBasicLand('Breeding Pool')).toBe(false);
  });
});
