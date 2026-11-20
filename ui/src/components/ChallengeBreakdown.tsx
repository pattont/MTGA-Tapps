import type { ReactNode } from 'react';
import { Hourglass, Skull, Target, ThumbsDown, Trophy, Zap } from 'lucide-react';
import {
  MIN_DECK_GAMES,
  MIN_RIVAL_MATCHES,
  type ChallengeStats,
  type DeckRecord,
  type Tally,
} from '../challengeStats';
import { formatDuration, outcomeLabel } from '../format';
import { CHALLENGES_ROUTE_HASH, gameRouteHash } from '../routes';
import { DeckLink } from './DeckLink';
import { MetricCard } from './MetricCard';
import { OpponentLink } from './OpponentLink';

function record(row: { wins: number; losses: number }): string {
  return `${row.wins}–${row.losses}`;
}

function percent(rate: number | null): string {
  return rate == null ? '—' : `${rate}%`;
}

function plural(count: number, word: string, many = `${word}s`): string {
  return `${count} ${count === 1 ? word : many}`;
}

function sideCard(label: string, side: Tally) {
  return (
    <MetricCard
      label={label}
      value={percent(side.winRate)}
      detail={side.games ? `${record(side)} in ${plural(side.games, 'game')}` : 'No games yet'}
    />
  );
}

/** The record strip at the top of the Challenges page. */
export function ChallengeRecord({ stats }: { stats: ChallengeStats }) {
  const { streak } = stats;
  return (
    <div className="metric-grid challenges-record">
      <MetricCard
        label="Match record"
        value={record(stats.matches)}
        detail={`${percent(stats.matches.winRate)} of ${plural(stats.matches.games, 'match', 'matches')}`}
      />
      <MetricCard
        label="Game record"
        value={record(stats.games)}
        detail={`${percent(stats.games.winRate)} of ${plural(stats.games.games, 'game')}`}
      />
      {sideCard('On the play', stats.onPlay)}
      {sideCard('On the draw', stats.onDraw)}
      <MetricCard
        label="Current streak"
        value={streak ? streak.result === 'win' ? plural(streak.length, 'win') : plural(streak.length, 'loss', 'losses') : '—'}
        tone={streak ? streak.result : 'default'}
        detail={streak ? (streak.result === 'win' ? 'Keep it going' : 'Time for a rematch') : undefined}
      />
      <MetricCard
        label="Best win streak"
        value={stats.longestWinStreak ? plural(stats.longestWinStreak, 'game') : '—'}
      />
    </div>
  );
}

function Highlight({
  icon,
  label,
  tone = 'neutral',
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  tone?: 'neutral' | 'win' | 'loss';
  value: ReactNode;
  detail: string;
}) {
  return (
    <article className={`challenge-highlight challenge-highlight-${tone}`}>
      <span className="challenge-highlight-label">
        <span aria-hidden="true">{icon}</span>
        {label}
      </span>
      <strong className="challenge-highlight-value">{value}</strong>
      <span className="challenge-highlight-detail">{detail}</span>
    </article>
  );
}

function deckDetail(deck: DeckRecord): string {
  return `${record(deck)} · ${percent(deck.winRate)} in ${plural(deck.games, 'game')}`;
}

/** Bragging rights: the rivals, decks and games worth bringing up. */
export function ChallengeHighlights({ stats }: { stats: ChallengeStats }) {
  const { nemesis, favoriteVictim, bestDeck, worstDeck, fastestWin, longestGame } = stats;
  const none = <span className="challenge-highlight-none">Nobody yet</span>;
  const notYet = <span className="challenge-highlight-none">Not yet</span>;
  return (
    <div className="challenge-highlights">
      <Highlight
        icon={<Target />}
        label="Favorite victim"
        tone="win"
        value={favoriteVictim ? <OpponentLink opponentName={favoriteVictim.friend} /> : none}
        detail={
          favoriteVictim
            ? `You're ${record(favoriteVictim)} against them (${percent(favoriteVictim.win_rate)})`
            : `You don't have a winning record against anyone yet (${MIN_RIVAL_MATCHES}+ matches)`
        }
      />
      <Highlight
        icon={<Skull />}
        label="Nemesis"
        tone="loss"
        value={nemesis ? <OpponentLink opponentName={nemesis.friend} /> : none}
        detail={
          nemesis
            ? `Beats you ${record({ wins: nemesis.losses, losses: nemesis.wins })} (${percent(nemesis.win_rate == null ? null : 100 - nemesis.win_rate)})`
            : `No friend has a winning record against you (${MIN_RIVAL_MATCHES}+ matches)`
        }
      />
      <Highlight
        icon={<Zap />}
        label="Fastest win"
        value={
          fastestWin ? (
            <a className="deck-link" href={gameRouteHash(fastestWin.game.game_id, CHALLENGES_ROUTE_HASH)}>
              Turn {fastestWin.game.total_turns}
            </a>
          ) : (
            notYet
          )
        }
        detail={fastestWin ? `vs ${fastestWin.friend} with ${fastestWin.game.deck_name}` : 'Win a game to set the mark'}
      />
      <Highlight
        icon={<Trophy />}
        label="Best deck"
        tone="win"
        value={bestDeck ? <DeckLink deckName={bestDeck.deck} /> : notYet}
        detail={bestDeck ? deckDetail(bestDeck) : `A deck needs ${MIN_DECK_GAMES} decided games and a win`}
      />
      <Highlight
        icon={<ThumbsDown />}
        label="Worst deck"
        tone="loss"
        value={worstDeck ? <DeckLink deckName={worstDeck.deck} /> : notYet}
        detail={worstDeck ? deckDetail(worstDeck) : `Needs another deck with ${MIN_DECK_GAMES} decided games and a loss`}
      />
      <Highlight
        icon={<Hourglass />}
        label="Longest game"
        value={
          longestGame ? (
            <a className="deck-link" href={gameRouteHash(longestGame.game.game_id, CHALLENGES_ROUTE_HASH)}>
              {formatDuration(longestGame.game.duration_seconds)}
            </a>
          ) : (
            notYet
          )
        }
        detail={
          longestGame
            ? [
                `vs ${longestGame.friend}`,
                longestGame.game.total_turns == null ? null : plural(longestGame.game.total_turns, 'turn'),
                outcomeLabel(longestGame.game.outcome),
              ]
                .filter(Boolean)
                .join(' · ')
            : 'No game length recorded yet'
        }
      />
    </div>
  );
}
