import { useEffect, useMemo, useRef, useState } from 'react';
import { pageTitle } from './branding';
import {
  fetchDashboardSnapshot,
  type CombatDeckRow,
  type CombatSplitRow,
  type DashboardSnapshot,
  type DeckRow,
  type FatigueRow,
  type MatchupRow,
  type OpenerLandRow,
  type OpponentThreatRow,
  type OutcomeReasonRow,
  type ScheduleRow,
  type DrawQualityRow,
  type MomentumRow,
  type PlayDrawRow,
  type RecentGameRow,
  type SessionRow,
  type SnapshotFilters,
} from './api';
import { Badge } from './components/Badge';
import { CardDetailPage } from './components/CardDetailPage';
import { CardLink } from './components/CardLink';
import { ColorPips } from './components/ColorPips';
import { opponentColorColumns } from './opponentColorColumns';
import { DeckDetailPage } from './components/DeckDetailPage';
import { DeckLink } from './components/DeckLink';
import { DeckVisual } from './components/DeckVisual';
import { FilterBar } from './components/FilterBar';
import { FormatsTable } from './components/FormatsTable';
import { GameDetailPage } from './components/GameDetailPage';
import { GamesPage } from './components/GamesPage';
import { MetricCard } from './components/MetricCard';
import { AuditPage } from './components/AuditPage';
import { OpponentDetailPage } from './components/OpponentDetailPage';
import { RankProgressChart } from './components/RankProgressChart';
import { SortableTable, type Column } from './components/SortableTable';
import { TrendChart } from './components/TrendChart';
import { TypeChip } from './components/TypeChip';
import { WinRateBar } from './components/WinRateBar';
import { AppShell } from './components/AppShell';
import { Section } from './components/Section';
import { ManaReadinessTable } from './components/ManaReadinessTable';
import { formatPercent, metricCards } from './dashboardData';
import { formatCardName, formatDateTime, formatDuration, formatNumber, outcomeLabel, outcomeTone, shortFormatLabel } from './format';
import { auditNavItems, cardNavItems, deckNavItems, gameNavItems, gamesNavItems, opponentNavItems } from './nav';
import { FORMAT_QUICK_FILTERS } from './quickFilters';
import { RouteFiltersContext } from './routeFilters';
import {
  dashboardRouteHash,
  deckRouteHashWithFilters,
  gameRouteHash,
  gamesRouteHash,
  parseAuditRoute,
  parseCardRoute,
  parseGamesRoute,
  parseDashboardRouteFilters,
  parseDeckRoute,
  parseGameRoute,
  parseOpponentRoute,
} from './routes';
import './styles.css';
import { getInitialTheme, hasStoredTheme, persistTheme, systemTheme, type ThemeName } from './theme';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; snapshot: DashboardSnapshot; lastUpdated: string; refreshError?: string }
  | { status: 'error'; message: string };

type RecentGameWithDrawQuality = RecentGameRow &
  Pick<DrawQualityRow, 'cards_seen' | 'lands_seen' | 'land_seen_pct'>;

const SNAPSHOT_REFRESH_MS = 20_000;
const DASHBOARD_TITLE = 'Performance Overview';

function formatLandsSeen(
  landsSeen: number | null | undefined,
  landSeenPct: number | null | undefined,
): string {
  const count = formatNumber(landsSeen);
  return landSeenPct === null || landSeenPct === undefined
    ? count
    : `${count} (${Math.ceil(landSeenPct)}%)`;
}

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

