import { useEffect, useMemo, useState } from 'react';
import {
  fetchAllGames,
  type AllGamesResponse,
  type AllGamesRow,
  type SnapshotFilters,
} from '../api';
import { colorComboLabel } from '../colorCombos';
import { formatDateTime, formatDuration, formatNumber, outcomeLabel, outcomeTone, shortFormatLabel } from '../format';
import { FORMAT_QUICK_FILTERS } from '../quickFilters';
import { gameRouteHash, gamesRouteHash } from '../routes';
import { Badge } from './Badge';
import { ColorPips } from './ColorPips';
import { DeckLink } from './DeckLink';
import { FilterBar } from './FilterBar';
import { Section } from './Section';
import { SortableTable, type Column } from './SortableTable';

const REFRESH_MS = 60_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; response: AllGamesResponse; refreshError?: string }
  | { status: 'error'; message: string };

function landsSeenLabel(row: AllGamesRow): string {
  const count = formatNumber(row.lands_seen);
  return row.land_seen_pct === null || row.land_seen_pct === undefined
    ? count
    : `${count} (${Math.ceil(row.land_seen_pct)}%)`;
}

const columns: Column<AllGamesRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => <a href={gameRouteHash(row.game_id, '#/games')}>{formatDateTime(row.started_at)}</a>,
    sortValue: (row) => row.started_at,
  },
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
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
    sortValue: (row) => row.outcome,
    center: true,
  },
  {
    key: 'opp_colors',
    header: 'Opp',
    render: (row) => <ColorPips colors={row.opp_colors} />,
    sortValue: (row) => row.opp_colors ?? '',
  },
  {
    key: 'is_flood',
    header: 'Draw Status',
    render: (row) =>
      row.is_flood ? (
        <Badge tone="flood">Flood</Badge>
      ) : row.is_screw ? (
        <Badge tone="screw">Mana Screw</Badge>
      ) : (
        'Normal'
      ),
    sortValue: (row) => (row.is_flood ? 2 : row.is_screw ? 1 : 0),
    center: true,
  },
  {
    key: 'went_first',
    header: 'Play/Draw',
    render: (row) =>
      row.went_first == null ? null : (
        <Badge tone={row.went_first ? 'play' : 'drawside'}>{row.went_first ? 'Play' : 'Draw'}</Badge>
      ),
    sortValue: (row) => row.went_first ?? -1,
    center: true,
  },
  { key: 'cards_seen', header: 'Cards Seen', numeric: true },
  {
    key: 'lands_seen',
    header: 'Lands Seen',
    render: (row) => landsSeenLabel(row),
    sortValue: (row) => row.lands_seen,
    numeric: true,
  },
  { key: 'total_turns', header: 'Turns', numeric: true },
  {
    key: 'duration_seconds',
    header: 'Game Time',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
    numeric: true,
  },
];

