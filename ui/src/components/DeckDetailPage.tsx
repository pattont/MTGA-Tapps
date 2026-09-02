import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ChartNoAxesCombined,
  Check,
  Clock,
  Copy,
  Crosshair,
  Flame,
  Gauge,
  Hourglass,
  Play,
  RefreshCw,
  Repeat,
  Swords,
  Timer,
  TrendingDown,
  Trophy,
} from 'lucide-react';
import {
  fetchDeckDetail,
  type CardPerformanceRow,
  type DeckCompositionRow,
  type DeckDetail,
  type DeckGameRow,
  type DeckInteractionSide,
  type DeckPlayedManaSeat,
  type DeckVersionRow,
  type MulliganRow,
  type OpponentColorRow,
  type SideboardSwapRow,
  type SnapshotFilters,
} from '../api';
import { formatPercent } from '../dashboardData';
import {
  boFormatLabel,
  formatCardName,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatTurnDuration,
  outcomeLabel,
  outcomeTone,
  shortFormatLabel,
} from '../format';
import { gameRouteHash, gamesRouteHash } from '../routes';
import { fetchManaCosts, playedManaStats, seedManaCosts, type CardManaInfo } from '../manaCosts';
import { makeOpponentColorColumns } from '../opponentColorColumns';
import { ManaCost } from './ManaCost';
import { Badge } from './Badge';
import { bucketCombatGroups, CombatGroupColumns, withDrawnSuffix } from './CombatGroupColumns';
import { ColorPips } from './ColorPips';
import { CardLink } from './CardLink';
import { CommanderBanner, commanderArtUrl } from './CommanderPanel';
import { makeCommanderColumns } from '../commanderColumns';
import { DeckVisual } from './DeckVisual';
import { FilterBar } from './FilterBar';
import { Section } from './Section';
import { ManaReadinessTable } from './ManaReadinessTable';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';
import { TrendChart } from './TrendChart';
import { TypeChip } from './TypeChip';
import { WinRateBar } from './WinRateBar';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: DeckDetail; refreshError?: string }
  | { status: 'error'; message: string };

type DeckListPerformanceRow = CardPerformanceRow & {
  quantity: number | null;
  deck_section: 'Main Deck' | 'Sideboard' | null;
  seen_pct: number | null;
  multiple_pct: number | null;
  seen_delta: number | null;
  opener_pct: number | null;
};

type DeckListManaRow = DeckListPerformanceRow & {
  mana: CardManaInfo | null;
  mana_cmc: number | null;
};

/** Every card name the decklist tables can show, for the mana-cost lookup. */
function deckCardNames(detail: DeckDetail): string[] {
  const names = new Set<string>();
  detail.card_performance.forEach((row) => names.add(row.display_name));
  detail.deck_export.main_deck.forEach((card) => names.add(card.display_name));
  detail.deck_export.sideboard.forEach((card) => names.add(card.display_name));
  // Both seats' played cards feed the mana-value averages in Combat & Resources.
  [detail.played_mana?.player, detail.played_mana?.opponent].forEach((seat) => {
    seat?.cards.forEach((card) => names.add(card.display_name));
  });
  return Array.from(names);
}

/** MTGA-style type bar, left to right, using the official card-type symbols
    from the bundled mana-font (chalice, claw mark, sunrise, bolt, flame…). */
const typeSymbol = (name: string): ReactNode => (
  <i aria-hidden="true" className={`ms ms-${name} type-count-icon`} />
);
const TYPE_COUNT_BOXES: Array<{ category: string; label: string; icon: ReactNode }> = [
  { category: 'Planeswalker', label: 'Planeswalker', icon: typeSymbol('planeswalker') },
  { category: 'Creature', label: 'Creature', icon: typeSymbol('creature') },
  { category: 'Sorcery', label: 'Sorcery', icon: typeSymbol('sorcery') },
  { category: 'Instant', label: 'Instant', icon: typeSymbol('instant') },
  { category: 'Artifact', label: 'Artifact', icon: typeSymbol('artifact') },
  { category: 'Enchantment', label: 'Enchantment', icon: typeSymbol('enchantment') },
  { category: 'Land', label: 'Land', icon: typeSymbol('land') },
];

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function cardNameAliases(cardName: string): Set<string> {
  const aliases = new Set([cardName]);
  cardName.split(' // ').forEach((name) => aliases.add(name.trim()));
  return aliases;
}

function compositionByName(detail: DeckDetail): Map<string, DeckCompositionRow> {
  const map = new Map<string, DeckCompositionRow>();
  for (const row of detail.composition ?? []) {
    cardNameAliases(row.display_name).forEach((alias) => map.set(alias, row));
  }
  return map;
}

