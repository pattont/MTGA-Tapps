import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEMO_LIVE, DEMO_OVERLAY } from './demo';
import { parseStreamOptions } from './options';
import { StreamApp } from './StreamApp';

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init });
}

function renderWidget(search: string) {
  return render(<StreamApp options={parseStreamOptions(search)} />);
}

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('StreamApp', () => {
  it('explains itself without a widget', () => {
    renderWidget('');
    expect(screen.getByText(/Stream Kit/)).toBeInTheDocument();
  });

  it('applies scale and background to the root', () => {
    const { container } = renderWidget('?widget=record&demo=1&scale=150&bg=glass');
    const root = container.querySelector('.sk') as HTMLElement;
    expect(root).toHaveClass('sk-bg-glass');
    expect(root.style.getPropertyValue('--sk-scale')).toBe('1.5');
  });
});

describe('deck widget', () => {
  it('shows sample data in demo mode without polling', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderWidget('?widget=deck&demo=1');
    expect(screen.getByText('Mono-Green Stompy')).toBeInTheDocument();
    expect(screen.getByText('Llanowar Elves')).toBeInTheDocument();
    expect(screen.getByText('Lands')).toBeInTheDocument();
    expect(screen.getByText('Tapps Tracker')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('hides between games and polls with the ETag', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ tracker: { state: 'idle' }, state: null }, { headers: { ETag: '"a"' } }))
      .mockResolvedValueOnce(json(DEMO_OVERLAY, { headers: { ETag: '"b"' } }))
      .mockImplementation(() => Promise.resolve(new Response(null, { status: 304 })));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderWidget('?widget=deck&brand=0');
    await flush();
    expect(container.querySelector('.sk-deck')).toBeNull();
    await flush(2000);
    expect(screen.getByText('Mono-Green Stompy')).toBeInTheDocument();
    expect(screen.queryByText('Tapps Tracker')).toBeNull();
    await flush(500);
    expect(fetchMock.mock.calls[2][1].headers).toEqual({ 'If-None-Match': '"b"' });
    // A 304 keeps what is on screen.
    expect(screen.getByText('Mono-Green Stompy')).toBeInTheDocument();
  });

  it('says it is waiting when idle=show and no game is up', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ tracker: { state: 'idle' }, state: null }))));
    renderWidget('?widget=deck&idle=show');
    await flush();
    expect(screen.getByText('Waiting for a game')).toBeInTheDocument();
  });
});

