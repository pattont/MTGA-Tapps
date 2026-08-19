import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Heart,
  Hourglass,
  Layers,
  Mountain,
  Play,
  RefreshCw,
  Repeat,
  Shield,
  Target,
  Timer,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  fetchGameDetail,
  type DeckChangeCard,
  type GameDetail,
  type GameDrawnCardRow,
  type GameOpeningHandRow,
  type GameParticipantStatsRow,
  type OpponentVisibleCardRow,
  type GamePlayedCardRow,
} from '../api';
import { saveGameAnnotation } from '../api';
import { pageTitle } from '../branding';
import { formatPercent } from '../dashboardData';
import { boFormatLabel, formatDateTime, formatDuration, formatNumber, formatTurnDuration, outcomeLabel, outcomeTone } from '../format';
import { gameRouteHash } from '../routes';
import { fetchManaCosts, playedManaStats, type CardManaInfo } from '../manaCosts';
import { DeckLink } from './DeckLink';
import { Badge } from './Badge';
import { bucketCombatGroups, CombatGroupColumns } from './CombatGroupColumns';
import { CardLink } from './CardLink';
import { ColorPips } from './ColorPips';
import { Section } from './Section';
import { LifeChart } from './LifeChart';
import { MetricCard } from './MetricCard';
import { OpponentLink } from './OpponentLink';
import { SortableTable, type Column } from './SortableTable';
import { TimelineList } from './TimelineList';
import { typeToneClass } from '../cardTypes';
import { TypeChip } from './TypeChip';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: GameDetail; refreshError?: string }
  | { status: 'error'; message: string };

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}


const openingColumns: Column<GameOpeningHandRow>[] = [
  { key: 'hand_position', header: '#', numeric: true },
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
  { key: 'copy_number', header: 'Copy', numeric: true },
];

const drawnColumns: Column<GameDrawnCardRow>[] = [
  {
    key: 'turn_number',
    header: 'Turn',
    render: (row) => formatNumber(row.turn_number),
    sortValue: (row) => row.turn_number,
    numeric: true,
  },
  { key: 'draw_position', header: '#', numeric: true },
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
];

const deckChangeColumns: Column<DeckChangeCard>[] = [
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
  {
    key: 'quantity',
    header: 'Copies',
    render: (row) => (row.quantity > 0 ? formatNumber(row.quantity) : '—'),
    sortValue: (row) => row.quantity,
    numeric: true,
  },
  {
    key: 'delta',
    header: 'Sideboard Change',
    render: (row) =>
      row.delta > 0 ? (
        <span className="deck-change-delta deck-change-delta-in">+{row.delta} in</span>
      ) : row.delta < 0 ? (
        <span className="deck-change-delta deck-change-delta-out">−{Math.abs(row.delta)} out</span>
      ) : (
        ''
      ),
    // Sort by magnitude so every changed card (in AND out) leads the table.
    sortValue: (row) => Math.abs(row.delta),
    numeric: true,
  },
];

/** Combat-stat cell: numbers/strings pass through, null/undefined show a dash. */
function formatStatCell(value: number | string | null | undefined): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return String(value);
}

function formatTurnList(turns: number[] | undefined): string {
  if (!turns || turns.length === 0) {
    return '—';
  }
  return turns.map((turn) => `T${turn}`).join(', ');
}

const playedColumns: Column<GamePlayedCardRow>[] = [
  {
    key: 'turns_played',
    header: 'Turn(s)',
    render: (row) => formatTurnList(row.turns_played),
    sortValue: (row) =>
      row.turns_played && row.turns_played.length > 0 ? row.turns_played[0] : Number.POSITIVE_INFINITY,
    numeric: true,
  },
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
  { key: 'played_count', header: 'Played', numeric: true },
];

const opponentCardColumns: Column<OpponentVisibleCardRow>[] = [
  {
    key: 'first_seen_turn',
    header: 'Revealed',
    render: (row) => (row.first_seen_turn != null ? `T${row.first_seen_turn}` : '—'),
    sortValue: (row) => row.first_seen_turn ?? Number.POSITIVE_INFINITY,
    numeric: true,
  },
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
  { key: 'played_count', header: 'Played', numeric: true },
  { key: 'drawn_count', header: 'Revealed Draws', numeric: true },
  { key: 'discarded_count', header: 'Discarded', numeric: true },
  { key: 'milled_count', header: 'Milled', numeric: true },
  { key: 'exiled_count', header: 'Exiled', numeric: true },
];

function isLandCard(card: { display_name: string; type_category: string }): boolean {
  return card.type_category.toLocaleLowerCase() === 'land' || card.display_name.trimEnd().endsWith('(Land)');
}

