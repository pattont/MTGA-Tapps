import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchDeckFinderJob, fetchDeckFinderProviders, fetchDeckFinderSources,
  hydrateDeckFinderDeck, startDeckFinderFetch,
  type DeckFinderDeck, type DeckFinderJobStatus, type DeckFinderProvider, type DeckFinderView,
} from '../api';
import { fetchDeckLibrary, importManagedDeck, addDeckToArena, fetchNativeDeckStatus, fetchNativeDeckJob } from '../deckManagerApi';
import { DeckFinderPage } from './DeckFinderPage';
import { exportedDeckName } from '../deckFinderName';

vi.mock('../deckManagerApi', () => ({ fetchDeckLibrary: vi.fn().mockResolvedValue({ collections: [], decks: [] }), importManagedDeck: vi.fn(), addDeckToArena: vi.fn(), fetchNativeDeckStatus: vi.fn(), fetchNativeDeckJob: vi.fn() }));

vi.mock('../api', () => ({
  fetchDeckFinderJob: vi.fn(), fetchDeckFinderProviders: vi.fn(),
  fetchDeckFinderSources: vi.fn(), hydrateDeckFinderDeck: vi.fn(),
  startDeckFinderFetch: vi.fn(), startDeckFinderSurprise: vi.fn(),
  startDeckFinderVariants: vi.fn(),
}));

const youtube: DeckFinderProvider = {
  key: 'youtube', display_name: 'youtube.com', description: 'Creators',
  homepage: 'https://www.youtube.com/', format_options: ['any'],
  uses_source_picker: true, allow_all_sources: false, source_picker_title: 'Creators',
  source_picker_all_label: 'all matching endpoints', creators: [],
};
const sources = [
  { name: 'Hello Good Game', url: 'https://www.youtube.com/@HelloGoodGame/videos', description: 'Latest 15 descriptions', formats: ['any'] },
  { name: 'Sloth', url: 'https://www.youtube.com/@SlothMtg/videos', description: 'Latest 15 descriptions', formats: ['any'] },
];
const view: DeckFinderView = {
  title: 'Creator Decks', count_label: 'Decks found', name_column_label: 'Deck',
  selection_label: 'Deck', selection_action: 'details', helper_text: null, show_notes: false,
  columns: [{ key: 'name', label: 'Deck' }, { key: 'player', label: 'Creator' }],
};
const deck: DeckFinderDeck = {
  name: 'Ramp 5 Lands at Once', source_site: 'youtube.com',
  source_url: 'https://www.youtube.com/watch?v=BfEESYLUBLQ', format_label: 'Standard',
  matches: null, win_rate: null, player_name: 'Hello Good Game', placing: null,
  event_name: null, event_date: null, notes: null,
  deck_text: 'About\nName Ramp 5 Lands at Once (HGG)\n\nDeck\n60 Forest',
  cells: { name: 'Ramp 5 Lands at Once', player: 'Hello Good Game' },
};

beforeEach(() => {
  vi.resetAllMocks();
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', ''); } },
    close: { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open'); } },
  });
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ collections: [], decks: [], capabilities: { arena_transfers: false, native_section: false, capacity: null, message: '' } });
  vi.mocked(fetchDeckFinderProviders).mockResolvedValue([youtube]);
  vi.mocked(fetchDeckFinderSources).mockResolvedValue(sources);
  vi.mocked(startDeckFinderFetch).mockResolvedValue({ done: true, decks: [deck], view });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: false, connected: false, busy: false,
    decks: [], limit: null, limit_reached: null, deck_screen_open: false, message: '' });
});

async function chooseCreator(name = 'Hello Good Game') {
  fireEvent.click(await screen.findByRole('button', { name: /youtube\.com\s*Creators/ }));
  const creators = await screen.findByRole('group', { name: 'Creators' });
  fireEvent.click(within(creators).getByRole('button', { name }));
}

