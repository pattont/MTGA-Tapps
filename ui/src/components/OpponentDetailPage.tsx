import { useEffect, useState } from 'react';
import { fetchOpponentDetail, type OpponentDetail, type OpponentGameRow } from '../api';
import { formatPercent } from '../dashboardData';
import { formatDateTime, formatDuration, formatNumber, outcomeLabel, outcomeTone } from '../format';
import { gameRouteHash, opponentRouteHash } from '../routes';
import { Badge } from './Badge';
import { DeckLink } from './DeckLink';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: OpponentDetail }
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
    key: 'deck_name',
    header: 'Your Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
  },
  { key: 'format_label', header: 'Format' },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => outcomeLabel(row.outcome),
  },
  { key: 'play_draw', header: 'Play / Draw' },
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

export function OpponentDetailPage({ opponentName }: { opponentName: string }) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    window.scrollTo(0, 0);
    const controller = new AbortController();
    void fetchOpponentDetail(opponentName, controller.signal)
      .then((detail) => setLoadState({ status: 'loaded', detail }))
      .catch((error: unknown) => {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          setLoadState({
            status: 'error',
            message: error instanceof Error ? error.message : 'Dashboard API failed',
          });
        }
      });
    return () => controller.abort();
  }, [opponentName]);

  if (loadState.status === 'loading') {
    return <p className="state-panel">Loading opponent history...</p>;
  }
  if (loadState.status === 'error') {
    return <p className="state-panel error-state">{loadState.message}</p>;
  }

  const { detail } = loadState;
  return (
    <>
      <div className="deck-detail-header" id="opponent-summary">
        <a className="back-link" href="#recent-games">← Back to dashboard</a>
        <div className="opponent-detail-title">
          <div>
            <p className="detail-eyebrow">HEAD-TO-HEAD</p>
            <h2>{detail.opponent_name}</h2>
            <p>Your tracked match history against this Arena player.</p>
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
          rows={detail.games}
        />
      </section>
    </>
  );
}
