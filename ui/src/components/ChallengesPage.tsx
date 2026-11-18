import { Swords } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  fetchChallenges,
  fetchTrackingSettings,
  type ChallengeFriendRow,
  type ChallengeGameRow,
  type ChallengesResponse,
  type TrackingSettings,
} from '../api';
import { formatDateTime, formatDuration, outcomeLabel, outcomeTone } from '../format';
import { challengeStats, friendName, streakLabel, type DeckRecord, type FriendExtras } from '../challengeStats';
import { CHALLENGES_ROUTE_HASH, gameRouteHash } from '../routes';
import { Badge } from './Badge';
import { ChallengeHighlights, ChallengeRecord } from './ChallengeBreakdown';
import { ColorPips } from './ColorPips';
import { DeckLink } from './DeckLink';
import { OpponentLink } from './OpponentLink';
import { ReplayLink } from './ReplayLink';
import { Section } from './Section';
import { SortableTable, type Column } from './SortableTable';

const REFRESH_MS = 60_000;
const GAMES_PAGE_SIZE = 20;
const FRIENDS_PAGE_SIZE = 10;

/** Games whose friend or deck name contains the query, ignoring case. */
function searchGames(games: ChallengeGameRow[], query: string): ChallengeGameRow[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return games;
  return games.filter(
    (game) =>
      friendName(game.opponent_name).toLowerCase().includes(needle) ||
      game.deck_name.toLowerCase().includes(needle),
  );
}

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; response: ChallengesResponse }
  | { status: 'error'; message: string };

/** A Friends table row: the backend's record plus what the games add. */
type FriendTableRow = ChallengeFriendRow & FriendExtras;

const friendColumns: Column<FriendTableRow>[] = [
  {
    key: 'friend',
    header: 'Friend',
    render: (row) => <OpponentLink opponentName={row.friend} />,
    sortValue: (row) => row.friend.toLowerCase(),
  },
  {
    key: 'colors',
    header: 'Plays',
    render: (row) => <ColorPips colors={row.colors} />,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'matches', header: 'Matches', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => (row.win_rate == null ? '—' : `${row.win_rate}%`),
    sortValue: (row) => row.win_rate ?? -1,
    numeric: true,
  },
  {
    key: 'streak',
    header: 'Streak',
    render: (row) => (row.streak ? <Badge tone={row.streak.result}>{streakLabel(row.streak)}</Badge> : '—'),
    // Win runs above loss runs, the longest at each end.
    sortValue: (row) => (row.streak ? (row.streak.result === 'win' ? row.streak.length : -row.streak.length) : 0),
    center: true,
  },
  {
    key: 'last_played',
    header: 'Last Played',
    render: (row) => (row.last_played ? formatDateTime(row.last_played) : '—'),
    sortValue: (row) => row.last_played ?? '',
    numeric: true,
  },
];

const deckColumns: Column<DeckRecord>[] = [
  {
    key: 'deck',
    header: 'Deck',
    render: (row) => (
      <span className="challenges-deck-cell">
        <ColorPips colors={row.colors} />
        <DeckLink deckName={row.deck} />
      </span>
    ),
    sortValue: (row) => row.deck.toLowerCase(),
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'winRate',
    header: 'Win Rate',
    render: (row) => (row.winRate == null ? '—' : `${row.winRate}%`),
    sortValue: (row) => row.winRate ?? -1,
    numeric: true,
  },
  {
    key: 'lastPlayed',
    header: 'Last Played',
    render: (row) => (row.lastPlayed ? formatDateTime(row.lastPlayed) : '—'),
    sortValue: (row) => row.lastPlayed ?? '',
    numeric: true,
  },
];

// No Format column: every challenge game is labelled "Direct Challenge".
const gameColumns: Column<ChallengeGameRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => <a href={gameRouteHash(row.game_id, CHALLENGES_ROUTE_HASH)}>{formatDateTime(row.started_at)}</a>,
    sortValue: (row) => row.started_at,
  },
  {
    key: 'opponent_name',
    header: 'Friend',
    render: (row) => <OpponentLink opponentName={friendName(row.opponent_name)} />,
    sortValue: (row) => friendName(row.opponent_name).toLowerCase(),
  },
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
  },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
    center: true,
  },
  {
    key: 'opp_colors',
    header: 'Opp',
    render: (row) => <ColorPips colors={row.opp_colors} />,
    sortValue: (row) => row.opp_colors ?? '',
  },
  {
    key: 'went_first',
    header: 'Play/Draw',
    render: (row) =>
      row.went_first == null ? null : (
        <Badge tone={row.went_first ? 'play' : 'drawside'}>{row.went_first ? 'Play' : 'Draw'}</Badge>
      ),
    sortValue: (row) => row.went_first ?? -1,
    center: true,
  },
  { key: 'total_turns', header: 'Turns', numeric: true },
  {
    key: 'duration_seconds',
    header: 'Game Time',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
    numeric: true,
  },
  {
    key: 'replay',
    header: '',
    sortable: false,
    render: (row) => (
      <ReplayLink availability={row.replay} gameId={row.game_id} returnHash={CHALLENGES_ROUTE_HASH} variant="icon" />
    ),
  },
];

