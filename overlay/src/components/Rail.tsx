import appIcon from '../icons/app.png';
import { formatWhole, landDanger, showsLibrary } from '../model';
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

/** The 44px rail: icon (drag handle), turn, land %, library, open-panel arrow, gear. */
export function Rail({ payload, link, dock, landsInPlay, onOpenPanel, onOpenSettings, onDragStart }: Props) {
  const state = payload?.state ?? null;
  const active = showsLibrary(state);
  const status =
    link !== 'online' || payload?.tracker.state === 'offline'
      ? 'Tracker not running'
      : state?.mid_game_attach
        ? 'Joined mid-game'
        : active
          ? null
          : 'Waiting for a match';
  const danger = state && active ? landDanger(state, landsInPlay) : false;
  return (
    <div class="rail" role="group" aria-label="Tapps Tracker" title={status ?? undefined}>
      <img class="logo" src={appIcon} width={22} height={22} alt="Tapps Tracker" onMouseDown={onDragStart} draggable={false} />
      <div class="sep" />
      <div class="cell">
        <span class="k">Turn</span>
        <span class="v">{active && state?.turn_number ? state.turn_number : '—'}</span>
      </div>
      <div class="sep" />
      <div class="cell" aria-label="Chance of a land on the next draw">
        <span class={danger ? 'land danger' : 'land'}>{active && state ? formatWhole(state.land_odds['1']) : '—'}</span>
        <span class="k">Land</span>
      </div>
      <div class="cell" aria-label="Library">
        <span class="lib">
          {active && state ? (
            <>
              <b>{state.library_size}</b>/{state.deck_size}
            </>
          ) : (
            '—'
          )}
        </span>
        <span class="bar">
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
      {status ? <span class={`rail-status ${link !== 'online' || payload?.tracker.state === 'offline' ? 'off' : ''}`} aria-hidden="true" /> : null}
    </div>
  );
}
