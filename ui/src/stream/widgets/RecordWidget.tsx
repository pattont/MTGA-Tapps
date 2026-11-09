import type { LivePayload } from '../../api';
import { rankText } from '../../format';
import { gamesIn, PERIOD_LABEL, periodRecord } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';
import { StatColumn } from './StatColumn';

export function RecordView({ payload, options }: { payload: LivePayload; options: StreamOptions }) {
  const totals = periodRecord(payload, options.period);
  const wins = totals?.wins ?? 0;
  const losses = totals?.losses ?? 0;
  const draws = totals?.draws ?? 0;
  const now = payload.now;
  const rank = shows(options, 'rank') ? now?.rank : null;
  // The deck's record over the same span as the headline (today or this session).
  const deckRecord = now?.deck_record;
  const deck =
    shows(options, 'deck') && deckRecord
      ? options.period === 'today'
        ? { wins: deckRecord.today_wins, losses: deckRecord.today_losses }
        : { wins: deckRecord.session_wins ?? 0, losses: deckRecord.session_losses ?? 0 }
      : null;
  const deckShown = deck && deck.wins + deck.losses > 0 ? deck : null;
  // Play / draw on the right; a side with no games yet is left out.
  const sides = shows(options, 'turn')
    ? [
        { key: 'play', label: 'Play', score: totals?.play },
        { key: 'draw', label: 'Draw', score: totals?.draw },
      ].filter((side) => gamesIn(side.score) > 0)
    : [];
  return (
    <div className="sk-panel sk-record">
      <div className="sk-record-head">
        <span className="sk-label">{PERIOD_LABEL[options.period]}</span>
        <Brand show={options.brand} />
      </div>
      <div className="sk-record-body">
        <div className="sk-record-left">
          <div className="sk-record-main">
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
            {totals?.win_rate != null ? <span className="sk-rate">{Math.round(totals.win_rate)}%</span> : null}
          </div>
          {rank || deckShown ? (
            <div className="sk-chips">
              {rank ? <span className="sk-chip sk-chip-rank">{rankText(rank)}</span> : null}
              {deckShown ? (
                <span className="sk-chip">
                  Deck {deckShown.wins}–{deckShown.losses}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        {sides.length > 0 ? (
          <div className="sk-record-sides">
            {sides.map((side) => (
              <StatColumn key={side.key} column={side} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Record: shown whenever the tracker is running. */
export function RecordWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  if (!payload || payload.tracker.state === 'offline') return null;
  return <RecordView payload={payload} options={options} />;
}
