import { useEffect, useRef, useState } from 'react';
import type { LiveGameRow, LiveNow } from '../../api';
import { DEMO_LIVE, DEMO_RESULT } from '../demo';
import { clock, matchLine, percent, PERIOD_LABEL, periodRecord, resultFacts, resultTone, type PeriodRecord } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';

const WORDS = { win: 'Victory', loss: 'Defeat', draw: 'Draw' } as const;
/** The fade-out before the card goes. */
const LEAVE_MS = 600;

export function ResultView({
  game,
  now,
  record,
  options,
  leaving = false,
}: {
  game: LiveGameRow;
  now: LiveNow | null;
  /** The session's or today's record (options.period), the finished game included. */
  record: PeriodRecord | null;
  options: StreamOptions;
  leaving?: boolean;
}) {
  const tone = resultTone(game.outcome) ?? 'draw';
  const facts = shows(options, 'facts') ? resultFacts(game, now) : [];
  const match = shows(options, 'match') ? matchLine(game, now) : null;
  const chips = !shows(options, 'details') ? [] : [
    game.total_turns ? `Turn ${game.total_turns}` : null,
    game.duration_seconds ? clock(game.duration_seconds) : null,
    game.went_first === 1 ? 'On the play' : game.went_first === 0 ? 'On the draw' : null,
  ].filter((chip): chip is string => Boolean(chip));
  const opponent = options.opponent && game.opponent_name ? game.opponent_name : null;
  return (
    <div className={`sk-panel rs rs-${tone}${leaving ? ' rs-leaving' : ''}`} role="status" aria-live="polite">
      <div className="rs-glow" aria-hidden="true" />
      <div className="rs-top">
        {match ? <span className="rs-match">{match}</span> : <span />}
        <Brand show={options.brand} />
      </div>
      <div className="rs-word">{WORDS[tone]}</div>
      <div className="rs-deck">
        <span className="rs-deck-name">{game.deck_name ?? 'Your deck'}</span>
        {opponent ? <span className="rs-vs"> vs {opponent}</span> : null}
      </div>
      <div className="rs-chips">
        {chips.map((chip) => (
          <span key={chip} className="rs-chip">
            {chip}
          </span>
        ))}
      </div>
      {facts.length > 0 ? (
        <ul className="rs-facts">
          {facts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      ) : null}
      {shows(options, 'record') && record && record.wins + record.losses > 0 ? (
        <div className="rs-session">
          <span className="sk-label">{PERIOD_LABEL[options.period]}</span>
          <strong>
            <span className="sk-win">{record.wins}</span>
            <span className="sk-dash">–</span>
            <span className="sk-loss">{record.losses}</span>
          </strong>
          {record.win_rate != null ? <span className="rs-rate">{percent(record.win_rate)}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Game result: shows each game that finishes while the source is open, for
 * `seconds`, then fades. Games already over when the page loads are never
 * shown, so a scene switch or reload doesn't replay the last result.
 */
export function ResultWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const seen = useRef<string | null | undefined>(undefined);
  const [shown, setShown] = useState<LiveGameRow | null>(null);
  const [leaving, setLeaving] = useState(false);

  const newest = payload && payload.tracker.state !== 'offline' ? (payload.games[0] ?? null) : null;
  useEffect(() => {
    if (options.demo || !payload) return;
    if (seen.current === undefined) {
      // The first answer only sets the starting point.
      seen.current = newest?.id ?? null;
      return;
    }
    if (newest && newest.id !== seen.current && resultTone(newest.outcome)) {
      seen.current = newest.id;
      setShown(newest);
      setLeaving(false);
    }
  }, [payload, newest, options.demo]);

  useEffect(() => {
    if (!shown) return undefined;
    const fade = window.setTimeout(() => setLeaving(true), options.seconds * 1000);
    const gone = window.setTimeout(() => setShown(null), options.seconds * 1000 + LEAVE_MS);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(gone);
    };
  }, [shown, options.seconds]);

  if (options.demo) {
    const now = DEMO_LIVE.now ? {
          ...DEMO_LIVE.now,
          game_id: DEMO_RESULT.id,
          in_game: false,
          last_game_frozen: true,
          player_life: 20,
          match_score: { wins: 2, losses: 0, draws: 0 },
        } : null;
    return <ResultView game={DEMO_RESULT} now={now} record={periodRecord(DEMO_LIVE, options.period)} options={options} />;
  }
  if (!shown || !payload) return null;
  // The frozen scoreboard belongs to this game only if the ids match.
  const now = payload.now && payload.now.game_id === shown.id ? payload.now : null;
  return <ResultView game={shown} now={now} record={periodRecord(payload, options.period)} options={options} leaving={leaving} />;
}
