import type { FilterOptions, SnapshotFilters } from '../api';
import { showInFormatAnalytics } from '../formatVisibility';

interface FilterBarProps {
  filters: SnapshotFilters;
  options: FilterOptions;
  onChange: (filters: SnapshotFilters) => void;
  /** Hide the deck selector (e.g. on a deck detail page). */
  hideDeck?: boolean;
}

const DAY_CHOICES = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
];

export function FilterBar({ filters, options, onChange, hideDeck = false }: FilterBarProps) {
  const hasFilters = Boolean(
    filters.deck || filters.format || filters.days || filters.since || filters.until,
  );
  return (
    <div className="filter-bar" role="group" aria-label="Dashboard filters">
      {hideDeck ? null : (
        <label>
          <span>Deck</span>
          <select
            value={filters.deck ?? ''}
            onChange={(event) => onChange({ ...filters, deck: event.target.value || undefined })}
          >
            <option value="">All decks</option>
            {options.decks.map((deck) => (
              <option key={deck} value={deck}>
                {deck}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        <span>Format</span>
        <select
          value={filters.format ?? ''}
          onChange={(event) => onChange({ ...filters, format: event.target.value || undefined })}
        >
          <option value="">All formats</option>
          {options.formats.filter(showInFormatAnalytics).map((format) => (
            <option key={format.raw_format} value={format.raw_format}>
              {format.format_label} ({format.raw_format})
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Period</span>
        <select
          value={filters.days ? String(filters.days) : ''}
          onChange={(event) =>
            onChange({ ...filters, days: event.target.value ? Number(event.target.value) : undefined })
          }
        >
          <option value="">All time</option>
          {DAY_CHOICES.map((choice) => (
            <option key={choice.value} value={String(choice.value)}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>From</span>
        <input
          type="date"
          value={filters.since ?? ''}
          onChange={(event) => onChange({ ...filters, since: event.target.value || undefined })}
        />
      </label>
      <label>
        <span>To</span>
        <input
          type="date"
          value={filters.until ?? ''}
          onChange={(event) => onChange({ ...filters, until: event.target.value || undefined })}
        />
      </label>
      {hasFilters ? (
        <button className="filter-clear" type="button" onClick={() => onChange({})}>
          Clear filters
        </button>
      ) : null}
    </div>
  );
}
