import { describe, expect, it } from 'vitest';
import { formatTopVsBottom } from './CombatGroupColumns';

describe('formatTopVsBottom', () => {
  it('splits scried cards into a top/bottom share that sums to 100', () => {
    expect(formatTopVsBottom(1, 2)).toBe('33%/67%');
    expect(formatTopVsBottom(3, 5)).toBe('38%/62%');
    expect(formatTopVsBottom(2, 0)).toBe('100%/0%');
    // Per-game averages work the same way as totals.
    expect(formatTopVsBottom(0.5, 1.5)).toBe('25%/75%');
  });

  it('is absent until something has been scried', () => {
    expect(formatTopVsBottom(0, 0)).toBeNull();
    expect(formatTopVsBottom(null, 2)).toBeNull();
    expect(formatTopVsBottom(undefined, undefined)).toBeNull();
  });
});
