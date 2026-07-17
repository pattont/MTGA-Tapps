import { useState } from 'react';
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
  const [imageFailed, setImageFailed] = useState(false);
  const typeCategory = visual.type_category || 'Other';
  const className = typeClass[typeCategory] ?? 'deck-visual-other';
  const showImage = Boolean(visual.image_url) && !imageFailed;
  return (
    <div className={`deck-visual ${className}`} aria-label={`${deckName} deck visual`}>
      {showImage ? (
        <img
          className="deck-visual-art"
          src={visual.image_url ?? undefined}
          alt={visual.card_name || deckName}
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <div className="deck-visual-frame">
          <span className="deck-visual-type">{typeCategory}</span>
          <strong>{visual.card_name || deckName}</strong>
        </div>
      )}
    </div>
  );
}
