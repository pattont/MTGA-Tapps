import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StreamKitSettings } from './StreamKitSettings';

const ORIGIN = 'http://127.0.0.1:8765';

function link(title: string): HTMLInputElement {
  return screen.getByLabelText(`${title} link`) as HTMLInputElement;
}

beforeEach(() => {
  localStorage.clear();
});

describe('StreamKitSettings', () => {
  it('lists every widget with its link and a sample-data preview', () => {
    render(<StreamKitSettings origin={ORIGIN} />);
    expect(link('Deck tracker').value).toBe(`${ORIGIN}/stream.html?widget=deck`);
    expect(link('Record').value).toBe(`${ORIGIN}/stream.html?widget=record`);
    expect(link('Matchup').value).toBe(`${ORIGIN}/stream.html?widget=matchup`);
    expect(link('Card spotlight').value).toBe(`${ORIGIN}/stream.html?widget=spotlight`);
    const deck = screen.getByRole('article', { name: 'Deck tracker' });
    expect(within(deck).getByRole('link', { name: /Preview/ })).toHaveAttribute(
      'href',
      `${ORIGIN}/stream.html?widget=deck&demo=1&preview=1`,
    );
    expect(within(deck).getByText('320 × 720')).toBeInTheDocument();
    // Non-streamers are told it costs them nothing.
    expect(screen.getByText(/Nothing here runs until a widget is open/)).toBeInTheDocument();
    expect(screen.getByText(/Stream Kit idea/)).toHaveTextContent('Thank you, MrNaosu, for the amazing Stream Kit idea!');
  });

  it('puts shared and per-widget choices in the links and remembers them', () => {
    const { unmount } = render(<StreamKitSettings origin={ORIGIN} />);
    fireEvent.change(screen.getByLabelText('Size'), { target: { value: '150' } });
    fireEvent.click(screen.getByLabelText(/Tapps Tracker/));
    const spotlight = screen.getByRole('article', { name: 'Card spotlight' });
    fireEvent.change(within(spotlight).getByLabelText('Cards from'), { target: { value: 'opponent' } });

    expect(link('Card spotlight').value).toBe(`${ORIGIN}/stream.html?widget=spotlight&scale=150&brand=0&who=opponent`);
    // The spotlight's choice stays on the spotlight.
    expect(link('Deck tracker').value).toBe(`${ORIGIN}/stream.html?widget=deck&scale=150&brand=0`);
    expect(within(spotlight).getByText('450 × 705')).toBeInTheDocument();

    unmount();
    render(<StreamKitSettings origin={ORIGIN} />);
    expect(link('Card spotlight').value).toBe(`${ORIGIN}/stream.html?widget=spotlight&scale=150&brand=0&who=opponent`);
  });

  it('builds the full overlay link from its slider and sideboard choice', () => {
    render(<StreamKitSettings origin={ORIGIN} />);
    const overlay = screen.getByRole('article', { name: 'Full overlay' });
    expect(link('Full overlay').value).toBe(`${ORIGIN}/stream.html?widget=overlay`);
    expect(within(overlay).getByText('520 × 960')).toBeInTheDocument();
    fireEvent.change(within(overlay).getByLabelText(/Background/), { target: { value: '30' } });
    fireEvent.change(within(overlay).getByLabelText('Sideboard'), { target: { value: 'below' } });
    // The shared background choice belongs to the other widgets.
    fireEvent.change(screen.getByLabelText('Background', { selector: 'select' }), { target: { value: 'glass' } });
    expect(link('Full overlay').value).toBe(`${ORIGIN}/stream.html?widget=overlay&opacity=30&sideboard=below`);
    expect(link('Deck tracker').value).toBe(`${ORIGIN}/stream.html?widget=deck&bg=glass`);
    expect(within(overlay).getByText('320 × 1320')).toBeInTheDocument();
    expect(within(overlay).getByText('30%')).toBeInTheDocument();
  });

  it('sets how many recent games to show', () => {
    render(<StreamKitSettings origin={ORIGIN} />);
    const games = screen.getByRole('article', { name: 'Recent games' });
    expect(link('Recent games').value).toBe(`${ORIGIN}/stream.html?widget=games`);
    expect(within(games).getByLabelText('Games shown')).toHaveValue('10');
    fireEvent.change(within(games).getByLabelText('Games shown'), { target: { value: '1' } });
    expect(link('Recent games').value).toBe(`${ORIGIN}/stream.html?widget=games&count=1`);
    expect(within(games).getByText('380 × 140')).toBeInTheDocument();
    fireEvent.click(within(games).getByLabelText('Record', { selector: 'input' }));
    expect(link('Recent games').value).toBe(`${ORIGIN}/stream.html?widget=games&count=1&hide=record`);
    expect(within(games).getByText('380 × 100')).toBeInTheDocument();
    expect(within(games).getByRole('option', { name: 'Last 25' })).toBeInTheDocument();
  });

  it('builds the new live widgets’ links from their choices', () => {
    render(<StreamKitSettings origin={ORIGIN} />);
    for (const [title, id] of [
      ['Scorebug', 'scorebug'],
      ['Deck stats', 'deckstats'],
      ['What they’re on', 'opponent'],
      ['Flood / screw meter', 'lands'],
      ['Game result', 'result'],
      ['Intermission', 'break'],
    ]) {
      expect(link(title).value).toBe(`${ORIGIN}/stream.html?widget=${id}`);
    }

    const scorebug = screen.getByRole('article', { name: 'Scorebug' });
    fireEvent.click(within(scorebug).getByLabelText('Turn timer'));
    expect(link('Scorebug').value).toBe(`${ORIGIN}/stream.html?widget=scorebug&hide=timer`);
    // The opponent's name sits in the same Show list but keeps its own link option.
    fireEvent.click(within(scorebug).getByLabelText('Opponent name'));
    expect(link('Scorebug').value).toBe(`${ORIGIN}/stream.html?widget=scorebug&opponent=0&hide=timer`);
    expect(within(scorebug).getByLabelText('Turn timer')).not.toBeChecked();

    const stats = screen.getByRole('article', { name: 'Deck stats' });
    expect(within(stats).getByText('440 × 230')).toBeInTheDocument();
    fireEvent.click(within(stats).getByLabelText('Play / draw'));
    expect(link('Deck stats').value).toBe(`${ORIGIN}/stream.html?widget=deckstats&hide=turn`);

    const record = screen.getByRole('article', { name: 'Record' });
    fireEvent.change(within(record).getByLabelText('Record'), { target: { value: 'today' } });
    expect(link('Record').value).toBe(`${ORIGIN}/stream.html?widget=record&period=today`);
    fireEvent.click(within(record).getByLabelText('Deck record'));
    expect(link('Record').value).toBe(`${ORIGIN}/stream.html?widget=record&period=today&hide=deck`);

    const opponent = screen.getByRole('article', { name: 'What they’re on' });
    fireEvent.click(within(opponent).getByLabelText('Card art'));
    fireEvent.change(within(opponent).getByLabelText('Lands'), { target: { value: 'all' } });
    expect(link('What they’re on').value).toBe(`${ORIGIN}/stream.html?widget=opponent&lands=all&hide=art`);

    const intermission = screen.getByRole('article', { name: 'Intermission' });
    fireEvent.change(within(intermission).getByLabelText('Title'), { target: { value: 'Back soon!' } });
    fireEvent.click(within(intermission).getByLabelText('Rank climb'));
    expect(link('Intermission').value).toBe(
      `${ORIGIN}/stream.html?widget=break&title=Back+soon%21&hide=rank`,
    );
    expect(within(intermission).getByText('560 × 308')).toBeInTheDocument();
  });

  it('copies a link', async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    render(<StreamKitSettings origin={ORIGIN} />);
    const matchup = screen.getByRole('article', { name: 'Matchup' });
    await user.click(within(matchup).getByRole('button', { name: /Copy link/ }));
    expect(writeText).toHaveBeenCalledWith(`${ORIGIN}/stream.html?widget=matchup`);
    expect(within(matchup).getByRole('button', { name: /Copied/ })).toBeInTheDocument();
  });
});