describe('YouTube Deck Finder', () => {
  it('opens the first deck in the selected panel and keeps the browser available', async () => {
    const listed = { ...deck, deck_text: 'About\nName Ramp 5 Lands at Once (HGG)\n\nDeck\n4 Opt (STA) 19\n56 Island\nSideboard\n2 Negate (MOM) 68' };
    vi.mocked(startDeckFinderFetch).mockResolvedValue({ done: true, decks: [listed], view });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<DeckFinderPage />);
    await chooseCreator();
    const panel = await screen.findByRole('complementary', { name: 'Selected deck' });
    expect(within(panel).getByRole('heading', { name: 'Ramp 5 Lands at Once (HGG)' })).toBeInTheDocument();
    expect(within(panel).getByText('Hello Good Game · Standard · 60 cards')).toBeInTheDocument();
    expect(within(panel).queryByText('Selected deck')).not.toBeInTheDocument();
    expect(within(panel).queryByText(/card names/)).not.toBeInTheDocument();
    expect(within(panel).getByRole('list', { name: 'Deck cards' })).toHaveTextContent('4Opt56Island');
    expect(within(panel).getByRole('list', { name: 'Sideboard cards' })).toHaveTextContent('2Negate');
    expect(screen.getByRole('region', { name: 'Deck Finder results' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: deck.name })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(within(panel).getByRole('button', { name: 'Export to Arena' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(listed.deck_text?.replace('\nSideboard', '\n\nSideboard')));
  });

  it('keeps the new deck loading when an older creator hydration finishes', async () => {
    let finishOld!: (value: DeckFinderDeck) => void;
    let finishNew!: (value: DeckFinderDeck) => void;
    const old = { ...deck, deck_text: null };
    const newer = { ...deck, name: 'Sloth Brew', source_url: sources[1].url, deck_text: null };
    vi.mocked(startDeckFinderFetch).mockResolvedValueOnce({ done: true, decks: [old], view });
    vi.mocked(hydrateDeckFinderDeck)
      .mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { finishNew = resolve; }));
    render(<DeckFinderPage />);
    await chooseCreator();
    await waitFor(() => expect(hydrateDeckFinderDeck).toHaveBeenCalledTimes(1));
    vi.mocked(startDeckFinderFetch).mockResolvedValue({ done: true, decks: [newer], view });
    fireEvent.click(within(screen.getByRole('group', { name: 'Creators' })).getByRole('button', { name: 'Sloth' }));
    await waitFor(() => expect(hydrateDeckFinderDeck).toHaveBeenCalledTimes(2));
    await act(async () => { finishOld({ ...old, deck_text: 'Deck\n60 Forest' }); });
    const panel = screen.getByRole('complementary', { name: 'Selected deck' });
    expect(within(panel).getByRole('heading', { name: 'Sloth Brew' })).toBeInTheDocument();
    expect(within(panel).getByRole('status')).toHaveTextContent('Loading deck list');
    expect(within(panel).queryByText('Forest')).not.toBeInTheDocument();
    await act(async () => { finishNew({ ...newer, deck_text: 'Deck\n60 Island' }); });
    expect(within(panel).getByText('Island')).toBeInTheDocument();
    expect(within(panel).queryByRole('status')).not.toBeInTheDocument();
  });

  it('opens the site picker without fetching sources or decks', async () => {
    const moxfield = {
      ...youtube, key: 'moxfield', display_name: 'moxfield.com',
      description: 'Full details about the public creator decks.',
    };
    vi.mocked(fetchDeckFinderProviders).mockResolvedValue([moxfield, youtube]);
    render(<DeckFinderPage />);
    const site = await screen.findByRole('button', { name: /moxfield\.com\s*Creators/ });
    expect(site).toHaveAttribute('title', moxfield.description);
    expect(screen.getByRole('button', { name: /youtube\.com\s*Creators/ })).toBeInTheDocument();
    expect(fetchDeckFinderSources).not.toHaveBeenCalled();
    expect(startDeckFinderFetch).not.toHaveBeenCalled();
  });

  it('fits the provider cards and shows only a Creators picker', async () => {
    render(<DeckFinderPage />);
    await chooseCreator('Sloth');
    expect(screen.queryByRole('group', { name: 'Match format' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /All \(/ })).not.toBeInTheDocument();
    expect(startDeckFinderFetch).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'youtube', format: 'any', source_name: 'Sloth', source_url: sources[1].url,
    }));
  });

  it('shows a simple loading message without a progress bar and exports without hydration', async () => {
    let finish!: (value: DeckFinderJobStatus) => void;
    vi.mocked(startDeckFinderFetch).mockResolvedValue({ job: 'youtube-job' });
    vi.mocked(fetchDeckFinderJob).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<DeckFinderPage />);
    await chooseCreator();
    expect(await screen.findByRole('status')).toHaveTextContent('Checking the latest 15 YouTube videos for decklists…');
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    await waitFor(() => expect(fetchDeckFinderJob).toHaveBeenCalled());
    await act(async () => { finish({ status: 'done', decks: [deck], view }); });
    fireEvent.click(await screen.findByRole('button', { name: deck.name }));
    fireEvent.click(screen.getByRole('button', { name: 'Export to Arena' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(deck.deck_text));
    expect(hydrateDeckFinderDeck).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute('href', deck.source_url);
  });

  it('retains the completed table during a YouTube refresh', async () => {
    render(<DeckFinderPage />);
    await chooseCreator();
    expect(await screen.findByRole('button', { name: deck.name })).toBeInTheDocument();
    vi.mocked(startDeckFinderFetch).mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(screen.getByRole('button', { name: deck.name })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Checking the latest 15 YouTube videos');
    expect(startDeckFinderFetch).toHaveBeenLastCalledWith(expect.objectContaining({ refresh: true }));
  });

  it('links to Settings when all YouTube creators are removed', async () => {
    vi.mocked(fetchDeckFinderSources).mockResolvedValue([]);
    render(<DeckFinderPage />);
    fireEvent.click(await screen.findByRole('button', { name: /youtube\.com\s*Creators/ }));
    expect(await screen.findByRole('link', { name: 'Settings' })).toHaveAttribute('href', '#/settings');
    expect(startDeckFinderFetch).not.toHaveBeenCalled();
  });

  it('does not replace a newly selected creator with an older completed job', async () => {
    let finish!: (value: DeckFinderJobStatus) => void;
    vi.mocked(startDeckFinderFetch).mockResolvedValueOnce({ job: 'old' });
    vi.mocked(fetchDeckFinderJob).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<DeckFinderPage />);
    await chooseCreator();
    await waitFor(() => expect(fetchDeckFinderJob).toHaveBeenCalled());
    const newer = { ...deck, name: 'Sloth Deck', source_url: 'https://www.youtube.com/watch?v=OVM43LPOhD4' };
    vi.mocked(startDeckFinderFetch).mockResolvedValue({ done: true, decks: [newer], view });
    fireEvent.click(within(screen.getByRole('group', { name: 'Creators' })).getByRole('button', { name: 'Sloth' }));
    expect(await screen.findByRole('button', { name: 'Sloth Deck' })).toBeInTheDocument();
    await act(async () => { finish({ status: 'done', decks: [deck], view }); });
    expect(screen.queryByRole('button', { name: deck.name })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sloth Deck' })).toBeInTheDocument();
  });
});


