import type { LiveDrawQuality } from '../api';
import { landMeter, landMeterStyle } from '../liveScoreboard';
import { DRAW_STATUS_LABEL } from '../stream/liveView';
import { Badge } from './Badge';

/**
 * The current game's lands on the player's side of the scoreboard: lands seen
 * against what the deck should have given, a gauge with Game Detail's screw
 * and flood zones, and the chance the next draw is a land.
 */
export function LiveLandMeter({ quality }: { quality: LiveDrawQuality }) {
  const meter = landMeter(quality);
  const over = meter.diff > 0;
  return (
    <div className={`live-lands live-lands-${meter.status}`} style={landMeterStyle(meter)}>
      <p className="live-lands-head">
        <span className="live-lands-count">
          <strong>{meter.lands}</strong> of {meter.seen} cards were lands
        </span>
        <span className="live-lands-expected">
          expected {meter.expected.toFixed(1)}
          {meter.diff !== 0 ? (
            <span className={over ? 'live-lands-over' : 'live-lands-under'}>
              {' '}
              ({over ? '+' : '−'}
              {Math.abs(meter.diff).toFixed(1)})
            </span>
          ) : null}
        </span>
        {meter.status !== 'normal' ? (
          <Badge tone={meter.status} className="live-lands-status" title={quality.reason ?? undefined}>
            {DRAW_STATUS_LABEL[meter.status]}
          </Badge>
        ) : null}
      </p>
      <div
        className="live-lands-gauge"
        role="img"
        aria-label={`${meter.lands} lands in ${meter.seen} cards, ${meter.expected.toFixed(1)} expected`}
      >
        <div className="live-lands-track">
          <span className="live-lands-zone live-lands-zone-screw" />
          <span className="live-lands-zone live-lands-zone-flood" />
        </div>
        <span className="live-lands-expected-mark" />
        <span className="live-lands-marker" />
        {/* What the two shaded ends mean. */}
        <div className="live-lands-scale" aria-hidden="true">
          <span>Screw</span>
          <span>Flood</span>
        </div>
      </div>
      <p className="live-lands-foot">
        {quality.next_land_pct != null ? (
          <span>
            Next draw <strong>{Math.round(quality.next_land_pct)}%</strong> land
            {quality.lands_left != null && quality.library_size != null
              ? ` · ${quality.lands_left} of ${quality.library_size} left`
              : ''}
          </span>
        ) : null}
        {quality.ramped_lands > 0 ? <span>{quality.ramped_lands} ramped</span> : null}
      </p>
    </div>
  );
}
