import { useEffect, useMemo, useState } from 'react';
import { fetchOpponents, type OpponentListRow } from '../api';
import { OpponentLink } from './OpponentLink';
import { Section } from './Section';
import { SortableTable, type Column } from './SortableTable';

function shortDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  return String(value).slice(0, 10);
}

const columns: Column<OpponentListRow>[] = [
  {
    key: 'opponent_name',
    header: 'Opponent',
    render: (row) => <OpponentLink opponentName={row.opponent_name} />,
    sortValue: (row) => row.opponent_name.toLowerCase(),
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => (row.win_rate == null ? '—' : `${row.win_rate}%`),
    sortValue: (row) => row.win_rate ?? -1,
    numeric: true,
  },
  {
    key: 'first_played',
    header: 'First Played',
    render: (row) => shortDate(row.first_played),
    sortValue: (row) => row.first_played ?? '',
    numeric: true,
  },
  {
    key: 'last_played',
    header: 'Last Played',
    render: (row) => shortDate(row.last_played),
    sortValue: (row) => row.last_played ?? '',
    numeric: true,
  },
];

export function OpponentsPage() {
  const [rows, setRows] = useState<OpponentListRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    let cancelled = false;
    fetchOpponents()
      .then((payload) => {
        if (!cancelled) {
          setRows(payload.opponents);
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : 'Failed to load opponents');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!rows) {
      return [];
    }
    const needle = search.trim().toLowerCase();
    if (!needle) {
      return rows;
    }
    return rows.filter((row) => row.opponent_name.toLowerCase().includes(needle));
  }, [rows, search]);

  return (
    <Section
      id="opponents-all"
      description="Everyone you've ever been paired against, with your record. Search a name — maybe you ran into an employee or a streamer without knowing it."
    >
      <div className="table-filter">
        <label className="filter-field">
          <span className="filter-field-label">Search</span>
          <input
            className="opponents-search"
            placeholder="Opponent name…"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        {rows ? (
          <span className="opponents-count">
            {filtered.length === rows.length
              ? `${rows.length} opponents`
              : `${filtered.length} of ${rows.length} opponents`}
          </span>
        ) : null}
      </div>
      {error ? (
        <p className="state-panel error-state" role="alert">
          {error}
        </p>
      ) : rows == null ? (
        <p className="state-panel">Loading opponents…</p>
      ) : (
        <SortableTable
          caption="All opponents faced"
          columns={columns}
          getRowKey={(row) => row.opponent_name}
          initialSort={{ key: 'games', direction: 'desc' }}
          pageSize={25}
          rows={filtered}
        />
      )}
    </Section>
  );
}
