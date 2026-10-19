/**
 * Readable label for an Arena deck Format attribute. Display only: the stored
 * value is what Arena wrote and is sent back to Arena unchanged on restore.
 *
 * "TraditionalStandard" → "Traditional Standard",
 * "HistoricBrawlWithAllowList_20260825" → "Historic Brawl".
 * Names that already contain spaces (typed by the user) are left alone.
 */
export function deckFormatLabel(format: string | null | undefined): string {
  const raw = (format ?? '').trim();
  if (!raw || /\s/.test(raw)) return raw;
  return raw
    .replace(/_\d{8}$/, '')
    .replace(/WithAllowList$/, '')
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .trim() || raw;
}

/**
 * Arena deck formats offered when adding a deck, as Arena's own Format values
 * (the ones Add to Arena maps directly; see native_deck_archive.arena_format).
 */
export const DECK_FORMATS = [
  'Standard', 'TraditionalStandard', 'Historic', 'TraditionalHistoric', 'Explorer', 'TraditionalExplorer',
  'Timeless', 'Alchemy', 'TraditionalAlchemy', 'Brawl', 'HistoricBrawl',
] as const;
