import type { PlayDrawRow } from './api';

export const ON_THE_PLAY = 'On the play';
export const ON_THE_DRAW = 'On the draw';

/** A Play / Draw row with its share of the games whose turn order is known. */
export type PlayDrawShareRow = PlayDrawRow & { share: number | null };

function isKnownSide(row: PlayDrawRow): boolean {
  return row.play_draw === ON_THE_PLAY || row.play_draw === ON_THE_DRAW;
}

/**
 * Adds each side's percent of play + draw games (the Overview's "% of Games").
 * Games with an unknown turn order count toward neither side, and their row gets none.
 */
export function withPlayDrawShare(rows: PlayDrawRow[]): PlayDrawShareRow[] {
  const known = rows.filter(isKnownSide).reduce((sum, row) => sum + row.games, 0);
  return rows.map((row) => ({
    ...row,
    share: known > 0 && isKnownSide(row) ? (100 * row.games) / known : null,
  }));
}
