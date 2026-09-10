import type { ReactNode } from 'react';

/** One Combat & Resources category table: rows are [label, you, opp] cells. */
export interface CombatGroupTable {
  title: string;
  rows: [string, ReactNode, ReactNode][];
}

/**
 * "played (N drawn)" cell that never wraps: the drawn part renders as a
 * small muted one-line suffix so wide values stay on a single row.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function withDrawnSuffix(played: ReactNode, drawn: ReactNode): ReactNode {
  return (
    <span className="stat-with-drawn">
      {played} <span className="stat-drawn-suffix">({drawn} drawn)</span>
    </span>
  );
}

/**
 * "1 (33%)": a scried-to-top or scried-to-bottom count with its share of
 * everything scried as the same small muted suffix as "(N drawn)". Works on
 * per-game totals and on per-game averages alike (a ratio of averages over
 * the same games is the ratio of the sums). The share is left off until
 * anything has been scried.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function withScryShare(
  value: number | null | undefined,
  top: number | null | undefined,
  bottom: number | null | undefined,
): ReactNode {
  if (value == null) {
    return null;
  }
  const total = (top ?? 0) + (bottom ?? 0);
  if (total <= 0) {
    return String(value);
  }
  return (
    <span className="stat-with-drawn">
      {value} <span className="stat-drawn-suffix">({Math.round((100 * value) / total)}%)</span>
    </span>
  );
}

/**
 * Renders Combat & Resources groups in EXPLICIT columns so the game page and
 * deck page lay out identically. CSS multi-column masonry balances by content
 * height, which broke groups into different columns on each page; a fixed
 * column assignment keeps "the same box in the same place" everywhere.
 */
export function CombatGroupColumns({ columns }: { columns: CombatGroupTable[][] }) {
  return (
    <div className="combat-columns">
      {columns.map((groups, index) => (
        <div key={index} className="combat-column">
          {groups.map((group) => (
            <div key={group.title} className="combat-group">
              <table className="combat-group-table">
                <caption className="visually-hidden">{group.title} stats by seat</caption>
                <thead>
                  <tr>
                    <th scope="col">{group.title}</th>
                    <th scope="col" className="numeric">
                      You
                    </th>
                    <th scope="col" className="numeric">
                      Opp
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map(([label, you, opp]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td className="numeric">{you}</td>
                      <td className="numeric">{opp}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * The one canonical column layout for Combat & Resources, shared by the game
 * and deck pages. Titles missing from `groups` are skipped, so both pages can
 * feed the same buckets even if a category is absent.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function bucketCombatGroups(groups: CombatGroupTable[]): CombatGroupTable[][] {
  const buckets = [
    ['Attack', 'Block', 'Life'],
    ['Cards', 'Scry'],
    ['Removal', 'Bounce', 'Land Destruction'],
    ['Counter Magic', 'Tokens'],
  ];
  const byTitle = new Map(groups.map((group) => [group.title, group]));
  return buckets.map((titles) =>
    titles.flatMap((title) => {
      const group = byTitle.get(title);
      return group ? [group] : [];
    }),
  );
}
