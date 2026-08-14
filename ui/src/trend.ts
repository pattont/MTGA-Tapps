import type { TrendRow } from './api';

export const TREND_WINDOW = 30;

export interface TrendPoint {
  rate: number;
  started_at: string;
}

export function rollingWinRates(rows: TrendRow[], window: number = TREND_WINDOW): TrendPoint[] {
  const points: TrendPoint[] = [];
  for (let i = 0; i < rows.length; i += 1) {
    const start = Math.max(0, i - window + 1);
    let wins = 0;
    for (let j = start; j <= i; j += 1) {
      if (rows[j].outcome === 'win') {
        wins += 1;
      }
    }
    points.push({ rate: (100 * wins) / (i - start + 1), started_at: rows[i].started_at });
  }
  return points;
}
