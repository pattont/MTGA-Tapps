import { useEffect, useRef, useState } from 'react';
import { ChevronDown, CircleHelp, Pencil, Archive, ArrowDownToLine, ArrowUpFromLine, Copy, FolderInput, FolderOpen, GitCompareArrows, Plus, RefreshCw, Search, Square, Star, Trash2, X } from 'lucide-react';
import {
  saveDeckCollection, removeDeckCollection, moveDecksToCollection, type DeckCollection, type NativeDeckJob,
  captureArenaDecks, exportManagedDeck, fetchDeckLibrary, fetchManagedDeck,
  importManagedDeck, updateManagedDeck, deleteManagedDeck, removeManagedDecks, type DeckLibrary, type ManagedDeckDetail,
  fetchArenaDeck, type ArenaDeck, type ArenaDeckCards, fetchNativeDeckStatus, startNativeDeckJob, fetchNativeDeckJob, cancelNativeDeckJob, addDeckToArena, type NativeDeckStatus, type NativeDeckAction, type ManagedDeck, type ManagedCard, type DeckRecord,
} from '../deckManagerApi';
import { DeckRecordBadge } from './DeckRecordBadge';
import { usePageVisible } from '../usePageVisible';
import { formatDateTime } from '../format';
import { DeckVisual } from './DeckVisual';
import { DeckTransferProgress } from './DeckTransferProgress';
import { DeckModal } from './DeckModal';
import { DeckDetail } from './DeckDetail';
import { ArenaDeckDetail } from './ArenaDeckDetail';
import { DeckCompare, type CompareSide } from './DeckCompare';
import { ColorPips } from './ColorPips';
import { ArenaStatusChip, DeckManagerStatus } from './DeckManagerStatus';
import { BuyPaperButton, BuyPaperDialog } from './BuyPaperDialog';
import { managedDeckSections } from '../paperDeck';
import { loadLabel, ARENA_LOADED_NOTICE } from '../deckManagerLabels';
import { DECK_FORMATS, deckFormatLabel } from '../deckFormatLabel';

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Deck Manager could not complete this action.';
}

type ModalView = 'help' | 'deck' | 'arena-deck' | 'compare' | 'import' | 'revision' | 'delete' | 'trash' | 'store' | 'arena-trash' | 'move-collection' | 'bulk-trash' | 'bulk-delete' | 'collection' | 'remove-collection' | 'stop-job';

const STOPPABLE: NativeDeckAction[] = ['backup', 'store', 'restore'];
const NEW_COLLECTION = '__new__';
const DEFAULT_IMPORT_NAME = 'DeckManager Import Deck';

const LIST_SECTIONS = ['Commander', 'Companion', 'Deck', 'Sideboard'];

/** An Arena deck's cards as Arena import text. */
function arenaListText(cards: ManagedCard[]) {
  return LIST_SECTIONS.map((section) => {
    const lines = cards.filter((card) => card.section === section)
      .map((card) => `${card.quantity} ${card.name}${card.set_code && card.collector_number ? ` (${card.set_code}) ${card.collector_number}` : ''}`);
    return lines.length ? `${section}\n${lines.join('\n')}` : '';
  }).filter(Boolean).join('\n\n');
}

/** A blank name for Add deck uses the list's own "Name …" line, then a default. */
function importName(name: string, text: string) {
  const listed = text.split(/\r?\n/u).map((line) => line.trim()).find((line) => /^name\s+\S/iu.test(line));
  return name.trim() || listed?.slice(5).trim() || DEFAULT_IMPORT_NAME;
}

type SortKey = 'name-asc' | 'name-desc' | 'updated-desc' | 'updated-asc' | 'modified-desc' | 'modified-asc' | 'played-desc';
const SORT_KEY = 'tapps.deckManager.sort';
// The Arena tab keeps its own order, newest edit first like Arena's deck list.
const ARENA_SORT_KEY = 'tapps.deckManager.arenaSort';
const sortLabels: Record<SortKey, string> = {
  'name-asc': 'Name A–Z', 'name-desc': 'Name Z–A', 'updated-desc': 'Updated: newest first', 'updated-asc': 'Updated: oldest first',
  'modified-desc': 'Modified in Arena: newest', 'modified-asc': 'Modified in Arena: oldest', 'played-desc': 'Played in Arena: recent',
};
/** The Arena tab drops "in Arena" from its labels. */
const arenaSortLabels: Partial<Record<SortKey, string>> = {
  'modified-desc': 'Modified: newest first', 'modified-asc': 'Modified: oldest first', 'played-desc': 'Played: most recent',
};
const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true });

type Sortable = { name: string; updated_at?: string; arena_modified?: string | null; arena_played?: string | null };
const sortDates: Partial<Record<SortKey, (deck: Sortable) => string | null | undefined>> = {
  'updated-desc': (deck) => deck.updated_at, 'updated-asc': (deck) => deck.updated_at,
  'modified-desc': (deck) => deck.arena_modified, 'modified-asc': (deck) => deck.arena_modified,
  'played-desc': (deck) => deck.arena_played,
};

/** Name order, or a date order where decks without that date come last either way. */
function storedSort(key: string, fallback: SortKey): SortKey {
  try { const stored = localStorage.getItem(key); return stored && stored in sortLabels ? stored as SortKey : fallback; } catch { return fallback; }
}

function sortDecks<T extends Sortable>(decks: T[], sort: SortKey): T[] {
  const date = sortDates[sort];
  return [...decks].sort((a, b) => {
    if (sort === 'name-desc') return byName(b, a);
    if (date) {
      const [first, second] = [date(a) || '', date(b) || ''];
      if (!first !== !second) return first ? -1 : 1;
      // All UTC ISO text, so text order is time order.
      const order = first.localeCompare(second);
      return (sort.endsWith('-asc') ? order : -order) || byName(a, b);
    }
    return byName(a, b);
  });
}

const statusLabels = {
  arena: 'In Arena', collection: 'Not in Arena',
  native: 'Exact copy', list: 'Deck list',
  backed: 'Backed up', unbacked: 'Not backed up',
};
type DeckStatus = keyof typeof statusLabels;
/** What each kind of saved copy holds, shown when hovering its pill. */
const statusHints: Partial<Record<DeckStatus, string>> = {
  native: 'Exact copy: read straight from Arena, with card styles, deck art and format. Goes back into Arena exactly as it was.',
  list: 'Deck list: the cards only, from Deck Finder, a pasted list or an edit. Goes back into Arena as a new deck, without card styles or deck art.',
};
/** Filter-only statuses: green "In Arena" is enough, so "Not in Arena" gets no pill. */
const shownPills = (statuses: DeckStatus[]) => statuses.filter((status) => status !== 'collection');

