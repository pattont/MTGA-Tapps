import type { OpponentColorRow } from './api';
import { ColorPips } from './components/ColorPips';
import type { Column } from './components/SortableTable';
import { WinRateBar } from './components/WinRateBar';
import { formatPercent } from './dashboardData';

/**
 * Columns for a record-by-opponent-colors table. Pass getHref to make each
 * combo link to a filtered game list (e.g. All Games with colors=UR).
 */
export function makeOpponentColorColumns(
  getHref?: (row: OpponentColorRow) => string,
): Column<OpponentColorRow>[] {
  return [
    {
      key: 'color_label',
      header: 'Opponent Colors',
      render: (row) => {
        const body = (
          <>
            <ColorPips colors={row.colors} />
            {row.color_label}
          </>
        );
        return getHref && row.colors ? (
          <a className="color-combo" href={getHref(row)}>
            {body}
          </a>
        ) : (
          <span className="color-combo">{body}</span>
        );
      },
      sortValue: (row) => row.color_label,
    },
    { key: 'games', header: 'Games', numeric: true },
    {
      key: 'pct_of_games',
      header: '% of Games',
      render: (row) => formatPercent(row.pct_of_games),
      sortValue: (row) => row.pct_of_games,
      numeric: true,
    },
    { key: 'wins', header: 'Wins', numeric: true },
    { key: 'losses', header: 'Losses', numeric: true },
    {
      key: 'win_rate',
      header: 'Win Rate',
      render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
      sortValue: (row) => row.win_rate,
      numeric: true,
    },
  ];
}
