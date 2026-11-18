import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { LiveGameRow, LivePayload } from '../api';
import { LiveTodayPanel } from './LiveTodayPanel';

const NOW = new Date(2026, 10, 9, 21, 0, 0).getTime();

function payload(overrides: Partial<LivePayload> = {}): LivePayload {
  return {
    tracker: { state: 'idle' },
    now: null,
    today: {
      date: '2026-11-09',
      games: 3,
      wins: 2,
      losses: 1,
      draws: 0,
      win_rate: 66.7,
      started_at: '2026-11-09T20:00:00',
      play: { wins: 2, losses: 0 },
      draw: { wins: 0, losses: 1 },
      decks: [{ deck_name: 'Boros Dragons', wins: 2, losses: 1 }],
      flood_games: 1,
      screw_games: 0,
    },
    games: [
      { id: 'S2:g3', outcome: 'win', started_at: '2026-11-09T20:40:00' },
      { id: 'S2:g2', outcome: 'win', started_at: '2026-11-09T20:20:00' },
      { id: 'S2:g1', outcome: 'loss', started_at: '2026-11-09T20:00:00' },
    ] as LiveGameRow[],
    events: [],
    seq: 0,
    ...overrides,
  } as LivePayload;
}

const tile = (label: RegExp) => screen.getByText(label).closest('.live-stat') as HTMLElement;

describe('LiveTodayPanel', () => {
  afterEach(cleanup);

  it("shows today's record, both sides of the coin flip, streak, flood and screw games, and decks", () => {
    const { container } = render(<LiveTodayPanel payload={payload()} nowMs={NOW} />);
    expect(screen.getByRole('heading', { name: 'Today' })).toBeTruthy();
    // Today is the only span: no Session | Today switch.
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByLabelText('2 wins, 1 losses').textContent).toBe('2–1');
    expect(container.querySelector('.live-today-rate')?.textContent).toBe('66.7%');
    expect(container.querySelector('.live-today-games')?.textContent).toBe('3 games');
    expect((container.querySelector('.live-today-bar i') as HTMLElement).style.width).toMatch(/^66\.6/);
    expect(tile(/On the play/).textContent).toBe('2–0On the play · 100%');
    expect(tile(/On the draw/).textContent).toBe('0–1On the draw · 0%');
    expect(tile(/Streak/).textContent).toBe('W2Streak');
    expect(tile(/Flood/).textContent).toBe('1Flood');
    expect(tile(/Mana screw/).textContent).toBe('0Mana screw');
    const decks = container.querySelector('.live-today-decks') as HTMLElement;
    expect(within(decks).getByRole('link', { name: 'Boros Dragons' })).toBeTruthy();
    expect(decks.querySelector('li')?.textContent).toBe('Boros Dragons2–166.7%');
  });

  it('leaves out what has no games yet', () => {
    const empty = payload({ games: [] });
    empty.today = {
      ...empty.today!,
      games: 0,
      wins: 0,
      losses: 0,
      win_rate: null,
      started_at: null,
      play: { wins: 0, losses: 0 },
      draw: { wins: 0, losses: 0 },
      decks: [],
      flood_games: undefined,
      screw_games: undefined,
    };
    const { container } = render(<LiveTodayPanel payload={empty} nowMs={NOW} />);
    expect(container.querySelector('.live-today-record')?.textContent).toBe('0–0');
    expect(container.querySelector('.live-today-rate')).toBeNull();
    expect(container.querySelector('.live-today-bar')).toBeNull();
    expect(tile(/On the play/).textContent).toBe('—On the play');
    expect(tile(/Streak/).textContent).toBe('—Streak');
    // An older tracker does not count flood and screw games.
    expect(tile(/Flood/).textContent).toBe('—Flood');
    expect(tile(/Mana screw/).textContent).toBe('—Mana screw');
    expect(container.querySelector('.live-today-decks')).toBeNull();
  });

  it('folds a long deck list and says so before anything is recorded', () => {
    const many = payload();
    many.today = { ...many.today!, decks: Array.from({ length: 8 }, (_, i) => ({ deck_name: `Deck ${i + 1}`, wins: 1, losses: 0 })) };
    const { container, rerender } = render(<LiveTodayPanel payload={many} nowMs={NOW} />);
    expect(container.querySelectorAll('.live-today-decks li')).toHaveLength(6);
    expect(container.querySelector('.live-today-more')?.textContent).toBe('+2 more');
    rerender(<LiveTodayPanel payload={payload({ today: null })} nowMs={NOW} />);
    expect(screen.getByText('Nothing recorded yet.')).toBeTruthy();
  });
});
