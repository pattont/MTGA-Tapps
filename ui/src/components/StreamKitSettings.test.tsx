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
  it('groups the widgets under the sidebar’s headings', () => {
    render(<StreamKitSettings origin={ORIGIN} />);
    const groups = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(groups).toEqual(['Your deck', 'The game', 'Your record', 'Breaks']);
    const deck = document.getElementById('stream-kit-deck') as HTMLElement;
    expect(within(deck).getAllByRole('article').map((node) => node.getAttribute('aria-label'))).toEqual([
      'Full overlay',
      'Deck tracker',
      'Flood / screw meter',
    ]);
    expect(document.getElementById('stream-kit-start')).toHaveTextContent('Getting started');
  });

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

  it('puts each widget’s own size, background and credit in its link and remembers them', () => {
    const { unmount } = render(<StreamKitSettings origin={ORIGIN} />);
    const spotlight = screen.getByRole('article', { name: 'Card spotlight' });
    fireEvent.change(within(spotlight).getByLabelText('Size'), { target: { value: '150' } });
    fireEvent.change(within(spotlight).getByLabelText('Background'), { target: { value: 'glass' } });
    // The credit checkbox sits beside Preview, on by default.
    const credit = within(spotlight).getByLabelText('Show “Tapps Tracker” credit');
    expect(credit).toBeChecked();
    fireEvent.click(credit);
    fireEvent.change(within(spotlight).getByLabelText('Cards from'), { target: { value: 'opponent' } });

    expect(link('Card spotlight').value).toBe(`${ORIGIN}/stream.html?widget=spotlight&scale=150&bg=glass&brand=0&who=opponent`);
    // The spotlight's choices stay on the spotlight.
    expect(link('Deck tracker').value).toBe(`${ORIGIN}/stream.html?widget=deck`);
    expect(within(spotlight).getByText('450 × 705')).toBeInTheDocument();

    unmount();
    render(<StreamKitSettings origin={ORIGIN} />);
    expect(link('Card spotlight').value).toBe(`${ORIGIN}/stream.html?widget=spotlight&scale=150&bg=glass&brand=0&who=opponent`);
  });

  it('starts every widget from the size, background and credit once chosen for all of them', () => {
    localStorage.setItem('mtga-stream-kit', JSON.stringify({ shared: { scale: 125, bg: 'none', brand: false }, widgets: {} }));
    render(<StreamKitSettings origin={ORIGIN} />);
    expect(link('Deck tracker').value).toBe(`${ORIGIN}/stream.html?widget=deck&scale=125&bg=none&brand=0`);
    const deck = screen.getByRole('article', { name: 'Deck tracker' });
    fireEvent.change(within(deck).getByLabelText('Size'), { target: { value: '100' } });
    expect(link('Deck tracker').value).toBe(`${ORIGIN}/stream.html?widget=deck&bg=none&brand=0`);
    // Other widgets keep the older choice.
    expect(link('Record').value).toBe(`${ORIGIN}/stream.html?widget=record&scale=125&bg=none&brand=0`);
  });

  it('builds the full overlay link from its slider and sideboard choice', () => {
    render(<StreamKitSettings origin={ORIGIN} />);
    const overlay = screen.getByRole('article', { name: 'Full overlay' });
    expect(link('Full overlay').value).toBe(`${ORIGIN}/stream.html?widget=overlay`);
    expect(within(overlay).getByText('520 × 960')).toBeInTheDocument();
    fireEvent.change(within(overlay).getByLabelText(/Background/), { target: { value: '30' } });
    fireEvent.change(within(overlay).getByLabelText('Sideboard'), { target: { value: 'below' } });
    // The overlay's background is its slider; it has no Solid / See-through choice.
    expect(within(overlay).queryByLabelText('Background', { selector: 'select' })).toBeNull();
    expect(within(overlay).getByLabelText('Size')).toHaveValue('100');
    expect(link('Full overlay').value).toBe(`${ORIGIN}/stream.html?widget=overlay&opacity=30&sideboard=below`);
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
    // Every record is today's: there is no Session | Today choice.
    expect(within(record).queryByLabelText('Record', { selector: 'select' })).toBeNull();
    // Its only dropdowns are its own size and background.
    expect(within(record).getAllByRole('combobox')).toEqual([
      within(record).getByLabelText('Size'),
      within(record).getByLabelText('Background'),
    ]);
    fireEvent.click(within(record).getByLabelText('Deck record'));
    expect(link('Record').value).toBe(`${ORIGIN}/stream.html?widget=record&hide=deck`);

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
