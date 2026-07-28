import { useEffect, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import {
  fetchDeckDetail,
  type CardPerformanceRow,
  type DeckDetail,
  type DeckGameRow,
  type MulliganRow,
  type OpeningHandRow,
  type SnapshotFilters,
} from '../api';
import { formatPercent } from '../dashboardData';
import {
  formatCardName,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatTurnDuration,
  outcomeLabel,
  outcomeTone,
} from '../format';
import { gameRouteHash } from '../routes';
import { Badge } from './Badge';
import { CardLink } from './CardLink';
import { DeckVisual } from './DeckVisual';
import { FormatsTable } from './FormatsTable';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';
import { TrendChart } from './TrendChart';
import { TypeChip } from './TypeChip';
import { WinRateBar } from './WinRateBar';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: DeckDetail }
  | { status: 'error'; message: string };

type DeckListPerformanceRow = CardPerformanceRow & {
  quantity: number | null;
  deck_section: 'Main Deck' | 'Sideboard' | null;
};

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function cardNameAliases(cardName: string): Set<string> {
  const aliases = new Set([cardName]);
  cardName.split(' // ').forEach((name) => aliases.add(name.trim()));
  return aliases;
}

function deckListPerformanceRows(detail: DeckDetail): DeckListPerformanceRow[] {
  if (!detail.deck_export.available) {
    return detail.card_performance.map((row) => ({
      ...row,
      quantity: null,
      deck_section: null,
    }));
  }

  const performance = detail.card_performance.map((row) => ({
    row,
    aliases: cardNameAliases(row.display_name),
  }));
  return [
    ...detail.deck_export.main_deck.map((card) => ({ card, deck_section: 'Main Deck' as const })),
    ...detail.deck_export.sideboard.map((card) => ({ card, deck_section: 'Sideboard' as const })),
  ].map(({ card, deck_section }) => {
    const aliases = cardNameAliases(card.display_name);
    const matchingPerformance = performance.find(({ aliases: performanceAliases }) =>
      Array.from(aliases).some((name) => performanceAliases.has(name)),
    )?.row;
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
    };
  });
}

const cardColumns: Column<DeckListPerformanceRow>[] = [
  { key: 'quantity', header: 'Count', numeric: true },
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'deck_section',
    header: 'Section',
    render: (row) => row.deck_section ?? 'Unknown',
    sortValue: (row) => row.deck_section,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
  { key: 'games_seen', header: 'Games Seen', numeric: true },
  { key: 'times_played', header: 'Played', numeric: true },
  { key: 'times_drawn', header: 'Drawn', numeric: true },
  {
    key: 'win_rate_when_seen',
    header: 'Win Rate When Seen',
    render: (row) => (
      <WinRateBar losses={row.losses_when_seen} winRate={row.win_rate_when_seen} wins={row.wins_when_seen} />
    ),
    sortValue: (row) => row.win_rate_when_seen,
    numeric: true,
  },
];

const openerColumns: Column<OpeningHandRow>[] = [
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
  { key: 'games_in_opener', header: 'Games In Opener', numeric: true },
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
  { key: 'format_label', header: 'Format' },
  {
    key: 'play_draw',
    header: 'Play / Draw',
    render: (row) => row.play_draw ?? 'Unknown',
    sortValue: (row) => row.play_draw,
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

export function DeckDetailPage({
  backHref = '#overview',
  deckName,
  filters = {},
}: {
  backHref?: string;
  deckName: string;
  filters?: SnapshotFilters;
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
          setLoadState((current) => (current.status === 'loaded' ? current : { status: 'error', message }));
        }
      }
    }

    void loadDetail();
    const refreshId = window.setInterval(() => {
      void loadDetail();
    }, DETAIL_REFRESH_MS);

    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [deckName, filters]);

  if (loadState.status === 'loading') {
    return <p className="state-panel">Loading deck details...</p>;
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

  const { detail } = loadState;
  const deckExport = detail.deck_export;
  const cardRows = deckListPerformanceRows(detail);

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

  const metrics = [
    { label: 'Games', value: String(detail.summary.games) },
    { label: 'Record', value: `${detail.summary.wins}–${detail.summary.losses}` },
    { label: 'Win Rate', value: formatPercent(detail.summary.win_rate) },
    { label: 'On Play', value: formatPercent(detail.profile.on_play_pct) },
    { label: 'Avg Mulligans', value: formatNumber(detail.profile.avg_mulligans) },
    { label: 'Avg Turns', value: formatNumber(detail.profile.avg_turns) },
    { label: 'Avg Duration', value: formatDuration(detail.profile.avg_duration_seconds) },
  ];

  return (
    <>
      <div className="deck-detail-header">
        <a className="back-link" href={backHref}>
          ← Back to dashboard
        </a>
        <div className="deck-detail-title">
          <DeckVisual deckName={detail.deck_name} visual={detail.deck_visual} />
          <div className="deck-detail-title-content">
            <div>
              <h2>{detail.deck_name}</h2>
              <p>
                {detail.deck_visual.card_name && detail.deck_visual.source === 'local_metadata'
                  ? `Signature card: ${formatCardName(detail.deck_visual.card_name)}`
                  : 'No card data yet'}
              </p>
            </div>
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
          </div>
        </div>
      </div>

      <section className="metric-grid metric-grid-deck" aria-label="Deck metrics">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} />
        ))}
      </section>

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
        <SortableTable
          caption="Deck list and card performance"
          columns={cardColumns}
          initialSort={{ key: 'deck_section', direction: 'asc' }}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          rows={cardRows}
        />
      </Section>

      <Section
        id="deck-openers"
        title="Opening Hands"
        description="How games went when a card was in your opening hand."
      >
        <SortableTable
          caption="Opening hand performance"
          columns={openerColumns}
          initialSort={{ key: 'games_in_opener', direction: 'desc' }}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          rows={detail.opening_hands}
        />
      </Section>

      <Section id="deck-mulligans" title="Mulligans" description="Results grouped by how many times you mulliganed.">
        <SortableTable
          caption="Mulligan performance"
          columns={mulliganColumns}
          getRowKey={(row) => String(row.mulligans)}
          rows={detail.mulligans}
        />
      </Section>

      <Section id="deck-formats" title="Formats">
        <FormatsTable caption="Format performance for this deck" rows={detail.formats} />
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
