import { describe, expect, it } from 'vitest';
import type { LiveDrawQuality, LiveNow } from './api';
import { landMeter, matchScoreText } from './liveScoreboard';

const now = (overrides: Partial<LiveNow>) => ({ match_type: 'best_of_3', match_score: { wins: 1, losses: 0, draws: 0 }, ...overrides }) as LiveNow;

describe('matchScoreText', () => {
  it('gives the score of a best-of-three, and how it ended once decided', () => {
    expect(matchScoreText(now({}))).toBe('Match 1–0');
    expect(matchScoreText(now({ match_score: { wins: 0, losses: 0, draws: 0 } }))).toBe('Match 0–0');
    expect(matchScoreText(now({ match_score: { wins: 2, losses: 1, draws: 0 } }))).toBe('Match won 2–1');
    expect(matchScoreText(now({ match_score: { wins: 0, losses: 2, draws: 0 } }))).toBe('Match lost 0–2');
  });

  it('says nothing in best-of-one or without a score', () => {
    expect(matchScoreText(now({ match_type: 'best_of_1' }))).toBeNull();
    expect(matchScoreText(now({ match_score: null }))).toBeNull();
    expect(matchScoreText(now({ match_score: undefined }))).toBeNull();
  });
});

function quality(overrides: Partial<LiveDrawQuality> = {}): LiveDrawQuality {
  return {
    lands_seen: 5,
    total_cards_seen: 12,
    ramped_lands: 0,
    expected_lands_seen: 4.8,
    expected_land_rate: 40,
    deck_size: 60,
    deck_lands: 24,
    flood_probability_pct: null,
    screw_probability_pct: null,
    is_flood: false,
    is_screw: false,
    is_land_streak: false,
    reason: null,
    next_land_pct: 39.6,
    library_size: 48,
    lands_left: 19,
    ...overrides,
  };
}

describe('landMeter', () => {
  it('places the count, the expected count and the screw and flood zones on a 0–100 gauge', () => {
    const meter = landMeter(quality());
    expect(meter).toMatchObject({ status: 'normal', lands: 5, seen: 12, expected: 4.8, diff: 0.2 });
    expect(meter.nowAt).toBeCloseTo((100 * 5) / 12);
    expect(meter.expectedAt).toBeCloseTo(40);
    // Screw on the left, flood on the right, the count in between when normal.
    expect(meter.screwEnd).toBeLessThan(meter.nowAt);
    expect(meter.floodStart).toBeGreaterThan(meter.nowAt);
  });

  it('reads flood and screw from the tracker, and the gap in lands', () => {
    expect(landMeter(quality({ lands_seen: 9, is_flood: true }))).toMatchObject({ status: 'flood', diff: 4.2 });
    expect(landMeter(quality({ lands_seen: 1, is_screw: true }))).toMatchObject({ status: 'screw', diff: -3.8 });
    expect(landMeter(quality({ is_land_streak: true })).status).toBe('streak');
  });

  it('works out the deck\'s lands from its land rate when the list is unknown, and survives no cards seen', () => {
    expect(landMeter(quality({ deck_lands: null })).floodStart).toBeCloseTo(landMeter(quality()).floodStart);
    expect(landMeter(quality({ total_cards_seen: 0, lands_seen: 0, expected_lands_seen: 0 }))).toMatchObject({ nowAt: 0, expectedAt: 0 });
  });
});
