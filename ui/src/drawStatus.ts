// Draw Status for game rows: Flood, Mana Screw, Land streak or Normal.

/** The draw flags every game row carries. */
export interface DrawStatusFlags {
  is_flood?: boolean;
  is_screw?: boolean;
  is_land_streak?: boolean;
}

export type DrawStatus = 'flood' | 'screw' | 'streak' | 'normal';

/** Flood, then Mana Screw, then a land streak that wasn't flood. */
export function drawStatusOf(row: DrawStatusFlags): DrawStatus {
  if (row.is_flood) {
    return 'flood';
  }
  if (row.is_screw) {
    return 'screw';
  }
  if (row.is_land_streak) {
    return 'streak';
  }
  return 'normal';
}

const SORT_ORDER: Record<DrawStatus, number> = { flood: 3, screw: 2, streak: 1, normal: 0 };

export function drawStatusSortValue(row: DrawStatusFlags): number {
  return SORT_ORDER[drawStatusOf(row)];
}

export const LAND_STREAK_HINT = 'An unusual run of land draws, but no more lands than expected overall';
