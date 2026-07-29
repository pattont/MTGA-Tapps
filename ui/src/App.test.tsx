import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { cardRouteHash, gameRouteHash } from './routes';

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
  formats: [
    { format_label: 'Standard Best-of-1 (Unranked)', raw_formats: 'Play, Unknown', games: 2, wins: 1, losses: 1, win_rate: 50 },
    { format_label: 'Midweek Magic', raw_formats: 'MWM_Brawl_20260623', games: 35, wins: 18, losses: 17, win_rate: 51.4 },
  ],
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
      land_seen_pct: 70.1,
      opening_cards: 7,
      known_draws: 3,
    },
  ],
  drawn_cards: [
    { display_name: 'Llanowar Elves', type_category: 'Creature', times_drawn: 1, games_seen: 1, pct_of_games: 50 },
  ],
  momentum: [{ split: 'After a win', games: 1, wins: 0, losses: 1, win_rate: 0, avg_mulligans: 1, on_play_pct: 0 }],
  combat_decks: [
    {
      deck_name: 'Boros Mouse',
      games: 2,
      wins: 1,
      losses: 1,
      win_rate: 50,
      avg_damage_dealt: 14.5,
      avg_damage_taken: 12,
      avg_attack_steps: 3,
      attackers_per_attack: 2.17,
      attackers_lost: 3,
      blockers_lost: 3,
      trade_ratio: 1,
      avg_life_gained: 2,
      avg_player_turns: 4.5,
      aggression_profile: 'Aggro' as const,
    },
  ],
  schedule: {
    by_weekday: [
      { label: 'Thursday', weekday: 4, games: 2, wins: 1, losses: 1, win_rate: 50 },
    ],
    by_time_of_day: [
      { label: 'Late Night (10pm–5am)', bucket: 3, games: 2, wins: 1, losses: 1, win_rate: 50 },
    ],
  },
  fatigue: [{ bucket: 0, label: 'Games 1–2', games: 2, wins: 1, losses: 1, win_rate: 50 }],
  streaks: {
    games: 2,
    current: { kind: 'loss', length: 1 },
    longest_win: 1,
    longest_loss: 1,
  },
  outcome_reasons: [{ reason: 'opponent_conceded', wins: 1, losses: 0, games: 1 }],
  opener_lands: [{ lands: 1, label: '1 land', games: 1, wins: 1, losses: 0, win_rate: 100 }],
  opponent_threats: [
    {
      display_name: 'Graveyard Trespasser',
      type_category: 'Creature',
      games: 2,
      plays: 3,
      wins: 1,
      losses: 1,
      loss_rate: 50,
    },
  ],
  matchups: [
    {
      deck_name: 'Boros Mouse',
      opponent_archetype: 'Dimir Midrange',
      games: 1,
      wins: 0,
      losses: 1,
      win_rate: 0,
    },
  ],
  mana_readiness: [
    {
      threshold: 2,
      label: '2 lands by turn 2',
      games: 2,
      on_time_games: 1,
      on_time_pct: 50,
      on_time_win_rate: 0,
      behind_games: 1,
      behind_win_rate: 100,
    },
  ],
  combat_split: [
    {
      split: 'Wins',
      games: 1,
      avg_damage_dealt: 20,
      avg_damage_taken: 6,
      avg_attack_steps: 4,
      avg_life_gained: 3,
      avg_cards_drawn: 9,
      avg_cards_denied: 1,
    },
    {
      split: 'Losses',
      games: 1,
      avg_damage_dealt: 9,
      avg_damage_taken: 18,
      avg_attack_steps: 2,
      avg_life_gained: 1,
      avg_cards_drawn: 10,
      avg_cards_denied: 5,
    },
  ],
  recent: [
    {
      game_id: 'game-2',
      started_at: '2026-06-04T00:10:00',
      deck_name: 'Boros Mouse',
      format_label: 'Standard Best-of-1',
      outcome: 'loss',
      mulligans: 1,
      duration_seconds: 300,
      total_turns: 10,
      flood_reasons: ['3 of 3 post-opening draws were lands'],
      is_flood: true,
      screw_reasons: [],
      is_screw: false,
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
  rank_progress: [
    {
      id: 1,
      captured_at: '2026-06-04T00:05:01',
      season_ordinal: 91,
      rank_class: 'Platinum',
      rank_level: 3,
      rank_step: 4,
      rank_steps: 6,
      raw_step: 4,
      rank_score: 82,
      rank_label: 'Platinum 3 (4/6)',
      matches_won: 60,
      matches_lost: 43,
      mythic_percentile: null,
      mythic_rank: null,
      game_id: 'game-1',
      outcome: 'win',
      best_of: 1,
      deck_name: 'Boros Mouse',
    },
  ],
  filters: { deck: null, format: null, days: null },
  filter_options: {
    decks: ['Boros Mouse', 'Izzet Wizards'],
    formats: [
      { raw_format: 'Play', format_label: 'Standard Best-of-1' },
      { raw_format: 'MWM_Brawl_20260623', format_label: 'Midweek Magic - Brawl' },
    ],
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
  deck_export: {
    available: true,
    source_game_id: 'game-1',
    main_deck: [
      { display_name: 'Mountain', quantity: 20, type_category: 'Land' },
      { display_name: 'Mouse Mentor', quantity: 4, type_category: 'Creature' },
    ],
    sideboard: [{ display_name: 'Duress', quantity: 1, type_category: 'Sorcery' }],
    text: 'About\nName Boros Mouse\n\nDeck\n20 Mountain\n4 Mouse Mentor\n\nSideboard\n1 Duress',
  },
  summary: { games: 2, wins: 1, losses: 1, draws: 0, win_rate: 50 },
  profile: { avg_duration_seconds: 270, avg_turns: 9, avg_mulligans: 0.5, on_play_pct: 50 },
  composition: [
    {
      display_name: 'Mouse Mentor',
      type_category: 'Creature',
      copies: 4,
      games_in_deck: 2,
      games_seen: 2,
      times_seen: 3,
      seen_pct: 100,
      expected_seen: 1.6,
      seen_delta: 1.4,
      wins_when_seen: 1,
      losses_when_seen: 1,
      win_rate_when_seen: 50,
      wins_when_not_seen: 0,
      losses_when_not_seen: 0,
      win_rate_when_not_seen: null,
    },
  ],
  versions: [
    {
      version: 1,
      first_played: '2026-06-04T00:01:00',
      last_played: '2026-06-04T00:01:00',
      games: 1,
      wins: 1,
      losses: 0,
      win_rate: 100,
      added: [],
      removed: [],
    },
    {
      version: 2,
      first_played: '2026-06-04T00:10:00',
      last_played: '2026-06-04T00:10:00',
      games: 1,
      wins: 0,
      losses: 1,
      win_rate: 0,
      added: ['2x Sheltered by Ghosts'],
      removed: ['2x Mouse Mentor'],
    },
  ],
  mana_readiness: [
    {
      threshold: 3,
      label: '3 lands by turn 3',
      games: 2,
      on_time_games: 2,
      on_time_pct: 100,
      on_time_win_rate: 50,
      behind_games: 0,
      behind_win_rate: null,
    },
  ],
  sideboard: {
    matches: 1,
    game_one: { wins: 1, losses: 0, win_rate: 100 },
    post_board: { wins: 0, losses: 1, win_rate: 0 },
    boarded_in: [{ display_name: 'Sheltered by Ghosts', copies: 2 }],
  },
  combat_profile: {
    deck_name: 'Boros Mouse',
    games: 2,
    wins: 1,
    losses: 1,
    win_rate: 50,
    avg_damage_dealt: 14.5,
    avg_damage_taken: 12,
    avg_attack_steps: 3,
    attackers_per_attack: 2.17,
    attackers_lost: 3,
    blockers_lost: 3,
    trade_ratio: 1,
    avg_life_gained: 2,
    avg_player_turns: 4.5,
    aggression_profile: 'Aggro' as const,
  },
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
      player_avg_turn_seconds: 30,
      opponent_avg_turn_seconds: 30,
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
    display_name: 'Opponent',
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
  participant_stats: [
    {
      role: 'player',
      attack_steps: 4,
      attacking_creatures: 9,
      attackers_lost: 1,
      blocking_creatures: 2,
      blockers_lost: 3,
      damage_dealt: 20,
      damage_taken: 6,
      life_lost: 8,
      self_damage: 2,
      life_gained: 3,
      cards_played: 12,
      cards_drawn: 9,
      cards_discarded: 0,
      cards_milled: 0,
      cards_exiled: 1,
    },
    {
      role: 'opponent',
      attack_steps: 2,
      attacking_creatures: 3,
      attackers_lost: 3,
      blocking_creatures: 4,
      blockers_lost: 1,
      damage_dealt: 8,
      damage_taken: 18,
      life_lost: 20,
      self_damage: 2,
      life_gained: 0,
      cards_played: 10,
      cards_drawn: 8,
      cards_discarded: 1,
      cards_milled: 0,
      cards_exiled: 0,
    },
  ],
  turn_timing: {
    player: { total_seconds: 60, turns_timed: 2, avg_seconds: 30 },
    opponent: { total_seconds: 30, turns_timed: 1, avg_seconds: 30 },
  },
  turns: [
    {
      turn_number: 1,
      seat_id: 1,
      role: 'player',
      started_at: '2026-06-04T00:01:00',
      ended_at: '2026-06-04T00:01:40',
      duration_seconds: 40,
      timing_source: 'live',
    },
    {
      turn_number: 2,
      seat_id: 2,
      role: 'opponent',
      started_at: '2026-06-04T00:01:40',
      ended_at: '2026-06-04T00:02:10',
      duration_seconds: 30,
      timing_source: 'estimated_header_events',
    },
    {
      turn_number: 3,
      seat_id: 1,
      role: 'player',
      started_at: '2026-06-04T00:02:10',
      ended_at: '2026-06-04T00:02:30',
      duration_seconds: 20,
      timing_source: 'live',
    },
  ],
  cards_played: [{ display_name: 'Mouse Mentor', type_category: 'Creature', played_count: 2 }],
  opponent_cards: [
    {
      display_name: 'Graveyard Trespasser',
      type_category: 'Creature',
      played_count: 1,
      drawn_count: 0,
      discarded_count: 1,
      milled_count: 0,
      exiled_count: 1,
    },
  ],
  timeline: [
    {
      turn_number: 1,
      phase: 'beginning',
      step: 'upkeep',
      event_type: 'turn',
      actor_role: 'player',
      text: 'Turn 1 begins',
      text_segments: [{ kind: 'text', text: 'Turn 1 begins' }],
      player_life: 20,
      opponent_life: 20,
    },
    {
      turn_number: 4,
      phase: 'combat',
      step: 'damage',
      event_type: 'damage',
      actor_role: 'player',
      text: '[0:20] [Mouse Mentor (2/1)] attacked [Graveyard Trespasser (3/3)] [resolved] [you] [Skeleton Pirate]',
      text_segments: [
        { kind: 'text', text: '[0:20] [' },
        { kind: 'card', text: 'Mouse Mentor', card_name: 'Mouse Mentor', card_type: 'Creature' },
        { kind: 'text', text: ' (2/1)] attacked [' },
        {
          kind: 'card',
          text: 'Graveyard Trespasser',
          card_name: 'Graveyard Trespasser',
          card_type: 'Creature',
        },
        { kind: 'text', text: ' (3/3)] [resolved] [you] [Skeleton Pirate]' },
      ],
      player_life: 12,
      opponent_life: 0,
    },
  ],
  life_curve: [
    { turn_number: 1, player_life: 20, opponent_life: 20 },
    { turn_number: 4, player_life: 12, opponent_life: 0 },
  ],
};

const opponentDetail = {
  opponent_name: 'Opponent',
  summary: { games: 2, wins: 1, losses: 1, draws: 0, win_rate: 50 },
  games: [
    {
      game_id: 'game-2',
      started_at: '2026-06-04T00:10:00',
      outcome: 'loss',
      duration_seconds: 300,
      total_turns: 10,
      player_turns: 5,
      opponent_turns: 5,
      raw_format: 'Play',
      format_label: 'Standard Best-of-1 (Unranked)',
      best_of: 1,
      deck_name: 'Boros Mouse',
      play_draw: 'On the draw',
      player_final_life: 0,
      opponent_final_life: 7,
    },
    {
      game_id: 'game-1',
      started_at: '2026-06-04T00:01:00',
      outcome: 'win',
      duration_seconds: 240,
      total_turns: 8,
      player_turns: 4,
      opponent_turns: 4,
      raw_format: 'Play',
      format_label: 'Standard Best-of-1 (Unranked)',
      best_of: 1,
      deck_name: 'Boros Mouse',
      play_draw: 'On the play',
      player_final_life: 12,
      opponent_final_life: 0,
    },
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
  opponent_impact: { games: 2, plays: 3, wins: 1, losses: 1, win_rate: 50, loss_rate: 50 },
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
    expect(screen.getByRole('link', { name: 'MTGA Tracker – Go to overview' })).toHaveAttribute(
      'href',
      '#overview',
    );
    expect(
      Array.from(document.querySelectorAll<HTMLImageElement>('.mana-pip')).map((image) =>
        image.getAttribute('src'),
      ),
    ).toEqual([
      '/icons/W.svg',
      '/icons/U.svg',
      '/icons/B.svg',
      '/icons/R.svg',
      '/icons/G.svg',
    ]);
    expect(screen.getByRole('heading', { name: 'Performance Overview' })).toBeInTheDocument();
    expect(screen.queryByText(/SQLite analytics/i)).not.toBeInTheDocument();
    expect(document.title).toBe('MTGA Tracker – Overview');
    expect(screen.getByText('50% WR · 1–1 · 2 games')).toBeInTheDocument();
    expect(screen.getAllByText('Boros Mouse').length).toBeGreaterThan(0);
    [
      ['Overview', '#overview'],
      ['Win Rate Trend', '#trend'],
      ['Recent Games', '#recent-games'],
      ['Decks', '#decks'],
      ['Formats', '#formats'],
      ['Sessions', '#sessions'],
    ].forEach(([label, href]) => {
      expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', href);
    });

    [
      'Win Rate Trend',
      'Decks',
      'Formats',
      'Play / Draw',
      'Momentum',
      'Recent Games',
      'Sessions',
    ].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });
    expect(screen.getByRole('table', { name: 'Tracker sessions' })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Draw quality by game' })).not.toBeInTheDocument();
    const dashboardNav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    expect(within(dashboardNav).getAllByRole('link').slice(0, 4).map((link) => link.textContent)).toEqual([
      'Overview',
      'Win Rate Trend',
      'Ranked Progress',
      'Recent Games',
    ]);
    expect(
      Array.from(document.querySelectorAll<HTMLElement>('.dashboard-main > section[id]')).map(
        (section) => section.id,
      ),
    ).toEqual([
      'overview',
      'trend',
      'rank-progress',
      'recent-games',
      'decks',
      'land-drops',
      'habits',
      'outcomes',
      'opponent-meta',
      'formats',
      'sessions',
    ]);
    const overviewSection = document.getElementById('overview');
    expect(overviewSection).not.toBeNull();
    expect(within(overviewSection as HTMLElement).getByRole('table', { name: 'Play and draw performance' })).toBeInTheDocument();
    expect(within(overviewSection as HTMLElement).getByRole('table', { name: 'Momentum splits' })).toBeInTheDocument();
    expect(within(dashboardNav).queryByRole('link', { name: 'Play / Draw' })).not.toBeInTheDocument();
    expect(within(dashboardNav).queryByRole('link', { name: 'Momentum' })).not.toBeInTheDocument();
    expect(within(dashboardNav).queryByRole('link', { name: 'Deck Play / Draw' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Midweek Magic/i)).not.toBeInTheDocument();

    const trendLink = within(dashboardNav).getByRole('link', { name: 'Win Rate Trend' });
    await user.click(trendLink);
    expect(trendLink).toHaveClass('active');
    const overviewLink = within(dashboardNav).getByRole('link', { name: 'Overview' });
    await user.click(overviewLink);
    expect(overviewLink).toHaveClass('active');
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0 });

    vi.mocked(window.scrollTo).mockClear();
    await user.click(
      screen.getByRole('link', { name: 'MTGA Tracker – Go to overview' }),
    );
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0 });

    await user.click(screen.getByRole('button', { name: /switch to light mode/i }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
  });

  it('links every deck mention to the deck detail page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })));
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();
    // Decks table, Best Deck metric, Recent Games, and Matchups.
    const deckLinks = screen.getAllByRole('link', { name: 'Boros Mouse' });
    expect(deckLinks.length).toBe(4);
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
    expect(document.title).toBe('MTGA Tracker – Boros Mouse');
    ['Win Rate Trend', 'Deck List & Card Performance', 'Mulligans', 'Decklist Changes', 'Formats', 'Recent Games'].forEach(
      (sectionName) => {
        expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
      },
    );
    expect(screen.getAllByText('Mouse Mentor').length).toBeGreaterThan(0);
    expect(screen.getByText('Signature card: Mouse Mentor')).toBeInTheDocument();
    const deckListTable = screen.getByRole('table', { name: 'Deck list and card performance' });
    const mountainRow = within(deckListTable).getByRole('link', { name: 'Mountain' }).closest('tr');
    const mentorRow = within(deckListTable).getByRole('link', { name: 'Mouse Mentor' }).closest('tr');
    const duressRow = within(deckListTable).getByRole('link', { name: 'Duress' }).closest('tr');
    expect(mountainRow).not.toBeNull();
    expect(mentorRow).not.toBeNull();
    expect(duressRow).not.toBeNull();
    expect(within(mountainRow as HTMLElement).getAllByRole('cell')[0]).toHaveTextContent('20');
    expect(within(mountainRow as HTMLElement).getAllByRole('cell')[2]).toHaveTextContent('Main Deck');
    expect(within(mentorRow as HTMLElement).getAllByRole('cell')[0]).toHaveTextContent('4');
    expect(within(mentorRow as HTMLElement).getAllByRole('cell')[4]).toHaveTextContent('2');
    expect(within(duressRow as HTMLElement).getAllByRole('cell')[0]).toHaveTextContent('1');
    expect(within(duressRow as HTMLElement).getAllByRole('cell')[2]).toHaveTextContent('Sideboard');
    expect(within(duressRow as HTMLElement).getAllByRole('cell')[4]).toHaveTextContent('0');

    const nav = screen.getByRole('navigation', { name: 'Dashboard sections' });
    expect(within(nav).getByRole('link', { name: '← Back to dashboard' })).toHaveAttribute('href', '#overview');
    ['Win Rate Trend', 'Deck List & Card Performance', 'Mulligans', 'Decklist Changes', 'Formats', 'Recent Games'].forEach(
      (label) => {
        expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument();
      },
    );

    await act(async () => {
      window.location.hash = '#overview';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    expect(await screen.findByLabelText('Overview metrics')).toBeInTheDocument();
    expect(document.title).toBe('MTGA Tracker – Overview');
    expect(screen.queryByRole('heading', { name: 'Deck List & Card Performance' })).not.toBeInTheDocument();
  });

  it('copies an exact Arena deck export from deck detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(String(url).startsWith('/api/deck') ? deckDetail : snapshot), {
          status: 200,
        }),
      ),
    );
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText');
    window.location.hash = '#/deck/Boros%20Mouse';
    render(<App />);

    await user.click(await screen.findByRole('button', { name: 'Copy Arena Deck' }));

    expect(writeText).toHaveBeenCalledWith(deckDetail.deck_export.text);
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
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

  it('filters the deck table by text', async () => {
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

  });

  it('shows ten decks at a time and pages through the remaining decks', async () => {
    const pagedSnapshot = {
      ...snapshot,
      decks: Array.from({ length: 17 }, (_, index) => ({
        ...snapshot.decks[0],
        deck_name: `Deck ${String(index + 1).padStart(2, '0')}`,
        games: index + 1,
      })),
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(pagedSnapshot), { status: 200 })));
    const user = userEvent.setup();
    render(<App />);

    const deckTable = await screen.findByRole('table', { name: 'Deck performance' });
    expect(within(deckTable).getAllByRole('row')).toHaveLength(11);
    expect(within(deckTable).getByText('Deck 17')).toBeInTheDocument();
    expect(within(deckTable).queryByText('Deck 01')).not.toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Deck performance pagination' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(within(deckTable).getAllByRole('row')).toHaveLength(8);
    expect(within(deckTable).getByText('Deck 01')).toBeInTheDocument();
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
      combat_decks: [],
      combat_split: [],
      mana_readiness: [],
      schedule: { by_weekday: [], by_time_of_day: [] },
      fatigue: [],
      streaks: { games: 0, current: null, longest_win: 0, longest_loss: 0 },
      outcome_reasons: [],
      opener_lands: [],
      opponent_threats: [],
      matchups: [],
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
    const headers = within(recentTable)
      .getAllByRole('columnheader')
      .map((header) => header.textContent?.replace(/[↕↑↓]/g, '').trim());
    expect(headers).toEqual([
      'Started',
      'Deck',
      'Format',
      'Outcome',
      'Match Record',
      'Draw Status',
      'Mulligan(s)',
      'Total Turns',
      'Cards Seen',
      'Lands Seen',
      'Game Time',
    ]);
    expect(within(recentTable).queryByRole('columnheader', { name: 'Land Seen' })).not.toBeInTheDocument();
    expect(within(recentTable).queryByRole('columnheader', { name: /Your Avg Turn/i })).not.toBeInTheDocument();
    expect(within(recentTable).queryByRole('columnheader', { name: /Opp\. Avg Turn/i })).not.toBeInTheDocument();
    const recentGameRow = within(recentTable).getAllByRole('row')[1];
    expect(within(recentGameRow).getByText('Flood')).toHaveClass('badge-draw');
    expect(within(recentGameRow).getAllByText('10')).toHaveLength(2);
    expect(within(recentGameRow).getByText('7 (71%)')).toBeInTheDocument();
  });

  it('shows mana-screwed games in Recent Games with the legacy API shape', async () => {
    const manaScrewedSnapshot = {
      ...snapshot,
      draw_quality: snapshot.draw_quality.map((row) =>
        row.game_id === 'game-1'
          ? { ...row, cards_seen: 10, lands_seen: 1, land_seen_pct: 10 }
          : row,
      ),
      recent: [
        {
          game_id: 'game-1',
          started_at: '2026-06-04T00:01:00',
          deck_name: 'Boros Mouse',
          format_label: 'Standard Best-of-1',
          outcome: 'loss',
          mulligans: 0,
          duration_seconds: 120,
          total_turns: 7,
          flood_reasons: [],
          is_flood: false,
        },
      ],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(manaScrewedSnapshot), { status: 200 })),
    );

    render(<App />);

    const recentTable = await screen.findByRole('table', { name: 'Recent games' });
    expect(within(recentTable).getByText('Mana Screw')).toHaveClass('badge-screw');
  });

  it('corrects a legacy zero-step rank snapshot after a same-tier win', async () => {
    const legacyRankSnapshot = {
      ...snapshot,
      rank_progress: [
        {
          ...snapshot.rank_progress[0],
          id: 1,
          captured_at: '2026-07-26T01:46:01',
          rank_class: 'Diamond',
          rank_level: 4,
          rank_step: 0,
          raw_step: undefined,
          rank_score: 96,
          rank_label: 'Diamond 4 (0/6)',
          matches_won: 81,
          matches_lost: 62,
        },
        {
          ...snapshot.rank_progress[0],
          id: 2,
          captured_at: '2026-07-26T02:00:22',
          rank_class: 'Diamond',
          rank_level: 4,
          rank_step: 0,
          raw_step: undefined,
          rank_score: 96,
          rank_label: 'Diamond 4 (0/6)',
          matches_won: 82,
          matches_lost: 62,
        },
      ],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(legacyRankSnapshot), { status: 200 })),
    );

    render(<App />);

    expect(await screen.findByText('Diamond 4 (1/6)')).toBeInTheDocument();
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
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole('heading', { name: /Game Jun 4/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/game?id=game-1', expect.anything());
    expect(document.title).toContain('Game Jun 4');
    ['Turn Timing', 'Draw Quality', 'Life Totals', 'Opening Hand', 'Drawn Cards', 'Cards Played', 'Opponent Revealed Cards', 'Timeline'].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });
    expect(screen.queryByRole('table', { name: 'Turn timing' })).not.toBeInTheDocument();
    expect(screen.getByText('You · 40 sec')).toBeInTheDocument();
    expect(screen.getByText('Opponent · 30 sec · Estimated')).toBeInTheDocument();
    const gameMetrics = screen.getByRole('region', { name: 'Game metrics' });
    expect(within(gameMetrics).queryByText('Outcome')).not.toBeInTheDocument();
    expect(within(gameMetrics).queryByText('Format')).not.toBeInTheDocument();
    expect(within(gameMetrics).getAllByRole('article')).toHaveLength(5);
    expect(screen.getByText('8 (73%)')).toBeInTheDocument();
    expect(screen.getByText('7 (70%)')).toBeInTheDocument();
    expect(screen.getAllByText('Flood').length).toBeGreaterThan(0);
    const drawStatus = screen.getByText('Draw Status').closest('.metric-card');
    expect(drawStatus).toHaveClass('metric-card-info');
    expect(within(drawStatus as HTMLElement).getByText('Flood')).toBeInTheDocument();
    expect(screen.getByText('Flood evidence')).toHaveClass('badge-draw');
    screen
      .getAllByText('Flood')
      .filter((element) => element.classList.contains('badge'))
      .forEach((badge) => expect(badge).toHaveClass('badge-draw'));
    expect(screen.queryByText('Turn 1 begins')).not.toBeInTheDocument();
    const timelineFilters = screen.getByRole('group', { name: 'Timeline filters' });
    expect(within(timelineFilters).queryByRole('option', { name: 'turn' })).not.toBeInTheDocument();
    expect(screen.getByText('1 of 1 events')).toBeInTheDocument();
    const timelineSection = screen.getByRole('heading', { name: 'Timeline' }).closest('section');
    expect(timelineSection).not.toBeNull();
    const timeline = within(timelineSection as HTMLElement);
    const timelineReturnHash = gameRouteHash('game-1', '#overview', 'game-timeline');
    expect(timeline.getByRole('link', { name: '[Mouse Mentor]' })).toHaveAttribute(
      'href',
      cardRouteHash('Mouse Mentor', timelineReturnHash),
    );
    expect(timeline.getByRole('link', { name: '[Graveyard Trespasser]' })).toHaveAttribute(
      'href',
      cardRouteHash('Graveyard Trespasser', timelineReturnHash),
    );
    expect(timeline.queryByRole('link', { name: 'resolved' })).not.toBeInTheDocument();
    expect(timeline.queryByRole('link', { name: 'you' })).not.toBeInTheDocument();
    expect(timeline.queryByRole('link', { name: 'Skeleton Pirate' })).not.toBeInTheDocument();
    expect(timelineSection).toHaveTextContent('[0:20] [Mouse Mentor]Creature2/1');
    expect(screen.getByRole('link', { name: 'Boros Mouse' })).toHaveAttribute('href', '#/deck/Boros%20Mouse');
    expect(screen.getByRole('link', { name: 'Opponent' })).toHaveAttribute('href', '#/opponent/Opponent');
    expect(screen.getAllByRole('button', { name: /^Collapse / })).toHaveLength(10);

    const timingToggle = screen.getByRole('button', { name: 'Collapse Turn Timing' });
    await user.click(timingToggle);
    expect(timingToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Your Turn Time')).not.toBeVisible();
    expect(screen.getByRole('button', { name: 'Expand Turn Timing' })).toBeInTheDocument();
  });

  it('marks a three-draw low-land drought as mana screw', async () => {
    const manaScrewDetail = {
      ...gameDetail,
      opening_hand: [
        { display_name: 'Swamp', type_category: 'Land', hand_position: 1, copy_number: 1 },
      ],
      drawn: [
        { display_name: 'First Nonland', type_category: 'Creature', turn_number: 2, draw_position: 1, copy_number: 1 },
        { display_name: 'Second Nonland', type_category: 'Instant', turn_number: 4, draw_position: 2, copy_number: 1 },
        { display_name: 'Third Nonland', type_category: 'Creature', turn_number: 6, draw_position: 3, copy_number: 1 },
      ],
      draw_quality: {
        total_draws: 3,
        identified_draws: 3,
        land_draws: 0,
        land_draw_pct: 0,
        opening_lands: 1,
        total_cards_seen: 10,
        lands_seen: 1,
        land_seen_pct: 10,
        expected_land_rate: 40,
        expected_lands_seen: 4,
        longest_land_streak: 0,
        max_lands_in_eight: null,
        longest_low_land_drought: 3,
        low_land_drought_lands: 1,
        flood_reasons: [],
        is_flood: false,
        screw_reasons: ['3 consecutive nonland draws while stuck on 1 land'],
        is_screw: true,
      },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(String(url).startsWith('/api/game') ? manaScrewDetail : snapshot), {
          status: 200,
        }),
      ),
    );
    window.location.hash = '#/game/game-1';

    render(<App />);

    expect(await screen.findByRole('heading', { name: /Game Jun 4/i })).toBeInTheDocument();
    expect(screen.getAllByText('Mana Screw').length).toBeGreaterThan(0);
    const drawStatus = screen.getByText('Draw Status').closest('.metric-card');
    expect(drawStatus).toHaveClass('metric-card-warning');
    expect(within(drawStatus as HTMLElement).getByText('Mana Screw')).toBeInTheDocument();
    expect(screen.getByText('3 draws')).toBeInTheDocument();
    expect(screen.getByText('Mana Screw Evidence')).toHaveClass('badge-screw');
    expect(screen.getByText('3 consecutive nonland draws while stuck on 1 land')).toBeInTheDocument();
    expect(screen.queryByText('Flood evidence')).not.toBeInTheDocument();
  });

  it('renders sortable head-to-head history for an opponent route', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/opponent')) {
        return new Response(JSON.stringify(opponentDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    window.location.hash = '#/opponent/Opponent';

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Opponent' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/opponent?name=Opponent', expect.anything());
    expect(screen.getByRole('table', { name: 'Games against Opponent' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Game History' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Boros Mouse' })).toHaveLength(2);
  });

  it('links card names to the card detail page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { status: 200 })));
    render(<App />);

    expect(await screen.findByText('MTGA Tracker')).toBeInTheDocument();

    // Card links on the dashboard now live in the Opponent Meta threat table.
    expect(screen.getByRole('link', { name: 'Graveyard Trespasser' })).toHaveAttribute(
      'href',
      '#/card/Graveyard%20Trespasser',
    );
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
      if (String(url).startsWith('/api/search')) {
        return new Response(
          JSON.stringify({ cards: searchResults, decks: [], opponents: [] }),
          { status: 200 },
        );
      }
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
    expect(screen.getByRole('img', { name: 'Mouse Mentor card' })).toHaveAttribute(
      'src',
      'https://api.scryfall.com/cards/named?exact=Mouse+Mentor&format=image&version=normal',
    );
    expect(fetchMock).toHaveBeenCalledWith('/api/card?name=Mouse+Mentor', expect.anything());
    expect(document.title).toBe('MTGA Tracker – Mouse Mentor');
    [
      'Card Summary',
      'When Opponent Plays This Card',
      'Played By Side',
      'Your Decks',
      'Opening Hand Impact',
    ].forEach((sectionName) => {
      expect(screen.getByRole('heading', { name: sectionName })).toBeInTheDocument();
    });
    expect(screen.getByRole('region', { name: 'Opponent card impact' })).toHaveTextContent('Your Loss Rate50%');
    expect(screen.getByRole('link', { name: 'Boros Mouse' })).toHaveAttribute('href', '#/deck/Boros%20Mouse');
    screen.getAllByRole('link', { name: '← Back to dashboard' }).forEach((link) => {
      expect(link).toHaveAttribute('href', '#overview');
    });
  });

  it('returns a card opened from the timeline to the originating game', async () => {
    const gameHash = gameRouteHash('game-1', '#recent-games', 'game-timeline');
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).startsWith('/api/card')) {
        return new Response(JSON.stringify(cardDetail), { status: 200 });
      }
      if (String(url).startsWith('/api/game')) {
        return new Response(JSON.stringify(gameDetail), { status: 200 });
      }
      return new Response(JSON.stringify(snapshot), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    window.location.hash = cardRouteHash('Mouse Mentor', gameHash);
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Mouse Mentor' })).toBeInTheDocument();
    const backLinks = screen.getAllByRole('link', { name: '← Back to game' });
    backLinks.forEach((link) => expect(link).toHaveAttribute('href', gameHash));
    await user.click(backLinks[0]);

    await waitFor(() => expect(window.location.hash).toBe(gameHash));
    expect(await screen.findByRole('heading', { name: /Game Jun 4/i })).toBeInTheDocument();
  });

  it('derives your opponent-card record from the legacy API perspective', async () => {
    const legacyCardDetail = {
      ...cardDetail,
      opponent_impact: undefined,
      by_role: cardDetail.by_role.map((row) =>
        row.role === 'opponent' ? { ...row, wins: 3, losses: 1, win_rate: 75 } : row,
      ),
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(legacyCardDetail), { status: 200 })),
    );
    window.location.hash = '#/card/Mouse%20Mentor';

    render(<App />);

    const impact = await screen.findByRole('region', { name: 'Opponent card impact' });
    expect(impact).toHaveTextContent('Your Record1–3');
    expect(impact).toHaveTextContent('Your Win Rate25%');
    expect(impact).toHaveTextContent('Your Loss Rate75%');
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
