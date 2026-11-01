import { useCallback, useRef, useState } from 'react';
import { fetchOverlay } from './api';
import { DEMO_OVERLAY } from './demo';
import type { OverlayPayload } from './types';
import { usePoll } from './usePoll';

const IN_GAME_MS = 500;
const IDLE_MS = 2000;

/**
 * `/api/overlay`, polled with its ETag: every 500 ms in a game, 2 s
 * otherwise. Demo mode returns the sample payload and makes no requests.
 */
export function useOverlay(demo: boolean): { payload: OverlayPayload | null; offline: boolean } {
  const [payload, setPayload] = useState<OverlayPayload | null>(demo ? DEMO_OVERLAY : null);
  const [offline, setOffline] = useState(false);
  const etag = useRef<string | null>(null);

  const tick = useCallback(async (signal: AbortSignal) => {
    try {
      const result = await fetchOverlay(etag.current, signal);
      setOffline(false);
      if (result) {
        etag.current = result.etag;
        setPayload(result.payload);
        return result.payload.state?.game_active ? IN_GAME_MS : IDLE_MS;
      }
      return IN_GAME_MS;
    } catch (error) {
      if (!signal.aborted) setOffline(true);
      throw error;
    }
  }, []);
  usePoll(tick, !demo);

  return { payload, offline };
}
