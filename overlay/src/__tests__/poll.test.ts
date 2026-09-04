import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { INTERVALS, OverlayPoller, intervalFor } from '../poll';
import { inGamePayload, idlePayload, offlinePayload } from './fixtures';

function response(status: number, body?: unknown, etag?: string): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name: string) => (name.toLowerCase() === 'etag' && etag ? etag : null) },
    json: async () => body,
  } as unknown as Response;
}

describe('intervalFor', () => {
  it('backs off with what is happening', () => {
    expect(intervalFor('online', inGamePayload())).toBe(INTERVALS.inGame);
    expect(intervalFor('online', idlePayload())).toBe(INTERVALS.idle);
    expect(intervalFor('online', offlinePayload())).toBe(INTERVALS.offline);
    expect(intervalFor('offline', inGamePayload())).toBe(INTERVALS.offline);
    expect(intervalFor('connecting', null)).toBe(INTERVALS.offline);
  });
});

describe('OverlayPoller', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('sends If-None-Match and treats 304 as still online', async () => {
    const calls: RequestInit[] = [];
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(init ?? {});
      return calls.length === 1 ? response(200, inGamePayload(), '"abc"') : response(304);
    });
    const onPayload = vi.fn();
    const onLink = vi.fn();
    const poller = new OverlayPoller('http://127.0.0.1:8765/', { onPayload, onLink }, fetchImpl as unknown as typeof fetch);
    poller.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl.mock.calls[0][0]).toBe('http://127.0.0.1:8765/api/overlay');
    expect(onPayload).toHaveBeenCalledTimes(1);
    expect(onLink).toHaveBeenCalledWith('online');
    await vi.advanceTimersByTimeAsync(INTERVALS.inGame);
    expect((calls[1].headers as Record<string, string>)['If-None-Match']).toBe('"abc"');
    expect(onPayload).toHaveBeenCalledTimes(1);
    poller.stop();
  });

  it('goes offline on a network error and slows down', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('refused');
    });
    const onLink = vi.fn();
    const poller = new OverlayPoller('http://127.0.0.1:8765', { onPayload: vi.fn(), onLink }, fetchImpl as unknown as typeof fetch);
    poller.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(onLink).toHaveBeenCalledWith('offline');
    await vi.advanceTimersByTimeAsync(INTERVALS.idle);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(INTERVALS.offline);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    poller.stop();
  });

  it('stops polling when stopped and drops the ETag on a new base url', async () => {
    const fetchImpl = vi.fn(async () => response(200, idlePayload(), '"x"'));
    const poller = new OverlayPoller('http://a', { onPayload: vi.fn(), onLink: vi.fn() }, fetchImpl as unknown as typeof fetch);
    poller.start();
    await vi.advanceTimersByTimeAsync(0);
    poller.stop();
    await vi.advanceTimersByTimeAsync(INTERVALS.offline * 3);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    poller.start();
    poller.setBaseUrl('http://b');
    await vi.advanceTimersByTimeAsync(0);
    const last = fetchImpl.mock.calls[fetchImpl.mock.calls.length - 1] as unknown as [string, RequestInit];
    expect(last[0]).toBe('http://b/api/overlay');
    expect((last[1].headers as Record<string, string>)['If-None-Match']).toBeUndefined();
    poller.stop();
  });
});
