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
        aria-hidden="true"
        focusable="false"
      >
        <line className="trend-guide" x1="0" y1={VIEW_HEIGHT / 2} x2={VIEW_WIDTH} y2={VIEW_HEIGHT / 2} />
        <path className="life-line-player" d={playerPath} />
        <path className="life-line-opponent" d={opponentPath} />
      </svg>
      <div className="life-legend">
        <span>Player</span>
        <span>Opponent</span>
      </div>
    </figure>
  );
}
