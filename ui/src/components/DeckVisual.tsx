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
  const className = typeClass[visual.type_category] ?? 'deck-visual-other';
  return (
    <div className={`deck-visual ${className}`} aria-label={`${deckName} deck visual`}>
      <div className="deck-visual-frame">
        <span className="deck-visual-type">{visual.type_category}</span>
        <strong>{visual.card_name || deckName}</strong>
      </div>
    </div>
  );
}
