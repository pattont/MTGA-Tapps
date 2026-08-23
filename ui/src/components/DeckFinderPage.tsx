import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, Dices, ExternalLink, RefreshCw } from 'lucide-react';
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

const JOB_POLL_MS = 700;
const JOB_TIMEOUT_MS = 120_000;

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
  const [results, setResults] = useState<DeckFinderResults | null>(null);
  const [variantsParent, setVariantsParent] = useState<DeckFinderDeck | null>(null);
  const [busyNote, setBusyNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDeck, setSelectedDeck] = useState<DeckFinderDeck | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle');
  const requestSeq = useRef(0);
  // What produced the current results — reused by Refresh, variants context,
  // and "back to results" after a variants drill-down.
  const [lastFetch, setLastFetch] = useState<FetchArgs | null>(null);

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
    setError(null);
    return requestSeq.current;
  }, []);

  const runFetch = useCallback(
    async (nextProvider: DeckFinderProvider, args: FetchArgs, refresh = false) => {
      const seq = beginRequest();
      setLastFetch(args);
      setBusyNote(`Fetching decks from ${nextProvider.display_name}…`);
      setResults(null);
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
    [beginRequest],
  );

  const loadSources = useCallback(
    async (nextProvider: DeckFinderProvider, nextFormat: string) => {
      const seq = beginRequest();
      setSources([]);
      setResults(null);
      setVariantsParent(null);
      setSelectedDeck(null);
      if (!nextProvider.uses_source_picker) {
        void runFetch(nextProvider, { format: nextFormat, sourceUrl: '', sourceName: '' });
        return;
      }
      try {
        const loaded = await fetchDeckFinderSources(nextProvider.key, nextFormat);
        if (requestSeq.current === seq) {
          setSources(loaded);
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
    [beginRequest, format, lastFetch, provider],
  );

  const openDeck = useCallback(
    async (deck: DeckFinderDeck) => {
      setCopyStatus('idle');
      setSelectedDeck(deck);
      if (deck.deck_text || !provider) {
        setHydrating(false);
        return;
      }
      setHydrating(true);
      try {
        const hydrated = await hydrateDeckFinderDeck(provider.key, deck);
        setSelectedDeck((current) =>
          current && current.source_url === deck.source_url ? hydrated : current,
        );
      } catch {
        // The drawer shows "deck list unavailable" and keeps the source link.
      } finally {
        setHydrating(false);
      }
    },
    [provider],
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

  const deckColumns: Column<DeckFinderDeck>[] = (results?.view.columns ?? []).map((column) => ({
    // Column identity is the server-provided table-spec key, not a DeckEntry
    // field; SortableTable only uses it as an identifier.
    key: column.key as keyof DeckFinderDeck,
    header: column.label,
    numeric: column.numeric,
    render: (row) =>
      column.key === 'name' ? (
        <button
          className="deckfinder-deck-link"
          type="button"
          onClick={() =>
            results?.view.selection_action === 'details' ? void openDeck(row) : void runVariants(row)
          }
        >
          {row.name}
        </button>
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
  const showSources = Boolean(provider?.uses_source_picker && sources.length > 1);
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

  return (
    <Section
      id="deck-finder-browse"
      title="Browse Decks"
      description="Pick a site and format, then find and export any deck list to your clipboard to be imported into Arena."
    >
      <div className="deckfinder-toolbar">
        <span className="deckfinder-step-label">Site</span>
        <button className="quick-filter deckfinder-surprise" type="button" onClick={() => void runSurprise()}>
          <Dices aria-hidden="true" /> Surprise Me
        </button>
      </div>

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
              onClick={() => selectProvider(candidate)}
            >
              <strong>{candidate.display_name}</strong>
              <span>{candidate.description}</span>
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

      {provider && provider.creators.length > 0 ? (
        <div className="deckfinder-filter-row">
          <span className="deckfinder-step-label">Creators</span>
          <div className="quick-filters deckfinder-chips" role="group" aria-label="Creators">
            {provider.creators.map((creator) => (
              <button
                key={creator.url}
                className="quick-filter"
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

      {showSources && provider && regularSources.length > 0 ? (
        <div className="deckfinder-filter-row">
          <span className="deckfinder-step-label">{provider.source_picker_title}</span>
          <div className="quick-filters deckfinder-chips" role="group" aria-label="Deck sources">
            {provider.allow_all_sources ? (
              <button
                className="quick-filter"
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
                className="quick-filter"
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
                className="quick-filter"
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
                className="quick-filter"
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

      {results ? (
        <>
          <div className="section-heading">
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
          </div>
          <SortableTable
            caption="Deck Finder results"
            columns={deckColumns}
            getRowKey={(row) => `${row.source_url}#${row.cells?.index ?? row.name}`}
            pageSize={15}
            rows={results.decks}
          />
        </>
      ) : null}

      {selectedDeck ? (
        <div className="deckfinder-detail">
          <div className="section-heading">
            <div>
              <h3>{selectedDeck.name}</h3>
              <p className="section-description">
                {[selectedDeck.player_name, selectedDeck.format_label, selectedDeck.event_name]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </div>
            <div className="deckfinder-detail-actions">
              <button
                className="deck-export-button"
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
              <a
                className="deck-neutral-button"
                href={selectedDeck.source_url}
                rel="noreferrer"
                target="_blank"
              >
                <ExternalLink aria-hidden="true" /> Source
              </a>
            </div>
          </div>
          {selectedDeck.deck_text ? (
            <pre className="deckfinder-decklist">{formatArenaImportText(selectedDeck.deck_text)}</pre>
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
        </div>
      ) : null}
    </Section>
  );
}
