export const cardTypeToneClass: Record<string, string> = {
  Land: 'type-chip-land',
  Creature: 'type-chip-creature',
  Instant: 'type-chip-instant',
  Sorcery: 'type-chip-sorcery',
  Artifact: 'type-chip-artifact',
  Enchantment: 'type-chip-enchantment',
  Planeswalker: 'type-chip-planeswalker',
  Battle: 'type-chip-other',
};

/** Color class for a card's primary type (first type when compound, e.g. "Creature, Artifact"). */
export function typeToneClass(type: string | null | undefined): string {
  const primary = String(type ?? '')
    .split(',')[0]
    .trim();
  return cardTypeToneClass[primary] ?? 'type-chip-other';
}
