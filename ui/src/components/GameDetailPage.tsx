import { useEffect, useState } from 'react';
import {
  fetchGameDetail,
  type GameDetail,
  type GameDrawnCardRow,
  type GameOpeningHandRow,
  type GamePlayedCardRow,
  type GameTurnTimingRow,
} from '../api';
import { formatPercent } from '../dashboardData';
import { formatDateTime, formatDuration, formatNumber, formatTurnDuration, outcomeLabel, outcomeTone } from '../format';
import { DeckLink } from './DeckLink';
import { Badge } from './Badge';
import { CardLink } from './CardLink';
import { LifeChart } from './LifeChart';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';
import { TimelineList } from './TimelineList';
import { TypeChip } from './TypeChip';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: GameDetail }
  | { status: 'error'; message: string };

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

const playedColumns: Column<GamePlayedCardRow>[] = [
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

function timingRoleLabel(role: GameTurnTimingRow['role']): string {
  if (role === 'player') {
    return 'You';
  }
  if (role === 'opponent') {
    return 'Opponent';
  }
  return 'Unknown';
}

function timingSourceLabel(source: string): string {
  return source === 'live' ? 'Live' : source === 'estimated_header_events' ? 'Estimated' : source;
}

const turnTimingColumns: Column<GameTurnTimingRow>[] = [
  { key: 'turn_number', header: 'Turn', numeric: true },
  {
    key: 'role',
    header: 'Player',
    render: (row) => timingRoleLabel(row.role),
    sortValue: (row) => timingRoleLabel(row.role),
  },
  {
    key: 'duration_seconds',
    header: 'Duration',
    render: (row) => <strong className="turn-duration-value">{formatTurnDuration(row.duration_seconds)}</strong>,
    sortValue: (row) => row.duration_seconds,
    numeric: true,
  },
  {
    key: 'timing_source',
    header: 'Timing',
    render: (row) => <Badge>{timingSourceLabel(row.timing_source)}</Badge>,
    sortValue: (row) => timingSourceLabel(row.timing_source),
  },
];

export function GameDetailPage({ gameId, backHref = '#overview' }: { gameId: string; backHref?: string }) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [gameId]);

  useEffect(() => {
    if (loadState.status === 'loaded') {
      document.title = `Game ${formatDateTime(loadState.detail.game.started_at)} – MTGA Tracker`;
    }
  }, [loadState]);

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
  }, [gameId]);

  if (loadState.status === 'loading') {
    return <p className="state-panel">Loading game details...</p>;
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
  const playDraw = detail.player.went_first === 1 ? 'On the play' : detail.player.went_first === 0 ? 'On the draw' : 'Unknown';
  const drawStatus = detail.draw_quality.total_draws === 0 ? 'No Draws' : detail.draw_quality.is_flood ? 'Flood' : 'Normal';
  const metricCards = [
    { label: 'Outcome', value: outcomeLabel(detail.game.outcome) },
    { label: 'Format', value: detail.game.format_label },
    { label: 'Play / Draw', value: playDraw },
    { label: 'Mulligans', value: formatNumber(detail.player.mulligans) },
    { label: 'Turns', value: formatNumber(detail.game.total_turns) },
    { label: 'Duration', value: formatDuration(detail.game.duration_seconds) },
    { label: 'Final Life', value: `${formatNumber(detail.player.ending_life)} / ${formatNumber(detail.opponent.ending_life)}` },
  ];
  return (
    <>
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
              {detail.draw_quality.is_flood ? <Badge tone="loss">Flood</Badge> : null}
            </div>
            <p>
              {detail.player.deck_name ? <DeckLink deckName={detail.player.deck_name} /> : 'Unknown deck'} ·{' '}
              {detail.game.format_label}
              {detail.game.best_of ? ` · Best-of-${detail.game.best_of}` : ''}
            </p>
          </div>
        </div>
      </div>

      <section className="metric-grid metric-grid-deck" aria-label="Game metrics">
        {metricCards.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} />
        ))}
      </section>

      <Section
        id="game-turn-timing"
        title="Turn Timing"
        description="Time spent on each player’s turns. Estimated rows come from historical turn-header timestamps; live rows were captured directly by the tracker."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Turn timing summary">
          <MetricCard label="Your Turn Time" value={formatTurnDuration(detail.turn_timing.player.total_seconds)} />
          <MetricCard label="Your Avg Turn" value={formatTurnDuration(detail.turn_timing.player.avg_seconds)} />
          <MetricCard label="Opponent Turn Time" value={formatTurnDuration(detail.turn_timing.opponent.total_seconds)} />
          <MetricCard label="Opponent Avg Turn" value={formatTurnDuration(detail.turn_timing.opponent.avg_seconds)} />
        </section>
        <SortableTable
          caption="Turn timing"
          columns={turnTimingColumns}
          getRowKey={(row) => row.turn_number}
          rows={detail.turns}
        />
      </Section>

      <Section
        id="game-draw-quality"
        title="Draw Quality"
        description="Post-opening draws. A game is marked Flood when more than 50% of total draws were identified as lands."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Game draw quality">
          <MetricCard label="Total Cards Drawn" value={formatNumber(detail.draw_quality.total_draws)} />
          <MetricCard label="Identified Draws" value={formatNumber(detail.draw_quality.identified_draws)} />
          <MetricCard label="Lands Drawn" value={formatNumber(detail.draw_quality.land_draws)} />
          <MetricCard label="Land Draw Percentage" value={formatPercent(detail.draw_quality.land_draw_pct)} />
          <MetricCard
            label="Draw Status"
            value={drawStatus}
            tone={detail.draw_quality.is_flood ? 'danger' : 'default'}
          />
        </section>
      </Section>

      <Section id="game-life" title="Life Totals" description="Life-total changes captured from the game timeline.">
        <div className="trend-wrap">
          <LifeChart points={detail.life_curve} />
        </div>
      </Section>

      <Section id="game-opening-hand" title="Opening Hand">
        <SortableTable
          caption="Opening hand"
          columns={openingColumns}
          getRowKey={(row) => `${row.hand_position}-${row.display_name}`}
          rows={detail.opening_hand}
        />
      </Section>

      <Section id="game-draws" title="Drawn Cards">
        <SortableTable
          caption="Drawn cards"
          columns={drawnColumns}
          getRowKey={(row) => `${row.draw_position}-${row.display_name}`}
          rows={detail.drawn}
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
        id="game-timeline"
        title="Timeline"
        description="Turn-by-turn play history captured from the tracker log."
      >
        <TimelineList rows={detail.timeline} />
      </Section>
    </>
  );
}
