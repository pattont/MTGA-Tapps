import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { LiveDrawQuality, LiveSeenCard } from '../api';
import { LiveLandMeter } from './LiveLandMeter';
import { LiveOpponentCards } from './LiveOpponentCards';

afterEach(cleanup);

function quality(overrides: Partial<LiveDrawQuality> = {}): LiveDrawQuality {
  return {
    lands_seen: 5,
    total_cards_seen: 12,
    ramped_lands: 0,
    expected_lands_seen: 4.8,
    expected_land_rate: 40,
    deck_size: 60,
    deck_lands: 24,
    flood_probability_pct: null,
    screw_probability_pct: null,
    is_flood: false,
    is_screw: false,
    is_land_streak: false,
    reason: null,
    next_land_pct: 39.6,
    library_size: 48,
    lands_left: 19,
    ...overrides,
  };
}

describe('LiveLandMeter', () => {
  it('shows lands against expected, the gauge and the next-draw odds', () => {
    const { container } = render(<LiveLandMeter quality={quality()} />);
    expect(container.querySelector('.live-lands-count')?.textContent).toBe('5 of 12 cards were lands');
    expect(container.querySelector('.live-lands-expected')?.textContent).toBe('expected 4.8 (+0.2)');
    expect(screen.getByRole('img', { name: '5 lands in 12 cards, 4.8 expected' })).toBeTruthy();
    expect(container.querySelector('.live-lands-foot')?.textContent).toBe('Next draw 40% land · 19 of 48 left');
    // On pace: no verdict badge.
    expect(container.querySelector('.live-lands-status')).toBeNull();
    expect((container.querySelector('.live-lands') as HTMLElement).style.getPropertyValue('--lands-expected')).toBe('40%');
  });

  it('names flood and mana screw with the reason on hover, and counts ramped lands', () => {
    const flooded = quality({ lands_seen: 9, is_flood: true, reason: '9 lands in 12 cards', ramped_lands: 2 });
    const { container, rerender } = render(<LiveLandMeter quality={flooded} />);
    const badge = container.querySelector('.live-lands-status') as HTMLElement;
    expect(badge.textContent).toBe('Flooding');
    expect(badge.title).toBe('9 lands in 12 cards');
    expect(container.querySelector('.live-lands-expected')?.textContent).toBe('expected 4.8 (+4.2)');
    expect(container.querySelector('.live-lands-foot')?.textContent).toContain('2 ramped');
    rerender(<LiveLandMeter quality={quality({ lands_seen: 1, is_screw: true, next_land_pct: null })} />);
    expect(container.querySelector('.live-lands-status')?.textContent).toBe('Mana screw');
    expect(container.querySelector('.live-lands-expected')?.textContent).toBe('expected 4.8 (−3.8)');
    expect(container.querySelector('.live-lands-foot')?.textContent).toBe('');
  });
});

describe('LiveOpponentCards', () => {
  const cards: LiveSeenCard[] = [
    { name: 'Island', type: 'Land', mana_cost: null, mana_value: null, count: 3 },
    { name: 'Hallowed Fountain', type: 'Land', mana_cost: null, mana_value: null, count: 1 },
    { name: 'No More Lies', type: 'Instant', mana_cost: '{W}{U}', mana_value: 2, count: 2 },
    { name: 'Tishana\'s Tidebinder', type: 'Creature', mana_cost: '{U}{U}', mana_value: 2, count: 1 },
    { name: 'Spyglass Siren', type: 'Creature', mana_cost: '{U}', mana_value: 1, count: 1 },
  ];

  it('groups what the opponent played by type and mana value, with lands on one line', () => {
    const { container } = render(<LiveOpponentCards cards={cards} />);
    expect(screen.getByRole('heading', { name: "Opponent's Cards" })).toBeTruthy();
    expect(container.querySelector('.live-opp-count')?.textContent).toBe('8 played');
    expect(Array.from(container.querySelectorAll('.live-opp-group h4')).map((el) => el.textContent)).toEqual(['Creatures', 'Instants & sorceries', 'Lands']);
    expect(Array.from(container.querySelectorAll('.live-opp-name')).map((el) => el.textContent)).toEqual(['Spyglass Siren', "Tishana's Tidebinder", '2× No More Lies']);
    expect(container.querySelector('.live-opp-lands')?.textContent).toBe('3× Island, Hallowed Fountain');
    // Names link to the card page (with the usual hover preview).
    const link = within(container.querySelector('.live-opp-list') as HTMLElement).getByRole('link', { name: 'No More Lies' });
    expect(link.getAttribute('href')).toBe('#/card/No%20More%20Lies');
    // Costs use the dashboard's mana symbols.
    expect(container.querySelectorAll('.live-opp-group li .mana-cost')).toHaveLength(3);
  });
});
