import { DRAW_STATUS_LABEL, floodGauge } from '../floodMeter';
import type { OverlayDrawQuality } from '../types';

/**
 * The Stream Kit Lands widget at the panel's width (Settings → Flood meter):
 * lands seen against expectation, on a gauge with the screw zone in gold on
 * the left and the flood zone in blue on the right.
 */
export function FloodMeter({ quality }: { quality: OverlayDrawQuality }) {
  const gauge = floodGauge(quality);
  if (!gauge) return null;
  const style = {
    '--fm-screw': `${gauge.screw}%`,
    '--fm-flood': `${gauge.flood}%`,
    '--fm-expected': `${gauge.expectedAt}%`,
    '--fm-now': `${gauge.nowAt}%`,
  };
  const label = `Lands: ${gauge.lands} of ${gauge.seen} cards, ${gauge.expected.toFixed(1)} expected; ${DRAW_STATUS_LABEL[gauge.status]}`;
  return (
    <div class={`fm fm-${gauge.status}`} style={style} role="group" aria-label={label}>
      <div class="fm-head">
        <span class="ss-lab">Lands</span>
        <span class="fm-status">{DRAW_STATUS_LABEL[gauge.status]}</span>
        <span class="fm-numbers">
          <b>{gauge.lands}</b> of {gauge.seen}
          <span class="fm-expect">
            {' '}
            · exp {gauge.expected.toFixed(1)}
            {gauge.diff !== 0 ? (
              <span class={gauge.diff > 0 ? 'fm-over' : 'fm-under'}>
                {' '}
                ({gauge.diff > 0 ? '+' : '−'}
                {Math.abs(gauge.diff).toFixed(1)})
              </span>
            ) : null}
          </span>
        </span>
      </div>
      <div class="fm-gauge" aria-hidden="true">
        <div class="fm-track">
          <span class="fm-zone fm-zone-screw" />
          <span class="fm-zone fm-zone-flood" />
        </div>
        <span class="fm-expected-mark" />
        <span class="fm-marker" />
      </div>
      <div class="fm-scale" aria-hidden="true">
        <span>Screw</span>
        <span>Normal</span>
        <span>Flood</span>
      </div>
    </div>
  );
}
