/**
 * The full-overlay widget's view helpers. These copy the in-game overlay's
 * own rules (overlay/src/model.ts, overlay/src/App.tsx) so the stream shows
 * the same labels, colours and background as the player sees; keep them in
 * step when the overlay changes.
 */

import { deckSections, isSingleton, type DeckRow } from './deckRows';
import type { DeckSort } from './options';
import type { OverlayState } from './types';

/**
 * The overlay's background slider (0–100) → charcoal alpha. Tops out at 88 %
 * so the board still shows through a little, and keeps the default (60)
 * reasonably dark. Text is never faded.
 */
export function tintAlpha(slider: number): number {
  const v = Math.max(0, Math.min(1, slider / 100));
  return Math.round(0.88 * Math.pow(v, 0.4) * 1000) / 1000;
}

/** "Std. Ranked": abbreviated so the header line fits. */
export function shortFormat(label: string | null | undefined): string {
  if (!label) return '';
  return label
    .replace(/Best-of-(\d)/i, 'BO$1')
    .replace(/\(Ranked\)/i, 'Ranked')
    .replace(/\(Unranked\)/i, '')
    .replace(/Standard/i, 'Std.')
    .replace(/Historic Brawl/i, 'Hist. Brawl')
    .replace(/Historic/i, 'Hist.')
    .replace(/Modern/i, 'Mod.')
    .replace(/Pioneer/i, 'Pio.')
    .replace(/Timeless/i, 'Time.')
    .replace(/Limited|Premier Draft|Quick Draft|Sealed/i, 'Ltd.')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Deck colours from the decklist's casting costs, as WUBRG letters. */
export function deckColors(cards: Array<{ mana_cost: string | null }>): string {
  const letters = new Set<string>();
  for (const card of cards) {
    for (const symbol of card.mana_cost?.matchAll(/\{([WUBRG])(?:\/([WUBRG]))?\}/g) ?? []) {
      letters.add(symbol[1]);
      if (symbol[2]) letters.add(symbol[2]);
    }
  }
  return ['W', 'U', 'B', 'R', 'G'].filter((c) => letters.has(c)).join('');
}

export function oddsTone(percent: number): 'hot' | 'warm' | 'cold' {
  if (percent >= 10) return 'hot';
  if (percent >= 5) return 'warm';
  return 'cold';
}

export interface OverlaySections {
  spells: DeckRow[];
  /** Each land, listed under the Lands row when lands=all. */
  lands: DeckRow[];
  /** Singleton decks: cards fully drawn, shown as a count like the overlay's folded Drawn group. */
  drawn: number;
}

export function overlaySections(state: OverlayState, sort: DeckSort): OverlaySections {
  const { spells, lands } = deckSections(state, sort, 'all');
  const drawn = isSingleton(state) ? state.cards.filter((card) => !card.land && card.left === 0).length : 0;
  return { spells, lands, drawn };
}

/** Whether there is a library to show: live, or frozen on the results screen. */
export function showsLibrary(state: OverlayState | null | undefined): state is OverlayState {
  return Boolean(state && !state.mid_game_attach && state.cards.length > 0 && (state.game_active || state.game_over));
}
