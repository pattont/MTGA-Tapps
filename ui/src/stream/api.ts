import type { LivePayload } from '../api';
import type { OverlayPayload } from './types';

export class HttpError extends Error {}

/** `/api/overlay`, sending the last ETag; null means unchanged (304). */
export async function fetchOverlay(
  etag: string | null,
  signal: AbortSignal,
): Promise<{ payload: OverlayPayload; etag: string | null } | null> {
  const response = await fetch('/api/overlay', {
    headers: etag ? { 'If-None-Match': etag } : {},
    cache: 'no-store',
    signal,
  });
  if (response.status === 304) return null;
  if (!response.ok) throw new HttpError(`overlay ${response.status}`);
  return { payload: (await response.json()) as OverlayPayload, etag: response.headers.get('ETag') };
}

/** `/api/live`; events=false skips the event feed. */
export async function fetchLive(since: number, events: boolean, signal: AbortSignal): Promise<LivePayload> {
  const params = new URLSearchParams({ since: String(since) });
  if (!events) params.set('events', '0');
  const response = await fetch(`/api/live?${params.toString()}`, { cache: 'no-store', signal });
  if (!response.ok) throw new HttpError(`live ${response.status}`);
  return (await response.json()) as LivePayload;
}
