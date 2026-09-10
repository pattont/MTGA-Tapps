import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { withScryShare } from './CombatGroupColumns';

function text(node: ReturnType<typeof withScryShare>): string {
  const { container } = render(<>{node}</>);
  return container.textContent ?? '';
}

describe('withScryShare', () => {
  it('appends the share of everything scried as the muted suffix', () => {
    expect(text(withScryShare(1, 1, 2))).toBe('1 (33%)');
    expect(text(withScryShare(2, 1, 2))).toBe('2 (67%)');
    expect(text(withScryShare(3, 3, 5))).toBe('3 (38%)');
    // Per-game averages work the same way as totals.
    expect(text(withScryShare(1.25, 1.25, 1.75))).toBe('1.25 (42%)');
    const { container } = render(<>{withScryShare(1, 1, 2)}</>);
    expect(container.querySelector('.stat-drawn-suffix')?.textContent).toBe('(33%)');
  });

  it('shows the bare number until anything has been scried, and nothing when untracked', () => {
    expect(withScryShare(0, 0, 0)).toBe('0');
    expect(withScryShare(null, 1, 2)).toBeNull();
    expect(withScryShare(undefined, undefined, undefined)).toBeNull();
  });
});
