import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Pencil, Archive, ArrowDownToLine, ArrowUpFromLine, Copy, FolderOpen, Plus, RefreshCw, Square, Trash2 } from 'lucide-react';
import {
  saveDeckCollection, removeDeckCollection, moveDecksToCollection, type DeckCollection, type NativeDeckJob,
  captureArenaDecks, exportManagedDeck, fetchDeckLibrary, fetchManagedDeck,
  importManagedDeck, updateManagedDeck, deleteManagedDeck, removeManagedDecks, type DeckLibrary, type ManagedDeckDetail,
  fetchNativeDeckStatus, startNativeDeckJob, fetchNativeDeckJob, cancelNativeDeckJob, addDeckToArena, type NativeDeckStatus, type NativeDeckAction, type ManagedDeck,
} from '../deckManagerApi';
import { usePageVisible } from '../usePageVisible';
import { formatDateTime } from '../format';
import { DeckVisual } from './DeckVisual';
import { DeckTransferProgress } from './DeckTransferProgress';
import { DeckModal } from './DeckModal';
import { DeckDetail } from './DeckDetail';
import { ColorPips } from './ColorPips';
import { DeckManagerStatus } from './DeckManagerStatus';
import { BuyPaperButton, BuyPaperDialog } from './BuyPaperDialog';
import { managedDeckSections } from '../paperDeck';
import { loadLabel } from '../deckManagerLabels';
import { DECK_FORMATS, deckFormatLabel } from '../deckFormatLabel';

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Deck Manager could not complete this action.';
}

type ModalView = 'deck' | 'import' | 'revision' | 'delete' | 'trash' | 'store' | 'bulk-trash' | 'bulk-delete' | 'collection' | 'remove-collection' | 'stop-job';

const STOPPABLE: NativeDeckAction[] = ['backup', 'store', 'restore'];
const NEW_COLLECTION = '__new__';

type SortKey = 'name-asc' | 'name-desc' | 'updated-desc' | 'updated-asc';
const SORT_KEY = 'tapps.deckManager.sort';
const sortLabels: Record<SortKey, string> = {
  'name-asc': 'Name A–Z', 'name-desc': 'Name Z–A', 'updated-desc': 'Updated: newest first', 'updated-asc': 'Updated: oldest first',
};
const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true });

function sortDecks<T extends { name: string; updated_at?: string }>(decks: T[], sort: SortKey): T[] {
  return [...decks].sort((a, b) => {
    if (sort === 'name-desc') return byName(b, a);
    if (sort === 'updated-desc' || sort === 'updated-asc') {
      const order = (a.updated_at ?? '').localeCompare(b.updated_at ?? '');
      return (sort === 'updated-desc' ? -order : order) || byName(a, b);
    }
    return byName(a, b);
  });
}

const statusLabels = {
  arena: 'In Arena', collection: 'Not in Arena', unknown: 'Arena not checked', trash: 'In Trash',
  native: 'Full backup', text: 'Text backup', partial: 'Captured list',
  backed: 'Backed up', unbacked: 'Not backed up',
};
type DeckStatus = keyof typeof statusLabels;

function deckArt(cardName?: string | null, cardId?: number | null) {
  const name = cardName && !cardName.startsWith('Card #') ? cardName : null;
  const nameUrl = name ? `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}&format=image&version=art_crop` : null;
  return { card_name: name, card_id: cardId ?? null, type_category: 'Other', source: 'local_metadata' as const,
    image_url: cardId ? `https://api.scryfall.com/cards/arena/${cardId}?format=image&version=art_crop` : nameUrl,
    image_fallback_url: cardId ? nameUrl : null };
}

const HELP_KEY = 'tapps.deckManager.helpOpen';

function DeckManagerHelp() {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(HELP_KEY) === '1'; } catch { return false; } });
  return (
    <details className="deck-manager-help" open={open} onToggle={(event) => {
      const next = event.currentTarget.open; setOpen(next);
      try { localStorage.setItem(HELP_KEY, next ? '1' : '0'); } catch { /* Preference only. */ }
    }}>
      <summary>How Deck Manager works</summary>
      <ul>
        <li><strong>Deck Manager doesn’t stay connected to Arena.</strong> It reads Arena only when you click Load or Refresh Arena decks, or start a backup or transfer, and then lets go. The status panel shows when it last read Arena.</li>
        <li><strong>Keep Arena open on the Decks screen, outside a match,</strong> whenever you load, back up or transfer decks. During a game Deck Manager leaves Arena alone.</li>
        <li><strong>Click Refresh Arena decks after any change made in Arena</strong> (adding, editing or deleting a deck). The Arena list is what Arena reported at the last refresh.</li>
        <li><strong>Back up all Arena decks first.</strong> Full backups keep cards, card styles, art and format, so a deck can be restored exactly.</li>
        <li>Moving a deck to your collection frees an Arena slot. Restoring or adding a deck uses one.</li>
        <li>Do one thing at a time, and don’t edit decks in Arena while a backup or transfer runs.</li>
        <li>If a transfer is interrupted, click <strong>Reconcile transfers</strong> before anything else. It only reads Arena and never repeats a change.</li>
      </ul>
    </details>
  );
}

