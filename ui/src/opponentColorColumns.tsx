import type { OpponentColorRow } from './api';
import { ColorPips } from './components/ColorPips';
import type { Column } from './components/SortableTable';
import { formatPercent } from './dashboardData';

export const opponentColorColumns: Column<OpponentColorRow>[] = [
  {
    key: 'color_label',
    header: 'Opponent Colors',
    render: (row) => (
      <span className="color-combo">
        <ColorPips colors={row.colors} />
        {row.color_label}
      </span>
    ),
    sortValue: (row) => row.color_label,
  },
  { key: 'games', header: 'Games', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => formatPercent(row.win_rate),
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];
