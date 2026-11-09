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
    // The session's play / draw split heads the list: a rate from five games, else the record.
    expect(container.querySelector('.sk-games-sides')).toHaveTextContent('Play80%Draw2–1');
    // No replay links on stream.
    expect(container.querySelector('a')).toBeNull();
  });

  it('can hide opponent names and show just the last game', () => {
    // record=0 is the 0.7.5 link for hiding the record; play / draw has its own switch.
    const { container } = renderWidget('?widget=games&demo=1&count=1&opponent=0&record=0');
    expect(container.querySelector('.sk-games-record')).toBeNull();
    expect(container.querySelector('.sk-games-sides')).toHaveTextContent('Play80%');
    expect(container.querySelectorAll('.sk-game')).toHaveLength(1);
    expect(screen.getByText('Last game')).toBeInTheDocument();
    expect(container.querySelector('.sk-game-meta')).toHaveTextContent('9 turns · 14 min');
    expect(screen.queryByText(/vs Opponent/)).toBeNull();
  });

  it('can hide the play / draw totals, each game’s turn order and its length', () => {
    const { container } = renderWidget('?widget=games&demo=1&count=3&hide=turn,order,details');
    expect(container.querySelector('.sk-games-sides')).toBeNull();
    expect(container.querySelector('.sk-turn-order')).toBeNull();
    expect(container.querySelector('.sk-game-meta')).toHaveTextContent(/^vs Opponent$/);
    expect(container.querySelector('.sk-games-record')).toHaveTextContent('Session6–275%');
  });

  it('shows today’s record when asked', () => {
    const { container } = renderWidget('?widget=games&demo=1&period=today');
    expect(container.querySelector('.sk-games-record')).toHaveTextContent('Today8–373%');
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
    // The deck chip follows the headline: this session's record with the deck.
    expect(screen.getByText('Deck 3–1')).toBeInTheDocument();
    const sides = document.querySelector('.sk-record-sides') as HTMLElement;
    expect(sides).toHaveTextContent('Play80%4–1');
    // Under five games on the draw: the record alone.
    expect(sides).toHaveTextContent('Draw2–1');
  });

  it('shows today’s record instead of the session’s, leaving out an empty side', async () => {
    const today = { ...DEMO_LIVE.today!, draw: { wins: 0, losses: 0 } };
    vi.stubGlobal('fetch', liveSequence({ ...DEMO_LIVE, today }));
    renderWidget('?widget=record&period=today');
    await flush();
    expect(screen.getByText('Today')).toBeInTheDocument();
    expect(screen.getByLabelText('8 wins, 3 losses')).toBeInTheDocument();
    expect(screen.getByText('Deck 4–1')).toBeInTheDocument();
    expect(screen.getByText('73%')).toBeInTheDocument();
    const sides = document.querySelector('.sk-record-sides') as HTMLElement;
    expect(sides).toHaveTextContent('Play83.3%5–1');
    expect(sides).not.toHaveTextContent('Draw');
  });

  it('shows only the chosen parts of the record', async () => {
    vi.stubGlobal('fetch', liveSequence(DEMO_LIVE));
    const { container } = renderWidget('?widget=record&hide=turn,deck');
    await flush();
    expect(container.querySelector('.sk-record-sides')).toBeNull();
    expect(screen.getByText('Diamond 2 · 3/6')).toBeInTheDocument();
    expect(screen.queryByText(/^Deck /)).toBeNull();
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

/** Answers each live poll with the next payload, repeating the last. */
function liveSequence(...payloads: unknown[]) {
  let index = 0;
  return vi.fn().mockImplementation(() => {
    const payload = payloads[Math.min(index, payloads.length - 1)];
    index += 1;
    return Promise.resolve(json(payload));
  });
}

describe('scorebug widget', () => {
  it('shows both sides, the turn, whose turn and the Bo3 score', () => {
    const { container } = renderWidget('?widget=scorebug&demo=1');
    const bug = container.querySelector('.sb') as HTMLElement;
    expect(bug).toHaveTextContent('Mono-Green Stompy');
    expect(bug).toHaveTextContent('Dimir Midrange');
    expect(bug).toHaveTextContent('Turn5');
    expect(bug).toHaveTextContent('Your turn');
    expect(bug).toHaveTextContent('Game 2 · 1–0');
    expect(container.querySelector('.sb-side-you')).toHaveClass('sb-active');
    expect(container.querySelector('.sb-timer')?.textContent).toMatch(/^0:4\d$/);
  });

  it('calls out a life change', async () => {
    const hit = { ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, opponent_life: 9 } };
    vi.stubGlobal('fetch', liveSequence(DEMO_LIVE, hit));
    const { container } = renderWidget('?widget=scorebug&hide=timer');
    await flush();
    expect(container.querySelector('.sb-delta')).toBeNull();
    expect(container.querySelector('.sb-timer')).toBeNull();
    await flush(2000);
    expect(container.querySelector('.sb-life-opp .sb-delta')).toHaveTextContent('−3');
    expect(container.querySelector('.sb-life-opp')).toHaveClass('sb-life-down');
    await flush(1700);
    expect(container.querySelector('.sb-delta')).toBeNull();
  });

  it('says Final between games with idle=show', async () => {
    const between = { ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, in_game: false, last_game_frozen: true } };
    vi.stubGlobal('fetch', liveSequence(between));
    const { container } = renderWidget('?widget=scorebug&idle=show');
    await flush();
    expect(container.querySelector('.sb')).toHaveTextContent('Final');
    expect(container.querySelector('.sb-active')).toBeNull();
  });
});