/** A tile's art source. `art_url` (Scryfall's image server) and `art_print` come from local data. */
type TileArt = { art_card?: string | null; art_card_id?: number | null; art_url?: string | null; art_print?: string | null };

/**
 * Tile art, cheapest source first. A page of tiles must not lean on Scryfall's
 * API: it turns away bursts, and its by-name lookup allows 2 requests a second.
 * The image server has no such limit, so a cached printing goes straight there.
 */
function deckArt(art?: TileArt | null) {
  const cardName = art?.art_card;
  const name = cardName && !cardName.startsWith('Card #') ? cardName : null;
  const nameUrl = name ? `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}&format=image&version=art_crop` : null;
  const cardId = art?.art_card_id ?? null;
  const primary = art?.art_url
    ?? (art?.art_print ? `https://api.scryfall.com/cards/${art.art_print}?format=image&version=art_crop` : null)
    ?? (cardId ? `https://api.scryfall.com/cards/arena/${cardId}?format=image&version=art_crop` : null);
  return { card_name: name, card_id: cardId, type_category: 'Other', source: 'local_metadata' as const,
    image_url: primary ?? nameUrl, image_fallback_url: primary ? nameUrl : null };
}

/** The How Deck Manager works dialog. */
const HELP = (
  <ul className="deck-manager-help-list">
    <li><strong>Deck Manager doesn’t stay connected to Arena.</strong> It reads Arena only when you load Arena decks or click Rescan Arena (beside the Arena status at the top right), or start a backup or transfer, and then lets go. The Arena status shows when it last read Arena.</li>
    <li><strong>Keep Arena open on the Decks screen, outside a match,</strong> whenever you load, back up or transfer decks. During a game Deck Manager leaves Arena alone.</li>
    <li><strong>Click Rescan Arena after any change made in Arena</strong> (adding, editing or deleting a deck). The Arena list is what Arena reported at the last scan.</li>
    <li><strong>Back up all Arena decks first.</strong> A backup is an <em>exact copy</em>: cards, card styles, deck art and format, so the deck goes back into Arena exactly as it was.</li>
    <li>A <em>deck list</em> is just the cards: a deck from Deck Finder, a pasted list or an edit. It goes into Arena as a new deck, without card styles or deck art. Back a deck up from the Arena tab to make it an exact copy.</li>
    <li>Moving a deck to your collection frees an Arena slot. Restoring or adding a deck uses one.</li>
    <li>Do one thing at a time, and don’t edit decks in Arena while a backup or transfer runs.</li>
    <li>If a transfer is interrupted, click <strong>Reconcile transfers</strong> before anything else. It only reads Arena and never repeats a change.</li>
  </ul>
);

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
  // Saved tab: one collection ('' = Unsorted) or every collection.
  const [collectionFilter, setCollectionFilter] = useState<string>('all');
  const [sort, setSort] = useState<SortKey>(() => storedSort(SORT_KEY, 'name-asc'));
  const [arenaSort, setArenaSort] = useState<SortKey>(() => storedSort(ARENA_SORT_KEY, 'modified-desc'));
  // Arena tab sections the user folded: 'favorites' and 'others'.
  const [arenaFolded, setArenaFolded] = useState<string[]>([]);
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
  // The Arena deck open in its dialog, the two decks being compared, and where Add deck sends a list.
  const [arenaSelected, setArenaSelected] = useState<string | null>(null);
  const [comparing, setComparing] = useState<{ view: 'saved' | 'arena'; ids: string[] } | null>(null);
  const [importToArena, setImportToArena] = useState(false);
  const [moveNewName, setMoveNewName] = useState('');
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
  // Where the deck is (only once Arena has been read) and what kind of copy it is.
  const savedStatuses = (deck: ManagedDeck): DeckStatus[] => [
    ...(!deck.trashed_at && native?.connected ? [inArena(deck) ? 'arena' as const : 'collection' as const] : []),
    deck.native_restorable ? 'native' : 'list',
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
  /** The saved entry whose cards stand in for an Arena deck: a full backup first, then any other saved copy. */
  const arenaCopy = (id: string) => arenaBackups.get(id) ?? arenaArtwork.get(id);
  /** Arena's own tile card; a saved copy's first card only when Arena named none. */
  const arenaTileArt = (id: string) => {
    const deck = native?.decks.find((item) => item.id === id);
    return deck?.art_card || deck?.art_card_id ? deckArt(deck) : deckArt(arenaArtwork.get(id));
  };
  // Every deck on the Arena tab is in Arena, so only its backup state gets a pill.
  const arenaStatuses = (id: string): DeckStatus[] => [arenaBackup(id) ? 'backed' : 'unbacked'];
  const filterStatuses: DeckStatus[] = view === 'arena' ? ['backed', 'unbacked'] : view === 'saved' && native?.connected ? ['arena', 'collection', 'native', 'list'] : ['native', 'list'];
  // A filter that no longer applies (Arena not read yet) shows everything.
  const activeStatus = statusFilter !== 'all' && filterStatuses.includes(statusFilter) ? statusFilter : 'all';
  // Arena's own edit and play dates; Saved Locally also has its local update time.
  const arenaSorts: SortKey[] = ['modified-desc', 'modified-asc', 'played-desc'];
  const sortOptions: SortKey[] = view === 'arena' ? ['name-asc', 'name-desc', ...arenaSorts] : ['name-asc', 'name-desc', 'updated-desc', 'updated-asc', ...arenaSorts];
  const activeSort = view === 'arena' ? (sortOptions.includes(arenaSort) ? arenaSort : 'modified-desc') : (sortOptions.includes(sort) ? sort : 'name-asc');
  const collectionNames = new Map((library?.collections ?? []).map((collection) => [collection.id, collection.name]));
  const shownCollection = view === 'saved' && (collectionFilter === '' || collectionNames.has(collectionFilter)) ? collectionFilter : 'all';
  const filtering = Boolean(query.trim()) || activeStatus !== 'all' || shownCollection !== 'all';
  const visible = sortDecks((library?.decks ?? []).filter((deck) =>
    Boolean(deck.trashed_at) === (view === 'trash')
    && (activeStatus === 'all' || savedStatuses(deck).includes(activeStatus))
    && (shownCollection === 'all' || (deck.collection_id ?? '') === shownCollection)
    // Saved decks also match their collection's name.
    && `${deck.name} ${deck.format_name} ${deckFormatLabel(deck.format_name)} ${deck.tags.join(' ')} ${view === 'saved' ? collectionNames.get(deck.collection_id ?? '') ?? '' : ''}`
      .toLowerCase().includes(query.toLowerCase())), activeSort);
  const shownId = selected;
  const selectedDeck = library?.decks.find((deck) => deck.id === selected);
  const activeDetail = detail?.id === shownId && (!revision || detail.revision_id === revision) ? detail : null;
  const editingRevision = modal === 'revision';
  const pageVisible = usePageVisible();
  const arenaDecks = sortDecks((native?.decks ?? []).filter((deck) => `${deck.name} ${deck.format_name} ${deckFormatLabel(deck.format_name)}`.toLowerCase().includes(query.toLowerCase())
    && (activeStatus === 'all' || arenaStatuses(deck.id).includes(activeStatus))), activeSort);
  // Arena's favorites get their own section above the rest, each in the chosen order.
  const arenaFavorites = arenaDecks.filter((deck) => deck.is_favorite);
  const arenaOthers = arenaDecks.filter((deck) => !deck.is_favorite);
  const checkedDecks = (library?.decks ?? []).filter((deck) => checked.includes(deck.id));
  const collectionGroups = [...(library?.collections ?? []), { id: '', name: 'Unsorted' }];
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
          const finished = job.result?.action ?? 'connect';
          // A backup started from an Arena deck or Compare stays open to show the cards it read.
          if (finished === 'backup' || finished === 'favorite') setModal((value) => value === 'arena-deck' || value === 'compare' ? value : null);
          else { setModal(null); setSelected(null); setRevision(undefined); }
          const count = job.result?.count ?? 0;
          const decks = `${count} deck${count === 1 ? '' : 's'}`;
          const stopped: Partial<Record<NativeDeckAction, string>> = {
            backup: `Backup stopped. ${decks} backed up before stopping; the rest were not backed up.`,
            store: `Stopped. Moved ${decks} to ${storedTo.current} and removed them from Arena; the remaining selected decks are still in Arena.`,
            restore: `Stopped. Restored ${decks} to Arena; the remaining selected decks were not restored.`,
          };
          const messages: Record<NativeDeckAction, string> = {
            connect: ARENA_LOADED_NOTICE, backup: `Backed up ${count} deck${count === 1 ? '' : 's'} to your collection.`,
            store: `Moved ${count} deck${count === 1 ? '' : 's'} to ${storedTo.current} and removed ${count === 1 ? 'it' : 'them'} from Arena. If Arena still shows ${count === 1 ? 'it' : 'them'}, leave Arena’s Decks screen and open it again.`,
            restore: `Restored ${count} deck${count === 1 ? '' : 's'} directly to Arena.`, reconcile: 'Interrupted transfers reconciled. No Arena writes were repeated.',
            add: 'Deck added directly to Arena.',
            favorite: job.result?.favorite === false ? 'Removed from your Arena favorites.' : 'Added to your Arena favorites.',
          };
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
    if (!shownId) return;
    const controller = new AbortController();
    fetchManagedDeck(shownId, revision, controller.signal).then((loaded) => {
      if (controller.signal.aborted) return;
      setDetail(loaded);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(err));
    });
    return () => controller.abort();
  }, [shownId, revision, refresh]);

  // The open Arena deck's cards, as of the last Arena read.
  const [arenaCards, setArenaCards] = useState<{ key: string; deck?: ArenaDeckCards; error?: string } | null>(null);
  const arenaCardsKey = modal === 'arena-deck' && arenaSelected ? `${arenaSelected}:${native?.refreshed_at ?? ''}` : '';
  useEffect(() => {
    if (!arenaCardsKey || !arenaSelected) return;
    const controller = new AbortController();
    fetchArenaDeck(arenaSelected, controller.signal)
      .then((deck) => { if (!controller.signal.aborted) setArenaCards({ key: arenaCardsKey, deck }); })
      .catch((err: unknown) => { if (!controller.signal.aborted) setArenaCards({ key: arenaCardsKey, error: errorMessage(err) }); });
    return () => controller.abort();
  }, [arenaCardsKey, arenaSelected]);
  const openArenaCards = arenaCards?.key === arenaCardsKey ? arenaCards : null;

  async function action(run: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await run(); } catch (err: unknown) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  async function nativeAction(kind: NativeDeckAction, ids = checked, collectionId?: string | null, trash = false) {
    if (native?.in_game) throw new Error('Finish your game first. Deck Manager can work with Arena again when it ends.');
    const decks = ids.map((id) => ({ id, ...(kind === 'restore' && activeDetail?.id === id ? { revision: activeDetail.revision_id } : {}) }));
    const job = await (trash ? startNativeDeckJob(kind, decks, collectionId, { trash })
      : collectionId === undefined ? startNativeDeckJob(kind, decks) : startNativeDeckJob(kind, decks, collectionId));
    setNativeJob(job.job_id); setNativeJobAction(kind); setNativeProgress('Contacting Arena…'); setTransferProgress(undefined);
  }

  /** Star or unstar one Arena deck, as Arena's own star button does. */
  async function toggleFavorite(deck: ArenaDeck) {
    if (native?.in_game) throw new Error('Finish your game first. Deck Manager can work with Arena again when it ends.');
    const job = await startNativeDeckJob('favorite', [{ id: deck.id, favorite: !deck.is_favorite }]);
    setNativeJob(job.job_id); setNativeJobAction('favorite'); setNativeProgress('Contacting Arena…'); setTransferProgress(undefined);
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

  function changeView(next: 'saved' | 'trash' | 'arena') { setView(next); setChecked([]); setStatusFilter('all'); setError(''); setNotice(''); }

  function filterByStatus(status: DeckStatus | 'all') { setStatusFilter(status); setChecked([]); expandAll(); }

  const clearFilters = <button type="button" className="deck-manager-link-button" onClick={() => { setQuery(''); setCollectionFilter('all'); filterByStatus('all'); }}>Clear filters</button>;

  /**
   * A tile's footer: its tracked-game record on the left, status pills on the
   * right (they wrap below when space runs out). Empty space opens the deck.
   */
  function tileFooter(statuses: DeckStatus[], record: DeckRecord | null | undefined, open: () => void) {
    return <div className="deck-manager-tile-footer" onClick={(event) => { if (!(event.target as Element).closest('button')) open(); }}>
      <DeckRecordBadge record={record} />
      {statusPills(statuses)}
    </div>;
  }

  function statusPills(statuses: DeckStatus[]) {
    return <div className="deck-manager-status-pills">{shownPills(statuses).map((status) =>
      <button type="button" key={status} className={`deck-manager-status-pill deck-manager-status-${status}`} disabled={busy}
        aria-label={`Filter by ${statusLabels[status]}`} title={`${statusHints[status] ? `${statusHints[status]}\n` : ''}Click to show ${statusLabels[status].toLowerCase()} decks.`}
        onClick={() => filterByStatus(status)}>{statusLabels[status]}</button>)}</div>;
  }

  function toggleChecked(id: string) { setChecked((value) => value.includes(id) ? value.filter((item) => item !== id) : [...value, id]); }

  function confirmRemoval() {
    setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setError(''); setNotice(''); setModal(view === 'trash' ? 'bulk-delete' : 'bulk-trash');
  }

  function closeModal() {
    setModal(null); setSelected(null); setRevision(undefined); setArenaSelected(null); setError('');
  }

  const opener = () => setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);

  /** Arena decks open like saved ones; their cards come from the saved copy. */
  function openArenaDeck(id: string) {
    opener();
    setArenaSelected(id); setSelected(null); setRevision(undefined);
    setModal('arena-deck'); setError(''); setNotice('');
  }

  /** One Arena deck's Move to collection / Move to trash use the same confirmations as a selection. */
  function confirmArenaMove(id: string, kind: 'store' | 'arena-trash') {
    setChecked([id]); setModal(kind); setError(''); setNotice('');
  }

  function openCompare() {
    opener(); setError(''); setNotice('');
    setComparing({ view: view === 'arena' ? 'arena' : 'saved', ids: checked.slice(0, 2) });
    setModal('compare');
  }

  function openHelp() { opener(); setModal('help'); }

  function backUpAll() { void action(() => nativeAction('backup', [])); }

  function captureLists() {
    void action(async () => {
      const result = await captureArenaDecks(); setRefresh((value) => value + 1);
      setNotice(`Captured ${result.captured} deck${result.captured === 1 ? '' : 's'}. ${result.note}${result.rejected ? ` ${result.rejected} malformed lists were skipped.` : ''}`);
    });
  }

  function openMoveCollection() {
    opener(); setMoveNewName(''); setError(''); setNotice(''); setModal('move-collection');
  }

  async function moveSelected() {
    let target = destination || null;
    let targetName = collectionGroups.find((group) => group.id === (target ?? ''))?.name ?? 'Unsorted';
    if (destination === NEW_COLLECTION) {
      const created = await saveDeckCollection(moveNewName);
      target = created.id; targetName = created.name; setDestination(created.id);
    }
    const result = await moveDecksToCollection(checkedDecks.map((deck) => deck.id), target);
    setChecked([]); setRefresh((value) => value + 1); expand(target ?? ''); closeModal();
    setNotice(`Moved ${result.count} deck${result.count === 1 ? '' : 's'} to ${targetName}.`);
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
    setImportToArena(view === 'arena');
    setSelected(null); setRevision(undefined); setText(''); setName(''); setFormat('');
    setError(''); setNotice(''); setModal('import');
  }

  async function saveImport() {
    if (importToArena) {
      // Arena's importer adds the list and a full copy is saved to the chosen collection.
      if (native?.in_game) throw new Error('Finish your game first. Deck Manager can work with Arena again when it ends.');
      // A name left blank is numbered past names Arena already has; a typed name is used as is.
      const job = await addDeckToArena(text, importName(name, text), format, undefined, importCollection || undefined, { renameIfTaken: !name.trim() });
      setNativeJob(job.job_id); setNativeJobAction('add'); setNativeProgress('Contacting Arena…'); setTransferProgress(undefined);
      return;
    }
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

  function openCollection(collection: DeckCollection | null = null) {
    setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setEditingCollection(collection); setCollectionName(collection?.name ?? '');
    setError(''); setNotice(''); setModal('collection');
  }

  function collectionOptions() {
    return <><option value="">Unsorted</option>{library?.collections?.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}</>;
  }

  function arenaTile(deck: ArenaDeck) {
    return (
      <div key={deck.id} className="deck-manager-tile-wrapper">
        <label className="deck-manager-tile-select" title={`Select ${deck.name}`} onClick={(event) => event.stopPropagation()}><input className="deck-manager-tile-check" type="checkbox" aria-label={`Select ${deck.name}`} checked={checked.includes(deck.id)} disabled={busy} onChange={() => toggleChecked(deck.id)} /></label>
        <button type="button" className={`deck-manager-tile deck-manager-arena-tile${deck.is_favorite ? ' deck-manager-tile-favorite' : ''}`} onClick={() => openArenaDeck(deck.id)} aria-haspopup="dialog" title={deck.is_favorite ? `${deck.name} (favorite in Arena)` : deck.name}>
          <span className="deck-manager-tile-art"><DeckVisual deckName={deck.name} visual={arenaTileArt(deck.id)} /></span>
          <span className="deck-manager-tile-text"><strong>{deck.name}</strong><small>{deckFormatLabel(deck.format_name) || 'Any format'} · {deck.main_count} cards</small><ColorPips colors={deck.colors} size={14} /></span>
        </button>
        <button type="button" className={`deck-manager-tile-favorite-toggle${deck.is_favorite ? ' is-favorite' : ''}`} aria-pressed={Boolean(deck.is_favorite)}
          aria-label={deck.is_favorite ? `Remove ${deck.name} from Arena favorites` : `Add ${deck.name} to Arena favorites`}
          title={arenaMoveBlocked || (deck.is_favorite ? 'Remove from Arena favorites' : 'Add to Arena favorites')}
          disabled={busy || Boolean(arenaMoveBlocked)} onClick={() => void action(() => toggleFavorite(deck))}>
          <Star size={18} aria-hidden="true" />
        </button>
        {tileFooter(arenaStatuses(deck.id), library?.records?.[deck.id], () => openArenaDeck(deck.id))}
      </div>
    );
  }

  /** A foldable Arena tab section; a search or filter keeps it open. */
  function arenaSection(key: string, title: string, decks: ArenaDeck[]) {
    const closed = !filtering && arenaFolded.includes(key);
    return <section className={`deck-manager-group deck-manager-arena-${key}`} key={key} aria-label={title}>
      <div className="deck-manager-group-heading deck-manager-toolbar">
        <button className="deck-manager-group-toggle" aria-label={`${title} (${decks.length})`} aria-expanded={!closed} aria-controls={`arena-${key}`} onClick={() => setArenaFolded((value) => closed ? value.filter((item) => item !== key) : [...value, key])}>
          <ChevronDown size={18} className={closed ? 'is-collapsed' : ''} />{key === 'favorites' ? <Star size={16} className="deck-manager-favorite-star" aria-hidden="true" /> : null}<strong>{title}</strong><span>({decks.length})</span>
        </button>
      </div>
      {!closed ? <div className="deck-manager-group-decks" id={`arena-${key}`}>{decks.map(arenaTile)}</div> : null}
    </section>;
  }

  function savedTile(deck: ManagedDeck) {
    return (
          <div className="deck-manager-tile-wrapper" key={deck.id}>
          <label className="deck-manager-tile-select" title={`Select ${deck.name}`} onClick={(event) => event.stopPropagation()}>
            <input className="deck-manager-tile-check" type="checkbox" aria-label={`Select ${deck.name}`} checked={checked.includes(deck.id)} disabled={busy} onChange={() => toggleChecked(deck.id)} />
          </label>
          <button key={deck.id} className="deck-manager-tile" onClick={() => choose(deck.id)} aria-haspopup="dialog" title={deck.name}>
            <span className="deck-manager-tile-art"><DeckVisual deckName={deck.name} visual={deckArt(deck)} /></span>
            <span className="deck-manager-tile-text">
              <strong>{deck.name}</strong>
              <small>{deckFormatLabel(deck.format_name) || 'Format not specified'} · {deck.main_count} cards</small>
              <ColorPips colors={deck.colors} size={14} />
              <small>Updated: <time dateTime={deck.updated_at} title={formatDateTime(deck.updated_at)}>{new Date(deck.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</time></small>
            </span>
          </button>
          {tileFooter(savedStatuses(deck), deck.record, () => choose(deck.id))}
          </div>

    );
  }


  const pendingTransfer = Boolean(native?.pending_transfers?.length);
  const arenaReadBlocked = !native?.available ? 'Deck Manager can’t connect to Arena on this computer.'
    : native.in_game ? 'Available after your game ends.'
    : pendingTransfer ? 'Reconcile the interrupted transfer first.' : '';
  const arenaMoveBlocked = arenaReadBlocked || (!native?.deck_screen_open ? 'Open Arena’s Decks screen, outside a match.' : '');
  const addToArenaBlocked = arenaReadBlocked || (native?.limit_reached === true ? 'Arena’s deck slots are full. Move a deck out first.' : '');
  const selectable = view === 'arena' ? arenaDecks.map((deck) => deck.id) : visible.map((deck) => deck.id);
  const compareBlocked = checked.length !== 2 ? 'Select two decks to compare.' : '';
  const compareButton = <button className="deck-manager-compare" disabled={busy || Boolean(compareBlocked)} title={compareBlocked || 'Show the card differences between the two selected decks.'} onClick={openCompare}><GitCompareArrows size={16} /> Compare</button>;

  function compareSide(id: string): CompareSide {
    if (comparing?.view === 'arena') {
      const deck = native?.decks.find((item) => item.id === id);
      return {
        key: id, name: deck?.name ?? 'Arena deck', colors: deck?.colors,
        summary: `${deckFormatLabel(deck?.format_name) || 'Any format'} · ${deck?.main_count ?? 0} cards`,
        art: <DeckVisual deckName={deck?.name ?? ''} visual={arenaTileArt(id)} />,
        source: deck ? { kind: 'arena', id, version: native?.refreshed_at } : null,
        record: library?.records?.[id] ?? null,
        note: native?.refreshed_at ? `In Arena · read ${new Date(native.refreshed_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}` : 'In Arena',
      };
    }
    const deck = library?.decks.find((item) => item.id === id);
    return {
      key: id, name: deck?.name ?? 'Saved deck', colors: deck?.colors,
      summary: `${deckFormatLabel(deck?.format_name) || 'Any format'} · ${deck?.main_count ?? 0} cards`,
      art: <DeckVisual deckName={deck?.name ?? ''} visual={deckArt(deck)} />,
      source: deck ? { kind: 'saved', id, version: deck.current_revision_id } : null,
      record: deck?.record ?? null,
      note: deck ? `Updated ${new Date(deck.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}` : undefined,
    };
  }
  const arenaDeck = arenaSelected ? native?.decks.find((deck) => deck.id === arenaSelected) : undefined;

  const deckCount = (count: number) => `${count} deck${count === 1 ? '' : 's'}`;
  function modalTitle() {
    if (modal === 'arena-deck') return arenaDeck?.name ?? 'Arena deck';
    if (modal === 'compare') return 'Compare decks';
    if (modal === 'help') return 'How Deck Manager works';
    if (modal === 'move-collection') return `Move ${deckCount(checkedDecks.length)} to a collection`;
    if (modal === 'arena-trash') return `Move ${deckCount(checked.length)} to Trash?`;
    if (modal === 'import' && importToArena) return 'Add a deck to Arena';
    return modal === 'stop-job' ? nativeJobAction === 'backup' ? 'Stop backing up Arena decks?' : 'Stop the transfer?' : modal === 'collection' ? editingCollection ? 'Rename collection' : 'New collection' : modal === 'remove-collection' ? `Remove ${editingCollection?.name} collection?` : modal === 'bulk-trash' ? `Move ${checkedDecks.length} decks to Trash?` : modal === 'bulk-delete' ? `Permanently delete ${checkedDecks.length} decks?` : modal === 'store' ? `Move ${checked.length} deck${checked.length === 1 ? '' : 's'} out of Arena?` : modal === 'trash' ? `Move ${activeDetail?.name ?? selectedDeck?.name ?? 'saved deck'} to Trash?` : modal === 'delete' ? `Delete ${activeDetail?.name ?? selectedDeck?.name ?? 'saved deck'}?` : modal === 'deck' ? activeDetail?.name ?? selectedDeck?.name ?? 'Saved deck' : editingRevision ? 'Save a new revision' : 'Add a deck';
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
            <Archive size={16} /> Saved Locally ({library?.decks.filter((d) => !d.trashed_at).length ?? 0})
          </button>
          <button aria-pressed={view === 'arena'} disabled={busy} onClick={() => changeView('arena')}><FolderOpen size={16} /> Arena{native?.connected ? ` (${native.decks.length})` : ''}</button>
          <button aria-pressed={view === 'trash'} disabled={busy} onClick={() => changeView('trash')}><Trash2 size={16} /> Trash</button>
        </div>
        <div className="deck-manager-toolbar deck-manager-collection-actions">
          {nativeJob && nativeJobAction && STOPPABLE.includes(nativeJobAction) ? <button className="deck-manager-delete" disabled={stopRequested} onClick={() => { setModalOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null); setModal('stop-job'); }}><Square size={16} />{stopRequested ? 'Stopping…' : nativeJobAction === 'backup' ? 'Stop backup' : 'Stop transfer'}</button> : null}
          <ArenaStatusChip native={native} running={Boolean(nativeProgress)} />
          {native?.available ? native.connected
            ? <button className="deck-manager-rescan" disabled={busy || native.in_game} title={native.in_game ? 'Available after your game ends.' : 'Reads your decks from Arena again, to pick up changes made in Arena. Arena must be on its Decks screen, outside a match.'} onClick={() => void action(() => nativeAction('connect', []))}><RefreshCw size={16} />{loadLabel(native)}</button>
            : <button className="deck-manager-load-arena" disabled={busy || native.in_game} title="Start here: reads the decks in Arena. Open Arena to its Decks screen (not in a match) first." onClick={() => void action(() => nativeAction('connect', []))}><RefreshCw size={16} />{loadLabel(native)}</button>
            : null}
          {native?.available
            ? native.connected ? <button aria-label="Back up all Arena decks" disabled={busy || Boolean(arenaReadBlocked)} title={arenaReadBlocked || 'Saves exact copies of every Arena deck to your collection. Arena is only read.'} onClick={backUpAll}><Archive size={16} /> Back up all</button> : null
            : <button disabled={busy} title="Back up decklists available in Arena’s log" onClick={captureLists}><RefreshCw size={16} /> Capture Arena lists</button>}
          <button className="deck-manager-icon-button" aria-label="How Deck Manager works" title="How Deck Manager works" onClick={openHelp}><CircleHelp size={16} /></button>
        </div>
      </div>
      <DeckManagerStatus native={native} jobAction={nativeJobAction} jobDetail={nativeProgress} progress={transferProgress}
        error={error} notice={notice} showMessages={!modal} busy={busy}
        onReconcile={() => void action(() => nativeAction('reconcile', []))} onDismiss={() => { setError(''); setNotice(''); }} />
      <div className={`deck-manager-toolbar deck-manager-bar${checked.length ? ' deck-manager-bar-selecting' : ''}`} role="toolbar" aria-label={checked.length ? 'Selected decks' : 'Find and add decks'}>
        {checked.length ? <>
          <button type="button" className="deck-manager-icon-button deck-manager-clear" aria-label="Select none" title="Select none" disabled={busy} onClick={() => setChecked([])}><X size={16} /></button>
          <strong className="deck-manager-selected-count">{checked.length} selected</strong>
          {selectable.some((id) => !checked.includes(id)) ? <button type="button" className="deck-manager-select-button" disabled={busy} onClick={() => setChecked(selectable)}>Select all</button> : null}
          <span className="deck-manager-action-divider" aria-hidden="true" />
          <div className="deck-manager-bar-actions">
            {view === 'saved' ? <>
              <button disabled={busy || !checkedDecks.length} onClick={openMoveCollection}><FolderInput size={16} /> Move to collection</button>
              {native?.available ? <button className="deck-manager-copy" aria-label="Restore selected to Arena" title={!canRestoreSelection ? 'Select native backups that are not already in Arena to restore.' : undefined} disabled={busy || !canRestoreSelection || !native.connected || !native.deck_screen_open || native.limit_reached !== false || pendingTransfer} onClick={() => void action(() => nativeAction('restore'))}><ArrowUpFromLine size={16} /> Restore to Arena</button> : null}
              {compareButton}
              <button className="deck-manager-delete" aria-label="Move selected to trash" disabled={busy || !checkedDecks.length} onClick={confirmRemoval}><Trash2 size={16} /> Move to trash</button>
            </> : view === 'arena' ? <>
              <button disabled={busy || Boolean(arenaMoveBlocked)} title={arenaMoveBlocked || 'Saves full copies of the selected decks to your collection. Arena is only read.'} onClick={() => void action(() => nativeAction('backup', checked))}><Archive size={16} /> Back up</button>
              <button disabled={busy || Boolean(arenaMoveBlocked)} title={arenaMoveBlocked || undefined} onClick={() => { opener(); setModal('store'); }}><FolderInput size={16} /> Move to collection</button>
              {compareButton}
              <button className="deck-manager-delete" aria-label="Move selected to trash" disabled={busy || Boolean(arenaMoveBlocked)} title={arenaMoveBlocked || 'Backs up the selected decks, removes them from Arena and puts the backups in Trash.'} onClick={() => { opener(); setModal('arena-trash'); }}><Trash2 size={16} /> Move to trash</button>
            </> : <button className="deck-manager-delete" aria-label="Delete selected permanently" disabled={busy || !checkedDecks.length} onClick={confirmRemoval}><Trash2 size={16} /> Delete permanently</button>}
          </div>
        </> : <>
          <label className="deck-manager-search-field">
            <Search size={16} aria-hidden="true" />
        <input type="search" aria-label="Search saved decks" placeholder={view === 'saved' ? 'Search deck names, tags, collections…' : view === 'arena' ? 'Search deck names or formats' : 'Search deck names, formats or tags'} value={query} disabled={busy} onChange={(e) => { setQuery(e.target.value); setChecked([]); expandAll(); }} />
          </label>
        <select className="deck-manager-status-filter" aria-label="Filter decks by status" value={activeStatus} disabled={busy} onChange={(e) => filterByStatus(e.target.value as DeckStatus | 'all')}>
          <option value="all">All statuses</option>
          {[{ label: 'Location', statuses: ['arena', 'collection'] }, { label: view === 'arena' ? 'Backup' : 'Saved as', statuses: ['native', 'list', 'backed', 'unbacked'] }].map((group) => {
            const options = filterStatuses.filter((status) => group.statuses.includes(status));
            return options.length ? <optgroup key={group.label} label={group.label}>{options.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}</optgroup> : null;
          })}
        </select>
        {view === 'saved' && library?.collections?.length ? (
          <select className="deck-manager-status-filter" aria-label="Show collection" value={shownCollection} disabled={busy} onChange={(e) => {
            const next = e.target.value; setCollectionFilter(next); setChecked([]); if (next !== 'all') expand(next);
          }}>
            <option value="all">All collections</option>
            {library.collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
            <option value="">Unsorted</option>
          </select>
        ) : null}
        <select className="deck-manager-status-filter deck-manager-sort" aria-label="Sort decks" value={activeSort} disabled={busy} onChange={(e) => {
          const next = e.target.value as SortKey;
          if (view === 'arena') setArenaSort(next); else setSort(next);
          try { localStorage.setItem(view === 'arena' ? ARENA_SORT_KEY : SORT_KEY, next); } catch { /* Preference only. */ }
        }}>
          {sortOptions.map((key) => <option key={key} value={key}>{(view === 'arena' && arenaSortLabels[key]) || sortLabels[key]}</option>)}
        </select>
          <div className="deck-manager-bar-actions">
            {view === 'saved' ? <>
              <button disabled={busy} onClick={() => openCollection()}><FolderOpen size={16} /> New collection</button>
              <button className="deck-manager-add" disabled={busy} onClick={openImport}><Plus size={18} /> Add deck</button>
            </> : view === 'arena' ? <>
              <button className="deck-manager-add" disabled={busy || Boolean(addToArenaBlocked)} title={addToArenaBlocked || 'Paste a decklist to add it to Arena. A copy is saved to your collection.'} onClick={openImport}><Plus size={18} /> Add deck</button>
            </> : null}
          </div>
        </>}
      </div>
      <div className={`deck-manager-decks${view === 'saved' || (view === 'arena' && arenaFavorites.length) ? ' deck-manager-collections-grid' : ''}`}>
        {view === 'arena' ? (arenaFavorites.length ? [
          arenaSection('favorites', 'Favorites', arenaFavorites),
          arenaOthers.length ? arenaSection('others', 'My Decks', arenaOthers) : null,
        ] : arenaDecks.map(arenaTile)) : (view === 'trash' ? visible.map(savedTile) : collectionGroups.map((group) => {
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
            {!closed ? <div className="deck-manager-group-decks" id={`collection-${group.id || 'unsorted'}`}>{decks.map(savedTile)}{!decks.length ? <p className="deck-manager-group-empty">No decks yet. Select decks and use Move to collection to add them here.</p> : null}</div> : null}
          </section>;
        }))}
      </div>
      {view === 'arena' && !arenaDecks.length ? <p className="empty-state">{!native?.connected ? `Arena decks aren’t loaded yet. Click ${loadLabel(native)} at the top right.` : filtering ? <>No Arena decks match your search or status filter. {clearFilters}</> : 'Arena reported no decks.'}</p> : null}
      {view !== 'arena' && (!library ? <p className="empty-state" role="status">Loading your collection…</p> : !visible.length ? (
        <p className="empty-state">{filtering ? <>No {view === 'trash' ? 'decks in Trash' : 'saved decks'} match your search or status filter. {clearFilters}</> : view === 'trash' ? 'No decks in trash.' : 'Add your first deck, or back up your Arena decks.'}</p>
      ) : null)}

      {modal ? (
        <DeckModal key={modal} title={modalTitle()} busy={modal === 'stop-job' ? false : busy} onClose={modal === 'trash' ? cancelTrash : modal === 'stop-job' ? () => setModal(null) : closeModal} returnFocus={modalOpener}
          wide={modal === 'deck' || modal === 'arena-deck' || modal === 'compare'}
          headerActions={modal === 'arena-deck' && openArenaCards?.deck ? <>
            <button disabled={busy} title="Copy this list in MTG Arena import format" onClick={() => void action(async () => {
              await navigator.clipboard.writeText(arenaListText(openArenaCards.deck!.cards)); setNotice('Deck list copied.');
            })}><Copy size={16} /> Copy deck list</button>
            <BuyPaperButton className="deck-manager-buy-paper" disabled={!openArenaCards.deck.cards.length} onOpen={setBuyingOpener} />
          </> : modal === 'deck' && activeDetail ? <>
            <button disabled={busy} title="Copy this list in MTG Arena import format" onClick={() => void action(() => exportDeck(false))}><Copy size={16} /> Copy deck list</button>
            <BuyPaperButton className="deck-manager-buy-paper" disabled={!activeDetail.deck.cards.length} onOpen={setBuyingOpener} />
            {native?.available && !activeDetail.trashed_at && !inArena(activeDetail) ? activeDetail.native_restorable
              ? <button className="deck-manager-copy" disabled={busy || !native.connected || !native.deck_screen_open || native.limit_reached !== false || Boolean(native.pending_transfers?.length)} onClick={() => void action(() => nativeAction('restore', [activeDetail.id]))}><ArrowUpFromLine size={16} /> Restore to Arena</button>
              : <button className="deck-manager-copy" disabled={busy || native.in_game || native.limit_reached === true || Boolean(native.pending_transfers?.length)} title="Adds this list with Arena’s importer. Arena must be on Decks outside a match." onClick={() => void action(() => addSavedToArena(activeDetail))}><ArrowUpFromLine size={16} /> Add to Arena</button>
              : null}
          </> : null}>
          {feedback}
          {modal === 'help' ? HELP : modal === 'arena-deck' ? arenaDeck ? (
            <ArenaDeckDetail deck={arenaDeck} record={library?.records?.[arenaDeck.id] ?? null} copy={arenaCopy(arenaDeck.id)} cards={openArenaCards?.deck ?? null} error={openArenaCards?.error ?? ''} busy={busy}
              statusPills={<div className="deck-manager-status-pills">{shownPills(arenaStatuses(arenaDeck.id)).map((status) => <span key={status} title={statusHints[status]} className={`deck-manager-status-pill deck-manager-status-${status}`}>{statusLabels[status]}</span>)}</div>}
              arenaBlocked={arenaMoveBlocked}
              onBackup={() => void action(() => nativeAction('backup', [arenaDeck.id]))}
              onMove={() => confirmArenaMove(arenaDeck.id, 'store')}
              onTrash={() => confirmArenaMove(arenaDeck.id, 'arena-trash')}
              onFavorite={() => void action(() => toggleFavorite(arenaDeck))} />
          ) : <p className="empty-state">Arena no longer lists this deck. Click {loadLabel(native)} to read Arena again.</p>
          : modal === 'compare' && comparing ? (
            <DeckCompare key={comparing.ids.join(':')} sides={[compareSide(comparing.ids[0]), compareSide(comparing.ids[1])]} />
          ) : modal === 'move-collection' ? <form className="deck-manager-delete-confirmation" onSubmit={(event) => { event.preventDefault(); void action(moveSelected); }}>
            <ul className="deck-manager-confirmation-list" aria-label="Decks to move">{checkedDecks.map((deck) => <li key={deck.id}><strong>{deck.name}</strong><small>{collectionGroups.find((group) => group.id === (deck.collection_id ?? ''))?.name ?? 'Unsorted'}</small></li>)}</ul>
            <label className="deck-manager-store-target">Move to<select autoFocus value={destination} disabled={busy} onChange={(event) => setDestination(event.target.value)}>{collectionOptions()}<option value={NEW_COLLECTION}>New collection…</option></select></label>
            {destination === NEW_COLLECTION ? <label className="deck-manager-store-target">New collection name<input value={moveNewName} maxLength={80} autoFocus disabled={busy} onChange={(event) => setMoveNewName(event.target.value)} /></label> : null}
            <div className="deck-manager-toolbar"><button type="button" disabled={busy} onClick={closeModal}>Cancel</button><button type="submit" className="deck-manager-add" disabled={busy || !checkedDecks.length || (destination === NEW_COLLECTION && !moveNewName.trim())}><FolderInput size={16} />{busy ? 'Moving…' : `Move ${deckCount(checkedDecks.length)}`}</button></div>
          </form> : modal === 'arena-trash' ? <div className="deck-manager-delete-confirmation">
            <p>These decks will be <strong>deleted from Arena</strong> to free deck slots. Each one is backed up and checked first, and the backup goes to Trash. From Trash you can restore a deck to your collection and then to Arena, or delete it for good. Your cards stay in your Arena collection.</p>
            <ul className="deck-manager-confirmation-list" aria-label="Decks to move to Trash">{(native?.decks ?? []).filter((d) => checked.includes(d.id)).map((d) => <li key={d.id}>{d.name}</li>)}</ul>
            <p className="deck-manager-store-note">Arena may keep showing these decks until you leave its Decks screen and open it again.</p>
            <div className="deck-manager-toolbar"><button disabled={busy} onClick={closeModal}>Cancel</button><button className="deck-manager-delete" disabled={busy || Boolean(nativeJob) || !checked.length} onClick={() => void action(async () => { storedTo.current = 'Trash'; await nativeAction('store', checked, undefined, true); })}><Trash2 size={16} />{busy || nativeJob ? 'Moving…' : 'Move to trash'}</button></div>
          </div> : modal === 'stop-job' ? <div className="deck-manager-delete-confirmation">
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
            <DeckDetail key={`${activeDetail.id}:${activeDetail.revision_id}`} detail={activeDetail} record={library?.decks.find((deck) => deck.id === activeDetail.id)?.record ?? null} busy={busy} collections={library?.collections ?? []}
              statusPills={<div className="deck-manager-status-pills">{shownPills(savedStatuses(activeDetail)).map((status) => <span key={status} title={statusHints[status]} className={`deck-manager-status-pill deck-manager-status-${status}`}>{statusLabels[status]}</span>)}</div>}
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
              <p className="deck-manager-description">{importToArena
                ? 'Paste an Arena decklist. Arena’s importer adds it, and a full copy is saved to your collection. Keep Arena on its Decks screen with a free deck slot.'
                : `Paste an Arena decklist or open a .txt or .tappsdeck backup.${editingRevision ? ' Earlier revisions are retained.' : ''}`}</p>
              <div className="deck-manager-fields">
                <label>Deck name<input value={name} onChange={(e) => setName(e.target.value)} placeholder={importToArena ? DEFAULT_IMPORT_NAME : 'Use the name in the decklist'} maxLength={256} /></label>
                <label>Format<select value={format} onChange={(e) => setFormat(e.target.value)}>
                  <option value="">Not specified</option>
                  {/* An existing revision keeps a format outside the list, such as one typed earlier. */}
                  {[...DECK_FORMATS, ...(format && !(DECK_FORMATS as readonly string[]).includes(format) ? [format] : [])].map((value) => <option key={value} value={value}>{deckFormatLabel(value)}</option>)}
                </select></label>
              </div>
              {!editingRevision ? <label>{importToArena ? 'Save a copy in' : 'Collection'}<select value={importCollection} disabled={busy} onChange={(event) => setImportCollection(event.target.value)}>{collectionOptions()}</select></label> : null}
              <label>Decklist or backup<textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} required spellCheck={false} /></label>
              <input ref={fileInput} type="file" accept={importToArena ? '.txt' : '.txt,.tappsdeck,.json'} className="deck-manager-file" aria-label="Open deck backup file" onChange={(event) => {
                const file = event.target.files?.[0]; if (!file) return;
                void action(async () => { if (file.size > 2_000_000) throw new Error('Deck file is too large.'); setText(await file.text()); setNotice(`${file.name} is ready to save.`); });
                event.target.value = '';
              }} />
              <div className="deck-manager-toolbar deck-manager-import-actions">
                <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}><FolderOpen size={16} /> Open file</button>
                {importToArena
                  ? <button className="deck-manager-add" type="submit" disabled={busy || !text.trim() || Boolean(addToArenaBlocked)} title={addToArenaBlocked || undefined}><ArrowUpFromLine size={16} />{busy ? 'Adding…' : 'Add to Arena'}</button>
                  : <button className="deck-manager-add" type="submit" disabled={busy || !text.trim()}><Archive size={16} />{busy ? 'Working…' : editingRevision ? 'Save revision' : 'Save deck'}</button>}
                <button type="button" disabled={busy} onClick={() => {
                  if (editingRevision) { setModal('deck'); setError(''); setNotice(''); } else closeModal();
                }}>{editingRevision ? 'Cancel revision' : 'Cancel'}</button>
              </div>
            </form>
          )}
        </DeckModal>
      ) : null}
      {buyingOpener && ((modal === 'deck' && activeDetail) || (modal === 'arena-deck' && openArenaCards?.deck)) ? (
        <BuyPaperDialog sections={managedDeckSections(modal === 'arena-deck' ? { deck: openArenaCards!.deck! } : activeDetail!)}
          onClose={() => setBuyingOpener(null)} returnFocus={buyingOpener} />
      ) : null}
    </section>
  );
}