/** Says so when Settings → Saved game modes keeps challenge games out. */
function NotSavedNote() {
  // undefined while loading; null when it could not be read.
  const [settings, setSettings] = useState<TrackingSettings | null | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    fetchTrackingSettings(controller.signal)
      .then(setSettings)
      .catch((exc: unknown) => {
        if (!(exc instanceof Error && exc.name === 'AbortError')) setSettings(null);
      });
    return () => controller.abort();
  }, []);

  if (!settings || settings.direct_challenge) return null;
  return (
    <p className="challenges-off" role="status">
      Challenge games aren't being saved, so new ones won't show up here. Turn{' '}
      <strong>Direct Challenge</strong> back on in <a href="#/settings">Settings → Saved game modes</a>.
    </p>
  );
}

export function ChallengesPage() {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [retryToken, setRetryToken] = useState(0);
  const [gameQuery, setGameQuery] = useState('');

  useEffect(() => {
    window.scrollTo(0, 0);
    let ignore = false;
    let activeController: AbortController | null = null;

    async function load() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const response = await fetchChallenges(controller.signal);
        if (!ignore) setLoadState({ status: 'loaded', response });
      } catch (error: unknown) {
        if (ignore || (error instanceof Error && error.name === 'AbortError')) return;
        const message = error instanceof Error ? error.message : 'Challenges API failed';
        // A failed refresh keeps the games already shown.
        setLoadState((current) => (current.status === 'loaded' ? current : { status: 'error', message }));
      }
    }

    void load();
    const refreshId = window.setInterval(() => {
      if (!document.hidden) void load();
    }, REFRESH_MS);
    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [retryToken]);

  const response = loadState.status === 'loaded' ? loadState.response : null;
  const stats = useMemo(
    () => (response ? challengeStats(response.games, response.friends) : null),
    [response],
  );
  const friendRows = useMemo<FriendTableRow[]>(
    () =>
      (response?.friends ?? []).map((row) => ({
        ...row,
        ...(stats?.friendExtras.get(row.friend) ?? { colors: '', streak: null }),
      })),
    [response, stats],
  );
  const shownGames = useMemo(() => searchGames(response?.games ?? [], gameQuery), [response, gameQuery]);

  return (
    <Section
      collapsible={false}
      id="challenges-page"
      description="Games against friends from Arena's Direct Challenge: who you beat, who beats you, and every game to back it up."
    >
      <NotSavedNote />
      {loadState.status === 'loading' ? (
        <p className="state-panel challenges-state" role="status" aria-busy="true">
          Loading challenges...
        </p>
      ) : loadState.status === 'error' ? (
        <div className="state-panel error-state challenges-state" role="alert">
          <p>{loadState.message}</p>
          <button className="retry-button" type="button" onClick={() => setRetryToken((token) => token + 1)}>
            Retry
          </button>
        </div>
      ) : loadState.response.total === 0 ? (
        <div className="challenges-empty">
          <span className="challenges-empty-icon" aria-hidden="true">
            <Swords />
          </span>
          <p className="challenges-empty-title">No challenges yet. Go challenge your friends!</p>
          <ol className="challenges-steps" aria-label="How to challenge a friend in Arena">
            <li>Open your Friends list in Arena</li>
            <li>Pick a friend</li>
            <li>Choose Challenge</li>
          </ol>
          <p className="challenges-empty-note">
            Every game you play against them shows up here, with your record against each friend.
          </p>
        </div>
      ) : stats ? (
        <>
          <ChallengeRecord stats={stats} />
          <h3 className="challenges-heading">Bragging rights</h3>
          <ChallengeHighlights stats={stats} />
          <h3 className="challenges-heading">
            Friends <span className="challenges-heading-note">{loadState.response.friends.length}</span>
          </h3>
          <SortableTable
            caption="Record against each friend"
            columns={friendColumns}
            getRowKey={(row) => row.friend}
            initialSort={{ key: 'games', direction: 'desc' }}
            pageSize={FRIENDS_PAGE_SIZE}
            rows={friendRows}
          />
          <h3 className="challenges-heading">
            Your decks <span className="challenges-heading-note">{stats.decks.length}</span>
          </h3>
          <SortableTable
            caption="Your decks in challenges"
            columns={deckColumns}
            getRowKey={(row) => row.deck}
            initialSort={{ key: 'games', direction: 'desc' }}
            pageSize={10}
            rows={stats.decks}
          />
          <div className="challenges-heading-row">
            <h3 className="challenges-heading">
              Games{' '}
              <span className="challenges-heading-note">
                {shownGames.length === loadState.response.total
                  ? loadState.response.total
                  : `${shownGames.length} of ${loadState.response.total}`}
              </span>
            </h3>
            <input
              aria-label="Search games by friend or deck"
              className="challenges-search"
              placeholder="Search friend or deck"
              type="search"
              value={gameQuery}
              onChange={(event) => setGameQuery(event.target.value)}
            />
          </div>
          {shownGames.length ? (
            <SortableTable
              caption="Challenge games"
              columns={gameColumns}
              getRowKey={(row) => row.game_id}
              initialSort={{ key: 'started_at', direction: 'desc' }}
              pageSize={GAMES_PAGE_SIZE}
              paginationControls="full"
              paginationKey={gameQuery.trim().toLowerCase()}
              rows={shownGames}
            />
          ) : (
            <p className="empty-state">No games against a friend or with a deck matching “{gameQuery.trim()}”.</p>
          )}
        </>
      ) : null}
    </Section>
  );
}
