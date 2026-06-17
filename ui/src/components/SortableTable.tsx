import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';
import { sortRows, type SortDirection } from '../sort';

export interface Column<T extends object> {
  key: keyof T;
  header: string;
  render?: (row: T) => ReactNode;
}

interface SortableTableProps<T extends object> {
  caption: string;
  columns: Column<T>[];
  rows: T[];
}

export function SortableTable<T extends object>({
  caption,
  columns,
  rows,
}: SortableTableProps<T>) {
  const [sortKey, setSortKey] = useState<keyof T>(columns[0].key);
  const [direction, setDirection] = useState<SortDirection>('asc');
  const sortedRows = useMemo(() => sortRows(rows, sortKey, direction), [direction, rows, sortKey]);

  function toggleSort(key: keyof T) {
    if (key === sortKey) {
      setDirection((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    setDirection('asc');
  }

  if (rows.length === 0) {
    return <p className="empty-state">No rows yet.</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={String(column.key)} scope="col">
                <button className="table-sort" type="button" onClick={() => toggleSort(column.key)}>
                  {column.header}
                  {sortKey === column.key ? <span aria-hidden="true">{direction === 'asc' ? ' ↑' : ' ↓'}</span> : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={String(column.key)}>{column.render ? column.render(row) : String(row[column.key] ?? '')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
