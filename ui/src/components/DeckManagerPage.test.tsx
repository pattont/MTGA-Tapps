import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchDeckLibrary, fetchManagedDeck, importManagedDeck, updateManagedDeck, exportManagedDeck, deleteManagedDeck, removeManagedDecks,
  saveDeckCollection, removeDeckCollection, moveDecksToCollection, fetchNativeDeckStatus, startNativeDeckJob, fetchNativeDeckJob, cancelNativeDeckJob, addDeckToArena, fetchArenaDeck,
  type ManagedDeck, type ManagedDeckDetail,
} from '../deckManagerApi';
import { DeckManagerPage } from './DeckManagerPage';

vi.mock('../deckManagerApi', () => ({
  saveDeckCollection: vi.fn(), removeDeckCollection: vi.fn(), moveDecksToCollection: vi.fn(), fetchDeckLibrary: vi.fn(), fetchManagedDeck: vi.fn(), importManagedDeck: vi.fn(),
  updateManagedDeck: vi.fn(), exportManagedDeck: vi.fn(), captureArenaDecks: vi.fn(), deleteManagedDeck: vi.fn(), removeManagedDecks: vi.fn(),
  fetchNativeDeckStatus: vi.fn(), startNativeDeckJob: vi.fn(), fetchNativeDeckJob: vi.fn(), cancelNativeDeckJob: vi.fn(), addDeckToArena: vi.fn(), fetchArenaDeck: vi.fn(),
}));

const saved: ManagedDeck = { id: 'deck-a', name: 'Any format deck', format_name: 'Standard',
  notes: '', tags: [], current_revision_id: 'new', trashed_at: null, saved_at: '2026-10-06T12:00:00Z', updated_at: '2026-10-06T12:00:00Z',
  source: 'import', completeness: 'text', main_count: 60, art_card: null };
const detail: ManagedDeckDetail = { ...saved, revision_id: 'new',
  deck: { name: saved.name, format_name: 'Standard', source: 'import', completeness: 'text',
    import_text: 'Deck\n4 Forest (DMU) 281', cards: [
      { section: 'Deck', quantity: 4, name: 'Forest', arena_id: null, set_code: 'DMU', collector_number: '281' },
      { section: 'Commander', quantity: 1, name: 'Atraxa', arena_id: null, set_code: null, collector_number: null },
    ] },
  revisions: [{ id: 'new', created_at: '2026-10-06T12:00:00Z', source: 'import', content_hash: 'new' },
    { id: 'old', created_at: '2026-10-01T12:00:00Z', source: 'import', content_hash: 'old' }],
};
const capabilities = { arena_transfers: false, native_section: false, capacity: null,
  message: 'Direct Arena transfers are not connected in this build.' };

it('selects an imported deck using its full checkbox label without opening details', async () => {
  render(<DeckManagerPage />);
  const checkbox = await screen.findByRole('checkbox', { name: `Select ${saved.name}` });
  fireEvent.click(checkbox.closest('label')!);
  expect(checkbox).toBeChecked();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(fetchManagedDeck).not.toHaveBeenCalled();
});

it('lists every selected saved deck before a bulk move and preserves selection on cancellation', async () => {
  const other = { ...saved, id: 'deck-b', name: 'Second saved deck' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved, other], capabilities });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
  fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
  await waitFor(() => expect(screen.getByRole('checkbox', { name: `Select ${other.name}` })).toBeChecked());
  fireEvent.click(screen.getByRole('button', { name: 'Move selected to trash' }));
  const dialog = screen.getByRole('dialog', { name: 'Move 2 decks to Trash?' });
  const list = within(dialog).getByRole('list', { name: 'Decks selected for removal' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(2);
  expect(list).toHaveTextContent(saved.name);
  expect(list).toHaveTextContent(other.name);
  expect(removeManagedDecks).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('checkbox', { name: `Select ${saved.name}` })).toBeChecked();
  expect(removeManagedDecks).not.toHaveBeenCalled();
});

it('moves only confirmed selected saved decks and prevents repeat removal', async () => {
  const other = { ...saved, id: 'deck-b', name: 'Second saved deck' };
  let finish!: (value: { ok: boolean; count: number }) => void;
  vi.mocked(removeManagedDecks).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved, other], capabilities });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
  fireEvent.click(screen.getByRole('button', { name: 'Move selected to trash' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Move to trash' }));
  expect(removeManagedDecks).toHaveBeenCalledExactlyOnceWith([saved.id], 'trash');
  expect(screen.getByRole('button', { name: 'Moving…' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, trashed_at: 'today' }, other], capabilities });
  await act(async () => { finish({ ok: true, count: 1 }); });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('1 deck moved to Trash');
});

