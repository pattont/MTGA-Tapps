import { describe, expect, it } from 'vitest';
import { formatHoursMinutes, formatTimeAgo } from './format';

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

describe('formatHoursMinutes', () => {
  it('reads minutes under an hour, hours and minutes above', () => {
    expect(formatHoursMinutes(45 * 60)).toBe('45m');
    expect(formatHoursMinutes(3 * 3600 + 20 * 60)).toBe('3h 20m');
    expect(formatHoursMinutes(2 * 3600 + 4 * 60)).toBe('2h 04m');
    expect(formatHoursMinutes(null)).toBe('—');
  });
});
