import { describe, expect, it } from 'vitest';
import { buildSections, isSingleton, landDanger, libraryNotice, manaSymbols, oddsTone, oddsWithin, shortFormat, sortRows, typeClass, unseenCount } from '../model';
import { drawStatus, landZones } from '../floodMeter';
import { brawlState, inGameState } from './fixtures';

describe('oddsWithin', () => {
  it('matches the hypergeometric formula from overlay_state.py', () => {
    expect(oddsWithin(4, 40, 1)).toBeCloseTo(0.1, 6);
    expect(oddsWithin(4, 40, 2)).toBeCloseTo(1 - (36 / 40) * (35 / 39), 6);
    expect(oddsWithin(0, 40, 3)).toBe(0);
    expect(oddsWithin(40, 40, 1)).toBe(1);
    expect(oddsWithin(3, 2, 1)).toBe(1);
  });
});

describe('buildSections', () => {
  it('puts spells first and groups lands into Basic / Nonbasic by default', () => {
    const sections = buildSections(inGameState(), 'odds', 'grouped');
    expect(sections.spells.every((r) => r.type_category !== 'Land')).toBe(true);
    expect(sections.lands.map((r) => r.name)).toEqual(['Basic lands', 'Nonbasic lands']);
    expect(sections.lands[0].left).toBe(8);
    expect(sections.lands[0].total).toBe(16);
    expect(sections.lands[1].left).toBe(3);
    expect(sections.drawn).toEqual([]);
  });

  it('takes grouped land odds over the cards not seen to leave when some left unseen', () => {
    // 24 cards milled in a message Arena only summarized: 21 left of a pool of 45.
    const state = { ...inGameState(), library_size: 21, unseen: 24, draw_pool: 45 };
    const [basic] = buildSections(state, 'odds', 'grouped').lands;
    expect(basic.left).toBe(8);
    expect(basic.odds['1']).toBeCloseTo(17.8, 1); // 8 in 45, not 8 in 21
    // Never more draws than the library holds.
    const last = buildSections({ ...state, library_size: 1 }, 'odds', 'grouped').lands[0];
    expect(last.odds['3']).toBe(last.odds['1']);
  });

  it('lists every land when asked', () => {
    const sections = buildSections(inGameState(), 'name', 'all');
    expect(sections.lands.map((r) => r.name)).toEqual(['Mountain', 'Rockface Village']);
  });

  it('keeps exhausted rows in place for 60-card decks', () => {
    const sections = buildSections(inGameState(), 'odds', 'grouped');
    const shock = sections.spells.find((r) => r.name === 'Shock');
    expect(shock?.left).toBe(0);
    expect(sections.spells[sections.spells.length - 1].name).toBe('Shock');
  });

  it('moves drawn singletons to the Drawn group in Brawl', () => {
    const sections = buildSections(brawlState(), 'odds', 'grouped');
    expect(sections.drawn.map((r) => r.name)).toEqual(['Arcane Signet', 'Sol Ring', 'Swords to Plowshares']);
    expect(sections.spells.some((r) => r.left === 0)).toBe(false);
  });

  it('sorts by odds, mana value, then name', () => {
    const rows = buildSections(inGameState(), 'mana', 'grouped').spells;
    const values = rows.map((r) => r.mana_value ?? 0);
    expect(values).toEqual([...values].sort((a, b) => a - b));
    const byName = sortRows(rows, 'name').map((r) => r.name);
    expect(byName).toEqual([...byName].sort((a, b) => a.localeCompare(b)));
    const byOdds = sortRows(rows, 'odds').map((r) => r.odds['1']);
    expect(byOdds).toEqual([...byOdds].sort((a, b) => b - a));
  });
});

describe('libraryNotice', () => {
  it('says nothing while every card is accounted for', () => {
    expect(unseenCount(inGameState())).toBe(0);
    expect(libraryNotice(inGameState())).toBeNull();
  });

  it('says how many cards left unseen and that counts are ceilings', () => {
    const state = { ...inGameState(), unseen: 24, log_gap: true };
    expect(unseenCount(state)).toBe(24);
    expect(libraryNotice(state)).toBe("24 cards left your library and Arena's log didn't name them. Counts show the most that can be left.");
    expect(libraryNotice({ ...state, unseen: 1 })).toContain("1 card left your library and Arena's log didn't name it.");
  });

  it('warns after a summarized message until the library is listed again', () => {
    expect(libraryNotice({ ...inGameState(), log_gap: true })).toBe("Arena's log skipped a large move. Counts may be out of date until your next draw.");
  });
});

describe('isSingleton', () => {
  it('is true with a commander or a 99+ card all-singleton list', () => {
    expect(isSingleton(inGameState())).toBe(false);
    expect(isSingleton(brawlState())).toBe(true);
    expect(isSingleton({ ...brawlState(), player_commanders: [] })).toBe(true);
  });
});

describe('labels', () => {
  it('abbreviates the format the way the header wants it', () => {
    expect(shortFormat('Standard Best-of-1 (Ranked)')).toBe('Std. BO1 Ranked');
    expect(shortFormat('Historic Brawl')).toBe('Hist. Brawl');
    expect(shortFormat('Premier Draft Best-of-1')).toBe('Ltd. BO1');
    expect(shortFormat(null)).toBe('');
  });

  it('tones odds and flags land danger', () => {
    expect(oddsTone(12)).toBe('hot');
    expect(oddsTone(7)).toBe('warm');
    expect(oddsTone(2)).toBe('cold');
    const state = inGameState();
    expect(landDanger({ ...state, land_odds: { '1': 20, '2': 30, '3': 40 } }, 2)).toBe(true);
    expect(landDanger({ ...state, land_odds: { '1': 20, '2': 30, '3': 40 } }, 5)).toBe(false);
    expect(landDanger(state, 2)).toBe(false);
  });

  it('splits mana costs into symbols and maps types to classes', () => {
    expect(manaSymbols('{1}{B}{B}')).toEqual(['1', 'B', 'B']);
    expect(manaSymbols('{W/U}{X}')).toEqual(['W/U', 'X']);
    expect(manaSymbols(null)).toEqual([]);
    expect(typeClass('Legendary Creature')).toBe('creature');
    expect(typeClass('Enchantment')).toBe('ench');
    expect(typeClass(undefined)).toBe('other');
  });
});

describe('flood meter numbers (a copy of the Stream Kit Lands widget\'s)', () => {
  it('marks ≤10 % tails as screw and flood, like draw_quality', () => {
    // 10 cards from 60 with 24 lands: 1 land or fewer is screw, 7 or more flood.
    expect(landZones(60, 24, 10)).toEqual({ screwMax: 1, floodMin: 7 });
  });

  it('names the status in the dashboard\'s order', () => {
    expect(drawStatus({ is_flood: true, is_screw: true, is_land_streak: true })).toBe('flood');
    expect(drawStatus({ is_flood: false, is_screw: true, is_land_streak: true })).toBe('screw');
    expect(drawStatus({ is_flood: false, is_screw: false, is_land_streak: true })).toBe('streak');
    expect(drawStatus({ is_flood: false, is_screw: false, is_land_streak: false })).toBe('normal');
  });
});
