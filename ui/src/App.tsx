import { useEffect, useMemo, useState } from 'react';
import {
  fetchDashboardSnapshot,
  type DashboardSnapshot,
  type DeckPlayDrawRow,
  type DeckRow,
  type DrawQualityRow,
  type DrawnCardRow,
  type MatchRow,
  type MomentumRow,
  type PlayDrawRow,
  type RecentGameRow,
  type SessionRow,
  type SnapshotFilters,
} from './api';
import { Badge } from './components/Badge';
import { CardDetailPage } from './components/CardDetailPage';
import { CardLink } from './components/CardLink';
import { DeckDetailPage } from './components/DeckDetailPage';
import { DeckLink } from './components/DeckLink';
import { DeckVisual } from './components/DeckVisual';
import { FilterBar } from './components/FilterBar';
import { FormatsTable } from './components/FormatsTable';
import { GameDetailPage } from './components/GameDetailPage';
import { MetricCard } from './components/MetricCard';
import { OpponentDetailPage } from './components/OpponentDetailPage';
import { RankProgressChart } from './components/RankProgressChart';
import { SortableTable, type Column } from './components/SortableTable';
import { TrendChart } from './components/TrendChart';
import { TypeChip } from './components/TypeChip';
import { WinRateBar } from './components/WinRateBar';
import { AppShell } from './components/AppShell';
import { formatPercent, metricCards } from './dashboardData';
import { formatDateTime, formatDuration, formatNumber, formatTurnDuration, outcomeLabel, outcomeTone } from './format';
import { cardNavItems, deckNavItems, gameNavItems, opponentNavItems } from './nav';
import { RouteFiltersContext } from './routeFilters';
import {
  dashboardRouteHash,
  gameRouteHash,
  parseCardRoute,
  parseDashboardRouteFilters,
  parseDeckRoute,
  parseGameRoute,
  parseOpponentRoute,
} from './routes';
import './styles.css';
import { getInitialTheme, persistTheme, type ThemeName } from './theme';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; snapshot: DashboardSnapshot; lastUpdated: string; refreshError?: string }
  | { status: 'error'; message: string };

type RecentGameWithDrawQuality = RecentGameRow &
  Pick<DrawQualityRow, 'cards_seen' | 'lands_seen' | 'land_seen_pct'>;

const SNAPSHOT_REFRESH_MS = 20_000;

function readInitialTheme(): ThemeName {
  try {
    return getInitialTheme();
  } catch {
    return 'dark';
  }
}

