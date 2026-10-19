import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Archive, Check, Copy, Dices, ExternalLink, FolderOpen, Info, Layers, Plus, RefreshCw, Search } from 'lucide-react';
import { fetchDeckLibrary, type DeckCollection, type NativeDeckJob, importManagedDeck, addDeckToArena, fetchNativeDeckStatus, fetchNativeDeckJob, type NativeDeckStatus } from '../deckManagerApi';
import { usePageVisible } from '../usePageVisible';
import { DeckTransferProgress } from './DeckTransferProgress';
import { DeckModal } from './DeckModal';
import { exportedDeckName } from '../deckFinderName';
import {
  fetchDeckFinderJob,
  fetchDeckFinderProviders,
  fetchDeckFinderSources,
  hydrateDeckFinderDeck,
  startDeckFinderFetch,
  startDeckFinderSurprise,
  startDeckFinderVariants,
  type DeckFinderDeck,
  type DeckFinderProvider,
  type DeckFinderResults,
  type DeckFinderSource,
} from '../api';
import { Section } from './Section';
import { SortableTable, type Column } from './SortableTable';
import { parseDeckFinderImport } from '../deckFinderImport';
import { DeckFinderDeckList } from './DeckFinderDeckList';
import { BuyPaperButton, BuyPaperDialog } from './BuyPaperDialog';

const JOB_POLL_MS = 700;
/** Arena status refresh while a deck is open; Add to Arena re-checks everything when clicked. */
const NATIVE_STATUS_MS = 10_000;
const JOB_TIMEOUT_MS = 120_000;

const SITE_SUBTITLES: Record<string, string> = {
  aetherhub: 'Meta & creators',
  magic_gg: 'Tournaments',
  moxfield: 'Creators',
  mtgo: 'Events',
  tcgplayer: 'Decks & creators',
  untapped: 'Arena meta',
  youtube: 'Creators',
};

function addBlockedReason(status: NativeDeckStatus): string | null {
  if (status.in_game) return 'Add to Arena is paused while you are in a game.';
  if (status.pending_transfers?.length) return 'Add to Arena is paused until an interrupted transfer is reconciled in Deck Manager.';
  if (status.busy) return 'Add to Arena is waiting for another Arena deck operation to finish.';
  if (status.limit_reached === true) return 'Arena’s deck slots are full. Move a deck to your collection first.';
  return null;
}

/** Arena wasn't on Decks: the fix is in Arena, so Deck Manager has nothing to offer. */
function needsDecksScreen(message: string) {
  return message.includes('Decks screen');
}

const SITE_ICONS: Record<string, string> = {
  aetherhub: 'aetherhub.png', magic_gg: 'magic.svg', moxfield: 'moxfield.ico',
  mtgo: 'mtgo.ico', tcgplayer: 'tcgplayer.ico', untapped: 'untapped.ico', youtube: 'youtube.svg',
};

/** Port of the terminal app's Arena import formatting: blank line before
    section headers (Sideboard, Companion, Commander) so Arena accepts it. */
function formatArenaImportText(deckText: string | null | undefined): string | null {
  if (!deckText) {
    return null;
  }
  const sectionHeaders = new Set(['sideboard', 'companion', 'commander', 'maybeboard']);
  const formatted: string[] = [];
  for (const line of deckText.split('\n')) {
    const stripped = line.trim();
    if (sectionHeaders.has(stripped.toLowerCase())) {
      if (formatted.length > 0 && formatted[formatted.length - 1].trim()) {
        formatted.push('');
      }
      formatted.push(stripped);
      continue;
    }
    formatted.push(line.replace(/\s+$/u, ''));
  }
  return formatted.join('\n').replace(/^\n+|\n+$/gu, '');
}

async function waitForJob(jobId: string) {
  const deadline = Date.now() + JOB_TIMEOUT_MS;
  for (;;) {
    const status = await fetchDeckFinderJob(jobId);
    if (status.status === 'done') {
      return status;
    }
    if (status.status === 'error') {
      throw new Error(status.error ?? 'Deck Finder job failed');
    }
    if (status.status === 'unknown' || Date.now() > deadline) {
      throw new Error('Deck Finder job timed out');
    }
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
  }
}

const FORMAT_CHIP_LABELS: Record<string, string> = {
  bo1: 'BO1',
  bo3: 'BO3',
  any: 'Any',
};

