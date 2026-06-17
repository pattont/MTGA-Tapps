import type { DeckVisual as DeckVisualData } from '../api';

interface DeckVisualProps {
  deckName: string;
  visual: DeckVisualData;
}

const typeClass: Record<string, string> = {
  Land: 'deck-visual-land',
  Creature: 'deck-visual-creature',
  Instant: 'deck-visual-instant',
  Sorcery: 'deck-visual-sorcery',
  Artifact: 'deck-visual-artifact',
  Enchantment: 'deck-visual-enchantment',
  Planeswalker: 'deck-visual-planeswalker',
};

export function DeckVisual({ deckName, visual }: DeckVisualProps) {
  const typeCategory = visual.type_category || 'Other';
  const className = typeClass[typeCategory] ?? 'deck-visual-other';
  return (
    <div className={`deck-visual ${className}`} aria-label={`${deckName} deck visual`}>
      <div className="deck-visual-frame">
        <span className="deck-visual-type">{typeCategory}</span>
        <strong>{visual.card_name || deckName}</strong>
      </div>
    </div>
  );
}