describe('game result widget', () => {
  const finished = { ...DEMO_LIVE.games[1], id: 'new-game' };

  it('skips the game already over, then shows the next one and fades it', async () => {
    const frozen = {
      ...DEMO_LIVE,
      now: { ...DEMO_LIVE.now!, in_game: false, last_game_frozen: true, game_id: 'new-game', player_life: 20 },
      games: [finished, ...DEMO_LIVE.games],
    };
    vi.stubGlobal('fetch', liveSequence(DEMO_LIVE, frozen));
    const { container } = renderWidget('?widget=result&seconds=5');
    await flush();
    expect(container.querySelector('.rs')).toBeNull();
    await flush(2000);
    const card = container.querySelector('.rs') as HTMLElement;
    expect(card).toHaveClass('rs-win');
    expect(card).toHaveTextContent('Victory');
    expect(card).toHaveTextContent('Mono-Green Stompy vs MoxMaven');
    expect(card).toHaveTextContent('Untouched: finished on 20 life');
    expect(card).toHaveTextContent('Won on the draw');
    await flush(5000);
    expect(container.querySelector('.rs')).toHaveClass('rs-leaving');
    await flush(700);
    expect(container.querySelector('.rs')).toBeNull();
  });

  it('shows a sample result in demo mode', () => {
    renderWidget('?widget=result&demo=1&opponent=0');
    expect(screen.getByText('Victory')).toBeInTheDocument();
    expect(screen.getByText('Match won 2–0')).toBeInTheDocument();
    expect(screen.queryByText(/MoxMaven/)).toBeNull();
    expect(document.querySelector('.rs-session')).toHaveTextContent('Session6–275%');
  });

  it('can show today’s record under the result', () => {
    renderWidget('?widget=result&demo=1&period=today');
    expect(document.querySelector('.rs-session')).toHaveTextContent('Today8–372.7%');
  });
});

describe('opponent cards widget', () => {
  it('groups their cards and folds lands into one line', () => {
    const { container } = renderWidget('?widget=opponent&demo=1&hide=art');
    expect(screen.getByText('Opponent is on')).toBeInTheDocument();
    expect(screen.getByText('Dimir Midrange')).toBeInTheDocument();
    expect(screen.getByText('Likely · 4 cards match')).toBeInTheDocument();
    expect(screen.getByText('Creatures')).toBeInTheDocument();
    expect(screen.getByText('Cut Down').closest('li')).toHaveTextContent('×2');
    expect(container.querySelector('.op-lands')).toHaveTextContent('Island ×2 · Swamp · Watery Grave');
    expect(container.querySelector('.op-art')).toBeNull();
  });

  it('lists lands with the cards and shows art when asked', () => {
    const { container } = renderWidget('?widget=opponent&demo=1&lands=all');
    expect(container.querySelector('.op-lands')).toBeNull();
    expect(screen.getByText('Watery Grave')).toBeInTheDocument();
    expect(container.querySelector('.op-art')?.getAttribute('src')).toContain('version=art_crop');
  });

  it('highlights a card the moment it is played', async () => {
    const seen = DEMO_LIVE.now!.opponent_seen!;
    const later = { ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, opponent_seen: [...seen, { name: 'Sheoldred, the Apocalypse', type: 'Creature', mana_cost: '{2}{B}{B}', mana_value: 4, count: 1 }] } };
    vi.stubGlobal('fetch', liveSequence(DEMO_LIVE, later));
    const { container } = renderWidget('?widget=opponent&hide=art');
    await flush();
    // The game so far is not news.
    expect(container.querySelector('.op-fresh')).toBeNull();
    await flush(2000);
    expect(screen.getByText('Sheoldred, the Apocalypse').closest('li')).toHaveClass('op-fresh');
  });
});

