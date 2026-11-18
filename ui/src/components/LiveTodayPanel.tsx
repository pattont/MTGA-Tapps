import type { LivePayload, LiveScore } from '../api';
import { todayView } from '../liveToday';
import { gamesIn, percent, rate } from '../stream/liveView';
import { DeckLink } from './DeckLink';

/** Decks listed before the rest fold into "+N more". */
const DECKS_SHOWN = 6;

/** One side of the coin flip: its record, and its win rate once it has a game. */
function SideTile({ side, label, score }: { side: 'play' | 'draw'; label: string; score: LiveScore }) {
  const games = gamesIn(score);
  return (
    <div className="live-stat">
      <span className="live-stat-value">{games > 0 ? `${score.wins}–${score.losses}` : '—'}</span>
      <span className="live-stat-label">
        <span className={`live-today-${side}`}>{label}</span>
        {games > 0 ? ` · ${percent(rate(score.wins, score.losses))}` : ''}
      </span>
    </div>
  );
}

/** How many games went one way with the lands; a dash when the tracker does not say. */
function LuckTile({ kind, label, title, games }: { kind: 'flood' | 'screw'; label: string; title: string; games: number | null }) {
  return (
    <div className="live-stat" title={title}>
      <span className="live-stat-value">{games ?? '—'}</span>
      <span className={`live-stat-label live-today-${kind}`}>{label}</span>
    </div>
  );
}

interface LiveTodayPanelProps {
  payload: LivePayload | null;
  /** The current time, for telling today's games apart. */
  nowMs: number;
}

/**
 * The Live Scoreboard's Today box: the record for every game that started
 * today (from local midnight), on the play and on the draw, the current
 * streak, how many games were flood or mana screw, and each deck's record.
 */
export function LiveTodayPanel({ payload, nowMs }: LiveTodayPanelProps) {
  const view = todayView(payload, nowMs);
  const decided = view ? view.wins + view.losses : 0;

  return (
    <section className="dashboard-section live-today">
      <div className="section-heading">
        <h3>Today</h3>
      </div>
      {view ? (
        <div className="live-today-body">
          <div className="live-today-head">
            <span
              className="live-today-record"
              aria-label={`${view.wins} wins, ${view.losses} losses${view.draws ? `, ${view.draws} draws` : ''}`}
            >
              <span className="live-today-w">{view.wins}</span>
              <span className="live-today-dash">–</span>
              <span className="live-today-l">{view.losses}</span>
              {view.draws ? (
                <>
                  <span className="live-today-dash">–</span>
                  <span>{view.draws}</span>
                </>
              ) : null}
            </span>
            {view.winRate !== null ? <span className="live-today-rate">{percent(view.winRate)}</span> : null}
            <span className="live-today-games">
              {view.games} {view.games === 1 ? 'game' : 'games'}
            </span>
          </div>
          {decided > 0 ? (
            <div className="live-today-bar" aria-hidden="true">
              <i style={{ width: `${(100 * view.wins) / decided}%` }} />
            </div>
          ) : null}
          <div className="live-stats">
            <SideTile side="play" label="On the play" score={view.play} />
            <SideTile side="draw" label="On the draw" score={view.draw} />
          </div>
          <div className="live-stats live-stats-three">
            <div className="live-stat">
              <span
                className={
                  view.streak ? `live-stat-value ${view.streak.outcome === 'win' ? 'live-stat-good' : 'live-stat-bad'}` : 'live-stat-value'
                }
              >
                {view.streak ? `${view.streak.outcome === 'win' ? 'W' : 'L'}${view.streak.length}` : '—'}
              </span>
              <span className="live-stat-label">Streak</span>
            </div>
            <LuckTile kind="flood" label="Flood" title="Games with too many lands (Game Detail's Flood)" games={view.floodGames} />
            <LuckTile kind="screw" label="Mana screw" title="Games short on lands (Game Detail's Mana Screw)" games={view.screwGames} />
          </div>
          {view.decks.length > 0 ? (
            <div className="live-today-decks">
              <h4>Decks</h4>
              <ul>
                {view.decks.slice(0, DECKS_SHOWN).map((deck) => (
                  <li key={deck.deck_name}>
                    <DeckLink deckName={deck.deck_name} />
                    <span className="live-today-deck-record">
                      {deck.wins}–{deck.losses}
                    </span>
                    <span className="live-today-deck-rate">{percent(rate(deck.wins, deck.losses))}</span>
                  </li>
                ))}
              </ul>
              {view.decks.length > DECKS_SHOWN ? (
                <p className="live-today-more">+{view.decks.length - DECKS_SHOWN} more</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="empty-state">Nothing recorded yet.</p>
      )}
    </section>
  );
}
