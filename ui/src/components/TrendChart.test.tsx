import { createEvent, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TrendRow } from '../api';
import { TrendChart } from './TrendChart';

function makeRows(outcomes: string[]): TrendRow[] {
  return outcomes.map((outcome, index) => ({
    game_id: `game-${index}`,
    started_at: `2026-07-0${index + 1}T10:00:00Z`,
    outcome,
  }));
}

function hoverAt(svg: SVGSVGElement, offsetX: number, clientWidth = 600) {
  Object.defineProperty(svg, 'clientWidth', { value: clientWidth, configurable: true });
  const event = createEvent.mouseMove(svg);
  Object.defineProperty(event, 'offsetX', { value: offsetX, configurable: true });
  fireEvent(svg, event);
}

describe('TrendChart', () => {
  const rows = makeRows(['win', 'win', 'loss', 'win', 'loss']);

  it('shows the empty state with fewer than five games', () => {
    render(<TrendChart rows={makeRows(['win', 'loss'])} />);

    expect(screen.getByText('Not enough finished games to chart a trend yet.')).toBeInTheDocument();
  });

  it('exposes the svg to screen readers with a data summary', () => {
    const { container } = render(<TrendChart rows={rows} />);

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).not.toHaveAttribute('aria-hidden');
    expect(svg).toHaveAttribute('role', 'img');
    expect(svg).toHaveAttribute('aria-label', 'Rolling win rate across 5 games, currently 60%');
  });

  it('renders no data-table fallback (removed to keep the section lean)', () => {
    const { container } = render(<TrendChart rows={rows} />);

    expect(container.querySelector('details.chart-data-details')).toBeNull();
    expect(screen.queryByText('View as table')).not.toBeInTheDocument();
  });

  it('renders a right-edge current-value label', () => {
    const { container } = render(<TrendChart rows={rows} />);

    // HTML float, not SVG <text>: SVG text distorts under preserveAspectRatio="none".
    const label = container.querySelector('.chart-axis-float-right');
    expect(label).not.toBeNull();
    expect(label?.textContent).toBe('60%');
  });

  it('shows a tooltip and crosshair on hover and clears on mouse leave', () => {
    const { container } = render(<TrendChart rows={rows} />);
    const svg = container.querySelector('svg') as SVGSVGElement;

    hoverAt(svg, 300);

    const tooltip = container.querySelector('.chart-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip?.textContent).toContain('67%');
    expect(container.querySelector('.chart-hover-line')).not.toBeNull();

    fireEvent.mouseLeave(svg);

    expect(container.querySelector('.chart-tooltip')).toBeNull();
    expect(container.querySelector('.chart-hover-line')).toBeNull();
  });

  it('ignores hover when the svg has no measurable width (jsdom default)', () => {
    const { container } = render(<TrendChart rows={rows} />);
    const svg = container.querySelector('svg') as SVGSVGElement;

    fireEvent.mouseMove(svg);

    expect(container.querySelector('.chart-tooltip')).toBeNull();
  });

  it('shows the year on both ends of the date axis', () => {
    const historicalRows = [
      { game_id: '1', started_at: '2025-04-23T12:00:00', outcome: 'win' },
      { game_id: '2', started_at: '2025-06-10T12:00:00', outcome: 'loss' },
      { game_id: '3', started_at: '2025-09-01T12:00:00', outcome: 'win' },
      { game_id: '4', started_at: '2026-02-12T12:00:00', outcome: 'loss' },
      { game_id: '5', started_at: '2026-09-23T12:00:00', outcome: 'win' },
    ];

    render(<TrendChart rows={historicalRows} />);

    expect(screen.getByText(/Apr.*23.*2025/)).toBeInTheDocument();
    expect(screen.getByText(/Sep.*23.*2026/)).toBeInTheDocument();
  });

  it('plots only the selected games while using earlier games for the rolling rate', () => {
    const historicalRows = Array.from({ length: 40 }, (_, index) => ({
      game_id: String(index),
      started_at: `2026-06-01T12:${String(index).padStart(2, '0')}:00`,
      outcome: index < 20 ? 'win' : 'loss',
    }));

    const { container } = render(<TrendChart rows={historicalRows} visibleGames={10} showSummary />);

    expect(screen.getByRole('img', { name: 'Rolling win rate across 10 games, currently 33%' })).toBeInTheDocument();
    const summary = screen.getByLabelText('Average win rate and rolling extremes');
    expect(summary).toHaveTextContent('Average Win Rate0%');
    expect(summary).toHaveTextContent('Low %33%');
    expect(summary).toHaveTextContent('High %63%');
    expect(container.querySelector('.trend-axis-record')).toHaveTextContent('10 games · 0 wins / 10 losses');
    expect(container.querySelectorAll('.trend-point')).toHaveLength(3);
  });

  it('shows the selected period record under the chart', () => {
    render(<TrendChart rows={rows} showSummary />);

    const summary = screen.getByLabelText('Average win rate and rolling extremes');
    expect(summary).toHaveTextContent('Average Win Rate60%');
    expect(summary).toHaveTextContent('Low %—');
    expect(summary).toHaveTextContent('High %—');
    expect(screen.getByText('5 games · 3 wins / 2 losses')).toBeInTheDocument();
    expect(screen.queryByText('50% guide')).not.toBeInTheDocument();
  });
});
