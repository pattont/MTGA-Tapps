import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchLiveStatus, type LiveEventRow, type LiveGameRow, type LiveNow, type LivePayload } from '../api';
import { formatDuration, outcomeLabel, outcomeTone, shortFormatLabel } from '../format';
import { Badge } from './Badge';
import { CardLink } from './CardLink';
import { ColorPips } from './ColorPips';
import { DeckLink } from './DeckLink';
import { TimelineList } from './TimelineList';
import { gameRouteHash } from '../routes';

/* Half a second keeps the feed feeling immediate without meaningful cost:
   each poll is a tiny indexed delta read of local SQLite, and polling
   pauses entirely while the tab is hidden. Much lower than this buys
   nothing — Arena flushes its log in bursts anyway. */
const POLL_MS = 500;
const MAX_FEED_ROWS = 600;

function commanderArtUrl(name: string): string {
  const front = name.split(' // ')[0];
  return `https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(front)}&format=image&version=art_crop`;
}

function gameClock(startedAt: string | null, nowMs: number): string | null {
  if (!startedAt) {
    return null;
  }
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) {
    return null;
  }
  return formatDuration(Math.max(0, Math.floor((nowMs - started) / 1000)));
}

function LifeReadout({ life, side }: { life: number | null; side: 'player' | 'opponent' }) {
  const previous = useRef<number | null>(null);
  const [pulse, setPulse] = useState<'up' | 'down' | null>(null);

  useEffect(() => {
    if (previous.current !== null && life !== null && life !== previous.current) {
      setPulse(life > previous.current ? 'up' : 'down');
      const timer = window.setTimeout(() => setPulse(null), 700);
      previous.current = life;
      return () => window.clearTimeout(timer);
    }
    previous.current = life;
    return undefined;
  }, [life]);

  return (
    <div className={`live-life live-life-${side}`}>
      <span className={pulse ? `live-life-value live-life-${pulse}` : 'live-life-value'}>
        {life ?? '—'}
      </span>
    </div>
  );
}

function CommanderCard({ name }: { name: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!name) {
    return (
      <div aria-hidden="true" className="live-commander live-commander-hidden" title="Not revealed yet">
        <span>?</span>
      </div>
    );
  }
  return (
    <div className="live-commander">
      {failed ? (
        <div className="live-commander-hidden">
          <span>?</span>
        </div>
      ) : (
        <img alt={name} loading="lazy" src={commanderArtUrl(name)} onError={() => setFailed(true)} />
      )}
      {/* Full card name, linked to /card, with the usual hover preview. */}
      <CardLink cardName={name} className="live-commander-name" returnHash="#/live">
        {name}
      </CardLink>
    </div>
  );
}

