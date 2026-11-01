import { ManaCost } from '../../components/ManaCost';
import { deckSections, type DeckRow } from '../deckRows';
import type { StreamOptions } from '../options';
import type { OverlayState } from '../types';
import { useOverlay } from '../useOverlay';
import { Brand } from './Brand';

function Row({ row }: { row: DeckRow }) {
  return (
    <li className={`sk-row sk-type-${row.typeClass}${row.left === 0 ? ' sk-row-out' : ''}`}>
      <span className="sk-row-count">{row.left}</span>
      <span className="sk-row-name">{row.name}</span>
      <span className="sk-row-cost">{row.mana_cost ? <ManaCost info={{ mana_cost: row.mana_cost, cmc: 0 }} /> : null}</span>
      <span className="sk-row-odds">{row.left > 0 ? `${row.nextDraw}%` : '—'}</span>
    </li>
  );
}

export function DeckView({ state, options }: { state: OverlayState; options: StreamOptions }) {
  const { spells, lands } = deckSections(state, options.sort, options.lands);
  const live = state.game_active && !state.game_over;
  return (
    <div className="sk-panel sk-deck">
      <header className="sk-head">
        <div className="sk-title">{state.deck_name || 'Your deck'}</div>
        <div className="sk-sub">
          <span>
            Library <strong>{state.library_size}</strong>
          </span>
          {state.lands_total > 0 ? (
            <span>
              Land next draw <strong>{Math.round(state.land_odds?.['1'] ?? 0)}%</strong>
            </span>
          ) : null}
          {!live ? <span className="sk-tag">Final</span> : null}
        </div>
      </header>
      <ul className="sk-rows" aria-label="Library">
        {spells.map((row) => (
          <Row key={row.key} row={row} />
        ))}
        {lands.length > 0 && spells.length > 0 ? <li className="sk-rows-gap" aria-hidden="true" /> : null}
        {lands.map((row) => (
          <Row key={row.key} row={row} />
        ))}
      </ul>
      <div className="sk-foot">
        <span className="sk-foot-note">Copies left · next-draw odds</span>
        <Brand show={options.brand} />
      </div>
    </div>
  );
}

/** Deck tracker: the overlay's library state, polled with its ETag. */
export function DeckWidget({ options }: { options: StreamOptions }) {
  const { payload, offline } = useOverlay(options.demo);
  const state = payload?.state ?? null;

  const inGame = Boolean(state && (state.game_active || state.game_over));
  if (state && (inGame || options.idle === 'show') && state.cards.length > 0) {
    return <DeckView state={state} options={options} />;
  }
  if (options.idle === 'show') {
    return (
      <div className="sk-panel sk-deck sk-waiting">
        <div className="sk-sub">{offline ? 'Tracker not running' : 'Waiting for a game'}</div>
        <Brand show={options.brand} />
      </div>
    );
  }
  return null;
}
