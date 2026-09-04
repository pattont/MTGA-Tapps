import W from '../icons/W.svg';
import U from '../icons/U.svg';
import B from '../icons/B.svg';
import R from '../icons/R.svg';
import G from '../icons/G.svg';
import C from '../icons/C.svg';
import { manaSymbols } from '../model';

const COLOR_ICONS: Record<string, string> = { W, U, B, R, G, C };

/** The real mana symbols (the dashboard's W/U/B/R/G vectors); generic and hybrid as small badges. */
export function ManaCost({ cost }: { cost: string | null | undefined }) {
  const symbols = manaSymbols(cost);
  if (symbols.length === 0) return <span class="mana" />;
  return (
    <span class="mana" aria-label={cost ?? ''}>
      {symbols.map((symbol, index) => {
        const icon = COLOR_ICONS[symbol];
        if (icon) return <img key={index} src={icon} alt={symbol} />;
        return (
          <i key={index} class={symbol.length > 1 ? 'gen hybrid' : 'gen'}>
            {symbol}
          </i>
        );
      })}
    </span>
  );
}
