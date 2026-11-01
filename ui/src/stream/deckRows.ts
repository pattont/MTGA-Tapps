/** Rows for the deck tracker widget, from the overlay's library state. */

import type { DeckSort } from './options';
import type { OverlayCard, OverlayState } from './types';

export interface DeckRow {
  key: string;
  name: string;
  /** creature / instant / sorcery / ench / artifact / walker / land / other */
  typeClass: string;
  mana_cost: string | null;
  left: number;
  total: number;
  /** Chance the next draw is this card, whole percent. */
  nextDraw: number;
}

export interface DeckSections {
  spells: DeckRow[];
  lands: DeckRow[];
}

export function typeClass(type: string | null | undefined): string {
  const t = (type || 'Other').toLowerCase();
  if (t.includes('creature')) return 'creature';
  if (t.includes('planeswalker')) return 'walker';
  if (t.includes('instant')) return 'instant';
  if (t.includes('sorcery')) return 'sorcery';
  if (t.includes('enchant')) return 'ench';
  if (t.includes('artifact')) return 'artifact';
  if (t.includes('land')) return 'land';
  return 'other';
}

function toRow(card: OverlayCard): DeckRow {
  return {
    key: card.name,
    name: card.name,
    typeClass: typeClass(card.land ? 'Land' : card.type_category),
    mana_cost: card.mana_cost,
    left: card.left,
    total: card.total,
    nextDraw: Math.round(card.odds?.['1'] ?? 0),
  };
}

function sortRows(rows: DeckRow[], sort: DeckSort, manaValue: Map<string, number>): DeckRow[] {
  return [...rows].sort((a, b) => {
    if (sort === 'odds' && b.nextDraw !== a.nextDraw) return b.nextDraw - a.nextDraw;
    if (sort === 'mana') {
      const am = manaValue.get(a.key) ?? Number.POSITIVE_INFINITY;
      const bm = manaValue.get(b.key) ?? Number.POSITIVE_INFINITY;
      if (am !== bm) return am - bm;
    }
    return a.name.localeCompare(b.name);
  });
}

/** Brawl and other 100-card singleton lists: a drawn card is gone for good. */
export function isSingleton(state: OverlayState): boolean {
  if (state.player_commanders.length > 0) return true;
  if (state.deck_size < 99) return false;
  const nonBasic = state.cards.filter((card) => !card.basic);
  return nonBasic.length > 0 && nonBasic.every((card) => card.total === 1);
}

/**
 * Spells first, then lands. In 60-card decks a card with no copies left stays
 * in place (the widget dims it); in singleton decks it drops out so the list
 * shrinks as the game goes. Grouped lands are one row from the tracker's own
 * land totals and odds.
 */
export function deckSections(state: OverlayState, sort: DeckSort, lands: 'grouped' | 'all'): DeckSections {
  const singleton = isSingleton(state);
  const manaValue = new Map(state.cards.map((card) => [card.name, card.mana_value ?? Number.POSITIVE_INFINITY]));
  const spells = state.cards.filter((card) => !card.land && !(singleton && card.left === 0)).map(toRow);
  let landRows: DeckRow[];
  if (lands === 'grouped') {
    landRows = state.lands_total > 0
      ? [
          {
            key: 'group:lands',
            name: 'Lands',
            typeClass: 'land',
            mana_cost: null,
            left: state.lands_left,
            total: state.lands_total,
            nextDraw: Math.round(state.land_odds?.['1'] ?? 0),
          },
        ]
      : [];
  } else {
    landRows = sortRows(
      state.cards.filter((card) => card.land && !(singleton && card.left === 0)).map(toRow),
      sort === 'mana' ? 'name' : sort,
      manaValue,
    );
  }
  return { spells: sortRows(spells, sort, manaValue), lands: landRows };
}
