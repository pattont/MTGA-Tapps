/**
 * Small pure pieces of the Live Scoreboard: the Bo3 match score and the land
 * meter's numbers. The meter's zones and status are the Stream Kit's
 * (`stream/liveView.ts`), so both read a game the same way.
 */

import type { CSSProperties } from 'react';
import type { LiveDrawQuality, LiveNow } from './api';
import type { DrawStatus } from './drawStatus';
import { drawStatus, landZones } from './stream/liveView';

/**
 * "Match 1–0" during a best-of-three, "Match won 2–1" / "Match lost 0–2" once
 * it is decided; null in best-of-one or when the tracker sends no score.
 * During a game the score leaves the game in progress out.
 */
export function matchScoreText(now: LiveNow): string | null {
  if (now.match_type !== 'best_of_3' || !now.match_score) return null;
  const { wins, losses } = now.match_score;
  if (wins >= 2) return `Match won ${wins}–${losses}`;
  if (losses >= 2) return `Match lost ${wins}–${losses}`;
  return `Match ${wins}–${losses}`;
}

export interface LandMeter {
  status: DrawStatus;
  lands: number;
  seen: number;
  expected: number;
  /** Lands seen minus expected, to one decimal; 0 when on pace. */
  diff: number;
  /** Gauge positions, 0–100 %: where screw ends, flood begins, the expected count and the current one. */
  screwEnd: number;
  floodStart: number;
  expectedAt: number;
  nowAt: number;
}

function at(count: number, max: number): number {
  return max > 0 ? Math.max(0, Math.min(100, (100 * count) / max)) : 0;
}

/** The land meter for a game in progress; the gauge runs from no lands to every card seen being one. */
export function landMeter(quality: LiveDrawQuality): LandMeter {
  const seen = quality.total_cards_seen;
  const lands = quality.lands_seen;
  const deckLands = quality.deck_lands ?? Math.round((quality.deck_size * quality.expected_land_rate) / 100);
  const zones = landZones(quality.deck_size, deckLands, seen);
  return {
    status: drawStatus(quality),
    lands,
    seen,
    expected: quality.expected_lands_seen,
    diff: Math.round((lands - quality.expected_lands_seen) * 10) / 10,
    screwEnd: at(zones.screwMax + 0.5, seen),
    floodStart: at(zones.floodMin - 0.5, seen),
    expectedAt: at(quality.expected_lands_seen, seen),
    nowAt: at(lands, seen),
  };
}

export function landMeterStyle(meter: LandMeter): CSSProperties {
  return {
    '--lands-screw': `${meter.screwEnd}%`,
    '--lands-flood': `${meter.floodStart}%`,
    '--lands-expected': `${meter.expectedAt}%`,
    '--lands-now': `${meter.nowAt}%`,
  } as CSSProperties;
}
