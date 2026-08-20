import { useState } from 'react';
import type { DeckVisual as DeckVisualData } from '../api';
import { formatCardName } from '../format';

interface DeckVisualProps {
  deckName: string;
  visual: DeckVisualData;
  /** 'large' renders the hero-sized art used on the deck detail header. */
  size?: 'normal' | 'large';
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

export function DeckVisual({ deckName, visual, size = 'normal' }: DeckVisualProps) {
  // Try each art URL in order (arena-id first, by-name fallback second —
  // new sets often lack the arena-id mapping on Scryfall for a while),
  // then fall back to the type-colored text tile.
  const sources = [visual.image_url, visual.image_fallback_url].filter(
    (url): url is string => Boolean(url),
  );
  // Failure count is keyed to the current URL set, so a payload refresh with
  // new art resets the chain without needing an effect.
  const sourcesKey = sources.join('|');
  const [attempt, setAttempt] = useState({ key: '', index: 0 });
  const sourceIndex = attempt.key === sourcesKey ? attempt.index : 0;
  const src = sourceIndex < sources.length ? sources[sourceIndex] : null;
  const typeCategory = visual.type_category || 'Other';
  const className = typeClass[typeCategory] ?? 'deck-visual-other';
  const visualName = visual.card_name ? formatCardName(visual.card_name) : deckName;
  const sizeClass = size === 'large' ? ' deck-visual-large' : '';
  return (
    <div className={`deck-visual ${className}${sizeClass}`} aria-label={`${deckName} deck visual`}>
      {src ? (
        <img
          className="deck-visual-art"
          src={src}
          alt={visualName}
          loading="lazy"
          onError={() => setAttempt({ key: sourcesKey, index: sourceIndex + 1 })}
        />
      ) : (
        <div className="deck-visual-frame">
          <span className="deck-visual-type">{typeCategory}</span>
          <strong>{visualName}</strong>
        </div>
      )}
    </div>
  );
}
