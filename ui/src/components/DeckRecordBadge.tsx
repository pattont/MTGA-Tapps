import type { ReactNode } from 'react';
import type { DeckRecord } from '../deckManagerApi';

type Score = { wins: number; losses: number };

const games = (score?: Score) => (score ? score.wins + score.losses : 0);
const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const sentence = (score: Score) => `${plural(score.wins, 'win', 'wins')}, ${plural(score.losses, 'loss', 'losses')}`;

/** A win rate, green at 50% or better; a dash without games. */
function Rate({ score }: { score?: Score }) {
  if (!score || !games(score)) return <span className="deck-record-none">–</span>;
  const rate = Math.round((100 * score.wins) / games(score));
  return <span className={rate >= 50 ? 'is-winning' : 'is-losing'}>{rate}%</span>;
}

function Column({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <span className="deck-record-column">
      <span className="deck-record-label">{label}</span>
      <span className="deck-record-value">{children}</span>
    </span>
  );
}

/**
 * A deck's tracked record as a small table, columns split by thin lines:
 * Ranked and Casual (every unranked queue and event) records, each only when
 * played; win rate on the play (teal) / on the draw (purple); and games played.
 * Without games it says so, faintly. Used on tiles, in both deck dialogs and in
 * Compare (`className` sets the context).
 */
export function DeckRecordBadge({ record, className = '' }: { record?: DeckRecord | null; className?: string }) {
  const played = record ? record.wins + record.losses : 0;
  if (!record || !played) {
    return <span className={`deck-record deck-record-empty ${className}`.trim()} title="The tracker hasn’t recorded a game with this deck yet.">No games logged</span>;
  }
  const queues = ([['Ranked', 'Ranked', record.ranked], ['Casual', 'Casual (unranked queues and events)', record.unranked]] as const)
    .flatMap(([label, hint, score]) => (score && games(score) ? [{ label, hint, score }] : []));
  const turnOrder = games(record.play) + games(record.draw) > 0;
  const title = [
    ...queues.map(({ hint, score }) => `${hint}: ${sentence(score)}`),
    ...(turnOrder ? [`On the play: ${record.play && games(record.play) ? sentence(record.play) : 'no games'}`,
      `On the draw: ${record.draw && games(record.draw) ? sentence(record.draw) : 'no games'}`] : []),
    `${plural(played, 'game', 'games')} played with this deck, under any name.`,
  ].join('\n');
  return (
    <span className={`deck-record ${className}`.trim()} title={title}>
      {queues.map(({ label, score }) => (
        <Column key={label} label={label}>
          <span className="deck-record-score">{score.wins}–{score.losses}</span><Rate score={score} />
        </Column>
      ))}
      {turnOrder ? (
        <Column label={<><span className="deck-record-play">Play</span> / <span className="deck-record-draw">Draw</span></>}>
          <Rate score={record.play} /><span className="deck-record-none">/</span><Rate score={record.draw} />
        </Column>
      ) : null}
      <Column label="Played"><span className="deck-record-score">{played}</span></Column>
    </span>
  );
}
