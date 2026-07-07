import { useMemo } from 'react';
import type { TrendRow } from '../api';
import { rollingWinRates, TREND_WINDOW } from '../trend';

const VIEW_WIDTH = 600;
const VIEW_HEIGHT = 120;

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
}

export function TrendChart({ rows }: { rows: TrendRow[] }) {
  const points = useMemo(() => rollingWinRates(rows), [rows]);

  if (points.length < 5) {
    return <p className="empty-state">Not enough finished games to chart a trend yet.</p>;
  }

  const step = VIEW_WIDTH / (points.length - 1);
  const coords = points.map((point, index) => ({
    x: index * step,
    y: VIEW_HEIGHT - (point.rate / 100) * VIEW_HEIGHT,
  }));
  const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const area = `${line} L${VIEW_WIDTH},${VIEW_HEIGHT} L0,${VIEW_HEIGHT} Z`;
  const latest = points[points.length - 1];

  return (
    <figure className="trend-chart" aria-label="Rolling win rate trend">
      <div className="trend-meta">
        <span>
          Rolling win rate <em>(last {Math.min(TREND_WINDOW, points.length)} games)</em>
        </span>
        <strong>{latest.rate.toFixed(0)}%</strong>
      </div>
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-hidden="true"
        focusable="false"
      >
        <line className="trend-guide" x1="0" y1={VIEW_HEIGHT / 2} x2={VIEW_WIDTH} y2={VIEW_HEIGHT / 2} />
        <path className="trend-area" d={area} />
        <path className="trend-line" d={line} />
      </svg>
      <div className="trend-axis">
        <span>{formatDate(points[0].started_at)}</span>
        <span>50% guide</span>
        <span>{formatDate(latest.started_at)}</span>
      </div>
    </figure>
  );
}
