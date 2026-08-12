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

describe('groupLimitedFormats', () => {
  it('collapses per-set limited rows under one expandable base row', async () => {
    const { groupLimitedFormats } = await import('./FormatsTable');
    const rows = [
      { format_label: 'Premier Draft - MSH', raw_formats: 'PremierDraft_MSH_20260623', games: 8, wins: 5, losses: 3, win_rate: 62.5 },
      { format_label: 'Premier Draft - HOB', raw_formats: 'PremierDraft_HOB_20260811', games: 4, wins: 1, losses: 3, win_rate: 25.0 },
      { format_label: 'Standard Ranked', raw_formats: 'Ladder', games: 100, wins: 55, losses: 45, win_rate: 55.0 },
    ];
    const grouped = groupLimitedFormats(rows);
    const premier = grouped.find((row) => row.format_label === 'Premier Draft');
    expect(premier).toBeTruthy();
    expect(premier?.games).toBe(12);
    expect(premier?.wins).toBe(6);
    expect(premier?.losses).toBe(6);
    expect(premier?.win_rate).toBe(50);
    expect(premier?.sub_rows?.map((row) => row.format_label)).toEqual(['HOB', 'MSH']);
    // Constructed rows pass through untouched, no sub-rows.
    const ladder = grouped.find((row) => row.format_label === 'Standard Ranked');
    expect(ladder).toBeTruthy();
    expect((ladder as { sub_rows?: unknown[] }).sub_rows).toBeUndefined();
  });

  it('does not split Traditional Sealed into the Sealed group', async () => {
    const { groupLimitedFormats } = await import('./FormatsTable');
    const grouped = groupLimitedFormats([
      { format_label: 'Traditional Sealed - MSH', raw_formats: 'Trad_Sealed_MSH', games: 4, wins: 2, losses: 2, win_rate: 50.0 },
      { format_label: 'Sealed - MSH', raw_formats: 'Sealed_MSH', games: 6, wins: 3, losses: 3, win_rate: 50.0 },
    ]);
    expect(grouped.map((row) => row.format_label).sort()).toEqual(['Sealed', 'Traditional Sealed']);
  });
});
