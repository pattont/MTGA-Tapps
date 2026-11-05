import { manaSymbols } from '../overlayView';

const COLOR_ICONS = new Set(['W', 'U', 'B', 'R', 'G', 'C']);

/**
 * A mana cost drawn the way the in-game overlay draws it
 * (overlay/src/components/ManaCost.tsx): the W/U/B/R/G/C vectors, and
 * generic, X and hybrid symbols as small grey badges. Keep the two in step.
 */
export function ManaCost({ cost }: { cost: string | null | undefined }) {
  const symbols = manaSymbols(cost);
  if (symbols.length === 0) return <span className="mana" />;
  return (
    <span className="mana" aria-label={cost ?? ''}>
      {symbols.map((symbol, index) =>
        COLOR_ICONS.has(symbol) ? (
          <img key={index} src={`/icons/${symbol}.svg`} alt={symbol} />
        ) : (
          <i key={index} className={symbol.length > 1 ? 'gen hybrid' : 'gen'}>
            {symbol}
          </i>
        ),
      )}
    </span>
  );
}
