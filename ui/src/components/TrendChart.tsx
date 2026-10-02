import { useMemo, useState } from 'react';
import type { TrendRow } from '../api';
import { rollingWinRates, TREND_WINDOW } from '../trend';

const VIEW_WIDTH = 600;
const VIEW_HEIGHT = 120;

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

export function TrendChart({
  rows,
  visibleGames,
  showSummary = false,
}: {
  rows: TrendRow[];
  visibleGames?: number;
  showSummary?: boolean;
}) {
  const selectedRows = visibleGames === undefined ? rows : rows.slice(-visibleGames);
  const points = useMemo(() => {
    const rates = rollingWinRates(rows);
    return visibleGames === undefined ? rates : rates.slice(-visibleGames);
  }, [rows, visibleGames]);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const wins = selectedRows.filter((row) => row.outcome === 'win').length;
  const losses = selectedRows.length - wins;
  const averageRate = selectedRows.length ? `${Math.round((100 * wins) / selectedRows.length)}%` : '—';
  const fullWindowStart = Math.max(0, TREND_WINDOW - 1 - (rows.length - points.length));
  const fullWindowPoints = points.slice(fullWindowStart);
  const lowRate = fullWindowPoints.length
    ? fullWindowPoints.reduce((low, point) => Math.min(low, point.rate), 100)
    : null;
  const highRate = fullWindowPoints.length
    ? fullWindowPoints.reduce((high, point) => Math.max(high, point.rate), 0)
    : null;
  const summary = showSummary ? (
    <div className="trend-summary" aria-label="Average win rate and rolling extremes">
      <div>
        <span>Average Win Rate</span>
        <strong>{averageRate}</strong>
      </div>
      <div>
        <span title="Lowest complete 30-game rolling win rate">Low %</span>
        <strong>{lowRate === null ? '—' : `${Math.round(lowRate)}%`}</strong>
      </div>
      <div>
        <span title="Highest complete 30-game rolling win rate">High %</span>
        <strong>{highRate === null ? '—' : `${Math.round(highRate)}%`}</strong>
      </div>
    </div>
  ) : null;

  if (points.length < 5) {
    return <>{summary}<p className="empty-state">Not enough finished games to chart a trend yet.</p></>;
  }

  const step = VIEW_WIDTH / (points.length - 1);
  const coords = points.map((point, index) => ({
    x: index * step,
    y: VIEW_HEIGHT - (point.rate / 100) * VIEW_HEIGHT,
  }));
  const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const area = `${line} L${VIEW_WIDTH},${VIEW_HEIGHT} L0,${VIEW_HEIGHT} Z`;
  const latest = points[points.length - 1];
  const lowIndex = lowRate === null
    ? null
    : points.findIndex((point, index) => index >= fullWindowStart && point.rate === lowRate);
  const highIndex = highRate === null
    ? null
    : points.findIndex((point, index) => index >= fullWindowStart && point.rate === highRate);
  const valueLabelY = Math.min(Math.max(coords[coords.length - 1].y - 4, 10), VIEW_HEIGHT - 4);

  const handleMouseMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const width = event.currentTarget.clientWidth ?? 0;
    const offsetX = event.nativeEvent.offsetX ?? 0;
    if (!width || points.length < 2) {
      return;
    }
    const ratio = Math.min(1, Math.max(0, offsetX / width));
    setHoverIndex(Math.round(ratio * (points.length - 1)));
  };

  const hovered = hoverIndex !== null && hoverIndex >= 0 && hoverIndex < points.length ? hoverIndex : null;
  const hoverLeftPct = hovered !== null ? Math.min(95, Math.max(5, (hovered / (points.length - 1)) * 100)) : null;

  return (
    <>
      {summary}
      <figure className="trend-chart" aria-label="Rolling win rate trend">
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Rolling win rate across ${points.length} games, currently ${latest.rate.toFixed(0)}%`}
          focusable="false"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
        >
          <line className="trend-guide" x1="0" y1={VIEW_HEIGHT / 2} x2={VIEW_WIDTH} y2={VIEW_HEIGHT / 2} />
          <path className="trend-area" d={area} />
          <path className="trend-line" d={line} />
          {lowIndex !== null ? <circle className="trend-point trend-point-low" cx={coords[lowIndex].x} cy={coords[lowIndex].y} r="3" /> : null}
          {highIndex !== null ? <circle className="trend-point trend-point-high" cx={coords[highIndex].x} cy={coords[highIndex].y} r="3" /> : null}
          <circle className="trend-point trend-point-latest" cx={coords[coords.length - 1].x} cy={coords[coords.length - 1].y} r="3.5" />
          {hovered !== null ? (
            <>
              <line
                className="chart-hover-line"
                x1={coords[hovered].x}
                y1={0}
                x2={coords[hovered].x}
                y2={VIEW_HEIGHT}
              />
              <circle className="trend-point trend-point-hover" cx={coords[hovered].x} cy={coords[hovered].y} r="4" />
            </>
          ) : null}
        </svg>
        <span
          className="chart-axis-float chart-axis-float-right"
          style={{ top: `${Math.min(84, Math.max(4, (valueLabelY / 120) * 100))}%` }}
          aria-hidden="true"
        >
          {latest.rate.toFixed(0)}%
        </span>
        {hovered !== null ? (
          <div className="chart-tooltip" style={{ left: `${hoverLeftPct}%`, top: '2.4rem' }}>
            {formatDate(points[hovered].started_at)} · {points[hovered].rate.toFixed(0)}%
          </div>
        ) : null}
        <div className="trend-axis">
          <span>{formatDate(points[0].started_at)}</span>
          <span className="trend-axis-record">{selectedRows.length} games · {wins} wins / {losses} losses</span>
          <span>{formatDate(latest.started_at)}</span>
        </div>
      </figure>
    </>
  );
}
