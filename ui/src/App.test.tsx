import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const snapshot = {
  summary: { games: 2, wins: 1, losses: 1, draws: 0, win_rate: 50 },
  decks: [
    {
      deck_name: 'Boros Mouse',
      games: 2,
      wins: 1,
      losses: 1,
      win_rate: 50,
      deck_visual: {
        card_id: 123,
        card_name: 'Mouse Mentor',
        type_category: 'Creature',
        image_url: null,
        source: 'local_metadata',
      },
    },
  ],
  formats: [{ format_label: 'Standard Best-of-1', raw_format: 'Play', games: 2, win_rate: 50 }],
  play_draw: [{ play_draw: 'On the play', games: 1, wins: 1, losses: 0, win_rate: 100 }],
  deck_play_draw: [{ deck_name: 'Boros Mouse', play_draw: 'On the play', games: 1, wins: 1, losses: 0, win_rate: 100 }],
  draw_quality: [
    {
      started_at: '2026-06-04T00:01:00',
      deck_name: 'Boros Mouse',
      outcome: 'win',
      cards_seen: 8,
      lands_seen: 3,
      land_seen_pct: 37.5,
      opening_cards: 7,
      known_draws: 1,
    },
  ],
  drawn_cards: [
    { display_name: 'Llanowar Elves', type_category: 'Creature', times_drawn: 1, games_seen: 1, pct_of_games: 50 },
  ],
  momentum: [{ split: 'After a win', games: 1, wins: 0, losses: 1, win_rate: 0, avg_mulligans: 1, on_play_pct: 0 }],
  recent: [
    {
      started_at: '2026-06-04T00:10:00',
      deck_name: 'Boros Mouse',
      format_label: 'Standard Best-of-1',
      outcome: 'loss',
      mulligans: 1,
      duration_seconds: 300,
    },
  ],
};

describe('App', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders dashboard sections from the API and toggles theme', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })));
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();
    expect(screen.getAllByText('Boros Mouse').length).toBeGreaterThan(0);
    [
      'Decks',
      'Formats',
      'Play / Draw',
      'Deck Play / Draw',
      'Draw Quality',
      'Visible Drawn Cards',
      'Momentum',
      'Recent Games',
    ].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /switch to light mode/i }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
  });

  it('renders an error state when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })));
    render(<App />);

    expect(await screen.findByText(/Dashboard API returned 500/)).toBeInTheDocument();
  });
});
