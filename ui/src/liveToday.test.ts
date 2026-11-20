import { describe, expect, it } from 'vitest';
import type { LiveGameRow, LivePayload } from './api';
import { todayGames, todayView } from './liveToday';

const NOW = new Date(2026, 10, 9, 21, 0, 0).getTime();

function game(id: string, outcome: string, startedAt: string): LiveGameRow {
  return { id, outcome, started_at: startedAt } as LiveGameRow;
}

/** Today is 2–2 over two tracker sessions; the morning's loss came from the first. */
function payload(overrides: Partial<LivePayload> = {}): LivePayload {
  return {
    tracker: { state: 'idle' },
    now: null,
    today: {
      date: '2026-11-09',
      games: 4,
      wins: 2,
      losses: 2,
      draws: 0,
      win_rate: 50,
      started_at: '2026-11-09T09:00:00',
      play: { wins: 2, losses: 1 },
      draw: { wins: 0, losses: 1 },
      decks: [
        { deck_name: 'Boros Dragons', wins: 2, losses: 1 },
        { deck_name: 'Kanister Artifacts', wins: 0, losses: 1 },
      ],
      flood_games: 1,
      screw_games: 1,
    },
    games: [
      game('S2:g3', 'win', '2026-11-09T20:40:00'),
      game('S2:g2', 'win', '2026-11-09T20:20:00'),
      game('S2:g1', 'loss', '2026-11-09T20:00:00'),
      game('S1:g1', 'loss', '2026-11-09T09:00:00'),
    ],
    events: [],
    seq: 0,
    ...overrides,
  } as LivePayload;
}

describe('todayView', () => {
  it('reads today across tracker sessions: record, sides, streak and decks', () => {
    expect(todayView(payload(), NOW)).toEqual({
      wins: 2,
      losses: 2,
      draws: 0,
      games: 4,
      winRate: 50,
      play: { wins: 2, losses: 1 },
      draw: { wins: 0, losses: 1 },
      streak: { outcome: 'win', length: 2 },
      floodGames: 1,
      screwGames: 1,
      decks: [
        { deck_name: 'Boros Dragons', wins: 2, losses: 1 },
        { deck_name: 'Kanister Artifacts', wins: 0, losses: 1 },
      ],
    });
  });

  it('counts a streak over all of today, whichever session played it', () => {
    const games = [game('S2:g2', 'loss', '2026-11-09T20:20:00'), game('S2:g1', 'loss', '2026-11-09T20:00:00'), game('S1:g1', 'loss', '2026-11-09T09:00:00')];
    expect(todayView(payload({ games }), NOW)?.streak).toEqual({ outcome: 'loss', length: 3 });
  });

  it('has no streak after a draw or before a game, and fills in what an older tracker leaves out', () => {
    const drawn = [game('S2:g2', 'draw', '2026-11-09T20:20:00'), game('S2:g1', 'win', '2026-11-09T20:00:00')];
    expect(todayView(payload({ games: drawn }), NOW)?.streak).toBeNull();
    const old = payload({ games: [] });
    old.today = { ...old.today!, decks: undefined, flood_games: undefined, screw_games: undefined };
    expect(todayView(old, NOW)).toMatchObject({ streak: null, floodGames: null, screwGames: null, decks: [] });
  });

  it('lists exactly the games today counts', () => {
    const ids = (nowMs: number) => todayGames(payload(), nowMs).map((g) => g.id);
    expect(ids(NOW)).toEqual(['S2:g3', 'S2:g2', 'S2:g1', 'S1:g1']);
    // After midnight yesterday's games are not today's, even the last one played.
    expect(ids(new Date(2026, 10, 10, 0, 3, 0).getTime())).toEqual([]);
  });

  it('is null before the tracker has written anything', () => {
    expect(todayView(null, NOW)).toBeNull();
    expect(todayView(payload({ today: null }), NOW)).toBeNull();
  });
});