function deckListPerformanceRows(detail: DeckDetail): DeckListPerformanceRow[] {
  const composition = compositionByName(detail);
  // Percentages of games use the deck's full game count. Composition stats
  // (seen 2+, expected) are scoped to games with a captured decklist, which
  // can be a much smaller set — do not mix the two denominators.
  const totalGames = detail.summary.games;
  const openerGames = new Map<string, number>();
  for (const row of detail.opening_hands ?? []) {
    cardNameAliases(row.display_name).forEach((alias) => openerGames.set(alias, row.games_in_opener));
  }
  const openerGamesFor = (name: string): number => {
    for (const alias of cardNameAliases(name)) {
      const found = openerGames.get(alias);
      if (found !== undefined) {
        return found;
      }
    }
    return 0;
  };
  const openerPct = (name: string): number | null => {
    if (!totalGames) {
      return null;
    }
    return Math.round((1000 * Math.min(openerGamesFor(name), totalGames)) / totalGames) / 10;
  };
  const gamesPct = (gamesSeen: number): number | null => {
    if (!totalGames) {
      return null;
    }
    return Math.round((1000 * Math.min(gamesSeen, totalGames)) / totalGames) / 10;
  };
  const compositionFor = (name: string): DeckCompositionRow | undefined => {
    for (const alias of cardNameAliases(name)) {
      const match = composition.get(alias);
      if (match) {
        return match;
      }
    }
    return undefined;
  };
  if (!detail.deck_export.available) {
    return detail.card_performance.map((row) => {
      const stats = compositionFor(row.display_name);
      return {
        ...row,
        quantity: stats?.copies ?? null,
        deck_section: null,
        seen_pct: gamesPct(row.games_seen),
        multiple_pct: stats?.multiple_pct ?? null,
        seen_delta: stats?.seen_delta ?? null,
        opener_pct: openerPct(row.display_name),
      };
    });
  }

  const performance = detail.card_performance.map((row) => ({
    row,
    aliases: cardNameAliases(row.display_name),
  }));
  const exportRows = [
    ...detail.deck_export.main_deck.map((card) => ({ card, deck_section: 'Main Deck' as const })),
    ...detail.deck_export.sideboard.map((card) => ({ card, deck_section: 'Sideboard' as const })),
  ].map(({ card, deck_section }) => {
    const aliases = cardNameAliases(card.display_name);
    const matchingPerformance = performance.find(({ aliases: performanceAliases }) =>
      Array.from(aliases).some((name) => performanceAliases.has(name)),
    )?.row;
    const stats = compositionFor(card.display_name);
    return {
      display_name: card.display_name,
      type_category: matchingPerformance?.type_category ?? card.type_category,
      quantity: card.quantity,
      deck_section,
      games_seen: matchingPerformance?.games_seen ?? 0,
      times_played: matchingPerformance?.times_played ?? 0,
      times_drawn: matchingPerformance?.times_drawn ?? 0,
      wins_when_seen: matchingPerformance?.wins_when_seen ?? 0,
      losses_when_seen: matchingPerformance?.losses_when_seen ?? 0,
      win_rate_when_seen: matchingPerformance?.win_rate_when_seen ?? null,
      seen_pct: gamesPct(matchingPerformance?.games_seen ?? 0),
      multiple_pct: stats?.multiple_pct ?? null,
      seen_delta: stats?.seen_delta ?? null,
      opener_pct: openerPct(card.display_name),
    };
  });
  // Brawl: the commander is the deck's 100th card but Arena's submitted
  // maindeck omits it — add it to the list so the count adds up.
  const commanderRows = (detail.commanders ?? [])
    .filter((commander) => {
      const aliases = cardNameAliases(commander.card_name);
      return !exportRows.some((row) =>
        Array.from(cardNameAliases(row.display_name)).some((name) => aliases.has(name)),
      );
    })
    .map((commander) => {
      const aliases = cardNameAliases(commander.card_name);
      const matchingPerformance = performance.find(({ aliases: performanceAliases }) =>
        Array.from(aliases).some((name) => performanceAliases.has(name)),
      )?.row;
      return {
        display_name: commander.card_name,
        type_category: matchingPerformance?.type_category ?? 'Creature',
        quantity: 1,
        deck_section: 'Main Deck' as const,
        // The commander starts in the command zone, visible to both players
        // every game by definition — "seen" is 100% of this deck's games,
        // and its when-seen record is simply the deck's record. Played
        // counts stay real (each cast from the command zone is tracked);
        // drawn/opener stats never apply since it is never drawn.
        games_seen: totalGames,
        times_played: matchingPerformance?.times_played ?? 0,
        times_drawn: matchingPerformance?.times_drawn ?? 0,
        wins_when_seen: detail.summary.wins,
        losses_when_seen: detail.summary.losses,
        win_rate_when_seen: detail.summary.win_rate,
        seen_pct: totalGames > 0 ? 100 : null,
        multiple_pct: null,
        seen_delta: null,
        opener_pct: null,
      };
    });
  return [...commanderRows, ...exportRows];
}

const sideboardSwapColumns: Column<SideboardSwapRow>[] = [
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  { key: 'boarded_in', header: 'In', numeric: true },
  { key: 'boarded_out', header: 'Out', numeric: true },
  {
    key: 'wins_in',
    header: 'Record When In',
    render: (row) =>
      row.games_in > 0 ? `${row.wins_in}–${row.losses_in}` : '—',
    sortValue: (row) => row.wins_in,
    numeric: true,
  },
  {
    key: 'win_rate_in',
    header: 'Win Rate When In',
    render: (row) =>
      row.games_in > 0 ? (
        <WinRateBar losses={row.losses_in} winRate={row.win_rate_in} wins={row.wins_in} />
      ) : (
        '—'
      ),
    sortValue: (row) => row.win_rate_in,
    numeric: true,
  },
  {
    key: 'vs_in',
    header: 'In Vs',
    render: (row) => row.vs_in || '—',
    sortValue: (row) => row.vs_in,
  },
  {
    key: 'vs_out',
    header: 'Out Vs',
    render: (row) => row.vs_out || '—',
    sortValue: (row) => row.vs_out,
  },
];

const cardColumns: Column<DeckListManaRow>[] = [
  { key: 'quantity', header: 'Count', numeric: true },
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'mana_cmc',
    header: 'Mana',
    render: (row) => <ManaCost info={row.mana} />,
    sortValue: (row) => row.mana_cmc,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
  {
    key: 'games_seen',
    header: 'Games Seen',
    render: (row) =>
      row.seen_pct === null ? formatNumber(row.games_seen) : `${row.games_seen} (${row.seen_pct}%)`,
    sortValue: (row) => row.games_seen,
    numeric: true,
  },
  {
    key: 'opener_pct',
    header: 'In Opener',
    render: (row) => formatPercent(row.opener_pct),
    sortValue: (row) => row.opener_pct,
    numeric: true,
  },
  {
    key: 'multiple_pct',
    header: 'Seen 2+ (decklist games)',
    render: (row) => formatPercent(row.multiple_pct),
    sortValue: (row) => row.multiple_pct,
    numeric: true,
  },
  {
    key: 'seen_delta',
    header: 'Seen vs Expected',
    render: (row) =>
      row.seen_delta === null ? '—' : `${row.seen_delta > 0 ? '+' : ''}${row.seen_delta}`,
    sortValue: (row) => row.seen_delta,
    numeric: true,
  },
];

