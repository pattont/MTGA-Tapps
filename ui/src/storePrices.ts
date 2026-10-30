/**
 * Store prices from the dashboard's /api/paper-prices endpoint, which keeps a
 * daily copy of Card Kingdom's and Mana Pool's public price lists
 * (src/mtga_tracker/paper_prices.py). The first lookup of the day answers
 * "loading" while the list downloads, so this polls until it's ready.
 */

export type StorePriceSource = 'cardkingdom' | 'manapool';

export interface StorePrice {
  name: string;
  usd: number;
  set: string;
  set_name: string;
  collector_number: string;
  finish: 'nonfoil' | 'foil' | 'etched';
  in_stock: boolean;
  url: string | null;
}

export interface StorePriceResult {
  prices: Map<string, StorePrice | null>;
  asOf: string;
}

const POLL_MS = 1500;
const TIMEOUT_MS = 180_000;

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(signal.reason); }, { once: true });
  });
}

/**
 * Prices for `names` (paper names) at one store. `onLoading` fires while the
 * store's list is still downloading. Rejects with the server's reason when
 * the list can't be loaded.
 */
export async function fetchStorePrices(
  vendor: StorePriceSource,
  names: string[],
  options: { signal?: AbortSignal; onLoading?: () => void } = {},
): Promise<StorePriceResult> {
  const params = new URLSearchParams({ vendor });
  names.forEach((name) => params.append('name', name));
  const deadline = Date.now() + TIMEOUT_MS;
  for (;;) {
    const response = await fetch(`/api/paper-prices?${params}`, { signal: options.signal });
    const body = (await response.json().catch(() => ({}))) as {
      status?: string; error?: string; as_of?: string; prices?: Record<string, StorePrice | null>;
    };
    if (response.status === 200 && body.status === 'ready') {
      return { prices: new Map(Object.entries(body.prices ?? {})), asOf: body.as_of ?? '' };
    }
    if (response.status !== 202 || Date.now() > deadline) {
      throw new Error(body.error || 'The store’s price list is unavailable right now.');
    }
    options.onLoading?.();
    await wait(POLL_MS, options.signal);
  }
}