function applyTheme(theme: ThemeName): void {
  try {
    persistTheme(theme);
  } catch {
    document.documentElement.dataset.theme = theme;
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="dashboard-section" id={id}>
      <div className="section-heading">
        <div>
          <h3>{title}</h3>
          {description ? <p className="section-description">{description}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function SetupCard() {
  return (
    <section className="setup-card" id="overview">
      <span className="eyebrow">Getting started</span>
      <h3>No tracked games yet</h3>
      <p>Run the tracker while playing Arena. Finished games will appear here automatically.</p>
      <div className="setup-commands">
        <code>venv/bin/python -m mtga_tracker.main</code>
        <code>venv/bin/python -m mtga_tracker.dashboard</code>
      </div>
    </section>
  );
}

const deckColumns: Column<DeckRow>[] = [
  {
    key: 'deck_visual',
    header: 'Deck',
    render: (row) => (
      <div className="deck-cell">
        <DeckVisual deckName={row.deck_name} visual={row.deck_visual} />
        <div>
          <DeckLink deckName={row.deck_name}>
            <strong>{row.deck_name}</strong>
          </DeckLink>
          <span>{row.deck_visual.source === 'local_metadata' && row.deck_visual.card_name ? row.deck_visual.card_name : 'No card data yet'}</span>
        </div>
      </div>
    ),
    sortValue: (row) => row.deck_name,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

const playDrawColumns: Column<PlayDrawRow>[] = [
  {
    key: 'play_draw',
    header: 'Play / Draw',
    render: (row) => row.play_draw ?? 'Unknown',
    sortValue: (row) => row.play_draw,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

const deckPlayDrawColumns: Column<DeckPlayDrawRow>[] = [
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
  },
  {
    key: 'play_draw',
    header: 'Play / Draw',
    render: (row) => row.play_draw ?? 'Unknown',
    sortValue: (row) => row.play_draw,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

const drawnCardColumns: Column<DrawnCardRow>[] = [
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
  { key: 'times_drawn', header: 'Times Drawn', numeric: true },
  { key: 'games_seen', header: 'Games Seen', numeric: true },
  {
    key: 'pct_of_games',
    header: 'Game Share',
    render: (row) => formatPercent(row.pct_of_games),
    sortValue: (row) => row.pct_of_games,
    numeric: true,
  },
];

const momentumColumns: Column<MomentumRow>[] = [
  { key: 'split', header: 'Split' },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
  {
    key: 'avg_mulligans',
    header: 'Avg Mulligans',
    render: (row) => formatNumber(row.avg_mulligans),
    sortValue: (row) => row.avg_mulligans,
    numeric: true,
  },
  {
    key: 'on_play_pct',
    header: 'On Play',
    render: (row) => formatPercent(row.on_play_pct),
    sortValue: (row) => row.on_play_pct,
    numeric: true,
  },
];

const recentColumns: Column<RecentGameWithDrawQuality>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => <a href={gameRouteHash(row.game_id, '#recent-games')}>{formatDateTime(row.started_at)}</a>,
    sortValue: (row) => row.started_at,
  },
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
  },
  { key: 'format_label', header: 'Format' },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
  },
  {
    key: 'cards_seen',
    header: 'Cards Seen',
    render: (row) => formatNumber(row.cards_seen),
    sortValue: (row) => row.cards_seen,
    numeric: true,
  },
  {
    key: 'lands_seen',
    header: 'Lands Seen',
    render: (row) => formatNumber(row.lands_seen),
    sortValue: (row) => row.lands_seen,
    numeric: true,
  },
  {
    key: 'land_seen_pct',
    header: 'Land Seen',
    render: (row) => formatPercent(row.land_seen_pct),
    sortValue: (row) => row.land_seen_pct,
    numeric: true,
  },
  {
    key: 'mulligans',
    header: 'Mulligans',
    render: (row) => formatNumber(row.mulligans),
    sortValue: (row) => row.mulligans,
    numeric: true,
  },
  {
    key: 'duration_seconds',
    header: 'Game Time',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
    numeric: true,
  },
  {
    key: 'player_avg_turn_seconds',
    header: 'Your Avg Turn',
    render: (row) => formatTurnDuration(row.player_avg_turn_seconds),
    sortValue: (row) => row.player_avg_turn_seconds,
    numeric: true,
  },
  {
    key: 'opponent_avg_turn_seconds',
    header: 'Opp. Avg Turn',
    render: (row) => formatTurnDuration(row.opponent_avg_turn_seconds),
    sortValue: (row) => row.opponent_avg_turn_seconds,
    numeric: true,
  },
];

const matchColumns: Column<MatchRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => (row.started_at ? formatDateTime(row.started_at) : '—'),
    sortValue: (row) => row.started_at,
  },
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
  },
  { key: 'format_label', header: 'Format' },
  {
    key: 'best_of',
    header: 'Best Of',
    render: (row) => formatNumber(row.best_of),
    sortValue: (row) => row.best_of,
    numeric: true,
  },
  { key: 'record', header: 'Record' },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
  },
];

const sessionColumns: Column<SessionRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => formatDateTime(row.started_at),
    sortValue: (row) => row.started_at,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  { key: 'draws', header: 'Draws', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
  {
    key: 'duration_seconds',
    header: 'Duration',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
    numeric: true,
  },
];

