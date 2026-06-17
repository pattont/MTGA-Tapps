import { act, render, screen, waitFor, within } from '@testing-library/react';
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
      game_id: 'game-1',
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
      game_id: 'game-2',
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
    vi.useRealTimers();
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

  it('refreshes the dashboard snapshot on an interval', async () => {
    vi.useFakeTimers();
    const updatedSnapshot = {
      ...snapshot,
      summary: { ...snapshot.summary, games: 3 },
      decks: [{ ...snapshot.decks[0], games: 3 }],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(updatedSnapshot), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await act(async () => {});
    const overview = screen.getByLabelText('Overview metrics');
    expect(within(overview).getByText('Games').closest('article')).toHaveTextContent('2');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(within(overview).getByText('Games').closest('article')).toHaveTextContent('3');
  });

  it('keeps the loaded dashboard visible when a refresh fails', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot), { status: 200 }))
      .mockResolvedValueOnce(new Response('locked', { status: 500 }));
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await act(async () => {});
    const overview = screen.getByLabelText('Overview metrics');
    expect(within(overview).getByText('Games').closest('article')).toHaveTextContent('2');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(within(overview).getByText('Games').closest('article')).toHaveTextContent('2');
    expect(screen.getByRole('status')).toHaveTextContent('Latest refresh failed: Dashboard API returned 500');
  });

  it('aborts a stale refresh before starting the next poll', async () => {
    vi.useFakeTimers();
    const latestSnapshot = {
      ...snapshot,
      summary: { ...snapshot.summary, games: 4 },
      decks: [{ ...snapshot.decks[0], games: 4 }],
    };
    let callCount = 0;
    let staleSignal: AbortSignal | undefined;
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      callCount += 1;
      if (callCount === 1) {
        return Promise.resolve(new Response(JSON.stringify(snapshot), { status: 200 }));
      }
      if (callCount === 2) {
        staleSignal = init?.signal ?? undefined;
        return new Promise<Response>(() => {});
      }
      return Promise.resolve(new Response(JSON.stringify(latestSnapshot), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    await act(async () => {});
    const overview = screen.getByLabelText('Overview metrics');
    expect(within(overview).getByText('Games').closest('article')).toHaveTextContent('2');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(staleSignal?.aborted).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(staleSignal?.aborted).toBe(true);
    expect(within(overview).getByText('Games').closest('article')).toHaveTextContent('4');
  });
});
