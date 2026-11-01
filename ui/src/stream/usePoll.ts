import { useEffect, useRef } from 'react';
import { usePageVisible } from '../usePageVisible';

export const ERROR_DELAY_MS = 5000;

/**
 * Runs `tick` now and again after the delay it returns, until unmounted or
 * the page is hidden (an OBS source outside the live scene, a background
 * tab). A thrown tick waits ERROR_DELAY_MS and tries again, so a tracker
 * restart only pauses the widget. `tick` may change between renders; the
 * loop always calls the latest one.
 */
export function usePoll(tick: (signal: AbortSignal) => Promise<number>, enabled = true): void {
  const visible = usePageVisible();
  const latest = useRef(tick);
  useEffect(() => {
    latest.current = tick;
  });

  useEffect(() => {
    if (!enabled || !visible) return undefined;
    const controller = new AbortController();
    let timer: number | undefined;
    const run = async () => {
      let delay: number;
      try {
        delay = await latest.current(controller.signal);
      } catch {
        if (controller.signal.aborted) return;
        delay = ERROR_DELAY_MS;
      }
      if (!controller.signal.aborted) timer = window.setTimeout(() => void run(), delay);
    };
    void run();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [enabled, visible]);
}
