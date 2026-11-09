import { useCallback, useRef, useState } from 'react';
import { fetchOverlay } from './api';
import { DEMO_OVERLAY } from './demo';
import type { OverlayPayload } from './types';
import { usePoll } from './usePoll';

export const IN_GAME_MS = 500;
export const IDLE_MS = 2000;
export const OFFLINE_MS = 10_000;

/** How long to wait before the next `/api/overlay` poll after this payload. */
export function overlayPollDelay(payload: OverlayPayload | null): number {
  if (!payload || payload.tracker.state === 'offline') return OFFLINE_MS;
  return payload.state?.game_active ? IN_GAME_MS : IDLE_MS;
}

/**
 * `/api/overlay`, polled with its ETag: every 500 ms in a game, 2 s
 * otherwise, 10 s while the tracker is offline. A 304 keeps the pace of the
 * last payload (it used to drop to 500 ms, so idle sources polled at game
 * speed for ever). Demo mode returns the sample payload and makes no requests.
 */
export function useOverlay(demo: boolean): { payload: OverlayPayload | null; offline: boolean } {
  const [payload, setPayload] = useState<OverlayPayload | null>(demo ? DEMO_OVERLAY : null);
  const [offline, setOffline] = useState(false);
  const etag = useRef<string | null>(null);
  const delay = useRef(IDLE_MS);

  const tick = useCallback(async (signal: AbortSignal) => {
    try {
      const result = await fetchOverlay(etag.current, signal);
      setOffline(false);
      if (result) {
        etag.current = result.etag;
        setPayload(result.payload);
        delay.current = overlayPollDelay(result.payload);
      }
      return delay.current;
    } catch (error) {
      if (!signal.aborted) setOffline(true);
      throw error;
    }
  }, []);
  usePoll(tick, !demo);

  return { payload, offline };
}