it('requires confirmation listing trashed decks for bulk permanent deletion and retains them on failure', async () => {
  const other = { ...saved, id: 'deck-b', name: 'Second saved deck', trashed_at: 'today' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, trashed_at: 'today' }, other], capabilities });
  vi.mocked(removeManagedDecks).mockRejectedValue(new Error('Reconcile an interrupted transfer first.'));
  render(<DeckManagerPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Trash' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
  fireEvent.click(screen.getByRole('checkbox', { name: `Select ${other.name}` }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete selected permanently' }));
  const dialog = screen.getByRole('dialog', { name: 'Permanently delete 2 decks?' });
  expect(within(dialog).getByRole('list')).toHaveTextContent(other.name);
  expect(removeManagedDecks).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Delete permanently' }));
  await waitFor(() => expect(removeManagedDecks).toHaveBeenCalledExactlyOnceWith([saved.id, other.id], 'delete'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Reconcile');
  expect(dialog).toBeInTheDocument();
  expect(fetchDeckLibrary).toHaveBeenCalledTimes(1);
});

it('selects decks already in Arena for local removal while rejecting a mixed restore selection', async () => {
  const active = { ...saved, native_restorable: true, native_arena_ids: ['arena-a'] };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [active], capabilities });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
  expect(screen.getByRole('button', { name: 'Move selected to trash' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Restore selected to Arena' })).toBeDisabled();
});

beforeEach(() => {
  vi.resetAllMocks();
  // Sort choices are remembered; each test starts from the defaults.
  localStorage.removeItem('tapps.deckManager.sort');
  localStorage.removeItem('tapps.deckManager.arenaSort');
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', ''); } },
    close: { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open'); } },
  });
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved], capabilities });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ available: false, connected: false, busy: false, decks: [], limit: null, limit_reached: null, deck_screen_open: false, message: 'Open Arena to manage decks.' });
  vi.mocked(fetchManagedDeck).mockResolvedValue(detail);
  vi.mocked(updateManagedDeck).mockResolvedValue({ ok: true });
  vi.mocked(deleteManagedDeck).mockResolvedValue({ ok: true });
  vi.mocked(removeManagedDecks).mockResolvedValue({ ok: true, count: 2 });
  vi.mocked(importManagedDeck).mockResolvedValue(detail);
  vi.mocked(exportManagedDeck).mockResolvedValue({ text: 'Commander\n1 Atraxa\n\nDeck\n4 Forest (DMU) 281', name: saved.name, extension: '.txt' });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe('Deck Manager', () => {
  it('shows any deck and preserves the raw text and optional format on save', async () => {
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add deck' }));
    expect(screen.getByRole('dialog', { name: 'Add a deck' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Deck name'), { target: { value: 'Another deck' } });
    const format = screen.getByRole('combobox', { name: 'Format' });
    expect(format).toHaveValue('');
    expect(within(format).getByRole('option', { name: 'Traditional Standard' })).toHaveValue('TraditionalStandard');
    fireEvent.change(format, { target: { value: 'HistoricBrawl' } });
    const text = 'Commander\n1 Atraxa\n\nDeck\n4 Forest (DMU) 281';
    fireEvent.change(screen.getByLabelText('Decklist or backup'), { target: { value: text } });
    fireEvent.click(screen.getByRole('button', { name: 'Save deck' }));
    await waitFor(() => expect(importManagedDeck).toHaveBeenCalledWith(text, 'Another deck', 'HistoricBrawl', undefined, null));
  });

  it('keeps a revision format that is not in the format list', async () => {
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, format_name: 'Historic Pauper' });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    const dialog = await screen.findByRole('dialog', { name: saved.name });
    fireEvent.click(await within(dialog).findByRole('button', { name: /new revision/i }));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Format' })).toHaveValue('Historic Pauper'));
  });

  it('copies the selected historical revision with its sections and printings', async () => {
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    await screen.findByRole('dialog', { name: saved.name });
    await screen.findByRole('button', { name: 'Copy deck list' });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, revision_id: 'old' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved revision' }), { target: { value: 'old' } });
    await waitFor(() => expect(fetchManagedDeck).toHaveBeenLastCalledWith('deck-a', 'old', expect.any(AbortSignal)));
    const button = await screen.findByRole('button', { name: 'Copy deck list' });
    fireEvent.click(button);
    await waitFor(() => expect(exportManagedDeck).toHaveBeenCalledWith('deck-a', 'old', 'arena'));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Commander\n1 Atraxa\n\nDeck\n4 Forest (DMU) 281');
  });

  it('moves only the local archive to trash and offers restore', async () => {
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    await screen.findByRole('dialog', { name: saved.name });
    const trashed = { ...saved, trashed_at: '2026-10-06' };
    expect(screen.queryByRole('button', { name: 'Delete permanently' })).not.toBeInTheDocument();
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [trashed], capabilities });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, trashed_at: '2026-10-06' });
    fireEvent.click(await screen.findByRole('button', { name: 'Move to trash' }));
    expect(screen.getByRole('dialog', { name: `Move ${saved.name} to Trash?` })).toBeInTheDocument();
    expect(updateManagedDeck).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Move to trash' }));
    await waitFor(() => expect(updateManagedDeck).toHaveBeenCalledWith('deck-a', { trashed: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Trash' }));
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    fireEvent.click(await screen.findByRole('button', { name: 'Restore from trash' }));
    await waitFor(() => expect(updateManagedDeck).toHaveBeenCalledWith('deck-a', { trashed: false }));
  });

  it('cancels a move to Trash without changing the deck or the selected revision', async () => {
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    await screen.findByRole('button', { name: 'Copy deck list' });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, revision_id: 'old' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved revision' }), { target: { value: 'old' } });
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Saved revision' })).toHaveValue('old'));
    fireEvent.click(screen.getByRole('button', { name: 'Move to trash' }));
    expect(screen.getByRole('dialog', { name: `Move ${saved.name} to Trash?` })).toHaveTextContent('You can restore it');
    expect(screen.queryByRole('button', { name: 'Copy deck list' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('combobox', { name: 'Saved revision' })).toHaveValue('old');
    expect(updateManagedDeck).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Move to trash' }));
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: false, cancelable: true }));
    expect(screen.getByRole('dialog', { name: saved.name })).toBeInTheDocument();
    expect(updateManagedDeck).not.toHaveBeenCalled();
  });

  it('retains the deck when a confirmed move to Trash fails', async () => {
    vi.mocked(updateManagedDeck).mockRejectedValue(new Error('Unable to save the library.'));
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    fireEvent.click(await screen.findByRole('button', { name: 'Move to trash' }));
    fireEvent.click(screen.getByRole('button', { name: 'Move to trash' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to save');
    expect(screen.getByRole('dialog', { name: `Move ${saved.name} to Trash?` })).toBeInTheDocument();
    expect(fetchDeckLibrary).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('dialog', { name: saved.name })).toHaveTextContent('Forest');
  });

  it('requires confirmation before deleting a trashed deck and allows cancellation', async () => {
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, trashed_at: '2026-10-06' }], capabilities });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, trashed_at: '2026-10-06' });
    render(<DeckManagerPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Trash' }));
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete permanently' }));
    expect(screen.getByRole('dialog', { name: `Delete ${saved.name}?` })).toHaveTextContent('all 2 saved revisions');
    expect(deleteManagedDeck).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('dialog', { name: saved.name })).toBeInTheDocument();
    expect(deleteManagedDeck).not.toHaveBeenCalled();
    expect(updateManagedDeck).not.toHaveBeenCalled();
  });

  it('deletes only the confirmed deck and prevents repeat actions while deleting', async () => {
    let finish!: (value: { ok: boolean }) => void;
    vi.mocked(deleteManagedDeck).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, trashed_at: '2026-10-06' }], capabilities });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, trashed_at: '2026-10-06' });
    render(<DeckManagerPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Trash' }));
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete permanently' }));
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [], capabilities });
    fireEvent.click(screen.getByRole('button', { name: 'Delete deck' }));
    expect(deleteManagedDeck).toHaveBeenCalledExactlyOnceWith(saved.id);
    expect(screen.getByRole('button', { name: 'Deleting…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    const dialog = screen.getByRole('dialog');
    fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await act(async () => { finish({ ok: true }); });
    expect(await screen.findByText('No decks in trash.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('permanently deleted');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the confirmation and deck available when deletion fails', async () => {
    vi.mocked(deleteManagedDeck).mockRejectedValue(new Error('The deck library could not be saved.'));
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, trashed_at: '2026-10-06' }], capabilities });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, trashed_at: '2026-10-06' });
    render(<DeckManagerPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Trash' }));
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete permanently' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete deck' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be saved');
    expect(screen.getByRole('dialog', { name: `Delete ${saved.name}?` })).toBeInTheDocument();
    expect(fetchDeckLibrary).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('dialog', { name: saved.name })).toHaveTextContent('Forest');
  });

  it('retains input when saving fails', async () => {
    vi.mocked(importManagedDeck).mockRejectedValue(new Error('Unrecognized card on line 2.'));
    render(<DeckManagerPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Add deck' }));
    const text = 'Deck\ninvalid';
    fireEvent.change(screen.getByLabelText('Decklist or backup'), { target: { value: text } });
    fireEvent.click(screen.getByRole('button', { name: 'Save deck' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unrecognized card on line 2.');
    expect(screen.getByLabelText('Decklist or backup')).toHaveValue(text);
  });

  it('ignores a slow detail response after selecting a different deck', async () => {
    let finish!: (value: ManagedDeckDetail) => void;
    vi.mocked(fetchManagedDeck).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const other = { ...saved, id: 'deck-b', name: 'Second deck' };
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved, other], capabilities });
    vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, ...other });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    fireEvent.click(screen.getByRole('button', { name: /Second deck/ }));
    await screen.findByRole('heading', { name: 'Second deck' });
    await act(async () => { finish(detail); });
    expect(screen.getByRole('heading', { name: 'Second deck' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: saved.name })).not.toBeInTheDocument();
  });
});


it('shows a large collection without opening or fetching details until a deck is clicked', async () => {
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: Array.from({ length: 104 }, (_, i) => ({ ...saved, id: `deck-${i}`, name: `Saved list ${i}` })), capabilities });
  render(<DeckManagerPage />);
  expect(await screen.findByRole('button', { name: 'Saved Locally (104)' })).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /Saved list/ })).toHaveLength(104);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(fetchManagedDeck).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved decks' }), { target: { value: 'Saved list 103' } });
  expect(screen.getAllByRole('button', { name: /Saved list/ })).toHaveLength(1);
  // 104 tiles: allow for a busy machine during the full suite (0.3 s on its own).
}, 15000);

