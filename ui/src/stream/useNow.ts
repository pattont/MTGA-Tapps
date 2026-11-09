import { useEffect, useState } from 'react';

/** The time, ticking every second while `enabled` (turn timers, session length). */
export function useNow(enabled = true, everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(timer);
  }, [enabled, everyMs]);
  return now;
}
