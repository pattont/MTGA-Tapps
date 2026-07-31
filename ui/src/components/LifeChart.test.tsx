import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { LifePoint } from '../api';
import { LifeChart } from './LifeChart';

const points: LifePoint[] = [
  { turn_number: 1, player_life: 20, opponent_life: 20 },
  { turn_number: 2, player_life: 18, opponent_life: 15 },
  { turn_number: 3, player_life: 12, opponent_life: 8 },
];

function hoverAt(wrap: HTMLElement, clientX: number, width = 600) {
  wrap.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width, height: 150, right: width, bottom: 150, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  fireEvent.mouseMove(wrap, { clientX });
}

describe('LifeChart', () => {
  it('shows the empty state with fewer than two points', () => {
    render(<LifeChart points={[points[0]]} />);

    expect(screen.getByText('Not enough life-total data for this game yet.')).toBeInTheDocument();
  });

  it('exposes the svg to screen readers with a data summary', () => {
    const { container } = render(<LifeChart points={points} />);

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).not.toHaveAttribute('aria-hidden');
    expect(svg).toHaveAttribute('role', 'img');
    expect(svg).toHaveAttribute('aria-label', 'Life totals over 3 recorded points, final 12 versus 8');
  });

  it('differentiates the opponent line with a dash pattern', () => {
    const { container } = render(<LifeChart points={points} />);

    expect(container.querySelector('.life-line-opponent')).toHaveAttribute('stroke-dasharray', '5 3');
    expect(container.querySelector('.life-line-player')).not.toHaveAttribute('stroke-dasharray');
  });

  it('renders legend color swatches for both series', () => {
    const { container } = render(<LifeChart points={points} />);

    expect(container.querySelector('.life-legend-swatch-player')).not.toBeNull();
    expect(container.querySelector('.life-legend-swatch-opponent')).not.toBeNull();
  });

  it('renders min and max life axis labels', () => {
    const { container } = render(<LifeChart points={points} />);

    // HTML floats, not SVG <text>: SVG text distorts under preserveAspectRatio="none".
    const labels = Array.from(container.querySelectorAll('.life-axis-label')).map(
      (node) => node.textContent,
    );
    expect(labels).toEqual(['20', '0']);
  });

  it('renders a data table fallback inside a collapsed details element', () => {
    const { container } = render(<LifeChart points={points} />);

    const details = container.querySelector('details.chart-data-details');
    expect(details).not.toBeNull();
    expect(screen.getByText('View as table')).toBeInTheDocument();
    expect(details?.querySelectorAll('tbody tr')).toHaveLength(3);
    expect(details?.textContent).toContain('Opponent life');
  });

  it('shows a tooltip on hover and clears it on mouse leave', () => {
    const { container } = render(<LifeChart points={points} />);
    const wrap = container.querySelector('.life-svg-wrap') as HTMLElement;

    hoverAt(wrap, 300);

    const tooltip = container.querySelector('.chart-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip?.textContent).toContain('Turn 2');
    expect(tooltip?.textContent).toContain('18');
    expect(tooltip?.textContent).toContain('15');

    fireEvent.mouseLeave(wrap);

    expect(container.querySelector('.chart-tooltip')).toBeNull();
  });

  it('renders a turn axis with one tick per turn', () => {
    const { container } = render(<LifeChart points={points} />);

    const ticks = Array.from(container.querySelectorAll('.life-axis-tick')).map(
      (node) => node.textContent,
    );
    expect(ticks).toEqual(['T1', 'T2', 'T3']);
    expect(container.querySelectorAll('.life-turn-grid')).toHaveLength(3);
  });

  it('ignores hover when the chart has no measurable width (jsdom default)', () => {
    const { container } = render(<LifeChart points={points} />);
    const wrap = container.querySelector('.life-svg-wrap') as HTMLElement;

    fireEvent.mouseMove(wrap);

    expect(container.querySelector('.chart-tooltip')).toBeNull();
  });
});