it('saves a selected Deck Finder list to the general library', async () => {
  vi.mocked(importManagedDeck).mockResolvedValue({ id: 'saved-id' } as Awaited<ReturnType<typeof importManagedDeck>>);
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  fireEvent.click(screen.getByRole('button', { name: 'Save to collection' }));
  expect(importManagedDeck).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole('button', { name: 'Unsorted' }));
  await waitFor(() => expect(importManagedDeck).toHaveBeenCalledWith(deck.deck_text, 'Ramp 5 Lands at Once (HGG)', 'Standard', undefined, null));
  expect(await screen.findByText(/Deck saved to Unsorted/)).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: 'Open Deck Manager' })).toHaveAttribute('href', '#/deck-manager');
});

it('adds the chosen list directly to Arena once and monitors the result without clipboard use', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: true, connected: false, busy: false, decks: [], limit: null, limit_reached: null, deck_screen_open: false, message: '' });
  vi.mocked(addDeckToArena).mockResolvedValue({ job_id: 'native-import' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'add', count: 1 } });
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  fireEvent.click(await screen.findByRole('button', { name: 'Add to Arena' }));
  await waitFor(() => expect(addDeckToArena).toHaveBeenCalledExactlyOnceWith(deck.deck_text, 'Ramp 5 Lands at Once (HGG)', 'Standard'));
  expect(await screen.findByRole('status')).toHaveTextContent('Deck added to Arena');
  expect(screen.getByRole('button', { name: 'Added to Arena' })).toBeDisabled();
  expect(importManagedDeck).not.toHaveBeenCalled();
});

