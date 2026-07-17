import type { FilterOptions, SnapshotFilters } from '../api';

interface FilterBarProps {
  filters: SnapshotFilters;
  options: FilterOptions;
  onChange: (filters: SnapshotFilters) => void;
}

const DAY_CHOICES = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
];

export function FilterBar({ filters, options, onChange }: FilterBarProps) {
  const hasFilters = Boolean(filters.deck || filters.format || filters.days);
  return (
    <div className="filter-bar" role="group" aria-label="Dashboard filters">
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
      <label>
        <span>Format</span>
        <select
          value={filters.format ?? ''}
          onChange={(event) => onChange({ ...filters, format: event.target.value || undefined })}
        >
          <option value="">All formats</option>
          {options.formats.map((format) => (
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
      {hasFilters ? (
        <button className="filter-clear" type="button" onClick={() => onChange({})}>
          Clear filters
        </button>
      ) : null}
    </div>
  );
}
