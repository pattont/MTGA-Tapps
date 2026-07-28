import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { RankProgressRow } from '../api';
import { RankProgressChart } from './RankProgressChart';

function makeRow(overrides: Partial<RankProgressRow>): RankProgressRow {
  return {
    id: 1,
    captured_at: '2026-07-01T10:00:00Z',
    season_ordinal: 42,
    rank_class: 'Gold',
    rank_level: 4,
    rank_step: 1,
    rank_steps: 6,
    raw_step: 1,
    rank_score: 49,
    rank_label: 'Gold 4 (1/6)',
    matches_won: 3,
    matches_lost: 1,
    mythic_percentile: null,
    mythic_rank: null,
    game_id: null,
    outcome: null,
    best_of: 1,
    deck_name: null,
    ...overrides,
  };
}

describe('RankProgressChart', () => {
  const rows = [
    makeRow({ id: 1 }),
    makeRow({
      id: 2,
      captured_at: '2026-07-02T10:00:00Z',
      raw_step: 2,
      rank_step: 2,
      rank_score: 50,
      rank_label: 'Gold 4 (2/6)',
      matches_won: 4,
    }),
  ];

  it('shows the empty state without snapshots', () => {
    render(<RankProgressChart rows={[]} />);

    expect(
      screen.getByText('No constructed rank snapshots have been captured yet.'),
    ).toBeInTheDocument();
  });

  it('labels the svg with a data summary', () => {
    const { container } = render(<RankProgressChart rows={rows} />);

    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('aria-label', 'Rank progress across 2 snapshots, currently Gold 4 (2/6)');
  });

  it('renders points with reduced radius and non-scaling stroke', () => {
    const { container } = render(<RankProgressChart rows={rows} />);

    const circles = container.querySelectorAll('circle.rank-progress-point');
    expect(circles).toHaveLength(2);
    circles.forEach((circle) => {
      expect(circle).toHaveAttribute('r', '3.5');
      expect(circle).toHaveAttribute('vector-effect', 'non-scaling-stroke');
    });
  });

});
