import { useEffect, useState } from 'react';
import { fetchOpponentDetail, type OpponentDetail, type OpponentGameRow, type SnapshotFilters } from '../api';
import { formatPercent } from '../dashboardData';
import { formatDateTime, formatDuration, formatNumber, outcomeLabel, outcomeTone, shortFormatLabel } from '../format';
import { gameRouteHash, opponentRouteHash } from '../routes';
import { Badge } from './Badge';
import { ColorPips } from './ColorPips';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: OpponentDetail; refreshError?: string }
  | { status: 'error'; message: string };

const columns = (opponentName: string): Column<OpponentGameRow>[] => [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => (
      <a className="table-link" href={gameRouteHash(row.game_id, opponentRouteHash(opponentName))}>
        {formatDateTime(row.started_at)}
      </a>
    ),
    sortValue: (row) => row.started_at,
  },
  {
    key: 'deck_colors',
    header: 'Your Colors',
    render: (row) => (row.deck_colors ? <ColorPips colors={row.deck_colors} /> : null),
    sortValue: (row) => row.deck_colors ?? '',
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
    sortValue: (row) => outcomeLabel(row.outcome),
  },
  {
    key: 'play_draw',
    header: 'Play/Draw',
    render: (row) =>
      row.play_draw === 'On the play' ? (
        <Badge tone="play">Play</Badge>
      ) : row.play_draw === 'On the draw' ? (
        <Badge tone="drawside">Draw</Badge>
      ) : null,
    sortValue: (row) => row.play_draw,
    center: true,
  },
  {
    key: 'duration_seconds',
    header: 'Duration',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
    numeric: true,
  },
  { key: 'total_turns', header: 'Turns', numeric: true },
  {
    key: 'player_final_life',
    header: 'Final Life',
    render: (row) => `${formatNumber(row.player_final_life)} / ${formatNumber(row.opponent_final_life)}`,
    sortValue: (row) => row.player_final_life,
    numeric: true,
  },
];

export function OpponentDetailPage({
  opponentName,
  filters = {},
}: {
  opponentName: string;
  filters?: SnapshotFilters;
}) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    window.scrollTo(0, 0);
    let ignore = false;
    let activeController: AbortController | null = null;

    async function load() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const detail = await fetchOpponentDetail(opponentName, filters, controller.signal);
        if (!ignore) {
          setLoadState({ status: 'loaded', detail });
        }
      } catch (error: unknown) {
        if (ignore || (error instanceof Error && error.name === 'AbortError')) {
          return;
        }
        const message = error instanceof Error ? error.message : 'Dashboard API failed';
        setLoadState((current) =>
          current.status === 'loaded'
            ? { ...current, refreshError: message }
            : { status: 'error', message },
        );
      }
    }

    void load();
    const refreshId = window.setInterval(() => {
      if (!document.hidden) {
        void load();
      }
    }, DETAIL_REFRESH_MS);
    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [opponentName, filters, retryToken]);

  if (loadState.status === 'loading') {
    return (
      <p className="state-panel" role="status" aria-busy="true">
        Loading opponent history...
      </p>
    );
  }
  if (loadState.status === 'error') {
    return (
      <div className="state-panel error-state" role="alert">
        <p>{loadState.message}</p>
        <button className="retry-button" type="button" onClick={() => setRetryToken((token) => token + 1)}>
          Retry
        </button>
      </div>
    );
  }

  const { detail } = loadState;
  return (
    <>
      {loadState.refreshError ? (
        <p className="refresh-status refresh-status-error" role="alert">
          Refresh failed: {loadState.refreshError} — showing the last loaded data.
        </p>
      ) : null}
      <div className="deck-detail-header" id="opponent-summary">
        <a className="back-link" href="#recent-games">← Back to dashboard</a>
        <div className="opponent-detail-title">
          <div>
            <p className="detail-eyebrow">Head-to-Head</p>
            <h2>{detail.opponent_name}</h2>
            <p className="detail-subtitle">Your tracked match history against this Arena player.</p>
          </div>
        </div>
      </div>

      <section className="metric-grid metric-grid-deck" aria-label="Opponent summary">
        <MetricCard label="Games" value={formatNumber(detail.summary.games)} />
        <MetricCard label="Wins" value={formatNumber(detail.summary.wins)} />
        <MetricCard label="Losses" value={formatNumber(detail.summary.losses)} />
        <MetricCard label="Win Rate" value={formatPercent(detail.summary.win_rate)} />
      </section>

      <section className="dashboard-section" id="opponent-games">
        <div className="section-heading">
          <div>
            <h3>Game History</h3>
            <p className="section-description">Every tracked game against this exact opponent name.</p>
          </div>
        </div>
        <SortableTable
          caption={`Games against ${detail.opponent_name}`}
          columns={columns(detail.opponent_name)}
          getRowKey={(row) => row.game_id}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          pageSize={15}
          rows={detail.games}
        />
      </section>
    </>
  );
}