it('tells the user to return to Arena’s Decks screen instead of opening Deck Manager', async () => {
  const reason = 'Arena isn’t on its Decks screen. Go to Decks in Arena, outside a match, then try again.';
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: true, connected: false, busy: false, decks: [], limit: 100, limit_reached: false, deck_screen_open: false, message: '' });
  vi.mocked(addDeckToArena).mockResolvedValue({ job_id: 'not-on-decks' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'error', detail: reason });
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  expect(screen.getByText('Arena must be on its Decks screen')).not.toHaveClass('deckfinder-manager-hint-alert');
  fireEvent.click(await screen.findByRole('button', { name: 'Add to Arena' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(reason);
  expect(screen.queryByRole('link', { name: 'Open Deck Manager' })).not.toBeInTheDocument();
  expect(screen.getByText('Arena must be on its Decks screen')).toHaveClass('deckfinder-manager-hint-alert');
});

it.each([{ in_game: true }, { limit_reached: true }])('blocks direct adds while a game is active or slots are full', async (guard) => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: true, connected: true, busy: false, decks: [], limit: 100, limit_reached: false, deck_screen_open: true, message: '', ...guard });
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  expect(await screen.findByRole('button', { name: 'Add to Arena' })).toBeDisabled();
  expect(addDeckToArena).not.toHaveBeenCalled();
});

it('adds a previously saved deck using the same library entry and selected collection', async () => {
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ collections: [{ id: 'green', name: 'Green' }], decks: [], capabilities: { arena_transfers: false, native_section: false, capacity: null, message: '' } });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: true, connected: false, busy: false, decks: [], limit: 100, limit_reached: false, deck_screen_open: true, message: '' });
  vi.mocked(importManagedDeck).mockResolvedValue({ id: 'saved-id' } as Awaited<ReturnType<typeof importManagedDeck>>);
  vi.mocked(addDeckToArena).mockResolvedValue({ job_id: 'add-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'running', detail: 'Preparing…', progress: { completed: 0, total: 1 } });
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save to collection' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Green' }));
  await screen.findByText(/Deck saved to Green/);
  expect(importManagedDeck).toHaveBeenCalledWith(deck.deck_text, 'Ramp 5 Lands at Once (HGG)', 'Standard', undefined, 'green');
  fireEvent.click(screen.getByRole('button', { name: 'Add to Arena' }));
  await waitFor(() => expect(addDeckToArena).toHaveBeenCalledExactlyOnceWith(deck.deck_text, 'Ramp 5 Lands at Once (HGG)', 'Standard', 'saved-id', 'green'));
  expect(await screen.findByRole('progressbar')).toHaveAttribute('value', '0');
});

it('searches collections in the save picker', async () => {
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ collections: [{ id: 'green', name: 'Green' }, { id: 'brawl', name: 'Brawl decks' }], decks: [], capabilities: { arena_transfers: false, native_section: false, capacity: null, message: '' } });
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  fireEvent.click(screen.getByRole('button', { name: 'Save to collection' }));
  fireEvent.change(await screen.findByRole('searchbox', { name: 'Search collections' }), { target: { value: 'braw' } });
  expect(screen.getByRole('button', { name: 'Brawl decks' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Green' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Unsorted' })).not.toBeInTheDocument();
});

it('explains that a pending transfer pauses direct adds', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: true, connected: true, busy: false, decks: [], limit: 100, limit_reached: false, deck_screen_open: true, message: '', pending_transfers: [{ id: 't', action: 'restore', phase: 'uncertain', deck_id: 'd' }] });
  render(<DeckFinderPage />);
  await chooseCreator();
  fireEvent.click(await screen.findByRole('button', { name: deck.name }));
  expect(await screen.findByRole('button', { name: 'Add to Arena' })).toBeDisabled();
  expect(screen.getByText(/paused until an interrupted transfer is reconciled/)).toBeInTheDocument();
});

it('reads the exported Arena name, falling back to the listed name', () => {
  expect(exportedDeckName('About\nName Rakdos Lizards (Ash)\n\nDeck\n4 Forest', 'Rakdos Lizards')).toBe('Rakdos Lizards (Ash)');
  expect(exportedDeckName('Deck\n4 Forest', 'Rakdos Lizards')).toBe('Rakdos Lizards');
});
