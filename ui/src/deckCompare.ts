/** Card-by-card differences between two saved decklists, for Deck Manager's Compare dialog. */
import type { CardFacts, ManagedCard } from './deckManagerApi';

export interface ComparedCard {
  name: string;
  /** Copies in the left deck (A) and the right deck (B). */
  a: number;
  b: number;
}

export interface ComparedSection {
  section: string;
  /** Cards A has more copies of; the extra is `a - b`. */
  onlyA: ComparedCard[];
  onlyB: ComparedCard[];
  /** Cards in both; `Math.min(a, b)` copies are shared. */
  shared: ComparedCard[];
}

export interface DeckComparison {
  sections: ComparedSection[];
  /** Card copies only in A, only in B, and in both, across every section. */
  onlyA: number;
  onlyB: number;
  shared: number;
  /** Share of the larger main deck (with commander and companion) both decks hold; null when both are empty. */
  similarity: number | null;
  identical: boolean;
}

const ORDER = ['Commander', 'Companion', 'Deck', 'Sideboard', 'Maybeboard'];
/** Sections outside the deck itself; they don't count toward similarity. */
const SIDE = new Set(['Sideboard', 'Maybeboard']);
const BASICS = new Set(['plains', 'island', 'swamp', 'mountain', 'forest', 'wastes']);

export const sectionLabel = (section: string) => section === 'Deck' ? 'Main deck' : section;

function isLand(name: string, facts: Record<string, CardFacts>) {
  const type = facts[name]?.type;
  if (type) return type === 'Land';
  return BASICS.has(name.toLowerCase().replace(/^snow-covered /u, ''));
}

/** Spells by mana value, then lands; names break ties. Unknown costs sit after known ones. */
export function sortCards(cards: ComparedCard[], facts: Record<string, CardFacts> = {}): ComparedCard[] {
  const rank = (card: ComparedCard) => {
    if (isLand(card.name, facts)) return 1000;
    return facts[card.name]?.mana_value ?? 100;
  };
  return [...cards].sort((x, y) => rank(x) - rank(y) || x.name.localeCompare(y.name, undefined, { sensitivity: 'base' }));
}

function tally(cards: ManagedCard[]) {
  const sections = new Map<string, Map<string, { name: string; quantity: number }>>();
  for (const card of cards) {
    const section = sections.get(card.section) ?? new Map<string, { name: string; quantity: number }>();
    sections.set(card.section, section);
    // Printings of one card are listed separately; they count as one card here.
    const key = card.name.trim().toLocaleLowerCase();
    const entry = section.get(key);
    if (entry) entry.quantity += card.quantity;
    else section.set(key, { name: card.name.trim(), quantity: card.quantity });
  }
  return sections;
}

const sectionRank = (section: string) => {
  const index = ORDER.indexOf(section);
  return index === -1 ? ORDER.length : index;
};

export function compareDecks(a: ManagedCard[], b: ManagedCard[], facts: Record<string, CardFacts> = {}): DeckComparison {
  const left = tally(a);
  const right = tally(b);
  const names = [...new Set([...left.keys(), ...right.keys()])]
    .sort((x, y) => sectionRank(x) - sectionRank(y) || x.localeCompare(y));
  let onlyA = 0, onlyB = 0, shared = 0, deckShared = 0, deckA = 0, deckB = 0;
  const sections = names.map((section) => {
    const cardsA = left.get(section) ?? new Map<string, { name: string; quantity: number }>();
    const cardsB = right.get(section) ?? new Map<string, { name: string; quantity: number }>();
    const result: ComparedSection = { section, onlyA: [], onlyB: [], shared: [] };
    for (const key of new Set([...cardsA.keys(), ...cardsB.keys()])) {
      const card = { name: (cardsA.get(key) ?? cardsB.get(key))!.name, a: cardsA.get(key)?.quantity ?? 0, b: cardsB.get(key)?.quantity ?? 0 };
      const both = Math.min(card.a, card.b);
      if (both > 0) result.shared.push(card);
      if (card.a > card.b) result.onlyA.push(card);
      if (card.b > card.a) result.onlyB.push(card);
      onlyA += Math.max(card.a - card.b, 0);
      onlyB += Math.max(card.b - card.a, 0);
      shared += both;
      if (!SIDE.has(section)) { deckShared += both; deckA += card.a; deckB += card.b; }
    }
    result.onlyA = sortCards(result.onlyA, facts);
    result.onlyB = sortCards(result.onlyB, facts);
    result.shared = sortCards(result.shared, facts);
    return result;
  });
  const largest = Math.max(deckA, deckB);
  return {
    sections, onlyA, onlyB, shared,
    similarity: largest ? deckShared / largest : null,
    identical: onlyA === 0 && onlyB === 0,
  };
}
