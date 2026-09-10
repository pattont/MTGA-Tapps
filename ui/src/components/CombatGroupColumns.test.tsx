import { describe, expect, it } from 'vitest';
import { withScryShare } from './CombatGroupColumns';

describe('withScryShare', () => {
  it('appends the share of everything scried, in plain text', () => {
    expect(withScryShare(1, 1, 2)).toBe('1 (33%)');
    expect(withScryShare(2, 1, 2)).toBe('2 (67%)');
    expect(withScryShare(3, 3, 5)).toBe('3 (38%)');
    // Per-game averages work the same way as totals.
    expect(withScryShare(1.25, 1.25, 1.75)).toBe('1.25 (42%)');
  });

  it('shows the bare number until anything has been scried, and nothing when untracked', () => {
    expect(withScryShare(0, 0, 0)).toBe('0');
    expect(withScryShare(null, 1, 2)).toBeNull();
    expect(withScryShare(undefined, undefined, undefined)).toBeNull();
  });
});
