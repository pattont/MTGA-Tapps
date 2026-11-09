import type { CSSProperties } from 'react';
import type { LiveDrawQuality } from '../../api';
import { DRAW_STATUS_LABEL, drawStatus, landZones, showsGame } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';

/** Where a land count sits on the gauge, 0–100 %. */
function at(count: number, max: number): number {
  return max > 0 ? Math.max(0, Math.min(100, (100 * count) / max)) : 0;
}

export function LandsView({ quality, options }: { quality: LiveDrawQuality; options: StreamOptions }) {
  const status = drawStatus(quality);
  const seen = quality.total_cards_seen;
  const lands = quality.lands_seen;
  const deckLands = quality.deck_lands ?? Math.round((quality.deck_size * quality.expected_land_rate) / 100);
  const zones = landZones(quality.deck_size, deckLands, seen);
  // The gauge runs from no lands to every card seen being a land.
  const style = {
    '--lm-screw': `${at(zones.screwMax + 0.5, seen)}%`,
    '--lm-flood': `${at(zones.floodMin - 0.5, seen)}%`,
    '--lm-expected': `${at(quality.expected_lands_seen, seen)}%`,
    '--lm-now': `${at(lands, seen)}%`,
  } as CSSProperties;
  const diff = Math.round((lands - quality.expected_lands_seen) * 10) / 10;
  return (
    <div className={`sk-panel lm lm-${status}`} style={style}>
      <div className="lm-head">
        <span className="sk-label">Lands</span>
        <span className={`lm-status lm-status-${status}`}>{DRAW_STATUS_LABEL[status]}</span>
        <Brand show={options.brand} />
      </div>
      <div className="lm-numbers">
        <span className="lm-count">
          <strong>{lands}</strong>
          <span className="lm-of"> of {seen} cards</span>
        </span>
        <span className="lm-expect">
          expected {quality.expected_lands_seen.toFixed(1)}
          {diff !== 0 ? (
            <span className={diff > 0 ? 'lm-over' : 'lm-under'}>
              {' '}
              ({diff > 0 ? '+' : '−'}
              {Math.abs(diff).toFixed(1)})
            </span>
          ) : null}
        </span>
      </div>
      <div className="lm-gauge" role="img" aria-label={`${lands} lands seen, ${quality.expected_lands_seen} expected`}>
        <div className="lm-track">
          <span className="lm-zone lm-zone-screw" />
          <span className="lm-zone lm-zone-flood" />
        </div>
        <span className="lm-expected-mark" />
        <span className="lm-marker">
          <span className="lm-marker-dot" />
        </span>
        <div className="lm-scale" aria-hidden="true">
          <span>Screw</span>
          <span>Normal</span>
          <span>Flood</span>
        </div>
      </div>
      <div className="lm-foot">
        {shows(options, 'odds') && quality.next_land_pct != null ? (
          <span>
            Next draw <strong>{Math.round(quality.next_land_pct)}%</strong> land
            {quality.lands_left != null && quality.library_size != null ? (
              <span className="lm-left">
                {' '}
                · {quality.lands_left} of {quality.library_size} left
              </span>
            ) : null}
          </span>
        ) : null}
        {quality.ramped_lands > 0 ? <span className="lm-left">{quality.ramped_lands} ramped</span> : null}
      </div>
      {shows(options, 'reason') && quality.reason ? <div className="lm-reason">{quality.reason}</div> : null}
    </div>
  );
}

/** Flood / screw meter: up during a game (and between games with idle=show). */
export function LandsWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const now = payload?.tracker.state === 'offline' ? null : payload?.now;
  if (!showsGame(now, options.idle) || !now.draw_quality) return null;
  return <LandsView quality={now.draw_quality} options={options} />;
}
