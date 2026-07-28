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

  it('renders a data table fallback inside a collapsed details element', () => {
    const { container } = render(<TrendChart rows={rows} />);

    const details = container.querySelector('details.chart-data-details');
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute('open');
    expect(screen.getByText('View as table')).toBeInTheDocument();
    expect(details?.querySelectorAll('tbody tr')).toHaveLength(5);
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
});
