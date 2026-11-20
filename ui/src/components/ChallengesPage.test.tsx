import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChallengesPage } from './ChallengesPage';

function json(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, status: 200 });
}

const game = {
  game_id: 'g1',
  match_id: 'm1',
  started_at: '2026-11-10T20:00:00',
  deck_name: 'Mono Red',
  format_label: 'Direct Challenge',
  outcome: 'win',
  mulligans: 0,
  went_first: 1,
  duration_seconds: 600,
  total_turns: 9,
  flood_reasons: [],
  is_flood: false,
  cards_seen: 15,
  lands_seen: 6,
  land_seen_pct: 40,
  opponent_name: 'Pal#123',
};

function stub({ games = [] as unknown[], friends = [] as unknown[] } = {}) {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  const state = { tracking: { direct_challenge: true } };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      if (path === '/api/settings/tracking' && init?.method === 'POST') {
        state.tracking = { ...state.tracking, ...JSON.parse(String(init.body)) };
        return json({ tracking: state.tracking });
      }
      if (path === '/api/settings/tracking') return json({ tracking: state.tracking });
      if (path === '/api/challenges') return json({ games, friends, total: games.length });
      return json({});
    }),
  );
  return state;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Challenges page', () => {
  it('sends you to challenge your friends when there are no challenge games', async () => {
    stub();
    render(<ChallengesPage />);
    expect(await screen.findByText('No challenges yet. Go challenge your friends!')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('lists the record against each friend and every challenge game', async () => {
    stub({
      games: [game],
      friends: [{ friend: 'Pal#123', matches: 1, games: 1, wins: 1, losses: 0, win_rate: 100, last_played: game.started_at }],
    });
    render(<ChallengesPage />);
    const friends = await screen.findByRole('table', { name: 'Record against each friend' });
    expect(within(friends).getByText('Pal#123')).toBeInTheDocument();
    expect(within(friends).getByText('100%')).toBeInTheDocument();
    const games = screen.getByRole('table', { name: 'Challenge games' });
    expect(within(games).getByText('Mono Red')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Your decks in challenges' })).toBeInTheDocument();
    expect(screen.getByText('Match record').parentElement).toHaveTextContent('1–0');
    // One win against one friend: a favorite victim needs two matches, so nobody yet.
    expect(screen.getByText('Favorite victim').closest('article')).toHaveTextContent('Nobody yet');
    expect(screen.getByText('Fastest win').closest('article')).toHaveTextContent('Turn 9');
  });

  it('lists the friends you have played the most games against first', async () => {
    stub({
      games: [game],
      friends: [
        { friend: 'Matches#1', matches: 3, games: 3, wins: 2, losses: 1, win_rate: 67, last_played: null },
        { friend: 'Bo3#2', matches: 2, games: 5, wins: 1, losses: 1, win_rate: 50, last_played: null },
      ],
    });
    render(<ChallengesPage />);
    const table = await screen.findByRole('table', { name: 'Record against each friend' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((row) => within(row).getAllByRole('cell')[0].textContent)).toEqual(['Bo3#2', 'Matches#1']);
  });

  it('pages the games twenty at a time and searches them by friend or deck', async () => {
    const games = Array.from({ length: 25 }, (_, index) => ({
      ...game,
      game_id: `g${index}`,
      match_id: `m${index}`,
      started_at: `2026-11-10T20:${String(index).padStart(2, '0')}:00`,
      opponent_name: index === 3 ? 'Rival#9' : 'Pal#123',
      deck_name: index === 5 ? 'Izzet Prowess' : 'Mono Red',
    }));
    stub({ games, friends: [] });
    render(<ChallengesPage />);
    const table = await screen.findByRole('table', { name: 'Challenge games' });
    expect(within(table).getAllByRole('row')).toHaveLength(21);

    const search = screen.getByRole('searchbox', { name: 'Search games by friend or deck' });
    fireEvent.change(search, { target: { value: 'rival' } });
    expect(within(screen.getByRole('table', { name: 'Challenge games' })).getAllByRole('row')).toHaveLength(2);
    expect(screen.getByText('1 of 25')).toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'izzet' } });
    expect(within(screen.getByRole('table', { name: 'Challenge games' })).getByText('Izzet Prowess')).toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'nobody' } });
    expect(screen.queryByRole('table', { name: 'Challenge games' })).toBeNull();
    expect(screen.getByText(/No games against a friend or with a deck matching/)).toBeInTheDocument();
  });

  it('says so when challenge games are not saved, and links to Settings', async () => {
    const state = stub();
    state.tracking.direct_challenge = false;
    render(<ChallengesPage />);
    expect(await screen.findByText(/Challenge games aren't being saved/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings → Saved game modes' })).toHaveAttribute('href', '#/settings');
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it('shows no note while challenge games are saved', async () => {
    stub();
    render(<ChallengesPage />);
    expect(await screen.findByText('No challenges yet. Go challenge your friends!')).toBeInTheDocument();
    expect(screen.queryByText(/aren't being saved/)).toBeNull();
  });
});
