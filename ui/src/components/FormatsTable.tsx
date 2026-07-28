import type { FormatRow } from '../api';
import { showInFormatAnalytics } from '../formatVisibility';
import { SortableTable, type Column } from './SortableTable';
import { WinRateBar } from './WinRateBar';

const formatColumns: Column<FormatRow>[] = [
  {
    key: 'format_label',
    header: 'Format',
    // Raw queue identifiers stay out of the UI but remain inspectable in the DOM.
    render: (row) => (
      <span className="format-label" data-raw-queues={row.raw_formats} title={`Raw queues: ${row.raw_formats}`}>
        {row.format_label}
      </span>
    ),
    sortValue: (row) => row.format_label,
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

interface FormatsTableProps {
  caption: string;
  rows: FormatRow[];
}

export function FormatsTable({ caption, rows }: FormatsTableProps) {
  const visibleRows = rows.filter(showInFormatAnalytics);
  return (
    <SortableTable
      caption={caption}
      columns={formatColumns}
      getRowKey={(row) => row.format_label}
      initialSort={{ key: 'format_label', direction: 'asc' }}
      rows={visibleRows}
    />
  );
}
