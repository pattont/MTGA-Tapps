import type { CardFacts, ManagedCard } from './deckManagerApi';

/** Type headings in deck-list order, lands last (Arena and most deckbuilders do the same). */
export const TYPE_GROUPS = [
  { type: 'Creature', label: 'Creatures', icon: 'creature' },
  { type: 'Planeswalker', label: 'Planeswalkers', icon: 'planeswalker' },
  { type: 'Battle', label: 'Battles', icon: 'battle' },
  { type: 'Instant', label: 'Instants', icon: 'instant' },
  { type: 'Sorcery', label: 'Sorceries', icon: 'sorcery' },
  { type: 'Artifact', label: 'Artifacts', icon: 'artifact' },
  { type: 'Enchantment', label: 'Enchantments', icon: 'enchantment' },
  { type: 'Other', label: 'Other', icon: 'multiple' },
  { type: 'Land', label: 'Lands', icon: 'land' },
] as const;

export type TypeGroup = (typeof TYPE_GROUPS)[number];

export interface CardGroup { group: TypeGroup; cards: ManagedCard[]; count: number }

const sum = (cards: ManagedCard[]) => cards.reduce((total, card) => total + card.quantity, 0);

/** Cheapest first, then by name; a card without a known cost goes last. */
export function byManaValue(cards: ManagedCard[], facts: Record<string, CardFacts> = {}): ManagedCard[] {
  const value = (card: ManagedCard) => facts[card.name]?.type === 'Land' ? 1000 : facts[card.name]?.mana_value ?? 100;
  return [...cards].sort((a, b) => value(a) - value(b) || a.name.localeCompare(b.name));
}

/**
 * The main deck under type headings, each sorted by mana value. Without any
 * type facts (no Arena card DB) it returns null, and the list stays as saved.
 */
export function groupByType(cards: ManagedCard[], facts: Record<string, CardFacts> = {}): CardGroup[] | null {
  if (!cards.some((card) => facts[card.name]?.type)) return null;
  const known = new Set<string>(TYPE_GROUPS.map((group) => group.type));
  return TYPE_GROUPS.map((group) => {
    const members = cards.filter((card) => {
      const type = facts[card.name]?.type;
      return (type && known.has(type) ? type : 'Other') === group.type;
    });
    return { group, cards: byManaValue(members, facts), count: sum(members) };
  }).filter((entry) => entry.cards.length);
}