describe('land meter widget', () => {
  it('shows the count, the verdict and the next-draw chance', () => {
    const { container } = renderWidget('?widget=lands&demo=1');
    const meter = container.querySelector('.lm') as HTMLElement;
    expect(meter).toHaveClass('lm-normal');
    expect(meter).toHaveTextContent('5 of 12 cards');
    expect(meter).toHaveTextContent('expected 4.4 (+0.6)');
    expect(meter).toHaveTextContent('Next draw 33% land · 15 of 46 left');
    expect(meter.style.getPropertyValue('--lm-now')).toBe(`${(100 * 5) / 12}%`);
  });

  it('shows Game Detail’s verdict and reason, and hides without draw data', async () => {
    const flooded = {
      ...DEMO_LIVE,
      now: { ...DEMO_LIVE.now!, draw_quality: { ...DEMO_LIVE.now!.draw_quality!, is_flood: true, reason: '7 of 8 post-opening draws were lands' } },
    };
    vi.stubGlobal('fetch', liveSequence(flooded));
    const shown = renderWidget('?widget=lands');
    await flush();
    expect(shown.container.querySelector('.lm')).toHaveClass('lm-flood');
    expect(screen.getByText('Flooding')).toBeInTheDocument();
    expect(screen.getByText('7 of 8 post-opening draws were lands')).toBeInTheDocument();
    shown.unmount();

    vi.stubGlobal('fetch', liveSequence({ ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, draw_quality: null } }));
    const hidden = renderWidget('?widget=lands');
    await flush();
    expect(hidden.container.querySelector('.lm')).toBeNull();
  });
});

describe('intermission widget', () => {
  it('shows the title, session, today, deck and rank climb', () => {
    const { container } = renderWidget('?widget=break&demo=1&title=Back%20in%205');
    const card = container.querySelector('.br') as HTMLElement;
    expect(card).toHaveTextContent('Back in 5');
    expect(card).toHaveTextContent('Session6–275%8 games · 2h 14m');
    expect(card).toHaveTextContent('Games');
    expect(container.querySelectorAll('.br-results .sk-result')).toHaveLength(8);
    expect(card).toHaveTextContent('Mono-Green Stompy');
    expect(card).toHaveTextContent('Diamond 4▲Diamond 2');
    expect(container.querySelectorAll('.br-steps .on')).toHaveLength(3);
  });

  it('can show today instead of the session', () => {
    const { container } = renderWidget('?widget=break&demo=1&period=today');
    const card = container.querySelector('.br') as HTMLElement;
    // No session length for a day.
    expect(card).toHaveTextContent('Today8–372.7%11 games');
    expect(card).not.toHaveTextContent('2h 14m');
  });

  it('keeps only the chosen rows, and the title while the tracker is off', async () => {
    vi.stubGlobal('fetch', liveSequence({ ...DEMO_LIVE, tracker: { ...DEMO_LIVE.tracker, state: 'offline' } }));
    const { container } = renderWidget('?widget=break&hide=session,results,deck,rank');
    await flush();
    expect(container.querySelector('.br')).toHaveTextContent('Be right back');
    expect(container.querySelectorAll('.br-row')).toHaveLength(0);
  });
});

