import type { CSSProperties, ReactNode } from 'react';
import { ColorPips } from '../../components/ColorPips';
import { ManaCost } from '../../components/ManaCost';
import type { DeckRow } from '../deckRows';
import type { DeckSort, StreamOptions } from '../options';
import { deckColors, oddsTone, overlaySections, shortFormat, showsLibrary, tintAlpha } from '../overlayView';
import type { OverlayPayload, OverlaySideCard, OverlayState } from '../types';
import { useOverlay } from '../useOverlay';
import { Brand } from './Brand';

/*
 * The in-game overlay's panel as one browser source. Nobody on stream can
 * hover or click, so the controls are gone, the sort reads as a label, and
 * the sideboard stays open beside the panel (or below it) instead of flying
 * out on a click. Card art for viewers is the spotlight widget's job.
 */

const SORTS: Array<[DeckSort, string]> = [
  ['odds', '%'],
  ['mana', 'Mana'],
  ['name', 'Name'],
];

function Chevron({ open }: { open: boolean }) {
  return (
    <svg aria-hidden="true" className="chev" viewBox="0 0 10 10" width="9" height="9">
      <path d={open ? 'M2 3.5 5 6.5 8 3.5' : 'M3.5 2 6.5 5 3.5 8'} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Cost({ cost }: { cost: string | null }) {
  return <span className="mana">{cost ? <ManaCost info={{ mana_cost: cost, cmc: 0 }} /> : null}</span>;
}

function CardRow({ row, sub }: { row: DeckRow; sub?: boolean }) {
  const out = row.left === 0;
  return (
    <div className={`row${out ? ' dim' : ''}${sub ? ' sub' : ''}`}>
      <span className="body">
        <span className={`nm ${row.typeClass}`}>{row.name}</span>
        <Cost cost={row.mana_cost} />
      </span>
      <span className="right">
        <span className="cnt">
          <b>{row.left}</b>/{row.total}
        </span>
        <span className={`pct ${out ? 'cold' : oddsTone(row.nextDraw)}`}>{out ? '—' : `${row.nextDraw}%`}</span>
      </span>
    </div>
  );
}

function SummaryRow({ label, typeClass, open, count, odds }: { label: string; typeClass: string; open: boolean; count: ReactNode; odds?: ReactNode }) {
  return (
    <div className={`row fold-row${odds === undefined ? ' side-row' : ''}`}>
      <span className="body">
        <span className={`nm ${typeClass}`}>
          {label} <Chevron open={open} />
        </span>
      </span>
      <span className="right">
        <span className="cnt">{count}</span>
        {odds}
      </span>
    </div>
  );
}

function Sideboard({ cards }: { cards: OverlaySideCard[] }) {
  return (
    <section className="sideboard" aria-label="Sideboard">
      <div className="sb-head">Sideboard</div>
      {cards.map((card) => (
        <div key={card.name} className="sb-row">
          <span className="body">
            <span className={`nm ${typeClassOf(card)}`}>{card.name}</span>
            <Cost cost={card.mana_cost} />
          </span>
          <span className="cnt">
            <b>{card.count}</b>
          </span>
        </div>
      ))}
    </section>
  );
}

function typeClassOf(card: OverlaySideCard): string {
  const t = (card.land ? 'Land' : card.type_category || 'Other').toLowerCase();
  if (t.includes('creature')) return 'creature';
  if (t.includes('planeswalker')) return 'walker';
  if (t.includes('instant')) return 'instant';
  if (t.includes('sorcery')) return 'sorcery';
  if (t.includes('enchant')) return 'ench';
  if (t.includes('artifact')) return 'artifact';
  if (t.includes('land')) return 'land';
  return 'other';
}

function headLine(state: OverlayState, payload: OverlayPayload, options: StreamOptions): string {
  const parts: string[] = [];
  const format = shortFormat(state.format_label);
  if (format) parts.push(format);
  if (state.opponent_name) {
    const h2h = payload.head_to_head;
    parts.push(`vs ${options.opponent ? state.opponent_name : 'Opponent'}${h2h ? ` (${h2h.wins}–${h2h.losses})` : ''}`);
  }
  return `${state.game_over ? 'Game over · ' : ''}${parts.join(' · ')}`;
}

export function OverlayView({ payload, options }: { payload: OverlayPayload; options: StreamOptions }) {
  const state = payload.state!;
  const { spells, lands, drawn } = overlaySections(state, options.sort);
  const sideboard = state.sideboard ?? [];
  const sideCount = sideboard.reduce((sum, card) => sum + card.count, 0);
  const sideOpen = options.sideboard !== 'off' && sideCount > 0;
  const landsOpen = options.lands === 'all';
  const unaccounted = state.unaccounted ?? 0;

  return (
    <>
      <div className="head">
        <div className="deck">
          <b>
            <span className="deck-name">{state.deck_name || 'Your deck'}</span>
            <ColorPips colors={deckColors(state.cards)} size={11} />
          </b>
          <span>{headLine(state, payload, options)}</span>
        </div>
        <div className="corner">
          <Brand show={options.brand} />
          <div className="turn">
            TURN<b>{state.turn_number ?? '—'}</b>
          </div>
        </div>
      </div>
      <div className="lands">
        <div className="t">
          Land drops
          <small>
            {state.lands_left} of {state.library_size} left
          </small>
        </div>
        {(['1', '2', '3'] as const).map((n) => (
          <div key={n} className={`odd${n === '1' ? ' now' : ''}`}>
            <small>{n === '1' ? 'NEXT' : `IN ${n}`}</small>
            <b>{Math.round(state.land_odds[n])}%</b>
          </div>
        ))}
      </div>
      <div className="tools">
        <span>Sort</span>
        <span className="seg" aria-label="Sorted by">
          {SORTS.map(([key, label]) => (
            <span key={key} className={options.sort === key ? 'on' : ''}>
              {label}
            </span>
          ))}
        </span>
        {state.game_over ? (
          <span className="pd over">FINAL</span>
        ) : state.on_play === null || state.on_play === undefined ? null : (
          <span className={`pd ${state.on_play ? 'play' : 'draw'}`}>{state.on_play ? 'PLAY' : 'DRAW'}</span>
        )}
        <span className="lib">
          Library <b>{state.library_size}</b> / {state.deck_size}
        </span>
      </div>
      <div className="list" aria-label="Library">
        {spells.map((row) => (
          <CardRow key={row.key} row={row} />
        ))}
        {state.lands_total > 0 ? (
          <SummaryRow
            label="Lands"
            typeClass="land"
            open={landsOpen}
            count={
              <>
                <b>{state.lands_left}</b>/{state.lands_total}
              </>
            }
            odds={
              <span className={`pct ${state.lands_left > 0 ? oddsTone(state.land_odds['1']) : 'cold'}`}>
                {state.lands_left > 0 ? `${Math.round(state.land_odds['1'])}%` : '—'}
              </span>
            }
          />
        ) : null}
        {landsOpen ? lands.map((row) => <CardRow key={row.key} row={row} sub />) : null}
        {drawn > 0 ? <div className="grp">Drawn ({drawn})</div> : null}
        {sideCount > 0 ? <SummaryRow label="Sideboard" typeClass="other" open={sideOpen} count={<b>{sideCount}</b>} /> : null}
        {unaccounted > 0 ? (
          <div className="note">
            {unaccounted} card{unaccounted === 1 ? '' : 's'} in the library the tracker can't name
          </div>
        ) : null}
      </div>
    </>
  );
}

function Empty({ offline, midGame }: { offline: boolean; midGame: boolean }) {
  return (
    <>
      <div className="head">
        <div className="deck">
          <b>Tapps Tracker</b>
        </div>
      </div>
      <div className="empty">
        {offline ? (
          <span className="pill off">
            <i className="dot" aria-hidden="true" /> Tracker not running
          </span>
        ) : midGame ? (
          <>
            <span className="pill">
              <i className="dot" aria-hidden="true" /> Joined mid-game
            </span>
            <span>The library can't be known for this game. Odds return next game.</span>
          </>
        ) : (
          <span className="pill">
            <i className="dot" aria-hidden="true" /> Waiting for a match…
          </span>
        )}
      </div>
    </>
  );
}

/** Full overlay: the in-game panel, the sideboard and the land odds in one source. */
export function OverlayWidget({ options }: { options: StreamOptions }) {
  const { payload, offline } = useOverlay(options.demo);
  const state = payload?.state ?? null;
  const live = payload !== null && showsLibrary(state);
  if (!live && options.idle !== 'show') return null;

  const sideboard = live ? (state?.sideboard ?? []) : [];
  const showSide = live && options.sideboard !== 'off' && sideboard.length > 0;
  const alpha = tintAlpha(options.opacity);
  const style = { '--tint-alpha': alpha } as CSSProperties;
  const classes = ['sko', `sko-side-${options.sideboard}`, alpha > 0 ? 'has-bg' : 'no-bg', `names-${options.names}`];

  return (
    <div className={classes.join(' ')} style={style}>
      <div className="panel" role="group" aria-label="Deck panel">
        {live ? (
          <OverlayView payload={payload} options={options} />
        ) : (
          <Empty offline={offline || payload?.tracker.state === 'offline'} midGame={Boolean(state?.mid_game_attach)} />
        )}
      </div>
      {showSide ? <Sideboard cards={sideboard} /> : null}
    </div>
  );
}
