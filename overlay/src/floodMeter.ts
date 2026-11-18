/**
 * The flood meter's numbers: a copy of the Stream Kit Lands widget's
 * (`ui/src/stream/liveView.ts` `landZones` / `drawStatus`,
 * `widgets/LandsWidget.tsx`), so both read a game alike. Change both.
 */

import type { OverlayDrawQuality } from './types';

export type DrawStatus = 'flood' | 'screw' | 'streak' | 'normal';

export const DRAW_STATUS_LABEL: Record<DrawStatus, string> = {
  flood: 'Flooding',
  screw: 'Mana screw',
  streak: 'Land streak',
  normal: 'Normal',
};

/** Flood, then Mana screw, then Land streak (the dashboard's Draw Status order). */
export function drawStatus(quality: Pick<OverlayDrawQuality, 'is_flood' | 'is_screw' | 'is_land_streak'>): DrawStatus {
  if (quality.is_flood) return 'flood';
  if (quality.is_screw) return 'screw';
  if (quality.is_land_streak) return 'streak';
  return 'normal';
}

function logChoose(n: number, k: number): number {
  if (k < 0 || k > n) return -Infinity;
  let total = 0;
  for (let i = 1; i <= k; i += 1) total += Math.log(n - k + i) - Math.log(i);
  return total;
}

/** P(exactly k lands among `draws` cards of a `deck` with `lands` lands). */
function hypergeomPmf(k: number, deck: number, lands: number, draws: number): number {
  const value = logChoose(lands, k) + logChoose(deck - lands, draws - k) - logChoose(deck, draws);
  return Number.isFinite(value) ? Math.exp(value) : 0;
}

/** Up to `screwMax` lands reads as screw, from `floodMin` as flood (≤10 % tails, like draw_quality). */
export function landZones(deck: number, lands: number, seen: number): { screwMax: number; floodMin: number } {
  const draws = Math.min(seen, deck);
  const pmf = Array.from({ length: draws + 1 }, (_, k) => hypergeomPmf(k, deck, lands, draws));
  let screwMax = -1;
  let low = 0;
  for (let k = 0; k <= draws; k += 1) {
    low += pmf[k];
    if (low * 100 <= 10) screwMax = k;
    else break;
  }
  let floodMin = draws + 1;
  let high = 0;
  for (let k = draws; k >= 0; k -= 1) {
    high += pmf[k];
    if (high * 100 <= 10) floodMin = k;
    else break;
  }
  return { screwMax, floodMin };
}

/** Where a land count sits on the gauge, 0–100 %. */
function at(count: number, max: number): number {
  return max > 0 ? Math.max(0, Math.min(100, (100 * count) / max)) : 0;
}

export interface FloodGauge {
  status: DrawStatus;
  lands: number;
  seen: number;
  expected: number;
  /** Lands over (+) or under (−) expectation, one decimal. */
  diff: number;
  /** Gauge positions in percent: the screw zone's end, the flood zone's start, the expected tick, the marker. */
  screw: number;
  flood: number;
  expectedAt: number;
  nowAt: number;
}

/** The gauge runs from no lands to every card seen being a land; null before any card is seen. */
export function floodGauge(quality: OverlayDrawQuality): FloodGauge | null {
  const seen = quality.total_cards_seen;
  if (!(seen > 0) || !(quality.deck_size > 0)) return null;
  const lands = quality.lands_seen;
  const deckLands = quality.deck_lands ?? Math.round((quality.deck_size * quality.expected_land_rate) / 100);
  const zones = landZones(quality.deck_size, deckLands, seen);
  return {
    status: drawStatus(quality),
    lands,
    seen,
    expected: quality.expected_lands_seen,
    diff: Math.round((lands - quality.expected_lands_seen) * 10) / 10,
    screw: at(zones.screwMax + 0.5, seen),
    flood: at(zones.floodMin - 0.5, seen),
    expectedAt: at(quality.expected_lands_seen, seen),
    nowAt: at(lands, seen),
  };
}
