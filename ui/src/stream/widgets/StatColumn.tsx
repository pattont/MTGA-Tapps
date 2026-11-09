import type { LiveScore } from '../../api';
import { gamesIn, percent, rate, RATE_MIN_GAMES } from '../liveView';

/** "34–21": wins in the text colour, the dash and losses muted. */
export function Score({ score, className = 'sk-score' }: { score: LiveScore; className?: string }) {
  return (
    <span className={className}>
      <span className="sk-score-w">{score.wins}</span>
      <span className="sk-score-l">–{score.losses}</span>
    </span>
  );
}

export interface StatColumnData {
  key: string;
  label: string;
  score: LiveScore | undefined;
}

/**
 * One column of a stat strip (deck stats, record): label, rate, record, or
 * only the record under RATE_MIN_GAMES. `sk-col-play`/`sk-col-draw` take the
 * teal/purple of play and draw.
 */
export function StatColumn({ column }: { column: StatColumnData }) {
  const score = column.score!;
  return (
    <div className={`sk-col sk-col-${column.key}`}>
      <span className="sk-col-label">{column.label}</span>
      {gamesIn(score) >= RATE_MIN_GAMES ? (
        <>
          <span className="sk-col-rate">{percent(rate(score.wins, score.losses))}</span>
          <Score score={score} />
        </>
      ) : (
        <Score score={score} className="sk-col-rate sk-score" />
      )}
    </div>
  );
}
