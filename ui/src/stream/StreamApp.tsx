import type { CSSProperties } from 'react';
import { useEffect } from 'react';
import { PRODUCT_NAME } from '../branding';
import { WIDGETS, type StreamOptions } from './options';
import { DeckWidget } from './widgets/DeckWidget';
import { GamesWidget } from './widgets/GamesWidget';
import { MatchupWidget } from './widgets/MatchupWidget';
import { OverlayWidget } from './widgets/OverlayWidget';
import { RecordWidget } from './widgets/RecordWidget';
import { SpotlightWidget } from './widgets/SpotlightWidget';

function Widget({ options }: { options: StreamOptions }) {
  switch (options.widget) {
    case 'overlay':
      return <OverlayWidget options={options} />;
    case 'deck':
      return <DeckWidget options={options} />;
    case 'record':
      return <RecordWidget options={options} />;
    case 'games':
      return <GamesWidget options={options} />;
    case 'matchup':
      return <MatchupWidget options={options} />;
    case 'spotlight':
      return <SpotlightWidget options={options} />;
    default:
      return (
        <div className="sk-panel sk-help">
          <div className="sk-title">{PRODUCT_NAME} Stream Kit</div>
          <p>
            Add <code>?widget=</code> and one of {WIDGETS.map((widget) => widget.id).join(', ')}. Settings → Streaming
            builds these links for you.
          </p>
        </div>
      );
  }
}

/** One widget per page; OBS sizes and places each browser source. */
export function StreamApp({ options }: { options: StreamOptions }) {
  useEffect(() => {
    document.documentElement.classList.toggle('sk-preview', options.preview);
    document.title = options.widget ? `${PRODUCT_NAME} – ${options.widget}` : `${PRODUCT_NAME} – Stream Kit`;
  }, [options.preview, options.widget]);
  const style = { '--sk-scale': options.scale / 100 } as CSSProperties;
  return (
    <div className={`sk sk-bg-${options.bg}`} style={style}>
      <Widget options={options} />
    </div>
  );
}
