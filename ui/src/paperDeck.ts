/**
 * Deck → paper shopping cart for the Buy on Paper dialog. Pure functions:
 * the dialog owns the state, these turn it into rows, totals and the list
 * handed to a store.
 */

import type { ImportSection } from './deckFinderImport';
import type { PaperCardInfo, PaperPriceMap } from './cardPrices';

export type BoardId = 'commander' | 'companion' | 'main' | 'sideboard' | 'maybeboard';

export const BOARD_ORDER: BoardId[] = ['commander', 'companion', 'main', 'sideboard', 'maybeboard'];

export const BOARD_LABELS: Record<BoardId, string> = {
  commander: 'Commander',
  companion: 'Companion',
  main: 'Main Deck',
  sideboard: 'Sideboard',
  maybeboard: 'Maybeboard',
};

/** Boards that start selected. A maybeboard isn't part of the deck. */
export const DEFAULT_BOARDS: BoardId[] = ['commander', 'companion', 'main', 'sideboard'];

const SECTION_BOARDS: Record<string, BoardId> = {
  deck: 'main', main: 'main', 'main deck': 'main', mainboard: 'main',
  sideboard: 'sideboard', commander: 'commander', companion: 'companion', maybeboard: 'maybeboard',
};

export interface PaperDeckCard {
  /** Stable row id: board + Arena name. */
  key: string;
  board: BoardId;
  quantity: number;
  /** The name as Arena knows it. */
  name: string;
}

/** Sections from an Arena import list or Deck Manager → one row per card per board. */
export function paperDeckFromSections(sections: ImportSection[]): PaperDeckCard[] {
  const rows = new Map<string, PaperDeckCard>();
  for (const section of sections) {
    const board = SECTION_BOARDS[section.name.trim().toLowerCase()] ?? 'main';
    for (const card of section.cards) {
      const name = card.name.trim();
      if (!name || card.quantity < 1) continue;
      const key = `${board}:${name.toLowerCase()}`;
      const existing = rows.get(key);
      if (existing) existing.quantity += card.quantity;
      else rows.set(key, { key, board, quantity: card.quantity, name });
    }
  }
  return BOARD_ORDER.flatMap((board) => Array.from(rows.values()).filter((row) => row.board === board));
}

/** A Deck Manager revision's cards, grouped the way an import list is. */
export function managedDeckSections(detail: { deck: { cards: { section: string; quantity: number; name: string }[] } }): ImportSection[] {
  const sections = new Map<string, ImportSection>();
  for (const card of detail.deck.cards) {
    const section = sections.get(card.section) ?? { name: card.section, cards: [] };
    section.cards.push({ quantity: card.quantity, name: card.name });
    sections.set(card.section, section);
  }
  return Array.from(sections.values());
}

const BASICS = new Set(['plains', 'island', 'swamp', 'mountain', 'forest', 'wastes']);

export function isBasicLand(name: string): boolean {
  const lower = name.trim().toLowerCase();
  return BASICS.has(lower) || BASICS.has(lower.replace(/^snow-covered /u, ''));
}

/** Can this card be bought in paper? Unknown (lookup failed) counts as yes. */
export function isBuyable(info: PaperCardInfo | null | undefined): boolean {
  return !info || info.status === 'paper';
}

export interface CartLine {
  /** Paper name when known, else the Arena name (the store gets to try). */
  name: string;
  quantity: number;
  set: string | null;
  collector_number: string | null;
}

export interface CartOptions {
  boards: ReadonlySet<BoardId>;
  /** Row keys the user switched off. */
  excluded: ReadonlySet<string>;
  skipBasics: boolean;
}

export interface CartSummary {
  lines: CartLine[];
  /** Copies going to the store. */
  cardCount: number;
  /** Sum of known prices for those copies. */
  total: number;
  /** Copies going to the store without a known price. */
  unpricedCount: number;
  /** Selected copies left out because they have no paper printing. */
  unavailableCount: number;
}

export function rowSelected(row: PaperDeckCard, options: CartOptions): boolean {
  return options.boards.has(row.board)
    && !options.excluded.has(row.key)
    && !(options.skipBasics && isBasicLand(row.name));
}

/** The cart for the current selection. Copies of one card across boards merge into one line. */
export function buildCart(rows: PaperDeckCard[], prices: PaperPriceMap, options: CartOptions): CartSummary {
  const lines = new Map<string, CartLine>();
  let total = 0;
  let cardCount = 0;
  let unpricedCount = 0;
  let unavailableCount = 0;
  for (const row of rows) {
    if (!rowSelected(row, options)) continue;
    const info = prices.get(row.name) ?? null;
    if (!isBuyable(info)) {
      unavailableCount += row.quantity;
      continue;
    }
    cardCount += row.quantity;
    const usd = info?.printing?.usd ?? null;
    if (usd === null) unpricedCount += row.quantity;
    else total += usd * row.quantity;
    const name = info?.name ?? row.name;
    const existing = lines.get(name.toLowerCase());
    if (existing) {
      existing.quantity += row.quantity;
    } else {
      lines.set(name.toLowerCase(), {
        name,
        quantity: row.quantity,
        set: info?.printing?.set || null,
        collector_number: info?.printing?.collector_number || null,
      });
    }
  }
  return {
    lines: Array.from(lines.values()),
    cardCount,
    total: Math.round(total * 100) / 100,
    unpricedCount,
    unavailableCount,
  };
}

export function formatUsd(value: number): string {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}
