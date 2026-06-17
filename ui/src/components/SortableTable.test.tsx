import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { SortableTable } from './SortableTable';

describe('SortableTable', () => {
  const rows = [
    { deck: 'Boros', games: 1, winRate: '50%' },
    { deck: 'Azorius', games: 4, winRate: '75%' },
  ];

  it('sorts by every clickable column', async () => {
    const user = userEvent.setup();
    render(
      <SortableTable
        caption="Decks"
        columns={[
          { key: 'deck', header: 'Deck' },
          { key: 'games', header: 'Games' },
          { key: 'winRate', header: 'WR' },
        ]}
        rows={rows}
      />,
    );

    await user.click(screen.getByRole('button', { name: /games/i }));
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Boros');

    await user.click(screen.getByRole('button', { name: /games/i }));
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Azorius');

    await user.click(screen.getByRole('button', { name: /deck/i }));
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Azorius');
  });

  it('renders an empty state', () => {
    render(<SortableTable caption="Recent" columns={[{ key: 'deck', header: 'Deck' }]} rows={[]} />);
    expect(screen.getByText('No rows yet.')).toBeInTheDocument();
  });
});
