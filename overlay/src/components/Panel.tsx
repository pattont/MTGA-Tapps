import { useMemo, useState } from 'preact/hooks';
import { buildSections, formatPct, formatWhole, oddsTone, shortFormat, typeClass, type Row } from '../model';
import type { Link, OverlayPayload, Settings, SortKey } from '../types';
import { Chevron, Gear, Pin } from './Icons';
import { ManaCost } from './ManaCost';
import W from '../icons/W.svg';
import U from '../icons/U.svg';
import B from '../icons/B.svg';
import R from '../icons/R.svg';
import G from '../icons/G.svg';

const PIP_ICONS: Record<string, string> = { W, U, B, R, G };

interface Props {
  payload: OverlayPayload | null;
  link: Link;
  settings: Settings;
  pinned: boolean;
  dock: Settings['dock'];
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  onCollapse: () => void;
  onTogglePin: () => void;
  onOpenSettings: () => void;
  onDragStart: (event: MouseEvent) => void;
  onHover: (row: Row | null, box: { top: number; bottom: number } | null) => void;
}

/** Deck colours from the decklist's casting costs — what the header pips show. */
export function deckColors(cards: { mana_cost: string | null }[]): string[] {
  const letters = new Set<string>();
  for (const card of cards) {
    for (const symbol of card.mana_cost?.matchAll(/\{([WUBRG])(?:\/([WUBRG]))?\}/g) ?? []) {
      letters.add(symbol[1]);
      if (symbol[2]) letters.add(symbol[2]);
    }
  }
  return ['W', 'U', 'B', 'R', 'G'].filter((c) => letters.has(c));
}

function CardRow({ row, exhausted, onHover }: { row: Row; exhausted: boolean; onHover: Props['onHover'] }) {
  const frac = row.total > 0 ? (100 * row.left) / row.total : 0;
  const tone = row.left > 0 ? oddsTone(row.odds['1']) : 'cold';
  return (
    <div
      class={`row${exhausted ? ' dim' : ''}`}
      onMouseEnter={(event) => {
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
        onHover(row, { top: rect.top, bottom: rect.bottom });
      }}
      onMouseLeave={() => onHover(null, null)}
    >
      <span class="mini">
        <i class="mbar">
          <b class={`fill-${typeClass(row.type_category)}`} style={{ width: `${frac}%` }} />
        </i>
      </span>
      <span class="cnt">
        <b>{row.left}</b>/{row.total}
      </span>
      <span class={`nm ${typeClass(row.type_category)}`} title={row.name}>
        {row.name}
      </span>
      <ManaCost cost={row.group ? null : row.mana_cost} />
      <span class={`pct ${tone}`}>{row.left > 0 ? formatPct(row.odds['1']) : '—'}</span>
    </div>
  );
}

