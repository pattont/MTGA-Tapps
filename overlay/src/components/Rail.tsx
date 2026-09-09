import appIcon from '../icons/app.png';
import { landDanger, showsLibrary } from '../model';
import type { Link, OverlayPayload } from '../types';
import { Chevron, Gear } from './Icons';

interface Props {
  payload: OverlayPayload | null;
  link: Link;
  dock: 'left' | 'right' | 'float';
  landsInPlay: number | null;
  onOpenPanel: () => void;
  onOpenSettings: () => void;
  onDragStart: (event: MouseEvent) => void;
}

/** Deck bar tone by what is left: green, yellow once half the deck is gone, red under 15 cards. */
export function deckTone(librarySize: number, deckSize: number): 'ok' | 'warn' | 'low' {
  if (librarySize < 15) return 'low';
  if (deckSize > 0 && librarySize * 2 <= deckSize) return 'warn';
  return 'ok';
}

/** The 44px rail: icon (drag handle), then Turn / Land / Deck as label-over-value
 *  cells at one size, the open-panel arrow, and the gear. */
export function Rail({ payload, link, dock, landsInPlay, onOpenPanel, onOpenSettings, onDragStart }: Props) {
  const state = payload?.state ?? null;
  const active = showsLibrary(state);
  const offline = link !== 'online' || payload?.tracker.state === 'offline';
  const danger = state && active ? landDanger(state, landsInPlay) : false;
  const tone = active && state ? deckTone(state.library_size, state.deck_size) : 'ok';
  return (
    <div class="rail" role="group" aria-label="Tapps Tracker">
      {/* The tracker link has no indicator while it works. When it does not,
          the icon itself says so: dimmed, with a warning badge and a tooltip. */}
      <span class={`logo-wrap${offline ? ' offline' : ''}`} title={offline ? 'Not connected to Tapps Tracker. Start the tracker; the overlay reconnects on its own.' : undefined}>
        <img class="logo" src={appIcon} width={22} height={22} alt="Tapps Tracker" onMouseDown={onDragStart} draggable={false} />
        {offline ? (
          <i class="warn-badge" aria-label="Tracker not running">
            !
          </i>
        ) : null}
      </span>
      <div class="sep" />
      <div class="cell">
        <span class="k">Turn</span>
        <span class="v">{active && state?.turn_number ? state.turn_number : '—'}</span>
      </div>
      <div class="sep" />
      <div class="cell" aria-label="Chance of a land on the next draw">
        <span class="k">Land</span>
        <span class={`v land${danger ? ' danger' : ''}`}>
          {active && state ? (
            <>
              {Math.round(state.land_odds['1'])}
              <span class="of">%</span>
            </>
          ) : (
            '—'
          )}
        </span>
      </div>
      <div class="sep" />
      <div class="cell" aria-label="Library">
        <span class="k">Deck</span>
        <span class={`v lib${active && state && state.deck_size >= 100 ? ' wide' : ''}`}>
          {active && state ? (
            <>
              <b>{state.library_size}</b>
              <span class="of">/{state.deck_size}</span>
            </>
          ) : (
            '—'
          )}
        </span>
        <span class={`bar ${tone}`}>
          <i style={{ width: active && state && state.deck_size > 0 ? `${(100 * state.library_size) / state.deck_size}%` : '0%' }} />
        </span>
      </div>
      <div class="sep" />
      {/* Points the way the panel opens: toward the board, away from the docked edge. */}
      <button type="button" class="open" onClick={onOpenPanel} title="Open the deck panel" aria-label="Open the deck panel">
        <Chevron dir={dock === 'left' ? 'right' : 'left'} />
      </button>
      <button type="button" class="gear" onClick={onOpenSettings} aria-label="Overlay settings">
        <Gear />
      </button>
    </div>
  );
}
