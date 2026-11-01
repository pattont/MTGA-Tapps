import { useCallback, useState } from 'react';
import type { LivePayload } from '../api';
import { fetchLive } from './api';
import { DEMO_LIVE } from './demo';
import { usePoll } from './usePoll';

const SCOREBOARD_MS = 2000;

/** The Live Scoreboard snapshot without its event feed, every two seconds. */
export function useLiveSnapshot(demo: boolean): LivePayload | null {
  const [payload, setPayload] = useState<LivePayload | null>(demo ? DEMO_LIVE : null);
  const tick = useCallback(async (signal: AbortSignal) => {
    try {
      setPayload(await fetchLive(0, false, signal));
    } catch (error) {
      if (!signal.aborted) setPayload(null);
      throw error;
    }
    return SCOREBOARD_MS;
  }, []);
  usePoll(tick, !demo);
  return payload;
}
