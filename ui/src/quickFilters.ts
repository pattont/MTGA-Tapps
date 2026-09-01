export interface QuickFilter {
  id: string;
  label: string;
  matches: (formatLabelLower: string) => boolean;
}

export interface FormatFamily extends QuickFilter {
  /** Second-tier pills shown when this family is selected. */
  refinements?: QuickFilter[];
}

/* Special events (qualifiers, Midweek Magic, opens) are their own family so
   a "Qualifier Play In Bo1 Timeless" doesn't pollute the Timeless ladder. */
const isEvent = (label: string): boolean =>
  /qualifier|play.?in|midweek|festival|metagame|arena open|arena championship/.test(label);

const isLimited = (label: string): boolean => /draft|sealed|cube|pick.?two|pick.?2/.test(label);

const isBrawl = (label: string): boolean => label.includes('brawl');

const bo1 = (label: string): boolean => /best-of-1|bo1/.test(label);
const bo3 = (label: string): boolean => /best-of-3|bo3/.test(label);
const ranked = (label: string): boolean => label.includes('(ranked)');

/** A constructed ladder family: the family word, minus Brawl/Limited/event
    queues that happen to mention it, with the usual BO/ranked refinements. */
function constructedFamily(id: string, label: string, word: string): FormatFamily {
  const inFamily = (l: string) => l.includes(word) && !isBrawl(l) && !isLimited(l) && !isEvent(l);
  return {
    id,
    label,
    matches: inFamily,
    refinements: [
      { id: `${id}-bo1`, label: 'BO1', matches: (l) => inFamily(l) && bo1(l) },
      { id: `${id}-bo3`, label: 'BO3', matches: (l) => inFamily(l) && bo3(l) },
      { id: `${id}-bo1-ranked`, label: 'BO1 Ranked', matches: (l) => inFamily(l) && bo1(l) && ranked(l) },
      { id: `${id}-bo3-ranked`, label: 'BO3 Ranked', matches: (l) => inFamily(l) && bo3(l) && ranked(l) },
    ],
  };
}

export const FORMAT_FAMILIES: FormatFamily[] = [
  { id: 'all', label: 'All', matches: () => true },
  constructedFamily('standard', 'Standard', 'standard'),
  constructedFamily('historic', 'Historic', 'historic'),
  constructedFamily('modern', 'Modern', 'modern'),
  constructedFamily('pioneer', 'Pioneer', 'pioneer'),
  constructedFamily('timeless', 'Timeless', 'timeless'),
  {
    id: 'limited',
    label: 'Limited',
    matches: (l) => isLimited(l) && !isEvent(l),
    refinements: [
      { id: 'limited-premier-draft', label: 'Premier Draft', matches: (l) => l.includes('premier draft') },
      { id: 'limited-quick-draft', label: 'Quick Draft', matches: (l) => l.includes('quick draft') },
      {
        id: 'limited-trad-draft',
        label: 'Traditional Draft',
        matches: (l) => l.includes('traditional') && l.includes('draft'),
      },
      {
        id: 'limited-sealed',
        label: 'Sealed',
        matches: (l) => l.includes('sealed') && !l.includes('traditional'),
      },
      {
        id: 'limited-trad-sealed',
        label: 'Traditional Sealed',
        matches: (l) => l.includes('traditional') && l.includes('sealed'),
      },
      { id: 'limited-pick-two', label: 'Pick Two', matches: (l) => /pick.?two|pick.?2/.test(l) },
    ],
  },
  {
    id: 'brawl',
    label: 'Brawl',
    matches: (l) => isBrawl(l),
    refinements: [
      {
        id: 'brawl-historic',
        label: 'Brawl (Historic)',
        matches: (l) => l.includes('historic brawl') || l.trim() === 'brawl',
      },
      { id: 'brawl-standard', label: 'Standard Brawl', matches: (l) => l.includes('standard brawl') },
      {
        id: 'brawl-competitive',
        label: 'Competitive Brawl',
        matches: (l) => l.includes('competitive') && l.includes('brawl'),
      },
    ],
  },
  { id: 'events', label: 'Events', matches: (l) => isEvent(l) },
];

/** Old single-tier chip ids (bookmarked ?q= values) mapped onto the new
    two-tier ids so saved links keep working. */
const LEGACY_QUICK_IDS: Record<string, string> = {
  'premier-draft': 'limited-premier-draft',
  sealed: 'limited-sealed',
  'trad-draft': 'limited-trad-draft',
  'trad-sealed': 'limited-trad-sealed',
  // The old cross-format BO chips have no family equivalent — fall back to All.
  bo1: 'all',
  bo3: 'all',
  'bo1-ranked': 'all',
  'bo3-ranked': 'all',
};

export function normalizeQuickFilterId(id: string | undefined | null): string {
  if (!id) {
    return 'all';
  }
  const mapped = LEGACY_QUICK_IDS[id] ?? id;
  return resolveQuickFilter(mapped) ? mapped : 'all';
}

/** Resolve a family or refinement id to its family (and refinement, if any). */
export function resolveQuickFilter(
  id: string,
): { family: FormatFamily; refinement?: QuickFilter } | null {
  for (const family of FORMAT_FAMILIES) {
    if (family.id === id) {
      return { family };
    }
    const refinement = family.refinements?.find((entry) => entry.id === id);
    if (refinement) {
      return { family, refinement };
    }
  }
  return null;
}

/** The row filter for a selected chip id (lowercased format labels). */
export function quickFilterPredicate(id: string): (formatLabelLower: string) => boolean {
  const resolved = resolveQuickFilter(normalizeQuickFilterId(id));
  if (!resolved || resolved.family.id === 'all') {
    return () => true;
  }
  const { family, refinement } = resolved;
  return refinement ? refinement.matches : family.matches;
}
