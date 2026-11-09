import { describe, expect, it } from 'vitest';
import { DEMO_OVERLAY } from './demo';
import type { OverlayPayload } from './types';
import { IDLE_MS, IN_GAME_MS, OFFLINE_MS, overlayPollDelay } from './useOverlay';

const withState = (patch: Partial<OverlayPayload['tracker']>, gameActive: boolean | null): OverlayPayload => ({
  ...DEMO_OVERLAY,
  tracker: { ...DEMO_OVERLAY.tracker, ...patch },
  state: gameActive === null ? null : { ...DEMO_OVERLAY.state!, game_active: gameActive },
});

describe('overlayPollDelay', () => {
  it('polls at game speed only while a game is on', () => {
    expect(overlayPollDelay(withState({ state: 'live' }, true))).toBe(IN_GAME_MS);
    expect(overlayPollDelay(withState({ state: 'live' }, false))).toBe(IDLE_MS);
    expect(overlayPollDelay(withState({ state: 'idle' }, null))).toBe(IDLE_MS);
  });

  it('backs off while the tracker is offline or nothing has arrived yet', () => {
    expect(overlayPollDelay(withState({ state: 'offline' }, true))).toBe(OFFLINE_MS);
    expect(overlayPollDelay(null)).toBe(OFFLINE_MS);
  });
});