it('closes on Escape and restores focus and scrolling to the collection', async () => {
  render(<DeckManagerPage />);
  const tile = await screen.findByRole('button', { name: new RegExp(saved.name) });
  tile.focus();
  fireEvent.click(tile);
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  expect(document.body.style.overflow).toBe('hidden');
  // The hidden scrollbar's space stays reserved so the tiles do not shift.
  expect(document.documentElement.style.scrollbarGutter).toBe('stable');
  fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(tile).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
  expect(document.documentElement.style.scrollbarGutter).not.toBe('stable');
});

it('keeps deck details open when clicking outside them; only the close button closes', async () => {
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  // jsdom gives the dialog an empty rect, so any positive point is outside it.
  fireEvent.mouseDown(dialog, { clientX: 50, clientY: 50 });
  fireEvent.click(dialog, { clientX: 50, clientY: 50 });
  expect(screen.getByRole('dialog', { name: saved.name })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close dialog' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('keeps Add deck open until its close button is used', async () => {
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Add deck' }));
  const dialog = screen.getByRole('dialog', { name: 'Add a deck' });
  fireEvent.mouseDown(dialog, { clientX: 50, clientY: 50 });
  fireEvent.click(dialog, { clientX: 50, clientY: 50 });
  expect(screen.getByRole('dialog', { name: 'Add a deck' })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close dialog' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('shows deck colors on saved and Arena tiles and in the deck dialog', async () => {
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, colors: 'WR' }], capabilities });
  vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, colors: 'WR' });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, decks: [{ ...connected.decks[0], colors: 'UB' }, connected.decks[1]] });
  render(<DeckManagerPage />);
  const tile = await screen.findByRole('button', { name: new RegExp(saved.name) });
  expect(within(tile).getByRole('img', { name: 'Colors: W, R' })).toBeInTheDocument();
  fireEvent.click(tile);
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  expect(within(dialog).getByRole('img', { name: 'Colors: W, R' })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close dialog' }));
  fireEvent.click(screen.getByRole('button', { name: 'Arena (2)' }));
  const arenaTile = await screen.findByRole('button', { name: /^Arena fixture A/ });
  expect(within(arenaTile).getByRole('img', { name: 'Colors: U, B' })).toBeInTheDocument();
  expect(within(screen.getByRole('button', { name: /^Arena fixture B/ })).queryByRole('img', { name: /Colors/ })).not.toBeInTheDocument();
});

it('edits a revision in a dialog bound to the opened deck', async () => {
  render(<DeckManagerPage />);
  const tile = await screen.findByRole('button', { name: new RegExp(saved.name) });
  tile.focus();
  fireEvent.click(tile);
  fireEvent.click(await screen.findByRole('button', { name: 'Edit as new revision' }));
  expect(await screen.findByRole('dialog', { name: 'Save a new revision' })).toBeInTheDocument();
  const text = 'Deck\n5 Forest';
  fireEvent.change(screen.getByLabelText('Decklist or backup'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Save revision' }));
  await waitFor(() => expect(importManagedDeck).toHaveBeenCalledWith(text, saved.name, 'Standard', saved.id, undefined));
  expect(await screen.findByRole('dialog', { name: saved.name })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
  expect(tile).toHaveFocus();
});

const connected = { available: true, connected: true, busy: false, deck_screen_open: true,
  limit: 100, limit_reached: false, message: 'Arena ready.', refreshed_at: '2026-10-07T12:00:00Z',
  decks: [{ id: 'arena-a', name: 'Arena fixture A', format_name: 'Standard', main_count: 60 },
    { id: 'arena-b', name: 'Arena fixture B', format_name: 'Brawl', main_count: 100 }], pending_transfers: [] };

it('shows each deck\'s record table (Ranked, Casual, Play / Draw, Played) on its tile and in its dialog', async () => {
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, record: { wins: 16, losses: 9,
    ranked: { wins: 15, losses: 9 }, unranked: { wins: 1, losses: 0 }, play: { wins: 10, losses: 4 }, draw: { wins: 6, losses: 5 } } }], capabilities,
    records: { 'arena-a': { wins: 2, losses: 3, ranked: { wins: 0, losses: 0 }, unranked: { wins: 2, losses: 3 }, play: { wins: 0, losses: 0 }, draw: { wins: 2, losses: 3 } } } });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(fetchArenaDeck).mockReturnValue(new Promise(() => {}));
  render(<DeckManagerPage />);
  const savedRecord = await screen.findByTitle(/^Ranked: 15 wins, 9 losses\sCasual \(unranked queues and events\): 1 win, 0 losses\sOn the play: 10 wins, 4 losses\sOn the draw: 6 wins, 5 losses\s25 games played/);
  expect(savedRecord).toHaveTextContent('Ranked15–963%Casual1–0100%Play / Draw71%/55%Played25');
  expect(within(savedRecord).getByText('63%')).toHaveClass('is-winning');
  fireEvent.click(screen.getByRole('button', { name: 'Arena (2)' }));
  // Only the queue it was played in; a side with no games shows a dash.
  const arenaRecord = await screen.findByTitle(/^Casual \(unranked queues and events\): 2 wins, 3 losses\sOn the play: no games/);
  expect(arenaRecord).toHaveTextContent('Casual2–340%Play / Draw–/40%Played5');
  expect(within(arenaRecord).getAllByText('40%')[0]).toHaveClass('is-losing');
  // A deck never played says so, quietly.
  expect(screen.getByText('No games logged')).toHaveClass('deck-record-empty');
  // The footer's empty space opens the deck, like the rest of the tile; the dialog repeats the record.
  fireEvent.click(arenaRecord);
  const dialog = await screen.findByRole('dialog', { name: 'Arena fixture A' });
  expect(within(dialog).getByTitle(/^Casual \(unranked queues and events\): 2 wins, 3 losses/)).toHaveClass('deck-record-dialog');
});

it('reads native status without automatically starting an Arena job', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  render(<DeckManagerPage />);
  expect(await screen.findByRole('button', { name: 'Arena (2)' })).toBeInTheDocument();
  expect(startNativeDeckJob).not.toHaveBeenCalled();
});

it('requires confirmation for bulk moves and cancellation never starts a job', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Arena fixture A' }));
  fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
  fireEvent.click(screen.getByRole('button', { name: 'Move to collection' }));
  const dialog = screen.getByRole('dialog', { name: 'Move 2 decks out of Arena?' });
  expect(dialog).toHaveTextContent('deleted from Arena');
  expect(dialog).toHaveTextContent('Arena may keep showing these decks until you leave its Decks screen and open it again.');
  expect(dialog).toHaveTextContent('Arena fixture A');
  expect(dialog).toHaveTextContent('Arena fixture B');
  expect(startNativeDeckJob).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  expect(startNativeDeckJob).not.toHaveBeenCalled();
  expect(screen.getByRole('checkbox', { name: 'Select Arena fixture A' })).toBeChecked();
});

it('moves only the confirmed selected Arena decks and monitors the job', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'move-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'store', count: 1 } });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Arena fixture A' }));
  fireEvent.click(screen.getByRole('button', { name: 'Move to collection' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Move out of Arena' }));
  await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('store', [{ id: 'arena-a' }], null));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Moved 1 deck to Unsorted and removed it from Arena. If Arena still shows it'));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('moves Arena decks straight into the chosen collection', async () => {
  const collection = { id: 'group-a', name: 'Control' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [], collections: [collection], capabilities });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'move-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'store', count: 1 } });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Arena fixture A' }));
  fireEvent.click(screen.getByRole('button', { name: 'Move to collection' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Save to collection' }), { target: { value: collection.id } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Move out of Arena' }));
  await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('store', [{ id: 'arena-a' }], collection.id));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(`Moved 1 deck to ${collection.name}`));
});

