import { FORMAT_FAMILIES, normalizeQuickFilterId, resolveQuickFilter } from '../quickFilters';

/**
 * Two-tier format chips: format families on top (All, Standard, …, Brawl),
 * and — when the selected family has them — a fly-out row of queue
 * refinements (BO1/BO3/Ranked, draft flavors, Brawl variants) beneath.
 * Clicking an active refinement returns to the whole family.
 */
export function FormatQuickFilters({
  value,
  onChange,
}: {
  value: string;
  onChange: (id: string) => void;
}) {
  const resolved = resolveQuickFilter(normalizeQuickFilterId(value));
  const family = resolved?.family ?? FORMAT_FAMILIES[0];
  const refinement = resolved?.refinement ?? null;

  return (
    <div className="quick-filter-stack">
      <div className="quick-filters" role="group" aria-label="Format families">
        {FORMAT_FAMILIES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={family.id === entry.id ? 'quick-filter quick-filter-active' : 'quick-filter'}
            aria-pressed={family.id === entry.id}
            onClick={() => onChange(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      {family.refinements ? (
        <div
          className="quick-filters quick-filters-sub"
          role="group"
          aria-label={`${family.label} queues`}
        >
          {family.refinements.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={
                refinement?.id === entry.id ? 'quick-filter quick-filter-active' : 'quick-filter'
              }
              aria-pressed={refinement?.id === entry.id}
              onClick={() => onChange(refinement?.id === entry.id ? family.id : entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
