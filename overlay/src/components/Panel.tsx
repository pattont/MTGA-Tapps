import { useEffect, useMemo, useState } from 'preact/hooks';
import { buildSections, formatPct, formatWhole, libraryNotice, oddsTone, shortFormat, showsLibrary, typeClass, unseenCount, type Row } from '../model';
import type { Link, OverlayPayload, Settings, SortKey } from '../types';
import { Chevron, Gear, Pin } from './Icons';
import { ManaCost } from './ManaCost';
import { FloodMeter } from './FloodMeter';
import { showsTodayRecord, TodayRecord } from './TodayRecord';
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
  /** Where the shell says the cursor is over the page (CSS px), or null when
      it is off the window. Hovering is driven from here, not from mouse
      events, which this never-focused window does not get until clicked. */
  cursor: { x: number; y: number } | null;
  sideboardOpen: boolean;
  onToggleSideboard: () => void;
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

/** Keys for the list's toggle rows: highlighted under the cursor, no hover card. */
const TOGGLE_LANDS = '\u0000lands';
const TOGGLE_DRAWN = '\u0000drawn';
const TOGGLE_SIDEBOARD = '\u0000sideboard';

/** `ceiling`: cards left the library unseen, so a count is the most that can be left ("≤3"). */
function CardRow({ row, exhausted, hot, sub, ceiling }: { row: Row; exhausted: boolean; hot: boolean; sub?: boolean; ceiling?: boolean }) {
  const tone = row.left > 0 ? oddsTone(row.odds['1']) : 'cold';
  const atMost = ceiling && row.left > 0;
  return (
    <div class={`row${exhausted ? ' dim' : ''}${sub ? ' sub' : ''}${hot ? ' hot' : ''}`} data-key={row.key}>
      <span class="body">
        <span class={`nm ${typeClass(row.type_category)}`} title={row.name}>
          {row.name}
        </span>
        {row.group ? null : <ManaCost cost={row.mana_cost} />}
      </span>
      <span class="right">
        <span class="cnt" title={atMost ? `At most ${row.left} left` : undefined}>
          <b>
            {atMost ? '≤' : ''}
            {row.left}
          </b>
          /{row.total}
        </span>
        <span class={`pct ${tone}`}>{row.left > 0 ? formatPct(row.odds['1']) : '—'}</span>
      </span>
    </div>
  );
}

