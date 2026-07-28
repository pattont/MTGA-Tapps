import { useMemo } from 'react';
import type { RankProgressRow } from '../api';
import { formatDateTime } from '../format';

const VIEW_WIDTH = 600;
const VIEW_HEIGHT = 150;
const MAX_RANK_SCORE = 120;
const RANK_LABELS = ['Mythic', 'Diamond', 'Platinum', 'Gold', 'Silver', 'Bronze'];

function normalizedRankRows(rows: RankProgressRow[]): RankProgressRow[] {
  const normalized: RankProgressRow[] = [];
  rows.forEach((row) => {
    if (row.rank_class === 'Mythic') {
      normalized.push(row);
      return;
    }
    const previous = normalized[normalized.length - 1];
    const sameTier =
      previous?.rank_class === row.rank_class && previous?.rank_level === row.rank_level;
    const sameRecord =
      sameTier &&
      previous.matches_won === row.matches_won &&
      previous.matches_lost === row.matches_lost;
    const advancedByWin =
      previous !== undefined &&
      sameTier &&
      row.rank_step === 0 &&
      row.matches_won !== null &&
      previous.matches_won !== null &&
      row.matches_won > previous.matches_won &&
      row.matches_lost === previous.matches_lost;
    const displayStep =
      row.raw_step !== null && row.raw_step !== undefined
        ? row.raw_step
        : row.rank_step > 0
          ? Math.min(row.rank_steps, row.rank_step + 1)
          : sameRecord
            ? previous?.rank_step ?? 0
            : advancedByWin
              ? 1
              : 0;
    normalized.push({
      ...row,
      rank_step: displayStep,
      rank_score: row.rank_score + (displayStep - row.rank_step),
      rank_label: `${row.rank_class} ${row.rank_level} (${displayStep}/${row.rank_steps})`,
    });
  });
  return normalized;
}

export function RankProgressChart({ rows }: { rows: RankProgressRow[] }) {
  const displayRows = useMemo(() => normalizedRankRows(rows), [rows]);
  const points = useMemo(
    () =>
      displayRows.map((row, index) => ({
        row,
        x:
          displayRows.length === 1
            ? VIEW_WIDTH / 2
            : (index * VIEW_WIDTH) / (displayRows.length - 1),
        y: VIEW_HEIGHT - (Math.max(0, Math.min(MAX_RANK_SCORE, row.rank_score)) / MAX_RANK_SCORE) * VIEW_HEIGHT,
      })),
    [displayRows],
  );

  if (points.length === 0) {
    return <p className="empty-state">No constructed rank snapshots have been captured yet.</p>;
  }

  const latest = points[points.length - 1].row;
  const line = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');

  return (
    <figure className="trend-chart rank-progress-chart" aria-label={`Constructed rank progress for season ${latest.season_ordinal}`}>
      <div className="trend-meta">
        <span>
          Constructed season {latest.season_ordinal} <em>({points.length} recorded changes)</em>
        </span>
        <strong>{latest.rank_label}</strong>
      </div>
      <div className="rank-chart-grid">
        <div className="rank-scale" aria-hidden="true">
          {RANK_LABELS.map((label) => <span key={label}>{label}</span>)}
        </div>
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Latest rank ${latest.rank_label}`}
        >
          {[0, 24, 48, 72, 96, 120].map((score) => {
            const y = VIEW_HEIGHT - (score / MAX_RANK_SCORE) * VIEW_HEIGHT;
            return <line key={score} className="trend-guide" x1="0" y1={y} x2={VIEW_WIDTH} y2={y} />;
          })}
          {points.length > 1 ? <path className="trend-line rank-progress-line" d={line} /> : null}
          {points.map((point) => (
            <circle key={point.row.id} className="rank-progress-point" cx={point.x} cy={point.y} r="4">
              <title>{`${point.row.rank_label} · ${formatDateTime(point.row.captured_at)}`}</title>
            </circle>
          ))}
        </svg>
      </div>
      <div className="trend-axis rank-progress-axis">
        <span>{formatDateTime(points[0].row.captured_at)}</span>
        <span>{latest.matches_won ?? 0}–{latest.matches_lost ?? 0} ranked record</span>
        <span>{formatDateTime(latest.captured_at)}</span>
      </div>
    </figure>
  );
}
