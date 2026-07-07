import { useEffect, useState } from 'react';
import {
  fetchDeckDetail,
  type CardPerformanceRow,
  type DeckDetail,
  type DeckGameRow,
  type FormatRow,
  type MulliganRow,
  type OpeningHandRow,
  type SnapshotFilters,
} from '../api';
import { formatPercent } from '../dashboardData';
import { formatDateTime, formatDuration, formatNumber, outcomeLabel, outcomeTone } from '../format';
import { gameRouteHash } from '../routes';
import { Badge } from './Badge';
import { CardLink } from './CardLink';
import { DeckVisual } from './DeckVisual';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';
import { TrendChart } from './TrendChart';
import { WinRateBar } from './WinRateBar';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: DeckDetail }
  | { status: 'error'; message: string };

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

const cardColumns: Column<CardPerformanceRow>[] = [
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => row.type_category ?? 'Other',
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
    render: (row) => row.type_category ?? 'Other',
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

const formatColumns: Column<FormatRow>[] = [
  { key: 'format_label', header: 'Format' },
  {
    key: 'raw_format',
    header: 'Raw Queue',
    render: (row) => row.raw_format ?? '—',
    sortValue: (row) => row.raw_format,
  },
  { key: 'games', header: 'Games', numeric: true },
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
    header: 'Duration',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
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
          <div>
            <h2>{detail.deck_name}</h2>
            <p>
              {detail.deck_visual.card_name && detail.deck_visual.source === 'local_metadata'
                ? `Signature card: ${detail.deck_visual.card_name}`
                : 'No card data yet'}
            </p>
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
        title="Card Performance"
        description="Win rate in games where each card showed up (played, drawn, or otherwise seen)."
      >
        <SortableTable
          caption="Card performance"
          columns={cardColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          rows={detail.card_performance}
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
        <SortableTable
          caption="Format performance for this deck"
          columns={formatColumns}
          getRowKey={(row) => `${row.format_label}-${row.raw_format ?? 'unknown'}`}
          rows={detail.formats}
        />
      </Section>

      <Section id="deck-games" title="Recent Games">
        <SortableTable
          caption="Recent games for this deck"
          columns={gameColumns}
          getRowKey={(row) => row.game_id}
          rows={detail.recent}
        />
      </Section>
    </>
  );
}
