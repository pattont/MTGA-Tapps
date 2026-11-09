import type { CSSProperties } from 'react';
import type { LiveDeckRecord, LiveNow } from '../../api';
import { ColorPips } from '../../components/ColorPips';
import { gamesIn, percent, RATE_MIN_GAMES, showsGame, streak } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';
import { Score, StatColumn, type StatColumnData } from './StatColumn';

/** A strip of columns; a column with no games is left out, and an empty strip is not drawn. */
function Strip({ columns }: { columns: StatColumnData[] }) {
  const shown = columns.filter((column) => gamesIn(column.score) > 0);
  const count = shown.length;
  if (count === 0) return null;
  return (
    <div className="ds-strip" style={{ '--ds-cols': count } as CSSProperties}>
      {shown.map((column) => (
        <StatColumn key={column.key} column={column} />
      ))}
    </div>
  );
}

export function DeckStatsView({ now, record, options }: { now: LiveNow; record: LiveDeckRecord | null; options: StreamOptions }) {
  const recent = record?.recent ?? [];
  const run = streak(recent);
  const total = gamesIn(record);
  const main: StatColumnData[] = record
    ? [
        ...(shows(options, 'queues')
          ? [
              { key: 'ranked', label: 'Ranked', score: record.ranked },
              { key: 'casual', label: 'Casual', score: record.unranked },
            ]
          : []),
        ...(shows(options, 'turn')
          ? [
              { key: 'play', label: 'Play', score: record.play },
              { key: 'draw', label: 'Draw', score: record.draw },
            ]
          : []),
      ]
    : [];
  return (
    <div className="sk-panel ds">
      <div className="ds-head">
        <span className="ds-name">{now.deck_name}</span>
        <ColorPips colors={now.player_colors} size={16} />
        <Brand show={options.brand} />
      </div>
      {record && total >= RATE_MIN_GAMES ? (
        <div className="ds-main">
          <span className="ds-rate">{percent(record.win_rate)}</span>
          <span className="ds-main-side">
            <Score score={record} />
            <span className="ds-caption">win rate with this deck</span>
          </span>
        </div>
      ) : record ? (
        <div className="ds-main">
          <Score score={record} className="ds-rate sk-score" />
          <span className="ds-caption">
            {total} {total === 1 ? 'game' : 'games'} with this deck
          </span>
        </div>
      ) : (
        <div className="ds-main ds-first">First recorded game with this deck</div>
      )}
      <Strip columns={main} />
      {record && shows(options, 'form') && recent.length > 0 ? (
        <div className="ds-form">
          <span className="sk-col-label">Last {recent.length}</span>
          <span className="ds-dots" aria-label={`Last ${recent.length} games, oldest first`}>
            {[...recent].reverse().map((outcome, index) => (
              <span key={index} className={`ds-dot ds-dot-${outcome === 'win' ? 'win' : 'loss'}`} title={outcome === 'win' ? 'Win' : 'Loss'} />
            ))}
          </span>
          {run && run.length >= 2 ? (
            <span className="ds-streak">
              {run.length} {run.outcome === 'win' ? 'wins' : 'losses'} in a row
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Deck stats: up during a game (and between games with idle=show). */
export function DeckStatsWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const now = payload?.tracker.state === 'offline' ? null : payload?.now;
  if (!showsGame(now, options.idle) || !now.deck_name) return null;
  return <DeckStatsView now={now} record={now.deck_record ?? null} options={options} />;
}