export function DeckManagerPage() {
  const [library, setLibrary] = useState<DeckLibrary | null>(null);
  const [detail, setDetail] = useState<ManagedDeckDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [revision, setRevision] = useState<string | undefined>();
  const [modal, setModal] = useState<ModalView | null>(null);
  const [buyingOpener, setBuyingOpener] = useState<HTMLElement | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<'saved' | 'trash' | 'arena'>('saved');
  const [statusFilter, setStatusFilter] = useState<DeckStatus | 'all'>('all');
  const [sort, setSort] = useState<SortKey>(() => {
    try { const stored = localStorage.getItem(SORT_KEY); return stored && stored in sortLabels ? stored as SortKey : 'name-asc'; } catch { return 'name-asc'; }
  });
  const [localBusy, setBusy] = useState(false);
  const [native, setNative] = useState<NativeDeckStatus | null>(null);
  const [nativeJob, setNativeJob] = useState<string | null>(null);
  const [nativeJobAction, setNativeJobAction] = useState<NativeDeckAction | null>(null);
  const [stopRequested, setStopRequested] = useState(false);
  const [nativeProgress, setNativeProgress] = useState('');
  const [transferProgress, setTransferProgress] = useState<NativeDeckJob['progress']>();
  // Open collections ('' = Unsorted). Named collections start collapsed.
  const [expanded, setExpanded] = useState<string[]>(['']);
  const [destination, setDestination] = useState('');
  // Move out of Arena: chosen collection ('' = Unsorted, NEW_COLLECTION = create one).
  const [storeTarget, setStoreTarget] = useState('');
  const [storeNewName, setStoreNewName] = useState('');
  const storedTo = useRef('your collection');
  const [importCollection, setImportCollection] = useState('');
  const [collectionName, setCollectionName] = useState('');
  const [editingCollection, setEditingCollection] = useState<DeckCollection | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const busy = localBusy || Boolean(nativeJob) || Boolean(native?.busy);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const [name, setName] = useState('');
  const [format, setFormat] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const [modalOpener, setModalOpener] = useState<HTMLElement | null>(null);

  const arenaIds = new Set(native?.decks.map((deck) => deck.id) ?? []);
  const inArena = (deck: { native_arena_ids?: string[] }) => (deck.native_arena_ids ?? []).some((id) => arenaIds.has(id));
  const savedStatuses = (deck: ManagedDeck): DeckStatus[] => [
    deck.trashed_at ? 'trash' : native?.connected ? inArena(deck) ? 'arena' : 'collection' : 'unknown',
    deck.native_restorable ? 'native' : deck.completeness === 'text' ? 'text' : 'partial',
  ];
  const arenaBackups = new Map<string, ManagedDeck>();
  const arenaArtwork = new Map<string, ManagedDeck>();
  for (const deck of library?.decks ?? []) {
    for (const id of deck.native_arena_ids ?? []) {
      arenaArtwork.set(id, deck);
      if (!deck.trashed_at && deck.native_restorable) arenaBackups.set(id, deck);
    }
  }
  const arenaBackup = (id: string) => arenaBackups.get(id);
  const arenaStatuses = (id: string): DeckStatus[] => ['arena', arenaBackup(id) ? 'backed' : 'unbacked'];
  const filterStatuses: DeckStatus[] = view === 'arena' ? ['arena', 'backed', 'unbacked'] : view === 'trash' ? ['trash', 'native', 'text', 'partial'] : ['arena', 'collection', 'unknown', 'native', 'text', 'partial'];
  // Arena reports no edit times, so its tab sorts by name only.
  const sortOptions: SortKey[] = view === 'arena' ? ['name-asc', 'name-desc'] : ['name-asc', 'name-desc', 'updated-desc', 'updated-asc'];
  const activeSort = sortOptions.includes(sort) ? sort : 'name-asc';
  const filtering = Boolean(query.trim()) || statusFilter !== 'all';
  const visible = sortDecks((library?.decks ?? []).filter((deck) =>
    Boolean(deck.trashed_at) === (view === 'trash')
    && (statusFilter === 'all' || savedStatuses(deck).includes(statusFilter))
    && `${deck.name} ${deck.format_name} ${deckFormatLabel(deck.format_name)} ${deck.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase())), activeSort);
  const selectedDeck = library?.decks.find((deck) => deck.id === selected);
  const activeDetail = detail?.id === selected && (!revision || detail.revision_id === revision) ? detail : null;
  const editingRevision = modal === 'revision';
  const pageVisible = usePageVisible();
  const arenaDecks = sortDecks((native?.decks ?? []).filter((deck) => `${deck.name} ${deck.format_name} ${deckFormatLabel(deck.format_name)}`.toLowerCase().includes(query.toLowerCase())
    && (statusFilter === 'all' || arenaStatuses(deck.id).includes(statusFilter))), activeSort);
  const checkedDecks = (library?.decks ?? []).filter((deck) => checked.includes(deck.id));
  const canRestoreSelection = checkedDecks.length > 0 && checkedDecks.length === checked.length
    && checkedDecks.every((deck) => deck.native_restorable && !deck.trashed_at && !inArena(deck));

  useEffect(() => {
    const controller = new AbortController();
    fetchDeckLibrary(controller.signal).then((loaded) => {
      if (!controller.signal.aborted) setLibrary(loaded);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(err));
    });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!pageVisible) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function readStatus() {
      try {
        const loaded = await fetchNativeDeckStatus(controller.signal);
        if (controller.signal.aborted) return;
        setNative(loaded);
        if (loaded.active_job) setNativeJob(loaded.active_job);
      } catch (err: unknown) { if (!controller.signal.aborted) setError(errorMessage(err)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void readStatus(), 5000);
    }
    void readStatus();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh, pageVisible]);

  useEffect(() => {
    if (!nativeJob) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const job = await fetchNativeDeckJob(nativeJob!, controller.signal);
        if (controller.signal.aborted) return;
        setNativeProgress(job.detail); setTransferProgress(job.progress);
        if (job.action) setNativeJobAction(job.action);
        if (job.cancel) setStopRequested(true);
        if (job.state === 'running') { timer = setTimeout(() => void poll(), 700); return; }
        setNativeJob(null); setNativeProgress(''); setNativeJobAction(null); setStopRequested(false);
        if (job.state === 'error') { setError(job.detail); setChecked([]); setModal((value) => value === 'store' || value === 'stop-job' ? null : value); }
        else {
          setChecked([]);
          setModal(null); setSelected(null); setRevision(undefined);
          const count = job.result?.count ?? 0;
          const decks = `${count} deck${count === 1 ? '' : 's'}`;
          const stopped: Partial<Record<NativeDeckAction, string>> = {
            backup: `Backup stopped. ${decks} backed up before stopping; the rest were not backed up.`,
            store: `Stopped. Moved ${decks} to ${storedTo.current} and removed them from Arena; the remaining selected decks are still in Arena.`,
            restore: `Stopped. Restored ${decks} to Arena; the remaining selected decks were not restored.`,
          };
          const messages: Record<NativeDeckAction, string> = {
            connect: 'Arena decks refreshed.', backup: `Backed up ${count} deck${count === 1 ? '' : 's'} to your collection.`,
            store: `Moved ${count} deck${count === 1 ? '' : 's'} to ${storedTo.current} and removed ${count === 1 ? 'it' : 'them'} from Arena. If Arena still shows ${count === 1 ? 'it' : 'them'}, leave Arena’s Decks screen and open it again.`,
            restore: `Restored ${count} deck${count === 1 ? '' : 's'} directly to Arena.`, reconcile: 'Interrupted transfers reconciled. No Arena writes were repeated.',
            add: 'Deck added directly to Arena.',
          };
          const finished = job.result?.action ?? 'connect';
          setNotice((job.result?.cancelled && stopped[finished]) || messages[finished]);
        }
        setRefresh((value) => value + 1);
      } catch (err: unknown) {
        if (!controller.signal.aborted) { setError(errorMessage(err)); setNativeJob(null); setNativeProgress(''); setRefresh((value) => value + 1); }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [nativeJob]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    fetchManagedDeck(selected, revision, controller.signal).then((loaded) => {
      if (controller.signal.aborted) return;
      setDetail(loaded);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(err));
    });
    return () => controller.abort();
  }, [selected, revision, refresh]);

  async function action(run: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await run(); } catch (err: unknown) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  async function nativeAction(kind: NativeDeckAction, ids = checked, collectionId?: string | null) {
    if (native?.in_game) throw new Error('Finish your game first. Deck Manager can work with Arena again when it ends.');
    const decks = ids.map((id) => ({ id, ...(kind === 'restore' && activeDetail?.id === id ? { revision: activeDetail.revision_id } : {}) }));
    const job = await (collectionId === undefined ? startNativeDeckJob(kind, decks) : startNativeDeckJob(kind, decks, collectionId));
    setNativeJob(job.job_id); setNativeJobAction(kind); setNativeProgress('Contacting Arena…'); setTransferProgress(undefined);
  }

  function expand(id: string) { setExpanded((value) => value.includes(id) ? value : [...value, id]); }
  // Searching or filtering opens every collection so matches are visible.
  function expandAll() { setExpanded(collectionGroups.map((group) => group.id)); }

  async function storeSelected() {
    let target = storeTarget || null;
    let name = library?.collections?.find((c) => c.id === target)?.name ?? 'Unsorted';
    if (storeTarget === NEW_COLLECTION) {
      const created = await saveDeckCollection(storeNewName);
      target = created.id; name = created.name;
      setRefresh((value) => value + 1);
      setStoreTarget(created.id); setStoreNewName('');
    }
    storedTo.current = name;
    expand(target ?? '');
    await nativeAction('store', checked, target);
  }

  /** Text and captured decks go through Arena's importer, like Deck Finder's Add to Arena. */
  async function addSavedToArena(deck: ManagedDeckDetail) {
    if (native?.in_game) throw new Error('Finish your game first. Deck Manager can work with Arena again when it ends.');
    const exported = await exportManagedDeck(deck.id, deck.revision_id, 'arena');
    const job = await addDeckToArena(exported.text, deck.name, deck.deck.format_name ?? '', deck.id);
    setNativeJob(job.job_id); setNativeJobAction('add'); setNativeProgress('Contacting Arena…'); setTransferProgress(undefined);
  }

  async function stopJob() {
    if (!nativeJob) return;
    await cancelNativeDeckJob(nativeJob);
    setStopRequested(true); setModal(null);
  }

  const clearFilters = <button type="button" className="deck-manager-link-button" onClick={() => { setQuery(''); filterByStatus('all'); }}>Clear filters</button>;

  function changeView(next: 'saved' | 'trash' | 'arena') { setView(next); setChecked([]); setStatusFilter('all'); setError(''); setNotice(''); }

  function filterByStatus(status: DeckStatus | 'all') { setStatusFilter(status); setChecked([]); expandAll(); }

  function statusPills(statuses: DeckStatus[]) {
    return <div className="deck-manager-status-pills">{statuses.map((status) =>
      <button type="button" key={status} className={`deck-manager-status-pill deck-manager-status-${status}`} disabled={busy}
        aria-label={`Filter by ${statusLabels[status]}`} title={`Show ${statusLabels[status].toLowerCase()} decks`}
        onClick={() => filterByStatus(status)}>{statusLabels[status]}</button>)}</div>;
  }

  function toggleChecked(id: string) { setChecked((value) => value.includes(id) ? value.filter((item) => item !== id) : [...value, id]); }

  function confirmRemoval() {
    setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setError(''); setNotice(''); setModal(view === 'trash' ? 'bulk-delete' : 'bulk-trash');
  }

  function closeModal() {
    setModal(null); setSelected(null); setRevision(undefined); setError('');
  }

  function cancelTrash() {
    setModal('deck'); setError(''); setNotice('');
  }

  function choose(id: string) {
    setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setSelected(id); setRevision(undefined); setModal('deck'); setError(''); setNotice('');
  }

  function openImport() {
    setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setSelected(null); setRevision(undefined); setText(''); setName(''); setFormat('');
    setError(''); setNotice(''); setModal('import');
  }

  async function saveImport() {
    const saved = await importManagedDeck(text, name, format, editingRevision ? selected ?? undefined : undefined, editingRevision ? undefined : importCollection || null);
    setRevision(undefined); setText(''); setName(''); setFormat('');
    if (editingRevision) { setSelected(saved.id); setModal('deck'); }
    else { setSelected(null); setModal(null); setView('saved'); setQuery(''); }
    setRefresh((value) => value + 1);
    setNotice(editingRevision ? 'Saved a new revision. Earlier lists are retained.' : 'Deck saved to your collection.');
  }

  async function exportDeck(download: boolean) {
    if (!activeDetail) return;
    const result = await exportManagedDeck(activeDetail.id, activeDetail.revision_id, download ? 'backup' : 'arena');
    if (download) {
      const url = URL.createObjectURL(new Blob([result.text], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url;
      const fileName = Array.from(result.name).filter((char) => char.charCodeAt(0) > 31).join('').replace(/[<>:"/\\|?*]/gu, '_');
      link.download = `${fileName || 'deck'}${result.extension}`;
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('Full deck backup downloaded.');
    } else {
      await navigator.clipboard.writeText(result.text);
      setNotice(`Deck copied. Open Arena’s Decks screen and click Import when a slot is available.${result.note ? ` ${result.note}` : ''}`);
    }
  }

  const collectionGroups = [...(library?.collections ?? []), { id: '', name: 'Unsorted' }];

  function openCollection(collection: DeckCollection | null = null) {
    setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setEditingCollection(collection); setCollectionName(collection?.name ?? '');
    setError(''); setNotice(''); setModal('collection');
  }

  function collectionOptions() {
    return <><option value="">Unsorted</option>{library?.collections?.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}</>;
  }

  function savedTile(deck: ManagedDeck) {
    return (
          <div className="deck-manager-tile-wrapper" key={deck.id}>
          <label className="deck-manager-tile-select" title={`Select ${deck.name}`} onClick={(event) => event.stopPropagation()}>
            <input className="deck-manager-tile-check" type="checkbox" aria-label={`Select ${deck.name}`} checked={checked.includes(deck.id)} disabled={busy} onChange={() => toggleChecked(deck.id)} />
          </label>
          <button key={deck.id} className="deck-manager-tile" onClick={() => choose(deck.id)} aria-haspopup="dialog" title={deck.name}>
            <span className="deck-manager-tile-art"><DeckVisual deckName={deck.name} visual={deckArt(deck.art_card)} /><ColorPips colors={deck.colors} size={14} /></span>
            <span className="deck-manager-tile-text">
              <strong>{deck.name}</strong>
              <small>{deckFormatLabel(deck.format_name) || 'Format not specified'} · {deck.main_count} cards</small>
              <small>Updated: <time dateTime={deck.updated_at} title={formatDateTime(deck.updated_at)}>{new Date(deck.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</time></small>
            </span>
          </button>
          {statusPills(savedStatuses(deck))}
          </div>

    );
  }


  const feedback = <>
    {error ? <p role="alert" className="deck-manager-error">{error}</p> : null}
    {notice ? <p role="status" className="deck-manager-notice">{notice}</p> : null}
    {nativeProgress ? <DeckTransferProgress detail={nativeProgress} progress={transferProgress} /> : null}
  </>;

  return (
    <section id="deck-manager-library" className="deck-manager-collection" aria-label="Saved deck collection">
      <div className="deck-manager-collection-toolbar">
        <div className="deck-manager-toolbar deck-manager-tabs">
          <button aria-pressed={view === 'saved'} disabled={busy} onClick={() => changeView('saved')}>
            <Archive size={16} /> Saved ({library?.decks.filter((d) => !d.trashed_at).length ?? 0})
          </button>
          <button aria-pressed={view === 'arena'} disabled={busy} onClick={() => changeView('arena')}><FolderOpen size={16} /> Arena{native?.connected ? ` (${native.decks.length})` : ''}</button>
          <button aria-pressed={view === 'trash'} disabled={busy} onClick={() => changeView('trash')}><Trash2 size={16} /> Trash</button>
        </div>
        <div className="deck-manager-toolbar deck-manager-collection-actions">
          {nativeJob && nativeJobAction && STOPPABLE.includes(nativeJobAction) ? <button className="deck-manager-delete" disabled={stopRequested} onClick={() => { setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null); setModal('stop-job'); }}><Square size={16} />{stopRequested ? 'Stopping…' : nativeJobAction === 'backup' ? 'Stop backup' : 'Stop transfer'}</button> : null}
          {native?.available ? <>
            <button disabled={busy || native.in_game} title={native.in_game ? 'Available after your game ends.' : 'Reads the decks in Arena right now. Arena must be on its Decks screen, outside a match.'} onClick={() => void action(() => nativeAction('connect', []))}><RefreshCw size={16} />{loadLabel(native)}</button>
            <button className="deck-manager-add" disabled={busy || native.in_game || Boolean(native.pending_transfers?.length)} onClick={() => void action(() => nativeAction('backup', view === 'arena' ? checked : []))}><Archive size={16} />{view === 'arena' && checked.length ? `Back up ${checked.length} selected` : 'Back up all Arena decks'}</button>
          </> : <button disabled={busy} title="Back up decklists available in Arena’s log" onClick={() => void action(async () => {
            const result = await captureArenaDecks(); setRefresh((value) => value + 1);
            setNotice(`Captured ${result.captured} deck${result.captured === 1 ? '' : 's'}. ${result.note}${result.rejected ? ` ${result.rejected} malformed lists were skipped.` : ''}`);
          })}><RefreshCw size={16} /> Capture Arena lists</button>}
        </div>
      </div>
      <DeckManagerHelp />
      <DeckManagerStatus native={native} jobAction={nativeJobAction} jobDetail={nativeProgress} progress={transferProgress}
        error={error} notice={notice} showMessages={!modal} busy={busy}
        onReconcile={() => void action(() => nativeAction('reconcile', []))} onDismiss={() => { setError(''); setNotice(''); }} />
      <div className="deck-manager-filters">
        <input type="search" className="deck-manager-search" aria-label="Search saved decks" placeholder="Search names, formats or tags" value={query} disabled={busy} onChange={(e) => { setQuery(e.target.value); setChecked([]); expandAll(); }} />
        <select className="deck-manager-status-filter" aria-label="Filter decks by status" value={statusFilter} disabled={busy} onChange={(e) => filterByStatus(e.target.value as DeckStatus | 'all')}>
          <option value="all">All statuses</option>
          {[{ label: 'Location', statuses: ['arena', 'collection', 'unknown', 'trash'] }, { label: 'Backup', statuses: ['native', 'text', 'partial', 'backed', 'unbacked'] }].map((group) => {
            const options = filterStatuses.filter((status) => group.statuses.includes(status));
            return options.length ? <optgroup key={group.label} label={group.label}>{options.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}</optgroup> : null;
          })}
        </select>
        <select className="deck-manager-status-filter deck-manager-sort" aria-label="Sort decks" value={activeSort} disabled={busy} onChange={(e) => {
          const next = e.target.value as SortKey; setSort(next);
          try { localStorage.setItem(SORT_KEY, next); } catch { /* Preference only. */ }
        }}>
          {sortOptions.map((key) => <option key={key} value={key}>{sortLabels[key]}</option>)}
        </select>
      </div>
      <div className="deck-manager-toolbar deck-manager-native-bar deck-manager-action-bar">
        {view === 'saved' ? <>
          <button className="deck-manager-add" disabled={busy} onClick={openImport}><Plus size={18} /> Add deck</button>
          <button disabled={busy} onClick={() => openCollection()}><FolderOpen size={16} /> New collection</button>
          <span className="deck-manager-action-divider" aria-hidden="true" />
          <select aria-label="Move selected decks to collection" value={destination} disabled={busy || !checkedDecks.length} onChange={(event) => setDestination(event.target.value)}>{collectionOptions()}</select>
          <button disabled={busy || !checkedDecks.length} onClick={() => void action(async () => {
            const result = await moveDecksToCollection(checkedDecks.map((deck) => deck.id), destination || null);
            setChecked([]); setRefresh((value) => value + 1); expand(destination);
            setNotice(`Moved ${result.count} deck${result.count === 1 ? '' : 's'} to ${collectionGroups.find((group) => group.id === destination)?.name ?? 'Unsorted'}.`);
          })}><FolderOpen size={16} /> Move decks</button>
          {native?.available ? <button className="deck-manager-copy" aria-label="Restore selected to Arena" title={!canRestoreSelection && checked.length ? 'Select native backups that are not already in Arena to restore.' : undefined} disabled={busy || !canRestoreSelection || !native.connected || !native.deck_screen_open || native.limit_reached !== false || Boolean(native.pending_transfers?.length)} onClick={() => void action(() => nativeAction('restore'))}><ArrowUpFromLine size={16} /> Restore to Arena</button> : null}
        </> : null}
        {view === 'arena' ? <button className="deck-manager-add" disabled={busy || !checked.length || !native?.deck_screen_open || Boolean(native.pending_transfers?.length)} onClick={() => { setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null); setModal('store'); }}><ArrowDownToLine size={16} /> Move to collection</button>
          : <button className="deck-manager-delete" aria-label={view === 'trash' ? 'Delete selected permanently' : 'Move selected to trash'} disabled={busy || !checkedDecks.length} onClick={confirmRemoval}><Trash2 size={16} />{view === 'trash' ? 'Delete permanently' : 'Move to trash'}</button>}
        <div className="deck-manager-select-all">
          <span>{checked.length} selected</span>
          {view === 'arena'
            ? <label><input type="checkbox" aria-label="Select all visible Arena decks" disabled={busy || !arenaDecks.length} checked={Boolean(arenaDecks.length) && arenaDecks.every((d) => checked.includes(d.id))} onChange={(e) => setChecked(e.target.checked ? arenaDecks.map((d) => d.id) : [])} /> Select all</label>
            : <label><input type="checkbox" aria-label="Select all visible saved decks" disabled={busy || !visible.length} checked={Boolean(visible.length) && visible.every((d) => checked.includes(d.id))} onChange={(e) => setChecked(e.target.checked ? visible.map((d) => d.id) : [])} /> Select all</label>}
        </div>
      </div>
      <div className={`deck-manager-decks${view === 'saved' ? ' deck-manager-collections-grid' : ''}`}>
        {view === 'arena' ? arenaDecks.map((deck) => <div key={deck.id} className="deck-manager-tile-wrapper">
          <label className="deck-manager-tile-select" title={`Select ${deck.name}`}><input className="deck-manager-tile-check" type="checkbox" aria-label={`Select ${deck.name}`} checked={checked.includes(deck.id)} disabled={busy} onChange={() => toggleChecked(deck.id)} /></label>
          <button type="button" className={`deck-manager-tile deck-manager-arena-tile${checked.includes(deck.id) ? ' deck-manager-tile-selected' : ''}`} disabled={busy} onClick={() => toggleChecked(deck.id)} aria-label={`Toggle selection of ${deck.name}`}>
          <span className="deck-manager-tile-art"><DeckVisual deckName={deck.name} visual={deckArt(arenaArtwork.get(deck.id)?.art_card ?? deck.art_card, arenaArtwork.has(deck.id) ? null : deck.art_card_id)} /><ColorPips colors={deck.colors} size={14} /></span>
          <span className="deck-manager-tile-text"><strong>{deck.name}</strong><small>{deckFormatLabel(deck.format_name) || 'Any format'} · {deck.main_count} cards</small></span>
          </button>
          {statusPills(arenaStatuses(deck.id))}
        </div>) : (view === 'trash' ? visible.map(savedTile) : collectionGroups.map((group) => {
          const decks = visible.filter((deck) => (deck.collection_id ?? '') === group.id);
          const closed = !expanded.includes(group.id);
          // One page-level message covers "nothing matches"; empty Unsorted adds nothing.
          if (!decks.length && (filtering || !group.id)) return null;
          return <section className="deck-manager-group" key={group.id} aria-label={`${group.name} collection`}>
            <div className="deck-manager-group-heading deck-manager-toolbar">
              <button className="deck-manager-group-toggle" aria-label={`${group.name} (${decks.length})`} aria-expanded={!closed} aria-controls={`collection-${group.id || 'unsorted'}`} onClick={() => setExpanded((value) => closed ? [...value, group.id] : value.filter((id) => id !== group.id))}>
                <ChevronDown size={18} className={closed ? 'is-collapsed' : ''} /><strong>{group.name}</strong><span>({decks.length})</span>
              </button>
              {group.id ? <><button aria-label={`Rename ${group.name}`} disabled={busy} onClick={() => openCollection(group)}><Pencil size={16} /></button>
                <button className="deck-manager-delete-quiet" aria-label={`Remove ${group.name} collection`} disabled={busy} onClick={() => { setEditingCollection(group); setModalOpener(document.activeElement as HTMLElement); setModal('remove-collection'); }}><Trash2 size={16} /></button></> : null}
            </div>
            {!closed ? <div className="deck-manager-group-decks" id={`collection-${group.id || 'unsorted'}`}>{decks.map(savedTile)}{!decks.length ? <p className="deck-manager-group-empty">No decks yet. Select decks and use Move decks to add them here.</p> : null}</div> : null}
          </section>;
        }))}
      </div>
      {view === 'arena' && !arenaDecks.length ? <p className="empty-state">{!native?.connected ? `Arena decks aren’t loaded yet. Click ${loadLabel(native)} at the top right.` : filtering ? <>No Arena decks match your search or status filter. {clearFilters}</> : 'Arena reported no decks.'}</p> : null}
      {view !== 'arena' && (!library ? <p className="empty-state" role="status">Loading your collection…</p> : !visible.length ? (
        <p className="empty-state">{filtering ? <>No {view === 'trash' ? 'decks in Trash' : 'saved decks'} match your search or status filter. {clearFilters}</> : view === 'trash' ? 'No decks in trash.' : 'Add your first deck, or back up your Arena decks.'}</p>
      ) : null)}

      {modal ? (
        <DeckModal key={modal} title={modal === 'stop-job' ? nativeJobAction === 'backup' ? 'Stop backing up Arena decks?' : 'Stop the transfer?' : modal === 'collection' ? editingCollection ? 'Rename collection' : 'New collection' : modal === 'remove-collection' ? `Remove ${editingCollection?.name} collection?` : modal === 'bulk-trash' ? `Move ${checkedDecks.length} decks to Trash?` : modal === 'bulk-delete' ? `Permanently delete ${checkedDecks.length} decks?` : modal === 'store' ? `Move ${checked.length} deck${checked.length === 1 ? '' : 's'} out of Arena?` : modal === 'trash' ? `Move ${activeDetail?.name ?? selectedDeck?.name ?? 'saved deck'} to Trash?` : modal === 'delete' ? `Delete ${activeDetail?.name ?? selectedDeck?.name ?? 'saved deck'}?` : modal === 'deck' ? activeDetail?.name ?? selectedDeck?.name ?? 'Saved deck' : editingRevision ? 'Save a new revision' : 'Add a deck'} busy={modal === 'stop-job' ? false : busy} onClose={modal === 'trash' ? cancelTrash : modal === 'stop-job' ? () => setModal(null) : closeModal} returnFocus={modalOpener}
          wide={modal === 'deck'}
          closeOnBackdrop={modal !== 'import' && modal !== 'revision'}
          headerActions={modal === 'deck' && activeDetail ? <>
            <button disabled={busy} title="Copy this list in MTG Arena import format" onClick={() => void action(() => exportDeck(false))}><Copy size={16} /> Copy deck list</button>
            <BuyPaperButton className="deck-manager-buy-paper" disabled={!activeDetail.deck.cards.length} onOpen={setBuyingOpener} />
            {native?.available && !activeDetail.trashed_at && !inArena(activeDetail) ? activeDetail.native_restorable
              ? <button className="deck-manager-copy" disabled={busy || !native.connected || !native.deck_screen_open || native.limit_reached !== false || Boolean(native.pending_transfers?.length)} onClick={() => void action(() => nativeAction('restore', [activeDetail.id]))}><ArrowUpFromLine size={16} /> Restore to Arena</button>
              : <button className="deck-manager-copy" disabled={busy || native.in_game || native.limit_reached === true || Boolean(native.pending_transfers?.length)} title="Adds this list with Arena’s importer. Arena must be on Decks outside a match." onClick={() => void action(() => addSavedToArena(activeDetail))}><ArrowUpFromLine size={16} /> Add to Arena</button>
              : null}
          </> : null}>
          {feedback}
          {modal === 'stop-job' ? <div className="deck-manager-delete-confirmation">
            <p>{nativeJobAction === 'backup'
              ? 'The backup stops after the deck it is reading now. Decks already read are verified and saved to your collection; the remaining Arena decks are not backed up. You can back them up later.'
              : 'The deck being transferred now finishes and is verified first. The remaining selected decks stay where they are, and you can transfer them later.'}</p>
            <div className="deck-manager-toolbar"><button onClick={() => setModal(null)}>Keep going</button><button className="deck-manager-delete" disabled={stopRequested || !nativeJob} onClick={() => void action(stopJob)}><Square size={16} /> Stop after this deck</button></div>
          </div> : modal === 'collection' ? <form className="deck-manager-import" onSubmit={(event) => { event.preventDefault(); void action(async () => {
            const result = await saveDeckCollection(collectionName, editingCollection?.id); expand(result.id); setRefresh((value) => value + 1); closeModal(); setNotice(editingCollection ? 'Collection renamed.' : 'Collection created.');
          }); }}>
            <label>Collection name<input autoFocus value={collectionName} maxLength={80} required onChange={(event) => setCollectionName(event.target.value)} placeholder="For example, Brawl or Blue decks" /></label>
            <div className="deck-manager-toolbar"><button type="button" disabled={busy} onClick={closeModal}>Cancel</button><button className="deck-manager-add" disabled={busy || !collectionName.trim()} type="submit">{editingCollection ? 'Save name' : 'Create collection'}</button></div>
          </form> : modal === 'remove-collection' ? <div className="deck-manager-delete-confirmation">
            <p>Remove this collection? All its decks, including decks in Trash, will move to Unsorted. Their saved revisions will be retained.</p>
            <div className="deck-manager-toolbar"><button disabled={busy} onClick={closeModal}>Cancel</button><button className="deck-manager-delete" disabled={busy || !editingCollection} onClick={() => void action(async () => {
              if (!editingCollection) return; await removeDeckCollection(editingCollection.id); setDestination(''); setImportCollection(''); setStoreTarget(''); setRefresh((value) => value + 1); closeModal(); setNotice('Collection removed. Its decks are in Unsorted.');
            })}>Remove collection</button></div>
          </div> : modal === 'bulk-trash' || modal === 'bulk-delete' ? <div className="deck-manager-delete-confirmation">
            <p>{modal === 'bulk-trash' ? 'These decks and all their saved revisions will move to Trash. You can restore them from the Trash tab.' : 'These decks and all their saved revisions will be permanently deleted. You cannot undo this from Trash.'}</p>
            <p className="deck-manager-description">This affects your saved collection only. Decks in Arena and recorded games remain unchanged.</p>
            <ul className="deck-manager-confirmation-list" aria-label="Decks selected for removal">{checkedDecks.map((deck) => <li key={deck.id}><strong>{deck.name}</strong><small>{deckFormatLabel(deck.format_name) || 'Any format'}</small></li>)}</ul>
            <div className="deck-manager-toolbar">
              <button disabled={busy} onClick={closeModal}>Cancel</button>
              <button className="deck-manager-delete" disabled={busy || !checkedDecks.length} onClick={() => void action(async () => {
                const result = await removeManagedDecks(checkedDecks.map((deck) => deck.id), modal === 'bulk-trash' ? 'trash' : 'delete');
                const removed = modal === 'bulk-delete';
                setChecked([]); setRefresh((value) => value + 1); closeModal();
                setNotice(`${result.count} deck${result.count === 1 ? '' : 's'} ${removed ? 'permanently deleted from your collection.' : 'moved to Trash. You can restore them there.'}`);
              })}><Trash2 size={16} />{busy ? modal === 'bulk-trash' ? 'Moving…' : 'Deleting…' : modal === 'bulk-trash' ? 'Move to trash' : 'Delete permanently'}</button>
            </div>
          </div> : modal === 'store' ? <div className="deck-manager-delete-confirmation">
            <p>These decks will be <strong>deleted from Arena</strong> to free deck slots. Each one is saved to Deck Manager and checked first, so you can restore it to Arena later. Your cards stay in your Arena collection.</p>
            <ul className="deck-manager-confirmation-list">{(native?.decks ?? []).filter((d) => checked.includes(d.id)).map((d) => <li key={d.id}>{d.name}</li>)}</ul>
            <label className="deck-manager-store-target">Save to collection<select value={storeTarget} disabled={busy || Boolean(nativeJob)} onChange={(event) => setStoreTarget(event.target.value)}>{collectionOptions()}<option value={NEW_COLLECTION}>New collection…</option></select></label>
            {storeTarget === NEW_COLLECTION ? <label className="deck-manager-store-target">New collection name<input value={storeNewName} maxLength={80} autoFocus disabled={busy || Boolean(nativeJob)} onChange={(event) => setStoreNewName(event.target.value)} /></label> : null}
            <p className="deck-manager-store-note">Arena may keep showing these decks until you leave its Decks screen and open it again.</p>
            <div className="deck-manager-toolbar"><button disabled={busy} onClick={closeModal}>Cancel</button><button className="deck-manager-add" disabled={busy || Boolean(nativeJob) || !checked.length || (storeTarget === NEW_COLLECTION && !storeNewName.trim())} onClick={() => void action(storeSelected)}><ArrowDownToLine size={16} />{busy || nativeJob ? 'Moving…' : 'Move out of Arena'}</button></div>
          </div> : modal === 'trash' ? (
            <div className="deck-manager-delete-confirmation">
              <p>This moves the deck and its saved revisions out of your collection into Trash. You can restore it from the Trash tab.</p>
              <div className="deck-manager-toolbar">
                <button disabled={busy} onClick={cancelTrash}>Cancel</button>
                <button className="deck-manager-delete" disabled={busy || !activeDetail || Boolean(activeDetail.trashed_at)} onClick={() => void action(async () => {
                  if (!activeDetail) return;
                  await updateManagedDeck(activeDetail.id, { trashed: true });
                  setRefresh((value) => value + 1); closeModal();
                  setNotice('Deck moved to Trash. You can restore it there.');
                })}><Trash2 size={16} />{busy ? 'Moving…' : 'Move to trash'}</button>
              </div>
            </div>
          ) : modal === 'delete' ? (
            <div className="deck-manager-delete-confirmation">
              <p>This permanently removes this deck and {activeDetail?.revisions.length === 1 ? 'its saved revision' : `all ${activeDetail?.revisions.length ?? 0} saved revisions`} from your collection. You cannot undo this from Trash.</p>
              <p className="deck-manager-description">Your deck in Arena and recorded game history are unchanged. Previously downloaded backups retain their copies.</p>
              <div className="deck-manager-toolbar">
                <button disabled={busy} onClick={() => { setModal('deck'); setError(''); }}>Cancel</button>
                <button className="deck-manager-delete" disabled={busy || !activeDetail?.trashed_at} onClick={() => void action(async () => {
                  if (!activeDetail) return;
                  await deleteManagedDeck(activeDetail.id);
                  setRefresh((value) => value + 1); closeModal();
                  setNotice('Deck and all saved revisions permanently deleted from your collection.');
                })}><Trash2 size={16} />{busy ? 'Deleting…' : 'Delete deck'}</button>
              </div>
            </div>
          ) : modal === 'deck' ? activeDetail ? (
            <DeckDetail key={`${activeDetail.id}:${activeDetail.revision_id}`} detail={activeDetail} busy={busy} collections={library?.collections ?? []}
              statusPills={<div className="deck-manager-status-pills">{savedStatuses(activeDetail).map((status) => <span key={status} className={`deck-manager-status-pill deck-manager-status-${status}`}>{statusLabels[status]}</span>)}</div>}
              onCollection={(target) => void action(async () => { await moveDecksToCollection([activeDetail.id], target); setRefresh((value) => value + 1); setNotice('Deck moved to collection.'); })}
              onRevision={setRevision}
              onSaveMetadata={(nextNotes, nextTags) => void action(async () => { await updateManagedDeck(activeDetail.id, { notes: nextNotes, tags: nextTags }); setRefresh((value) => value + 1); setNotice('Notes and tags saved.'); })}
              onEditRevision={() => void action(async () => {
                const exported = await exportManagedDeck(activeDetail.id, activeDetail.revision_id, 'arena');
                setText(exported.text); setName(activeDetail.name); setFormat(activeDetail.format_name); setModal('revision');
              })}
              onDownload={() => void action(() => exportDeck(true))}
              onTrash={() => { setModal('trash'); setError(''); setNotice(''); }}
              onRestoreFromTrash={() => void action(async () => { await updateManagedDeck(activeDetail.id, { trashed: false }); setRefresh((value) => value + 1); closeModal(); setNotice('Deck restored to your collection.'); })}
              onDeletePermanently={() => { setModal('delete'); setError(''); setNotice(''); }} />
          ) : <p role="status" className="empty-state">Loading deck…</p> : (
            <form className="deck-manager-import" onSubmit={(event) => { event.preventDefault(); void action(saveImport); }}>
              <p className="deck-manager-description">Paste an Arena decklist or open a .txt or .tappsdeck backup.{editingRevision ? ' Earlier revisions are retained.' : ''}</p>
              <div className="deck-manager-fields">
                <label>Deck name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Use the name in the decklist" maxLength={256} /></label>
                <label>Format<select value={format} onChange={(e) => setFormat(e.target.value)}>
                  <option value="">Not specified</option>
                  {/* An existing revision keeps a format outside the list, such as one typed earlier. */}
                  {[...DECK_FORMATS, ...(format && !(DECK_FORMATS as readonly string[]).includes(format) ? [format] : [])].map((value) => <option key={value} value={value}>{deckFormatLabel(value)}</option>)}
                </select></label>
              </div>
              {!editingRevision ? <label>Collection<select value={importCollection} disabled={busy} onChange={(event) => setImportCollection(event.target.value)}>{collectionOptions()}</select></label> : null}
              <label>Decklist or backup<textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} required spellCheck={false} /></label>
              <input ref={fileInput} type="file" accept=".txt,.tappsdeck,.json" className="deck-manager-file" aria-label="Open deck backup file" onChange={(event) => {
                const file = event.target.files?.[0]; if (!file) return;
                void action(async () => { if (file.size > 2_000_000) throw new Error('Deck file is too large.'); setText(await file.text()); setNotice(`${file.name} is ready to save.`); });
                event.target.value = '';
              }} />
              <div className="deck-manager-toolbar deck-manager-import-actions">
                <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}><FolderOpen size={16} /> Open file</button>
                <button className="deck-manager-add" type="submit" disabled={busy || !text.trim()}><Archive size={16} />{busy ? 'Working…' : editingRevision ? 'Save revision' : 'Save deck'}</button>
                <button type="button" disabled={busy} onClick={() => {
                  if (editingRevision) { setModal('deck'); setError(''); setNotice(''); } else closeModal();
                }}>{editingRevision ? 'Cancel revision' : 'Cancel'}</button>
              </div>
            </form>
          )}
        </DeckModal>
      ) : null}
      {buyingOpener && modal === 'deck' && activeDetail ? (
        <BuyPaperDialog deckName={activeDetail.name} sections={managedDeckSections(activeDetail)}
          onClose={() => setBuyingOpener(null)} returnFocus={buyingOpener} />
      ) : null}
    </section>
  );
}
