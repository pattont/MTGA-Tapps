import { describe, expect, it } from 'vitest';
import { normalizeQuickFilterId, quickFilterPredicate } from './quickFilters';

const STANDARD_R1 = 'standard best-of-1 (ranked)';
const STANDARD_U3 = 'standard best-of-3 (unranked)';
const HISTORIC_BRAWL = 'historic brawl';
const TIMELESS_QUALIFIER = 'qualifier play in bo1 timeless';
const TRAD_SEALED = 'traditional sealed - msh';

describe('format quick filters', () => {
  it('families match their ladder queues and nothing else', () => {
    expect(quickFilterPredicate('standard')(STANDARD_R1)).toBe(true);
    expect(quickFilterPredicate('standard')(HISTORIC_BRAWL)).toBe(false);
    // Brawl queues never leak into their base format's family.
    expect(quickFilterPredicate('historic')(HISTORIC_BRAWL)).toBe(false);
    expect(quickFilterPredicate('brawl')(HISTORIC_BRAWL)).toBe(true);
    // Events don't pollute the ladder family they mention.
    expect(quickFilterPredicate('timeless')(TIMELESS_QUALIFIER)).toBe(false);
    expect(quickFilterPredicate('events')(TIMELESS_QUALIFIER)).toBe(true);
  });

  it('refinements narrow within the family', () => {
    expect(quickFilterPredicate('standard-bo1-ranked')(STANDARD_R1)).toBe(true);
    expect(quickFilterPredicate('standard-bo1-ranked')(STANDARD_U3)).toBe(false);
    expect(quickFilterPredicate('limited-sealed')('sealed - msh')).toBe(true);
    expect(quickFilterPredicate('limited-sealed')(TRAD_SEALED)).toBe(false);
    expect(quickFilterPredicate('limited-trad-sealed')(TRAD_SEALED)).toBe(true);
    expect(quickFilterPredicate('brawl-standard')('standard brawl')).toBe(true);
    expect(quickFilterPredicate('brawl-standard')(HISTORIC_BRAWL)).toBe(false);
    // Arena's renamed queue: plain "Brawl" is the historic one.
    expect(quickFilterPredicate('brawl-historic')('brawl')).toBe(true);
  });

  it('legacy bookmarked chip ids keep working', () => {
    expect(normalizeQuickFilterId('premier-draft')).toBe('limited-premier-draft');
    expect(normalizeQuickFilterId('trad-sealed')).toBe('limited-trad-sealed');
    expect(normalizeQuickFilterId('bo1')).toBe('all');
    expect(normalizeQuickFilterId('nonsense')).toBe('all');
    expect(normalizeQuickFilterId(undefined)).toBe('all');
  });
});
