import { describe, expect, it } from 'vitest';
import type { ManagedCard } from './deckManagerApi';
import { compareDecks, sortCards } from './deckCompare';

const card = (quantity: number, name: string, section = 'Deck'): ManagedCard =>
  ({ section, quantity, name, arena_id: null, set_code: null, collector_number: null });

describe('compareDecks', () => {
  it('splits each section into cards only in one deck and cards in both', () => {
    const result = compareDecks(
      [card(4, 'Lightning Bolt'), card(20, 'Mountain'), card(2, 'Negate', 'Sideboard')],
      [card(2, 'Lightning Bolt'), card(20, 'Mountain'), card(2, 'Shock')],
    );
    expect(result.sections.map((s) => s.section)).toEqual(['Deck', 'Sideboard']);
    const [deck, side] = result.sections;
    expect(deck.onlyA).toEqual([{ name: 'Lightning Bolt', a: 4, b: 2 }]);
    expect(deck.onlyB).toEqual([{ name: 'Shock', a: 0, b: 2 }]);
    expect(deck.shared.map((c) => c.name)).toEqual(['Lightning Bolt', 'Mountain']);
    expect(side.onlyA).toEqual([{ name: 'Negate', a: 2, b: 0 }]);
    expect(result).toMatchObject({ onlyA: 4, onlyB: 2, shared: 22, identical: false });
    // Sideboards don't count: 22 shared of the larger 24-card main deck.
    expect(result.similarity).toBeCloseTo(22 / 24);
  });

  it('adds up separate printings and ignores letter case', () => {
    const result = compareDecks([card(2, 'Shock'), card(2, 'shock')], [card(4, 'Shock')]);
    expect(result.identical).toBe(true);
    expect(result.similarity).toBe(1);
    expect(result.sections[0].shared).toEqual([{ name: 'Shock', a: 4, b: 4 }]);
  });

  it('orders commander first and reports empty lists without a similarity', () => {
    const result = compareDecks([card(1, 'Atraxa', 'Commander'), card(1, 'Forest')], [card(1, 'Forest')]);
    expect(result.sections.map((s) => s.section)).toEqual(['Commander', 'Deck']);
    expect(compareDecks([], []).similarity).toBeNull();
  });
});

describe('sortCards', () => {
  it('sorts spells by mana value with lands last', () => {
    const cards = ['Mountain', 'Fireball', 'Shock', 'Mystery card', 'Ancient Den'].map((name) => ({ name, a: 1, b: 0 }));
    const sorted = sortCards(cards, {
      Fireball: { mana_cost: '{X}{R}', mana_value: 1 }, Shock: { mana_cost: '{R}', mana_value: 1 },
      'Ancient Den': { type: 'Land' },
    });
    expect(sorted.map((c) => c.name)).toEqual(['Fireball', 'Shock', 'Mystery card', 'Ancient Den', 'Mountain']);
  });
});
