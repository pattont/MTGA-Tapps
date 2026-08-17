import type { CommanderRow } from './api';
import { ColorPips } from './components/ColorPips';
import type { Column } from './components/SortableTable';
import { WinRateBar } from './components/WinRateBar';

/**
 * Columns for a record-by-commander table (Brawl). Shared by the
 * "Your Commanders" and "Faced Commanders" overview tables.
 */
export function makeCommanderColumns(header: string): Column<CommanderRow>[] {
  return [
    {
      key: 'commander',
      header,
      render: (row) => (
        <span className="color-combo">
          {row.colors ? <ColorPips colors={row.colors} /> : null}
          {row.commander}
        </span>
      ),
      sortValue: (row) => row.commander,
    },
    { key: 'games', header: 'Games', numeric: true },
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
