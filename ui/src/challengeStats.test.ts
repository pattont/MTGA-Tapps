import { describe, expect, it } from 'vitest';
import type { ChallengeFriendRow, ChallengeGameRow } from './api';
import { challengeStats, streakLabel } from './challengeStats';

let next = 0;
function game(overrides: Partial<ChallengeGameRow>): ChallengeGameRow {
  next += 1;
  return {
    game_id: `g${next}`,
    match_id: `m${next}`,
    started_at: `2026-11-01T10:${String(next).padStart(2, '0')}:00`,
    deck_name: 'Mono Red',
    deck_colors: 'R',
    format_label: 'Direct Challenge',
    outcome: 'win',
    mulligans: 0,
    went_first: 1,
    duration_seconds: 600,
    total_turns: 8,
    flood_reasons: [],
    is_flood: false,
    cards_seen: 15,
    lands_seen: 6,
    land_seen_pct: 40,
    opponent_name: 'Pal',
    ...overrides,
  };
}

function friend(name: string, wins: number, losses: number): ChallengeFriendRow {
  return {
    friend: name,
    matches: wins + losses,
    games: wins + losses,
    wins,
    losses,
    win_rate: wins + losses ? Math.round((wins / (wins + losses)) * 100) : null,
    last_played: null,
  };
}

describe('challengeStats', () => {
  it('counts the record, play/draw split and streaks in game order', () => {
    const games = [
      game({ outcome: 'loss', went_first: 0 }),
      game({ outcome: 'win', went_first: 1 }),
      game({ outcome: 'win', went_first: 0 }),
      game({ outcome: 'draw', went_first: 1 }),
      game({ outcome: 'win', went_first: 1 }),
    ];
    // Newest first, as the API sends them.
    const stats = challengeStats([...games].reverse(), [friend('Pal', 3, 1)]);
    expect(stats.games).toEqual({ games: 5, wins: 3, losses: 1, winRate: 75 });
    expect(stats.matches).toEqual({ games: 4, wins: 3, losses: 1, winRate: 75 });
    expect(stats.onPlay).toMatchObject({ games: 3, wins: 2, losses: 0 });
    expect(stats.onDraw).toMatchObject({ games: 2, wins: 1, losses: 1 });
    // A draw neither extends nor breaks a run.
    expect(stats.streak).toEqual({ result: 'win', length: 3 });
    expect(stats.longestWinStreak).toBe(3);
    expect(streakLabel(stats.streak)).toBe('W3');
    expect(streakLabel(null)).toBe('—');
  });

  it('names a nemesis and a favorite victim only past the match minimum', () => {
    const friends = [friend('Rival', 1, 3), friend('Victim', 4, 1), friend('Once', 0, 1), friend('Even', 2, 2)];
    const stats = challengeStats([], friends);
    expect(stats.nemesis?.friend).toBe('Rival');
    expect(stats.favoriteVictim?.friend).toBe('Victim');
    expect(challengeStats([], [friend('Once', 0, 1), friend('Even', 2, 2)]).nemesis).toBeNull();
  });

  it('picks the best and worst deck from decks with enough decided games', () => {
    const games = [
      ...['win', 'win', 'loss'].map((outcome) => game({ deck_name: 'Gruul', outcome })),
      ...['loss', 'loss', 'win'].map((outcome) => game({ deck_name: 'Izzet', outcome })),
      ...['loss', 'loss'].map((outcome) => game({ deck_name: 'Rarely', outcome })),
    ];
    const stats = challengeStats(games, []);
    expect(stats.bestDeck).toMatchObject({ deck: 'Gruul', wins: 2, losses: 1, winRate: 67 });
    expect(stats.worstDeck).toMatchObject({ deck: 'Izzet', wins: 1, losses: 2, winRate: 33 });
    expect(stats.decks.map((row) => row.deck)).toEqual(['Gruul', 'Izzet', 'Rarely']);
  });

  it('never makes one deck both best and worst', () => {
    const games = ['win', 'win', 'loss'].map((outcome) => game({ deck_name: 'Solo', outcome }));
    const stats = challengeStats(games, []);
    expect(stats.bestDeck?.deck).toBe('Solo');
    expect(stats.worstDeck).toBeNull();
  });

  it('finds the fastest win and the longest game', () => {
    const quick = game({ outcome: 'win', total_turns: 4, opponent_name: 'Speedy' });
    const quickLoss = game({ outcome: 'loss', total_turns: 3 });
    const long = game({ outcome: 'loss', duration_seconds: 2400, opponent_name: ' ' });
    const stats = challengeStats([quick, quickLoss, long], []);
    expect(stats.fastestWin).toMatchObject({ game: { game_id: quick.game_id }, friend: 'Speedy' });
    expect(stats.longestGame).toMatchObject({ game: { game_id: long.game_id }, friend: 'Opponent' });
  });

  it('gives each friend their most-shown colours and current streak', () => {
    const games = [
      game({ opponent_name: 'Pal', opp_colors: 'UB', outcome: 'loss' }),
      game({ opponent_name: 'Pal', opp_colors: 'UB', outcome: 'win' }),
      game({ opponent_name: 'Pal', opp_colors: 'R', outcome: 'win' }),
    ];
    const extras = challengeStats(games, []).friendExtras.get('Pal');
    expect(extras).toEqual({ colors: 'UB', streak: { result: 'win', length: 2 } });
  });
});
