import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { SortableTable } from './SortableTable';

describe('SortableTable', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  const rows = [
    { deck: 'Boros', games: 1, winRate: '50%' },
    { deck: 'Azorius', games: 4, winRate: '75%' },
  ];
  type DeckRow = (typeof rows)[number];

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
        getRowKey={(row) => row.deck}
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
    render(<SortableTable<DeckRow> caption="Recent" columns={[{ key: 'deck', header: 'Deck' }]} getRowKey={(row) => row.deck} rows={[]} />);
    expect(screen.getByText('No rows yet.')).toBeInTheDocument();
  });

  it('renders an empty state when there are no columns', () => {
    const columns: { key: keyof DeckRow; header: string }[] = [];
    render(<SortableTable<DeckRow> caption="Recent" columns={columns} getRowKey={(row) => row.deck} rows={rows} />);
    expect(screen.getByText('No rows yet.')).toBeInTheDocument();
  });

  it('exposes sort state through column headers', async () => {
    const user = userEvent.setup();
    render(
      <SortableTable
        caption="Decks"
        columns={[
          { key: 'deck', header: 'Deck' },
          { key: 'games', header: 'Games' },
        ]}
        getRowKey={(row) => row.deck}
        rows={rows}
      />,
    );

    expect(screen.getByRole('columnheader', { name: /deck/i })).toHaveAttribute('aria-sort', 'ascending');
    expect(screen.getByRole('columnheader', { name: /games/i })).toHaveAttribute('aria-sort', 'none');

    await user.click(screen.getByRole('button', { name: /games/i }));
    expect(screen.getByRole('columnheader', { name: /deck/i })).toHaveAttribute('aria-sort', 'none');
    expect(screen.getByRole('columnheader', { name: /games/i })).toHaveAttribute('aria-sort', 'ascending');

    await user.click(screen.getByRole('button', { name: /games/i }));
    expect(screen.getByRole('columnheader', { name: /games/i })).toHaveAttribute('aria-sort', 'descending');
  });

  it('resets sorting when the active sort column is removed', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <SortableTable
        caption="Decks"
        columns={[
          { key: 'deck', header: 'Deck' },
          { key: 'games', header: 'Games' },
        ]}
        getRowKey={(row) => row.deck}
        rows={rows}
      />,
    );

    await user.click(screen.getByRole('button', { name: /games/i }));
    expect(screen.getByRole('columnheader', { name: /games/i })).toHaveAttribute('aria-sort', 'ascending');

    rerender(<SortableTable caption="Decks" columns={[{ key: 'deck', header: 'Deck' }]} getRowKey={(row) => row.deck} rows={rows} />);

    expect(screen.queryByRole('button', { name: /games/i })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /deck/i })).toHaveAttribute('aria-sort', 'ascending');
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Azorius');
  });

  it('uses custom sort values and renders nonsortable headers without buttons', async () => {
    const user = userEvent.setup();
    const richRows = [
      { deck: 'Boros', details: { label: 'Mouse Mentor', winRate: 50 }, notes: { source: 'local' } },
      { deck: 'Azorius', details: { label: 'Sky Control', winRate: 75 }, notes: { source: 'local' } },
    ];

    render(
      <SortableTable
        caption="Decks"
        columns={[
          { key: 'deck', header: 'Deck' },
          {
            key: 'details',
            header: 'WR',
            render: (row) => `${row.details.winRate}%`,
            sortValue: (row) => row.details.winRate,
          },
          {
            key: 'notes',
            header: 'Notes',
            render: (row) => row.notes.source,
            sortable: false,
          },
        ]}
        getRowKey={(row) => row.deck}
        rows={richRows}
      />,
    );

    expect(screen.getByRole('columnheader', { name: /notes/i })).toHaveAttribute('aria-sort', 'none');
    expect(screen.queryByRole('button', { name: /notes/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /wr/i }));
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Boros');

    await user.click(screen.getByRole('button', { name: /wr/i }));
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Azorius');
  });

  it('paginates after sorting and resets to the first page when sorting changes', async () => {
    const user = userEvent.setup();
    const pagedRows = Array.from({ length: 17 }, (_, index) => ({
      deck: `Deck ${String(index + 1).padStart(2, '0')}`,
      games: index + 1,
      winRate: '50%',
    }));

    render(
      <SortableTable
        caption="Decks"
        columns={[
          { key: 'deck', header: 'Deck' },
          { key: 'games', header: 'Games' },
        ]}
        getRowKey={(row) => row.deck}
        initialSort={{ key: 'games', direction: 'desc' }}
        pageSize={15}
        rows={pagedRows}
      />,
    );

    const table = screen.getByRole('table', { name: 'Decks' });
    expect(within(table).getByText('Deck 17')).toBeInTheDocument();
    expect(within(table).queryByText('Deck 01')).not.toBeInTheDocument();
    expect(screen.getByText('Showing 1-15 of 17')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(within(table).getByText('Deck 01')).toBeInTheDocument();
    expect(within(table).queryByText('Deck 17')).not.toBeInTheDocument();
    expect(screen.getByText('Showing 16-17 of 17')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /deck/i }));
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    expect(within(table).getByText('Deck 01')).toBeInTheDocument();
  });

  it('returns to page one when the pagination key changes', async () => {
    const user = userEvent.setup();
    const pagedRows = Array.from({ length: 17 }, (_, index) => ({
      deck: `Deck ${String(index + 1).padStart(2, '0')}`,
      games: index + 1,
      winRate: '50%',
    }));
    const { rerender } = render(
      <SortableTable
        caption="Decks"
        columns={[{ key: 'deck', header: 'Deck' }]}
        getRowKey={(row) => row.deck}
        pageSize={15}
        paginationKey=""
        rows={pagedRows}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();

    rerender(
      <SortableTable
        caption="Decks"
        columns={[{ key: 'deck', header: 'Deck' }]}
        getRowKey={(row) => row.deck}
        pageSize={15}
        paginationKey="control"
        rows={pagedRows}
      />,
    );

    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
  });
});