export function Panel(props: Props) {
  const { payload, link, settings, pinned, sort, onSort, onCollapse, onTogglePin, onOpenSettings, onDragStart, onHover } = props;
  const state = payload?.state ?? null;
  const offline = link !== 'online' || payload?.tracker.state === 'offline';
  const sections = useMemo(() => (state ? buildSections(state, sort, settings.lands) : null), [state, sort, settings.lands]);
  const [showDrawn, setShowDrawn] = useState(false);
  const pips = state ? deckColors(state.cards) : [];
  const h2h = payload?.head_to_head;
  const active = Boolean(state?.game_active) && !state?.mid_game_attach && (state?.library_size ?? 0) > 0;

  return (
    <div class={`panel density-${settings.density}`} role="group" aria-label="Deck panel">
      <div class="head" onMouseDown={onDragStart}>
        <div class="deck">
          <b>
            {state?.deck_name ?? 'Tapps Overlay'}
            {pips.length > 0 ? (
              <span class="pips">
                {pips.map((c) => (
                  <img key={c} src={PIP_ICONS[c]} alt={c} />
                ))}
              </span>
            ) : null}
          </b>
          <span>
            {offline
              ? 'Tracker offline'
              : state?.mid_game_attach
                ? 'Joined mid-game — library unknown'
                : !active
                  ? 'Between games'
                  : `${shortFormat(state?.format_label)}${state?.opponent_name ? ` · vs ${state.opponent_name}` : ''}${
                      h2h ? ` (${h2h.wins}–${h2h.losses})` : ''
                    }`}
          </span>
        </div>
        <div class="turn">
          TURN<b>{active && state?.turn_number ? state.turn_number : '—'}</b>
        </div>
        <div class="ctl" onMouseDown={(event) => event.stopPropagation()}>
          <button type="button" onClick={onCollapse} title="Collapse to rail" aria-label="Collapse to rail">
            <Chevron dir={settings.dock === 'left' ? 'left' : 'right'} />
          </button>
          <button type="button" class={pinned ? 'on' : ''} onClick={onTogglePin} title={pinned ? 'Pinned — stays open' : 'Unpinned — returns to the rail when idle'} aria-label="Pin">
            <Pin filled={pinned} />
          </button>
          <button type="button" onClick={onOpenSettings} title="Settings" aria-label="Settings">
            <Gear />
          </button>
        </div>
      </div>

      {active && state ? (
        <>
          <div class="lands">
            <div class="t">
              Land drops
              <small>
                {state.lands_left} of {state.library_size} left
              </small>
            </div>
            <div class="odd now">
              <small>NEXT</small>
              <b>{formatWhole(state.land_odds['1'])}</b>
            </div>
            <div class="odd">
              <small>IN 2</small>
              <b>{formatWhole(state.land_odds['2'])}</b>
            </div>
            <div class="odd">
              <small>IN 3</small>
              <b>{formatWhole(state.land_odds['3'])}</b>
            </div>
          </div>
          <div class="tools">
            <span>Sort</span>
            <span class="seg" role="group" aria-label="Sort">
              {(['odds', 'mana', 'name'] as SortKey[]).map((key) => (
                <button key={key} type="button" class={sort === key ? 'on' : ''} onClick={() => onSort(key)}>
                  {key === 'odds' ? '%' : key === 'mana' ? 'Mana' : 'Name'}
                </button>
              ))}
            </span>
            {state.on_play === null ? null : (
              <span class={`pd ${state.on_play ? 'play' : 'draw'}`}>{state.on_play ? 'PLAY' : 'DRAW'}</span>
            )}
            <span class="lib">
              Library <b>{state.library_size}</b> / {state.deck_size}
            </span>
          </div>
          <div class="list">
            {sections && sections.spells.length > 0 ? <div class="grp">Spells</div> : null}
            {sections?.spells.map((row) => (
              <CardRow key={row.key} row={row} exhausted={row.left === 0} onHover={onHover} />
            ))}
            {sections && sections.lands.length > 0 ? <div class="grp">Lands</div> : null}
            {sections?.lands.map((row) => (
              <CardRow key={row.key} row={row} exhausted={row.left === 0} onHover={onHover} />
            ))}
            {sections && sections.drawn.length > 0 ? (
              <>
                <button type="button" class="grp grp-toggle" onClick={() => setShowDrawn((v) => !v)} aria-expanded={showDrawn}>
                  Drawn ({sections.drawn.length}) <Chevron dir={showDrawn ? 'down' : 'right'} />
                </button>
                {showDrawn ? sections.drawn.map((row) => <CardRow key={row.key} row={row} exhausted onHover={onHover} />) : null}
              </>
            ) : null}
            {state.unaccounted > 0 ? (
              <div class="note">
                {state.unaccounted} card{state.unaccounted === 1 ? '' : 's'} in the library the tracker can't name
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <div class="empty">
          {offline ? (
            <>
              <b>Tracker not running</b>
              <span>Start Tapps Tracker and the overlay will connect on its own.</span>
            </>
          ) : state?.mid_game_attach ? (
            <>
              <b>Joined mid-game</b>
              <span>The library can't be known for this game. Odds return next game.</span>
            </>
          ) : (
            <>
              <b>Waiting for a match</b>
              <span>Queue up — the deck fills in when the game starts.</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
