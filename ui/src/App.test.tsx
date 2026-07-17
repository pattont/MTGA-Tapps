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
  formats: [{ format_label: 'Standard Best-of-1 (Unranked)', raw_formats: 'Play, Unknown', games: 2, wins: 1, losses: 1, win_rate: 50 }],
  midweek_formats: [{ format_label: 'Midweek Magic - Slow Start', raw_formats: 'MWM_SlowStart_20260602', games: 1, wins: 1, losses: 0, win_rate: 100 }],
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
    {
      game_id: 'game-2',
      started_at: '2026-06-04T00:10:00',
      deck_name: 'Boros Mouse',
      outcome: 'loss',
      cards_seen: 10,
      lands_seen: 7,
      land_seen_pct: 70,
      opening_cards: 7,
      known_draws: 3,
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
  matches: [
    {
      match_id: 'match-1',
      started_at: '2026-06-04T00:01:00',
      raw_format: 'TraditionalLadder',
      format_label: 'Standard Best-of-3 (Ranked)',
      best_of: 3,
      deck_name: 'Boros Mouse',
      games: 3,
      wins: 2,
      losses: 1,
      record: '2-1',
      outcome: 'win',
    },
  ],
  sessions: [
    {
      session_id: 'session-1',
      started_at: '2026-06-04T00:00:00',
      ended_at: '2026-06-04T00:15:00',
      duration_seconds: 900,
      games: 2,
      wins: 1,
      losses: 1,
      draws: 0,
      win_rate: 50,
    },
  ],
  trend: [
    { game_id: 'game-1', started_at: '2026-06-04T00:01:00', outcome: 'win' },
    { game_id: 'game-2', started_at: '2026-06-04T00:10:00', outcome: 'loss' },
    { game_id: 'game-3', started_at: '2026-06-04T00:20:00', outcome: 'win' },
    { game_id: 'game-4', started_at: '2026-06-04T00:30:00', outcome: 'win' },
    { game_id: 'game-5', started_at: '2026-06-04T00:40:00', outcome: 'loss' },
    { game_id: 'game-6', started_at: '2026-06-04T00:50:00', outcome: 'win' },
  ],
  filters: { deck: null, format: null, days: null },
  filter_options: {
    decks: ['Boros Mouse', 'Izzet Wizards'],
    formats: [{ raw_format: 'Play', format_label: 'Standard Best-of-1' }],
  },
};

const deckDetail = {
  deck_name: 'Boros Mouse',
  deck_visual: {
    card_id: 123,
    card_name: 'Mouse Mentor',
    type_category: 'Creature',
    image_url: null,
    source: 'local_metadata',
  },
  summary: { games: 2, wins: 1, losses: 1, draws: 0, win_rate: 50 },
  profile: { avg_duration_seconds: 270, avg_turns: 9, avg_mulligans: 0.5, on_play_pct: 50 },
  formats: [{ format_label: 'Standard Best-of-1 (Unranked)', raw_formats: 'Play, Unknown', games: 2, wins: 1, losses: 1, win_rate: 50 }],
  midweek_formats: [{ format_label: 'Midweek Magic - Slow Start', raw_formats: 'MWM_SlowStart_20260602', games: 1, wins: 1, losses: 0, win_rate: 100 }],
  card_performance: [
    {
      display_name: 'Mouse Mentor',
      type_category: 'Creature',
      games_seen: 2,
      times_played: 3,
      times_drawn: 1,
      wins_when_seen: 1,
      losses_when_seen: 1,
      win_rate_when_seen: 50,
    },
  ],
  opening_hands: [
    { display_name: 'Mountain', type_category: 'Land', games_in_opener: 2, wins: 1, losses: 1, win_rate: 50 },
  ],
  mulligans: [{ mulligans: 0, games: 1, wins: 1, losses: 0, win_rate: 100 }],
  recent: [
    {
      game_id: 'game-1',
      started_at: '2026-06-04T00:01:00',
      outcome: 'win',
      duration_seconds: 240,
      total_turns: 8,
      raw_format: 'Play',
      format_label: 'Standard Best-of-1',
      mulligans: 0,
      play_draw: 'On the play',
    },
  ],
  trend: snapshot.trend,
};

