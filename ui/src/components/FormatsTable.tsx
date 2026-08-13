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

interface GroupedFormatRow extends FormatRow {
  sub_rows?: FormatRow[];
}

/**
 * Limited formats come per set ("Premier Draft - MSH", "Premier Draft - HOB").
 * The top level shows the plain format with aggregate record; each set is an
 * expandable sub-row, so a new set release doesn't add a top-level row.
 */
const LIMITED_BASES = [
  'Premier Draft',
  'Quick Draft',
  'Traditional Draft',
  'Traditional Sealed',
  'Sealed',
];

function limitedBase(label: string): string | null {
  for (const base of LIMITED_BASES) {
    if (label === base || label.startsWith(`${base} - `)) {
      return base;
    }
  }
  return null;
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, exported for tests
export function groupLimitedFormats(rows: FormatRow[]): GroupedFormatRow[] {
  const out: GroupedFormatRow[] = [];
  const groups = new Map<string, GroupedFormatRow>();
  for (const row of rows) {
    const base = limitedBase(row.format_label);
    if (!base) {
      out.push(row);
      continue;
    }
    let group = groups.get(base);
    if (!group) {
      group = {
        format_label: base,
        raw_formats: '',
        games: 0,
        wins: 0,
        losses: 0,
        win_rate: null,
        sub_rows: [],
      };
      groups.set(base, group);
      out.push(group);
    }
    group.games += row.games;
    group.wins += row.wins;
    group.losses += row.losses;
    group.raw_formats = [group.raw_formats, row.raw_formats].filter(Boolean).join(', ');
    const qualifier =
      row.format_label === base ? base : row.format_label.slice(base.length + 3).trim();
    group.sub_rows?.push({ ...row, format_label: qualifier || row.format_label });
  }
  for (const group of groups.values()) {
    const decided = group.wins + group.losses;
    group.win_rate = decided ? Math.round((1000 * group.wins) / decided) / 10 : null;
    group.sub_rows?.sort((a, b) => a.format_label.localeCompare(b.format_label));
  }
  return out;
}

interface FormatsTableProps {
  caption: string;
  rows: FormatRow[];
}

export function FormatsTable({ caption, rows }: FormatsTableProps) {
  const visibleRows = groupLimitedFormats(rows.filter(showInFormatAnalytics));
  return (
    <SortableTable
      caption={caption}
      columns={formatColumns}
      getRowKey={(row) => row.format_label}
      getSubRows={(row: GroupedFormatRow) => row.sub_rows}
      initialSort={{ key: 'format_label', direction: 'asc' }}
      rows={visibleRows}
    />
  );
}
