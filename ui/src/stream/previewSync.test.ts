import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { STREAM_KIT_STORAGE_KEY, savedOptionsFor, usePreviewOptions } from './previewSync';

function saveFromAnotherTab(value: unknown) {
  window.dispatchEvent(new StorageEvent('storage', { key: STREAM_KIT_STORAGE_KEY, newValue: JSON.stringify(value) }));
}

afterEach(() => {
  window.history.replaceState(null, '', '/');
});

describe('preview sync', () => {
  it('reads one widget’s saved choices over the defaults', () => {
    const raw = JSON.stringify({ shared: { scale: 150 }, widgets: { record: { period: 'today' } } });
    expect(savedOptionsFor(raw, 'record')).toMatchObject({ scale: 150, period: 'today', bg: 'solid' });
    expect(savedOptionsFor('not json', 'record')).toBeNull();
    expect(savedOptionsFor(null, 'record')).toBeNull();
  });

  it('follows Settings while it is a preview, and rewrites its address', () => {
    const { result } = renderHook(() => usePreviewOptions('?widget=record&demo=1&preview=1'));
    expect(result.current.period).toBe('session');
    act(() => saveFromAnotherTab({ shared: { scale: 125 }, widgets: { record: { period: 'today', hide: ['rank', 'deck'] } } }));
    expect(result.current).toMatchObject({ period: 'today', hide: ['rank', 'deck'], scale: 125, demo: true, preview: true });
    expect(window.location.search).toBe('?widget=record&scale=125&period=today&hide=rank%2Cdeck&demo=1&preview=1');
  });

  it('never changes a real (OBS) source', () => {
    const { result } = renderHook(() => usePreviewOptions('?widget=record'));
    act(() => saveFromAnotherTab({ shared: {}, widgets: { record: { period: 'today' } } }));
    expect(result.current.period).toBe('session');
  });
});