const gameDetail = {
  game: {
    game_id: 'game-1',
    match_id: 'match-1',
    game_number: 1,
    started_at: '2026-06-04T00:01:00',
    ended_at: '2026-06-04T00:05:00',
    duration_seconds: 240,
    total_turns: 8,
    player_turns: 4,
    opponent_turns: 4,
    outcome: 'win',
    outcome_reason: 'opponent_conceded',
    raw_format: 'Play',
    format_label: 'Standard Best-of-1',
    best_of: 1,
  },
  player: {
    role: 'player',
    deck_name: 'Boros Mouse',
    went_first: 1,
    mulligans: 0,
    opening_hand_size: 7,
    starting_life: 20,
    ending_life: 12,
  },
  opponent: {
    role: 'opponent',
    starting_life: 20,
    ending_life: 0,
  },
  opening_hand: [{ display_name: 'Mountain', type_category: 'Land', hand_position: 1, copy_number: 1 }],
  drawn: [
    { display_name: 'Llanowar Elves', type_category: 'Creature', turn_number: 2, draw_position: 1, copy_number: 1 },
  ],
  draw_quality: {
    total_draws: 10,
    identified_draws: 9,
    land_draws: 7,
    land_draw_pct: 70,
    is_flood: true,
  },
  cards_played: [{ display_name: 'Mouse Mentor', type_category: 'Creature', played_count: 2 }],
  timeline: [
    {
      turn_number: 1,
      phase: 'beginning',
      step: 'upkeep',
      event_type: 'turn',
      actor_role: 'player',
      text: 'Turn 1 begins',
      player_life: 20,
      opponent_life: 20,
    },
    {
      turn_number: 4,
      phase: 'combat',
      step: 'damage',
      event_type: 'damage',
      actor_role: 'player',
      text: 'Mouse Mentor attacks',
      player_life: 12,
      opponent_life: 0,
    },
  ],
  life_curve: [
    { turn_number: 1, player_life: 20, opponent_life: 20 },
    { turn_number: 4, player_life: 12, opponent_life: 0 },
  ],
};

const cardDetail = {
  card_name: 'Mouse Mentor',
  image_url: 'https://api.scryfall.com/cards/named?fuzzy=Mouse%20Mentor&format=image&version=art_crop',
  summary: { games_seen: 2, total_played: 3, wins: 1, losses: 1, win_rate: 50 },
  all_usage: {
    games_seen: 4,
    total_played: 6,
    player_games_seen: 2,
    player_played: 3,
    opponent_games_seen: 2,
    opponent_played: 3,
  },
  by_role: [
    { role: 'player', side_label: 'You', games_seen: 2, total_played: 3, wins: 1, losses: 1, win_rate: 50 },
    { role: 'opponent', side_label: 'Opponent', games_seen: 2, total_played: 3, wins: 1, losses: 1, win_rate: 50 },
  ],
  by_deck: [
    { deck_name: 'Boros Mouse', games_seen: 2, total_played: 3, wins: 1, losses: 1, win_rate: 50 },
  ],
  opener_impact: { games_in_opener: 1, wins: 0, losses: 1, win_rate: 0, times_drawn: 1 },
};

