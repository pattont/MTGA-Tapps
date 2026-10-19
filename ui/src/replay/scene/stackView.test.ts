import { describe, expect, it } from 'vitest';
import { compactExits, stackCardWidth, stackRows } from './stackView';

describe('stackRows', () => {
  it('keeps the top card full size and shows only the rows that fit the stage', () => {
    expect(stackRows(0, 659)).toEqual({ full: 0, chips: 0 });
    // Unmeasured: the old generous rule.
    expect(stackRows(2, null)).toEqual({ full: 2, chips: 0 });
    expect(stackRows(9, null)).toEqual({ full: 1, chips: 6 });
    // A 659 px stage fits one full card plus two compact rows, never two full cards.
    expect(stackCardWidth(659)).toBe(240);
    expect(stackCardWidth(500)).toBeCloseTo((500 - 224) / 1.395, 6);
    expect(stackRows(1, 659)).toEqual({ full: 1, chips: 0 });
    expect(stackRows(2, 659)).toEqual({ full: 1, chips: 1 });
    expect(stackRows(9, 659)).toEqual({ full: 1, chips: 2 });
    // The top card is the same width whether the stack holds one item or nine.
    expect(stackCardWidth(659)).toBe(stackCardWidth(659));
    // A tall stage fits two full cards, and up to six compact rows under one.
    expect(stackRows(2, 1370)).toEqual({ full: 2, chips: 0 });
    expect(stackRows(12, 1370)).toEqual({ full: 1, chips: 6 });
    // Width limits.
    expect(stackCardWidth(300)).toBe(150);
    expect(stackCardWidth(2000)).toBe(240);
  });
});

describe('compactExits', () => {
  it('keeps a countered spell full size when only one card fits', () => {
    // A counterspell resolved, then the spell it countered: room for one full card.
    const exits = [{ exit: 'resolved' as const }, { exit: 'countered' as const }];
    expect(compactExits(exits, 1)).toEqual([true, false]);
    expect(compactExits(exits, 2)).toEqual([false, false]);
    // Otherwise the newest keeps its full card.
    expect(compactExits([{ exit: 'resolved' as const }, { exit: 'resolved' as const }], 1)).toEqual([true, false]);
    expect(compactExits([{ exit: 'fizzled' as const }, { exit: 'resolved' as const }], 1)).toEqual([false, true]);
  });
});