function Scoreboard({
  now,
  clockMs,
  waiting,
}: {
  now: LiveNow;
  clockMs: number;
  /** Game over: keep showing the final scoreboard, flagged as waiting. */
  waiting: boolean;
}) {
  const isBrawl = now.player_commanders.length > 0 || now.opponent_commanders.length > 0;
  const clock = waiting ? null : gameClock(now.game_started_at, clockMs);
  const turnChip =
    now.turn_number && now.active_role
      ? `Turn ${now.turn_number} — ${now.active_role === 'player' ? 'You' : 'Opponent'}`
      : now.turn_number
        ? `Turn ${now.turn_number}`
        : 'Starting up…';

  return (
    <div className="live-scoreboard">
      <div className="live-scoreboard-meta">
        {now.format ? <span className="live-chip">{shortFormatLabel(now.format)}</span> : null}
        {now.match_type === 'best_of_3' ? (
          <span className="live-chip">Game {now.game_number ?? 1} of 3</span>
        ) : null}
        {waiting ? (
          <span className="live-chip live-chip-previous">Previous Game</span>
        ) : (
          <span
            className={
              now.active_role === 'opponent' ? 'live-chip live-chip-turn live-chip-pulse' : 'live-chip live-chip-turn'
            }
          >
            {turnChip}
          </span>
        )}
      </div>

      <div className="live-versus">
        <div className="live-side">
          <p className="live-side-name">{now.player_name ?? 'You'}</p>
          <p className="live-side-detail">
            {isBrawl || !now.deck_name ? null : <DeckLink deckName={now.deck_name} />}
            <ColorPips colors={now.player_colors} />
          </p>
          {isBrawl ? (
            <div className="live-commanders">
              {(now.player_commanders.length > 0 ? now.player_commanders : [null]).map(
                (name, index) => (
                  <CommanderCard key={name ?? `p${index}`} name={name} />
                ),
              )}
            </div>
          ) : null}
          <LifeReadout life={now.player_life} side="player" />
        </div>

        <div aria-hidden="true" className="live-vs">
          vs
        </div>

        <div className="live-side live-side-opponent">
          <p className="live-side-name">{now.opponent_name ?? 'Opponent'}</p>
          {/* Opponent colors fill in the moment their cards reveal them. */}
          <p className="live-side-detail">
            <ColorPips colors={now.opponent_colors} />
          </p>
          {isBrawl ? (
            <div className="live-commanders">
              {(now.opponent_commanders.length > 0 ? now.opponent_commanders : [null]).map(
                (name, index) => (
                  <CommanderCard key={name ?? `o${index}`} name={name} />
                ),
              )}
            </div>
          ) : null}
          <LifeReadout life={now.opponent_life} side="opponent" />
        </div>
      </div>

      <div className="live-scoreboard-footer">
        <p className="live-scoreboard-footnote">
          {[
            now.on_play === null ? null : now.on_play ? 'On the play' : 'On the draw',
            now.mulligans ? `${now.mulligans} mulligan${now.mulligans === 1 ? '' : 's'}` : 'No mulligans',
            now.deck_name && isBrawl ? now.deck_name : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {clock ? <span className="live-scoreboard-clock">{clock}</span> : null}
      </div>
    </div>
  );
}

function GamesList({ games }: { games: LiveGameRow[] }) {
  if (games.length === 0) {
    return <p className="empty-state">No finished games yet today — go queue up!</p>;
  }
  return (
    <ol className="live-games">
      {games.map((game) => (
        <li key={game.id}>
          <a className="live-game-row" href={gameRouteHash(game.id, '#/live')}>
            <Badge tone={outcomeTone(game.outcome)}>{outcomeLabel(game.outcome)}</Badge>
            <span className="live-game-main">
              <span className="live-game-deck">{game.deck_name ?? '(unknown deck)'}</span>
              <span className="live-game-meta">
                {[
                  game.opponent_name ? `vs ${game.opponent_name}` : null,
                  game.total_turns ? `${game.total_turns} turns` : null,
                  game.duration_seconds ? formatDuration(game.duration_seconds) : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </span>
            <span className="live-game-time">
              {game.started_at
                ? new Date(game.started_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
                : ''}
            </span>
          </a>
        </li>
      ))}
    </ol>
  );
}

export function LiveLogPage() {
  const [payload, setPayload] = useState<LivePayload | null>(null);
  // The last in-game snapshot: kept on screen between games so players can
  // study the final board state while they queue.
  const [lastGameNow, setLastGameNow] = useState<LiveNow | null>(null);
  const [events, setEvents] = useState<LiveEventRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [following, setFollowing] = useState(true);
  const [clockMs, setClockMs] = useState(() => Date.now());
  const seqRef = useRef(0);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const gameKeyRef = useRef<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const next = await fetchLiveStatus(seqRef.current);
      seqRef.current = next.seq;
      setPayload(next);
      setError(null);
      // A new game clears the previous one — the finished game lives in the
      // rail's game list; the feed is the current game only.
      const gameKey = next.now?.game_id ?? null;
      const isNewGame = gameKey !== null && gameKey !== gameKeyRef.current;
      if (gameKey !== null) {
        gameKeyRef.current = gameKey;
      }
      if (next.now?.in_game) {
        setLastGameNow(next.now);
      } else if (next.now) {
        // Game over: the frozen scoreboard keeps the last in-game snapshot,
        // but the endgame log lines land after that snapshot — fold in the
        // final life totals and the persisted deck colors as they arrive.
        const after = next.now;
        const tail = [...next.events]
          .reverse()
          .find((row) => row.player_life !== null || row.opponent_life !== null);
        setLastGameNow((previous) => {
          if (!previous || (after.game_id !== null && after.game_id !== previous.game_id)) {
            return previous;
          }
          const merged = {
            ...previous,
            player_colors: previous.player_colors || after.player_colors,
            opponent_colors: previous.opponent_colors || after.opponent_colors,
            player_life: tail?.player_life ?? previous.player_life,
            opponent_life: tail?.opponent_life ?? previous.opponent_life,
          };
          return merged.player_colors === previous.player_colors &&
            merged.opponent_colors === previous.opponent_colors &&
            merged.player_life === previous.player_life &&
            merged.opponent_life === previous.opponent_life
            ? previous
            : merged;
        });
      }
      if (isNewGame || next.events.length > 0) {
        setEvents((current) => {
          const base = isNewGame
            ? next.events
            : current.length === 0
              ? next.events
              : [...current, ...next.events];
          return base.length > MAX_FEED_ROWS ? base.slice(-MAX_FEED_ROWS) : base;
        });
      }
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'Live feed unavailable');
    }
  }, []);

  useEffect(() => {
    let timer: number | null = null;
    let cancelled = false;

    async function tick() {
      if (!cancelled && !document.hidden) {
        await poll();
      }
      if (!cancelled) {
        timer = window.setTimeout(() => void tick(), POLL_MS);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [poll]);

  // A ticking clock for the game timer without waiting on polls.
  useEffect(() => {
    const id = window.setInterval(() => setClockMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // Auto-follow the feed unless the user scrolled up.
  useEffect(() => {
    const feed = feedRef.current;
    if (feed && following) {
      feed.scrollTop = feed.scrollHeight;
    }
  }, [events, following]);

  const onFeedScroll = useCallback(() => {
    const feed = feedRef.current;
    if (!feed) {
      return;
    }
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
    setFollowing(atBottom);
  }, []);

  const state = payload?.tracker.state ?? 'offline';
  const now = payload?.now ?? null;
  const session = payload?.session ?? null;
  const lastGame = payload?.games[0] ?? null;

  return (
    <div className="live-layout">
      <div className="live-main">
        <section className="dashboard-section" id="live-scoreboard">
          {state === 'live' && now?.in_game ? (
            <Scoreboard clockMs={clockMs} now={now} waiting={false} />
          ) : state === 'offline' ? (
            <div className="live-waiting">
              <p className="live-waiting-title">Tracker is not running</p>
              <p className="live-waiting-detail">
                Start the MTGA Tracker app and this page goes live automatically — no refresh
                needed.
              </p>
            </div>
          ) : lastGameNow ? (
            // Between games: the previous game's final scoreboard stays up,
            // flagged as waiting, so a break doesn't blank the page.
            <Scoreboard clockMs={clockMs} now={lastGameNow} waiting />
          ) : (
            <div className="live-waiting">
              <p className="live-waiting-title">
                <span aria-hidden="true" className="live-pulse-dot" /> Waiting for a match…
              </p>
              <p className="live-waiting-detail">
                {lastGame
                  ? `Last game: ${outcomeLabel(lastGame.outcome)} with ${lastGame.deck_name ?? 'your deck'}${lastGame.opponent_name ? ` vs ${lastGame.opponent_name}` : ''}.`
                  : 'Tracking is on. Queue into a game and the scoreboard lights up here.'}
              </p>
            </div>
          )}
          {error ? (
            <p className="state-panel error-state live-error" role="alert">
              {error}
            </p>
          ) : null}
        </section>

        <section className="dashboard-section live-feed-section" id="live-feed">
          <div className="section-heading">
            <h3>Live Feed</h3>
            {state !== 'offline' && !now?.in_game && events.length > 0 ? (
              <span className="live-chip live-chip-turn">
                <span aria-hidden="true" className="live-pulse-dot" /> Waiting for next match…
              </span>
            ) : null}
          </div>
          {events.length === 0 ? (
            <p className="empty-state live-feed-empty">
              {state === 'offline' ? (
                'Start the tracker and game events stream here live.'
              ) : (
                <>
                  <span aria-hidden="true" className="live-pulse-dot" /> Waiting for a match…
                </>
              )}
            </p>
          ) : (
            <div className="live-feed-wrap">
              {/* The exact same Timeline the /game page renders, live. */}
              <div className="live-feed" ref={feedRef} onScroll={onFeedScroll}>
                <TimelineList cardReturnHash="#/live" rows={events} showFilters={false} />
              </div>
              {!following ? (
                <button
                  className="live-jump"
                  type="button"
                  onClick={() => {
                    setFollowing(true);
                    const feed = feedRef.current;
                    if (feed) {
                      feed.scrollTop = feed.scrollHeight;
                    }
                  }}
                >
                  ↓ Jump to latest
                </button>
              ) : null}
            </div>
          )}
        </section>
      </div>

      <div className="live-rail" id="live-session">
        <section className="dashboard-section">
          <div className="section-heading">
            <h3>Session</h3>
          </div>
          {session ? (
            <div className="live-stats">
              <div className="live-stat">
                <span className="live-stat-value">{session.games_played}</span>
                <span className="live-stat-label">Games</span>
              </div>
              <div className="live-stat">
                <span className="live-stat-value">
                  {session.wins}–{session.losses}
                </span>
                <span className="live-stat-label">
                  Record{session.win_rate !== null ? ` · ${session.win_rate}%` : ''}
                </span>
              </div>
              <div className="live-stat">
                <span className="live-stat-value">
                  {session.runtime_seconds ? formatDuration(session.runtime_seconds) : '—'}
                </span>
                <span className="live-stat-label">Runtime</span>
              </div>
              <div className="live-stat">
                <span
                  className={
                    state === 'offline'
                      ? 'live-stat-value live-stat-bad'
                      : 'live-stat-value live-stat-good'
                  }
                >
                  {state === 'live' ? 'Live' : state === 'idle' ? 'Ready' : 'Off'}
                </span>
                <span className="live-stat-label">Tracker</span>
              </div>
            </div>
          ) : (
            <p className="empty-state">No session recorded yet.</p>
          )}
        </section>

        <section className="dashboard-section">
          <div className="section-heading">
            <h3>Today's Games</h3>
          </div>
          <GamesList games={payload?.games ?? []} />
        </section>
      </div>
    </div>
  );
}