describe('full overlay widget', () => {
  it('draws the in-game panel with the sideboard beside it', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderWidget('?widget=overlay&demo=1');
    const panel = screen.getByRole('group', { name: 'Deck panel' });
    expect(panel).toHaveTextContent('Mono-Green Stompy');
    expect(panel).toHaveTextContent('Std. Ranked · vs Opponent (2–1)');
    expect(panel).toHaveTextContent('Land drops15 of 46 left');
    expect(panel).toHaveTextContent('DRAW');
    expect(panel).toHaveTextContent('Library 46 / 60');
    expect(screen.getByText('Sideboard', { selector: '.nm' })).toBeInTheDocument();
    const sideboard = screen.getByRole('region', { name: 'Sideboard' });
    expect(sideboard).toHaveTextContent('Pick Your Poison');
    // The sideboard row counts the whole sideboard.
    expect(container.querySelector('.side-row .cnt')).toHaveTextContent('10');
    const root = container.querySelector('.sko') as HTMLElement;
    expect(root).toHaveClass('sko-side-right', 'has-bg', 'names-type');
    expect(root.style.getPropertyValue('--tint-alpha')).toBe('0.717');
    expect(screen.getByText('Tapps Tracker')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('follows the sideboard, lands, background and name options', () => {
    const { container } = renderWidget('?widget=overlay&demo=1&sideboard=off&lands=all&opacity=0&opponent=0&names=white&brand=0');
    expect(screen.queryByRole('region', { name: 'Sideboard' })).toBeNull();
    // Still listed as a folded row, as in game.
    expect(container.querySelector('.side-row')).not.toBeNull();
    expect(screen.getByText('Fabled Passage').closest('.row')).toHaveClass('sub');
    expect(container.querySelector('.sko')).toHaveClass('no-bg', 'names-white');
    expect(screen.getByRole('group', { name: 'Deck panel' })).toHaveTextContent('vs Opponent (2–1)');
    expect(screen.queryByText('Tapps Tracker')).toBeNull();
  });

  it('hides between games, or waits when idle=show', async () => {
    const idle = () => Promise.resolve(json({ tracker: { state: 'idle' }, state: null }));
    vi.stubGlobal('fetch', vi.fn().mockImplementation(idle));
    const { container, unmount } = renderWidget('?widget=overlay');
    await flush();
    expect(container.querySelector('.sko')).toBeNull();
    unmount();
    renderWidget('?widget=overlay&idle=show');
    await flush();
    expect(screen.getByText(/Waiting for a match/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Sideboard' })).toBeNull();
  });
});

describe('recent games widget', () => {
  it('lists the newest games with result, turn order, opponent, turns and length', () => {
    const { container } = renderWidget('?widget=games&demo=1&count=3');
    const rows = Array.from(container.querySelectorAll('.sk-game'));
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('LLossMono-Green Stompyvs Opponent · 9 turns · 14 minPlay');
    expect(rows[1]).toHaveTextContent('WWinMono-Green Stompyvs MoxMaven · 7 turns · 11 minDraw');
    expect(screen.getByText('Recent games')).toBeInTheDocument();
    expect(screen.getByText('Tapps Tracker')).toBeInTheDocument();
    // The session record leads, on by default.
    expect(container.querySelector('.sk-games-record')).toHaveTextContent('Session6–275%');
    expect(screen.getByLabelText('6 wins, 2 losses')).toBeInTheDocument();
    // No replay links on stream.
    expect(container.querySelector('a')).toBeNull();
  });

  it('can hide opponent names and show just the last game', () => {
    const { container } = renderWidget('?widget=games&demo=1&count=1&opponent=0&record=0');
    expect(container.querySelector('.sk-games-record')).toBeNull();
    expect(container.querySelectorAll('.sk-game')).toHaveLength(1);
    expect(screen.getByText('Last game')).toBeInTheDocument();
    expect(container.querySelector('.sk-game-meta')).toHaveTextContent('9 turns · 14 min');
    expect(screen.queryByText(/vs Opponent/)).toBeNull();
  });

  it('says when there are no games yet and hides while the tracker is off', async () => {
    const live = (state: string) => ({ ...DEMO_LIVE, tracker: { ...DEMO_LIVE.tracker, state }, games: [] });
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.resolve(json(live('idle'))))
      .mockImplementation(() => Promise.resolve(json(live('offline'))));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderWidget('?widget=games');
    await flush();
    expect(screen.getByText('No games yet today')).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/live?since=0&events=0');
    await flush(2000);
    expect(container.querySelector('.sk-games')).toBeNull();
  });
});

describe('record and matchup widgets', () => {
  it('asks the live feed for the scoreboard only', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(json(DEMO_LIVE)));
    vi.stubGlobal('fetch', fetchMock);
    renderWidget('?widget=record');
    await flush();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/live?since=0&events=0');
    expect(screen.getByLabelText('6 wins, 2 losses')).toBeInTheDocument();
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.getByText('Diamond 2 · 3/6')).toBeInTheDocument();
    expect(screen.getByText('Deck today 4–1')).toBeInTheDocument();
  });

  it('hides the record while the tracker is offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ ...DEMO_LIVE, tracker: { ...DEMO_LIVE.tracker, state: 'offline' } }))));
    const { container } = renderWidget('?widget=record');
    await flush();
    expect(container.querySelector('.sk-record')).toBeNull();
  });

  it('shows the matchup and can hide the opponent’s name', () => {
    renderWidget('?widget=matchup&demo=1&opponent=0');
    expect(screen.getByText('Opponent')).toBeInTheDocument();
    expect(screen.getByText('Dimir Midrange')).toBeInTheDocument();
    expect(screen.getByText('On the draw')).toBeInTheDocument();
    expect(screen.getByText('Game 2 of 3')).toBeInTheDocument();
    expect(screen.getByText('Head-to-head 2–1')).toBeInTheDocument();
  });

  it('hides the matchup between games unless idle=show', async () => {
    const between = { ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, in_game: false, last_game_frozen: true } };
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json(between))));
    const hidden = renderWidget('?widget=matchup');
    await flush();
    expect(hidden.container.querySelector('.sk-matchup')).toBeNull();
    hidden.unmount();
    renderWidget('?widget=matchup&idle=show');
    await flush();
    expect(screen.getByText('Last game')).toBeInTheDocument();
  });
});

describe('spotlight widget', () => {
  const history = {
    ...DEMO_LIVE,
    events: [{ id: 10, event_type: 'cast', actor_role: 'opponent', text: 'Opponent: cast [Duress (Sorcery)]' }],
    seq: 10,
  };

  it('skips the game so far and shows a new cast until it fades', async () => {
    const fresh = {
      ...history,
      events: [...history.events, { id: 11, event_type: 'cast', actor_role: 'opponent', text: 'Opponent: cast [Go for the Throat (Instant)]' }],
      seq: 11,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(history))
      .mockResolvedValueOnce(json(history))
      .mockImplementation(() => Promise.resolve(json(fresh)));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderWidget('?widget=spotlight&seconds=4');
    await flush();
    await flush(1000);
    expect(screen.queryByAltText('Duress')).toBeNull();
    expect(fetchMock.mock.calls[1][0]).toBe('/api/live?since=10');

    await flush(1000);
    const image = screen.getByAltText('Go for the Throat');
    expect(image.getAttribute('src')).toContain('exact=Go+for+the+Throat');
    expect(screen.getByText('Opponent cast')).toBeInTheDocument();
    // Hidden until the image loads, then up for `seconds`.
    expect(container.querySelector('.sk-spot-in')).toBeNull();
    fireEvent.load(image);
    expect(container.querySelector('.sk-spot-in')).not.toBeNull();
    await flush(4000);
    expect(container.querySelector('.sk-spot-in')).toBeNull();
  });

  it('falls back to the card name when the image fails', async () => {
    renderWidget('?widget=spotlight&demo=1');
    fireEvent.error(screen.getByAltText('Llanowar Elves'));
    expect(screen.getByText('Llanowar Elves')).toHaveClass('sk-spot-fallback');
    expect(screen.getByText('You cast')).toBeInTheDocument();
  });
});
