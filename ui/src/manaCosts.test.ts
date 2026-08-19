import { describe, expect, it, vi } from 'vitest';
import {
  fetchManaCosts,
  frontFaceName,
  manaCostSymbols,
  manaSymbolClass,
  playedManaStats,
  seedManaCosts,
  type CardManaInfo,
} from './manaCosts';

describe('manaCostSymbols', () => {
  it('splits a cost into individual symbols', () => {
    expect(manaCostSymbols('{2}{G}{G}')).toEqual(['{2}', '{G}', '{G}']);
    expect(manaCostSymbols('{X}{B/P}{U}')).toEqual(['{X}', '{B/P}', '{U}']);
    expect(manaCostSymbols('')).toEqual([]);
  });
});

describe('manaSymbolClass', () => {
  it('maps every symbol shape to its mana-font class', () => {
    expect(manaSymbolClass('{G}')).toBe('ms-g');
    expect(manaSymbolClass('{10}')).toBe('ms-10');
    expect(manaSymbolClass('{X}')).toBe('ms-x');
    // Hybrid, twobrid, Phyrexian, hybrid-Phyrexian, colorless-hybrid, snow.
    expect(manaSymbolClass('{G/U}')).toBe('ms-gu');
    expect(manaSymbolClass('{2/W}')).toBe('ms-2w');
    expect(manaSymbolClass('{B/P}')).toBe('ms-bp');
    expect(manaSymbolClass('{G/W/P}')).toBe('ms-gwp');
    expect(manaSymbolClass('{C/B}')).toBe('ms-cb');
    expect(manaSymbolClass('{S}')).toBe('ms-s');
  });
});

describe('seedManaCosts', () => {
  it('serves seeded server costs without touching the network', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {} });
    const fetchSpy = vi.fn(async () => {
      throw new Error('offline');
    });
    vi.stubGlobal('fetch', fetchSpy);
    seedManaCosts({
      'Unholy Annex // Ritual Chamber': { mana_cost: '{1}{B}{B}', mana_value: 3 },
      Swamp: { mana_cost: '', mana_value: 0 },
    });

    const map = await fetchManaCosts(['Unholy Annex // Ritual Chamber', 'Swamp']);

    expect(map.get('Unholy Annex // Ritual Chamber')).toEqual({ mana_cost: '{1}{B}{B}', cmc: 3 });
    expect(map.get('Swamp')).toEqual({ mana_cost: '', cmc: 0 });
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe('frontFaceName', () => {
  it('keeps only the front face of split names', () => {
    expect(frontFaceName('Fire // Ice')).toBe('Fire');
    expect(frontFaceName('Mountain')).toBe('Mountain');
  });
});

describe('playedManaStats', () => {
  const mana = new Map<string, CardManaInfo | null>([
    ['Cheap Rat', { mana_cost: '{B}', cmc: 1 }],
    ['Big Ogre', { mana_cost: '{4}{R}{R}', cmc: 6 }],
    ['Swamp', { mana_cost: '', cmc: 0 }],
    ['Mystery Card', null],
  ]);

  it('averages mana value per played card, weighted by play count', () => {
    const stats = playedManaStats(
      [
        { display_name: 'Cheap Rat', type_category: 'Creature', count: 3 },
        { display_name: 'Big Ogre', type_category: 'Creature', count: 1 },
      ],
      mana,
      9,
    );
    // (3*1 + 1*6) / 4 plays = 2.3; 9 total mana over 9 turns = 1.
    expect(stats.avg_per_card).toBe(2.3);
    expect(stats.per_turn).toBe(1);
  });

  it('excludes lands and unresolved cards from both stats', () => {
    const stats = playedManaStats(
      [
        { display_name: 'Swamp', type_category: 'Land', count: 8 },
        { display_name: 'Mystery Card', type_category: 'Creature', count: 2 },
        { display_name: 'Cheap Rat', type_category: 'Creature', count: 2 },
      ],
      mana,
      4,
    );
    expect(stats.avg_per_card).toBe(1);
    expect(stats.per_turn).toBe(0.5);
  });

  it('returns nulls with no known plays or no turn count', () => {
    expect(playedManaStats([], mana, 10)).toEqual({ avg_per_card: null, per_turn: null });
    expect(
      playedManaStats([{ display_name: 'Cheap Rat', type_category: 'Creature', count: 1 }], mana, null),
    ).toEqual({ avg_per_card: 1, per_turn: null });
  });
});
