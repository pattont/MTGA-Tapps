import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FormatsTable } from './FormatsTable';

describe('FormatsTable', () => {
  it('sorts formats alphabetically by default and omits Midweek Magic', () => {
    render(
      <FormatsTable
        caption="Format performance"
        rows={[
          {
            format_label: 'Standard Best-of-1',
            raw_formats: 'Play',
            games: 20,
            wins: 10,
            losses: 10,
            win_rate: 50,
          },
          {
            format_label: 'Midweek Magic',
            raw_formats: 'MWM_Brawl_20260623',
            games: 35,
            wins: 18,
            losses: 17,
            win_rate: 51.4,
          },
          {
            format_label: 'Alchemy Best-of-1',
            raw_formats: 'Alchemy',
            games: 2,
            wins: 1,
            losses: 1,
            win_rate: 50,
          },
          {
            format_label: 'Historic Best-of-3',
            raw_formats: 'TraditionalHistoric',
            games: 5,
            wins: 3,
            losses: 2,
            win_rate: 60,
          },
        ]}
      />,
    );

    const table = screen.getByRole('table', { name: 'Format performance' });
    expect(
      within(table)
        .getAllByRole('row')
        .slice(1)
        .map((row) => within(row).getAllByRole('cell')[0].textContent),
    ).toEqual(['Alchemy Best-of-1', 'Historic Best-of-3', 'Standard Best-of-1']);
    expect(within(table).queryByText(/Midweek Magic/i)).not.toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: /format/i })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
  });
});
