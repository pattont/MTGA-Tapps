import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { drawStatusOf, drawStatusSortValue } from '../drawStatus';
import { DrawStatusBadge } from './DrawStatusBadge';

describe('DrawStatusBadge', () => {
  it('ranks flood over screw over a land streak', () => {
    expect(drawStatusOf({ is_flood: true, is_screw: true, is_land_streak: true })).toBe('flood');
    expect(drawStatusOf({ is_screw: true, is_land_streak: true })).toBe('screw');
    expect(drawStatusOf({ is_land_streak: true })).toBe('streak');
    expect(drawStatusOf({})).toBe('normal');
    const order = [{}, { is_land_streak: true }, { is_screw: true }, { is_flood: true }].map(drawStatusSortValue);
    expect(order).toEqual([0, 1, 2, 3]);
  });

  it('renders a soft Land streak badge with an explanation on hover', () => {
    render(<DrawStatusBadge row={{ is_land_streak: true }} />);
    const badge = screen.getByText('Land streak');
    expect(badge).toHaveClass('badge-streak');
    expect(badge).toHaveAttribute('title', expect.stringMatching(/no more lands than expected/));
  });

  it('renders plain Normal text without a badge', () => {
    const { container } = render(<DrawStatusBadge row={{ is_flood: false }} />);
    expect(container).toHaveTextContent('Normal');
    expect(container.querySelector('.badge')).toBeNull();
  });
});