describe('deck stats widget', () => {
  it('shows the win rate, record and Deck Manager’s splits', () => {
    const { container } = renderWidget('?widget=deckstats&demo=1');
    const stats = container.querySelector('.ds') as HTMLElement;
    expect(stats).toHaveTextContent('61.8%');
    expect(stats).toHaveTextContent('34–21');
    expect(stats).toHaveTextContent('Ranked64.7%22–12');
    expect(stats).toHaveTextContent('Casual57.1%12–9');
    expect(stats).toHaveTextContent('Play67.9%19–9');
    expect(stats).toHaveTextContent('Draw55.6%15–12');
    expect(stats).toHaveTextContent('3 wins in a row');
    expect(container.querySelectorAll('.ds-dots .ds-dot')).toHaveLength(10);
    expect(container.querySelectorAll('.ds-dots .ds-dot-loss')).toHaveLength(3);
  });

  it('shows only the chosen parts', () => {
    const { container } = renderWidget('?widget=deckstats&demo=1&hide=queues,turn');
    const stats = container.querySelector('.ds') as HTMLElement;
    expect(stats).not.toHaveTextContent('Ranked');
    expect(stats).not.toHaveTextContent('Play');
    expect(container.querySelector('.ds-strip')).toBeNull();
    expect(stats).toHaveTextContent('Last 10');
  });

  it('leaves out a column with no games', async () => {
    const record = DEMO_LIVE.now!.deck_record!;
    const casualOnly = { ...record, ranked: { wins: 0, losses: 0 }, unranked: { wins: 34, losses: 21 } };
    vi.stubGlobal('fetch', liveSequence({ ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, deck_record: casualOnly } }));
    const { container } = renderWidget('?widget=deckstats');
    await flush();
    const stats = container.querySelector('.ds') as HTMLElement;
    expect(stats).not.toHaveTextContent('Ranked');
    expect(stats).toHaveTextContent('Casual61.8%34–21');
    expect(container.querySelector('.ds-strip')).toHaveStyle({ '--ds-cols': '3' });
  });

  it('shows records, not rates, under five games', async () => {
    const few = {
      ...DEMO_LIVE.now!.deck_record!,
      wins: 2,
      losses: 1,
      win_rate: 66.7,
      ranked: { wins: 1, losses: 0 },
      unranked: { wins: 1, losses: 1 },
      play: { wins: 2, losses: 0 },
      draw: { wins: 0, losses: 1 },
      recent: ['win', 'loss', 'win'],
    };
    vi.stubGlobal('fetch', liveSequence({ ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, deck_record: few } }));
    const { container } = renderWidget('?widget=deckstats');
    await flush();
    const stats = container.querySelector('.ds') as HTMLElement;
    expect(stats).toHaveTextContent('2–13 games with this deck');
    expect(stats).not.toHaveTextContent('%');
    expect(stats).toHaveTextContent('Ranked1–0');
    expect(stats).toHaveTextContent('Last 3');
  });

  it('says when the deck has no recorded games yet', async () => {
    vi.stubGlobal('fetch', liveSequence({ ...DEMO_LIVE, now: { ...DEMO_LIVE.now!, deck_record: null } }));
    renderWidget('?widget=deckstats');
    await flush();
    expect(screen.getByText('First recorded game with this deck')).toBeInTheDocument();
  });
});

describe('turning parts off', () => {
  it('hides the matchup’s chips one by one', () => {
    const { container } = renderWidget('?widget=matchup&demo=1&hide=order,game,turn,h2h');
    expect(container.querySelector('.sk-panel')).toHaveTextContent('Dimir Midrange');
    expect(screen.queryByText('On the draw')).toBeNull();
    expect(screen.queryByText('Game 2 of 3')).toBeNull();
    expect(screen.queryByText(/^Turn /)).toBeNull();
    expect(screen.queryByText(/Head-to-head/)).toBeNull();
  });

  it('hides the scorebug’s deck names and Bo3 score', () => {
    const { container } = renderWidget('?widget=scorebug&demo=1&hide=yourdeck,theirdeck,match');
    expect(container.querySelector('.sb-match')).toBeNull();
    for (const detail of container.querySelectorAll('.sb-detail-text')) expect(detail).toBeEmptyDOMElement();
    expect(container.querySelector('.sb')).toHaveTextContent('Turn');
  });

  it('hides the land meter’s odds and explanation', () => {
    const { container } = renderWidget('?widget=lands&demo=1&hide=odds,reason');
    expect(container.querySelector('.lm')).not.toHaveTextContent('Next draw');
    expect(container.querySelector('.lm-reason')).toBeNull();
  });

  it('hides the game result’s match score, details, highlights and record', () => {
    const { container } = renderWidget('?widget=result&demo=1&hide=match,details,facts,record');
    expect(screen.getByText('Victory')).toBeInTheDocument();
    expect(screen.queryByText('Match won 2–0')).toBeNull();
    expect(container.querySelectorAll('.rs-chip')).toHaveLength(0);
    expect(container.querySelector('.rs-facts')).toBeNull();
    expect(container.querySelector('.rs-session')).toBeNull();
  });

  it('hides the full overlay’s head-to-head, turn, land drops, play / draw and library count', () => {
    const { container } = renderWidget('?widget=overlay&demo=1&hide=h2h,turn,drops,order,library');
    expect(container.querySelector('.deck')).not.toHaveTextContent(/\(\d+–\d+\)/);
    expect(container.querySelector('.turn')).toBeNull();
    expect(container.querySelector('.lands')).toBeNull();
    expect(container.querySelector('.pd')).toBeNull();
    expect(container.querySelector('.lib')).toBeNull();
    expect(container.querySelector('.list')).not.toBeNull();
  });

  it('hides the deck tracker’s library count and land odds', () => {
    const { container } = renderWidget('?widget=deck&demo=1&hide=library,odds');
    expect(container.querySelector('.sk-sub')).not.toHaveTextContent('Library');
    expect(container.querySelector('.sk-sub')).not.toHaveTextContent('Land next draw');
  });
});
