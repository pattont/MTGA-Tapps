import { useEffect, useRef, useState } from 'react';
import type { LiveNow } from '../../api';
import { ColorPips } from '../../components/ColorPips';
import { clock, opponentDeck, secondsSince, showsGame } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { useNow } from '../useNow';
import { Brand } from './Brand';

/** How long a life change stays called out. */
const DELTA_MS = 1600;

/** A life total that flashes and shows the change (−3, +2) when it moves. */
function Life({ value, side }: { value: number | null; side: 'you' | 'opp' }) {
  const previous = useRef<number | null>(value);
  const [delta, setDelta] = useState<{ amount: number; key: number } | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (before === null || value === null || before === value) return undefined;
    setDelta({ amount: value - before, key: Date.now() });
    const timer = window.setTimeout(() => setDelta(null), DELTA_MS);
    return () => window.clearTimeout(timer);
  }, [value]);
  const tone = delta ? (delta.amount > 0 ? 'up' : 'down') : null;
  return (
    <span className={`sb-life sb-life-${side}${tone ? ` sb-life-${tone}` : ''}`}>
      <span key={delta?.key ?? 'steady'} className="sb-life-value">
        {value ?? '—'}
      </span>
      {delta ? (
        <span key={`d${delta.key}`} className={`sb-delta sb-delta-${tone}`} aria-hidden="true">
          {delta.amount > 0 ? `+${delta.amount}` : `−${-delta.amount}`}
        </span>
      ) : null}
    </span>
  );
}

function Side({
  side,
  name,
  detail,
  colors,
  life,
  active,
}: {
  side: 'you' | 'opp';
  name: string;
  detail: string | null;
  colors: string;
  life: number | null;
  active: boolean;
}) {
  return (
    <div className={`sb-side sb-side-${side}${active ? ' sb-active' : ''}`}>
      <div className="sb-who">
        <span className="sb-name">{name}</span>
        <span className="sb-detail">
          {side === 'you' ? <ColorPips colors={colors} size={14} /> : null}
          <span className="sb-detail-text">{detail ?? ''}</span>
          {side === 'opp' ? <ColorPips colors={colors} size={14} /> : null}
        </span>
      </div>
      <Life value={life} side={side} />
    </div>
  );
}

export function ScorebugView({ now, options, nowMs }: { now: LiveNow; options: StreamOptions; nowMs: number }) {
  const live = now.in_game;
  const yourTurn = live && now.active_role === 'player';
  const theirTurn = live && now.active_role === 'opponent';
  const elapsed = shows(options, 'timer') && live ? secondsSince(now.turn_started_at, nowMs) : null;
  const bo3 = now.match_type === 'best_of_3';
  const score = now.match_score;
  return (
    <div className="sk-panel sb">
      <Side
        side="you"
        name={now.player_name || 'You'}
        detail={!shows(options, 'yourdeck') ? null : now.player_commanders.length > 0 ? now.player_commanders.join(' + ') : now.deck_name}
        colors={now.player_colors}
        life={now.player_life}
        active={yourTurn}
      />
      <div className="sb-mid">
        <div className="sb-turn">
          {live ? (
            <>
              <span className="sb-turn-label">Turn</span>
              <span className="sb-turn-number">{now.turn_number ?? '—'}</span>
            </>
          ) : (
            <span className="sb-final">Final</span>
          )}
        </div>
        {live && (yourTurn || theirTurn) ? (
          <div className={`sb-whose ${yourTurn ? 'sb-whose-you' : 'sb-whose-opp'}`}>
            {yourTurn ? 'Your turn' : 'Their turn'}
            {elapsed !== null ? <span className="sb-timer">{clock(elapsed)}</span> : null}
          </div>
        ) : null}
        {bo3 && shows(options, 'match') ? (
          <div className="sb-match">
            Game {now.game_number ?? 1}
            {score ? (
              <>
                {' · '}
                <span className="sk-win">{score.wins}</span>
                <span className="sk-dash">–</span>
                <span className="sk-loss">{score.losses}</span>
              </>
            ) : null}
          </div>
        ) : null}
        <Brand show={options.brand} />
      </div>
      <Side
        side="opp"
        name={options.opponent && now.opponent_name ? now.opponent_name : 'Opponent'}
        detail={shows(options, 'theirdeck') ? opponentDeck(now) : null}
        colors={now.opponent_colors}
        life={now.opponent_life}
        active={theirTurn}
      />
    </div>
  );
}

/** Scorebug: up during a game (and between games with idle=show). */
export function ScorebugWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const now = payload?.tracker.state === 'offline' ? null : payload?.now;
  const visible = showsGame(now, options.idle);
  const nowMs = useNow(visible && shows(options, 'timer') && Boolean(now?.in_game));
  if (!visible) return null;
  return <ScorebugView now={now} options={options} nowMs={nowMs} />;
}
