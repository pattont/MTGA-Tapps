/** Pure view-model helpers for the panel: grouping, sorting, labels, odds. */

import type { OverlayCard, OverlayState, SortKey } from './types';

export interface Row {
  key: string;
  name: string;
  type_category: string;
  mana_cost: string | null;
  mana_value: number | null;
  total: number;
  left: number;
  odds: Record<'1' | '2' | '3', number>;
  /** An aggregate row (Basic lands / Nonbasic lands). */
  group?: 'basic' | 'nonbasic';
}

export const TYPE_ORDER = ['Creature', 'Planeswalker', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Battle', 'Land', 'Other'];

export function typeClass(type: string | null | undefined): string {
  const t = (type || 'Other').toLowerCase();
  if (t.includes('creature')) return 'creature';
  if (t.includes('instant')) return 'instant';
  if (t.includes('sorcery')) return 'sorcery';
  if (t.includes('enchant')) return 'ench';
  if (t.includes('artifact')) return 'artifact';
  if (t.includes('planeswalker')) return 'walker';
  if (t.includes('land')) return 'land';
  return 'other';
}

/** Hypergeometric "at least one in N draws" — the same formula as overlay_state.py. */
export function oddsWithin(copies: number, library: number, draws: number): number {
  if (copies <= 0 || library <= 0 || draws <= 0) return 0;
  if (copies >= library) return 1;
  const n = Math.min(draws, library);
  const misses = library - copies;
  if (misses < n) return 1;
  // C(misses, n) / C(library, n) computed as a running product to avoid big factorials.
  let ratio = 1;
  for (let i = 0; i < n; i += 1) {
    ratio *= (misses - i) / (library - i);
  }
  return 1 - ratio;
}

function pct(value: number): number {
  return Math.round(value * 1000) / 10;
}

function aggregate(key: 'basic' | 'nonbasic', label: string, cards: OverlayCard[], library: number): Row | null {
  if (cards.length === 0) return null;
  const left = cards.reduce((sum, c) => sum + c.left, 0);
  const total = cards.reduce((sum, c) => sum + c.total, 0);
  return {
    key: `group:${key}`,
    name: label,
    type_category: 'Land',
    mana_cost: null,
    mana_value: 0,
    total,
    left,
    odds: { '1': pct(oddsWithin(left, library, 1)), '2': pct(oddsWithin(left, library, 2)), '3': pct(oddsWithin(left, library, 3)) },
    group: key,
  };
}

function toRow(card: OverlayCard): Row {
  return {
    key: card.name,
    name: card.name,
    type_category: card.type_category,
    mana_cost: card.mana_cost,
    mana_value: card.mana_value,
    total: card.total,
    left: card.left,
    odds: card.odds,
  };
}

export function sortRows(rows: Row[], sort: SortKey): Row[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    if (sort === 'odds') {
      if (b.odds['1'] !== a.odds['1']) return b.odds['1'] - a.odds['1'];
    } else if (sort === 'mana') {
      const am = a.mana_value ?? Number.POSITIVE_INFINITY;
      const bm = b.mana_value ?? Number.POSITIVE_INFINITY;
      if (am !== bm) return am - bm;
    }
    return a.name.localeCompare(b.name);
  });
  return copy;
}

export interface Sections {
  spells: Row[];
  lands: Row[];
  /** Singleton formats: cards fully drawn move here instead of dimming in place. */
  drawn: Row[];
}

/**
 * Spells first, then lands. Exhausted rows stay in place (dimmed) in
 * 60-card formats; in singleton formats (Brawl) they move to a collapsed
 * "Drawn" group so the visible list shrinks as the game goes.
 */
export function buildSections(state: OverlayState, sort: SortKey, lands: 'grouped' | 'all'): Sections {
  const singleton = isSingleton(state);
  const spells: Row[] = [];
  const drawn: Row[] = [];
  const landCards: OverlayCard[] = [];
  for (const card of state.cards) {
    if (card.land) {
      landCards.push(card);
      continue;
    }
    const row = toRow(card);
    if (singleton && card.left === 0) drawn.push(row);
    else spells.push(row);
  }
  let landRows: Row[];
  if (lands === 'grouped') {
    landRows = [
      aggregate('basic', 'Basic lands', landCards.filter((c) => c.basic), state.library_size),
      aggregate('nonbasic', 'Nonbasic lands', landCards.filter((c) => !c.basic), state.library_size),
    ].filter((row): row is Row => row !== null);
  } else {
    landRows = sortRows(landCards.map(toRow), sort);
  }
  return { spells: sortRows(spells, sort), lands: landRows, drawn: sortRows(drawn, 'name') };
}

export function isSingleton(state: OverlayState): boolean {
  if (state.player_commanders.length > 0) return true;
  if (state.deck_size >= 99) {
    // Every non-basic card at one copy is the other tell for a singleton list.
    const nonBasic = state.cards.filter((c) => !c.basic);
    return nonBasic.length > 0 && nonBasic.every((c) => c.total === 1);
  }
  return false;
}

/** "Std. BO1 Ranked" — abbreviated so "Ranked" always fits the header line. */
export function shortFormat(label: string | null | undefined): string {
  if (!label) return '';
  let text = label
    .replace(/Best-of-(\d)/i, 'BO$1')
    .replace(/\(Ranked\)/i, 'Ranked')
    .replace(/\(Unranked\)/i, '')
    .replace(/Standard/i, 'Std.')
    .replace(/Historic Brawl/i, 'Hist. Brawl')
    .replace(/Historic/i, 'Hist.')
    .replace(/Modern/i, 'Mod.')
    .replace(/Pioneer/i, 'Pio.')
    .replace(/Timeless/i, 'Time.')
    .replace(/Limited|Premier Draft|Quick Draft|Sealed/i, 'Ltd.')
    .replace(/\s+/g, ' ')
    .trim();
  return text;
}

/** Whether the panel has a library to show: live, or frozen on the results screen. */
export function showsLibrary(state: OverlayState | null | undefined): boolean {
  return Boolean(state && !state.mid_game_attach && state.cards.length > 0 && (state.game_active || state.game_over));
}

export function oddsTone(value: number): 'hot' | 'warm' | 'cold' {
  if (value >= 10) return 'hot';
  if (value >= 5) return 'warm';
  return 'cold';
}

/** Land number goes to the danger tone: under 25% with fewer than four lands in play. */
export function landDanger(state: OverlayState, landsInPlay: number | null): boolean {
  return state.land_odds['1'] < 25 && (landsInPlay ?? 0) < 4 && state.library_size > 0;
}

/** Odds are shown as whole percentages everywhere: "27%", never "26.8%". */
export function formatPct(value: number): string {
  return `${Math.round(value)}%`;
}

export const formatWhole = formatPct;

/** Break "{1}{B}{B}" into symbols; hybrid "{W/U}" stays one symbol. */
export function manaSymbols(cost: string | null | undefined): string[] {
  if (!cost) return [];
  const out: string[] = [];
  for (const match of cost.matchAll(/\{([^}]+)\}/g)) out.push(match[1]);
  return out;
}
