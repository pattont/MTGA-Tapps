import { useState } from 'react';
import type { LifePoint } from '../api';

const VIEW_WIDTH = 600;
const VIEW_HEIGHT = 130;
const PADDING = 10;

function pathFor(values: number[], maxLife: number): string {
  if (values.length === 0) {
    return '';
  }
  const usableHeight = VIEW_HEIGHT - PADDING * 2;
  const step = values.length > 1 ? VIEW_WIDTH / (values.length - 1) : VIEW_WIDTH;
  return values
    .map((value, index) => {
      const x = index * step;
      const y = PADDING + usableHeight - (value / maxLife) * usableHeight;
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

export function LifeChart({ points }: { points: LifePoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (points.length < 2) {
    return <p className="empty-state">Not enough life-total data for this game yet.</p>;
  }

  const maxLife = Math.max(20, ...points.map((point) => point.player_life), ...points.map((point) => point.opponent_life));
  const playerPath = pathFor(
    points.map((point) => point.player_life),
    maxLife,
  );
  const opponentPath = pathFor(
    points.map((point) => point.opponent_life),
    maxLife,
  );
  const latest = points[points.length - 1];
  const step = VIEW_WIDTH / (points.length - 1);

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
  const hoveredPoint = hovered !== null ? points[hovered] : null;

  return (
    <figure className="life-chart" aria-label="Life totals over the game">
      <div className="trend-meta">
        <span>Life totals</span>
        <strong>
          {latest.player_life} / {latest.opponent_life}
        </strong>
      </div>
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Life totals over ${points.length} recorded points, final ${latest.player_life} versus ${latest.opponent_life}`}
        focusable="false"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <line className="trend-guide" x1="0" y1={VIEW_HEIGHT / 2} x2={VIEW_WIDTH} y2={VIEW_HEIGHT / 2} />
        <path className="life-line-player" d={playerPath} />
        <path className="life-line-opponent" strokeDasharray="5 3" d={opponentPath} />
        {hovered !== null ? (
          <line
            className="chart-hover-line"
            x1={hovered * step}
            y1={0}
            x2={hovered * step}
            y2={VIEW_HEIGHT}
          />
        ) : null}
        <text className="chart-value-label" x={4} y={PADDING + 8}>
          {maxLife}
        </text>
        <text className="chart-value-label" x={4} y={VIEW_HEIGHT - PADDING}>
          0
        </text>
      </svg>
      {hoveredPoint !== null ? (
        <div className="chart-tooltip" style={{ left: `${hoverLeftPct}%`, top: '2.4rem' }}>
          Turn {hoveredPoint.turn_number ?? '—'} · You {hoveredPoint.player_life} · Opp {hoveredPoint.opponent_life}
        </div>
      ) : null}
      <div className="life-legend">
        <span>
          <span className="life-legend-swatch life-legend-swatch-player" aria-hidden="true" />
          Player
        </span>
        <span>
          <span className="life-legend-swatch life-legend-swatch-opponent" aria-hidden="true" />
          Opponent
        </span>
      </div>
      <details className="chart-data-details">
        <summary>View as table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Turn</th>
              <th scope="col">Player life</th>
              <th scope="col">Opponent life</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={`${point.turn_number ?? 'x'}-${index}`}>
                <td>{point.turn_number ?? '—'}</td>
                <td>{point.player_life}</td>
                <td>{point.opponent_life}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
