/**
 * Auto-scroll for card lists taller than the OBS source (a 100-card Brawl
 * deck). Nobody can scroll a browser source, so the list moves by itself:
 * a pause at the top, a slow glide down, a pause at the bottom, a quicker
 * glide back. Pure timing here; widgets/AutoScroll.tsx drives it.
 */

export type ScrollPhase = 'top' | 'down' | 'bottom' | 'up';

export interface ScrollState {
  phase: ScrollPhase;
  /** Scroll position, in the list's own pixels. */
  position: number;
  /** When the current pause began (ms). */
  since: number;
}

/** Pause at the top, long enough to read the first rows. */
export const HOLD_TOP_MS = 3500;
/** Pause at the bottom. */
export const HOLD_BOTTOM_MS = 2500;
/** Glide speed down, pixels per second: slow enough to read names. */
export const SPEED_DOWN = 22;
/** Back up three times faster. */
export const SPEED_UP = 66;

export function startScroll(now: number): ScrollState {
  return { phase: 'top', position: 0, since: now };
}

/**
 * The next state, `elapsed` ms after the last step, for a list that can
 * scroll `max` pixels (0 or less: it fits, so it stays at the top).
 */
export function stepScroll(state: ScrollState, now: number, elapsed: number, max: number): ScrollState {
  if (max <= 1) return startScroll(now);
  const seconds = Math.max(0, elapsed) / 1000;
  switch (state.phase) {
    case 'top':
      return now - state.since >= HOLD_TOP_MS ? { phase: 'down', position: 0, since: now } : { ...state, position: 0 };
    case 'down': {
      const position = Math.min(max, state.position + SPEED_DOWN * seconds);
      return position >= max ? { phase: 'bottom', position: max, since: now } : { ...state, position };
    }
    case 'bottom':
      return now - state.since >= HOLD_BOTTOM_MS
        ? { phase: 'up', position: max, since: now }
        : { ...state, position: Math.min(max, state.position) };
    case 'up': {
      const position = Math.max(0, Math.min(max, state.position) - SPEED_UP * seconds);
      return position <= 0 ? startScroll(now) : { ...state, position };
    }
  }
}
