import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchDeckLibrary, fetchManagedDeck, importManagedDeck, updateManagedDeck, exportManagedDeck, deleteManagedDeck, removeManagedDecks,
  saveDeckCollection, removeDeckCollection, moveDecksToCollection, fetchNativeDeckStatus, startNativeDeckJob, fetchNativeDeckJob, cancelNativeDeckJob, addDeckToArena,
  type ManagedDeck, type ManagedDeckDetail,
} from '../deckManagerApi';
import { DeckManagerPage } from './DeckManagerPage';

vi.mock('../deckManagerApi', () => ({
  saveDeckCollection: vi.fn(), removeDeckCollection: vi.fn(), moveDecksToCollection: vi.fn(), fetchDeckLibrary: vi.fn(), fetchManagedDeck: vi.fn(), importManagedDeck: vi.fn(),
  updateManagedDeck: vi.fn(), exportManagedDeck: vi.fn(), captureArenaDecks: vi.fn(), deleteManagedDeck: vi.fn(), removeManagedDecks: vi.fn(),
  fetchNativeDeckStatus: vi.fn(), startNativeDeckJob: vi.fn(), fetchNativeDeckJob: vi.fn(), cancelNativeDeckJob: vi.fn(), addDeckToArena: vi.fn(),
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
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select all visible saved decks' }));
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
  expect(await screen.findByRole('button', { name: 'Saved (104)' })).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /Saved list/ })).toHaveLength(104);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(fetchManagedDeck).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved decks' }), { target: { value: 'Saved list 103' } });
  expect(screen.getAllByRole('button', { name: /Saved list/ })).toHaveLength(1);
});

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

it('closes deck details from the backdrop, but not after a drag that ends there', async () => {
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(saved.name) }));
  const dialog = await screen.findByRole('dialog', { name: saved.name });
  // jsdom gives the dialog an empty rect, so any positive point is outside it.
  fireEvent.mouseDown(within(dialog).getByRole('heading', { name: saved.name }), { clientX: 5, clientY: 5 });
  fireEvent.click(dialog, { clientX: 50, clientY: 50 });
  expect(screen.getByRole('dialog', { name: saved.name })).toBeInTheDocument();
  fireEvent.mouseDown(dialog, { clientX: 50, clientY: 50 });
  fireEvent.click(dialog, { clientX: 50, clientY: 50 });
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
  const arenaTile = await screen.findByRole('button', { name: 'Toggle selection of Arena fixture A' });
  expect(within(arenaTile).getByRole('img', { name: 'Colors: U, B' })).toBeInTheDocument();
  expect(within(screen.getByRole('button', { name: 'Toggle selection of Arena fixture B' })).queryByRole('img', { name: /Colors/ })).not.toBeInTheDocument();
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
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select all visible Arena decks' }));
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

it('filters saved presence and backup type through pills and clears hidden selection', async () => {
  const second = { ...saved, id: 'second', name: 'Collection deck', native_restorable: true };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [{ ...saved, native_arena_ids: ['arena-a'] }, second], capabilities });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
  render(<DeckManagerPage />);
  fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
  fireEvent.click(await screen.findByRole('button', { name: 'Filter by Not in Arena' }));
  expect(screen.queryByRole('checkbox', { name: `Select ${saved.name}` })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Move selected to trash' })).toBeDisabled();
  expect(fetchManagedDeck).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter decks by status' }), { target: { value: 'text' } });
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
  fireEvent.click(screen.getByRole('button', { name: 'Move decks' }));
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

it('sorts saved decks by name or update time and Arena decks by name only', async () => {
  const older = { ...saved, id: 'deck-old', name: 'Zebra deck', updated_at: '2026-01-01T00:00:00Z' };
  const newer = { ...saved, id: 'deck-new', name: 'Alpha deck', updated_at: '2026-09-01T00:00:00Z' };
  vi.mocked(fetchDeckLibrary).mockResolvedValue({ decks: [older, newer], capabilities });
  vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
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
  fireEvent.click(screen.getByRole('button', { name: 'Arena (2)' }));
  const sortBox = screen.getByRole('combobox', { name: 'Sort decks' });
  expect(within(sortBox).queryByRole('option', { name: /Updated/ })).not.toBeInTheDocument();
  fireEvent.change(sortBox, { target: { value: 'name-desc' } });
  expect(names(/^Select Arena fixture/)).toEqual(['Select Arena fixture B', 'Select Arena fixture A']);
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
  const save = within(dialog).getByRole('button', { name: 'Save notes & tags' });
  expect(save).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText('Tags'), { target: { value: 'ramp, green' } });
  expect(save).toBeEnabled();
  fireEvent.click(save);
  await waitFor(() => expect(updateManagedDeck).toHaveBeenCalledWith('deck-a', { notes: '', tags: ['ramp', ' green'] }));
});

describe('Arena status panel', () => {
  const status = () => screen.getByRole('region', { name: 'Arena status' });

  it('explains how to load Arena decks before the first read, above the search', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, connected: false, decks: [], refreshed_at: undefined });
    render(<DeckManagerPage />);
    expect(await within(status()).findByText('Arena decks not loaded yet')).toBeInTheDocument();
    expect(within(status()).getByText(/then click Load Arena decks/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load Arena decks' })).toBeEnabled();
    // The panel comes before the search box in reading order.
    expect(status().compareDocumentPosition(screen.getByRole('searchbox')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows when Arena was last read and keeps that list during a game', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, in_game: true });
    render(<DeckManagerPage />);
    expect(await within(status()).findByText('You’re in a game')).toBeInTheDocument();
    expect(within(status()).getByText(/won’t touch Arena until the game ends\. The Arena list below is from/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh Arena decks' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Arena (2)' })).toBeInTheDocument();
  });

  it('summarizes a fresh read with the deck count and slot limit', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue(connected);
    render(<DeckManagerPage />);
    expect(await within(status()).findByText(/^Arena decks loaded/)).toBeInTheDocument();
    expect(within(status()).getByText(/2 decks in Arena · limit 100\. Changed something in Arena\? Click Refresh Arena decks\./)).toBeInTheDocument();
  });

  it('asks for the interrupted transfer to be checked first, from the panel', async () => {
    vi.mocked(fetchNativeDeckStatus).mockResolvedValue({ ...connected, pending_transfers: [{ id: 't', action: 'restore', phase: 'uncertain', deck_id: 'deck-a' }] });
    vi.mocked(startNativeDeckJob).mockResolvedValue({ job_id: 'job-r' });
    vi.mocked(fetchNativeDeckJob).mockReturnValue(new Promise(() => {}));
    render(<DeckManagerPage />);
    expect(await within(status()).findByText('A transfer was interrupted')).toBeInTheDocument();
    fireEvent.click(within(status()).getByRole('button', { name: 'Reconcile transfers' }));
    await waitFor(() => expect(startNativeDeckJob).toHaveBeenCalledWith('reconcile', []));
    expect(await within(status()).findByText('Checking the interrupted transfer…')).toBeInTheDocument();
  });

  it('shows results inside the panel and lets them be dismissed', async () => {
    vi.mocked(moveDecksToCollection).mockResolvedValue({ ok: true, count: 1 });
    render(<DeckManagerPage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: `Select ${saved.name}` }));
    fireEvent.click(screen.getByRole('button', { name: 'Move decks' }));
    expect(await within(status()).findByText('Moved 1 deck to Unsorted.')).toBeInTheDocument();
    fireEvent.click(within(status()).getByRole('button', { name: 'Dismiss message' }));
    expect(within(status()).queryByText('Moved 1 deck to Unsorted.')).not.toBeInTheDocument();
  });
});
