import { describe, expect, it } from 'vitest';
import { formatPercent, metricCards } from './dashboardData';
import type { DashboardSnapshot } from './api';

describe('formatPercent', () => {
  it('formats numbers and blanks', () => {
    expect(formatPercent(57.4)).toBe('57.4%');
    expect(formatPercent(null)).toBe('—');
  });
});

describe('metricCards', () => {
  it('derives overview metrics from the snapshot', () => {
    const snapshot = {
      summary: { games: 3, wins: 2, losses: 1, draws: 0, win_rate: 66.7 },
      decks: [
        {
          deck_name: 'Boros Mouse',
          games: 3,
          wins: 2,
          losses: 1,
          win_rate: 66.7,
          deck_visual: {
            card_id: null,
            card_name: 'Boros Mouse',
            type_category: 'Creature',
            image_url: null,
            source: 'deck_name',
          },
        },
      ],
      formats: [],
      midweek_formats: [],
      play_draw: [],
      deck_play_draw: [],
      draw_quality: [],
      drawn_cards: [],
      momentum: [],
      recent: [],
      matches: [],
      sessions: [],
      trend: [],
      filter_options: { decks: [], formats: [] },
    } satisfies DashboardSnapshot;

    expect(metricCards(snapshot)).toEqual([
      { label: 'Games', value: '3' },
      { label: 'Wins', value: '2' },
      { label: 'Losses', value: '1' },
      { label: 'Win Rate', value: '66.7%' },
      { label: 'Best Deck', value: 'Boros Mouse', href: '#/deck/Boros%20Mouse' },
    ]);
  });
});
