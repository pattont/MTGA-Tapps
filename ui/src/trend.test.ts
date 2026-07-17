import { describe, expect, it } from 'vitest';
import { rollingWinRates } from './trend';

function row(outcome: string, index: number) {
  return { game_id: `game-${index}`, started_at: `2026-06-0${index + 1}T00:00:00`, outcome };
}

describe('rollingWinRates', () => {
  it('returns an empty list for no games', () => {
    expect(rollingWinRates([])).toEqual([]);
  });

  it('expands the window until it is full, then rolls', () => {
    const rows = ['win', 'loss', 'win', 'win'].map(row);
    const points = rollingWinRates(rows, 2);

    expect(points.map((point) => point.rate)).toEqual([100, 50, 50, 100]);
    expect(points[3].started_at).toBe(rows[3].started_at);
  });
});
