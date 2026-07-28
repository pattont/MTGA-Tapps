import type { ManaReadinessRow } from '../api';
import { formatPercent } from '../dashboardData';
import { SortableTable, type Column } from './SortableTable';

const columns: Column<ManaReadinessRow>[] = [
  { key: 'label', header: 'Milestone' },
  { key: 'games', header: 'Games', numeric: true },
  {
    key: 'on_time_pct',
    header: 'On Time',
    render: (row) => formatPercent(row.on_time_pct),
    sortValue: (row) => row.on_time_pct,
    numeric: true,
  },
  {
    key: 'on_time_win_rate',
    header: 'WR On Time',
    render: (row) => formatPercent(row.on_time_win_rate),
    sortValue: (row) => row.on_time_win_rate,
    numeric: true,
  },
  {
    key: 'behind_games',
    header: 'Games Behind',
    numeric: true,
  },
  {
    key: 'behind_win_rate',
    header: 'WR Behind',
    render: (row) => formatPercent(row.behind_win_rate),
    sortValue: (row) => row.behind_win_rate,
    numeric: true,
  },
];

export function ManaReadinessTable({ rows, caption }: { rows: ManaReadinessRow[]; caption: string }) {
  if (!rows || rows.length === 0) {
    return <p className="empty-state">Not enough turn-tagged draw data yet.</p>;
  }
  return (
    <SortableTable
      caption={caption}
      columns={columns}
      getRowKey={(row) => String(row.threshold)}
      initialSort={{ key: 'label', direction: 'asc' }}
      rows={rows}
    />
  );
}
