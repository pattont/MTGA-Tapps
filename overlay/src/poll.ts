/**
 * The state poll: conditional GETs against the tracker's /api/overlay.
 *
 * `If-None-Match` turns an unchanged library into a 304 that allocates and
 * parses nothing. The interval backs off with what is happening — every
 * 300 ms during a game, two seconds between games, ten when the tracker is
 * unreachable — and stops entirely while the window is hidden (the caller
 * pauses it), so an idle overlay does no work at all.
 */

import type { Link, OverlayPayload } from './types';

export const INTERVALS = {
  inGame: 300,
  idle: 2000,
  offline: 10_000,
} as const;

export interface PollHandlers {
  onPayload: (payload: OverlayPayload) => void;
  onLink: (link: Link) => void;
}

export function intervalFor(link: Link, payload: OverlayPayload | null): number {
  if (link !== 'online') return INTERVALS.offline;
  if (payload?.tracker.state === 'offline') return INTERVALS.offline;
  if (payload?.state?.game_active) return INTERVALS.inGame;
  return INTERVALS.idle;
}

export class OverlayPoller {
  private etag: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private inflight = false;
  private kicked = false;
  private link: Link = 'connecting';
  private last: OverlayPayload | null = null;

  constructor(
    private baseUrl: string,
    private handlers: PollHandlers,
    private fetchImpl: typeof fetch = (input, init) => fetch(input, init),
  ) {}

  setBaseUrl(url: string): void {
    if (url !== this.baseUrl) {
      this.baseUrl = url;
      this.etag = null;
      this.kick();
    }
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    void this.tick();
  }

  stop(): void {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /** Poll now (a hotkey, a resume) without waiting for the timer. */
  kick(): void {
    if (!this.running) return;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.inflight) {
      // Let the current request finish; go again straight after.
      this.kicked = true;
      return;
    }
    void this.tick();
  }

  private schedule(): void {
    if (!this.running) return;
    const delay = this.kicked ? 0 : intervalFor(this.link, this.last);
    this.kicked = false;
    this.timer = setTimeout(() => void this.tick(), delay);
  }

  private async tick(): Promise<void> {
    if (!this.running || this.inflight) return;
    this.inflight = true;
    const base = this.baseUrl;
    try {
      const headers: Record<string, string> = {};
      if (this.etag) headers['If-None-Match'] = this.etag;
      const response = await this.fetchImpl(`${base.replace(/\/$/, '')}/api/overlay`, {
        headers,
        cache: 'no-store',
      });
      if (base !== this.baseUrl) {
        // The URL changed under us; this answer belongs to the old tracker.
      } else if (response.status === 304) {
        this.setLink('online');
      } else if (response.ok) {
        const payload = (await response.json()) as OverlayPayload;
        this.etag = response.headers.get('ETag');
        this.last = payload;
        this.setLink('online');
        this.handlers.onPayload(payload);
      } else {
        this.setLink('offline');
      }
    } catch {
      if (base === this.baseUrl) this.setLink('offline');
    } finally {
      this.inflight = false;
      this.schedule();
    }
  }

  private setLink(link: Link): void {
    if (link !== this.link) {
      this.link = link;
      this.handlers.onLink(link);
    }
  }
}
