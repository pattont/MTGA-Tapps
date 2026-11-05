import { describe, expect, it } from 'vitest';
import { formatTimeAgo } from './format';

describe('formatTimeAgo', () => {
  const now = new Date(2026, 10, 4, 9, 30);

  it('counts calendar days, not 24-hour spans', () => {
    expect(formatTimeAgo(new Date(2026, 10, 4, 0, 5).toISOString(), now)).toBe('today');
    expect(formatTimeAgo(new Date(2026, 10, 3, 23, 50).toISOString(), now)).toBe('yesterday');
    expect(formatTimeAgo(new Date(2026, 10, 1, 12).toISOString(), now)).toBe('3 days ago');
  });

  it('rounds longer spans down to weeks, months and years', () => {
    expect(formatTimeAgo(new Date(2026, 9, 20).toISOString(), now)).toBe('2 weeks ago');
    expect(formatTimeAgo(new Date(2026, 7, 1).toISOString(), now)).toBe('3 months ago');
    expect(formatTimeAgo(new Date(2023, 10, 1).toISOString(), now)).toBe('3 years ago');
  });

  it('returns null for unreadable timestamps', () => {
    expect(formatTimeAgo('not a date', now)).toBeNull();
  });
});
