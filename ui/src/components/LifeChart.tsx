import { useState } from 'react';
import type { LifePoint } from '../api';

const VIEW_WIDTH = 600;
const VIEW_HEIGHT = 130;
// Generous vertical padding keeps the max/zero gridlines clear of the
// floating axis labels rendered above and below them.
const PADDING = 22;
const MAX_TURN_LABELS = 14;

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

interface TurnTick {
  index: number;
  turn: number;
}

/** First data point of each turn, thinned to at most MAX_TURN_LABELS entries. */
function turnTicks(points: LifePoint[]): TurnTick[] {
  const ticks: TurnTick[] = [];
  let lastTurn: number | null = null;
  points.forEach((point, index) => {
    const turn = point.turn_number;
    if (turn !== null && turn !== undefined && turn !== lastTurn) {
      ticks.push({ index, turn });
      lastTurn = turn;
    }
  });
  const step = Math.ceil(ticks.length / MAX_TURN_LABELS);
  return step > 1 ? ticks.filter((_, index) => index % step === 0) : ticks;
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
  const ticks = turnTicks(points);

  // Read the pointer against the wrapper's own box: offsetX would be relative
  // to whichever child element (line path, gridline) is under the cursor.
  const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || points.length < 2) {
      return;
    }
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    setHoverIndex(Math.round(ratio * (points.length - 1)));
  };

  const hovered = hoverIndex !== null && hoverIndex >= 0 && hoverIndex < points.length ? hoverIndex : null;
  const hoverLeftPct = hovered !== null ? Math.min(88, Math.max(6, (hovered / (points.length - 1)) * 100)) : null;
  const hoveredPoint = hovered !== null ? points[hovered] : null;

  return (
    <figure className="life-chart" aria-label="Life totals over the game">
      <div className="trend-meta">
        <span>Final (You / Opp)</span>
        <strong>
          {latest.player_life} / {latest.opponent_life}
        </strong>
      </div>
      <div
        className="life-svg-wrap"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Life totals over ${points.length} recorded points, final ${latest.player_life} versus ${latest.opponent_life}`}
          focusable="false"
        >
          {ticks.map((tick) => (
            <line
              key={`grid-${tick.turn}`}
              className="life-turn-grid"
              x1={tick.index * step}
              y1={PADDING - 6}
              x2={tick.index * step}
              y2={VIEW_HEIGHT - PADDING + 6}
            />
          ))}
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
        </svg>
        <span className="life-axis-label life-axis-label-top" aria-hidden="true">
          {maxLife}
        </span>
        <span className="life-axis-label life-axis-label-bottom" aria-hidden="true">0</span>
        {hoveredPoint !== null ? (
          <div className="chart-tooltip" style={{ left: `${hoverLeftPct}%`, top: '8px' }}>
            Turn {hoveredPoint.turn_number ?? '—'} · You {hoveredPoint.player_life} · Opp{' '}
            {hoveredPoint.opponent_life}
          </div>
        ) : null}
      </div>
      <div className="life-axis-x" aria-hidden="true">
        {ticks.map((tick) => (
          <span
            key={`label-${tick.turn}`}
            className="life-axis-tick"
            style={{ left: `${(tick.index / (points.length - 1)) * 100}%` }}
          >
            T{tick.turn}
          </span>
        ))}
      </div>
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