it('creates a new collection for Arena decks before moving them', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(saveDeckCollection).mockResolvedValue({ id: 'group-new', name: 'Retired' });
  vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'move-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'running', detail: 'Moving…' });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Arena fixture A' }));
  fireEvent.click(screen.getByRole('button', { name: 'Move to collection' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Save to collection' }), { target: { value: '__new__' } });
  const move = within(dialog).getByRole('button', { name: 'Move out of Arena' });
  expect(move).toBeDisabled();
  fireEvent.change(within(dialog).getByRole('textbox', { name: 'New collection name' }), { target: { value: 'Retired' } });
  fireEvent.click(move);
  await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('store', [{ id: 'arena-a' }], 'group-new'));
  expect(saveDeckCollection).toHaveBeenCalledExactlyOnceWith('Retired');
});

it('restores the selected native revision directly without copying', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, native_restorable: true });
  vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'restore-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'restore', count: 1 } });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  fireEvent.click(await screen.findByRole('button', { name: 'Restore to Arena' }));
  await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('restore', [{ id: saved.id, revision: 'new' }]));
  expect(exportManagedDeck).not.toHaveBeenCalled();
  expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
});

it('disables native restore when slots are full and offers reconciliation for interruptions', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, limit_reached: true,
    pending_transfers: [{ id: 'pending', action: 'restore', phase: 'uncertain', deck_id: saved.id }] });
  vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, native_restorable: true });
  render(<DeckManagerPage />);
  expect(await screen.findByRole('button', { name: 'Reconcile transfers' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: new RegExp(saved.name) }));
  expect(await screen.findByRole('button', { name: 'Restore to Arena' })).toBeDisabled();
  expect(startNativeDeckJob).not.toHaveBeenCalled();
});

it('loads tile art from Scryfall’s image server or the printing before any name lookup', async () => {
  const [a, b] = connected.decks;
  const cdn = 'https://cards.scryfall.io/art_crop/front/4/9/494e.jpg';
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, decks: [
    { ...a, art_card: 'Restoration Magic', art_card_id: 95884, art_url: cdn, art_print: 'fin/30' },
    { ...b, art_card: 'Ajani Unrelenting', art_card_id: 106487, art_url: null, art_print: 'fra/242' },
  ] });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  expect(await screen.findByRole('img', { name: 'Restoration Magic' })).toHaveAttribute('src', cdn);
  expect(screen.getByRole('img', { name: 'Ajani Unrelenting' })).toHaveAttribute('src', 'https://api.scryfall.com/cards/fra/242?format=image&version=art_crop');
});

it('uses the saved artwork for matching Arena tiles and filters their backup status', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, native_restorable: true, native_arena_ids: ['arena-a'], art_card: 'Forest' }], capabilities });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  const image = await screen.findByRole('img', { name: 'Forest' });
  expect(image).toHaveAttribute('src', expect.stringContaining('named?exact=Forest'));
  fireEvent.click(screen.getByRole('button', { name: 'Filter by Not backed up' }));
  expect(screen.getByRole('combobox', { name: 'Filter decks by status' })).toHaveValue('unbacked');
  expect(screen.queryByRole('checkbox', { name: 'Select Arena fixture A' })).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Select Arena fixture B' })).toBeInTheDocument();
});

it('shows only the badges that tell decks apart', async () => {
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved, { ...saved, id: 'gone', name: 'Trashed deck', native_restorable: true, trashed_at: '2026-10-06' }], capabilities });
  render(<DeckManagerPage />);
  // Arena not read yet: no presence badge, just the kind of copy.
  expect(await screen.findByRole('button', { name: 'Filter by Deck list' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Filter by (In Arena|Not in Arena|Arena not checked)/ })).not.toBeInTheDocument();
  expect(within(screen.getByRole('combobox', { name: 'Filter decks by status' })).queryByRole('option', { name: 'In Arena' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /^Trash/ }));
  expect(await screen.findByRole('button', { name: 'Filter by Exact copy' })).toBeInTheDocument();
  expect(screen.queryByText('In Trash')).not.toBeInTheDocument();
});