const FORMAT_LONG_LABELS: Record<string, string> = {
  bo1: 'Best of 1 (Bo1)',
  bo3: 'Best of 3 (Bo3)',
  any: 'Any Format',
};

interface FetchArgs {
  format: string;
  sourceUrl: string;
  sourceName: string;
}

export function DeckFinderPage() {
  const [providers, setProviders] = useState<DeckFinderProvider[] | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [provider, setProvider] = useState<DeckFinderProvider | null>(null);
  const [format, setFormat] = useState('any');
  const [sources, setSources] = useState<DeckFinderSource[]>([]);
  const [sourcesLoaded, setSourcesLoaded] = useState(false);
  const [results, setResults] = useState<DeckFinderResults | null>(null);
  const [variantsParent, setVariantsParent] = useState<DeckFinderDeck | null>(null);
  const [busyNote, setBusyNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDeck, setSelectedDeck] = useState<DeckFinderDeck | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle');
  const [savedDeckId, setSavedDeckId] = useState<{ id: string; source: string; collection: string } | null>(null);
  const [saveError, setSaveError] = useState<{ message: string; source: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [collections, setCollections] = useState<DeckCollection[]>([]);
  const [pickingCollection, setPickingCollection] = useState<HTMLElement | null>(null);
  const [buyingOpener, setBuyingOpener] = useState<HTMLElement | null>(null);
  const [collectionQuery, setCollectionQuery] = useState('');
  const [transferProgress, setTransferProgress] = useState<NativeDeckJob['progress']>();
  const collectionsLoaded = useRef(false);
  useEffect(() => {
    // The whole saved library comes back with the collections, so it is only
    // read once someone opens the collection picker.
    if (!pickingCollection || collectionsLoaded.current) return;
    const controller = new AbortController();
    fetchDeckLibrary(controller.signal).then((library) => {
      if (controller.signal.aborted) return;
      collectionsLoaded.current = true;
      setCollections(library.collections ?? []);
    }).catch(() => {});
    return () => controller.abort();
  }, [pickingCollection]);
  const [nativeStatus, setNativeStatus] = useState<NativeDeckStatus | null>(null);
  const [arenaJob, setArenaJob] = useState<{ id: string; source: string } | null>(null);
  const [arenaFeedback, setArenaFeedback] = useState<{ source: string; message: string; error: boolean } | null>(null);
  const [adding, setAdding] = useState(false);
  const [addedSource, setAddedSource] = useState<string | null>(null);
  const [nativeRefresh, setNativeRefresh] = useState(0);
  const requestSeq = useRef(0);
  const deckRequestSeq = useRef(0);
  // What produced the current results — reused by Refresh, variants context,
  // and "back to results" after a variants drill-down.
  const [lastFetch, setLastFetch] = useState<FetchArgs | null>(null);

  const pageVisible = usePageVisible();
  const showingDeck = selectedDeck !== null;
  useEffect(() => {
    // Arena's status only gates the Add to Arena button, so it is read while a
    // deck is open in a visible tab, and again at once when either returns.
    if (!pageVisible || !showingDeck) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const status = await fetchNativeDeckStatus(controller.signal);
        if (!controller.signal.aborted) setNativeStatus(status);
      } catch { /* Provider browsing and clipboard export remain available. */ }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), NATIVE_STATUS_MS);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [nativeRefresh, pageVisible, showingDeck]);

  useEffect(() => {
    if (!arenaJob) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const job = await fetchNativeDeckJob(arenaJob!.id, controller.signal);
        if (controller.signal.aborted) return;
        setTransferProgress(job.progress);
        setArenaFeedback({ source: arenaJob!.source, message: job.state === 'done' ? 'Deck added to Arena and backed up in your collection.' : job.detail, error: job.state === 'error' });
        if (job.state === 'running') { timer = setTimeout(() => void poll(), JOB_POLL_MS); return; }
        if (job.state === 'done') setAddedSource(arenaJob!.source);
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        setArenaFeedback({ source: arenaJob!.source, message: error instanceof Error ? error.message : 'Check Deck Manager before retrying this transfer.', error: true });
      }
      setArenaJob(null); setAdding(false); setNativeRefresh((value) => value + 1);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [arenaJob]);

  async function addSelectedDeck() {
    if (!selectedDeck?.deck_text || adding || nativeStatus?.in_game) return;
    const source = selectedDeck.source_url + selectedDeck.name;
    setAdding(true); setArenaFeedback(null);
    try {
      const args = [formatArenaImportText(selectedDeck.deck_text) || '', exportedDeckName(selectedDeck.deck_text, selectedDeck.name), selectedDeck.format_label || ''] as const;
      const saved = savedDeckId?.source === source ? savedDeckId : null;
      // A saved deck keeps its collection; an unsaved one is backed up in Unsorted.
      const result = saved?.collection ? await addDeckToArena(...args, saved.id, saved.collection) : saved ? await addDeckToArena(...args, saved.id) : await addDeckToArena(...args);
      setArenaJob({ id: result.job_id, source });
    } catch (error: unknown) {
      setAdding(false);
      setArenaFeedback({ source, message: error instanceof Error ? error.message : 'Could not add this deck to Arena.', error: true });
    }
  }

  function saveSelectedDeck(collection: string) {
    if (!selectedDeck?.deck_text) return;
    const source = selectedDeck.source_url + selectedDeck.name;
    setPickingCollection(null); setSaving(true); setSaveError(null);
    void importManagedDeck(formatArenaImportText(selectedDeck.deck_text) || '', exportedDeckName(selectedDeck.deck_text, selectedDeck.name), selectedDeck.format_label || '', savedDeckId?.source === source ? savedDeckId.id : undefined, collection || null)
      .then((saved) => setSavedDeckId({ id: saved.id, source, collection }))
      .catch((error: unknown) => setSaveError({ message: error instanceof Error ? error.message : 'Could not save this deck.', source }))
      .finally(() => setSaving(false));
  }

  useEffect(() => {
    let cancelled = false;
    fetchDeckFinderProviders()
      .then((loaded) => {
        if (!cancelled) {
          setProviders(loaded);
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setProvidersError(exc instanceof Error ? exc.message : 'Deck Finder failed to load');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const beginRequest = useCallback(() => {
    requestSeq.current += 1;
    deckRequestSeq.current += 1;
    setHydrating(false);
    setError(null);
    return requestSeq.current;
  }, []);

  const openDeck = useCallback(
    async (deck: DeckFinderDeck, deckProvider = provider) => {
      const seq = ++deckRequestSeq.current;
      setCopyStatus('idle');
      setSelectedDeck(deck);
      if (deck.deck_text || !deckProvider) {
        setHydrating(false);
        return;
      }
      setHydrating(true);
      try {
        const hydrated = await hydrateDeckFinderDeck(deckProvider.key, deck);
        if (deckRequestSeq.current === seq) setSelectedDeck(hydrated);
      } catch {
        // Keep the source link available when a deck cannot be hydrated.
      } finally {
        if (deckRequestSeq.current === seq) setHydrating(false);
      }
    },
    [provider],
  );

  const runFetch = useCallback(
    async (nextProvider: DeckFinderProvider, args: FetchArgs, refresh = false) => {
      const seq = beginRequest();
      setLastFetch(args);
      setBusyNote(
        nextProvider.key === 'youtube'
          ? 'Checking the latest 15 YouTube videos for decklists…'
          : `Fetching decks from ${nextProvider.display_name}…`,
      );
      if (!(refresh && nextProvider.key === 'youtube')) {
        setResults(null);
      }
      setVariantsParent(null);
      setSelectedDeck(null);
      try {
        const started = await startDeckFinderFetch({
          provider: nextProvider.key,
          format: args.format,
          source_url: args.sourceUrl || undefined,
          source_name: args.sourceName || undefined,
          refresh,
        });
        let decks = started.decks;
        let view = started.view;
        if (!started.done && started.job) {
          const finished = await waitForJob(started.job);
          decks = finished.decks;
          view = finished.view;
        }
        if (requestSeq.current === seq && decks && view) {
          setResults({ decks, view });
          if (view.selection_action === 'details' && decks[0]) {
            void openDeck(decks[0], nextProvider);
          }
        }
      } catch (exc: unknown) {
        if (requestSeq.current === seq) {
          setError(exc instanceof Error ? exc.message : 'Deck fetch failed');
        }
      } finally {
        if (requestSeq.current === seq) {
          setBusyNote(null);
        }
      }
    },
    [beginRequest, openDeck],
  );

  const loadSources = useCallback(
    async (nextProvider: DeckFinderProvider, nextFormat: string) => {
      const seq = beginRequest();
      setSources([]);
      setSourcesLoaded(false);
      setResults(null);
      setVariantsParent(null);
      setSelectedDeck(null);
      // A fresh site/format means no source pill is "current" any more —
      // lastFetch also drives which pill stays lit.
      setLastFetch(null);
      if (!nextProvider.uses_source_picker) {
        void runFetch(nextProvider, { format: nextFormat, sourceUrl: '', sourceName: '' });
        return;
      }
      try {
        const loaded = await fetchDeckFinderSources(nextProvider.key, nextFormat);
        if (requestSeq.current === seq) {
          setSources(loaded);
          setSourcesLoaded(true);
          if (loaded.length === 1) {
            // Only one source matches this filter — use it automatically,
            // like the terminal app does.
            void runFetch(nextProvider, {
              format: nextFormat,
              sourceUrl: loaded[0].url,
              sourceName: loaded[0].name,
            });
          }
        }
      } catch (exc: unknown) {
        if (requestSeq.current === seq) {
          setError(exc instanceof Error ? exc.message : 'Failed to load sources');
        }
      }
    },
    [beginRequest, runFetch],
  );

  const runVariants = useCallback(
    async (parent: DeckFinderDeck) => {
      if (!provider) {
        return;
      }
      const seq = beginRequest();
      setBusyNote(`Loading ${parent.name}…`);
      // Clear the old table right away — keeping it up while the variants
      // load makes the page look stale.
      setResults(null);
      setSelectedDeck(null);
      try {
        const started = await startDeckFinderVariants({
          provider: provider.key,
          format: lastFetch?.format ?? format,
          deck: parent,
          source_name: lastFetch?.sourceName || undefined,
        });
        const finished = await waitForJob(started.job);
        if (requestSeq.current === seq && finished.decks && finished.view) {
          setResults({ decks: finished.decks, view: finished.view });
          setVariantsParent(parent);
          setSelectedDeck(null);
          if (finished.view.selection_action === 'details' && finished.decks[0]) {
            void openDeck(finished.decks[0]);
          }
        }
      } catch (exc: unknown) {
        if (requestSeq.current === seq) {
          setError(exc instanceof Error ? exc.message : 'Variants fetch failed');
        }
      } finally {
        if (requestSeq.current === seq) {
          setBusyNote(null);
        }
      }
    },
    [beginRequest, format, lastFetch, openDeck, provider],
  );

  const runSurprise = useCallback(async () => {
    const seq = beginRequest();
    setBusyNote('Finding you a surprise deck…');
    try {
      const started = await startDeckFinderSurprise('any');
      const finished = await waitForJob(started.job);
      if (requestSeq.current === seq && finished.deck) {
        setResults(null);
        setVariantsParent(null);
        setSelectedDeck(finished.deck);
      }
    } catch (exc: unknown) {
      if (requestSeq.current === seq) {
        setError(exc instanceof Error ? exc.message : 'Surprise fetch failed');
      }
    } finally {
      if (requestSeq.current === seq) {
        setBusyNote(null);
      }
    }
  }, [beginRequest]);

  async function copyDeck(deck: DeckFinderDeck) {
    const text = formatArenaImportText(deck.deck_text);
    if (!text) {
      setCopyStatus('error');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus('copied');
      window.setTimeout(() => setCopyStatus('idle'), 1800);
    } catch {
      setCopyStatus('error');
    }
  }

  function selectProvider(next: DeckFinderProvider) {
    setProvider(next);
    // Keep the current format when the new site supports it; otherwise the
    // site's first real format (BO1 before BO3), or Any as the fallback.
    const nextFormat = next.format_options.includes(format)
      ? format
      : (next.format_options[0] ?? 'any');
    setFormat(nextFormat);
    void loadSources(next, nextFormat);
  }

  function selectFormat(nextFormat: string) {
    setFormat(nextFormat);
    if (provider) {
      void loadSources(provider, nextFormat);
    }
  }

  const metadataColumns = (results?.view.columns ?? []).filter((column) =>
    !['index', 'name', 'win_rate', 'matches', 'placing'].includes(column.key),
  );
  const deckColumns: Column<DeckFinderDeck>[] = (results?.view.columns ?? [])
    .filter((column) => ['index', 'name', 'win_rate', 'matches', 'placing'].includes(column.key))
    .map((column) => ({
      // Column identity is the server-provided table-spec key, not a DeckEntry
      // field; SortableTable only uses it as an identifier.
      key: column.key as keyof DeckFinderDeck,
      header: column.label,
      numeric: column.numeric,
      render: (row) =>
        column.key === 'name' ? (
          <>
            <button
              className="deckfinder-deck-link"
              type="button"
              aria-pressed={selectedDeck?.source_url === row.source_url && selectedDeck?.name === row.name}
              onClick={() =>
                results?.view.selection_action === 'details' ? void openDeck(row) : void runVariants(row)
              }
            >
              {row.name}
            </button>
            <span className="deckfinder-row-meta">
              {metadataColumns.map((column) => row.cells?.[column.key])
                .filter((value) => value && value !== '-' && value !== '—').join(' · ')}
            </span>
          </>
        ) : (
          (row.cells?.[column.key] ?? '—')
        ),
      sortValue: (row) => {
        switch (column.key) {
          case 'index':
            return Number(row.cells?.index ?? 0);
          case 'name':
            return row.name;
          case 'win_rate':
            return row.win_rate;
          case 'matches':
            return row.matches;
          case 'date':
            return row.event_date ?? '';
          default:
            return row.cells?.[column.key] ?? '';
        }
      },
    }));

  const showFormatChips = Boolean(provider && provider.format_options.length > 1);
  // Creator-backed sources (name "Creator: X") get their own chip row, like
  // the terminal app's separate creator table (TCGplayer, Moxfield).
  const regularSources = sources.filter((source) => !source.name.startsWith('Creator: '));
  const creatorSources = sources.filter((source) => source.name.startsWith('Creator: '));
  const showSources = Boolean(
    provider?.uses_source_picker &&
    (sources.length > 1 || (provider.key === 'youtube' && sources.length > 0)),
  );
  const resultContext = provider
    ? [
      provider.display_name,
      FORMAT_LONG_LABELS[lastFetch?.format ?? format] ?? format,
      lastFetch?.sourceName
        ? lastFetch.sourceName
        : provider.uses_source_picker
          ? `All (${provider.source_picker_all_label})`
          : null,
    ]
      .filter(Boolean)
      .join(' · ')
    : '';

  const parsedDeck = useMemo(() => parseDeckFinderImport(selectedDeck?.deck_text), [selectedDeck?.deck_text]);

  return (
    <div className="deckfinder-page" data-provider={provider?.key}>
      <Section
        id="deck-finder-browse"
        title="Browse Decks"
        description="Pick a site and creator, then copy a deck into Arena."
        headingAction={(
          <button className="quick-filter deckfinder-surprise" type="button" onClick={() => void runSurprise()}>
            <Dices aria-hidden="true" /> Surprise Me
          </button>
        )}
      >
        {providersError ? (
          <p className="empty-state deckfinder-state">{providersError}</p>
        ) : providers === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading sites...
          </p>
        ) : (
          <div className="deckfinder-providers" role="group" aria-label="Deck sites">
            {providers.map((candidate) => (
              <button
                key={candidate.key}
                type="button"
                className={
                  provider?.key === candidate.key
                    ? 'deckfinder-provider deckfinder-provider-active'
                    : 'deckfinder-provider'
                }
                data-provider={candidate.key}
                aria-pressed={provider?.key === candidate.key}
                title={candidate.description}
                onClick={() => selectProvider(candidate)}
              >
                <span className="deckfinder-site-icon" aria-hidden="true">
                  {SITE_ICONS[candidate.key] ? (
                    <img src={`/providers/${SITE_ICONS[candidate.key]}`} alt="" width={24} height={24} />
                  ) : <Search />}
                </span>
                <strong>{candidate.display_name}</strong>
                <span className="deckfinder-site-subtitle">{SITE_SUBTITLES[candidate.key] ?? candidate.description}</span>
              </button>
            ))}
          </div>
        )}

        {showFormatChips && provider ? (
          <div className="deckfinder-filter-row">
            <span className="deckfinder-step-label">Format</span>
            <div className="quick-filters deckfinder-chips" role="group" aria-label="Match format">
              {provider.format_options.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={format === option ? 'quick-filter quick-filter-active' : 'quick-filter'}
                  aria-pressed={format === option}
                  onClick={() => selectFormat(option)}
                >
                  {FORMAT_CHIP_LABELS[option] ?? option}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {showSources && provider && regularSources.length > 0 ? (
          <div className="deckfinder-filter-row">
            <span className="deckfinder-step-label">{provider.source_picker_title}</span>
            <div className="quick-filters deckfinder-chips" role="group" aria-label={provider.source_picker_title === 'Creators' ? 'Creators' : 'Deck sources'}>
              {provider.allow_all_sources ? (
                <button
                  className={
                    lastFetch && lastFetch.sourceUrl === ''
                      ? 'quick-filter quick-filter-active'
                      : 'quick-filter'
                  }
                  aria-pressed={Boolean(lastFetch && lastFetch.sourceUrl === '')}
                  type="button"
                  onClick={() =>
                    provider &&
                    void runFetch(provider, { format, sourceUrl: '', sourceName: '' })
                  }
                >
                  All ({provider.source_picker_all_label})
                </button>
              ) : null}
              {regularSources.map((source) => (
                <button
                  key={`${source.name}-${source.url}`}
                  className={
                    lastFetch?.sourceUrl === source.url
                      ? 'quick-filter quick-filter-active'
                      : 'quick-filter'
                  }
                  aria-pressed={lastFetch?.sourceUrl === source.url}
                  title={source.description}
                  type="button"
                  onClick={() =>
                    provider &&
                    void runFetch(provider, {
                      format,
                      sourceUrl: source.url,
                      sourceName: source.name,
                    })
                  }
                >
                  {source.name}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {showSources && provider && creatorSources.length > 0 ? (
          <div className="deckfinder-filter-row">
            <span className="deckfinder-step-label">
              {regularSources.length > 0 ? 'Creators' : provider.source_picker_title}
            </span>
            <div className="quick-filters deckfinder-chips" role="group" aria-label="Creators">
              {regularSources.length === 0 && provider.allow_all_sources ? (
                <button
                  className={
                    lastFetch && lastFetch.sourceUrl === ''
                      ? 'quick-filter quick-filter-active'
                      : 'quick-filter'
                  }
                  aria-pressed={Boolean(lastFetch && lastFetch.sourceUrl === '')}
                  type="button"
                  onClick={() =>
                    provider &&
                    void runFetch(provider, { format, sourceUrl: '', sourceName: '' })
                  }
                >
                  All ({provider.source_picker_all_label})
                </button>
              ) : null}
              {creatorSources.map((source) => (
                <button
                  key={`${source.name}-${source.url}`}
                  className={
                    lastFetch?.sourceUrl === source.url
                      ? 'quick-filter quick-filter-active'
                      : 'quick-filter'
                  }
                  aria-pressed={lastFetch?.sourceUrl === source.url}
                  title={source.description}
                  type="button"
                  onClick={() =>
                    provider &&
                    void runFetch(provider, {
                      format,
                      sourceUrl: source.url,
                      sourceName: source.name,
                    })
                  }
                >
                  {source.name.replace(/^Creator:\s*/u, '')}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {provider && provider.creators.length > 0 ? (
          <div className="deckfinder-filter-row">
            <span className="deckfinder-step-label">Creators</span>
            <div className="quick-filters deckfinder-chips" role="group" aria-label="Creators">
              {provider.creators.map((creator) => (
                <button
                  key={creator.url}
                  className={
                    lastFetch?.sourceUrl === creator.url
                      ? 'quick-filter quick-filter-active'
                      : 'quick-filter'
                  }
                  aria-pressed={lastFetch?.sourceUrl === creator.url}
                  title={creator.description}
                  type="button"
                  onClick={() =>
                    provider &&
                    void runFetch(provider, {
                      format: 'any',
                      sourceUrl: creator.url,
                      sourceName: creator.name,
                    })
                  }
                >
                  {creator.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {provider?.key === 'youtube' && sourcesLoaded && sources.length === 0 ? (
          <p className="empty-state deckfinder-state">
            Add a YouTube creator in <a href="#/settings">Settings</a> to find their decks.
          </p>
        ) : null}

        {busyNote ? (
          <p className="state-panel deckfinder-state deckfinder-busy" role="status" aria-busy="true">
            <span className="deckfinder-spinner" aria-hidden="true" />
            {busyNote}
          </p>
        ) : null}
        {error ? (
          <div className="state-panel error-state deckfinder-state" role="alert">
            <p>{error}</p>
          </div>
        ) : null}

      </Section>

      {results || selectedDeck ? (
        <section className="dashboard-section deckfinder-results" aria-label="Deck results">
          {results ? <div className="section-heading deckfinder-results-heading">
            <div>
              <h3>{results.view.title}</h3>
              <p className="section-description">
                {[
                  resultContext,
                  `${results.decks.length} ${results.view.count_label.toLowerCase()}`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              {results.view.helper_text ? (
                <p className="section-description">{results.view.helper_text}</p>
              ) : null}
            </div>
            {variantsParent ? (
              <button
                className="quick-filter deckfinder-heading-action"
                type="button"
                onClick={() =>
                  provider && lastFetch && void runFetch(provider, lastFetch)
                }
              >
                ← Back to results
              </button>
            ) : (
              <button
                className="quick-filter deckfinder-heading-action"
                title="Fetch fresh results"
                type="button"
                onClick={() =>
                  provider && lastFetch && void runFetch(provider, lastFetch, true)
                }
              >
                <RefreshCw aria-hidden="true" /> Refresh
              </button>
            )}
          </div> : null}
          <div className={results ? 'deckfinder-workspace' : 'deckfinder-workspace deckfinder-workspace-single'}>
            {results ? <div className="deckfinder-browser">
              <SortableTable
                caption="Deck Finder results"
                columns={deckColumns}
                getRowKey={(row) => `${row.source_url}#${row.cells?.index ?? row.name}`}
                pageSize={15}
                paginationKey={`${provider?.key}:${lastFetch?.sourceUrl}:${variantsParent?.source_url}`}
                rows={results.decks}
                getRowClassName={(row) => selectedDeck?.source_url === row.source_url && selectedDeck?.name === row.name ? 'deckfinder-row-selected' : undefined}
              />
            </div> : null}

            {selectedDeck ? (
              <aside className="deckfinder-detail" aria-label="Selected deck">
                <div className="deckfinder-detail-heading">
                  <div className="deckfinder-detail-title-row">
                    <h3>{parsedDeck?.name || selectedDeck.name}</h3>
                    <div className="deckfinder-title-actions">
                      <a
                        className="deck-neutral-button"
                        href={selectedDeck.source_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <ExternalLink aria-hidden="true" /> Source
                      </a>
                      <BuyPaperButton className="deck-export-button" disabled={!parsedDeck} onOpen={setBuyingOpener} />
                      <button
                        className="deck-export-button deckfinder-title-export"
                        disabled={!selectedDeck.deck_text}
                        type="button"
                        onClick={() => void copyDeck(selectedDeck)}
                      >
                        {copyStatus === 'copied' ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                        {copyStatus === 'copied'
                          ? 'Copied'
                          : copyStatus === 'error'
                            ? 'Export Failed'
                            : 'Export to Arena'}
                      </button>
                    </div>
                  </div>
                  <p className="section-description">
                    {[selectedDeck.player_name, selectedDeck.format_label,
                      parsedDeck ? `${parsedDeck.mainCount} cards` : null, selectedDeck.event_name]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                  <fieldset className="deckfinder-manager-actions">
                  <legend><a href="#/deck-manager" title="Open Deck Manager"><Layers aria-hidden="true" />Deck Manager</a></legend>
                  <div className="deckfinder-detail-actions">
                    {nativeStatus?.available ? <button className="deck-export-button deckfinder-manager-add" type="button"
                      disabled={saving || adding || addedSource === selectedDeck.source_url + selectedDeck.name || nativeStatus.busy || nativeStatus.in_game || nativeStatus.limit_reached === true || Boolean(nativeStatus.pending_transfers?.length) || !selectedDeck.deck_text}
                      title={addBlockedReason(nativeStatus) ?? 'Adds the deck with Arena’s importer. Arena must be open on Decks outside a match, with a free deck slot.'}
                      onClick={() => void addSelectedDeck()}>{addedSource === selectedDeck.source_url + selectedDeck.name ? <Check aria-hidden="true" /> : <Plus aria-hidden="true" />}{adding ? 'Adding…' : addedSource === selectedDeck.source_url + selectedDeck.name ? 'Added to Arena' : 'Add to Arena'}</button> : null}
                    <button className="deck-neutral-button deckfinder-manager-save" disabled={saving || adding || !selectedDeck.deck_text} type="button" onClick={(event) => {
                      setCollectionQuery(''); setPickingCollection(event.currentTarget);
                    }}><Archive aria-hidden="true" />{saving ? 'Saving…' : 'Save to collection'}</button>
                    {nativeStatus?.available ? <span className={`deckfinder-manager-hint${arenaFeedback?.error && arenaFeedback.source === selectedDeck.source_url + selectedDeck.name && needsDecksScreen(arenaFeedback.message) ? ' deckfinder-manager-hint-alert' : ''}`}>
                      <Info aria-hidden="true" />Arena must be on its Decks screen</span> : null}
                  </div>
                  {adding && arenaFeedback?.source === selectedDeck.source_url + selectedDeck.name ? <DeckTransferProgress detail={arenaFeedback.message} progress={transferProgress} /> : null}
                  {nativeStatus?.available && !adding && addBlockedReason(nativeStatus) ? <p className="deckfinder-arena-blocked">{addBlockedReason(nativeStatus)} {nativeStatus.pending_transfers?.length ? <a href="#/deck-manager">Open Deck Manager</a> : null}</p> : null}
                  {savedDeckId?.source === selectedDeck.source_url + selectedDeck.name ? <p role="status">Deck saved to {collections.find((c) => c.id === savedDeckId.collection)?.name ?? 'Unsorted'}. <a href="#/deck-manager">Open Deck Manager</a></p> : null}
                  {saveError?.source === selectedDeck.source_url + selectedDeck.name ? <p role="alert">{saveError.message}</p> : null}
                  {!adding && arenaFeedback?.source === selectedDeck.source_url + selectedDeck.name ? <p role={arenaFeedback.error ? 'alert' : 'status'}>{arenaFeedback.message} {arenaFeedback.error && !needsDecksScreen(arenaFeedback.message) ? <a href="#/deck-manager">Open Deck Manager</a> : null}</p> : null}
                  </fieldset>
                </div>
                {pickingCollection ? <DeckModal title="Save to collection" busy={false} onClose={() => setPickingCollection(null)} returnFocus={pickingCollection}>
                  <input type="search" aria-label="Search collections" placeholder="Search collections" autoFocus value={collectionQuery} onChange={(event) => setCollectionQuery(event.target.value)} />
                  <ul className="deck-collection-picker" aria-label="Collections">
                    {[{ id: '', name: 'Unsorted' }, ...collections].filter((c) => c.name.toLowerCase().includes(collectionQuery.trim().toLowerCase())).map((c) => (
                      <li key={c.id || 'unsorted'}><button type="button" onClick={() => saveSelectedDeck(c.id)}><FolderOpen aria-hidden="true" size={16} />{c.name}</button></li>
                    ))}
                  </ul>
                  {collections.length && ![{ name: 'Unsorted' }, ...collections].some((c) => c.name.toLowerCase().includes(collectionQuery.trim().toLowerCase())) ? <p className="deck-manager-description">No collections match “{collectionQuery}”.</p> : null}
                </DeckModal> : null}
                {selectedDeck.deck_text ? (
                  parsedDeck ? <DeckFinderDeckList deck={parsedDeck} /> : (
                    <pre className="deckfinder-decklist">{formatArenaImportText(selectedDeck.deck_text)}</pre>
                  )
                ) : hydrating ? (
                  <p className="state-panel deckfinder-busy" role="status" aria-busy="true">
                    <span className="deckfinder-spinner" aria-hidden="true" />
                    Loading deck list…
                  </p>
                ) : (
                  <p className="empty-state">
                    No importable deck list for this entry — use the Source link to view it on{' '}
                    {selectedDeck.source_site}.
                  </p>
                )}
              </aside>
            ) : (
              <div className="deckfinder-detail deckfinder-detail-empty">
                <Search aria-hidden="true" />
                <h3>Choose a deck</h3>
                <p>Select a result to see its full list and copy it into Arena.</p>
              </div>
            )}
          </div>
        </section>
      ) : null}
      {/* Outside the selected-deck panel so its provider-colored headings don't apply. */}
      {buyingOpener && selectedDeck && parsedDeck ? (
        <BuyPaperDialog sections={parsedDeck.sections}
          onClose={() => setBuyingOpener(null)} returnFocus={buyingOpener} />
      ) : null}
    </div>
  );
}
