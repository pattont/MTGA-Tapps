import { describe, expect, it } from 'vitest';
import { withPlayDrawShare } from './playDrawShare';

function row(play_draw: string | null, games: number) {
  return { play_draw, games, wins: 0, losses: 0, win_rate: null };
}

describe('withPlayDrawShare', () => {
  it('splits the games whose turn order is known, leaving Unknown out', () => {
    const rows = withPlayDrawShare([row('On the play', 30), row('On the draw', 10), row('Unknown', 60)]);
    expect(rows.map((r) => r.share)).toEqual([75, 25, null]);
  });

  it('has no share without known games', () => {
    expect(withPlayDrawShare([row('Unknown', 4)])[0].share).toBeNull();
    expect(withPlayDrawShare([])).toEqual([]);
  });
});
