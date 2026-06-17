import { describe, expect, it } from 'vitest';
import { compareValues, sortRows } from './sort';

describe('compareValues', () => {
  it('sorts numbers before blanks in ascending order', () => {
    expect([null, 3, 1, undefined].sort(compareValues)).toEqual([1, 3, null, undefined]);
  });

  it('sorts percentage strings numerically', () => {
    expect(['57.4%', '9%', '100%'].sort(compareValues)).toEqual(['9%', '57.4%', '100%']);
  });

  it('sorts ISO-like dates by time', () => {
    expect(['2026-06-05T00:00:00', '2026-06-04T00:00:00'].sort(compareValues)).toEqual([
      '2026-06-04T00:00:00',
      '2026-06-05T00:00:00',
    ]);
  });

  it('sorts strings case-insensitively', () => {
    expect(['Boros', 'azorius'].sort(compareValues)).toEqual(['azorius', 'Boros']);
  });
});

describe('sortRows', () => {
  it('does not mutate the original rows', () => {
    const rows = [
      { deck: 'Boros', games: 1 },
      { deck: 'Azorius', games: 4 },
    ];
    const sorted = sortRows(rows, 'games', 'desc');

    expect(sorted.map((row) => row.games)).toEqual([4, 1]);
    expect(rows.map((row) => row.games)).toEqual([1, 4]);
  });

  it('accepts interface-shaped row types', () => {
    interface ApiDeckRow {
      deck_name: string;
      win_rate: number | null;
    }

    const rows: ApiDeckRow[] = [
      { deck_name: 'Azorius Control', win_rate: 50 },
      { deck_name: 'Boros Mouse', win_rate: 66.7 },
      { deck_name: 'Dimir Midrange', win_rate: null },
    ];

    expect(sortRows(rows, 'win_rate', 'desc').map((row) => row.deck_name)).toEqual([
      'Boros Mouse',
      'Azorius Control',
      'Dimir Midrange',
    ]);
  });

  it('keeps blank values last when sorting descending', () => {
    const rows = [
      { deck: 'Boros', winRate: null },
      { deck: 'Azorius', winRate: 42 },
      { deck: 'Dimir', winRate: undefined },
      { deck: 'Gruul', winRate: 58 },
    ];

    expect(sortRows(rows, 'winRate', 'desc').map((row) => row.deck)).toEqual([
      'Gruul',
      'Azorius',
      'Boros',
      'Dimir',
    ]);
  });
});
