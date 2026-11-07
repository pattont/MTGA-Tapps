import type { LiveGameRow, LivePayload, LiveScore } from '../../api';
import { formatDuration, outcomeLabel, outcomeShortLabel, outcomeTone } from '../../format';
import { gamesIn, percent, PERIOD_LABEL, periodRecord, rate, RATE_MIN_GAMES } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';

/*
 * Live Scoreboard's Today's Games list for stream: the same rows (result,
 * deck with Play/Draw, opponent, turns, length), newest first, without the
 * replay links or the clock time.
 */

function GameRow({ game, options }: { game: LiveGameRow; options: StreamOptions }) {
  const tone = outcomeTone(game.outcome);
  const onPlay = !shows(options, 'order') ? null : game.went_first === 1 ? true : game.went_first === 0 ? false : null;
  const details = shows(options, 'details');
  const meta = [
    options.opponent && game.opponent_name ? `vs ${game.opponent_name}` : null,
    details && game.total_turns ? `${game.total_turns} turns` : null,
    details && game.duration_seconds ? formatDuration(game.duration_seconds) : null,
  ].filter(Boolean);
  return (
    <li className="sk-game">
      <span className={`sk-result sk-result-${tone}`} title={outcomeLabel(game.outcome)}>
        <span aria-hidden="true">{outcomeShortLabel(game.outcome)}</span>
        <span className="sk-hidden">{outcomeLabel(game.outcome)}</span>
      </span>
      <span className="sk-game-main">
        <span className="sk-game-deck">{game.deck_name ?? 'Unknown deck'}</span>
        {meta.length > 0 ? <span className="sk-game-meta">{meta.join(' · ')}</span> : null}
      </span>
      {onPlay === null ? null : (
        <span className={`sk-turn-order ${onPlay ? 'sk-chip-play' : 'sk-chip-draw'}`}>{onPlay ? 'Play' : 'Draw'}</span>
      )}
    </li>
  );
}

/** "Play 80%" (or "Play 2–1" under RATE_MIN_GAMES); nothing before a game on that side. */
function Side({ side, score }: { side: 'play' | 'draw'; score: LiveScore | undefined }) {
  if (!score || gamesIn(score) === 0) return null;
  const label = side === 'play' ? 'Play' : 'Draw';
  const record = `${score.wins}–${score.losses}`;
  return (
    <span className={`sk-games-side sk-games-side-${side}`} title={`On the ${side}: ${record}`}>
      <span className="sk-games-side-label">{label}</span>
      {gamesIn(score) >= RATE_MIN_GAMES ? percent(rate(score.wins, score.losses)) : record}
    </span>
  );
}

/** "Session 6–2 · 75%" (or today's), the same numbers as the Record widget. */
function PeriodLine({ payload, options }: { payload: LivePayload; options: StreamOptions }) {
  const session = periodRecord(payload, options.period);
  const wins = session?.wins ?? 0;
  const losses = session?.losses ?? 0;
  const draws = session?.draws ?? 0;
  return (
    <span className="sk-games-record">
      <span className="sk-label">{PERIOD_LABEL[options.period]}</span>
      <strong aria-label={`${wins} wins, ${losses} losses${draws ? `, ${draws} draws` : ''}`}>
        <span className="sk-win">{wins}</span>
        <span className="sk-dash">–</span>
        <span className="sk-loss">{losses}</span>
        {draws ? (
          <>
            <span className="sk-dash">–</span>
            {draws}
          </>
        ) : null}
      </strong>
      {session?.win_rate != null ? <span className="sk-games-rate">{Math.round(session.win_rate)}%</span> : null}
    </span>
  );
}

export function GamesView({ payload, options }: { payload: LivePayload; options: StreamOptions }) {
  const games = payload.games.slice(0, options.count);
  const record = shows(options, 'record');
  const totals = periodRecord(payload, options.period);
  return (
    <div className="sk-panel sk-games">
      {record ? (
        <div className="sk-games-head">
          <PeriodLine payload={payload} options={options} />
          <Brand show={options.brand} />
        </div>
      ) : null}
      <div className="sk-games-head">
        <span className="sk-label">{options.count === 1 ? 'Last game' : 'Recent games'}</span>
        {shows(options, 'turn') ? (
          // The play / draw split, above the rows' Play / Draw badges.
          <span className="sk-games-sides">
            <Side side="play" score={totals?.play} />
            <Side side="draw" score={totals?.draw} />
          </span>
        ) : null}
        {record ? null : <Brand show={options.brand} />}
      </div>
      {games.length > 0 ? (
        <ol className="sk-games-list">
          {games.map((game) => (
            <GameRow key={game.id} game={game} options={options} />
          ))}
        </ol>
      ) : (
        <div className="sk-sub">No games yet today</div>
      )}
    </div>
  );
}

/** Recent games: shown whenever the tracker is running, like the session record. */
export function GamesWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  if (!payload || payload.tracker.state === 'offline') return null;
  return <GamesView payload={payload} options={options} />;
}
