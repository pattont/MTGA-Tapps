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

type OpponentGameOrMatchRow = OpponentGameRow & {
  /** True for a synthetic Bo3 match rollup row. */
  match_row?: boolean;
  /** "Game N" label on the per-game sub-rows of a match rollup. */
  game_label?: string;
  /** The games of a Bo3 match, nested under its rollup row. */
  sub_games?: OpponentGameOrMatchRow[];
};

/** Time of day only — the match rollup row already shows the date. */
function formatTimeOnly(value: string): string {
  const stamp = new Date(value);
  if (Number.isNaN(stamp.getTime())) {
    return formatDateTime(value);
  }
  return stamp.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function sumOrNull(values: Array<number | null | undefined>): number | null {
  const present = values.filter((value): value is number => value !== null && value !== undefined);
  return present.length ? present.reduce((total, value) => total + value, 0) : null;
}

/** Collapse each Bo3 match into one rollup row (you faced this opponent
    once), with the individual games nested beneath — the same shape the
    dashboard's Recent Games table uses. Bo1 games pass through untouched. */
function groupOpponentGames(rows: OpponentGameRow[]): OpponentGameOrMatchRow[] {
  const grouped: OpponentGameOrMatchRow[] = [];
  const matchRowByMatchId = new Map<string, OpponentGameOrMatchRow>();
  for (const row of rows) {
    const matchId = row.match_id;
    if (!matchId || (row.best_of ?? 1) <= 1) {
      grouped.push(row);
      continue;
    }
    const subRow: OpponentGameOrMatchRow = { ...row, game_label: `Game ${row.game_number ?? '?'}` };
    const existing = matchRowByMatchId.get(matchId);
    if (existing?.sub_games) {
      existing.sub_games.push(subRow);
      continue;
    }
    const matchRow: OpponentGameOrMatchRow = { ...row, match_row: true, sub_games: [subRow] };
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
    const last = games[games.length - 1];
    Object.assign(matchRow, {
      game_id: first?.game_id ?? matchRow.game_id,
      started_at: first?.started_at ?? matchRow.started_at,
      outcome: wins === losses ? matchRow.outcome : wins > losses ? 'win' : 'loss',
      duration_seconds: sumOrNull(games.map((game) => game.duration_seconds)),
      total_turns: sumOrNull(games.map((game) => game.total_turns)),
      player_final_life: last?.player_final_life ?? null,
      opponent_final_life: last?.opponent_final_life ?? null,
    });
  }
  return grouped;
}

const columns = (opponentName: string): Column<OpponentGameOrMatchRow>[] => [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) =>
      row.game_label ? (
        <a className="subrow-link" href={gameRouteHash(row.game_id, opponentRouteHash(opponentName))}>
          <span className="subrow-game-label">{row.game_label}</span>
          <span className="subrow-time">{formatTimeOnly(row.started_at)}</span>
        </a>
      ) : (
        <a className="table-link" href={gameRouteHash(row.game_id, opponentRouteHash(opponentName))}>
          {formatDateTime(row.started_at)}
        </a>
      ),
    sortValue: (row) => row.started_at,
  },
  {
    key: 'deck_colors',
    header: 'Your Colors',
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
    sortValue: (row) => outcomeLabel(row.outcome),
  },
  {
    key: 'play_draw',
    header: 'Play/Draw',
    render: (row) =>
      row.match_row ? null : row.play_draw === 'On the play' ? (
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
        {detail.summary.matches != null ? (
          <MetricCard
            label="Matches"
            value={formatNumber(detail.summary.matches)}
            detail={`${formatNumber(detail.summary.match_wins ?? 0)} – ${formatNumber(detail.summary.match_losses ?? 0)}`}
          />
        ) : null}
        <MetricCard label="Games" value={formatNumber(detail.summary.games)} />
        <MetricCard label="Wins" value={formatNumber(detail.summary.wins)} />
        <MetricCard label="Losses" value={formatNumber(detail.summary.losses)} />
        <MetricCard label="Win Rate" value={formatPercent(detail.summary.win_rate)} />
      </section>

      <section className="dashboard-section" id="opponent-games">
        <div className="section-heading">
          <div>
            <h3>Game History</h3>
            <p className="section-description">
              Every tracked pairing against this exact opponent name — a Bo3 match is one row,
              with its games nested beneath.
            </p>
          </div>
        </div>
        <SortableTable
          caption={`Games against ${detail.opponent_name}`}
          columns={columns(detail.opponent_name)}
          getRowKey={(row) => (row.match_row ? `match:${row.match_id}` : row.game_id)}
          getSubRows={(row) => row.sub_games}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          pageSize={15}
          rows={groupOpponentGames(detail.games)}
        />
      </section>
    </>
  );
}
