import type { ReactNode } from 'react';
import type { LivePayload } from '../../api';
import { ColorPips } from '../../components/ColorPips';
import { outcomeLabel, outcomeShortLabel, outcomeTone } from '../../format';
import { PERIOD_LABEL, percent, periodGames, periodRecord, rankName, rankOrder, secondsSince, span } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { useNow } from '../useNow';
import { Brand } from './Brand';

/** Today's results as W/L squares, oldest first (left to right). */
const MAX_RESULTS = 20;

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="br-row">
      <span className="br-label">{label}</span>
      <div className="br-value">{children}</div>
    </div>
  );
}

export function BreakView({ payload, options, nowMs }: { payload: LivePayload | null; options: StreamOptions; nowMs: number }) {
  const live = payload && payload.tracker.state !== 'offline' ? payload : null;
  const record = periodRecord(live, options.period);
  const games = record ? (options.period === 'today' ? live?.today?.games ?? 0 : live?.session?.games_played ?? 0) : 0;
  const now = live?.now ?? null;
  // The session's length; "today" has none worth showing.
  const length = options.period === 'session' ? secondsSince(live?.session?.started_at, nowMs) : null;
  const results = periodGames(live, options.period, nowMs)
    .filter((game) => outcomeTone(game.outcome) !== 'neutral')
    .slice(0, MAX_RESULTS)
    .reverse();
  const deck = now?.deck_name ? now.deck_record : null;
  const rank = now?.rank ?? null;
  const climb = rank?.start ? rankOrder(rank) - rankOrder(rank.start) : 0;

  return (
    <div className="sk-panel br">
      <div className="br-top">
        <span className="br-title">{options.title || 'Be right back'}</span>
        <Brand show={options.brand} />
      </div>
      {shows(options, 'session') && record && games > 0 ? (
        <Row label={PERIOD_LABEL[options.period]}>
          <span className="br-record">
            <span className="sk-win">{record.wins}</span>
            <span className="sk-dash">–</span>
            <span className="sk-loss">{record.losses}</span>
            {record.draws ? (
              <>
                <span className="sk-dash">–</span>
                {record.draws}
              </>
            ) : null}
          </span>
          {record.win_rate != null ? <span className="br-rate">{percent(record.win_rate)}</span> : null}
          <span className="br-note">
            {games} {games === 1 ? 'game' : 'games'}
            {length !== null && length >= 60 ? ` · ${span(length)}` : ''}
          </span>
        </Row>
      ) : null}
      {shows(options, 'results') && results.length > 0 ? (
        <Row label="Games">
          <span className="br-results" aria-label={`${PERIOD_LABEL[options.period]}’s results, oldest first`}>
            {results.map((game) => (
              <span key={game.id} className={`sk-result sk-result-${outcomeTone(game.outcome)}`} title={outcomeLabel(game.outcome)}>
                {outcomeShortLabel(game.outcome)}
              </span>
            ))}
          </span>
        </Row>
      ) : null}
      {shows(options, 'deck') && now?.deck_name ? (
        <Row label="Deck">
          <span className="br-deck">
            <span className="br-deck-name">{now.deck_name}</span>
            <ColorPips colors={now.player_colors} size={15} />
          </span>
          {deck ? (
            <span className="br-note">
              <span className="sk-win">{deck.wins}</span>
              <span className="sk-dash">–</span>
              <span className="sk-loss">{deck.losses}</span> · {percent(deck.win_rate)}
            </span>
          ) : null}
        </Row>
      ) : null}
      {shows(options, 'rank') && rank ? (
        <Row label="Rank">
          {rank.start && climb !== 0 ? (
            <span className="br-rank">
              <span className="br-rank-from">{rankName(rank.start)}</span>
              <span className={climb > 0 ? 'br-up' : 'br-down'} aria-label={climb > 0 ? 'up to' : 'down to'}>
                {climb > 0 ? '▲' : '▼'}
              </span>
              <span className="br-rank-now">{rankName(rank)}</span>
            </span>
          ) : (
            <span className="br-rank">
              <span className="br-rank-now">{rankName(rank)}</span>
            </span>
          )}
          {rank.rank_class !== 'Mythic' ? (
            <span className="br-steps" aria-label={`${rank.rank_step} of ${rank.rank_steps} steps`}>
              {Array.from({ length: rank.rank_steps }, (_, step) => (
                <span key={step} className={step < rank.rank_step ? 'on' : ''} />
              ))}
            </span>
          ) : null}
        </Row>
      ) : null}
    </div>
  );
}

/** Intermission card: always up; the title stays even while the tracker is off. */
export function BreakWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const nowMs = useNow(true, 30_000);
  return <BreakView payload={payload} options={options} nowMs={nowMs} />;
}
