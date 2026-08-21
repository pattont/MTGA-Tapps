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
    ['Cards', 'Removal'],
    ['Bounce', 'Land Destruction'],
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
