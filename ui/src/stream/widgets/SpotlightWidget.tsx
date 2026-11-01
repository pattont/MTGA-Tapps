import { useCallback, useEffect, useRef, useState } from 'react';
import { cardPreviewImageUrl } from '../../cardPreview';
import { fetchLive } from '../api';
import { DEMO_CASTS } from '../demo';
import type { StreamOptions } from '../options';
import { ingestFeed, START_CURSOR, type Cast, type SpotlightCursor } from '../spotlight';
import { usePoll } from '../usePoll';
import { Brand } from './Brand';

const FEED_MS = 1000;
/** Pause between demo cards, after one fades. */
const DEMO_GAP_MS = 1500;

type ImageState = 'loading' | 'ready' | 'failed';

export function SpotlightView({
  cast,
  image,
  visible,
  options,
  onImage,
}: {
  cast: Cast;
  image: ImageState;
  visible: boolean;
  options: StreamOptions;
  onImage: (state: ImageState) => void;
}) {
  return (
    <div className={`sk-spot${visible ? ' sk-spot-in' : ''}`} aria-live="polite" aria-hidden={!visible}>
      <div className="sk-panel sk-spot-caption">
        <span className={cast.role === 'opponent' ? 'sk-loss' : 'sk-win'}>
          {cast.role === 'opponent' ? 'Opponent cast' : 'You cast'}
        </span>
        <Brand show={options.brand} />
      </div>
      {image === 'failed' ? (
        <div className="sk-spot-fallback">{cast.name}</div>
      ) : (
        <img
          className="sk-spot-card"
          src={cardPreviewImageUrl(cast.name)}
          alt={cast.name}
          onLoad={() => onImage('ready')}
          onError={() => onImage('failed')}
        />
      )}
    </div>
  );
}

/**
 * Card spotlight: each new cast from the live feed, large, for a few
 * seconds. A newer cast replaces the one on screen at once.
 */
export function SpotlightWidget({ options }: { options: StreamOptions }) {
  // serial tells two showings of the same card apart (the demo repeats ids).
  const [shown, setShown] = useState<{ cast: Cast; serial: number } | null>(() =>
    options.demo ? { cast: { id: 1, ...DEMO_CASTS[0] }, serial: 1 } : null,
  );
  const [image, setImage] = useState<ImageState>('loading');
  const [expired, setExpired] = useState(0);
  const cursor = useRef<SpotlightCursor>(START_CURSOR);
  const session = useRef<string | null>(null);

  const show = useCallback((cast: Cast) => {
    setShown((current) => ({ cast, serial: (current?.serial ?? 0) + 1 }));
    setImage('loading');
  }, []);

  const tick = useCallback(
    async (signal: AbortSignal) => {
      try {
        const payload = await fetchLive(cursor.current.seq, true, signal);
        // A new tracker session (or a restored database) restarts the ids.
        if (payload.tracker.session_id !== session.current) {
          session.current = payload.tracker.session_id;
          cursor.current = START_CURSOR;
        }
        const result = ingestFeed(cursor.current, payload.events, payload.seq, options.who);
        cursor.current = result.cursor;
        if (result.cast) show(result.cast);
      } catch (error) {
        // After an outage, catch up again rather than replaying what was missed.
        cursor.current = { ...cursor.current, caughtUp: false };
        throw error;
      }
      return FEED_MS;
    },
    [options.who, show],
  );
  usePoll(tick, !options.demo);

  // Demo: cycle sample cards.
  useEffect(() => {
    if (!options.demo) return undefined;
    let index = 0;
    const timer = window.setInterval(() => {
      index = (index + 1) % DEMO_CASTS.length;
      show({ id: index + 1, ...DEMO_CASTS[index] });
    }, options.seconds * 1000 + DEMO_GAP_MS);
    return () => window.clearInterval(timer);
  }, [options.demo, options.seconds, show]);

  // Up once the image settles, faded after the chosen time.
  const serial = shown?.serial ?? 0;
  useEffect(() => {
    if (!serial || image === 'loading') return undefined;
    const timer = window.setTimeout(() => setExpired(serial), options.seconds * 1000);
    return () => window.clearTimeout(timer);
  }, [serial, image, options.seconds]);

  if (!shown) return null;
  const visible = image !== 'loading' && expired !== shown.serial;
  return (
    <SpotlightView
      key={shown.serial}
      cast={shown.cast}
      image={image}
      visible={visible}
      options={options}
      onImage={setImage}
    />
  );
}
