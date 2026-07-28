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
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
}

export function TrendChart({ rows }: { rows: TrendRow[] }) {
  const points = useMemo(() => rollingWinRates(rows), [rows]);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

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
        aria-label={`Rolling win rate across ${points.length} games, currently ${latest.rate.toFixed(0)}%`}
        focusable="false"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <line className="trend-guide" x1="0" y1={VIEW_HEIGHT / 2} x2={VIEW_WIDTH} y2={VIEW_HEIGHT / 2} />
        <path className="trend-area" d={area} />
        <path className="trend-line" d={line} />
        {hovered !== null ? (
          <line
            className="chart-hover-line"
            x1={coords[hovered].x}
            y1={0}
            x2={coords[hovered].x}
            y2={VIEW_HEIGHT}
          />
        ) : null}
        <text className="chart-value-label" x={VIEW_WIDTH - 4} y={valueLabelY} textAnchor="end">
          {latest.rate.toFixed(0)}%
        </text>
      </svg>
      {hovered !== null ? (
        <div className="chart-tooltip" style={{ left: `${hoverLeftPct}%`, top: '2.4rem' }}>
          {formatDate(points[hovered].started_at)} · {points[hovered].rate.toFixed(0)}%
        </div>
      ) : null}
      <div className="trend-axis">
        <span>{formatDate(points[0].started_at)}</span>
        <span>50% guide</span>
        <span>{formatDate(latest.started_at)}</span>
      </div>
      <details className="chart-data-details">
        <summary>View as table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Rolling win rate</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={`${point.started_at}-${index}`}>
                <td>{formatDate(point.started_at)}</td>
                <td>{point.rate.toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
