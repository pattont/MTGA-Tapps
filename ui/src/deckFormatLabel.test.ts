import { describe, expect, it } from 'vitest';
import { deckFormatLabel } from './deckFormatLabel';

describe('deckFormatLabel', () => {
  it.each([
    ['TraditionalStandard', 'Traditional Standard'],
    ['HistoricBrawl', 'Historic Brawl'],
    ['HistoricBrawlWithAllowList_20260825', 'Historic Brawl'],
    ['Standard', 'Standard'],
    ['Historic Pauper', 'Historic Pauper'],
    ['', ''],
    [null, ''],
  ])('%s → %s', (raw, label) => expect(deckFormatLabel(raw)).toBe(label));
});
