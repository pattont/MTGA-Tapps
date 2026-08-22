import { ChartNoAxesCombined, Flame, HeartCrack, Swords, TrendingDown, Trophy } from 'lucide-react';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { pageTitle } from './branding';
import {
  fetchDashboardSnapshot,
  type CombatDeckRow,
  type CombatSplitRow,
  type DashboardSnapshot,
  type DeckRow,
  type FatigueRow,
  type OpenerLandRow,
  type OutcomeReasonRow,
  type ScheduleRow,
  type DrawQualityRow,
  type MatchLevelSummary,
  type MomentumRow,
  type PlayDrawRow,
  type RecentGameRow,
  type SessionRow,
  type SnapshotFilters,
} from './api';
import { Badge } from './components/Badge';
import { CardDetailPage } from './components/CardDetailPage';
import { ColorPips } from './components/ColorPips';
import { makeCommanderColumns } from './commanderColumns';
import { makeOpponentColorColumns } from './opponentColorColumns';
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
import { WinRateBar } from './components/WinRateBar';
import { AppShell } from './components/AppShell';
import { Section } from './components/Section';
import { ManaReadinessTable } from './components/ManaReadinessTable';
import { bestDeckMetric, formatPercent, metricCards } from './dashboardData';
import type { MetricDefinition } from './dashboardData';
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
  Pick<DrawQualityRow, 'cards_seen' | 'lands_seen' | 'land_seen_pct'> & {
    /** True for a synthetic Bo3 match rollup row. */
    match_row?: boolean;
    /** "Game N" label on the per-game sub-rows of a match rollup. */
    game_label?: string;
    /** The games of a Bo3 match, nested under its rollup row. */
    sub_games?: RecentGameWithDrawQuality[];
  };

/** Time of day only — the match rollup row already shows the date. */
function formatTimeOnly(value: string): string {
  const stamp = new Date(value);
  if (Number.isNaN(stamp.getTime())) {
    return formatDateTime(value);
  }
  return stamp.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/** WUBRG-ordered union of opponent color strings. */
function unionColors(values: Array<string | undefined>): string {
  const seen = new Set(values.flatMap((value) => (value ? value.split('') : [])));
  return ['W', 'U', 'B', 'R', 'G']
    .filter((color) => seen.has(color))
    .join('');
}

function sumOrNull(values: Array<number | null | undefined>): number | null {
  const present = values.filter((value): value is number => value !== null && value !== undefined);
  return present.length ? present.reduce((total, value) => total + value, 0) : null;
}

/**
 * Collapse the games of each Bo3 match into one rollup row with the
 * individual games nested beneath it. Bo1 games pass through untouched.
 */
function groupRecentGames(rows: RecentGameWithDrawQuality[]): RecentGameWithDrawQuality[] {
  const grouped: RecentGameWithDrawQuality[] = [];
  const matchRowByMatchId = new Map<string, RecentGameWithDrawQuality>();
  for (const row of rows) {
    const matchId = row.match_id;
    if (!matchId || (row.best_of ?? 1) <= 1) {
      grouped.push(row);
      continue;
    }
    const subRow = { ...row, game_label: `Game ${row.game_number ?? '?'}` };
    const existing = matchRowByMatchId.get(matchId);
    if (existing?.sub_games) {
      existing.sub_games.push(subRow);
      continue;
    }
    const matchRow: RecentGameWithDrawQuality = { ...row, match_row: true, sub_games: [subRow] };
    matchRowByMatchId.set(matchId, matchRow);
    grouped.push(matchRow);
  }
  for (const matchRow of matchRowByMatchId.values()) {
    const games = (matchRow.sub_games ?? []).sort(
      (a, b) => (a.game_number ?? 0) - (b.game_number ?? 0),
    );
    matchRow.sub_games = games;
    const first = games[0];
    const wins = matchRow.match_wins ?? 0;
    const losses = matchRow.match_losses ?? 0;
    Object.assign(matchRow, {
      game_id: first?.game_id ?? matchRow.game_id,
      started_at: first?.started_at ?? matchRow.started_at,
      outcome: wins === losses ? matchRow.outcome : wins > losses ? 'win' : 'loss',
      opp_colors: unionColors(games.map((game) => game.opp_colors)),
      mulligans: sumOrNull(games.map((game) => game.mulligans)),
      total_turns: sumOrNull(games.map((game) => game.total_turns)),
      duration_seconds: sumOrNull(games.map((game) => game.duration_seconds)),
      cards_seen: sumOrNull(games.map((game) => game.cards_seen)),
      lands_seen: sumOrNull(games.map((game) => game.lands_seen)),
      is_flood: games.some((game) => game.is_flood),
      is_screw: games.some((game) => game.is_screw),
    });
    const cards = matchRow.cards_seen;
    const lands = matchRow.lands_seen;
    matchRow.land_seen_pct = cards && lands !== null ? (100 * lands) / cards : null;
  }
  return grouped;
}

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
      <div className="setup-card-pips" aria-hidden="true">
        {['W', 'U', 'B', 'R', 'G'].map((color) => (
          <img key={color} alt="" height={28} src={`/icons/${color}.svg`} width={28} />
        ))}
      </div>
      <h3>No tracked games yet</h3>
      <p>
        You're all set — the tracker is running. Play a game of MTG Arena and it will show up
        here automatically when it finishes.
      </p>
      <p className="setup-card-hint">
        Keep the tracker running while you play. This page refreshes on its own.
      </p>
      <div className="setup-card-warning" role="alert">
        <strong>Games not showing up?</strong> The tracker can only see games when{' '}
        <strong>Detailed Logs</strong> are enabled in MTG Arena. In Arena, click the gear icon
        (top right) → <em>Adjust Options</em> → <em>Account</em> → check{' '}
        <em>"Detailed Logs (Plugin Support)"</em>, then restart Arena.
      </div>
    </section>
  );
}

