import 'mana-font/css/mana.min.css';
import { manaCostSymbols, manaSymbolClass, type CardManaInfo } from '../manaCosts';

/**
 * A card's mana cost as official MTG symbols, rendered from the bundled
 * mana-font icon set (works offline; covers hybrid, twobrid, Phyrexian,
 * X, snow, and colorless pips). Lands and unknown costs render a dash.
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
        <i
          key={`${symbol}-${index}`}
          aria-hidden="true"
          className={`ms ms-cost ms-shadow ${manaSymbolClass(symbol)}`}
          title={symbol}
        />
      ))}
    </span>
  );
}