export function GamesPage({
  filters = {},
  onFiltersChange,
}: {
  filters?: SnapshotFilters;
  onFiltersChange?: (filters: SnapshotFilters) => void;
}) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [quickFilter, setQuickFilter] = useState(() =>
    FORMAT_QUICK_FILTERS.some((filter) => filter.id === filters.quick)
      ? (filters.quick as string)
      : 'all',
  );
  const [deckSearch, setDeckSearch] = useState('');
  const [retryToken, setRetryToken] = useState(0);

  // Bookmarkable quick filter: the chip is read from the URL on mount and
  // written back on click, so a bookmarked ?q=bo3 view survives refresh.
  function selectQuickFilter(id: string) {
    setQuickFilter(id);
    try {
      const next = { ...filters };
      if (id === 'all') {
        delete next.quick;
      } else {
        next.quick = id;
      }
      window.history.replaceState(null, '', gamesRouteHash(next));
    } catch {
      // history API unavailable; the chip still works for this visit.
    }
  }

  useEffect(() => {
    window.scrollTo(0, 0);
    let ignore = false;
    let activeController: AbortController | null = null;

    async function load() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const response = await fetchAllGames(filters, controller.signal);
        if (!ignore) {
          setLoadState({ status: 'loaded', response });
        }
      } catch (error: unknown) {
        if (ignore || (error instanceof Error && error.name === 'AbortError')) {
          return;
        }
        const message = error instanceof Error ? error.message : 'Games API failed';
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
    }, REFRESH_MS);
    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [filters, retryToken]);

  const loadedResponse = loadState.status === 'loaded' ? loadState.response : null;
  const rows = useMemo(() => loadedResponse?.games ?? [], [loadedResponse]);

  const filterOptions = useMemo(() => {
    const decks = Array.from(new Set(rows.map((row) => row.deck_name))).sort((a, b) =>
      a.localeCompare(b),
    );
    const formats = new Map<string, string>();
    for (const row of rows) {
      const raw = (row as AllGamesRow & { raw_format?: string | null }).raw_format;
      if (raw && !formats.has(raw)) {
        formats.set(raw, row.format_label);
      }
    }
    return {
      decks,
      formats: Array.from(formats.entries()).map(([raw_format, format_label]) => ({
        raw_format,
        format_label,
      })),
    };
  }, [rows]);

  const visibleRows = useMemo(() => {
    const active = FORMAT_QUICK_FILTERS.find((filter) => filter.id === quickFilter);
    const query = deckSearch.trim().toLocaleLowerCase();
    return rows.filter((row) => {
      if (active && active.id !== 'all' && !active.matches(row.format_label.toLocaleLowerCase())) {
        return false;
      }
      if (query && !row.deck_name.toLocaleLowerCase().includes(query)) {
        return false;
      }
      if (filters.colors && (row.opp_colors ?? '') !== filters.colors) {
        return false;
      }
      return true;
    });
  }, [deckSearch, filters.colors, quickFilter, rows]);

  if (loadState.status === 'loading') {
    return (
      <p className="state-panel" role="status" aria-busy="true">
        Loading all games...
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

  return (
    <>
      {loadState.refreshError ? (
        <p className="refresh-status refresh-status-error" role="alert">
          Refresh failed: {loadState.refreshError} — showing the last loaded data.
        </p>
      ) : null}
      <Section
        id="all-games-list"
        description={`Every tracked game (${loadState.response.total} total), newest first.`}
      >
        {onFiltersChange ? (
          <FilterBar filters={filters} onChange={onFiltersChange} options={filterOptions} />
        ) : null}
        {filters.colors ? (
          <p className="active-color-filter">
            <span>Showing games vs</span>
            <ColorPips colors={filters.colors} size={22} />
            <strong className="active-color-name">
              {colorComboLabel(filters.colors) ?? filters.colors}
            </strong>
            {onFiltersChange ? (
              <button
                className="quick-filter"
                type="button"
                onClick={() => {
                  const next = { ...filters };
                  delete next.colors;
                  onFiltersChange(next);
                }}
              >
                Clear
              </button>
            ) : null}
          </p>
        ) : null}
        <div className="quick-filters" role="group" aria-label="Quick format filters">
          {FORMAT_QUICK_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              className={quickFilter === filter.id ? 'quick-filter quick-filter-active' : 'quick-filter'}
              aria-pressed={quickFilter === filter.id}
              onClick={() => selectQuickFilter(filter.id)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <div className="table-filter">
          <label>
            <span>Search decks</span>
            <input
              type="search"
              value={deckSearch}
              onChange={(event) => setDeckSearch(event.target.value)}
              placeholder="Deck name"
            />
          </label>
        </div>
        <SortableTable
          caption="All games"
          columns={columns}
          pageSize={25}
          paginationKey={`${quickFilter}|${deckSearch.trim().toLocaleLowerCase()}`}
          getRowKey={(row) => row.game_id}
          initialSort={{ key: 'started_at', direction: 'desc' }}
          rows={visibleRows}
        />
      </Section>
    </>
  );
}
