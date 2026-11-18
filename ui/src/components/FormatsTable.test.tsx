import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { FormatRow } from '../api';
import { FormatsTable, formatGroup } from './FormatsTable';

describe('FormatsTable', () => {
  it('sorts formats alphabetically by default and omits Midweek Magic', () => {
    render(
      <FormatsTable
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

    // Only constructed games: one table under its heading.
    expect(screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)).toEqual(['Constructed']);
    const table = screen.getByRole('table', { name: 'Constructed formats' });
    expect(
      within(table)
        .getAllByRole('row')
        .slice(1)
        .map((row) => within(row).getAllByRole('cell')[0].textContent),
    ).toEqual(['Alchemy BO1', 'Historic BO3', 'Standard BO1']);
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

  it('splits Constructed from Limited into two tables, each with its own header and sort', () => {
    const row = (format_label: string, games: number): FormatRow => ({
      format_label,
      raw_formats: format_label,
      games,
      wins: games,
      losses: 0,
      win_rate: 100,
    });
    render(
      <FormatsTable
        rows={[
          row('Sealed - MSH', 10),
          row('Standard BO1 (Ranked)', 423),
          row('Premier Draft - MSH', 8),
          row('Brawl', 1),
          row('Qualifier Play In Bo1 Timeless', 3),
          row('Powered Cube', 5),
        ]}
      />,
    );
    expect(screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)).toEqual(['Constructed', 'Limited']);
    const names = (caption: string) =>
      within(screen.getByRole('table', { name: caption }))
        .getAllByRole('row')
        .slice(1)
        .map((tr) => within(tr).getAllByRole('cell')[0].textContent);
    expect(names('Constructed formats')).toEqual(['Brawl', 'Qualifier Play In Bo1 Timeless', 'Standard BO1 (Ranked)']);
    expect(names('Limited formats')).toEqual(['Powered Cube', 'Premier Draft', 'Sealed']);
    // Each table has Format / Games / Win Rate; sorting one leaves the other alone.
    const limited = screen.getByRole('table', { name: 'Limited formats' });
    expect(within(limited).getAllByRole('columnheader').map((th) => th.textContent?.replace(/[↑↓↕]/g, '').trim())).toEqual([
      'Format',
      'Games',
      'Win Rate',
    ]);
    fireEvent.click(within(limited).getByRole('button', { name: /^games/i }));
    expect(new Set(names('Limited formats'))).toEqual(new Set(['Powered Cube', 'Premier Draft', 'Sealed']));
    expect(names('Constructed formats')).toEqual(['Brawl', 'Qualifier Play In Bo1 Timeless', 'Standard BO1 (Ranked)']);
  });

  it('keeps one empty Constructed section when there are no games', () => {
    render(<FormatsTable rows={[]} />);
    expect(screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)).toEqual(['Constructed']);
    expect(screen.getByText('No rows yet.')).toBeInTheDocument();
  });

  it('names the group of a format', () => {
    expect(formatGroup('Quick Draft - EOE')).toBe('Limited');
    expect(formatGroup('Arena Cube')).toBe('Limited');
    expect(formatGroup('Traditional Sealed')).toBe('Limited');
    expect(formatGroup('Historic BO3')).toBe('Constructed');
    expect(formatGroup('Brawl (Ranked)')).toBe('Constructed');
  });
});