type VersionRowWithDelta = DeckVersionRow & { wr_delta: number | null };

const versionColumns: Column<VersionRowWithDelta>[] = [
  { key: 'version', header: 'Version', numeric: true },
  {
    key: 'first_played',
    header: 'First Played',
    render: (row) => (row.first_played ? formatDateTime(row.first_played) : '—'),
    sortValue: (row) => row.first_played ?? '',
  },
  {
    key: 'last_played',
    header: 'Last Played',
    render: (row) => (row.last_played ? formatDateTime(row.last_played) : '—'),
    sortValue: (row) => row.last_played ?? '',
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
    key: 'wr_delta',
    header: 'WR vs Previous',
    render: (row) =>
      row.wr_delta === null ? '—' : `${row.wr_delta > 0 ? '+' : ''}${Math.round(row.wr_delta * 10) / 10}%`,
    sortValue: (row) => row.wr_delta,
    numeric: true,
  },
  {
    key: 'added',
    header: 'Changes vs Previous',
    render: (row) =>
      row.added.length === 0 && row.removed.length === 0 ? (
        row.version === 1 ? 'Initial list' : 'No changes'
      ) : (
        <span className="version-changes">
          {row.added.map((change) => (
            <span key={`in-${change}`} className="version-change version-change-in">
              + {change}
            </span>
          ))}
          {row.removed.map((change) => (
            <span key={`out-${change}`} className="version-change version-change-out">
              − {change}
            </span>
          ))}
        </span>
      ),
    sortValue: (row) => row.added.length + row.removed.length,
  },
];

