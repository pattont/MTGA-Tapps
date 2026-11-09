/**
 * A Preview tab follows Settings → Streaming live: Settings saves its choices
 * to localStorage, and a stream page opened with preview=1 rebuilds its
 * options (and its address) whenever they change in another tab. OBS sources
 * never set preview, so their URL stays the only truth.
 */

import { useEffect, useState } from 'react';
import { DEFAULT_OPTIONS, parseStreamOptions, streamUrl, type StreamOptions, type WidgetId } from './options';

export const STREAM_KIT_STORAGE_KEY = 'mtga-stream-kit';

/** One widget's options from the saved Settings choices, or null when there are none. */
export function savedOptionsFor(raw: string | null, widget: WidgetId): StreamOptions | null {
  try {
    const saved = JSON.parse(raw ?? 'null') as { shared?: Partial<StreamOptions>; widgets?: Record<string, Partial<StreamOptions>> } | null;
    if (!saved || typeof saved !== 'object') return null;
    return { ...DEFAULT_OPTIONS, ...saved.shared, ...saved.widgets?.[widget] };
  } catch {
    return null;
  }
}

export function usePreviewOptions(search: string): StreamOptions {
  const [options, setOptions] = useState(() => parseStreamOptions(search));
  const { preview, demo, widget } = options;
  useEffect(() => {
    if (!preview || !widget) return undefined;
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STREAM_KIT_STORAGE_KEY) return;
      const saved = savedOptionsFor(event.newValue, widget);
      if (!saved) return;
      const url = streamUrl(window.location.origin, widget, saved, { demo, preview: true });
      window.history.replaceState(null, '', url);
      setOptions(parseStreamOptions(new URL(url).search));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [preview, demo, widget]);
  return options;
}