function readHasStoredTheme(): boolean {
  try {
    return hasStoredTheme();
  } catch {
    return false;
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
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

type DeckWithCombatRow = DeckRow & Partial<CombatDeckRow>;

const deckColumns: Column<DeckWithCombatRow>[] = [
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
          <span>
            {row.deck_visual.source === 'local_metadata' && row.deck_visual.card_name
              ? formatCardName(row.deck_visual.card_name)
              : 'No card data yet'}
          </span>
        </div>
      </div>
    ),
    sortValue: (row) => row.deck_name,
  },
  {
    key: 'aggression_profile',
    header: 'Profile',
    render: (row) =>
      row.aggression_profile ? (
        <span title={row.damage_per_turn ? `${row.damage_per_turn} damage per turn` : undefined}>
          <Badge tone="draw">{row.aggression_profile}</Badge>
        </span>
      ) : (
        '—'
      ),
    sortValue: (row) => row.aggression_profile ?? '',
  },
  { key: 'games', header: 'Games', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
  {
    key: 'avg_damage_dealt',
    header: 'Dmg Dealt / Game',
    render: (row) => formatNumber(row.avg_damage_dealt),
    sortValue: (row) => row.avg_damage_dealt,
    numeric: true,
  },
  {
    key: 'avg_damage_taken',
    header: 'Dmg Taken / Game',
    render: (row) => formatNumber(row.avg_damage_taken),
    sortValue: (row) => row.avg_damage_taken,
    numeric: true,
  },
  {
    key: 'avg_attack_steps',
    header: 'Attacks / Game',
    render: (row) => formatNumber(row.avg_attack_steps),
    sortValue: (row) => row.avg_attack_steps,
    numeric: true,
  },
  {
    key: 'attackers_per_attack',
    header: 'Attackers / Attack',
    render: (row) => formatNumber(row.attackers_per_attack),
    sortValue: (row) => row.attackers_per_attack,
    numeric: true,
  },
  {
    key: 'avg_player_turns',
    header: 'Avg Turns',
    render: (row) => formatNumber(row.avg_player_turns),
    sortValue: (row) => row.avg_player_turns,
    numeric: true,
  },
  {
    key: 'avg_life_gained',
    header: 'Life Gained / Game',
    render: (row) => formatNumber(row.avg_life_gained),
    sortValue: (row) => row.avg_life_gained,
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

const combatSplitColumns: Column<CombatSplitRow>[] = [
  { key: 'split', header: 'Result' },
  { key: 'games', header: 'Games', numeric: true },
  {
    key: 'avg_damage_dealt',
    header: 'Dmg Dealt',
    render: (row) => formatNumber(row.avg_damage_dealt),
    sortValue: (row) => row.avg_damage_dealt,
    numeric: true,
  },
  {
    key: 'avg_damage_taken',
    header: 'Dmg Taken',
    render: (row) => formatNumber(row.avg_damage_taken),
    sortValue: (row) => row.avg_damage_taken,
    numeric: true,
  },
  {
    key: 'avg_attack_steps',
    header: 'Attacks',
    render: (row) => formatNumber(row.avg_attack_steps),
    sortValue: (row) => row.avg_attack_steps,
    numeric: true,
  },
  {
    key: 'avg_life_gained',
    header: 'Life Gained',
    render: (row) => formatNumber(row.avg_life_gained),
    sortValue: (row) => row.avg_life_gained,
    numeric: true,
  },
  {
    key: 'avg_cards_drawn',
    header: 'Cards Drawn',
    render: (row) => formatNumber(row.avg_cards_drawn),
    sortValue: (row) => row.avg_cards_drawn,
    numeric: true,
  },
  {
    key: 'avg_cards_denied',
    header: 'Discarded + Milled',
    render: (row) => formatNumber(row.avg_cards_denied),
    sortValue: (row) => row.avg_cards_denied,
    numeric: true,
  },
];

const scheduleColumns: Column<ScheduleRow>[] = [
  {
    key: 'label',
    header: 'When',
    // Sort chronologically (Sunday..Saturday / morning..late night), not alphabetically.
    sortValue: (row) => row.weekday ?? row.bucket ?? 0,
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

const fatigueColumns: Column<FatigueRow>[] = [
  { key: 'label', header: 'Session Position' },
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

const outcomeReasonColumns: Column<OutcomeReasonRow>[] = [
  {
    key: 'reason',
    header: 'How It Ended',
    render: (row) => row.reason.replaceAll('_', ' '),
    sortValue: (row) => row.reason,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Your Wins', numeric: true },
  { key: 'losses', header: 'Your Losses', numeric: true },
];

const openerLandColumns: Column<OpenerLandRow>[] = [
  { key: 'label', header: 'Kept Opener' },
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

const opponentThreatColumns: Column<OpponentThreatRow>[] = [
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
  { key: 'games', header: 'Games Seen', numeric: true },
  { key: 'plays', header: 'Times Played', numeric: true },
  { key: 'losses', header: 'Your Losses', numeric: true },
  {
    key: 'loss_rate',
    header: 'Loss Rate',
    render: (row) => formatPercent(row.loss_rate),
    sortValue: (row) => row.loss_rate,
    numeric: true,
  },
];

const matchupColumns: Column<MatchupRow>[] = [
  {
    key: 'deck_name',
    header: 'Your Deck',
    render: (row) => (
      <DeckLink deckName={row.deck_name}>
        <strong>{row.deck_name}</strong>
      </DeckLink>
    ),
    sortValue: (row) => row.deck_name,
  },
  { key: 'opponent_archetype', header: 'Opponent Archetype' },
  { key: 'games', header: 'Games', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
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
  {
    key: 'format_label',
    header: 'Format',
    render: (row) => shortFormatLabel(row.format_label),
    sortValue: (row) => row.format_label,
  },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
  },
  {
    key: 'opp_colors',
    header: 'Opp',
    render: (row) => <ColorPips colors={row.opp_colors} />,
    sortValue: (row) => row.opp_colors ?? '',
  },
  {
    key: 'match_wins',
    header: 'Match Record',
    render: (row) =>
      (row.best_of ?? 1) > 1 && row.match_wins !== null && row.match_wins !== undefined
        ? `${row.match_wins}–${row.match_losses ?? 0}`
        : '—',
    sortValue: (row) => ((row.best_of ?? 1) > 1 ? (row.match_wins ?? 0) - (row.match_losses ?? 0) : null),
    numeric: true,
  },
  {
    key: 'is_flood',
    header: 'Draw Status',
    render: (row) =>
      row.is_flood ? (
        <Badge tone="draw">Flood</Badge>
      ) : row.is_screw ? (
        <Badge tone="screw">Mana Screw</Badge>
      ) : (
        'Normal'
      ),
    sortValue: (row) => (row.is_flood ? 2 : row.is_screw ? 1 : 0),
  },
  {
    key: 'mulligans',
    header: 'Mulligan(s)',
    render: (row) => formatNumber(row.mulligans),
    sortValue: (row) => row.mulligans,
    numeric: true,
  },
  {
    key: 'total_turns',
    header: 'Total Turns',
    render: (row) => formatNumber(row.total_turns),
    sortValue: (row) => row.total_turns,
    numeric: true,
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
    render: (row) => formatLandsSeen(row.lands_seen, row.land_seen_pct),
    sortValue: (row) => row.lands_seen,
    numeric: true,
  },
  {
    key: 'duration_seconds',
    header: 'Game Time',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
    numeric: true,
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
  const themeChosenRef = useRef<boolean>(readHasStoredTheme());
  const [filters, setFilters] = useState<SnapshotFilters>(() => parseDashboardRouteFilters(window.location.hash) ?? {});
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [routeHash, setRouteHash] = useState<string>(() => window.location.hash);
  const deckRoute = useMemo(() => parseDeckRoute(routeHash), [routeHash]);
  const gameRoute = useMemo(() => parseGameRoute(routeHash), [routeHash]);
  const cardRoute = useMemo(() => parseCardRoute(routeHash), [routeHash]);
  const opponentRoute = useMemo(() => parseOpponentRoute(routeHash), [routeHash]);
  const auditRoute = useMemo(() => parseAuditRoute(routeHash), [routeHash]);
  const gamesRoute = useMemo(() => parseGamesRoute(routeHash), [routeHash]);
  const deckName = deckRoute?.name ?? null;
  const gameId = gameRoute?.id ?? null;
  const cardName = cardRoute?.name ?? null;
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
  const cardPageNavItems = useMemo(
    () =>
      cardRoute
        ? cardNavItems.map((item) =>
            item.id === 'back-to-dashboard'
              ? {
                  ...item,
                  label: cardRoute.returnHash.startsWith('#/game/') ? '← Back to game' : '← Back to dashboard',
                  route: cardRoute.returnHash,
                }
              : item,
          )
        : cardNavItems,
    [cardRoute],
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
    if (themeChosenRef.current) {
      applyTheme(theme);
    } else {
      // No explicit preference yet: reflect the theme without persisting it,
      // so the dashboard keeps following the OS setting.
      document.documentElement.dataset.theme = theme;
    }
  }, [theme]);

  useEffect(() => {
    // Follow OS theme changes live while the user has no explicit preference.
    if (typeof window.matchMedia !== 'function') {
      return;
    }
    const media = window.matchMedia('(prefers-color-scheme: light)');
    function onSystemThemeChange() {
      try {
        if (!hasStoredTheme()) {
          setTheme(systemTheme());
        }
      } catch {
        // Ignore storage failures; the explicit toggle still works.
      }
    }
    media.addEventListener?.('change', onSystemThemeChange);
    return () => media.removeEventListener?.('change', onSystemThemeChange);
  }, []);

  useEffect(() => {
    if (
      deckRoute
      || gameRoute
      || cardRoute
      || opponentRoute
      || auditRoute
      || gamesRoute
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
  }, [auditRoute, cardRoute, deckRoute, gameRoute, gamesRoute, loadState.status, opponentRoute, routeHash]);

  useEffect(() => {
    document.title = deckRoute
      ? pageTitle(deckRoute.name)
      : gameRoute
        ? pageTitle('Game')
        : cardRoute
          ? pageTitle(cardRoute.name)
          : opponentRoute
            ? pageTitle(opponentRoute.name)
            : auditRoute
              ? pageTitle('DB Health')
              : gamesRoute
                ? pageTitle('All Games')
                : pageTitle('Overview');
  }, [auditRoute, deckRoute, gameRoute, gamesRoute, cardRoute, opponentRoute]);

  useEffect(() => {
    if (deckName || gameId || cardName || opponentRoute || auditRoute || gamesRoute) {
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
  }, [filters, deckName, gameId, cardName, opponentRoute, auditRoute, gamesRoute]);

  function toggleTheme() {
    themeChosenRef.current = true;
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }

  function updateFilters(nextFilters: SnapshotFilters) {
    setFilters(nextFilters);
    // Keep the dashboard URL shareable/bookmarkable without triggering a
    // scroll jump or an extra hashchange round-trip.
    if (!deckRoute && !gameRoute && !cardRoute && !opponentRoute) {
      try {
        window.history.replaceState(null, '', dashboardRouteHash(nextFilters));
        setRouteHash(window.location.hash);
      } catch {
        // history API unavailable: fall back to plain state updates.
      }
    }
  }

  return (
    <RouteFiltersContext.Provider value={activeRouteFilters}>
      <AppShell
        theme={theme}
        onToggleTheme={toggleTheme}
        navItems={
          gamesRoute
            ? gamesNavItems
          : auditRoute
            ? auditNavItems
          : cardRoute
            ? cardPageNavItems
            : gameId
              ? gamePageNavItems
              : deckName
                ? deckPageNavItems
                : opponentRoute
                  ? opponentNavItems
                  : undefined
        }
        heading={gamesRoute ? 'All Games' : auditRoute ? 'Database Health' : cardName ? formatCardName(cardName) : (gameRoute ? 'Game Detail' : deckName ?? opponentRoute?.name ?? DASHBOARD_TITLE)}
      >
        {gamesRoute ? (
          <GamesPage
            filters={gamesRoute.filters}
            onFiltersChange={(nextFilters) => {
              window.location.hash = gamesRouteHash(nextFilters);
            }}
          />
        ) : auditRoute ? (
          <AuditPage />
        ) : cardRoute ? (
          <CardDetailPage
            key={`${cardRoute.name}-${cardRoute.returnHash}`}
            backHref={cardRoute.returnHash}
            cardName={cardRoute.name}
            filters={cardRoute.filters}
          />
        ) : gameRoute ? (
          <GameDetailPage
            key={gameRoute.id}
            backHref={gameRoute.returnHash}
            focusId={gameRoute.focusId}
            gameId={gameRoute.id}
          />
        ) : deckName ? (
          <DeckDetailPage
            key={`${deckName}-${deckBackHref}`}
            backHref={deckBackHref}
            deckName={deckName}
            filters={deckRouteFilters}
            onFiltersChange={(nextFilters) => {
              window.location.hash = deckRouteHashWithFilters(deckName, nextFilters);
            }}
          />
        ) : opponentRoute ? (
          <OpponentDetailPage key={opponentRoute.name} filters={opponentRoute.filters} opponentName={opponentRoute.name} />
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
                onFiltersChange={updateFilters}
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
  const [recentQuickFilter, setRecentQuickFilter] = useState('all');
  const filteredDecks = useMemo(() => {
    const combatByDeck = new Map((snapshot.combat_decks ?? []).map((row) => [row.deck_name, row]));
    const merged = snapshot.decks.map((row) => ({ ...combatByDeck.get(row.deck_name), ...row }));
    const query = deckSearch.trim().toLocaleLowerCase();
    if (!query) {
      return merged;
    }
    return merged.filter((row) => row.deck_name.toLocaleLowerCase().includes(query));
  }, [deckSearch, snapshot.combat_decks, snapshot.decks]);
  const recentGames = useMemo(() => {
    const qualityByGame = new Map(snapshot.draw_quality.map((row) => [row.game_id, row]));
    return snapshot.recent.map((row) => {
      const quality = qualityByGame.get(row.game_id);
      const aggregateManaScrew =
        quality?.cards_seen !== null &&
        quality?.cards_seen !== undefined &&
        quality.cards_seen >= 10 &&
        quality?.lands_seen !== null &&
        quality?.lands_seen !== undefined &&
        quality.lands_seen <= 2;
      return {
        ...row,
        cards_seen: quality?.cards_seen ?? null,
        lands_seen: quality?.lands_seen ?? null,
        land_seen_pct: quality?.land_seen_pct ?? null,
        is_screw: Boolean(row.is_screw) || aggregateManaScrew,
      };
    });
  }, [snapshot.draw_quality, snapshot.recent]);

  const filteredRecentGames = useMemo(() => {
    const active = FORMAT_QUICK_FILTERS.find((filter) => filter.id === recentQuickFilter);
    if (!active || active.id === 'all') {
      return recentGames;
    }
    return recentGames.filter((row) => active.matches(row.format_label.toLocaleLowerCase()));
  }, [recentGames, recentQuickFilter]);

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
            <MetricCard
              key={metric.label}
              detail={metric.detail}
              href={metric.href}
              label={metric.label}
              value={metric.value}
            />
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
        description="Constructed ladder progress by season. Ranked Standard Best-of-1 and Best-of-3 share this rank."
      >
        {(snapshot.filter_options.rank_seasons ?? []).length > 1 ? (
          <div className="table-filter">
            <label>
              <span>Season</span>
              <select
                value={filters.season ?? ''}
                onChange={(event) =>
                  onFiltersChange({
                    ...filters,
                    season: event.target.value ? Number(event.target.value) : undefined,
                  })
                }
              >
                <option value="">Latest</option>
                {(snapshot.filter_options.rank_seasons ?? []).map((season) => (
                  <option key={season} value={season}>
                    Season {season}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
        <div className="trend-wrap">
          <RankProgressChart rows={snapshot.rank_progress ?? []} />
        </div>
      </Section>

      <Section
        id="recent-games"
        title="Recent Games"
        description="Recent results with draw distribution, flood or mana-screw status, total turns, and game time."
      >
        <div className="quick-filters" role="group" aria-label="Quick format filters">
          {FORMAT_QUICK_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              className={recentQuickFilter === filter.id ? 'quick-filter quick-filter-active' : 'quick-filter'}
              aria-pressed={recentQuickFilter === filter.id}
              onClick={() => setRecentQuickFilter(filter.id)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <SortableTable
          caption="Recent games"
          columns={recentColumns}
          pageSize={15}
          paginationKey={recentQuickFilter}
          getRowKey={(row) => row.game_id}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          rows={filteredRecentGames}
        />
        <p className="section-footer-link">
          <a className="table-link" href={gamesRouteHash(filters)}>
            View all games →
          </a>
        </p>
      </Section>

      <Section
        id="decks"
        title="Decks"
        description="Record plus combat telemetry per deck: damage pace, attacks, and lifegain. Profile is judged by damage dealt per turn."
      >
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
          pageSize={10}
          paginationKey={deckSearch.trim().toLocaleLowerCase()}
          rows={filteredDecks}
        />
        <div className="section-heading">
          <div>
            <h3>Wins vs Losses</h3>
            <p className="section-description">
              How your games look when you win compared to when you lose.
            </p>
          </div>
        </div>
        <SortableTable
          caption="Combat splits by result"
          columns={combatSplitColumns}
          getRowKey={(row) => row.split}
          rows={snapshot.combat_split ?? []}
        />
      </Section>

      <Section
        id="land-drops"
        title="Land Availability"
        description="How often you had N lands available by turn N (opening hand + tagged draws), and how win rate shifts when you fall behind."
      >
        <ManaReadinessTable caption="Land availability on curve" rows={snapshot.mana_readiness ?? []} />
      </Section>

      <Section
        id="habits"
        title="Habits & Schedule"
        description="When you play and how deep into a session you are, versus how often you win."
      >
        <div className="overview-analytics">
          <section className="overview-panel" aria-labelledby="habits-weekday-title">
            <div className="section-heading">
              <div>
                <h3 id="habits-weekday-title">By Day of Week</h3>
              </div>
            </div>
            <SortableTable
              caption="Win rate by weekday"
              columns={scheduleColumns}
              getRowKey={(row) => row.label}
              initialSort={{ key: 'label', direction: 'asc' }}
              rows={snapshot.schedule?.by_weekday ?? []}
            />
          </section>
          <section className="overview-panel" aria-labelledby="habits-time-title">
            <div className="section-heading">
              <div>
                <h3 id="habits-time-title">By Time of Day</h3>
              </div>
            </div>
            <SortableTable
              caption="Win rate by time of day"
              columns={scheduleColumns}
              getRowKey={(row) => row.label}
              initialSort={{ key: 'label', direction: 'asc' }}
              rows={snapshot.schedule?.by_time_of_day ?? []}
            />
          </section>
        </div>
        <div className="section-heading">
          <div>
            <h3>Session Fatigue</h3>
            <p className="section-description">Win rate by how many games deep into a tracker session you were.</p>
          </div>
        </div>
        <SortableTable
          caption="Win rate by session position"
          columns={fatigueColumns}
          getRowKey={(row) => row.label}
          rows={snapshot.fatigue ?? []}
        />
      </Section>

      <Section
        id="outcomes"
        title="Streaks & Outcomes"
        description="Run lengths, how games actually end, and what your kept opening hands cost you."
      >
        <section className="metric-grid" aria-label="Streaks">
          <MetricCard
            label="Current Streak"
            value={
              snapshot.streaks?.current
                ? `${snapshot.streaks.current.length} ${snapshot.streaks.current.kind === 'win' ? 'W' : 'L'}`
                : '—'
            }
          />
          <MetricCard label="Longest Win Streak" value={formatNumber(snapshot.streaks?.longest_win)} />
          <MetricCard label="Longest Loss Streak" value={formatNumber(snapshot.streaks?.longest_loss)} />
          <MetricCard label="Decided Games" value={formatNumber(snapshot.streaks?.games)} />
        </section>
        <div className="overview-analytics">
          <section className="overview-panel" aria-labelledby="outcomes-reasons-title">
            <div className="section-heading">
              <div>
                <h3 id="outcomes-reasons-title">How Games End</h3>
              </div>
            </div>
            <SortableTable
              caption="Outcome reasons"
              columns={outcomeReasonColumns}
              getRowKey={(row) => row.reason}
              initialSort={{ key: 'games', direction: 'desc' }}
              rows={snapshot.outcome_reasons ?? []}
            />
          </section>
          <section className="overview-panel" aria-labelledby="outcomes-opener-title">
            <div className="section-heading">
              <div>
                <h3 id="outcomes-opener-title">Kept Opener Lands</h3>
              </div>
            </div>
            <SortableTable
              caption="Win rate by lands in kept opening hand"
              columns={openerLandColumns}
              getRowKey={(row) => row.label}
              rows={snapshot.opener_lands ?? []}
            />
          </section>
        </div>
      </Section>

      <Section
        id="opponent-meta"
        title="Opponent Meta"
        description="What the ladder is beating you with, and matchup records when opponent archetypes are identified."
      >
        <div className="section-heading">
          <div>
            <h3>Opponent Colors</h3>
            <p className="section-description">
              Color combinations inferred from every card each opponent revealed. Games with no
              identified colored cards show as Unknown.
            </p>
          </div>
        </div>
        <SortableTable
          caption="Record by opponent color combination"
          columns={opponentColorColumns}
          getRowKey={(row) => row.color_label}
          initialSort={{ key: 'games', direction: 'desc' }}
          pageSize={15}
          rows={snapshot.opponent_colors ?? []}
        />
        <div className="section-heading">
          <div>
            <h3>Cards That Beat You</h3>
            <p className="section-description">
              Opponent-played cards ranked by how often their games end in your losses (minimum 2 games).
            </p>
          </div>
        </div>
        <SortableTable
          caption="Opponent threat leaderboard"
          columns={opponentThreatColumns}
          getRowKey={(row) => row.display_name}
          initialSort={{ key: 'loss_rate', direction: 'desc' }}
          pageSize={15}
          rows={snapshot.opponent_threats ?? []}
        />
        <div className="section-heading">
          <div>
            <h3>Matchups</h3>
            <p className="section-description">
              Your decks against identified opponent archetypes. Archetype identification is optional — enable
              the deck LLM in config.py (DECK_LLM_ENABLED plus an API key) and future games will be tagged.
            </p>
          </div>
        </div>
        {(snapshot.matchups ?? []).length > 0 ? (
          <SortableTable
            caption="Matchup records"
            columns={matchupColumns}
            getRowKey={(row) => `${row.deck_name}|${row.opponent_archetype}`}
            initialSort={{ key: 'games', direction: 'desc' }}
            pageSize={15}
            rows={snapshot.matchups ?? []}
          />
        ) : (
          <p className="empty-state">No identified opponent archetypes yet.</p>
        )}
      </Section>

      <Section id="formats" title="Formats">
        <FormatsTable caption="Format performance" rows={snapshot.formats} />
      </Section>

      <Section id="sessions" title="Sessions" description="Tracker runtime sessions with game volume and record.">
        <SortableTable
          caption="Tracker sessions"
          columns={sessionColumns}
          pageSize={15}
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
