/**
 * The Settings switch for Buy on Paper, shared by every screen that shows
 * the button. It's read once per page load from /api/paper-prices/status;
 * the Settings page updates it in place when the switch changes, so the
 * buttons disappear without a reload.
 */

import { useEffect, useSyncExternalStore } from 'react';
import type { BuyOnPaperSettings } from './api';

/** Scryfall prices cached by the dialog (cardPrices.ts). */
const BROWSER_PRICE_CACHE = 'mtga-tracker-paper-prices-v1';

let enabled: boolean | null = null;
let requested = false;
const listeners = new Set<() => void>();

function publish(value: boolean) {
  enabled = value;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function load() {
  if (requested) return;
  requested = true;
  fetch('/api/paper-prices/status')
    .then((response) => (response.ok ? response.json() : null))
    .then((body: Partial<BuyOnPaperSettings> | null) => publish(typeof body?.enabled === 'boolean' ? body.enabled : true))
    // An older tracker without the switch: Buy on Paper is simply on.
    .catch(() => publish(true));
}

/** True once the switch is known to be on. Hidden until then, so turning it off never flashes the button. */
export function useBuyOnPaperEnabled(): boolean {
  const value = useSyncExternalStore(subscribe, () => enabled);
  useEffect(load, []);
  return value === true;
}

export async function saveBuyOnPaperEnabled(next: boolean): Promise<BuyOnPaperSettings> {
  const response = await fetch('/api/settings/buy-on-paper', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: next }),
  });
  const body = (await response.json().catch(() => ({}))) as { buy_on_paper?: BuyOnPaperSettings; error?: string };
  if (!response.ok || !body.buy_on_paper) {
    throw new Error(body.error || 'Buy on Paper could not be changed.');
  }
  if (!next) {
    try {
      localStorage.removeItem(BROWSER_PRICE_CACHE);
    } catch {
      // Browser storage is optional.
    }
  }
  publish(body.buy_on_paper.enabled);
  return body.buy_on_paper;
}

/** Test hook. */
export function resetBuyOnPaperSetting(value: boolean | null = null): void {
  enabled = value;
  requested = value !== null;
}