describe('App', () => {
  beforeEach(() => {
    window.location.hash = '';
    window.scrollTo = vi.fn();
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
      ['Overview', '#overview'],
      ['Win Rate Trend', '#trend'],
      ['Recent Games', '#recent-games'],
      ['Decks', '#decks'],
      ['Formats', '#formats'],
      ['Deck Play / Draw', '#deck-play-draw'],
      ['Visible Drawn Cards', '#visible-drawn-cards'],
      ['Bo3 Matches', '#matches'],
      ['Sessions', '#sessions'],
    ].forEach(([label, href]) => {
      expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', href);
    });

    [
      'Win Rate Trend',
      'Decks',
      'Formats',
      'Play / Draw',
      'Deck Play / Draw',
      'Visible Drawn Cards',
      'Momentum',
      'Recent Games',
      'Best-of-3 Matches',
      'Sessions',
    ].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });
    expect(screen.getByRole('table', { name: 'Best-of-3 matches' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Tracker sessions' })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Draw quality by game' })).not.toBeInTheDocument();
    const dashboardNav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    expect(within(dashboardNav).getAllByRole('link').slice(0, 3).map((link) => link.textContent)).toEqual([
      'Overview',
      'Win Rate Trend',
      'Recent Games',
    ]);
    expect(
      Array.from(document.querySelectorAll<HTMLElement>('.dashboard-main > section[id]')).map(
        (section) => section.id,
      ),
    ).toEqual([
      'overview',
      'trend',
      'recent-games',
      'decks',
      'formats',
      'deck-play-draw',
      'visible-drawn-cards',
      'matches',
      'sessions',
    ]);
    const overviewSection = document.getElementById('overview');
    expect(overviewSection).not.toBeNull();
    expect(within(overviewSection as HTMLElement).getByRole('table', { name: 'Play and draw performance' })).toBeInTheDocument();
    expect(within(overviewSection as HTMLElement).getByRole('table', { name: 'Momentum splits' })).toBeInTheDocument();
    expect(within(dashboardNav).queryByRole('link', { name: 'Play / Draw' })).not.toBeInTheDocument();
    expect(within(dashboardNav).queryByRole('link', { name: 'Momentum' })).not.toBeInTheDocument();

    const trendLink = within(dashboardNav).getByRole('link', { name: 'Win Rate Trend' });
    await user.click(trendLink);
    expect(trendLink).toHaveClass('active');
    const overviewLink = within(dashboardNav).getByRole('link', { name: 'Overview' });
    await user.click(overviewLink);
    expect(overviewLink).toHaveClass('active');
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0 });

    await user.click(screen.getByRole('button', { name: /switch to light mode/i }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
  });

  it('links every deck mention to the deck detail page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })));
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();
    // Decks table, Best Deck metric, Deck Play / Draw, Recent Games, and Matches.
    const deckLinks = screen.getAllByRole('link', { name: 'Boros Mouse' });
    expect(deckLinks.length).toBe(5);
    deckLinks.forEach((link) => {
      expect(link).toHaveAttribute('href', '#/deck/Boros%20Mouse');
    });
  });

  it('routes to the deck detail page and back to the dashboard', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/deck')) {
        return new Response(JSON.stringify(deckDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Boros Mouse' }).length).toBeGreaterThan(0);

    await act(async () => {
      window.location.hash = '#/deck/Boros%20Mouse';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    expect((await screen.findAllByRole('heading', { name: 'Boros Mouse' })).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledWith('/api/deck?name=Boros+Mouse', expect.anything());
    expect(document.title).toBe('Boros Mouse – MTGA Tracker');
    ['Win Rate Trend', 'Card Performance', 'Opening Hands', 'Mulligans', 'Formats', 'Recent Games'].forEach(
      (sectionName) => {
        expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
      },
    );
    expect(screen.getAllByText('Mouse Mentor').length).toBeGreaterThan(0);
    expect(screen.getByText('Signature card: Mouse Mentor')).toBeInTheDocument();

    const nav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    expect(within(nav).getByRole('link', { name: '← Back to dashboard' })).toHaveAttribute('href', '#overview');
    ['Win Rate Trend', 'Card Performance', 'Opening Hands', 'Mulligans', 'Formats', 'Recent Games'].forEach(
      (label) => {
        expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument();
      },
    );

    await act(async () => {
      window.location.hash = '#overview';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    expect(await screen.findByLabelText('Overview metrics')).toBeInTheDocument();
    expect(document.title).toBe('MTGA Tracker Dashboard');
    expect(screen.queryByRole('heading', { name: 'Card Performance' })).not.toBeInTheDocument();
  });

  it('carries dashboard filters into deck links and deck detail fetches', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/deck')) {
        return new Response(JSON.stringify(deckDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Format'), 'Play');
    await user.selectOptions(screen.getByLabelText('Period'), '30');
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith('/api/snapshot?format=Play&days=30', expect.anything()),
    );

    expect(screen.getAllByRole('link', { name: 'Boros Mouse' })[0]).toHaveAttribute(
      'href',
      '#/deck/Boros%20Mouse?format=Play&days=30',
    );

    await act(async () => {
      window.location.hash = '#/deck/Boros%20Mouse?format=Play&days=30';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    expect((await screen.findAllByRole('heading', { name: 'Boros Mouse' })).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledWith('/api/deck?name=Boros+Mouse&format=Play&days=30', expect.anything());
    screen.getAllByRole('link', { name: '← Back to dashboard' }).forEach((link) => {
      expect(link).toHaveAttribute('href', '#overview?format=Play&days=30');
    });

    await act(async () => {
      window.location.hash = '#overview?format=Play&days=30';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith('/api/snapshot?format=Play&days=30', expect.anything()),
    );
  });

  it('filters deck and visible drawn card tables by text', async () => {
    const expandedSnapshot = {
      ...snapshot,
      decks: [
        ...snapshot.decks,
        {
          deck_name: 'Izzet Wizards',
          games: 1,
          wins: 1,
          losses: 0,
          win_rate: 100,
          deck_visual: {
            card_id: null,
            card_name: 'Slickshot Show-Off',
            type_category: 'Creature',
            image_url: null,
            source: 'local_metadata',
          },
        },
      ],
      drawn_cards: [
        ...snapshot.drawn_cards,
        { display_name: 'Slickshot Show-Off', type_category: 'Creature', times_drawn: 2, games_seen: 1, pct_of_games: 50 },
      ],
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(expandedSnapshot), { status: 200 })));
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Search decks'), 'izzet');
    const deckTable = screen.getByRole('table', { name: 'Deck performance' });
    expect(within(deckTable).getByText('Izzet Wizards')).toBeInTheDocument();
    expect(within(deckTable).queryByText('Boros Mouse')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Search cards'), 'slick');
    const cardTable = screen.getByRole('table', { name: 'Visible drawn card frequency' });
    expect(within(cardTable).getByText('Slickshot Show-Off')).toBeInTheDocument();
    expect(within(cardTable).queryByText('Llanowar Elves')).not.toBeInTheDocument();
  });

  it('shows setup guidance when there are no tracked games yet', async () => {
    const emptySnapshot = {
      ...snapshot,
      summary: { games: 0, wins: 0, losses: 0, draws: 0, win_rate: null },
      decks: [],
      formats: [],
      play_draw: [],
      deck_play_draw: [],
      draw_quality: [],
      drawn_cards: [],
      momentum: [],
      recent: [],
      matches: [],
      sessions: [],
      trend: [],
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(emptySnapshot), { status: 200 })));
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'No tracked games yet' })).toBeInTheDocument();
    expect(screen.getByText('venv/bin/python -m mtga_tracker.main')).toBeInTheDocument();
    expect(screen.getByText('venv/bin/python -m mtga_tracker.dashboard')).toBeInTheDocument();
  });

  it('links game rows to the game detail page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })));
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();

    expect(screen.getByRole('link', { name: /Jun 4.*12:10 AM/i })).toHaveAttribute(
      'href',
      '#/game/game-2?return=%23recent-games',
    );
    const recentTable = screen.getByRole('table', { name: 'Recent games' });
    expect(within(recentTable).getByRole('columnheader', { name: /Cards Seen/i })).toBeInTheDocument();
    expect(within(recentTable).getByRole('columnheader', { name: /Lands Seen/i })).toBeInTheDocument();
    expect(within(recentTable).getByText('70%')).toBeInTheDocument();
  });

  it('returns from a game to the dashboard section that opened it', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/game')) {
        return new Response(JSON.stringify(gameDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      render(<App />);
      const recentTable = await screen.findByRole('table', { name: 'Recent games' });
      await user.click(within(recentTable).getByRole('link', { name: /Jun 4.*12:10 AM/i }));

      expect(await screen.findByRole('heading', { name: /Game Jun 4/i })).toBeInTheDocument();
      const backLinks = screen.getAllByRole('link', { name: '← Back to dashboard' });
      backLinks.forEach((link) => expect(link).toHaveAttribute('href', '#recent-games'));
      await user.click(backLinks[0]);

      await waitFor(() => expect(window.location.hash).toBe('#recent-games'));
      expect(await screen.findByRole('table', { name: 'Recent games' })).toBeInTheDocument();
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' }));
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it('routes to the game detail page and renders game sections', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/game')) {
        return new Response(JSON.stringify(gameDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    window.location.hash = '#/game/game-1';

    render(<App />);

    expect(await screen.findByRole('heading', { name: /Game Jun 4/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/game?id=game-1', expect.anything());
    expect(document.title).toContain('Game Jun 4');
    ['Draw Quality', 'Life Totals', 'Opening Hand', 'Drawn Cards', 'Cards Played', 'Timeline'].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });
    expect(screen.getByText('70%')).toBeInTheDocument();
    expect(screen.getAllByText('Flood').length).toBeGreaterThan(0);
    expect(screen.getByText('Turn 1 begins')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Boros Mouse' })).toHaveAttribute('href', '#/deck/Boros%20Mouse');
  });

  it('links card names to the card detail page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })));
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Llanowar Elves' })).toHaveAttribute('href', '#/card/Llanowar%20Elves');
  });

  it('searches all tracked cards and opens the selected card detail', async () => {
    const shelteredDetail = {
      ...cardDetail,
      card_name: 'Sheltered by Ghosts',
      image_url: null,
    };
    const searchResults = [
      {
        card_name: 'Sheltered by Ghosts',
        type_category: 'Enchantment',
        games_seen: 12,
        deck_count: 2,
        total_played: 9,
        last_seen_at: '2026-06-04T00:10:00',
      },
    ];
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/cards')) {
        return new Response(JSON.stringify(searchResults), { status: 200 });
      }
      if (String(url).startsWith('/api/card')) {
        return new Response(JSON.stringify(shelteredDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText('MTGA Tracker');
    await user.type(screen.getByRole('combobox', { name: 'Search by card name' }), 'Sheltered by Ghosts');

    const result = await screen.findByRole('option', { name: /Sheltered by Ghosts.*12 games.*9 played/i });
    expect(result).toHaveAttribute('href', '#/card/Sheltered%20by%20Ghosts');
    await user.click(result);

    expect((await screen.findAllByRole('heading', { name: 'Sheltered by Ghosts' })).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Card Summary' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/card?name=Sheltered+by+Ghosts', expect.anything());
  });

  it('routes to the card detail page and renders card sections', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/card')) {
        return new Response(JSON.stringify(cardDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    window.location.hash = '#/card/Mouse%20Mentor';

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Mouse Mentor' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/card?name=Mouse+Mentor', expect.anything());
    expect(document.title).toBe('Mouse Mentor – MTGA Tracker');
    ['Card Summary', 'Usage by Side', 'Your Decks', 'Opening Hand Impact'].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: 'Boros Mouse' })).toHaveAttribute('href', '#/deck/Boros%20Mouse');
  });

  it('shows an error with a way back when the deck detail API fails', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/deck')) {
        return new Response('missing', { status: 404 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    window.location.hash = '#/deck/Missing%20Deck';
    render(<App />);

    expect(await screen.findByText(/No recorded games for deck: Missing Deck/)).toBeInTheDocument();
    const backLinks = screen.getAllByRole('link', { name: /back to dashboard/i });
    expect(backLinks.length).toBeGreaterThan(0);
    backLinks.forEach((link) => {
      expect(link).toHaveAttribute('href', '#overview');
    });
  });

  it('refetches with query params when filters change', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith('/api/snapshot', expect.anything());

    await user.selectOptions(screen.getByLabelText('Deck'), 'Boros Mouse');
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith('/api/snapshot?deck=Boros+Mouse', expect.anything()),
    );

    await user.selectOptions(screen.getByLabelText('Period'), '30');
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith('/api/snapshot?deck=Boros+Mouse&days=30', expect.anything()),
    );

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith('/api/snapshot', expect.anything()));
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