export default function App() {
  const [theme, setTheme] = useState<ThemeName>(() => readInitialTheme());
  const [filters, setFilters] = useState<SnapshotFilters>(() => parseDashboardRouteFilters(window.location.hash) ?? {});
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [routeHash, setRouteHash] = useState<string>(() => window.location.hash);
  const deckRoute = useMemo(() => parseDeckRoute(routeHash), [routeHash]);
  const gameRoute = useMemo(() => parseGameRoute(routeHash), [routeHash]);
  const cardRoute = useMemo(() => parseCardRoute(routeHash), [routeHash]);
  const opponentRoute = useMemo(() => parseOpponentRoute(routeHash), [routeHash]);
  const deckName = deckRoute?.name ?? null;
  const gameId = gameRoute?.id ?? null;
  const deckRouteFilters = deckRoute?.filters ?? {};
  const activeRouteFilters = deckRoute ? deckRouteFilters : filters;
  const deckBackHref = deckRoute ? dashboardRouteHash(deckRoute.filters) : '#overview';
  const deckPageNavItems = useMemo(
    () =>
      deckRoute
        ? deckNavItems.map((item) =>
            item.id === 'back-to-dashboard' ? { ...item, route: dashboardRouteHash(deckRoute.filters) } : item,
          )
        : deckNavItems,
    [deckRoute],
  );
  const gamePageNavItems = useMemo(
    () =>
      gameRoute
        ? gameNavItems.map((item) =>
            item.id === 'back-to-dashboard' ? { ...item, route: gameRoute.returnHash } : item,
          )
        : gameNavItems,
    [gameRoute],
  );

  useEffect(() => {
    function onHashChange() {
      const nextHash = window.location.hash;
      setRouteHash(nextHash);
      const dashboardFilters = parseDashboardRouteFilters(nextHash);
      if (dashboardFilters) {
        setFilters(dashboardFilters);
      }
    }
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (
      deckRoute
      || gameRoute
      || cardRoute
      || opponentRoute
      || loadState.status !== 'loaded'
      || !routeHash.startsWith('#')
    ) {
      return;
    }
    const sectionId = routeHash.slice(1).split('?')[0];
    if (sectionId === 'overview') {
      window.scrollTo({ top: 0, left: 0 });
    } else if (sectionId && !sectionId.startsWith('/')) {
      document.getElementById(sectionId)?.scrollIntoView?.({ block: 'start' });
    }
  }, [cardRoute, deckRoute, gameRoute, loadState.status, opponentRoute, routeHash]);

  useEffect(() => {
    document.title = deckRoute
      ? `${deckRoute.name} – MTGA Tracker`
      : gameRoute
        ? 'Game – MTGA Tracker'
        : cardRoute
          ? `${cardRoute} – MTGA Tracker`
          : opponentRoute
            ? `${opponentRoute} – MTGA Tracker`
            : 'MTGA Tracker Dashboard';
  }, [deckRoute, gameRoute, cardRoute, opponentRoute]);

  useEffect(() => {
    if (deckName || gameId || cardRoute || opponentRoute) {
      return;
    }
    let ignore = false;
    let requestSequence = 0;
    let activeController: AbortController | null = null;

    async function loadSnapshot() {
      const sequence = requestSequence + 1;
      requestSequence = sequence;
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const snapshot = await fetchDashboardSnapshot(filters, controller.signal);
        if (!ignore && sequence === requestSequence) {
          setLoadState({ status: 'loaded', snapshot, lastUpdated: new Date().toISOString() });
        }
      } catch (error: unknown) {
        if (!ignore && sequence === requestSequence && !isAbortError(error)) {
          const message = error instanceof Error ? error.message : 'Dashboard API failed';
          setLoadState((current) =>
            current.status === 'loaded' ? { ...current, refreshError: message } : { status: 'error', message },
          );
        }
      }
    }

    void loadSnapshot();
    const refreshId = window.setInterval(() => {
      void loadSnapshot();
    }, SNAPSHOT_REFRESH_MS);

    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [filters, deckName, gameId, cardRoute, opponentRoute]);

  function toggleTheme() {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }

  return (
    <RouteFiltersContext.Provider value={activeRouteFilters}>
      <AppShell
        theme={theme}
        onToggleTheme={toggleTheme}
        navItems={
          cardRoute
            ? cardNavItems
            : gameId
              ? gamePageNavItems
              : deckName
                ? deckPageNavItems
                : opponentRoute
                  ? opponentNavItems
                  : undefined
        }
        eyebrow={
          cardRoute
            ? 'Card breakdown'
            : gameRoute
              ? 'Game breakdown'
              : deckName
                ? 'Deck breakdown'
                : opponentRoute
                  ? 'Opponent history'
                  : 'SQLite analytics'
        }
        heading={cardRoute ?? (gameRoute ? 'Game detail' : deckName ?? opponentRoute ?? 'Performance overview')}
      >
        {cardRoute ? (
          <CardDetailPage key={cardRoute} cardName={cardRoute} />
        ) : gameRoute ? (
          <GameDetailPage key={gameRoute.id} backHref={gameRoute.returnHash} gameId={gameRoute.id} />
        ) : deckName ? (
          <DeckDetailPage
            key={`${deckName}-${deckBackHref}`}
            backHref={deckBackHref}
            deckName={deckName}
            filters={deckRouteFilters}
          />
        ) : opponentRoute ? (
          <OpponentDetailPage key={opponentRoute} opponentName={opponentRoute} />
        ) : (
          <>
            {loadState.status === 'loading' ? <p className="state-panel">Loading dashboard snapshot...</p> : null}
            {loadState.status === 'error' ? (
              <div className="state-panel error-state" role="alert">
                {loadState.message}
              </div>
            ) : null}
            {loadState.status === 'loaded' ? (
              <Dashboard
                filters={filters}
                lastUpdated={loadState.lastUpdated}
                onFiltersChange={setFilters}
                refreshError={loadState.refreshError}
                snapshot={loadState.snapshot}
              />
            ) : null}
          </>
        )}
      </AppShell>
    </RouteFiltersContext.Provider>
  );
}

