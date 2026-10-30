/**
 * One hover preview for the whole replay page (scene meshes and log card
 * names), styled like CardLink's `.card-preview`. A single delegated preview
 * keeps hundreds of log rows from each mounting their own floating tooltip.
 * Images that need an api.scryfall.com lookup go through the page's
 * rate-limited queue instead of an `<img>` pointed at the API, so sweeping
 * the pointer across the log never exceeds the shared request budget.
 */
import { useEffect, useState, useSyncExternalStore } from 'react';
import { formatCardName } from '../../format';
import { PICTURES_MAX, UNDER_MAX_ROWS, previewPosition, underPictures } from '../scene/hoverStore';
import type { HoverStore, HoverUnder, PreviewBox } from '../scene/hoverStore';
import type { TextureStore } from '../scene/textureStore';
import type { CardKey } from '../types';

function PreviewImage({ url, name, fallback }: { url: string | null; name: string; fallback: string | null }) {
  const [state, setState] = useState<'loading' | 'loaded' | 'failed'>('loading');
  if (url === null || state === 'failed') {
    if (fallback) {
      return (
        <img
          className="card-preview-image card-preview-image-loaded card-preview-generated"
          src={fallback}
          alt={`${formatCardName(name)} card preview`}
        />
      );
    }
    return (
      <div className="card-preview-fallback">
        <strong>{formatCardName(name)}</strong>
        <span>Card image unavailable</span>
      </div>
    );
  }
  return (
    <>
      {state === 'loading' ? <div className="card-preview-loading">{formatCardName(name)}</div> : null}
      <img
        className={state === 'loaded' ? 'card-preview-image card-preview-image-loaded' : 'card-preview-image'}
        src={url}
        alt={`${formatCardName(name)} card preview`}
        onLoad={() => setState('loaded')}
        onError={() => setState('failed')}
      />
    </>
  );
}

interface Lookup {
  id: string;
  url: string | null;
}

/** Preview URL for the hovered card: immediate when known, else looked up once per hover target. */
function usePreviewUrl(store: TextureStore, card: CardKey | null, name: string): string | null | undefined {
  const immediate = store.previewUrlNow(card);
  const id = `${card ?? ''}|${name}`;
  const [lookup, setLookup] = useState<Lookup | null>(null);
  useEffect(() => {
    if (immediate || !name) return;
    let live = true;
    store.resolvePreview(card, name).then(
      (url) => {
        if (live) setLookup({ id, url });
      },
      () => {
        if (live) setLookup({ id, url: null });
      },
    );
    return () => {
      live = false;
    };
  }, [store, card, name, id, immediate]);
  if (immediate) return immediate;
  return lookup?.id === id ? lookup.url : undefined;
}

export function PreviewCard({ store, card, name }: { store: TextureStore; card: CardKey | null; name: string }) {
  const url = usePreviewUrl(store, card, name);
  if (url === undefined) {
    return <div className="card-preview-loading">{formatCardName(name)}</div>;
  }
  // No image anywhere (a token Scryfall has not printed): the procedural face.
  return <PreviewImage key={url ?? 'none'} url={url} name={name} fallback={url ? null : store.generatedFaceUrl(card)} />;
}

/** The cards tucked under the hovered permanent: top of the stack first, a thumbnail and name each. */
function UnderList({ store, under }: { store: TextureStore; under: readonly HoverUnder[] }) {
  const shown = under.slice(-UNDER_MAX_ROWS).reverse();
  const more = under.length - shown.length;
  return (
    <div className="replay-preview-under">
      <div className="replay-preview-under-title">
        Under this card <span>{under.length}</span>
      </div>
      <ul>
        {shown.map((item, i) => (
          <li key={`${item.card ?? ''}|${item.name}|${i}`}>
            <span className="replay-preview-under-thumb" aria-hidden="true">
              {item.name ? <PreviewCard store={store} card={item.card} name={item.name} /> : null}
            </span>
            <span className="replay-preview-under-name">{item.name ? formatCardName(item.name) : 'Face-down card'}</span>
            {item.zone === 'exile' ? <span className="replay-preview-under-tag">exiled</span> : null}
          </li>
        ))}
      </ul>
      {more > 0 ? <div className="replay-preview-under-more">and {more} more below</div> : null}
    </div>
  );
}

/** Each distinct card in the tucked stack, pictured beside the hovered card so none of them needs its own hover. */
function UnderPictures({ store, under, box }: { store: TextureStore; under: readonly HoverUnder[]; box: PreviewBox }) {
  const pictures = underPictures(under);
  const shown = pictures.slice(0, PICTURES_MAX);
  const more = pictures.length - shown.length;
  return (
    <div className="replay-preview-pictures">
      <div
        className="replay-preview-pictures-grid"
        style={{ gridTemplateColumns: `repeat(${box.pictureColumns}, ${box.pictureWidth}px)` }}
      >
        {shown.map((picture) => (
          <figure key={picture.card} className="replay-preview-picture">
            <div className="card-preview-media">
              <PreviewCard store={store} card={picture.card} name={picture.name} />
            </div>
            {picture.count > 1 ? <figcaption className="replay-preview-picture-count">×{picture.count}</figcaption> : null}
          </figure>
        ))}
      </div>
      {more > 0 ? <div className="replay-preview-under-more">and {more} more</div> : null}
    </div>
  );
}

export function CardPreview({ hover, store }: { hover: HoverStore; store: TextureStore }) {
  const info = useSyncExternalStore(hover.subscribe, hover.get);
  if (!info || !info.name) return null;
  const box = previewPosition(info, { width: window.innerWidth, height: window.innerHeight });
  const under = info.under ?? [];
  return (
    <div
      className="card-preview replay-card-preview"
      role="tooltip"
      data-card-name={info.name}
      style={{ position: 'fixed', left: box.left, top: box.top, width: box.width }}
    >
      <div className="replay-preview-body">
        <div className="replay-preview-host" style={{ width: box.hostWidth - 10 }}>
          <div className="card-preview-media">
            <PreviewCard key={`${info.card ?? ''}|${info.name}`} store={store} card={info.card} name={info.name} />
          </div>
          {info.note ? <div className="replay-preview-note">{info.note}</div> : null}
          {under.length ? <UnderList store={store} under={under} /> : null}
        </div>
        {box.pictureColumns ? <UnderPictures store={store} under={under} box={box} /> : null}
      </div>
    </div>
  );
}