const mulliganColumns: Column<MulliganRow>[] = [
  { key: 'mulligans', header: 'Mulligans', numeric: true },
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

const gameColumns: Column<DeckGameRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => <a href={gameRouteHash(row.game_id)}>{formatDateTime(row.started_at)}</a>,
    sortValue: (row) => row.started_at,
  },
  {
    key: 'format_label',
    header: 'Format',
    render: (row) => shortFormatLabel(row.format_label),
    sortValue: (row) => row.format_label,
  },
  {
    key: 'play_draw',
    header: 'Play / Draw',
    render: (row) =>
      row.play_draw === 'On the play' ? (
        <span className="text-play">Play</span>
      ) : row.play_draw === 'On the draw' ? (
        <span className="text-drawside">Draw</span>
      ) : (
        (row.play_draw ?? 'Unknown')
      ),
    sortValue: (row) => row.play_draw,
  },
  {
    key: 'opp_colors',
    header: 'Opp',
    render: (row) => <ColorPips colors={row.opp_colors} />,
    sortValue: (row) => row.opp_colors ?? '',
  },
  {
    key: 'is_flood',
    header: 'Draw Status',
    render: (row) =>
      row.is_flood ? (
        <Badge tone="flood">Flood</Badge>
      ) : row.is_screw ? (
        <Badge tone="screw">Mana Screw</Badge>
      ) : (
        'Normal'
      ),
    sortValue: (row) => (row.is_flood ? 2 : row.is_screw ? 1 : 0),
  },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
  },
  {
    key: 'mulligans',
    header: 'Mulligans',
    render: (row) => formatNumber(row.mulligans),
    sortValue: (row) => row.mulligans,
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


type CutCardRow = DeckCompositionRow & {
  wins_in_deck: number;
  losses_in_deck: number;
  win_rate_in_deck: number | null;
};

function versionsWithDelta(versions: DeckVersionRow[]): VersionRowWithDelta[] {
  return versions.map((version, index) => {
    const previous = index > 0 ? versions[index - 1] : null;
    const delta =
      previous && previous.win_rate !== null && version.win_rate !== null
        ? version.win_rate - previous.win_rate
        : null;
    return { ...version, wr_delta: delta };
  });
}

function cutCardRows(detail: DeckDetail): CutCardRow[] {
  if (!detail.deck_export.available) {
    return [];
  }
  const currentNames = new Set<string>();
  for (const card of [...detail.deck_export.main_deck, ...detail.deck_export.sideboard]) {
    cardNameAliases(card.display_name).forEach((alias) => currentNames.add(alias));
  }
  return (detail.composition ?? [])
    .filter((row) => !Array.from(cardNameAliases(row.display_name)).some((alias) => currentNames.has(alias)))
    .map((row) => {
      const wins = row.wins_when_seen + row.wins_when_not_seen;
      const losses = row.losses_when_seen + row.losses_when_not_seen;
      const decided = wins + losses;
      return {
        ...row,
        wins_in_deck: wins,
        losses_in_deck: losses,
        win_rate_in_deck: decided ? Math.round((1000 * wins) / decided) / 10 : null,
      };
    })
    .sort((a, b) => b.games_in_deck - a.games_in_deck);
}

const cutCardColumns: Column<CutCardRow>[] = [
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
  { key: 'games_in_deck', header: 'Games In Deck', numeric: true },
  {
    key: 'win_rate_in_deck',
    header: 'Deck WR While In List',
    render: (row) => (
      <WinRateBar losses={row.losses_in_deck} winRate={row.win_rate_in_deck} wins={row.wins_in_deck} />
    ),
    sortValue: (row) => row.win_rate_in_deck,
    numeric: true,
  },
  {
    key: 'seen_pct',
    header: 'Seen %',
    render: (row) => formatPercent(row.seen_pct),
    sortValue: (row) => row.seen_pct,
    numeric: true,
  },
  {
    key: 'win_rate_when_seen',
    header: 'WR When Seen',
    render: (row) => formatPercent(row.win_rate_when_seen),
    sortValue: (row) => row.win_rate_when_seen,
    numeric: true,
  },
];

/** "4.8 (39.7%)": average lands per game with the land share beside it. */
function landsWithPercent(avg: number | null | undefined, pct: number | null | undefined): string {
  if (pct == null) {
    return '—';
  }
  return avg == null ? `${pct}%` : `${avg.toFixed(1)} (${pct}%)`;
}

export function DeckDetailPage({
  backHref = '#overview',
  deckName,
  filters = {},
  onFiltersChange,
}: {
  backHref?: string;
  deckName: string;
  filters?: SnapshotFilters;
  onFiltersChange?: (filters: SnapshotFilters) => void;
}) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle');

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [deckName]);

  // The page is remounted per deck (keyed by deck name in App), so the
  // initial 'loading' state covers deck switches without an effect reset.
  useEffect(() => {
    let ignore = false;
    let activeController: AbortController | null = null;

    async function loadDetail() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const detail = await fetchDeckDetail(deckName, filters, controller.signal);
        if (!ignore) {
          setLoadState({ status: 'loaded', detail });
        }
      } catch (error: unknown) {
        if (!ignore && !isAbortError(error)) {
          const message = error instanceof Error ? error.message : 'Dashboard API failed';
          setLoadState((current) =>
            current.status === 'loaded'
              ? { ...current, refreshError: message }
              : { status: 'error', message },
          );
        }
      }
    }

    void loadDetail();
    const refreshId = window.setInterval(() => {
      if (!document.hidden) {
        void loadDetail();
      }
    }, DETAIL_REFRESH_MS);

    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [deckName, filters]);

  const deckFacedCommanderColumns = useMemo(() => makeCommanderColumns('Opponent Commander'), []);
  const deckOpponentColorColumns = useMemo(
    () => makeOpponentColorColumns((row) => gamesRouteHash({ deck: deckName, colors: row.colors })),
    [deckName],
  );
  const [manaCosts, setManaCosts] = useState<Map<string, CardManaInfo | null>>(() => new Map());
  const loadedDetail = loadState.status === 'loaded' ? loadState.detail : null;
  useEffect(() => {
    if (!loadedDetail) {
      return;
    }
    let cancelled = false;
    // Arena-derived costs from the payload win; Scryfall only fills gaps.
    seedManaCosts(loadedDetail.card_mana);
    void fetchManaCosts(deckCardNames(loadedDetail)).then((map) => {
      if (!cancelled) {
        setManaCosts(map);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadedDetail]);
  const landProfile =
    loadState.status === 'loaded' &&
    loadState.detail.land_profile &&
    loadState.detail.land_profile.classified_games > 0
      ? loadState.detail.land_profile
      : null;

  if (loadState.status === 'loading') {
    return (
      <p className="state-panel" role="status" aria-busy="true">
        Loading deck details...
      </p>
    );
  }
  if (loadState.status === 'error') {
    return (
      <div className="state-panel error-state" role="alert">
        <p>{loadState.message}</p>
        <a className="back-link" href={backHref}>
          ← Back to dashboard
        </a>
      </div>
    );
  }

  const { detail, refreshError } = loadState;
  const deckExport = detail.deck_export;
  const cardRows = deckListPerformanceRows(detail);
  const cutCards = cutCardRows(detail);
  const deckListRows: DeckListManaRow[] = cardRows.map((row) => {
    const mana = manaCosts.get(row.display_name) ?? null;
    return { ...row, mana, mana_cmc: mana ? mana.cmc : null };
  });
  const mainDeckRows = deckListRows.filter((row) => row.deck_section !== 'Sideboard');
  const sideboardRows = deckListRows.filter((row) => row.deck_section === 'Sideboard');
  const deckCountsKnown = deckExport.available;
  const mainDeckTotal = mainDeckRows.reduce((sum, row) => sum + (row.quantity ?? 0), 0);
  const sideboardTotal = sideboardRows.reduce((sum, row) => sum + (row.quantity ?? 0), 0);
  const typeCounts = TYPE_COUNT_BOXES.map((box) => ({
    ...box,
    count: mainDeckRows
      .filter((row) => row.type_category === box.category)
      .reduce((sum, row) => sum + (row.quantity ?? 0), 0),
  }));
  // Mana-value stats: printed costs from the client-side Scryfall cache
  // joined against each seat's played-card totals. Lands excluded.
  const manaStatsFor = (seat: DeckPlayedManaSeat | undefined) =>
    playedManaStats(
      (seat?.cards ?? []).map((card) => ({
        display_name: card.display_name,
        type_category: card.type_category,
        count: card.times_played,
      })),
      manaCosts,
      seat?.turns,
    );
  const playerManaStats = manaStatsFor(detail.played_mana?.player);
  const opponentManaStats = manaStatsFor(detail.played_mana?.opponent);
  const manaCell = (value: number | null) => (value == null ? '—' : String(value));
  const playedManaRows: [string, string, string][] = [
    [
      'Mana value / card played',
      manaCell(playerManaStats.avg_per_card),
      manaCell(opponentManaStats.avg_per_card),
    ],
    ['Mana spent / turn', manaCell(playerManaStats.per_turn), manaCell(opponentManaStats.per_turn)],
  ];

  async function copyArenaDeck() {
    if (!deckExport?.available || !deckExport.text) {
      return;
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(deckExport.text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = deckExport.text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand('copy');
        textarea.remove();
        if (!copied) {
          throw new Error('Clipboard copy failed');
        }
      }
      setCopyStatus('copied');
      window.setTimeout(() => setCopyStatus('idle'), 1800);
    } catch {
      setCopyStatus('error');
    }
  }

  // Lives on the filter row (trailing slot), in line with Format/Period.
  const copyDeckButton = (
    <button
      className="deck-export-button"
      disabled={!deckExport?.available}
      onClick={() => void copyArenaDeck()}
      title={
        deckExport?.available
          ? 'Copy this deck in MTG Arena import format'
          : 'No exact submitted deck list has been captured yet'
      }
      type="button"
    >
      {copyStatus === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      {copyStatus === 'copied' ? 'Copied' : copyStatus === 'error' ? 'Copy Failed' : 'Copy Arena Deck'}
    </button>
  );

  const metrics = [
    { label: 'Games', value: String(detail.summary.games), icon: <Swords /> },
    { label: 'Record', value: `${detail.summary.wins}–${detail.summary.losses}`, icon: <Trophy /> },
    { label: 'Win Rate', value: formatPercent(detail.summary.win_rate), icon: <ChartNoAxesCombined /> },
    { label: 'On Play', value: formatPercent(detail.profile.on_play_pct), icon: <Play /> },
    { label: 'Avg Mulligans', value: formatNumber(detail.profile.avg_mulligans), icon: <RefreshCw /> },
    { label: 'Avg Turns', value: formatNumber(detail.profile.avg_turns), icon: <Repeat /> },
    { label: 'Avg Duration', value: formatDuration(detail.profile.avg_duration_seconds), icon: <Timer /> },
  ];

  // Best / worst opponent color: highest and lowest win rate; ties go to the
  // matchup with more games played (a bigger sample is the better trophy).
  const ratedColorRows = (detail.opponent_colors ?? []).filter(
    (row) => row.win_rate != null && row.games > 0,
  );
  const pickColorRow = (better: (a: OpponentColorRow, b: OpponentColorRow) => boolean) =>
    ratedColorRows.reduce<OpponentColorRow | null>(
      (winner, row) => (winner === null || better(row, winner) ? row : winner),
      null,
    );
  const bestVsColor =
    ratedColorRows.length >= 2
      ? pickColorRow(
          (a, b) =>
            (a.win_rate ?? 0) > (b.win_rate ?? 0) ||
            ((a.win_rate ?? 0) === (b.win_rate ?? 0) && a.games > b.games),
        )
      : null;
  const worstVsColor =
    ratedColorRows.length >= 2
      ? pickColorRow(
          (a, b) =>
            (a.win_rate ?? 0) < (b.win_rate ?? 0) ||
            ((a.win_rate ?? 0) === (b.win_rate ?? 0) && a.games > b.games),
        )
      : null;

  const interaction = detail.interaction_profile ?? null;
  /** Average cell: folds the drawn average into the played cell like the
      game page ("1.2 (2.3 drawn)"); opponent drawn averages are always
      null (hidden information) so their cells stay plain. */
  const interactionCell = (
    side: DeckInteractionSide | undefined,
    key: keyof DeckInteractionSide,
    drawnKey?: keyof DeckInteractionSide,
  ): ReactNode => {
    const value = side?.[key];
    if (value == null) {
      return '—';
    }
    if (key === 'land_replacement_pct') {
      return `${value}%`;
    }
    const drawn = drawnKey ? side?.[drawnKey] : null;
    // Drawn renders as a small muted no-wrap suffix so cells stay one line.
    return drawn != null ? withDrawnSuffix(value, drawn) : String(value);
  };
  const interactionGroups: {
    title: string;
    rows: [string, keyof DeckInteractionSide, (keyof DeckInteractionSide)?][];
  }[] = [
    {
      title: 'Attack',
      rows: [
        ['Attack steps', 'attack_steps'],
        ['Attacking creatures', 'attacking_creatures'],
        ['Attackers lost', 'attackers_lost'],
      ],
    },
    {
      title: 'Block',
      rows: [
        ['Blocking creatures', 'blocking_creatures'],
        ['Blockers lost', 'blockers_lost'],
      ],
    },
    {
      title: 'Life',
      rows: [
        ['Damage dealt', 'damage_dealt'],
        ['Damage taken', 'damage_taken'],
        ['Life lost', 'life_lost'],
        ['Self damage', 'self_damage'],
        ['Life gained', 'life_gained'],
        ['Poison counters added', 'poison_added'],
      ],
    },
    {
      title: 'Cards',
      rows: [
        ['Played', 'cards_played'],
        ['Drawn', 'cards_drawn'],
        ['Discarded', 'cards_discarded'],
        ['Milled', 'cards_milled'],
        ['Exiled', 'cards_exiled'],
      ],
    },
    {
      title: 'Removal',
      rows: [
        ['Removal played', 'removal_played', 'removal_drawn'],
        ['Board wipes played', 'wipes_played', 'wipes_drawn'],
        ['Creatures lost to removal', 'creatures_removed'],
        ['Non-creatures lost to removal', 'noncreatures_removed'],
      ],
    },
    {
      title: 'Bounce',
      rows: [
        ['Bounce cards played', 'bounces_played', 'bounces_drawn'],
        ['Creatures bounced to hand', 'creatures_bounced'],
        ['Non-creatures bounced to hand', 'noncreatures_bounced'],
      ],
    },
    {
      title: 'Land Destruction',
      rows: [
        ['Lands Destroyed', 'lands_lost'],
        ['Lands Successfully Replaced', 'lands_replaced'],
        ['Lands Lost To Destruction', 'lands_unreplaced'],
        ['Land Replacement Rate', 'land_replacement_pct'],
      ],
    },
    {
      title: 'Counter Magic',
      rows: [
        ['Counters played', 'counters_played', 'counters_drawn'],
        ['Counters successful', 'counters_landed'],
        ['Counters failed', 'counters_failed'],
      ],
    },
    {
      title: 'Tokens',
      rows: [
        ['Created', 'tokens_created'],
        ['Destroyed', 'tokens_destroyed'],
        ['Sacrificed', 'tokens_sacrificed'],
        ['Exiled', 'tokens_exiled'],
      ],
    },
  ];
  // Format rectangles: labels already carry the queue split (Ranked vs
  // Unranked, Best-of-1 vs Best-of-3, Competitive vs Casual Brawl).
  const formatCards = [...detail.formats].sort((a, b) => b.games - a.games);

  // Brawl decks: the commander IS the deck's face — it replaces the
  // signature card (the commander is card 100 and never appears in the
  // submitted-maindeck chart, so this callout is where it lives).
  const commanders = detail.commanders ?? [];
  const heroVisual =
    commanders.length > 0
      ? {
          card_id: null,
          card_name: commanders[0].card_name,
          type_category: 'Creature',
          image_url: commanderArtUrl(commanders[0].card_name),
          source: 'commander' as const,
        }
      : detail.deck_visual;

  return (
    <>
      {heroVisual.image_url ? (
        // Ambient backdrop from the deck's face card art: heavily blurred and
        // faded so it tints the page without fighting the content.
        <div
          aria-hidden="true"
          className="deck-art-backdrop"
          style={{ backgroundImage: `url(${heroVisual.image_url})` }}
        />
      ) : null}
      {refreshError ? (
        <p className="refresh-status refresh-status-error" role="alert">
          Refresh failed: {refreshError} — showing the last loaded data.
        </p>
      ) : null}
      <div className="deck-detail-header">
        <a className="back-link" href={backHref}>
          ← Back to dashboard
        </a>
        <div className="deck-detail-title deck-detail-title-hero">
          <DeckVisual deckName={detail.deck_name} size="large" visual={heroVisual} />
          <div className="deck-detail-title-content">
            <div>
              <h2>{detail.deck_name}</h2>
              <p>
                {commanders.length > 0 ? (
                  <>
                    Commander:{' '}
                    {commanders.map((commander, index) => (
                      <span key={commander.card_name}>
                        {index > 0 ? ' · ' : ''}
                        <CardLink cardName={commander.card_name} returnHash={`#/deck/${encodeURIComponent(detail.deck_name)}`}>
                          {formatCardName(commander.card_name)}
                        </CardLink>
                      </span>
                    ))}
                  </>
                ) : detail.deck_visual.card_name && detail.deck_visual.source === 'local_metadata' ? (
                  `Signature card: ${formatCardName(detail.deck_visual.card_name)}`
                ) : (
                  'No card data yet'
                )}
              </p>
              {detail.deck_colors ? (
                <div className="deck-color-pips">
                  <ColorPips colors={detail.deck_colors} size={22} />
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      {onFiltersChange ? (
        <FilterBar
          filters={filters}
          hideDeck
          trailing={copyDeckButton}
          onChange={onFiltersChange}
          options={{
            decks: [],
            formats: detail.formats.flatMap((format) =>
              (format.raw_formats ?? '')
                .split(',')
                .map((raw) => raw.trim())
                .filter(Boolean)
                .map((raw) => ({ raw_format: raw, format_label: format.format_label })),
            ),
          }}
        />
      ) : (
        <div className="filter-bar" role="group" aria-label="Deck actions">
          <div className="filter-bar-trailing">{copyDeckButton}</div>
        </div>
      )}

      <section className="metric-grid metric-grid-deck" aria-label="Deck metrics">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} icon={metric.icon} label={metric.label} value={metric.value} />
        ))}
      </section>

      {(detail.accounts ?? []).length > 1 ? (
        <p className="account-flag" title="This deck has tracked games from more than one Arena account">
          Played on {detail.accounts?.length} accounts:{' '}
          {detail.accounts?.map((account) => `${account.name} (${account.games})`).join(' · ')}
        </p>
      ) : null}

      <Section
        id="deck-combat"
        title="Combat Profile"
        description="Per-game combat and resource telemetry for this deck."
      >
        {detail.combat_profile || (detail.streaks?.games ?? 0) > 0 ? (
          <section className="metric-grid metric-grid-deck" aria-label="Deck combat metrics">
            {detail.streaks ? (
              <>
                <MetricCard
                  icon={<Flame />}
                  label="Win Streak"
                  value={formatNumber(detail.streaks.longest_win)}
                  detail={
                    detail.streaks.current?.kind === 'win'
                      ? `current: ${detail.streaks.current.length} in a row`
                      : 'longest'
                  }
                />
                <MetricCard
                  icon={<TrendingDown />}
                  label="Losing Streak"
                  value={formatNumber(detail.streaks.longest_loss)}
                  detail={
                    detail.streaks.current?.kind === 'loss'
                      ? `current: ${detail.streaks.current.length} in a row`
                      : 'longest'
                  }
                />
              </>
            ) : null}
            {detail.combat_profile ? (
              <>
                {/* Raw per-game averages live in Combat & Resources below;
                    this box keeps the deck-level identity and derived ratios. */}
                <MetricCard
                  icon={<Gauge />}
                  label="Profile"
                  value={detail.combat_profile.aggression_profile ?? '—'}
                />
                <MetricCard
                  icon={<Crosshair />}
                  label="Attackers / Attack"
                  value={formatNumber(detail.combat_profile.attackers_per_attack)}
                />
              </>
            ) : null}
          </section>
        ) : (
          <p className="empty-state">No combat telemetry recorded for this deck yet.</p>
        )}
      </Section>

      <Section
        id="deck-turn-timing"
        title="Turn Timing"
        description="Average pace across this deck's games."
      >
        {detail.turn_timing ? (
          <section className="metric-grid metric-grid-deck" aria-label="Deck turn timing">
            <MetricCard
              icon={<Timer />}
              label="Your Turn Time / Game"
              value={formatDuration(detail.turn_timing.player?.avg_total_seconds ?? null)}
            />
            <MetricCard
              icon={<Clock />}
              label="Your Avg Turn"
              value={formatTurnDuration(detail.turn_timing.player?.avg_turn_seconds ?? null)}
            />
            <MetricCard
              icon={<Hourglass />}
              label="Opponent Turn Time / Game"
              value={formatDuration(detail.turn_timing.opponent?.avg_total_seconds ?? null)}
            />
            <MetricCard
              icon={<Clock />}
              label="Opponent Avg Turn"
              value={formatTurnDuration(detail.turn_timing.opponent?.avg_turn_seconds ?? null)}
            />
          </section>
        ) : (
          <p className="empty-state">No turn timing recorded for this deck yet.</p>
        )}
      </Section>

      <Section
        id="deck-draw-quality"
        title="Draw Quality"
        description="Average cards and lands seen per game. The flood / screw / normal split lives in Land Statistics below."
      >
        {landProfile && landProfile.avg_cards_seen != null ? (
          <section className="metric-grid metric-grid-deck" aria-label="Deck draw quality">
            <MetricCard
              label="Cards Drawn / Game"
              value={formatNumber(landProfile.avg_cards_drawn)}
            />
            <MetricCard
              label="Cards Seen / Game"
              value={formatNumber(landProfile.avg_cards_seen)}
            />
            <MetricCard
              label="Lands Drawn / Game"
              value={landsWithPercent(landProfile.avg_lands_drawn, landProfile.lands_drawn_pct)}
            />
            <MetricCard
              label="Lands Seen / Game"
              value={landsWithPercent(landProfile.avg_lands_seen, landProfile.lands_seen_pct)}
            />
            <MetricCard
              label="Expected Lands / Game"
              value={landsWithPercent(
                landProfile.expected_lands_seen,
                landProfile.expected_land_pct != null && landProfile.expected_land_pct > 0
                  ? landProfile.expected_land_pct
                  : null,
              )}
            />
          </section>
        ) : (
          <p className="empty-state">No classified games for this deck yet.</p>
        )}
      </Section>

      <Section
        id="deck-interaction"
        title="Combat & Resources"
        description="Per-seat, per-game averages for this deck."
      >
        {interaction ? (
          <CombatGroupColumns
            columns={bucketCombatGroups(
              interactionGroups.map((group) => ({
                title: group.title,
                rows: [
                  ...group.rows.map(([label, key, drawnKey]): [string, ReactNode, ReactNode] => [
                    label,
                    interactionCell(interaction.player, key, drawnKey),
                    // Opponent draws are hidden information — no drawn suffix.
                    interactionCell(interaction.opponent, key),
                  ]),
                  ...(group.title === 'Cards' ? playedManaRows : []),
                ],
              })),
            )}
          />
        ) : (
          <p className="empty-state">No interaction telemetry recorded for this deck yet.</p>
        )}
      </Section>

      <Section
        id="deck-formats"
        title="Formats"
        description="This deck's record in every queue it has been played in."
      >
        {formatCards.length > 0 ? (
          <section className="metric-grid metric-grid-deck" aria-label="Deck format performance">
            {formatCards.map((row) => (
              <MetricCard
                key={row.format_label}
                icon={<Trophy />}
                label={boFormatLabel(row.format_label)}
                value={row.win_rate != null ? `${row.win_rate}%` : '—'}
                detail={`${row.wins}-${row.losses} · ${row.games} game${
                  row.games === 1 ? '' : 's'
                }`}
              />
            ))}
          </section>
        ) : (
          <p className="empty-state">No format data recorded for this deck yet.</p>
        )}
      </Section>

      <Section id="deck-trend" title="Win Rate Trend" description="Rolling win rate across this deck's finished games.">
        <div className="trend-wrap">
          <TrendChart rows={detail.trend} />
        </div>
      </Section>

      <Section
        id="deck-cards"
        title="Deck List & Card Performance"
        description={
          deckExport.available
            ? 'Latest captured main deck and sideboard counts, with tracked performance for each card.'
            : 'Tracked card performance. Exact deck counts are unavailable because no submitted deck list was captured.'
        }
      >
        {deckCountsKnown ? (
          <section className="metric-grid type-count-grid" aria-label="Main deck card type counts">
            {typeCounts.map((box) => (
              <MetricCard key={box.category} icon={box.icon} label={box.label} value={box.count} />
            ))}
          </section>
        ) : null}
        {commanders.length > 0 ? (
          <CommanderBanner
            commanders={commanders}
            returnHash={`#/deck/${encodeURIComponent(detail.deck_name)}`}
          />
        ) : null}
        <SortableTable
          caption="Deck list and card performance"
          columns={cardColumns}
          initialSort={{ key: 'type_category', direction: 'asc' }}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          rows={mainDeckRows}
          footerCells={
            deckCountsKnown ? { quantity: mainDeckTotal, display_name: 'Total' } : undefined
          }
        />
        {sideboardRows.length > 0 ? (
          <>
            <div className="section-heading">
              <div>
                <h3>Sideboard</h3>
              </div>
            </div>
            <SortableTable
              caption="Sideboard cards"
              columns={cardColumns}
              initialSort={{ key: 'type_category', direction: 'asc' }}
              getRowKey={(row) => `${row.display_name}-${row.type_category}`}
              rows={sideboardRows}
              footerCells={
                deckCountsKnown ? { quantity: sideboardTotal, display_name: 'Total' } : undefined
              }
            />
          </>
        ) : null}
      </Section>

      <Section id="deck-mulligans" title="Mulligans" description="Results grouped by how many times you mulliganed.">
        <SortableTable
          caption="Mulligan performance"
          columns={mulliganColumns}
          getRowKey={(row) => String(row.mulligans)}
          rows={detail.mulligans}
        />
      </Section>

      <Section
        id="deck-lands"
        title={landProfile ? 'Land Statistics' : 'Land Availability'}
        description={
          landProfile
            ? `Across ${landProfile.classified_games} classified games`
            : 'How often this deck had N lands by turn N, and the cost of falling behind.'
        }
      >
        {landProfile ? (
          <>
            <section className="metric-grid metric-grid-deck" aria-label="Land draw profile">
              <MetricCard
                label="Lands"
                value={
                  landProfile.lands !== null && landProfile.deck_size
                    ? `${landProfile.lands} / ${landProfile.deck_size}`
                    : '—'
                }
                detail={
                  landProfile.lands !== null && landProfile.deck_size
                    ? `${Math.round((100 * landProfile.lands) / landProfile.deck_size)}% of deck`
                    : undefined
                }
              />
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
                  How often this deck had N lands by turn N, and the cost of falling behind.
                </p>
              </div>
            </div>
          </>
        ) : null}
        <ManaReadinessTable caption="Deck land availability" rows={detail.mana_readiness ?? []} />
      </Section>

      <Section
        id="deck-opponent-colors"
        title="Vs Opponent Colors"
        description="This deck's record against each opponent color combination, inferred from every card they revealed."
      >
        {bestVsColor && worstVsColor ? (
          <div className="vs-color-highlights">
            <div className="vs-color-card vs-color-card-best">
              <span className="vs-color-card-label">Best Against</span>
              <span className="vs-color-card-value">
                <ColorPips colors={bestVsColor.colors} />
                <span className="vs-color-card-rate">{bestVsColor.win_rate}%</span>
              </span>
              <span className="vs-color-card-detail">
                {bestVsColor.color_label} · {bestVsColor.wins}-{bestVsColor.losses} in{' '}
                {bestVsColor.games} games
              </span>
            </div>
            <div className="vs-color-card vs-color-card-worst">
              <span className="vs-color-card-label">Worst Against</span>
              <span className="vs-color-card-value">
                <ColorPips colors={worstVsColor.colors} />
                <span className="vs-color-card-rate">{worstVsColor.win_rate}%</span>
              </span>
              <span className="vs-color-card-detail">
                {worstVsColor.color_label} · {worstVsColor.wins}-{worstVsColor.losses} in{' '}
                {worstVsColor.games} games
              </span>
            </div>
          </div>
        ) : null}
        <SortableTable
          caption="Record by opponent color combination"
          columns={deckOpponentColorColumns}
          getRowKey={(row) => row.color_label}
          initialSort={{ key: 'games', direction: 'desc' }}
          pageSize={10}
          paginationKey={deckName}
          rows={detail.opponent_colors ?? []}
        />
        {(detail.faced_commanders ?? []).length > 0 ? (
          <>
            <div className="section-heading">
              <div>
                <h3>Opponent Commanders</h3>
                <p className="section-description">
                  The commanders this deck has been paired against, and its record vs each.
                </p>
              </div>
            </div>
            <SortableTable
              caption="Record against opponent commanders with this deck"
              columns={deckFacedCommanderColumns}
              getRowKey={(row) => row.commander}
              initialSort={{ key: 'games', direction: 'desc' }}
              pageSize={10}
              paginationKey={`${deckName}-commanders`}
              rows={detail.faced_commanders ?? []}
            />
          </>
        ) : null}
      </Section>

      <Section
        id="deck-versions"
        title="Decklist Changes"
        description="Every distinct submitted maindeck, in play order, with its record and the diff against the previous version."
      >
        {(detail.versions ?? []).length > 0 ? (
          <SortableTable
            caption="Deck versions"
            columns={versionColumns}
            getRowKey={(row) => String(row.version)}
            initialSort={{ key: 'version', direction: 'asc' }}
            rows={versionsWithDelta(detail.versions ?? [])}
          />
        ) : (
          <p className="empty-state">No submitted decklists recorded for this deck yet.</p>
        )}
        {cutCards.length > 0 ? (
          <>
            <div className="section-heading">
              <div>
                <h3>Cut From Current List</h3>
                <p className="section-description">
                  Cards from earlier versions that are not in the current list, with the deck's record
                  while they were in it. The Deck List table and Arena export always reflect only the
                  current version.
                </p>
              </div>
            </div>
            <SortableTable
              caption="Cards cut from the current list"
              columns={cutCardColumns}
              getRowKey={(row) => row.display_name}
              initialSort={{ key: 'games_in_deck', direction: 'desc' }}
              rows={cutCards}
            />
          </>
        ) : null}
        {detail.sideboard ? (
          <>
            <div className="section-heading">
              <div>
                <h3>Sideboarding (Bo3)</h3>
                <p className="section-description">
                  Game 1 record vs post-sideboard record across {detail.sideboard.matches}{' '}
                  multi-game {detail.sideboard.matches === 1 ? 'match' : 'matches'}.
                </p>
              </div>
            </div>
            <section className="metric-grid metric-grid-deck" aria-label="Sideboard record">
              <MetricCard
                label="Game 1 Record"
                value={`${detail.sideboard.game_one.wins}-${detail.sideboard.game_one.losses}`}
              />
              <MetricCard
                label="Game 1 Win Rate"
                value={formatPercent(detail.sideboard.game_one.win_rate)}
              />
              <MetricCard
                label="Post-Board Record"
                value={`${detail.sideboard.post_board.wins}-${detail.sideboard.post_board.losses}`}
              />
              <MetricCard
                label="Post-Board Win Rate"
                value={formatPercent(detail.sideboard.post_board.win_rate)}
              />
            </section>
            {(detail.sideboard.swaps ?? []).length > 0 ? (
              <SortableTable
                caption="Sideboard swaps"
                columns={sideboardSwapColumns}
                getRowKey={(row) => row.display_name}
                initialSort={{ key: 'boarded_in', direction: 'desc' }}
                pageSize={10}
                rows={detail.sideboard.swaps ?? []}
              />
            ) : detail.sideboard.boarded_in.length > 0 ? (
              <p className="section-description">
                Most boarded in:{' '}
                {detail.sideboard.boarded_in
                  .map((card) => `${card.copies}x ${card.display_name}`)
                  .join(', ')}
              </p>
            ) : null}
          </>
        ) : null}
      </Section>

      <Section id="deck-games" title="Recent Games" description="Game length and average turn pace for both players.">
        <SortableTable
          caption="Recent games for this deck"
          columns={gameColumns}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          getRowKey={(row) => row.game_id}
          rows={detail.recent}
        />
      </Section>
    </>
  );
}