function Dashboard({
  filters,
  lastUpdated,
  onFiltersChange,
  refreshError,
  snapshot,
}: {
  filters: SnapshotFilters;
  lastUpdated: string;
  onFiltersChange: (filters: SnapshotFilters) => void;
  refreshError?: string;
  snapshot: DashboardSnapshot;
}) {
  const [deckSearch, setDeckSearch] = useState('');
  const [drawnCardSearch, setDrawnCardSearch] = useState('');
  const filteredDecks = useMemo(() => {
    const query = deckSearch.trim().toLocaleLowerCase();
    if (!query) {
      return snapshot.decks;
    }
    return snapshot.decks.filter((row) => row.deck_name.toLocaleLowerCase().includes(query));
  }, [deckSearch, snapshot.decks]);
  const filteredDrawnCards = useMemo(() => {
    const query = drawnCardSearch.trim().toLocaleLowerCase();
    if (!query) {
      return snapshot.drawn_cards;
    }
    return snapshot.drawn_cards.filter((row) => row.display_name.toLocaleLowerCase().includes(query));
  }, [drawnCardSearch, snapshot.drawn_cards]);
  const recentGames = useMemo(() => {
    const qualityByGame = new Map(snapshot.draw_quality.map((row) => [row.game_id, row]));
    return snapshot.recent.map((row) => {
      const quality = qualityByGame.get(row.game_id);
      return {
        ...row,
        cards_seen: quality?.cards_seen ?? null,
        lands_seen: quality?.lands_seen ?? null,
        land_seen_pct: quality?.land_seen_pct ?? null,
      };
    });
  }, [snapshot.draw_quality, snapshot.recent]);

  return (
    <>
      <div className={refreshError ? 'refresh-status refresh-status-error' : 'refresh-status'} role="status">
        {refreshError
          ? `Latest refresh failed: ${refreshError}. Showing last dashboard snapshot.`
          : `Updated ${formatDateTime(lastUpdated)}`}
      </div>

      {snapshot.summary.games === 0 ? (
        <SetupCard />
      ) : (
        <>
      <FilterBar filters={filters} onChange={onFiltersChange} options={snapshot.filter_options} />

      <section className="overview-section" id="overview" aria-label="Overview">
        <section className="metric-grid" aria-label="Overview metrics">
          {metricCards(snapshot, filters).map((metric) => (
            <MetricCard key={metric.label} href={metric.href} label={metric.label} value={metric.value} />
          ))}
        </section>
        <div className="overview-analytics">
          <section className="overview-panel" aria-labelledby="overview-play-draw-title">
            <div className="section-heading">
              <div>
                <h3 id="overview-play-draw-title">Play / Draw</h3>
              </div>
            </div>
            <SortableTable
              caption="Play and draw performance"
              columns={playDrawColumns}
              getRowKey={(row) => row.play_draw ?? 'unknown'}
              rows={snapshot.play_draw}
            />
          </section>
          <section className="overview-panel" aria-labelledby="overview-momentum-title">
            <div className="section-heading">
              <div>
                <h3 id="overview-momentum-title">Momentum</h3>
                <p className="section-description">
                  Next-game results after wins and losses, including mulligans and on-play percentage.
                </p>
              </div>
            </div>
            <SortableTable
              caption="Momentum splits"
              columns={momentumColumns}
              getRowKey={(row) => row.split}
              rows={snapshot.momentum}
            />
          </section>
        </div>
      </section>

      <Section
        id="trend"
        title="Win Rate Trend"
        description="Rolling win rate across your most recent finished games."
      >
        <div className="trend-wrap">
          <TrendChart rows={snapshot.trend} />
        </div>
      </Section>

      <Section
        id="rank-progress"
        title="Ranked Progress"
        description="Constructed ladder progress for the current season. Ranked Standard Best-of-1 and Best-of-3 share this rank."
      >
        <div className="trend-wrap">
          <RankProgressChart rows={snapshot.rank_progress ?? []} />
        </div>
      </Section>

      <Section
        id="recent-games"
        title="Recent Games"
        description="Recent results with draw distribution, total game time, and average turn pace."
      >
        <SortableTable
          caption="Recent games"
          columns={recentColumns}
          getRowKey={(row) => row.game_id}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          rows={recentGames}
        />
      </Section>

      <Section id="decks" title="Decks">
        <div className="table-filter">
          <label>
            <span>Search decks</span>
            <input
              type="search"
              value={deckSearch}
              onChange={(event) => setDeckSearch(event.target.value)}
              placeholder="Deck name"
            />
          </label>
        </div>
        <SortableTable
          caption="Deck performance"
          columns={deckColumns}
          getRowKey={(row) => row.deck_name}
          initialSort={{ key: 'games', direction: 'desc' }}
          rows={filteredDecks}
        />
      </Section>

      <Section id="formats" title="Formats">
        <FormatsTable caption="Format performance" midweekRows={snapshot.midweek_formats} rows={snapshot.formats} />
      </Section>

      <Section id="deck-play-draw" title="Deck Play / Draw">
        <SortableTable
          caption="Deck play and draw performance"
          columns={deckPlayDrawColumns}
          getRowKey={(row) => `${row.deck_name}-${row.play_draw ?? 'unknown'}`}
          rows={snapshot.deck_play_draw}
        />
      </Section>

      <Section id="visible-drawn-cards" title="Visible Drawn Cards">
        <div className="table-filter">
          <label>
            <span>Search cards</span>
            <input
              type="search"
              value={drawnCardSearch}
              onChange={(event) => setDrawnCardSearch(event.target.value)}
              placeholder="Card name"
            />
          </label>
        </div>
        <SortableTable
          caption="Visible drawn card frequency"
          columns={drawnCardColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category ?? 'unknown'}`}
          initialSort={{ key: 'times_drawn', direction: 'desc' }}
          rows={filteredDrawnCards}
        />
      </Section>

      <Section
        id="matches"
        title="Best-of-3 Matches"
        description="Multi-game matches with the game record inside each match. Single-game (Bo1) play lives in Recent Games."
      >
        <SortableTable
          caption="Best-of-3 matches"
          columns={matchColumns}
          getRowKey={(row) => row.match_id}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          rows={snapshot.matches}
        />
      </Section>

      <Section id="sessions" title="Sessions" description="Tracker runtime sessions with game volume and record.">
        <SortableTable
          caption="Tracker sessions"
          columns={sessionColumns}
          getRowKey={(row) => row.session_id}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          rows={snapshot.sessions}
        />
      </Section>
        </>
      )}
    </>
  );
}
