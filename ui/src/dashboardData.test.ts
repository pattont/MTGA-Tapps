import { describe, expect, it } from 'vitest';
import { formatPercent, metricCards } from './dashboardData';
import type { DashboardSnapshot } from './api';

const deckVisual = {
  card_id: null,
  card_name: null,
  type_category: 'Other',
  image_url: null,
  source: 'deck_name' as const,
};

function snapshotWithDecks(decks: DashboardSnapshot['decks']): DashboardSnapshot {
  return {
    summary: { games: 0, wins: 0, losses: 0, draws: 0, win_rate: null },
    decks,
    formats: [],
    midweek_formats: [],
    play_draw: [],
    deck_play_draw: [],
    draw_quality: [],
    drawn_cards: [],
    momentum: [],
    combat_decks: [],
    combat_split: [],
    mana_readiness: [],
    schedule: { by_weekday: [], by_time_of_day: [] },
    fatigue: [],
    streaks: { games: 0, current: null, longest_win: 0, longest_loss: 0 },
    outcome_reasons: [],
    opener_lands: [],
    recent: [],
    matches: [],
    sessions: [],
    trend: [],
    filter_options: { decks: [], formats: [] },
  };
}

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
      combat_decks: [],
      combat_split: [],
      mana_readiness: [],
      schedule: { by_weekday: [], by_time_of_day: [] },
      fatigue: [],
      streaks: { games: 0, current: null, longest_win: 0, longest_loss: 0 },
      outcome_reasons: [],
      opener_lands: [],
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
      {
        label: 'Best Deck (small sample)',
        value: 'Boros Mouse',
        detail: '66.7% WR · 2–1 · 3 games',
        href: '#/deck/Boros%20Mouse',
      },
    ]);
  });

  it('favors a proven winning record over a one-game perfect record', () => {
    const snapshot = snapshotWithDecks([
      {
        deck_name: 'One Game Wonder',
        games: 1,
        wins: 1,
        losses: 0,
        win_rate: 100,
        deck_visual: deckVisual,
      },
      {
        deck_name: 'Proven Deck',
        games: 100,
        wins: 60,
        losses: 40,
        win_rate: 60,
        deck_visual: deckVisual,
      },
    ]);

    expect(metricCards(snapshot).find((metric) => metric.label === 'Best Deck')).toMatchObject({
      value: 'Proven Deck',
      detail: '60% WR · 60–40 · 100 games',
    });
  });

  it('still rewards a meaningfully stronger win rate with a credible sample', () => {
    const snapshot = snapshotWithDecks([
      {
        deck_name: 'High Volume Average',
        games: 100,
        wins: 50,
        losses: 50,
        win_rate: 50,
        deck_visual: deckVisual,
      },
      {
        deck_name: 'Strong Challenger',
        games: 10,
        wins: 8,
        losses: 2,
        win_rate: 80,
        deck_visual: deckVisual,
      },
    ]);

    expect(metricCards(snapshot).find((metric) => metric.label === 'Best Deck')).toMatchObject({
      value: 'Strong Challenger',
      detail: '80% WR · 8–2 · 10 games',
    });
  });
});


describe('best deck minimum sample', () => {
  const deckVisual = {
    card_id: null,
    card_name: 'Deck',
    type_category: 'Creature',
    image_url: null,
    source: 'deck_name' as const,
  };

  it('prefers a deck with a credible sample over a hot 4-0 deck', () => {
    const snapshot = snapshotWithDecks([
      { deck_name: 'Hot Streak', games: 4, wins: 4, losses: 0, win_rate: 100, deck_visual: deckVisual },
      { deck_name: 'Workhorse', games: 40, wins: 24, losses: 16, win_rate: 60, deck_visual: deckVisual },
    ]);

    expect(metricCards(snapshot).find((metric) => metric.label.startsWith('Best Deck'))).toMatchObject({
      label: 'Best Deck',
      value: 'Workhorse',
    });
  });

  it('falls back to small samples when nothing has enough games, with a caveat', () => {
    const snapshot = snapshotWithDecks([
      { deck_name: 'Only Deck', games: 3, wins: 2, losses: 1, win_rate: 66.7, deck_visual: deckVisual },
    ]);

    expect(metricCards(snapshot).find((metric) => metric.label.startsWith('Best Deck'))).toMatchObject({
      label: 'Best Deck (small sample)',
      value: 'Only Deck',
    });
  });
});
