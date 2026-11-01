import type { LivePayload } from '../../api';
import { rankText } from '../../format';
import type { StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';

export function RecordView({ payload, options }: { payload: LivePayload; options: StreamOptions }) {
  const session = payload.session;
  const wins = session?.wins ?? 0;
  const losses = session?.losses ?? 0;
  const draws = session?.draws ?? 0;
  const now = payload.now;
  const deck = now?.deck_record;
  const deckToday = deck && deck.today_wins + deck.today_losses > 0 ? deck : null;
  return (
    <div className="sk-panel sk-record">
      <div className="sk-record-main">
        <span className="sk-label">Session</span>
        <span className="sk-big" aria-label={`${wins} wins, ${losses} losses${draws ? `, ${draws} draws` : ''}`}>
          <span className="sk-win">{wins}</span>
          <span className="sk-dash">–</span>
          <span className="sk-loss">{losses}</span>
          {draws ? (
            <>
              <span className="sk-dash">–</span>
              <span>{draws}</span>
            </>
          ) : null}
        </span>
        {session?.win_rate != null ? <span className="sk-rate">{Math.round(session.win_rate)}%</span> : null}
      </div>
      <div className="sk-chips">
        {now?.rank ? <span className="sk-chip sk-chip-rank">{rankText(now.rank)}</span> : null}
        {deckToday ? (
          <span className="sk-chip">
            Deck today {deckToday.today_wins}–{deckToday.today_losses}
          </span>
        ) : null}
        <Brand show={options.brand} />
      </div>
    </div>
  );
}

/** Session record: shown whenever the tracker is running. */
export function RecordWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  if (!payload || payload.tracker.state === 'offline') return null;
  return <RecordView payload={payload} options={options} />;
}
