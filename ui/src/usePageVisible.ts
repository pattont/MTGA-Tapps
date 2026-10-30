import { useSyncExternalStore } from 'react';

function subscribe(onChange: () => void): () => void {
  document.addEventListener('visibilitychange', onChange);
  return () => document.removeEventListener('visibilitychange', onChange);
}

/**
 * False while the tab is hidden (another tab, minimized window). Polling
 * effects list it as a dependency: they stop in the background and run again
 * at once when the page comes back, so nothing shown is stale.
 */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, () => document.visibilityState !== 'hidden', () => true);
}
