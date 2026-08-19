import { manaCostSymbols, manaSymbolUrl, type CardManaInfo } from '../manaCosts';

/**
 * A card's mana cost as official symbol images (Scryfall-hosted SVGs, same
 * dependency as the card-art backdrop). Lands and unknown costs render a dash.
 */
export function ManaCost({ info }: { info: CardManaInfo | null | undefined }) {
  if (!info || !info.mana_cost) {
    return <>—</>;
  }
  const symbols = manaCostSymbols(info.mana_cost);
  if (symbols.length === 0) {
    return <>—</>;
  }
  return (
    <span className="mana-cost" aria-label={`Mana cost ${info.mana_cost}`}>
      {symbols.map((symbol, index) => (
        <img
          key={`${symbol}-${index}`}
          alt={symbol}
          className="mana-symbol"
          loading="lazy"
          src={manaSymbolUrl(symbol)}
        />
      ))}
    </span>
  );
}