it('filters saved presence and backup type through pills and clears hidden selection', async () => {
  const second = { ...saved, id: 'second', name: 'Collection deck', native_restorable: true };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, native_arena_ids: ['arena-a'] }, second], capabilities });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${second.name}` }));
  // Only decks in Arena get a presence pill; "Not in Arena" stays a filter option.
  expect(screen.queryByRole('button', { name: 'Filter by Not in Arena' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Filter by Exact copy' })).toHaveAttribute('title', expect.stringContaining('exactly as it was'));
  fireEvent.click(await screen.findByRole('button', { name: 'Filter by In Arena' }));
  expect(screen.queryByRole('checkbox', { name: `Select ${second.name}` })).not.toBeInTheDocument();
  // The selection was cleared, so the bar shows search and filters again.
  expect(screen.queryByRole('button', { name: 'Move selected to trash' })).not.toBeInTheDocument();
  expect(screen.getByRole('searchbox', { name: 'Search saved decks' })).toBeInTheDocument();
  expect(fetchManagedDeck).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter decks by status' }), { target: { value: 'collection' } });
  expect(screen.getByRole('checkbox', { name: `Select ${second.name}` })).toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: `Select ${saved.name}` })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter decks by status' }), { target: { value: 'list' } });
  expect(screen.getByRole('checkbox', { name: `Select ${saved.name}` })).toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: `Select ${second.name}` })).not.toBeInTheDocument();
});

it('creates collections, collapses their decks and moves a selection to another collection', async () => {
  const collection = { id: 'group-a', name: 'Control' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, collection_id: collection.id }], collections: [collection], capabilities });
  vi.mocked(saveDeckCollection).mockResolvedValue({ id: 'group-b', name: 'Brawl' });
  vi.mocked(moveDecksToCollection).mockResolvedValue({ ok: true, count: 1 });
  render(<DeckManagerPage />);
  const group = await screen.findByRole('region', { name: 'Control collection' });
  const toggle = within(group).getByRole('button', { name: 'Control (1)' });
  // Named collections start collapsed; Unsorted starts open.
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByRole('checkbox', { name: `Select ${saved.name}` })).not.toBeInTheDocument();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  fireEvent.click(screen.getByRole('checkbox', { name: `Select ${saved.name}` }));
  fireEvent.click(screen.getByRole('button', { name: 'Move to collection' }));
  const move = screen.getByRole('dialog', { name: 'Move 1 deck to a collection' });
  expect(within(move).getByRole('list', { name: 'Decks to move' })).toHaveTextContent(`${saved.name}Control`);
  fireEvent.click(within(move).getByRole('button', { name: 'Move 1 deck' }));
  await waitFor(() => expect(moveDecksToCollection).toHaveBeenCalledExactlyOnceWith([saved.id], null));
  fireEvent.click(screen.getByRole('button', { name: 'New collection' }));
  fireEvent.change(screen.getByLabelText('Collection name'), { target: { value: 'Brawl' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create collection' }));
  await waitFor(() => expect(saveDeckCollection).toHaveBeenCalledExactlyOnceWith('Brawl', undefined));
});

it('opens Unsorted and expands every collection while searching', async () => {
  const collection = { id: 'group-a', name: 'Control' };
  const second = { ...saved, id: 'second', name: 'Unsorted deck' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, collection_id: collection.id }, second], collections: [collection], capabilities });
  render(<DeckManagerPage />);
  const unsorted = await screen.findByRole('region', { name: 'Unsorted collection' });
  expect(within(unsorted).getByRole('button', { name: 'Unsorted (1)' })).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('checkbox', { name: `Select ${second.name}` })).toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: `Select ${saved.name}` })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved decks' }), { target: { value: saved.name } });
  expect(screen.getByRole('checkbox', { name: `Select ${saved.name}` })).toBeInTheDocument();
});

it('requires confirmation to remove a collection and explains that decks are retained', async () => {
  const collection = { id: 'group-a', name: 'Control' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, collection_id: collection.id }], collections: [collection], capabilities });
  vi.mocked(removeDeckCollection).mockResolvedValue({ ok: true, count: 1 });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Remove Control collection' }));
  const dialog = screen.getByRole('dialog', { name: 'Remove Control collection?' });
  expect(dialog).toHaveTextContent('Unsorted');
  expect(dialog).toHaveTextContent('saved revisions will be retained');
  expect(removeDeckCollection).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Remove collection' }));
  await waitFor(() => expect(removeDeckCollection).toHaveBeenCalledExactlyOnceWith(collection.id));
});

it('shows verified transfer progress and leaves connecting progress indeterminate', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, active_job: 'running-job', busy: true });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'running', detail: 'Verified 1 of 4 transfers…', progress: { completed: 1, total: 4 } });
  render(<DeckManagerPage />);
  const bar = await screen.findByRole('progressbar', { name: 'Deck transfer progress' });
  expect(bar).toHaveAttribute('max', '4');
  expect(bar).toHaveAttribute('value', '1');
  expect(screen.getByText('25%')).toBeInTheDocument();
});

it('adds a text-only saved deck to Arena through Arena’s importer', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(exportManagedDeck).mockResolvedValue({ text: 'About\nName Any format deck\n\nDeck\n4 Forest', name: saved.name, extension: '.txt' } as Awaited<ReturnType<typeof exportManagedDeck>>);
  vi.mocked(addDeckToArena).mockResolvedValue({ job_id: 'add-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'add', count: 1 } });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const add = await screen.findByRole('button', { name: 'Add to Arena' });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  await waitFor(() => expect(addDeckToArena).toHaveBeenCalledExactlyOnceWith('About\nName Any format deck\n\nDeck\n4 Forest', saved.name, 'Standard', 'deck-a'));
  expect(exportManagedDeck).toHaveBeenCalledWith('deck-a', 'new', 'arena');
  expect(await screen.findByText('Deck added directly to Arena.', undefined, { timeout: 3000 })).toBeInTheDocument();
});

it('stops a running backup after confirmation and reports what was saved', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'backup-job' });
  let finished = false;
  vi.mocked(fetchNativeDeckJob).mockImplementation(async () => finished
    ? { state: 'done', detail: 'Completed.', action: 'backup', result: { action: 'backup', count: 12, cancelled: true } }
    : { state: 'running', detail: 'Read 12 of 95 decks…', action: 'backup', progress: { completed: 12, total: 190 } });
  vi.mocked(cancelNativeDeckJob).mockResolvedValue({ state: 'running', cancel: true });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  fireEvent.click(screen.getByRole('button', { name: 'Back up all Arena decks' }));
  // The banner's title says what is running; the bar has no second line repeating it.
  const status = await screen.findByRole('region', { name: 'Arena status' });
  expect(await within(status).findByText('Backing up Arena decks…')).toBeInTheDocument();
  expect(within(status).getByRole('progressbar', { name: 'Deck transfer progress' })).toBeInTheDocument();
  expect(within(status).queryByText('Read 12 of 95 decks…')).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'Stop backup' }));
  const dialog = screen.getByRole('dialog', { name: 'Stop backing up Arena decks?' });
  expect(dialog).toHaveTextContent('Decks already read are verified and saved');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Keep going' }));
  expect(cancelNativeDeckJob).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Stop backup' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stop after this deck' }));
  await waitFor(() => expect(cancelNativeDeckJob).toHaveBeenCalledExactlyOnceWith('backup-job'));
  expect(await screen.findByRole('button', { name: 'Stopping…' })).toBeDisabled();
  finished = true;
  expect(await screen.findByText(/Backup stopped. 12 decks backed up before stopping/, undefined, { timeout: 3000 })).toBeInTheDocument();
});

it('sorts saved decks by name or update time and Arena decks by name or Arena dates', async () => {
  const older = { ...saved, id: 'deck-old', name: 'Zebra deck', updated_at: '2026-01-01T00:00:00Z' };
  const newer = { ...saved, id: 'deck-new', name: 'Alpha deck', updated_at: '2026-09-01T00:00:00Z' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [older, newer], capabilities });
  const [a, b] = connected.decks;
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, decks: [
    { ...a, arena_modified: '2026-10-01T00:00:00+00:00', arena_played: null },
    { ...b, arena_modified: '2026-08-01T00:00:00+00:00', arena_played: '2026-09-01T00:00:00+00:00' },
    { id: 'arena-c', name: 'Arena fixture C', format_name: 'Standard', main_count: 60 },
  ] });
  render(<DeckManagerPage />);
  const names = (pattern: RegExp) => screen.getAllByRole('checkbox', { name: pattern }).map((box) => box.getAttribute('aria-label'));
  await screen.findByRole('checkbox', { name: 'Select Zebra deck' });
  expect(names(/^Select .* deck$/)).toEqual(['Select Alpha deck', 'Select Zebra deck']);
  fireEvent.change(screen.getByRole('combobox', { name: 'Sort decks' }), { target: { value: 'name-desc' } });
  expect(names(/^Select .* deck$/)).toEqual(['Select Zebra deck', 'Select Alpha deck']);
  fireEvent.change(screen.getByRole('combobox', { name: 'Sort decks' }), { target: { value: 'updated-asc' } });
  expect(names(/^Select .* deck$/)).toEqual(['Select Zebra deck', 'Select Alpha deck']);
  fireEvent.change(screen.getByRole('combobox', { name: 'Sort decks' }), { target: { value: 'updated-desc' } });
  expect(names(/^Select .* deck$/)).toEqual(['Select Alpha deck', 'Select Zebra deck']);
  fireEvent.click(screen.getByRole('button', { name: 'Arena (3)' }));
  const sortBox = screen.getByRole('combobox', { name: 'Sort decks' });
  expect(within(sortBox).queryByRole('option', { name: /Updated/ })).not.toBeInTheDocument();
  fireEvent.change(sortBox, { target: { value: 'name-desc' } });
  expect(names(/^Select Arena fixture/)).toEqual(['Select Arena fixture C', 'Select Arena fixture B', 'Select Arena fixture A']);
  // Decks without the date come last in either direction.
  fireEvent.change(sortBox, { target: { value: 'modified-desc' } });
  expect(within(sortBox).getByRole('option', { name: 'Modified: newest first' })).toBeInTheDocument();
  expect(names(/^Select Arena fixture/)).toEqual(['Select Arena fixture A', 'Select Arena fixture B', 'Select Arena fixture C']);
  fireEvent.change(sortBox, { target: { value: 'modified-asc' } });
  expect(names(/^Select Arena fixture/)).toEqual(['Select Arena fixture B', 'Select Arena fixture A', 'Select Arena fixture C']);
  fireEvent.change(sortBox, { target: { value: 'played-desc' } });
  expect(names(/^Select Arena fixture/)).toEqual(['Select Arena fixture B', 'Select Arena fixture A', 'Select Arena fixture C']);
  fireEvent.click(screen.getByRole('button', { name: /^Saved Locally/ }));
  expect(within(screen.getByRole('combobox', { name: 'Sort decks' })).getByRole('option', { name: 'Modified in Arena: newest' })).toBeInTheDocument();
});

it('orders Arena by newest edit and puts Arena favorites in their own gold section', async () => {
  const [a, b] = connected.decks;
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, decks: [
    { ...a, arena_modified: '2026-10-01T00:00:00+00:00' },
    { ...b, arena_modified: '2026-10-05T00:00:00+00:00', is_favorite: true },
    { id: 'arena-c', name: 'Arena fixture C', format_name: 'Standard', main_count: 60, arena_modified: '2026-10-09T00:00:00+00:00' },
    { id: 'arena-d', name: 'Arena fixture D', format_name: 'Standard', main_count: 60, arena_modified: '2026-09-01T00:00:00+00:00', is_favorite: true },
  ] });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (4)' }));
  expect(screen.getByRole('combobox', { name: 'Sort decks' })).toHaveValue('modified-desc');
  const names = (region: string) => within(screen.getByRole('region', { name: region })).getAllByRole('checkbox').map((box) => box.getAttribute('aria-label'));
  expect(names('Favorites')).toEqual(['Select Arena fixture B', 'Select Arena fixture D']);
  expect(names('My Decks')).toEqual(['Select Arena fixture C', 'Select Arena fixture A']);
  expect(screen.getByRole('button', { name: /^Arena fixture B/ })).toHaveClass('deck-manager-tile-favorite');
  expect(screen.getByRole('button', { name: /^Arena fixture C/ })).not.toHaveClass('deck-manager-tile-favorite');
  fireEvent.click(screen.getByRole('button', { name: 'Favorites (2)' }));
  expect(screen.queryByRole('checkbox', { name: 'Select Arena fixture B' })).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Select Arena fixture C' })).toBeInTheDocument();
  // The Saved Locally tab keeps its own order.
  fireEvent.click(screen.getByRole('button', { name: /^Saved Locally/ }));
  expect(screen.getByRole('combobox', { name: 'Sort decks' })).toHaveValue('name-asc');
});

it('stars and unstars Arena decks from their tiles and dialog', async () => {
  const [a, b] = connected.decks;
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, decks: [a, { ...b, is_favorite: true }] });
  vi.mocked(fetchArenaDeck).mockReturnValue(new Promise(() => {}));
  vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'favorite-job' });
  vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'favorite', count: 1, favorite: true } });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  expect(screen.getByRole('button', { name: 'Remove Arena fixture B from Arena favorites' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Add Arena fixture A to Arena favorites' }));
  await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('favorite', [{ id: 'arena-a', favorite: true }]));
  expect(await screen.findByText('Added to your Arena favorites.')).toBeInTheDocument();
  // The dialog stays open after a star from inside it.
  fireEvent.click(screen.getByRole('button', { name: /^Arena fixture B/ }));
  const dialog = screen.getByRole('dialog', { name: 'Arena fixture B' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Favorite' }));
  await waitFor(() => expect(startNativeDeckJob).toHaveBeenLastCalledWith('favorite', [{ id: 'arena-b', favorite: false }]));
  expect(await screen.findByRole('dialog', { name: 'Arena fixture B' })).toBeInTheDocument();
});

it('keeps the star off while Arena is not on its Decks screen', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, deck_screen_open: false });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
  const star = screen.getByRole('button', { name: 'Add Arena fixture A to Arena favorites' });
  expect(star).toBeDisabled();
  expect(star).toHaveAttribute('title', expect.stringContaining('Decks screen'));
});

it('shows one message when filters hide every deck, with a way to clear them', async () => {
  render(<DeckManagerPage />);
  await screen.findByRole('checkbox', { name: `Select ${saved.name}` });
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved decks' }), { target: { value: 'no such deck' } });
  expect(screen.getByText(/No saved decks match your search or status filter/)).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Unsorted collection' })).not.toBeInTheDocument();
  expect(screen.queryByText(/Add your first deck/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(await screen.findByRole('checkbox', { name: `Select ${saved.name}` })).toBeInTheDocument();
});

it('hides Restore to Arena for a deck Arena already has, but still copies its list', async () => {
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  const inArena = { ...saved, native_restorable: true, native_arena_ids: ['arena-a'] };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [inArena], capabilities });
  vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, ...inArena });
  vi.mocked(exportManagedDeck).mockResolvedValue({ text: 'Deck\n4 Forest (DMU) 281', name: saved.name, extension: '.txt', note: '' } as Awaited<ReturnType<typeof exportManagedDeck>>);
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  await within(dialog).findByText('In Arena');
  expect(within(dialog).queryByRole('button', { name: 'Restore to Arena' })).not.toBeInTheDocument();
  expect(within(dialog).queryByRole('button', { name: 'Add to Arena' })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Copy deck list' }));
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Deck\n4 Forest (DMU) 281'));
});

it('keeps notes and tags tucked away and saves only after a change', async () => {
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  expect(within(dialog).getByRole('region', { name: 'Deck (4)' })).toHaveTextContent('Forest');
  expect(within(dialog).getByText('Deck Info')).toBeInTheDocument();
  const save = within(dialog).getByRole('button', { name: 'Save notes & tags' });
  expect(save).toBeDisabled();
  const tags = within(dialog).getByLabelText('Tags');
  // A comma finishes a tag; the text after it stays in the box.
  fireEvent.change(tags, { target: { value: 'ramp, green' } });
  expect(within(dialog).getByRole('button', { name: 'Remove tag ramp' })).toBeInTheDocument();
  expect(tags).toHaveValue('green');
  expect(save).toBeEnabled();
  // Unfinished text is saved too.
  fireEvent.click(save);
  await waitFor(() => expect(updateManagedDeck).toHaveBeenCalledWith('deck-a', { notes: '', tags: ['ramp', 'green'] }));
});

it('edits tags as chips: Enter adds, duplicates are ignored, Backspace and the x remove', async () => {
  vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, tags: ['aggro'] });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  const tags = within(dialog).getByLabelText('Tags');
  const chips = () => within(dialog).queryAllByRole('button', { name: /^Remove tag/ }).map((b) => b.getAttribute('aria-label'));
  expect(chips()).toEqual(['Remove tag aggro']);
  fireEvent.change(tags, { target: { value: 'Bo3' } });
  fireEvent.keyDown(tags, { key: 'Enter' });
  fireEvent.change(tags, { target: { value: 'AGGRO,' } });
  expect(chips()).toEqual(['Remove tag aggro', 'Remove tag Bo3']);
  fireEvent.keyDown(tags, { key: 'Backspace' });
  expect(chips()).toEqual(['Remove tag aggro']);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Remove tag aggro' }));
  expect(chips()).toEqual([]);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Discard' }));
  expect(chips()).toEqual(['Remove tag aggro']);
});

it('groups the main deck by type with mana costs, cheapest first and lands last', async () => {
  const card = (quantity: number, name: string, section = 'Deck') => ({ section, quantity, name, arena_id: null, set_code: null, collector_number: null });
  vi.mocked(fetchManagedDeck).mockResolvedValue({ ...detail, deck: { ...detail.deck, cards: [
    card(21, 'Swamp'), card(2, 'The End'), card(4, 'Deep-Cavern Bat'), card(3, 'Bitter Triumph'), card(1, 'Mystery Card'), card(2, 'Duress', 'Sideboard'),
  ] }, card_info: {
    Swamp: { type: 'Land' }, 'The End': { type: 'Instant', mana_cost: '{2}{B}', mana_value: 3 },
    'Deep-Cavern Bat': { type: 'Creature', mana_cost: '{1}{B}', mana_value: 2 }, 'Bitter Triumph': { type: 'Instant', mana_cost: '{1}{B}', mana_value: 2 },
    Duress: { type: 'Sorcery', mana_cost: '{B}', mana_value: 1 },
  } });
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  const main = within(dialog).getByRole('region', { name: 'Deck (31)' });
  const groups = within(main).getAllByRole('list').map((list) => list.getAttribute('aria-label'));
  expect(groups).toEqual(['Creatures (4)', 'Instants (5)', 'Other (1)', 'Lands (21)']);
  const instants = within(main).getByRole('list', { name: 'Instants (5)' });
  expect(within(instants).getAllByRole('listitem').map((row) => row.querySelector('.deck-card-name')?.textContent)).toEqual(['Bitter Triumph', 'The End']);
  // Drawn like the in-game overlay: color vectors and grey generic badges.
  const cost = within(instants).getByLabelText('Mana cost {2}{B}');
  expect(within(cost).getByRole('img', { name: 'B' })).toHaveAttribute('src', '/icons/B.svg');
  expect(cost.querySelector('.gen')).toHaveTextContent('2');
  // Side piles keep one list, with costs.
  expect(within(within(dialog).getByRole('region', { name: 'Sideboard (2)' })).getByLabelText('Mana cost {B}')).toBeInTheDocument();
});

describe('Arena status', () => {
  const banner = () => screen.findByRole('region', { name: 'Arena status' });

  it('shows only a green Load button before the first read, without a chip or banner', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, connected: false, decks: [], refreshed_at: undefined });
    render(<DeckManagerPage />);
    const load = await screen.findByRole('button', { name: 'Load Arena decks' });
    expect(load).toBeEnabled();
    expect(load).toHaveClass('deck-manager-load-arena');
    expect(load).toHaveAttribute('title', expect.stringContaining('Decks screen'));
    expect(screen.queryByText('Arena not loaded')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Arena status' })).not.toBeInTheDocument();
  });

  it('confirms a load in the green banner alone, without a second box repeating it', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'connect-job' });
    vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', action: 'connect', result: { action: 'connect', count: 0 } });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Rescan Arena' }));
    const status = await banner();
    expect(await within(status).findByText(/^Arena decks loaded/)).toBeInTheDocument();
    expect(within(status).queryByText('Arena decks refreshed.')).not.toBeInTheDocument();
    fireEvent.click(within(status).getByRole('button', { name: 'Dismiss message' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Arena status' })).not.toBeInTheDocument());
  });

  it('puts a job result in the banner headline, not in a box under it', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'backup-job' });
    vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', action: 'backup', result: { action: 'backup', count: 2 } });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Back up all Arena decks' }));
    const status = await banner();
    const headline = await within(status).findByText('Backed up 2 decks to your collection.');
    expect(headline.tagName).toBe('STRONG');
    expect(within(status).getByText(/2 decks in Arena · limit 100/)).toBeInTheDocument();
    expect(within(status).queryByText(/^Arena decks loaded/)).not.toBeInTheDocument();
    expect(status.querySelector('.deck-manager-status-message')).toBeNull();
    fireEvent.click(within(status).getByRole('button', { name: 'Dismiss message' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Arena status' })).not.toBeInTheDocument());
  });

  it('shows when Arena was last read and keeps that list during a game', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, in_game: true });
    render(<DeckManagerPage />);
    const status = await banner();
    expect(within(status).getByText('You’re in a game')).toBeInTheDocument();
    expect(within(status).getByText(/won’t touch Arena until the game ends\. The Arena list below is from/)).toBeInTheDocument();
    expect(screen.getByText('In a game')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rescan Arena' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Arena (2)' })).toBeInTheDocument();
  });

  it('summarizes a fresh read in the chip with the deck count and slot limit', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    render(<DeckManagerPage />);
    const chip = await screen.findByText(/^Arena 2\/100/);
    expect(chip).toHaveAttribute('title', expect.stringMatching(/^Arena decks loaded .*2 decks in Arena · limit 100\. Changed something in Arena\? Click Rescan Arena\./));
    expect(screen.queryByRole('region', { name: 'Arena status' })).not.toBeInTheDocument();
  });

  it('asks for the interrupted transfer to be checked first, from the banner', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, pending_transfers: [{ id: 't', action: 'restore', phase: 'uncertain', deck_id: 'deck-a' }] });
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'job-r' });
    vi.mocked(fetchNativeDeckJob).mockReturnValue(new Promise(() => {}));
    render(<DeckManagerPage />);
    const status = await banner();
    expect(within(status).getByText('A transfer was interrupted')).toBeInTheDocument();
    fireEvent.click(within(status).getByRole('button', { name: 'Reconcile transfers' }));
    await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledWith('reconcile', []));
    expect(await within(await banner()).findByText('Checking the interrupted transfer…')).toBeInTheDocument();
  });

  it('shows results in the banner and lets them be dismissed', async () => {
    vi.mocked(moveDecksToCollection).mockResolvedValue({ ok: true, count: 1 });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
    fireEvent.click(screen.getByRole('button', { name: 'Move to collection' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Move 1 deck' }));
    const status = await banner();
    expect(await within(status).findByText('Moved 1 deck to Unsorted.')).toBeInTheDocument();
    fireEvent.click(within(status).getByRole('button', { name: 'Dismiss message' }));
    expect(screen.queryByText('Moved 1 deck to Unsorted.')).not.toBeInTheDocument();
  });

  it('keeps Back up all beside Rescan Arena and the help behind the ? button, with no ⋯ menu', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'backup-job' });
    vi.mocked(fetchNativeDeckJob).mockReturnValue(new Promise(() => {}));
    render(<DeckManagerPage />);
    await screen.findByText(/^Arena 2\/100/);
    expect(screen.queryByRole('button', { name: 'More Deck Manager actions' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'How Deck Manager works' }));
    expect(screen.getByRole('dialog', { name: 'How Deck Manager works' })).toHaveTextContent('Back up all Arena decks first.');
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    // On the Saved tab too, not only Arena.
    fireEvent.click(screen.getByRole('button', { name: 'Back up all Arena decks' }));
    await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('backup', []));
  });
});

describe('selection, Compare and Arena deck actions', () => {
  const other: ManagedDeck = { ...saved, id: 'deck-b', name: 'Second saved deck', current_revision_id: 'b1' };
  const cards = (list: [number, string][]) => list.map(([quantity, name]) =>
    ({ section: 'Deck', quantity, name, arena_id: null, set_code: null, collector_number: null }));

  it('clears the selection with Select none and enables Compare only for two decks', async () => {
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved, other, { ...saved, id: 'deck-c', name: 'Third deck' }], capabilities });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
    const compare = screen.getByRole('button', { name: 'Compare' });
    expect(compare).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: `Select ${other.name}` }));
    expect(compare).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
    expect(screen.getByText('3 selected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Select all' })).not.toBeInTheDocument();
    expect(compare).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Select none' }));
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Compare' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: `Select ${saved.name}` })).not.toBeChecked();
  });

  it('compares two saved decks card by card', async () => {
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [saved, other], capabilities });
    vi.mocked(fetchManagedDeck).mockImplementation(async (id) => id === saved.id
      ? { ...detail, deck: { ...detail.deck, cards: cards([[4, 'Lightning Bolt'], [20, 'Mountain']]) } }
      : { ...detail, ...other, revision_id: 'b1', deck: { ...detail.deck, cards: cards([[2, 'Lightning Bolt'], [20, 'Mountain'], [2, 'Shock']]) } });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
    fireEvent.click(screen.getByRole('checkbox', { name: `Select ${other.name}` }));
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    const dialog = await screen.findByRole('dialog', { name: 'Compare decks' });
    const onlyA = await within(dialog).findByRole('list', { name: `Only in ${saved.name}` });
    expect(onlyA).toHaveTextContent('+2Lightning Bolt4 vs 2');
    expect(within(dialog).getByRole('list', { name: `Only in ${other.name}` })).toHaveTextContent('+2Shock');
    expect(dialog).toHaveTextContent('92%');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Swap sides' }));
    expect(within(dialog).getByRole('list', { name: `Only in ${other.name}` })).toBeInTheDocument();
    expect(startNativeDeckJob).not.toHaveBeenCalled();
  });

  const arenaCards = (id: string, list: [number, string][]) => ({ id, name: id, format_name: 'Standard', refreshed_at: '2026-10-07T12:00:00Z',
    cards: cards(list), card_info: {} });

  it('opens an Arena deck with the cards from the last Arena read, without a backup', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, decks: [
      { ...connected.decks[0], arena_modified: '2026-10-12T06:12:37+00:00', arena_played: null }, connected.decks[1]] });
    vi.mocked(fetchArenaDeck).mockResolvedValue(arenaCards('arena-a', [[20, 'Island'], [4, 'Opt']]));
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'backup-job' });
    vi.mocked(fetchNativeDeckJob).mockReturnValue(new Promise(() => {}));
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
    fireEvent.click(screen.getByRole('button', { name: /^Arena fixture A/ }));
    const dialog = screen.getByRole('dialog', { name: 'Arena fixture A' });
    expect(await within(dialog).findByText('Opt')).toBeInTheDocument();
    expect(fetchArenaDeck).toHaveBeenCalledWith('arena-a', expect.anything());
    expect(within(dialog).getByText('Not saved locally yet')).toBeInTheDocument();
    expect(within(dialog).getByText(/Modified in Arena/)).toBeInTheDocument();
    expect(within(dialog).getByText('Never played')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Select Arena fixture A' })).not.toBeChecked();
    expect(startNativeDeckJob).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: /Copy deck list/ }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('Deck\n20 Island\n4 Opt'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Back up' }));
    await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('backup', [{ id: 'arena-a' }]));
  });

  it('offers Arena actions for a deck that is already saved', async () => {
    const copy = { ...saved, native_restorable: true, native_arena_ids: ['arena-a'] };
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [copy], capabilities });
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(fetchArenaDeck).mockResolvedValue(arenaCards('arena-a', [[60, 'Forest']]));
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
    fireEvent.click(screen.getByRole('button', { name: /^Arena fixture A/ }));
    const dialog = screen.getByRole('dialog', { name: 'Arena fixture A' });
    expect(await within(dialog).findByText('Forest')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Back up again' })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move to trash' }));
    expect(screen.getByRole('dialog', { name: 'Move 1 deck to Trash?' })).toHaveTextContent('Arena fixture A');
  });

  it('moves selected Arena decks to Trash through the verified move', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'trash-job' });
    vi.mocked(fetchNativeDeckJob).mockResolvedValue({ state: 'done', detail: 'Completed.', result: { action: 'store', count: 1 } });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Arena fixture B' }));
    fireEvent.click(screen.getByRole('button', { name: 'Move selected to trash' }));
    const dialog = screen.getByRole('dialog', { name: 'Move 1 deck to Trash?' });
    expect(dialog).toHaveTextContent('deleted from Arena');
    expect(startNativeDeckJob).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move to trash' }));
    await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledExactlyOnceWith('store', [{ id: 'arena-b' }], undefined, { trash: true }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Moved 1 deck to Trash and removed it from Arena.'));
  });

  it('compares two Arena decks from the last Arena read, without a backup', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(fetchArenaDeck).mockImplementation(async (id) => id === 'arena-a'
      ? arenaCards(id, [[4, 'Shock'], [20, 'Mountain']]) : arenaCards(id, [[20, 'Mountain'], [4, 'Opt']]));
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Arena fixture A' }));
    fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    const dialog = screen.getByRole('dialog', { name: 'Compare decks' });
    expect(await within(dialog).findByRole('list', { name: 'Only in Arena fixture A' })).toHaveTextContent('+4Shock');
    expect(within(dialog).getByRole('list', { name: 'Only in Arena fixture B' })).toHaveTextContent('+4Opt');
    expect(startNativeDeckJob).not.toHaveBeenCalled();
  });

  it('filters saved decks by collection and finds them by collection name', async () => {
    const control = { id: 'group-a', name: 'Control' };
    vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, collection_id: control.id }, other], collections: [control], capabilities });
    render(<DeckManagerPage />);
    const picker = await screen.findByRole('combobox', { name: 'Show collection' });
    fireEvent.change(picker, { target: { value: control.id } });
    expect(screen.getByRole('checkbox', { name: `Select ${saved.name}` })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: `Select ${other.name}` })).not.toBeInTheDocument();
    fireEvent.change(picker, { target: { value: '' } });
    expect(screen.getByRole('checkbox', { name: `Select ${other.name}` })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: `Select ${saved.name}` })).not.toBeInTheDocument();
    fireEvent.change(picker, { target: { value: 'all' } });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved decks' }), { target: { value: 'contr' } });
    expect(screen.getByRole('checkbox', { name: `Select ${saved.name}` })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: `Select ${other.name}` })).not.toBeInTheDocument();
    expect(screen.getByRole('searchbox')).toHaveAttribute('placeholder', 'Search deck names, tags, collections…');
  });

  it('adds a pasted list straight to Arena from the Arena tab', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(addDeckToArena).mockResolvedValue({ job_id: 'add-job' });
    vi.mocked(fetchNativeDeckJob).mockReturnValue(new Promise(() => {}));
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
    fireEvent.click(screen.getByRole('button', { name: /Add deck/ }));
    const dialog = screen.getByRole('dialog', { name: 'Add a deck to Arena' });
    const add = within(dialog).getByRole('button', { name: 'Add to Arena' });
    expect(add).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('Decklist or backup'), { target: { value: 'Deck\n60 Forest' } });
    fireEvent.change(within(dialog).getByLabelText('Deck name'), { target: { value: 'Forests' } });
    fireEvent.click(add);
    await waitFor(() => expect(addDeckToArena).toHaveBeenCalledExactlyOnceWith('Deck\n60 Forest', 'Forests', '', undefined, undefined, { renameIfTaken: false }));
    expect(importManagedDeck).not.toHaveBeenCalled();
  });

  it.each([
    ['Deck\n60 Forest', 'DeckManager Import Deck'],
    ['About\nName Mono Green\n\nDeck\n60 Forest', 'Mono Green'],
  ])('names a blank Arena import from its list or the default', async (list, expected) => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    vi.mocked(addDeckToArena).mockResolvedValue({ job_id: 'add-job' });
    vi.mocked(fetchNativeDeckJob).mockReturnValue(new Promise(() => {}));
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Arena (2)' }));
    fireEvent.click(screen.getByRole('button', { name: /Add deck/ }));
    const dialog = screen.getByRole('dialog', { name: 'Add a deck to Arena' });
    fireEvent.change(within(dialog).getByLabelText('Decklist or backup'), { target: { value: list } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add to Arena' }));
    await waitFor(() => expect(addDeckToArena).toHaveBeenCalledExactlyOnceWith(list, expected, '', undefined, undefined, { renameIfTaken: true }));
  });
});