/** Maps metric icon keys to lucide icons; icons inherit the card's colors. */
const METRIC_ICONS: Record<string, ReactNode> = {
  matches: <Swords />,
  wins: <Trophy />,
  losses: <HeartCrack />,
  winRate: <ChartNoAxesCombined />,
  winStreak: <Flame />,
  lossStreak: <TrendingDown />,
};

/** Six ranked stat cards — shared by the lifetime and per-season rows. */
function rankedMetricCards(summary: MatchLevelSummary, matchesLabel: string): ReactNode {
  return (
    <>
      <MetricCard
        icon={METRIC_ICONS.matches}
        label={matchesLabel}
        value={formatNumber(summary.matches)}
      />
      <MetricCard icon={METRIC_ICONS.wins} label="Wins" tone="win" value={formatNumber(summary.wins)} />
      <MetricCard
        icon={METRIC_ICONS.losses}
        label="Losses"
        tone="loss"
        value={formatNumber(summary.losses)}
      />
      <MetricCard icon={METRIC_ICONS.winRate} label="Win Rate" value={formatPercent(summary.win_rate)} />
      <MetricCard
        icon={METRIC_ICONS.winStreak}
        label="Longest Win Streak"
        value={formatNumber(summary.longest_win)}
      />
      <MetricCard
        icon={METRIC_ICONS.lossStreak}
        label="Longest Loss Streak"
        value={formatNumber(summary.longest_loss)}
      />
    </>
  );
}


