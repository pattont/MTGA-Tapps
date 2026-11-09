import { describe, expect, it } from 'vitest';
import { HOLD_BOTTOM_MS, HOLD_TOP_MS, SPEED_DOWN, SPEED_UP, startScroll, stepScroll } from './autoScroll';

describe('auto-scroll', () => {
  it('stays at the top while the list fits', () => {
    const state = stepScroll({ phase: 'down', position: 40, since: 0 }, 5000, 16, 0);
    expect(state).toEqual(startScroll(5000));
  });

  it('pauses, glides down, pauses, and glides back up faster', () => {
    const max = 100;
    let state = startScroll(0);
    state = stepScroll(state, HOLD_TOP_MS - 1, 16, max);
    expect(state).toMatchObject({ phase: 'top', position: 0 });
    state = stepScroll(state, HOLD_TOP_MS, 16, max);
    expect(state.phase).toBe('down');

    let t = HOLD_TOP_MS;
    state = stepScroll(state, (t += 1000), 1000, max);
    expect(state).toMatchObject({ phase: 'down', position: SPEED_DOWN });
    state = stepScroll(state, (t += 10_000), 10_000, max);
    expect(state).toMatchObject({ phase: 'bottom', position: max, since: t });

    state = stepScroll(state, t + HOLD_BOTTOM_MS - 1, 16, max);
    expect(state.phase).toBe('bottom');
    state = stepScroll(state, (t += HOLD_BOTTOM_MS), 16, max);
    expect(state.phase).toBe('up');
    state = stepScroll(state, (t += 1000), 1000, max);
    expect(state).toMatchObject({ phase: 'up', position: max - SPEED_UP });
    state = stepScroll(state, (t += 5000), 5000, max);
    expect(state).toEqual(startScroll(t));
  });

  it('copes with a list that shrinks mid-scroll', () => {
    const state = stepScroll({ phase: 'bottom', position: 300, since: 0 }, 10, 10, 120);
    expect(state.position).toBe(120);
  });
});
