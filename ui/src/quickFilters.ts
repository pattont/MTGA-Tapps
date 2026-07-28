export interface QuickFilter {
  id: string;
  label: string;
  matches: (formatLabelLower: string) => boolean;
}

export const FORMAT_QUICK_FILTERS: QuickFilter[] = [
  { id: 'all', label: 'All', matches: () => true },
  { id: 'bo1', label: 'BO1', matches: (label) => label.includes('best-of-1') },
  { id: 'bo3', label: 'BO3', matches: (label) => label.includes('best-of-3') },
  {
    id: 'premier-draft',
    label: 'Premier Draft',
    matches: (label) =>
      label.includes('premier draft') ||
      (label.includes('draft') && !label.includes('traditional') && !label.includes('quick')),
  },
  {
    id: 'sealed',
    label: 'Sealed',
    matches: (label) => label.includes('sealed') && !label.includes('traditional'),
  },
  {
    id: 'trad-draft',
    label: 'Traditional Draft',
    matches: (label) => label.includes('traditional') && label.includes('draft'),
  },
  {
    id: 'trad-sealed',
    label: 'Traditional Sealed',
    matches: (label) => label.includes('traditional') && label.includes('sealed'),
  },
];
