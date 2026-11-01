import { describe, expect, it } from 'vitest';
import { deckSections, isSingleton } from './deckRows';
import { DEMO_OVERLAY } from './demo';
import type { OverlayCard, OverlayState } from './types';

const demo = DEMO_OVERLAY.state!;

function single(name: string, left: number, extra: Partial<OverlayCard> = {}): OverlayCard {
  return {
    name,
    type_category: 'Creature',
    mana_cost: '{1}{G}',
    mana_value: 2,
    total: 1,
    left,
    land: false,
    basic: false,
    odds: { '1': left, '2': left, '3': left },
    ...extra,
  };
}

describe('deckSections', () => {
  it('sorts spells by mana value, keeps exhausted cards, and groups lands', () => {
    const { spells, lands } = deckSections(demo, 'mana', 'grouped');
    expect(spells[0].name).toBe('Llanowar Elves');
    expect(spells.at(-1)?.name).toBe('Ouroboroid');
    const veil = spells.find((row) => row.name === 'Snakeskin Veil');
    expect(veil).toMatchObject({ left: 0, total: 4, typeClass: 'instant' });
    expect(lands).toEqual([
      { key: 'group:lands', name: 'Lands', typeClass: 'land', mana_cost: null, left: 15, total: 22, nextDraw: 33 },
    ]);
  });

  it('sorts by next-draw odds and lists lands one by one', () => {
    const { spells, lands } = deckSections(demo, 'odds', 'all');
    expect(spells[0].nextDraw).toBeGreaterThanOrEqual(spells[1].nextDraw);
    expect(lands.map((row) => row.name)).toEqual(['Forest', 'Fabled Passage']);
  });

  it('drops drawn cards from singleton lists', () => {
    const brawl: OverlayState = {
      ...demo,
      player_commanders: ['Wilhelt, the Rotcleaver'],
      deck_size: 99,
      cards: [single('Gravecrawler', 0), single('Diregraf Ghoul', 1)],
      lands_total: 0,
      lands_left: 0,
    };
    expect(isSingleton(brawl)).toBe(true);
    const { spells, lands } = deckSections(brawl, 'name', 'grouped');
    expect(spells.map((row) => row.name)).toEqual(['Diregraf Ghoul']);
    expect(lands).toEqual([]);
    expect(isSingleton(demo)).toBe(false);
  });
});
