import { useEffect, useState } from 'react';
import {
  fetchGameDetail,
  type GameDetail,
  type GameDrawnCardRow,
  type GameOpeningHandRow,
  type GamePlayedCardRow,
  type GameTimelineRow,
} from '../api';
import { formatDateTime, formatDuration, formatNumber, outcomeLabel, outcomeTone } from '../format';
import { DeckLink } from './DeckLink';
import { CardLink } from './CardLink';
import { LifeChart } from './LifeChart';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';

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
  { key: 'type_category', header: 'Type' },
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
  { key: 'type_category', header: 'Type' },
];

const playedColumns: Column<GamePlayedCardRow>[] = [
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  { key: 'type_category', header: 'Type' },
  { key: 'played_count', header: 'Played', numeric: true },
];

const timelineColumns: Column<GameTimelineRow>[] = [
  {
    key: 'turn_number',
    header: 'Turn',
    render: (row) => formatNumber(row.turn_number),
    sortValue: (row) => row.turn_number,
    numeric: true,
  },
  {
    key: 'phase',
    header: 'Phase',
    render: (row) => row.phase ?? '—',
    sortValue: (row) => row.phase,
  },
  {
    key: 'event_type',
    header: 'Type',
    render: (row) => row.event_type ?? '—',
    sortValue: (row) => row.event_type,
  },
  {
    key: 'actor_role',
    header: 'Actor',
    render: (row) => row.actor_role ?? '—',
    sortValue: (row) => row.actor_role,
  },
  { key: 'text', header: 'Event' },
  {
    key: 'player_life',
    header: 'You',
    render: (row) => formatNumber(row.player_life),
    sortValue: (row) => row.player_life,
    numeric: true,
  },
  {
    key: 'opponent_life',
    header: 'Opp',
    render: (row) => formatNumber(row.opponent_life),
    sortValue: (row) => row.opponent_life,
    numeric: true,
  },
];

export function GameDetailPage({ gameId }: { gameId: string }) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [eventType, setEventType] = useState<string>('');

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
        <a className="back-link" href="#overview">
          ← Back to dashboard
        </a>
      </div>
    );
  }

  const { detail } = loadState;
  const playDraw = detail.player.went_first === 1 ? 'On the play' : detail.player.went_first === 0 ? 'On the draw' : 'Unknown';
  const metricCards = [
    { label: 'Outcome', value: outcomeLabel(detail.game.outcome) },
    { label: 'Format', value: detail.game.format_label },
    { label: 'Play / Draw', value: playDraw },
    { label: 'Mulligans', value: formatNumber(detail.player.mulligans) },
    { label: 'Turns', value: formatNumber(detail.game.total_turns) },
    { label: 'Duration', value: formatDuration(detail.game.duration_seconds) },
    { label: 'Final Life', value: `${formatNumber(detail.player.ending_life)} / ${formatNumber(detail.opponent.ending_life)}` },
  ];
  const eventTypes = Array.from(
    new Set(detail.timeline.map((row) => row.event_type).filter((value): value is string => Boolean(value))),
  ).sort();
  const filteredTimeline = eventType
    ? detail.timeline.filter((row) => row.event_type === eventType)
    : detail.timeline;

  return (
    <>
      <div className="deck-detail-header" id="game-summary">
        <a className="back-link" href="#overview">
          ← Back to dashboard
        </a>
        <div className="deck-detail-title">
          <div className={`game-outcome-mark game-outcome-${outcomeTone(detail.game.outcome)}`}>
            {outcomeLabel(detail.game.outcome)}
          </div>
          <div>
            <h2>Game {formatDateTime(detail.game.started_at)}</h2>
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

      <Section id="game-timeline" title="Timeline" description="Structured event history captured from the tracker log.">
        <div className="timeline-filter">
          <label>
            <span>Event Type</span>
            <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
              <option value="">All events</option>
              {eventTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
        </div>
        <SortableTable
          caption="Game timeline"
          columns={timelineColumns}
          getRowKey={(row) => `${row.turn_number ?? 'unknown'}-${row.event_type ?? 'event'}-${row.text}`}
          rows={filteredTimeline}
        />
      </Section>
    </>
  );
}
