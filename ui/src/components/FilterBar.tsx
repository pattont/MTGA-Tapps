import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { FilterOptions, SnapshotFilters } from '../api';
import { showInFormatAnalytics } from '../formatVisibility';

interface FilterBarProps {
  filters: SnapshotFilters;
  options: FilterOptions;
  onChange: (filters: SnapshotFilters) => void;
  /** Hide the deck selector (e.g. on a deck detail page). */
  hideDeck?: boolean;
  /** Hide the format dropdown (All Games: the quick-filter pills cover it). */
  hideFormat?: boolean;
  /** Drop the "Deck" label — the trigger's "All decks" text says it already. */
  hideDeckLabel?: boolean;
  /** Double-width deck picker (All Games, where the format dropdown is gone). */
  wideDeck?: boolean;
  /** Right-aligned page action on the filter row (e.g. Copy Arena Deck). */
  trailing?: ReactNode;
}

const DAY_CHOICES = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
];

/** Deck picker with a search box in the dropdown — deck lists get long. */
function DeckSelect({
  value,
  decks,
  onChange,
}: {
  value?: string;
  decks: string[];
  onChange: (deck?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    searchRef.current?.focus();
    const onDocPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const trimmed = query.trim().toLocaleLowerCase();
  const filtered = trimmed
    ? decks.filter((deck) => deck.toLocaleLowerCase().includes(trimmed))
    : decks;

  const select = (deck?: string) => {
    onChange(deck);
    setOpen(false);
    setQuery('');
  };

  return (
    <div className="deck-select" ref={rootRef}>
      <button
        type="button"
        className="deck-select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Deck filter"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="deck-select-value">{value ?? 'All decks'}</span>
        <span className="deck-select-caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open ? (
        <div className="deck-select-popup">
          <input
            ref={searchRef}
            type="search"
            placeholder="Search decks"
            aria-label="Search decks in filter"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <ul role="listbox" aria-label="Decks">
            <li>
              <button
                type="button"
                className={!value ? 'deck-select-option deck-select-option-active' : 'deck-select-option'}
                role="option"
                aria-selected={!value}
                onClick={() => select(undefined)}
              >
                All decks
              </button>
            </li>
            {filtered.map((deck) => (
              <li key={deck}>
                <button
                  type="button"
                  className={
                    deck === value
                      ? 'deck-select-option deck-select-option-active'
                      : 'deck-select-option'
                  }
                  role="option"
                  aria-selected={deck === value}
                  onClick={() => select(deck)}
                >
                  {deck}
                </button>
              </li>
            ))}
            {filtered.length === 0 ? <li className="deck-select-empty">No decks match</li> : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function FilterBar({
  filters,
  options,
  onChange,
  hideDeck = false,
  hideFormat = false,
  hideDeckLabel = false,
  wideDeck = false,
  trailing,
}: FilterBarProps) {
  const hasFilters = Boolean(
    filters.deck || filters.format || filters.days || filters.since || filters.until,
  );
  return (
    <div className="filter-bar" role="group" aria-label="Dashboard filters">
      {hideDeck ? null : (
        <div className={wideDeck ? 'filter-field filter-field-wide-deck' : 'filter-field'}>
          {hideDeckLabel ? null : <span className="filter-field-label">Deck</span>}
          <DeckSelect
            decks={options.decks}
            value={filters.deck}
            onChange={(deck) => onChange({ ...filters, deck })}
          />
        </div>
      )}
      {hideFormat ? null : (
        <label className="filter-field">
          <span className="filter-field-label">Format</span>
          <select
            value={filters.format ?? ''}
            onChange={(event) => onChange({ ...filters, format: event.target.value || undefined })}
          >
            <option value="">All formats</option>
            {options.formats.filter(showInFormatAnalytics).map((format) => (
              <option key={format.raw_format} value={format.raw_format}>
                {format.format_label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="filter-field">
        <span className="filter-field-label">Period</span>
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
      <label className="filter-field">
        <span className="filter-field-label">From</span>
        <input
          type="date"
          value={filters.since ?? ''}
          onChange={(event) => onChange({ ...filters, since: event.target.value || undefined })}
        />
      </label>
      <label className="filter-field">
        <span className="filter-field-label">To</span>
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
      {trailing ? <div className="filter-bar-trailing">{trailing}</div> : null}
    </div>
  );
}
