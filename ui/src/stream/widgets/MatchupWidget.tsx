import type { LiveNow } from '../../api';
import { ColorPips } from '../../components/ColorPips';
import { opponentDeck } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { Brand } from './Brand';

export function MatchupView({ now, options }: { now: LiveNow; options: StreamOptions }) {
  const deck = opponentDeck(now);
  const h2h = now.head_to_head;
  const bo3 = now.match_type === 'best_of_3';
  return (
    <div className="sk-panel sk-matchup">
      <div className="sk-vs">
        <span className="sk-label">vs</span>
        <span className="sk-opp">{options.opponent && now.opponent_name ? now.opponent_name : 'Opponent'}</span>
        <ColorPips colors={now.opponent_colors} size={18} />
        {/* Top right, so the credit never needs a line of its own. */}
        <Brand show={options.brand} />
      </div>
      <div className="sk-arch">{deck ?? 'Deck not revealed yet'}</div>
      <div className="sk-chips">
        {shows(options, 'order') && now.on_play != null ? (
          <span className={`sk-chip ${now.on_play ? 'sk-chip-play' : 'sk-chip-draw'}`}>
            {now.on_play ? 'On the play' : 'On the draw'}
          </span>
        ) : null}
        {shows(options, 'game') && bo3 && now.game_number ? <span className="sk-chip">Game {now.game_number} of 3</span> : null}
        {shows(options, 'turn') && now.turn_number ? <span className="sk-chip">Turn {now.turn_number}</span> : null}
        {shows(options, 'h2h') && h2h && h2h.wins + h2h.losses > 0 ? (
          <span className="sk-chip">
            Head-to-head {h2h.wins}–{h2h.losses}
          </span>
        ) : null}
        {!now.in_game ? <span className="sk-chip sk-tag">Last game</span> : null}
      </div>
    </div>
  );
}

/** Matchup: shown during a game (and between games with idle=show). */
export function MatchupWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const now = payload?.tracker.state === 'offline' ? null : payload?.now;
  if (!now || !(now.in_game || (options.idle === 'show' && now.last_game_frozen))) return null;
  return <MatchupView now={now} options={options} />;
}