function longestLandRun(flags: boolean[]): number {
  let longest = 0;
  let current = 0;
  flags.forEach((isLand) => {
    current = isLand ? current + 1 : 0;
    longest = Math.max(longest, current);
  });
  return longest;
}

function maxLandsInEight(flags: boolean[]): number | null {
  if (flags.length < 8) {
    return null;
  }
  let maximum = 0;
  for (let index = 0; index <= flags.length - 8; index += 1) {
    maximum = Math.max(maximum, flags.slice(index, index + 8).filter(Boolean).length);
  }
  return maximum;
}

function calculateLowLandDrought(
  flags: Array<boolean | null>,
  openingLands: number,
): { draws: number; lands: number | null } {
  let landsSeen = openingLands;
  let current = 0;
  let longest = 0;
  let landsAtLongest: number | null = null;
  flags.forEach((isLand) => {
    if (isLand === true) {
      landsSeen += 1;
      current = 0;
    } else if (isLand === false && landsSeen <= 2) {
      current += 1;
      if (current > longest) {
        longest = current;
        landsAtLongest = landsSeen;
      }
    } else {
      current = 0;
    }
  });
  return { draws: longest, lands: landsAtLongest };
}

function formatWholePercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value)}%`;
}

export function GameDetailPage({
  gameId,
  backHref = '#overview',
  focusId,
}: {
  gameId: string;
  backHref?: string;
  focusId?: 'game-timeline' | null;
}) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [noteDraft, setNoteDraft] = useState('');
  const [tagsDraft, setTagsDraft] = useState('');
  const [noteStatus, setNoteStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [noteError, setNoteError] = useState<string | null>(null);
  const [, setAnnotationLoaded] = useState(false);
  // Keyed by game so navigating to another game resets to the first page
  // without needing an effect.
  const [drawTurnPageState, setDrawTurnPageState] = useState({ gameId, page: 0 });
  const drawTurnPage = drawTurnPageState.gameId === gameId ? drawTurnPageState.page : 0;
  const setDrawTurnPage = (page: number) => setDrawTurnPageState({ gameId, page });

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [gameId]);

  useEffect(() => {
    if (loadState.status === 'loaded') {
      document.title = pageTitle(`Game ${formatDateTime(loadState.detail.game.started_at)}`);
    }
  }, [loadState]);

  useEffect(() => {
    if (loadState.status === 'loaded' && focusId === 'game-timeline') {
      document.getElementById(focusId)?.scrollIntoView?.({ block: 'start' });
    }
  }, [focusId, loadState.status]);

  useEffect(() => {
    let ignore = false;
    let activeController: AbortController | null = null;

    async function loadDetail() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const detail = await fetchGameDetail(gameId, controller.signal);
        if (!ignore) {
          setLoadState({ status: 'loaded', detail });
          setAnnotationLoaded((alreadyLoaded) => {
            if (!alreadyLoaded) {
              setNoteDraft(detail.annotation?.note ?? '');
              setTagsDraft((detail.annotation?.tags ?? []).join(', '));
            }
            return true;
          });
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
  }, [gameId]);

  // Mana costs for both seats' played cards (client-side Scryfall cache)
  // feed the mana-value rows in Combat & Resources.
  const [manaCosts, setManaCosts] = useState<Map<string, CardManaInfo | null>>(() => new Map());
  const manaNamesKey =
    loadState.status === 'loaded'
      ? Array.from(
          new Set(
            [...loadState.detail.cards_played, ...loadState.detail.opponent_cards].map(
              (row) => row.display_name,
            ),
          ),
        ).join('\n')
      : '';
  useEffect(() => {
    if (!manaNamesKey) {
      return;
    }
    let cancelled = false;
    void fetchManaCosts(manaNamesKey.split('\n')).then((map) => {
      if (!cancelled) {
        setManaCosts(map);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [manaNamesKey]);

  if (loadState.status === 'loading') {
    return (
      <p className="state-panel" role="status" aria-busy="true">
        Loading game details...
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
  const playDraw = detail.player.went_first === 1 ? 'Play' : detail.player.went_first === 0 ? 'Draw' : 'Unknown';
  const landByPosition = new Map(detail.drawn.map((card) => [card.draw_position, isLandCard(card)]));
  const drawLandFlags = Array.from(
    { length: detail.draw_quality.total_draws },
    (_, index) => landByPosition.get(index + 1) ?? false,
  );
  const knownDrawLandFlags = Array.from(
    { length: detail.draw_quality.total_draws },
    (_, index) => landByPosition.get(index + 1) ?? null,
  );
  const longestLandStreak = detail.draw_quality.longest_land_streak ?? longestLandRun(drawLandFlags);
  const maxLandsInEightDraws = detail.draw_quality.max_lands_in_eight ?? maxLandsInEight(drawLandFlags);
  const openingLands = detail.draw_quality.opening_lands ?? detail.opening_hand.filter(isLandCard).length;
  const lowLandDroughtFallback = calculateLowLandDrought(knownDrawLandFlags, openingLands);
  const longestLowLandDrought =
    detail.draw_quality.longest_low_land_drought ?? lowLandDroughtFallback.draws;
  const lowLandDroughtLands =
    detail.draw_quality.low_land_drought_lands ?? lowLandDroughtFallback.lands;
  const totalCardsSeen =
    detail.draw_quality.total_cards_seen ?? detail.opening_hand.length + detail.draw_quality.total_draws;
  const landsSeen = detail.draw_quality.lands_seen ?? openingLands + detail.draw_quality.land_draws;
  const landSeenPct =
    detail.draw_quality.land_seen_pct ?? (totalCardsSeen ? (100 * landsSeen) / totalCardsSeen : null);
  const expectedLandRate = detail.draw_quality.expected_land_rate ?? 40;
  const expectedLandsSeen =
    detail.draw_quality.expected_lands_seen ?? (totalCardsSeen * expectedLandRate) / 100;
  const isFlood =
    detail.draw_quality.is_flood ||
    longestLandStreak >= 4 ||
    (maxLandsInEightDraws !== null && maxLandsInEightDraws >= 6);
  const fallbackFloodReasons = [
    ...(detail.draw_quality.land_draw_pct !== null &&
    detail.draw_quality.land_draw_pct > 50 &&
    detail.draw_quality.total_draws >= 6
      ? [
          `${detail.draw_quality.land_draws} of ${detail.draw_quality.total_draws} post-opening draws were lands`,
        ]
      : []),
    ...(longestLandStreak >= 4 ? [`${longestLandStreak} consecutive land draws`] : []),
    ...(maxLandsInEightDraws !== null && maxLandsInEightDraws >= 6
      ? [`${maxLandsInEightDraws} lands in an 8-draw window`]
      : []),
  ];
  const floodReasons =
    detail.draw_quality.flood_reasons && detail.draw_quality.flood_reasons.length > 0
      ? detail.draw_quality.flood_reasons
      : fallbackFloodReasons;
  const isScrew = Boolean(detail.draw_quality.is_screw) || longestLowLandDrought >= 3;
  const fallbackScrewReasons =
    longestLowLandDrought >= 3 && lowLandDroughtLands !== null
      ? [
          `${longestLowLandDrought} consecutive nonland draws while stuck on ${lowLandDroughtLands} ${
            lowLandDroughtLands === 1 ? 'land' : 'lands'
          }`,
        ]
      : [];
  const screwReasons =
    detail.draw_quality.screw_reasons && detail.draw_quality.screw_reasons.length > 0
      ? detail.draw_quality.screw_reasons
      : fallbackScrewReasons;
  const drawStatus =
    detail.draw_quality.total_draws === 0
      ? 'No Draws'
      : isFlood
        ? 'Flood'
        : isScrew
          ? 'Mana Screw'
          : 'Normal';
  const playerStats = detail.participant_stats.find((row) => row.role === 'player');
  const opponentStats = detail.participant_stats.find((row) => row.role === 'opponent');
  /** Display view: folds drawn counts into played cells and derives rates.
      Opponent drawn counts are hidden information, so their cells stay plain. */
  const buildStatsView = (
    stats: GameParticipantStatsRow | undefined,
    hideDrawn: boolean,
  ): Record<string, number | string | null | undefined> | null => {
    if (!stats) {
      return null;
    }
    const withDrawn = (
      played: number | null | undefined,
      drawn: number | null | undefined,
    ): number | string | null | undefined =>
      // NBSP keeps "(4 drawn)" together; the cell may wrap after the number
      // in narrow columns instead of overflowing the card.
      !hideDrawn && drawn != null ? `${played ?? 0} (${drawn}\u00A0drawn)` : played;
    const lost = stats.lands_lost;
    const replaced = stats.lands_replaced;
    return {
      ...stats,
      removal_played: withDrawn(stats.removal_played, stats.removal_drawn),
      wipes_played: withDrawn(stats.wipes_played, stats.wipes_drawn),
      bounces_played: withDrawn(stats.bounces_played, stats.bounces_drawn),
      counters_played: withDrawn(stats.counters_played, stats.counters_drawn),
      lands_unreplaced:
        lost != null && replaced != null ? Math.max(0, lost - replaced) : null,
      land_replacement_rate:
        lost != null && replaced != null && lost > 0
          ? `${Math.round((100 * replaced) / lost)}%`
          : null,
    };
  };
  const playerView = buildStatsView(playerStats, false);
  const opponentView = buildStatsView(opponentStats, true);
  // Successful counters BY a side are the OTHER side's spells that got
  // countered; failed = played minus successful (paid-through soft counters,
  // counter battles, fizzles — the outcome is all that matters).
  const attachCounterOutcomes = (
    view: Record<string, number | string | null | undefined> | null,
    ownStats: GameParticipantStatsRow | undefined,
    otherStats: GameParticipantStatsRow | undefined,
  ) => {
    if (!view) {
      return;
    }
    const successful = otherStats?.spells_countered;
    view.counters_successful = successful ?? null;
    const played = ownStats?.counters_played;
    view.counters_failed =
      typeof played === 'number' && typeof successful === 'number'
        ? Math.max(0, played - successful)
        : null;
  };
  attachCounterOutcomes(playerView, playerStats, opponentStats);
  attachCounterOutcomes(opponentView, opponentStats, playerStats);
  const combatGroups: { title: string; rows: [string, string][] }[] = [
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
        ['Removal played', 'removal_played'],
        ['Board wipes played', 'wipes_played'],
        ['Creatures lost to removal', 'creatures_removed'],
        ['Non-creatures lost to removal', 'noncreatures_removed'],
      ],
    },
    {
      title: 'Bounce',
      rows: [
        ['Bounce cards played', 'bounces_played'],
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
        ['Land Replacement Rate', 'land_replacement_rate'],
      ],
    },
    {
      title: 'Counter Magic',
      rows: [
        ['Counters played', 'counters_played'],
        ['Counters successful', 'counters_successful'],
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
  // Mana-value stats from printed costs (Scryfall) — lands excluded, X = 0.
  const playerManaStats = playedManaStats(
    detail.cards_played.map((row) => ({
      display_name: row.display_name,
      type_category: row.type_category,
      count: row.played_count,
    })),
    manaCosts,
    detail.game.player_turns,
  );
  const opponentManaStats = playedManaStats(
    detail.opponent_cards.map((row) => ({
      display_name: row.display_name,
      type_category: row.type_category,
      count: row.played_count,
    })),
    manaCosts,
    detail.game.opponent_turns,
  );
  const playedManaRows: [string, string, string][] = [
    [
      'Avg mana value / card played',
      formatStatCell(playerManaStats.avg_per_card),
      formatStatCell(opponentManaStats.avg_per_card),
    ],
    [
      'Mana spent / turn',
      formatStatCell(playerManaStats.per_turn),
      formatStatCell(opponentManaStats.per_turn),
    ],
  ];
  const mulliganHands = detail.mulligan_hands ?? [];
  async function saveAnnotation() {
    setNoteStatus('saving');
    try {
      const tags = tagsDraft
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean);
      const saved = await saveGameAnnotation(gameId, noteDraft.trim(), tags);
      setNoteDraft(saved.note);
      setTagsDraft(saved.tags.join(', '));
      setNoteStatus('saved');
      setNoteError(null);
    } catch (error: unknown) {
      setNoteError(error instanceof Error ? error.message : null);
      setNoteStatus('error');
    }
  }

  const drawsByTurnMap = new Map<number, { lands: number; nonlands: number }>();
  for (const row of detail.drawn) {
    if (row.turn_number === null || row.turn_number === undefined) {
      continue;
    }
    const bucket = drawsByTurnMap.get(row.turn_number) ?? { lands: 0, nonlands: 0 };
    if ((row.type_category ?? '').toLowerCase() === 'land' || row.display_name.endsWith('(Land)')) {
      bucket.lands += 1;
    } else {
      bucket.nonlands += 1;
    }
    drawsByTurnMap.set(row.turn_number, bucket);
  }
  const drawsByTurn = Array.from(drawsByTurnMap.entries())
    .sort(([a], [b]) => a - b)
    .map(([turn, counts]) => ({ turn, ...counts }));
  // Long games (hello, Brawl) page the draws-by-turn strip and table together,
  // ten turns at a time.
  const DRAW_TURNS_PER_PAGE = 10;
  const drawTurnPageCount = Math.max(1, Math.ceil(drawsByTurn.length / DRAW_TURNS_PER_PAGE));
  const activeDrawTurnPage = Math.min(drawTurnPage, drawTurnPageCount - 1);
  const drawTurnsPaged = drawTurnPageCount > 1;
  const visibleDrawTurnRows = drawTurnsPaged
    ? drawsByTurn.slice(
        activeDrawTurnPage * DRAW_TURNS_PER_PAGE,
        (activeDrawTurnPage + 1) * DRAW_TURNS_PER_PAGE,
      )
    : drawsByTurn;
  const visibleDrawTurns = new Set(visibleDrawTurnRows.map((row) => row.turn));
  const visibleDrawnRows = drawTurnsPaged
    ? detail.drawn.filter(
        (row) => row.turn_number === null || row.turn_number === undefined || visibleDrawTurns.has(row.turn_number),
      )
    : detail.drawn;
  const timelineReturnHash = gameRouteHash(gameId, backHref, 'game-timeline');
  // AI-identified archetype (dominant colors + strategy) overrides the plain
  // color label; the pips still show every color actually seen.
  const opponentDeckLabel = detail.opponent.deck_archetype ?? detail.opponent.color_label;
  const opponentDeckType = detail.opponent.colors ? (
    <span className="color-combo" title={detail.opponent.color_label ?? undefined}>
      <ColorPips colors={detail.opponent.colors} size={20} />
      {opponentDeckLabel}
    </span>
  ) : (
    detail.opponent.deck_archetype ?? 'Unknown'
  );
  const matchGames = detail.match_games ?? [];
  const matchWins = matchGames.filter((game) => game.outcome === 'win').length;
  const matchLosses = matchGames.filter((game) => game.outcome === 'loss').length;
  const matchOutcome = matchWins > matchLosses ? 'win' : matchLosses > matchWins ? 'loss' : 'split';
  const matchDurationSeconds = matchGames.reduce(
    (total, game) => total + (game.duration_seconds ?? 0),
    0,
  );
  const metricCards = [
    { label: 'Play / Draw', value: playDraw, icon: <Play /> },
    { label: 'Opponent Deck Type', value: opponentDeckType, icon: <Shield /> },
    { label: 'Mulligans', value: formatNumber(detail.player.mulligans), icon: <RefreshCw /> },
    { label: 'Turns', value: formatNumber(detail.game.total_turns), icon: <Repeat /> },
    { label: 'Duration', value: formatDuration(detail.game.duration_seconds), icon: <Timer /> },
    {
      label: 'Final Life',
      value: `${formatNumber(detail.player.ending_life)} / ${formatNumber(detail.opponent.ending_life)}`,
      icon: <Heart />,
    },
  ];
  return (
    <>
      {refreshError ? (
        <p className="refresh-status refresh-status-error" role="alert">
          Refresh failed: {refreshError} — showing the last loaded data.
        </p>
      ) : null}
      <div className="deck-detail-header" id="game-summary">
        <a className="back-link" href={backHref}>
          ← Back to dashboard
        </a>
        <div className="deck-detail-title">
          <div className={`game-outcome-mark game-outcome-${outcomeTone(detail.game.outcome)}`}>
            {outcomeLabel(detail.game.outcome)}
          </div>
          <div>
            <div className="game-title-row">
              <h2>Game {formatDateTime(detail.game.started_at)}</h2>
              {isFlood ? <Badge tone="draw">Flood</Badge> : null}
              {!isFlood && isScrew ? <Badge tone="screw">Mana Screw</Badge> : null}
            </div>
            <p>
              {detail.player.deck_name ? <DeckLink deckName={detail.player.deck_name} /> : 'Unknown deck'} ·{' '}
              {boFormatLabel(detail.game.format_label)}
              {detail.game.best_of && !detail.game.format_label.includes('Best-of')
                ? ` · BO${detail.game.best_of}`
                : ''}
              {(detail.game.game_number ?? 1) > 1 ? ` · Game ${detail.game.game_number}` : ''}
            </p>
            {detail.sideboard_changes ? (
              <p className="sideboard-changes">
                Sideboarded:{' '}
                {[
                  ...detail.sideboard_changes.added.map((entry) => `+${entry}`),
                  ...detail.sideboard_changes.removed.map((entry) => `−${entry}`),
                ].join(' · ')}
              </p>
            ) : null}
            {detail.opponent.display_name ? (
              <p>
                vs. <OpponentLink opponentName={detail.opponent.display_name} />
                {detail.multi_account && detail.player.display_name ? (
                  <span className="account-flag" title="This machine has games from more than one Arena account">
                    {' '}
                    · playing as {detail.player.display_name}
                  </span>
                ) : null}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {matchGames.length > 0 ? (
        <div className="match-strip" aria-label="BO3 match overview">
          <div className="match-strip-head">
            <Badge tone={matchOutcome === 'win' ? 'win' : matchOutcome === 'loss' ? 'loss' : 'draw'}>
              Match {matchOutcome === 'win' ? 'Win' : matchOutcome === 'loss' ? 'Loss' : 'Split'}
            </Badge>
            <span className="match-strip-record">
              {matchWins}–{matchLosses}
            </span>
            <span className="match-strip-desc">
              BO{detail.game.best_of ?? 3}
              {detail.opponent.display_name ? (
                <>
                  {' '}
                  vs <OpponentLink opponentName={detail.opponent.display_name} />
                </>
              ) : null}
              {' · '}
              {formatDuration(matchDurationSeconds)} total
            </span>
          </div>
          <div className="match-strip-games">
            {matchGames.map((game) => {
              const isCurrent = game.game_id === detail.game.game_id;
              const body = (
                <>
                  <span className="match-game-num">Game {game.game_number ?? '?'}</span>
                  <span className={`match-game-outcome match-game-outcome-${outcomeTone(game.outcome)}`}>
                    {outcomeLabel(game.outcome)}
                  </span>
                  <span className="match-game-meta">
                    {formatNumber(game.total_turns)} turns · {formatDuration(game.duration_seconds)}
                  </span>
                </>
              );
              return isCurrent ? (
                <span key={game.game_id} className="match-game-pill match-game-pill-current" aria-current="true">
                  {body}
                </span>
              ) : (
                <a key={game.game_id} className="match-game-pill" href={gameRouteHash(game.game_id, backHref)}>
                  {body}
                </a>
              );
            })}
          </div>
        </div>
      ) : null}

      <section className="metric-grid metric-grid-deck" aria-label="Game metrics">
        {metricCards.map((metric) => (
          <MetricCard key={metric.label} icon={metric.icon} label={metric.label} value={metric.value} />
        ))}
      </section>

      <Section
        id="game-turn-timing"
        title="Turn Timing"
        description="Average pace stays here. Individual turn durations are shown with each turn in the Timeline; estimated values come from historical turn headers."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Turn timing summary">
          <MetricCard icon={<Timer />} label="Your Turn Time" value={formatTurnDuration(detail.turn_timing.player.total_seconds)} />
          <MetricCard icon={<Clock />} label="Your Avg Turn" value={formatTurnDuration(detail.turn_timing.player.avg_seconds)} />
          <MetricCard icon={<Hourglass />} label="Opponent Turn Time" value={formatTurnDuration(detail.turn_timing.opponent.total_seconds)} />
          <MetricCard icon={<Clock />} label="Opponent Avg Turn" value={formatTurnDuration(detail.turn_timing.opponent.avg_seconds)} />
        </section>
      </Section>

      <Section
        id="game-draw-quality"
        title="Draw Quality"
        description="Flood tracks excess lands and concentrated land streaks. Mana screw tracks statistically low land access and three or more known nonland draws while stuck on one or two lands."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Game draw quality">
          {/* No icons here: nine cards per row leave no room — values would wrap. */}
          <MetricCard label="Total Cards Seen" value={formatNumber(totalCardsSeen)} />
          <MetricCard label="Lands Seen" value={`${landsSeen} (${formatWholePercent(landSeenPct)})`} />
          <MetricCard label="Total Cards Drawn" value={formatNumber(detail.draw_quality.total_draws)} />
          <MetricCard
            label="Lands Drawn"
            value={`${detail.draw_quality.land_draws} (${formatWholePercent(detail.draw_quality.land_draw_pct)})`}
          />
          <MetricCard label={`Expected Lands (${formatPercent(expectedLandRate)})`} value={expectedLandsSeen.toFixed(1)} />
          <MetricCard label="Longest Land Streak" value={formatNumber(longestLandStreak)} />
          <MetricCard
            label="Worst 8-Draw Window"
            value={maxLandsInEightDraws === null ? '—' : `${maxLandsInEightDraws} lands`}
          />
          <MetricCard
            label="Low-Land Drought"
            value={longestLowLandDrought ? `${longestLowLandDrought} draws` : '—'}
          />
          <MetricCard
            label="Draw Status"
            value={drawStatus}
            tone={isFlood ? 'info' : isScrew ? 'warning' : 'default'}
          />
        </section>
        {isFlood && floodReasons.length > 0 ? (
          <p className="draw-quality-reason">
            <Badge tone="draw">Flood evidence</Badge>
            <span>{floodReasons.join(' · ')}</span>
          </p>
        ) : null}
        {!isFlood && isScrew && screwReasons.length > 0 ? (
          <p className="draw-quality-reason">
            <Badge tone="screw">Mana Screw Evidence</Badge>
            <span>{screwReasons.join(' · ')}</span>
          </p>
        ) : null}
      </Section>

      <Section
        id="game-combat"
        title="Combat & Resources"
        description="Per-seat combat, damage, and resource totals recorded for this game."
      >
        {detail.participant_stats.length > 0 ? (
          <CombatGroupColumns
            columns={bucketCombatGroups(
              combatGroups.map((group) => ({
                title: group.title,
                rows: [
                  ...group.rows.map(([label, key]): [string, string, string] => [
                    label,
                    formatStatCell(playerView ? playerView[key] : null),
                    formatStatCell(opponentView ? opponentView[key] : null),
                  ]),
                  ...(group.title === 'Cards' ? playedManaRows : []),
                ],
              })),
            )}
          />
        ) : (
          <p className="empty-state">No combat telemetry recorded for this game.</p>
        )}
      </Section>

      <Section id="game-life" title="Life Totals" description="Life-total changes captured from the game timeline.">
        <div className="trend-wrap">
          <LifeChart points={detail.life_curve} />
        </div>
      </Section>

      {detail.deck_changes ? (
        <Section
          id="game-deck-changes"
          title="Deck w/ Changes"
          description={`The deck you took into this game after sideboarding, compared with the deck that started the match${
            detail.deck_changes.base_game_number > 1 ? ` (game ${detail.deck_changes.base_game_number})` : ''
          }. Draw-quality odds for this game use these numbers.`}
        >
          <section className="metric-grid metric-grid-deck" aria-label="Sideboarded deck numbers">
            <MetricCard
              icon={<Layers />}
              label="Deck Total"
              value={`${detail.deck_changes.deck_total}`}
              detail={
                detail.deck_changes.deck_total !== detail.deck_changes.base_deck_total
                  ? `was ${detail.deck_changes.base_deck_total}`
                  : 'unchanged'
              }
            />
            <MetricCard
              icon={<Mountain />}
              label="Lands"
              value={`${detail.deck_changes.lands}`}
              detail={
                detail.deck_changes.lands !== detail.deck_changes.base_lands
                  ? `was ${detail.deck_changes.base_lands}`
                  : 'unchanged'
              }
            />
            <MetricCard
              icon={<Target />}
              label="Land Density"
              value={
                detail.deck_changes.deck_total
                  ? `${((100 * detail.deck_changes.lands) / detail.deck_changes.deck_total).toFixed(1)}%`
                  : '—'
              }
              detail={
                detail.deck_changes.base_deck_total
                  ? `was ${((100 * detail.deck_changes.base_lands) / detail.deck_changes.base_deck_total).toFixed(1)}%`
                  : undefined
              }
            />
          </section>
          <SortableTable
            caption="Deck with sideboard changes"
            columns={deckChangeColumns}
            getRowKey={(row) => row.display_name}
            getRowClassName={(row) =>
              row.delta > 0
                ? 'deck-change-row deck-change-row-in'
                : row.delta < 0
                  ? 'deck-change-row deck-change-row-out'
                  : undefined
            }
            initialSort={{ key: 'delta', direction: 'desc' }}
            pageSize={15}
            rows={[...detail.deck_changes.cards, ...detail.deck_changes.removed]}
          />
        </Section>
      ) : null}

      <Section
        id="game-opening-hand"
        title="Opening Hand"
        description={
          mulliganHands.length > 0
            ? 'Every hand seen before keeping: mulliganed hands go back whole, and the final hand bottoms one card per mulligan.'
            : undefined
        }
      >
        {mulliganHands.length > 0 ? (
          <div className="mulligan-history">
            {mulliganHands.map((hand) => {
              const bottomedCount = hand.cards.filter((card) => card.bottomed).length;
              const kept = bottomedCount > 0;
              return (
                <div key={hand.hand_number} className="mulligan-hand">
                  <div className="mulligan-hand-head">
                    <span className="mulligan-hand-title">
                      {hand.hand_number === 1
                        ? 'Hand 1 — first seven'
                        : `Hand ${hand.hand_number} — after mulligan ${hand.hand_number - 1}`}
                    </span>
                    <span className={kept ? 'mulligan-hand-verdict mulligan-hand-kept' : 'mulligan-hand-verdict'}>
                      {kept
                        ? `Kept · bottomed ${bottomedCount} ${bottomedCount === 1 ? 'card' : 'cards'}`
                        : 'Mulliganed away'}
                    </span>
                  </div>
                  <ul className="mulligan-cards">
                    {hand.cards.map((card) => (
                      <li
                        key={`${hand.hand_number}-${card.hand_position}`}
                        className={`mulligan-card ${typeToneClass(card.type_category)}${
                          card.bottomed ? ' mulligan-card-bottomed' : ''
                        }`}
                      >
                        <CardLink cardName={card.display_name} />
                        {card.bottomed ? <span className="mulligan-card-note">bottomed</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
            <h4 className="mulligan-kept-title">Kept hand</h4>
          </div>
        ) : (detail.player.mulligans ?? 0) > 0 ? (
          <p className="mulligan-history-missing">
            This game was recorded before mulligan-history support, so only the kept hand below was saved.
          </p>
        ) : null}
        <SortableTable
          caption={mulliganHands.length > 0 ? 'Kept hand' : 'Opening hand'}
          columns={openingColumns}
          getRowKey={(row) => `${row.hand_position}-${row.display_name}`}
          rows={detail.opening_hand}
        />
      </Section>

      <Section id="game-draws" title="Drawn Cards">
        {visibleDrawTurnRows.length > 0 ? (
          <div className="draws-by-turn" aria-label="Draws by turn">
            {visibleDrawTurnRows.map(({ turn, lands, nonlands }) => (
              <div key={turn} className="draws-by-turn-cell">
                <span className="draws-by-turn-turn">T{turn}</span>
                <span className="draws-by-turn-counts">
                  {lands > 0 ? <span className="draws-by-turn-lands">{lands}L</span> : null}
                  {nonlands > 0 ? <span className="draws-by-turn-spells">{nonlands}S</span> : null}
                </span>
              </div>
            ))}
          </div>
        ) : null}
        {drawTurnsPaged ? (
          <nav className="table-pagination" aria-label="Drawn cards turn pagination">
            <p>
              Turns {visibleDrawTurnRows[0]?.turn}–{visibleDrawTurnRows[visibleDrawTurnRows.length - 1]?.turn} of{' '}
              {drawsByTurn[drawsByTurn.length - 1]?.turn}
            </p>
            <div className="table-pagination-controls">
              <button
                type="button"
                aria-label="Previous turns"
                title="Previous turns"
                disabled={activeDrawTurnPage === 0}
                onClick={() => setDrawTurnPage(activeDrawTurnPage - 1)}
              >
                <ChevronLeft aria-hidden="true" />
              </button>
              <span>
                Page {activeDrawTurnPage + 1} of {drawTurnPageCount}
              </span>
              <button
                type="button"
                aria-label="Next turns"
                title="Next turns"
                disabled={activeDrawTurnPage === drawTurnPageCount - 1}
                onClick={() => setDrawTurnPage(activeDrawTurnPage + 1)}
              >
                <ChevronRight aria-hidden="true" />
              </button>
            </div>
          </nav>
        ) : null}
        <SortableTable
          caption="Drawn cards"
          columns={drawnColumns}
          getRowKey={(row) => `${row.draw_position}-${row.display_name}`}
          rows={visibleDrawnRows}
        />
      </Section>

      <Section id="game-played" title="Cards Played">
        <SortableTable
          caption="Cards played"
          columns={playedColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          rows={detail.cards_played}
        />
      </Section>

      <Section
        id="game-opponent-cards"
        title="Opponent Revealed Cards"
        description="Every identified opponent card exposed through play, a visible draw, discard, mill, or exile."
      >
        <SortableTable
          caption="Opponent revealed cards"
          columns={opponentCardColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          initialSort={{ key: 'played_count', direction: 'desc' }}
          rows={detail.opponent_cards ?? []}
        />
      </Section>

      <Section
        id="game-notes"
        title="Notes & Tags"
        description="Your own notes for this game. Tags are comma-separated (e.g. misplay, flood, great game)."
      >
        <div className="annotation-editor">
          <label className="annotation-label">
            <span>Note</span>
            <textarea
              className="annotation-note"
              maxLength={4000}
              rows={3}
              value={noteDraft}
              onChange={(event) => {
                setNoteDraft(event.target.value);
                setNoteStatus('idle');
              }}
            />
          </label>
          <label className="annotation-label">
            <span>Tags</span>
            <input
              className="annotation-tags"
              placeholder="misplay, flood, great game"
              type="text"
              value={tagsDraft}
              onChange={(event) => {
                setTagsDraft(event.target.value);
                setNoteStatus('idle');
              }}
            />
          </label>
          <div className="annotation-actions">
            <button
              className="deck-export-button"
              disabled={noteStatus === 'saving'}
              type="button"
              onClick={() => void saveAnnotation()}
            >
              {noteStatus === 'saving' ? 'Saving…' : 'Save Notes'}
            </button>
            {noteStatus === 'saved' ? (
              <span className="annotation-status" role="status">
                Saved
              </span>
            ) : null}
            {noteStatus === 'error' ? (
              <span className="annotation-status annotation-status-error" role="alert">
                Save failed — {noteError || 'is the dashboard server running?'}
              </span>
            ) : null}
          </div>
        </div>
      </Section>

      <Section
        id="game-timeline"
        title="Timeline"
        description="Turn-by-turn play history captured from the tracker log."
      >
        <TimelineList
          cardReturnHash={timelineReturnHash}
          rows={detail.timeline}
          timings={detail.turns}
        />
        <div className={`timeline-end timeline-end-${detail.game.outcome ?? 'unknown'}`}>
          <strong>
            Game ended —{' '}
            {detail.game.outcome === 'win'
              ? 'You won'
              : detail.game.outcome === 'loss'
                ? 'You lost'
                : detail.game.outcome === 'draw'
                  ? 'Draw'
                  : 'Result unknown'}
          </strong>
          {detail.game.outcome_reason ? <span>{detail.game.outcome_reason}</span> : null}
          <span>
            {formatDuration(detail.game.duration_seconds)} · {formatNumber(detail.game.total_turns)}{' '}
            turns
          </span>
        </div>
      </Section>
    </>
  );
}
