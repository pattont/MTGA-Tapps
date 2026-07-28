import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';
import { sortRows, type SortDirection } from '../sort';

interface StoredSort {
  key: string;
  direction: SortDirection;
}

function readStoredSort(caption: string): StoredSort | null {
  try {
    const raw = sessionStorage.getItem(`mtga-table-sort:${caption}`);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as StoredSort;
    if (typeof parsed?.key === 'string' && (parsed.direction === 'asc' || parsed.direction === 'desc')) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function storeSort(caption: string, sort: StoredSort): void {
  try {
    sessionStorage.setItem(`mtga-table-sort:${caption}`, JSON.stringify(sort));
  } catch {
    // Persistence is best-effort only.
  }
}

type SortValue = string | number | boolean | null | undefined;

export interface Column<T extends object> {
  key: keyof T;
  header: string;
  render?: (row: T) => ReactNode;
  sortValue?: (row: T) => SortValue;
  sortable?: boolean;
  numeric?: boolean;
}

export interface InitialSort<T extends object> {
  key: keyof T;
  direction: SortDirection;
}

interface SortableTableProps<T extends object> {
  caption: string;
  columns: Column<T>[];
  compact?: boolean;
  getRowKey: (row: T) => string | number;
  rows: T[];
  initialSort?: InitialSort<T>;
  pageSize?: number;
  paginationKey?: string | number;
}

export function SortableTable<T extends object>({
  caption,
  columns,
  compact = false,
  getRowKey,
  rows,
  initialSort,
  pageSize,
  paginationKey = '',
}: SortableTableProps<T>) {
  const sortableColumns = useMemo(() => columns.filter((column) => column.sortable !== false), [columns]);
  const firstSortableKey = sortableColumns[0]?.key ?? null;
  const [sortKey, setSortKey] = useState<keyof T | null>(() => {
    const stored = readStoredSort(caption);
    if (stored && columns.some((column) => String(column.key) === stored.key)) {
      return stored.key as keyof T;
    }
    return initialSort?.key ?? firstSortableKey;
  });
  const [direction, setDirection] = useState<SortDirection>(() => {
    const stored = readStoredSort(caption);
    if (stored && columns.some((column) => String(column.key) === stored.key)) {
      return stored.direction;
    }
    return initialSort?.direction ?? 'asc';
  });
  const [pagination, setPagination] = useState({ key: paginationKey, page: 1 });
  const requestedSortColumn = sortableColumns.find((column) => column.key === sortKey) ?? null;
  const activeSortColumn = requestedSortColumn ?? sortableColumns[0] ?? null;
  const activeDirection = requestedSortColumn ? direction : 'asc';

  const sortedRows = useMemo(() => {
    if (!activeSortColumn) {
      return rows;
    }
    if (activeSortColumn.sortValue) {
      return sortRows(
        rows.map((row) => ({ row, value: activeSortColumn.sortValue?.(row) })),
        'value',
        activeDirection,
      ).map(({ row }) => row);
    }
    return sortRows(rows, activeSortColumn.key, activeDirection);
  }, [activeDirection, activeSortColumn, rows]);
  const pageCount = pageSize ? Math.max(1, Math.ceil(sortedRows.length / pageSize)) : 1;
  const requestedPage = pagination.key === paginationKey ? pagination.page : 1;
  const activePage = Math.min(requestedPage, pageCount);
  const pageStart = pageSize ? (activePage - 1) * pageSize : 0;
  const visibleRows = pageSize ? sortedRows.slice(pageStart, pageStart + pageSize) : sortedRows;
  const isPaginated = Boolean(pageSize && sortedRows.length > pageSize);

  function toggleSort(key: keyof T) {
    setPagination({ key: paginationKey, page: 1 });
    if (key === activeSortColumn?.key) {
      const nextDirection = activeDirection === 'asc' ? 'desc' : 'asc';
      setSortKey(key);
      setDirection(nextDirection);
      storeSort(caption, { key: String(key), direction: nextDirection });
      return;
    }
    setSortKey(key);
    setDirection('asc');
    storeSort(caption, { key: String(key), direction: 'asc' });
  }

  function changePage(page: number) {
    setPagination({ key: paginationKey, page: Math.min(Math.max(page, 1), pageCount) });
  }

  function exportCsv() {
    const header = columns.map((column) => csvCell(column.header)).join(',');
    const lines = sortedRows.map((row) =>
      columns
        .map((column) => csvCell(column.sortValue ? column.sortValue(row) : row[column.key]))
        .join(','),
    );
    const blob = new Blob([`${header}\n${lines.join('\n')}\n`], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${caption.toLocaleLowerCase().replaceAll(/[^a-z0-9]+/g, '-')}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  if (rows.length === 0 || columns.length === 0) {
    return <p className="empty-state">No rows yet.</p>;
  }

  return (
    <div className={isPaginated ? 'table-container table-container-paginated' : 'table-container'}>
      <div className="table-toolbar">
        <button
          type="button"
          className="table-export"
          aria-label="Download CSV"
          title={`Download all rows of “${caption}” as CSV`}
          onClick={exportCsv}
        >
          Download CSV
        </button>
      </div>
      <div
        className={compact ? 'table-wrap table-wrap-compact' : 'table-wrap'}
        role="region"
        aria-label={caption}
        tabIndex={0}
      >
        <table>
          <caption>{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => {
                const isSortable = column.sortable !== false;
                const isActive = activeSortColumn?.key === column.key;
                const ariaSort = isActive ? (activeDirection === 'asc' ? 'ascending' : 'descending') : 'none';

                return (
                  <th
                    key={String(column.key)}
                    scope="col"
                    aria-sort={ariaSort}
                    className={column.numeric ? 'num' : undefined}
                  >
                    {isSortable ? (
                      <button
                        className={isActive ? 'table-sort table-sort-active' : 'table-sort'}
                        type="button"
                        onClick={() => toggleSort(column.key)}
                      >
                        {column.header}
                        <span className="table-sort-icon" aria-hidden="true">
                          {isActive ? (activeDirection === 'asc' ? '↑' : '↓') : '↕'}
                        </span>
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={getRowKey(row)}>
                {columns.map((column) => (
                  <td key={String(column.key)} className={column.numeric ? 'num' : undefined}>
                    {column.render ? column.render(row) : String(row[column.key] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {isPaginated ? (
        <nav className="table-pagination" aria-label={`${caption} pagination`}>
          <p>
            Showing {pageStart + 1}-{Math.min(pageStart + (pageSize ?? 0), sortedRows.length)} of {sortedRows.length}
          </p>
          <div className="table-pagination-controls">
            <button
              type="button"
              aria-label="Previous page"
              title="Previous page"
              disabled={activePage === 1}
              onClick={() => changePage(activePage - 1)}
            >
              <ChevronLeft aria-hidden="true" />
            </button>
            <span>
              Page {activePage} of {pageCount}
            </span>
            <button
              type="button"
              aria-label="Next page"
              title="Next page"
              disabled={activePage === pageCount}
              onClick={() => changePage(activePage + 1)}
            >
              <ChevronRight aria-hidden="true" />
            </button>
          </div>
        </nav>
      ) : null}
    </div>
  );
}
