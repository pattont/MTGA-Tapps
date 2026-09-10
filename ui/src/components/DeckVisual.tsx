import { useEffect, useState } from 'react';
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

/** An art request that has neither loaded nor errored by then is treated as
    failed and the next source is tried. Scryfall can answer an image URL
    with a 503 that Chrome never reports as an error, leaving a blank tile. */
export const ART_LOAD_TIMEOUT_MS = 6000;

export function DeckVisual({ deckName, visual, size = 'normal' }: DeckVisualProps) {
  // Try each art URL in order (arena-id first, by-name fallback second —
  // new sets often lack the arena-id mapping on Scryfall for a while).
  // The type-colored frame is the tile's base state and stays underneath:
  // the art is layered over it only once it has actually loaded, so a slow,
  // hung, or failed request never leaves an empty box.
  const sources = [visual.image_url, visual.image_fallback_url].filter(
    (url): url is string => Boolean(url),
  );
  // Failure count is keyed to the current URL set, so a payload refresh with
  // new art resets the chain without needing an effect.
  const sourcesKey = sources.join('|');
  const [attempt, setAttempt] = useState({ key: '', index: 0 });
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const sourceIndex = attempt.key === sourcesKey ? attempt.index : 0;
  const src = sourceIndex < sources.length ? sources[sourceIndex] : null;
  const loaded = src !== null && loadedSrc === src;

  useEffect(() => {
    if (!src || loaded) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setAttempt({ key: sourcesKey, index: sourceIndex + 1 });
    }, ART_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [src, loaded, sourcesKey, sourceIndex]);

  const typeCategory = visual.type_category || 'Other';
  const className = typeClass[typeCategory] ?? 'deck-visual-other';
  const visualName = visual.card_name ? formatCardName(visual.card_name) : deckName;
  const sizeClass = size === 'large' ? ' deck-visual-large' : '';
  return (
    <div className={`deck-visual ${className}${sizeClass}`} aria-label={`${deckName} deck visual`}>
      <div className="deck-visual-frame" aria-hidden={loaded ? 'true' : undefined}>
        <span className="deck-visual-type">{typeCategory}</span>
        <strong>{visualName}</strong>
      </div>
      {src ? (
        <img
          key={src}
          className={loaded ? 'deck-visual-art deck-visual-art-loaded' : 'deck-visual-art'}
          src={src}
          alt={visualName}
          loading="lazy"
          onLoad={() => setLoadedSrc(src)}
          onError={() => setAttempt({ key: sourcesKey, index: sourceIndex + 1 })}
        />
      ) : null}
    </div>
  );
}