function BestDeckBar({
  metric,
  visual,
}: {
  metric: MetricDefinition;
  visual?: DeckRow['deck_visual'];
}) {
  return (
    <section className="best-deck-bar" aria-label={metric.label}>
      {visual?.image_url ? (
        <div
          className="best-deck-art"
          style={{ backgroundImage: `url(${visual.image_url})` }}
          aria-hidden="true"
        />
      ) : null}
      <span className="best-deck-label">{metric.label}</span>
      {metric.href ? (
        <a className="best-deck-name" href={metric.href}>
          {metric.value}
        </a>
      ) : (
        <span className="best-deck-name">{metric.value}</span>
      )}
      {metric.detail ? <span className="best-deck-detail">{metric.detail}</span> : null}
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
  {
    key: 'colors',
    header: 'Colors',
    render: (row) => (row.colors ? <ColorPips colors={row.colors} /> : '—'),
    sortValue: (row) => row.colors ?? '',
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
];

const playDrawColumns: Column<PlayDrawRow>[] = [
  {
    key: 'play_draw',
    // The panel heading already says "Play / Draw" — no need to repeat it.
    header: '',
    sortable: false,
    render: (row) => row.play_draw ?? 'Unknown',
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'avg_mulligans',
    header: 'Avg Mulligans',
    render: (row) => formatNumber(row.avg_mulligans),
    sortValue: (row) => row.avg_mulligans,
    numeric: true,
  },
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
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

const combatSplitColumns: Column<CombatSplitRow>[] = [
  {
    key: 'split',
    header: 'Result',
    render: (row) => (
      <span className={row.split === 'Wins' ? 'result-label-win' : 'result-label-loss'}>
        {row.split}
      </span>
    ),
    // Ascending puts Wins first, matching the tinted card order up top.
    sortValue: (row) => (row.split === 'Wins' ? 0 : 1),
  },
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

interface OutcomeReasonGroupRow {
  reason: string;
  games: number;
}

/** Share of a side's total, e.g. 289 of 431 → "67.1%". */
function formatShare(games: number, total: number): string {
  return total > 0 ? `${((100 * games) / total).toFixed(1)}%` : '—';
}

/** Split outcome reasons into win-condition and loss-condition lists. */
function groupOutcomeReasons(rows: OutcomeReasonRow[]): {
  wins: OutcomeReasonGroupRow[];
  losses: OutcomeReasonGroupRow[];
  winTotal: number;
  lossTotal: number;
} {
  const wins = rows
    .filter((row) => row.wins > 0)
    .map((row) => ({ reason: row.reason, games: row.wins }))
    .sort((a, b) => b.games - a.games);
  const losses = rows
    .filter((row) => row.losses > 0)
    .map((row) => ({ reason: row.reason, games: row.losses }))
    .sort((a, b) => b.games - a.games);
  return {
    wins,
    losses,
    winTotal: wins.reduce((sum, row) => sum + row.games, 0),
    lossTotal: losses.reduce((sum, row) => sum + row.games, 0),
  };
}

const openerLandColumns: Column<OpenerLandRow>[] = [
  { key: 'label', header: 'Kept Opener' },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'avg_mulligans',
    header: 'Avg Mulligans',
    render: (row) => formatNumber(row.avg_mulligans),
    sortValue: (row) => row.avg_mulligans,
    numeric: true,
  },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

const homeOpponentColorColumns = makeOpponentColorColumns((row) =>
  gamesRouteHash({ colors: row.colors }),
);

const yourCommanderColumns = makeCommanderColumns('Your Commander');
const facedCommanderColumns = makeCommanderColumns('Opponent Commander');

const recentColumns: Column<RecentGameWithDrawQuality>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) =>
      row.game_label ? (
        <a className="subrow-link" href={gameRouteHash(row.game_id, '#recent-games')}>
          <span className="subrow-game-label">{row.game_label}</span>
          <span className="subrow-time">{formatTimeOnly(row.started_at)}</span>
        </a>
      ) : (
        <a href={gameRouteHash(row.game_id, '#recent-games')}>{formatDateTime(row.started_at)}</a>
      ),
    sortValue: (row) => row.started_at,
  },
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => (row.game_label ? null : <DeckLink deckName={row.deck_name} />),
    sortValue: (row) => row.deck_name,
  },
  {
    key: 'deck_colors',
    header: 'Colors',
    render: (row) =>
      row.game_label || !row.deck_colors ? null : <ColorPips colors={row.deck_colors} />,
    sortValue: (row) => row.deck_colors ?? '',
  },
  {
    key: 'format_label',
    header: 'Format',
    render: (row) =>
      row.game_label
        ? null
        : row.match_row
          ? `${shortFormatLabel(row.format_label)} · ${row.sub_games?.length ?? 0} game${
              (row.sub_games?.length ?? 0) === 1 ? '' : 's'
            }`
          : shortFormatLabel(row.format_label),
    sortValue: (row) => row.format_label,
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
    render: (row) => (row.game_label ? null : <ColorPips colors={row.opp_colors} />),
    sortValue: (row) => row.opp_colors ?? '',
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
    center: true,
  },
  {
    key: 'mulligans',
    header: 'Mulligan(s)',
    render: (row) => formatNumber(row.mulligans),
    sortValue: (row) => row.mulligans,
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
    key: 'total_turns',
    header: 'Turns',
    render: (row) => formatNumber(row.total_turns),
    sortValue: (row) => row.total_turns,
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

  const playerName =
    loadState.status === 'loaded' ? loadState.snapshot.summary.player_name : undefined;
  const dashboardTitle = playerName
    ? `${playerName}${playerName.endsWith('s') ? "'" : "'s"} Performance Overview`
    : DASHBOARD_TITLE;

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
        heading={gamesRoute ? 'All Games' : auditRoute ? 'Database Health' : cardName ? formatCardName(cardName) : gameRoute ? 'Game Detail' : deckName ? 'Deck Details' : (opponentRoute?.name ?? dashboardTitle)}
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
  const landProfile =
    snapshot.land_profile && snapshot.land_profile.classified_games > 0
      ? snapshot.land_profile
      : null;
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

  const outcomeGroups = useMemo(
    () => groupOutcomeReasons(snapshot.outcome_reasons ?? []),
    [snapshot.outcome_reasons],
  );

  const filteredRecentGames = useMemo(() => {
    const active = FORMAT_QUICK_FILTERS.find((filter) => filter.id === recentQuickFilter);
    const base =
      !active || active.id === 'all'
        ? recentGames
        : recentGames.filter((row) => active.matches(row.format_label.toLocaleLowerCase()));
    return groupRecentGames(base);
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
          {metricCards(snapshot).map((metric) => (
            <MetricCard
              key={metric.label}
              detail={metric.detail}
              href={metric.href}
              icon={metric.iconName ? METRIC_ICONS[metric.iconName] : undefined}
              label={metric.label}
              tone={metric.tone}
              value={metric.value}
            />
          ))}
        </section>
        <BestDeckBar
          metric={bestDeckMetric(snapshot, filters)}
          visual={
            snapshot.decks.find(
              (deck) => deck.deck_name === bestDeckMetric(snapshot, filters).value,
            )?.deck_visual
          }
        />
        <div className="overview-analytics">
          <section className="overview-panel" aria-labelledby="overview-wvl-title">
            <div className="section-heading">
              <div>
                <h3 id="overview-wvl-title">Wins vs Losses</h3>
                <p className="section-description">
                  How your games look when you win compared to when you lose. Per game, and only
                  games with combat telemetry — early tracker versions didn&apos;t record it, so
                  totals run below How Games End.
                </p>
              </div>
            </div>
            <SortableTable
              caption="Combat splits by result"
              columns={combatSplitColumns}
              getRowKey={(row) => row.split}
              rows={snapshot.combat_split ?? []}
            />
          </section>
        </div>
        <div className="overview-analytics">
          <section className="overview-panel" aria-labelledby="overview-play-draw-title">
            <div className="section-heading">
              <div>
                <h3 id="overview-play-draw-title">Play / Draw</h3>
                <p className="section-description">
                  Your record when you started on the play versus on the draw.
                </p>
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
        <div className="overview-analytics">
          <section className="overview-panel" aria-labelledby="outcomes-reasons-title">
            <div className="section-heading">
              <div>
                <h3 id="outcomes-reasons-title">How Games End</h3>
                <p className="section-description">
                  Individual games — a Bo3 contributes each of its games, so totals run above the
                  match-level cards up top.
                </p>
              </div>
            </div>
            <div className="outcome-reason-pair">
              <div className="table-wrap" role="region" aria-label="How wins end" tabIndex={0}>
                <table className="outcome-reason-grid">
                  <caption>How wins end</caption>
                  <tbody>
                    <tr className="outcome-group-row outcome-group-row-win">
                      <th colSpan={2} scope="colgroup">
                        Wins
                      </th>
                    </tr>
                    {outcomeGroups.wins.map((row) => (
                      <tr key={`win-${row.reason}`}>
                        <td>{row.reason.replaceAll('_', ' ')}</td>
                        <td className="num">
                          {formatNumber(row.games)}
                          <span className="outcome-reason-pct">
                            {' '}
                            ({formatShare(row.games, outcomeGroups.winTotal)})
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="table-wrap" role="region" aria-label="How losses end" tabIndex={0}>
                <table className="outcome-reason-grid">
                  <caption>How losses end</caption>
                  <tbody>
                    <tr className="outcome-group-row outcome-group-row-loss">
                      <th colSpan={2} scope="colgroup">
                        Losses
                      </th>
                    </tr>
                    {outcomeGroups.losses.map((row) => (
                      <tr key={`loss-${row.reason}`}>
                        <td>{row.reason.replaceAll('_', ' ')}</td>
                        <td className="num">
                          {formatNumber(row.games)}
                          <span className="outcome-reason-pct">
                            {' '}
                            ({formatShare(row.games, outcomeGroups.lossTotal)})
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
          <section className="overview-panel" aria-labelledby="outcomes-opener-title">
            <div className="section-heading">
              <div>
                <h3 id="outcomes-opener-title">Kept Opener Lands</h3>
                <p className="section-description">
                  Results by how many lands were in the opening hand you kept.
                </p>
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
      </section>

      <Section
        id="trend"
        title="Win Rate Trend"
        description="Rolling win rate across your most recent 30 finished games."
      >
        <div className="trend-wrap">
          <TrendChart rows={snapshot.trend} />
        </div>
      </Section>

      <Section
        id="rank-progress"
        title="Constructed Ranked"
        description="Constructed ranked queues only, match-level (a Bo3 counts once). Ranked Standard BO1 and BO3 share the ladder rank charted below."
      >
        {snapshot.ranked_summary && snapshot.ranked_summary.matches > 0 ? (
          <>
            <div className="section-heading">
              <div>
                <h3>Lifetime Ranked Stats</h3>
              </div>
            </div>
            <section className="metric-grid ranked-metric-grid" aria-label="Lifetime ranked record">
              {rankedMetricCards(snapshot.ranked_summary, 'Ranked Matches')}
            </section>
          </>
        ) : null}
        <div className="section-heading">
          <div>
            <h3>
              {filters.season && snapshot.ranked_season_summary
                ? `Season ${snapshot.ranked_season_summary.season_ordinal} Stats`
                : 'Current Season Stats'}
            </h3>
            <p className="section-description">
              Resets every seasonal rollover; the dropdown swaps the chart and the boxes below it
              to that season.
            </p>
          </div>
        </div>
        {(snapshot.filter_options.rank_seasons ?? []).length > 0 ? (
          <div className="table-filter">
            <label className="filter-field">
              <span className="filter-field-label">Season</span>
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
        {snapshot.ranked_season_summary ? (
          <section className="metric-grid ranked-metric-grid" aria-label="Season ranked record">
            {rankedMetricCards(snapshot.ranked_season_summary, 'Season Matches')}
          </section>
        ) : null}
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
          getRowKey={(row) => (row.match_row ? `match:${row.match_id}` : row.game_id)}
          getSubRows={(row) => row.sub_games}
          renderDetailRow={(row) =>
            row.match_row && row.match_wins !== null && row.match_wins !== undefined ? (
              // Match record lives in the Bo3 flyout only — a win is a win at
              // the top level, whether it took two games or three.
              <div className="match-record-detail">
                Match record:{' '}
                <strong>
                  {row.match_wins}–{row.match_losses ?? 0}
                </strong>
              </div>
            ) : !row.match_row && (row.player_commander || row.opponent_commander) ? (
              <div className="commander-matchup">
                <span className="color-combo">
                  {row.player_commander_colors ? (
                    <ColorPips colors={row.player_commander_colors} />
                  ) : null}
                  {row.player_commander ?? 'Unknown commander'}
                </span>
                <span className="commander-matchup-vs">vs</span>
                <span className="color-combo">
                  {row.opponent_commander_colors ? (
                    <ColorPips colors={row.opponent_commander_colors} />
                  ) : null}
                  {row.opponent_commander ?? 'Unknown commander'}
                </span>
              </div>
            ) : null
          }
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
          <input
            type="search"
            aria-label="Search decks"
            value={deckSearch}
            onChange={(event) => setDeckSearch(event.target.value)}
            placeholder="Search decks"
          />
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
      </Section>

      <Section
        id="land-drops"
        title="Land Statistics"
        description={
          landProfile
            ? `Across ${landProfile.classified_games} classified games`
            : 'How often you had N lands available by turn N (opening hand + tagged draws), and how win rate shifts when you fall behind.'
        }
      >
        {landProfile ? (
          <>
            <section className="metric-grid" aria-label="Land draw profile">
              <MetricCard
                label="Normal"
                value={
                  <span className="land-stat-normal">
                    {Math.round((100 * landProfile.normal_games) / landProfile.classified_games)}%
                  </span>
                }
                detail={`${landProfile.normal_games}/${landProfile.classified_games} games`}
              />
              <MetricCard
                label="Flood"
                value={
                  <span className="land-stat-flood">
                    {Math.round((100 * landProfile.flood_games) / landProfile.classified_games)}%
                  </span>
                }
                detail={`${landProfile.flood_games}/${landProfile.classified_games} games`}
              />
              <MetricCard
                label="Screw"
                value={
                  <span className="land-stat-screw">
                    {Math.round((100 * landProfile.screw_games) / landProfile.classified_games)}%
                  </span>
                }
                detail={`${landProfile.screw_games}/${landProfile.classified_games} games`}
              />
            </section>
            <div className="section-heading">
              <div>
                <h3>Land Availability</h3>
                <p className="section-description">
                  How often you had N lands available by turn N (opening hand + tagged draws), and
                  how win rate shifts when you fall behind.
                </p>
              </div>
            </div>
          </>
        ) : null}
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
            <p className="section-description">
              Win rate by how many games deep into a tracker session you were. Games 1–4 are the
              fresh baseline; fatigue only plausibly shows from game 5 on.
            </p>
          </div>
        </div>
        <SortableTable
          caption="Win rate by session position"
          columns={fatigueColumns}
          getRowKey={(row) => row.label}
          rows={snapshot.fatigue ?? []}
        />
      </Section>

      {(snapshot.brawl?.games ?? 0) > 0 ||
      (snapshot.your_commanders ?? []).length > 0 ||
      (snapshot.faced_commanders ?? []).length > 0 ? (
        <Section
          id="brawl"
          title="Brawl"
          description="Commander win rates from your Brawl games — the commander is visible from the opening hand, so every tracked Brawl game counts."
        >
          {snapshot.brawl && snapshot.brawl.games > 0 ? (
            <section className="metric-grid" aria-label="Brawl record">
              <MetricCard label="Brawl Games" value={formatNumber(snapshot.brawl.games)} />
              <MetricCard
                label="Brawl Record"
                value={`${formatNumber(snapshot.brawl.wins)} – ${formatNumber(snapshot.brawl.losses)}`}
              />
              <MetricCard label="Brawl Win Rate" value={formatPercent(snapshot.brawl.win_rate)} />
              {snapshot.brawl.queues.map((queue) => (
                <MetricCard
                  key={queue.format_label}
                  label={queue.format_label}
                  value={`${formatNumber(queue.wins)} – ${formatNumber(queue.losses)}`}
                  detail={formatPercent(queue.win_rate)}
                />
              ))}
            </section>
          ) : null}
          <div className="section-heading">
            <div>
              <h3>Your Commanders</h3>
              <p className="section-description">
                Record with each commander you brought to the ladder. Partner commanders count
                under each partner.
              </p>
            </div>
          </div>
          <SortableTable
            caption="Record by your commander"
            columns={yourCommanderColumns}
            getRowKey={(row) => row.commander}
            initialSort={{ key: 'games', direction: 'desc' }}
            pageSize={8}
            rows={snapshot.your_commanders ?? []}
          />
          <div className="section-heading">
            <div>
              <h3>Faced Commanders</h3>
              <p className="section-description">
                The commanders your opponents brought, and your record against each.
              </p>
            </div>
          </div>
          <SortableTable
            caption="Record against opponent commanders"
            columns={facedCommanderColumns}
            getRowKey={(row) => row.commander}
            initialSort={{ key: 'games', direction: 'desc' }}
            pageSize={8}
            rows={snapshot.faced_commanders ?? []}
          />
        </Section>
      ) : null}

      <Section
        id="opponent-meta"
        title="Opponent Meta"
        description="Your record by opponent color combination, inferred from every card each opponent revealed. Games with no identified colored cards show as Unknown."
      >
        <SortableTable
          caption="Record by opponent color combination"
          columns={homeOpponentColorColumns}
          getRowKey={(row) => row.color_label}
          initialSort={{ key: 'games', direction: 'desc' }}
          pageSize={10}
          rows={snapshot.opponent_colors ?? []}
        />
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