export function Panel(props: Props) {
  const { payload, link, settings, pinned, sort, onSort, onCollapse, onTogglePin, onOpenSettings, onDragStart, onHover, cursor, sideboardOpen, onToggleSideboard } = props;
  const state = payload?.state ?? null;
  const offline = link !== 'online' || payload?.tracker.state === 'offline';
  const sections = useMemo(() => (state ? buildSections(state, sort, settings.lands) : null), [state, sort, settings.lands]);
  // Cards left the library unseen: counts are ceilings, and a line says so.
  const ceiling = state ? unseenCount(state) > 0 : false;
  const notice = state ? libraryNotice(state) : null;
  // The row under the shell-reported cursor: highlighted here, and reported
  // up for the hover card. Gone the moment the cursor is off it. This is the
  // list's only highlight (no CSS :hover, which sticks once the window starts
  // passing the mouse to Arena). The Lands, Sideboard and Drawn toggles carry
  // keys too, for the highlight only.
  const [hotKey, setHotKey] = useState<string | null>(null);
  useEffect(() => {
    const rowsByKey = new Map<string, Row>();
    if (sections) {
      for (const list of [sections.spells, sections.lands, sections.drawn]) for (const row of list) rowsByKey.set(row.key, row);
    }
    const hit = cursor && typeof document !== 'undefined' ? document.elementFromPoint(cursor.x, cursor.y) : null;
    const el = hit instanceof Element ? hit.closest<HTMLElement>('.list [data-key]') : null;
    const key = el?.dataset.key ?? null;
    const row = key ? rowsByKey.get(key) ?? null : null;
    setHotKey(key);
    if (row && el) {
      const rect = el.getBoundingClientRect();
      onHover(row, { top: rect.top, bottom: rect.bottom });
    } else {
      onHover(null, null);
    }
  }, [cursor, sections, onHover]);
  const [showDrawn, setShowDrawn] = useState(false);
  // Lands fold into one row (total + next-draw %) until opened.
  const [landsOpen, setLandsOpen] = useState(false);
  const sideboard = state?.sideboard ?? [];
  const sideboardCount = sideboard.reduce((sum, card) => sum + card.count, 0);
  const pips = state ? deckColors(state.cards) : [];
  const h2h = payload?.head_to_head;
  const today = payload?.today;
  const recordStyle = settings.sessionRecord ?? 'scoreboard';
  const active = showsLibrary(state);
  // The flood meter shows with the game's library (live, or the game just over).
  const floodPlace = settings.floodMeter ?? 'above';
  const quality = active ? payload?.draw_quality ?? null : null;
  const floodMeter = floodPlace !== 'off' && quality ? <FloodMeter quality={quality} /> : null;

  return (
    <div class={`panel density-${settings.density}`} role="group" aria-label="Deck panel">
      <div class="head" onMouseDown={onDragStart}>
        <div class="deck">
          <b>
            {(active && state?.deck_name) || 'Tapps Tracker'}
            {pips.length > 0 ? (
              <span class="pips">
                {pips.map((c) => (
                  <img key={c} src={PIP_ICONS[c]} alt={c} />
                ))}
              </span>
            ) : null}
          </b>
          {active && state ? (
            <span>
              {state.game_over ? 'Game over · ' : ''}
              {shortFormat(state.format_label)}
              {state.opponent_name ? ` · vs ${state.opponent_name}` : ''}
              {h2h ? ` (${h2h.wins}–${h2h.losses})` : ''}
            </span>
          ) : state?.mid_game_attach && !offline ? (
            <span>Joined mid-game — library unknown</span>
          ) : null}
        </div>
        {active && state ? (
          <div class="turn">
            TURN<b>{state.turn_number ?? '—'}</b>
          </div>
        ) : null}
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
                {ceiling ? 'up to ' : ''}
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
            {state.game_over ? (
              <span class="pd over">FINAL</span>
            ) : state.on_play === null ? null : (
              <span class={`pd ${state.on_play ? 'play' : 'draw'}`}>{state.on_play ? 'PLAY' : 'DRAW'}</span>
            )}
            <span class="lib">
              Library <b>{state.library_size}</b> / {state.deck_size}
            </span>
          </div>
          <div class="list">
            <div class="list-body">
            {notice ? (
              <div class="note warn" role="status">
                {notice}
              </div>
            ) : null}
            {sections?.spells.map((row) => (
              <CardRow key={row.key} row={row} exhausted={row.left === 0} hot={hotKey === row.key} ceiling={ceiling} />
            ))}
            {sections && sections.lands.length > 0 ? (
              <button
                type="button"
                class={`row land-row${landsOpen ? ' open' : ''}${hotKey === TOGGLE_LANDS ? ' hot' : ''}`}
                data-key={TOGGLE_LANDS}
                onClick={() => setLandsOpen((v) => !v)}
                aria-expanded={landsOpen}
                aria-label={`Lands, ${state.lands_left} of ${state.lands_total} left`}
              >
                <span class="body">
                  <span class="nm land">
                    Lands <Chevron dir={landsOpen ? 'down' : 'right'} />
                  </span>
                </span>
                <span class="right">
                  <span class="cnt">
                    <b>
                      {ceiling && state.lands_left > 0 ? '≤' : ''}
                      {state.lands_left}
                    </b>
                    /{state.lands_total}
                  </span>
                  <span class={`pct ${state.lands_left > 0 ? oddsTone(state.land_odds['1']) : 'cold'}`}>
                    {state.lands_left > 0 ? formatPct(state.land_odds['1']) : '—'}
                  </span>
                </span>
              </button>
            ) : null}
            {landsOpen
              ? sections?.lands.map((row) => <CardRow key={row.key} row={row} exhausted={row.left === 0} hot={hotKey === row.key} sub ceiling={ceiling} />)
              : null}
            {sections && sections.drawn.length > 0 ? (
              <>
                <button
                  type="button"
                  class={`grp grp-toggle${hotKey === TOGGLE_DRAWN ? ' hot' : ''}`}
                  data-key={TOGGLE_DRAWN}
                  onClick={() => setShowDrawn((v) => !v)}
                  aria-expanded={showDrawn}
                >
                  Drawn ({sections.drawn.length}) <Chevron dir={showDrawn ? 'down' : 'right'} />
                </button>
                {showDrawn ? sections.drawn.map((row) => <CardRow key={row.key} row={row} exhausted hot={hotKey === row.key} />) : null}
              </>
            ) : null}
            {sideboardCount > 0 ? (
              <button
                type="button"
                class={`row side-row${sideboardOpen ? ' open' : ''}${hotKey === TOGGLE_SIDEBOARD ? ' hot' : ''}`}
                data-key={TOGGLE_SIDEBOARD}
                onClick={onToggleSideboard}
                aria-expanded={sideboardOpen}
                aria-label={`Sideboard, ${sideboardCount} cards`}
              >
                <span class="body">
                  <span class="nm other">
                    Sideboard <Chevron dir={sideboardOpen ? 'down' : 'right'} />
                  </span>
                </span>
                <span class="right">
                  <span class="cnt">
                    <b>{sideboardCount}</b>
                  </span>
                </span>
              </button>
            ) : null}
            {state.unaccounted > 0 ? (
              <div class="note">
                {state.unaccounted} card{state.unaccounted === 1 ? '' : 's'} in the library the tracker can't name
              </div>
            ) : null}
            </div>
          </div>
        </>
      ) : (
        <div class="empty">
          {offline ? (
            <>
              <span class="pill off">
                <i class="dot" aria-hidden="true" /> Tracker not running
              </span>
              <span>Start Tapps Tracker and the overlay connects on its own.</span>
            </>
          ) : state?.mid_game_attach ? (
            <>
              <span class="pill">
                <i class="dot" aria-hidden="true" /> Joined mid-game
              </span>
              <span>The library can't be known for this game. Odds return next game.</span>
            </>
          ) : (
            <span class="pill">
              <i class="dot" aria-hidden="true" /> Waiting for a match…
            </span>
          )}
        </div>
      )}
      {floodPlace === 'above' ? floodMeter : null}
      {recordStyle !== 'off' && showsTodayRecord(recordStyle, today) ? <TodayRecord today={today} style={recordStyle} /> : null}
      {floodPlace === 'below' ? floodMeter : null}
    </div>
  );
}
