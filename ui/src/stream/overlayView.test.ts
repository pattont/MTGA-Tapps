import { describe, expect, it } from 'vitest';
import { DEMO_OVERLAY } from './demo';
import { deckColors, oddsTone, overlaySections, shortFormat, showsLibrary, tintAlpha } from './overlayView';
import type { OverlayState } from './types';

const demo = DEMO_OVERLAY.state!;

describe('overlay view helpers', () => {
  it('maps the background slider the way the in-game overlay does', () => {
    expect(tintAlpha(0)).toBe(0);
    expect(tintAlpha(100)).toBe(0.88);
    expect(tintAlpha(60)).toBeCloseTo(0.717, 3);
    expect(tintAlpha(250)).toBe(0.88);
  });

  it('shortens format labels and reads deck colours from costs', () => {
    expect(shortFormat('Standard (Ranked)')).toBe('Std. Ranked');
    expect(shortFormat('Historic Brawl')).toBe('Hist. Brawl');
    expect(shortFormat(null)).toBe('');
    expect(deckColors([{ mana_cost: '{1}{G}' }, { mana_cost: '{W/U}' }, { mana_cost: null }])).toBe('WUG');
  });

  it('tones odds like the overlay', () => {
    expect(oddsTone(12)).toBe('hot');
    expect(oddsTone(6)).toBe('warm');
    expect(oddsTone(2)).toBe('cold');
  });

  it('keeps lands apart and counts drawn singleton cards', () => {
    const { spells, lands, drawn } = overlaySections(demo, 'mana');
    expect(spells.some((row) => row.typeClass === 'land')).toBe(false);
    expect(lands.map((row) => row.name)).toEqual(['Fabled Passage', 'Forest']);
    expect(drawn).toBe(0);

    const brawl: OverlayState = {
      ...demo,
      player_commanders: ['Wilhelt, the Rotcleaver'],
      cards: [
        { ...demo.cards[0], name: 'Gravecrawler', total: 1, left: 0 },
        { ...demo.cards[0], name: 'Diregraf Ghoul', total: 1, left: 1 },
      ],
    };
    const sections = overlaySections(brawl, 'name');
    expect(sections.spells.map((row) => row.name)).toEqual(['Diregraf Ghoul']);
    expect(sections.drawn).toBe(1);
  });

  it('shows a library only in a game or on its results screen', () => {
    expect(showsLibrary(demo)).toBe(true);
    expect(showsLibrary({ ...demo, game_active: false, game_over: true })).toBe(true);
    expect(showsLibrary({ ...demo, game_active: false })).toBe(false);
    expect(showsLibrary({ ...demo, mid_game_attach: true })).toBe(false);
    expect(showsLibrary(null)).toBe(false);
  });
});
