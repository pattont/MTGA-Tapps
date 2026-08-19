import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { Fragment, useMemo, useState } from 'react';
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
  /**
   * Rows nested under a parent row (e.g. the games of a Bo3 match). A parent
   * with sub-rows gets an expander chevron in its first cell; sub-rows render
   * beneath it, excluded from sorting and pagination counts.
   */
  getSubRows?: (row: T) => T[] | null | undefined;
  /**
   * Full-width detail content for a row (e.g. a Brawl game's commander
   * matchup). A row with detail gets the same expander chevron; the detail
   * renders in one cell spanning every column.
   */
  renderDetailRow?: (row: T) => ReactNode | null | undefined;
  /** Extra class for a row's <tr>, e.g. to highlight changed rows. */
  getRowClassName?: (row: T) => string | undefined;
  /**
   * Totals row rendered in a <tfoot>, keyed by column key — e.g.
   * `{ display_name: 'Total', quantity: 60 }`. Unkeyed columns stay empty.
   * Always reflects the FULL row set (sorting and pagination don't move it).
   */
  footerCells?: Partial<Record<string, ReactNode>>;
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
  getSubRows,
  renderDetailRow,
  getRowClassName,
  footerCells,
}: SortableTableProps<T>) {
  const [expandedKeys, setExpandedKeys] = useState<Set<string | number>>(() => new Set());

  function toggleExpanded(key: string | number) {
    setExpandedKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }
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


  if (rows.length === 0 || columns.length === 0) {
    return <p className="empty-state">No rows yet.</p>;
  }

  return (
    <div className={isPaginated ? 'table-container table-container-paginated' : 'table-container'}>
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
            {visibleRows.map((row) => {
              const rowKey = getRowKey(row);
              const subRows = getSubRows?.(row) ?? null;
              const detail = renderDetailRow?.(row) ?? null;
              const expandable = Boolean((subRows && subRows.length > 0) || detail);
              const expanded = expandable && expandedKeys.has(rowKey);
              const rowClasses = [
                expandable ? 'table-row-expandable' : null,
                expanded ? 'table-row-expanded' : null,
                getRowClassName?.(row) ?? null,
              ]
                .filter(Boolean)
                .join(' ');
              return (
                <Fragment key={rowKey}>
                  <tr className={rowClasses || undefined}>
                    {columns.map((column, columnIndex) => (
                      <td key={String(column.key)} className={column.numeric ? 'num' : undefined}>
                        {columnIndex === 0 && expandable ? (
                          <span className="row-expander-cell">
                            <button
                              aria-expanded={expanded}
                              aria-label={expanded ? 'Hide match games' : 'Show match games'}
                              className="row-expander"
                              type="button"
                              onClick={() => toggleExpanded(rowKey)}
                            >
                              {expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
                            </button>
                            {column.render ? column.render(row) : String(row[column.key] ?? '')}
                          </span>
                        ) : column.render ? (
                          column.render(row)
                        ) : (
                          String(row[column.key] ?? '')
                        )}
                      </td>
                    ))}
                  </tr>
                  {expanded && detail ? (
                    <tr className="table-subrow table-detail-row">
                      <td colSpan={columns.length}>{detail}</td>
                    </tr>
                  ) : null}
                  {expanded && subRows
                    ? subRows.map((subRow) => (
                        <tr key={getRowKey(subRow)} className="table-subrow">
                          {columns.map((column) => (
                            <td key={String(column.key)} className={column.numeric ? 'num' : undefined}>
                              {column.render ? column.render(subRow) : String(subRow[column.key] ?? '')}
                            </td>
                          ))}
                        </tr>
                      ))
                    : null}
                </Fragment>
              );
            })}
          </tbody>
          {footerCells ? (
            <tfoot>
              <tr className="table-footer-row">
                {columns.map((column) => (
                  <td key={String(column.key)} className={column.numeric ? 'num' : undefined}>
                    {footerCells[String(column.key)] ?? ''}
                  </td>
                ))}
              </tr>
            </tfoot>
          ) : null}
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
