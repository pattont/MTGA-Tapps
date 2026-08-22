import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Copy, Dices, ExternalLink, RefreshCw } from 'lucide-react';
import {
  fetchDeckFinderConfig,
  fetchDeckFinderJob,
  fetchDeckFinderProviders,
  fetchDeckFinderSources,
  hydrateDeckFinderDeck,
  saveDeckFinderConfig,
  startDeckFinderFetch,
  startDeckFinderSurprise,
  startDeckFinderVariants,
  type DeckFinderConfig,
  type DeckFinderCreator,
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

const FORMAT_CHOICES: Array<{ id: string; label: string }> = [
  { id: 'bo1', label: 'BO1' },
  { id: 'bo3', label: 'BO3' },
  { id: 'any', label: 'Any' },
];

function formatPercentValue(value: number | null): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 10) / 10}%`;
}

export function DeckFinderPage() {
  const [providers, setProviders] = useState<DeckFinderProvider[] | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [provider, setProvider] = useState<DeckFinderProvider | null>(null);
  const [format, setFormat] = useState('bo1');
  const [sources, setSources] = useState<DeckFinderSource[]>([]);
  const [results, setResults] = useState<DeckFinderResults | null>(null);
  const [variantsParent, setVariantsParent] = useState<DeckFinderDeck | null>(null);
  const [busyNote, setBusyNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDeck, setSelectedDeck] = useState<DeckFinderDeck | null>(null);
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle');
  const [config, setConfig] = useState<DeckFinderConfig | null>(null);
  const [configStatus, setConfigStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const requestSeq = useRef(0);

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
    fetchDeckFinderConfig()
      .then((loaded) => {
        if (!cancelled) {
          setConfig(loaded);
        }
      })
      .catch(() => {
        // Settings section simply stays hidden if the config can't load.
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

  const loadSources = useCallback(
    async (nextProvider: DeckFinderProvider, nextFormat: string) => {
      const seq = beginRequest();
      setSources([]);
      setResults(null);
      setVariantsParent(null);
      setSelectedDeck(null);
      if (!nextProvider.uses_source_picker) {
        return;
      }
      try {
        const loaded = await fetchDeckFinderSources(nextProvider.key, nextFormat);
        if (requestSeq.current === seq) {
          setSources(loaded);
        }
      } catch (exc: unknown) {
        if (requestSeq.current === seq) {
          setError(exc instanceof Error ? exc.message : 'Failed to load sources');
        }
      }
    },
    [beginRequest],
  );

  const runFetch = useCallback(
    async (
      nextProvider: DeckFinderProvider,
      nextFormat: string,
      sourceUrl: string,
      refresh = false,
    ) => {
      const seq = beginRequest();
      setBusyNote(`Fetching decks from ${nextProvider.display_name}…`);
      setResults(null);
      setVariantsParent(null);
      setSelectedDeck(null);
      try {
        const started = await startDeckFinderFetch({
          provider: nextProvider.key,
          format: nextFormat,
          source_url: sourceUrl || undefined,
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

  const runVariants = useCallback(
    async (parent: DeckFinderDeck) => {
      if (!provider) {
        return;
      }
      const seq = beginRequest();
      setBusyNote(`Loading variants of ${parent.name}…`);
      try {
        const started = await startDeckFinderVariants({
          provider: provider.key,
          format,
          deck: parent,
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
    [beginRequest, format, provider],
  );

  const openDeck = useCallback(
    async (deck: DeckFinderDeck) => {
      setCopyStatus('idle');
      setSelectedDeck(deck);
      if (deck.deck_text || !provider) {
        return;
      }
      try {
        const hydrated = await hydrateDeckFinderDeck(provider.key, deck);
        setSelectedDeck((current) =>
          current && current.source_url === deck.source_url ? hydrated : current,
        );
      } catch {
        // The drawer shows "deck list unavailable" and keeps the source link.
      }
    },
    [provider],
  );

  const runSurprise = useCallback(async () => {
    const seq = beginRequest();
    setBusyNote('Finding you a surprise deck…');
    try {
      const started = await startDeckFinderSurprise(format);
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
  }, [beginRequest, format]);

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
    const nextFormat = next.supported_formats.includes(format)
      ? format
      : (next.supported_formats[0] ?? 'any');
    setFormat(nextFormat);
    void loadSources(next, nextFormat);
    if (!next.uses_source_picker) {
      void runFetch(next, nextFormat, '');
    }
  }

  function selectFormat(nextFormat: string) {
    setFormat(nextFormat);
    if (provider) {
      void loadSources(provider, nextFormat);
      if (!provider.uses_source_picker) {
        void runFetch(provider, nextFormat, '');
      }
    }
  }

  const deckColumns: Column<DeckFinderDeck>[] = [
    {
      key: 'name',
      header: results?.view.name_column_label ?? 'Deck',
      render: (row) => (
        <button
          className="deckfinder-deck-link"
          type="button"
          onClick={() =>
            results?.view.selection_action === 'variants' ? void runVariants(row) : void openDeck(row)
          }
        >
          {row.name}
        </button>
      ),
      sortValue: (row) => row.name,
    },
    {
      key: 'player_name',
      header: 'Player',
      render: (row) => row.player_name ?? '—',
      sortValue: (row) => row.player_name ?? '',
    },
    {
      key: 'win_rate',
      header: 'Win Rate',
      render: (row) => formatPercentValue(row.win_rate),
      sortValue: (row) => row.win_rate,
      numeric: true,
    },
    {
      key: 'matches',
      header: 'Matches',
      render: (row) => (row.matches === null || row.matches === undefined ? '—' : String(row.matches)),
      sortValue: (row) => row.matches,
      numeric: true,
    },
    {
      key: 'event_name',
      header: 'Event / Date',
      render: (row) =>
        [row.event_name, row.event_date].filter(Boolean).join(' · ') || row.format_label || '—',
      sortValue: (row) => row.event_date ?? '',
    },
    ...(results?.view.show_notes === false || !results?.decks.some((deck) => deck.notes)
      ? []
      : ([
          {
            key: 'notes',
            header: 'Notes',
            render: (row) => row.notes ?? '',
            sortValue: (row) => row.notes ?? '',
          },
        ] as Column<DeckFinderDeck>[])),
  ];

  const hasPickableSources = Boolean(provider?.uses_source_picker && sources.length > 0);

  return (
    <>
      <Section
        id="deck-finder-browse"
        title="Browse Decks"
        description="Browse top decks from the community sites and copy any list straight into Arena — no terminal needed."
      >
        <div className="deckfinder-toolbar">
          <div className="quick-filters" role="group" aria-label="Match format">
            {FORMAT_CHOICES.map((choice) => (
              <button
                key={choice.id}
                type="button"
                className={format === choice.id ? 'quick-filter quick-filter-active' : 'quick-filter'}
                aria-pressed={format === choice.id}
                disabled={Boolean(provider && !provider.supported_formats.includes(choice.id) && choice.id !== 'any')}
                onClick={() => selectFormat(choice.id)}
              >
                {choice.label}
              </button>
            ))}
          </div>
          <button className="quick-filter deckfinder-surprise" type="button" onClick={() => void runSurprise()}>
            <Dices aria-hidden="true" /> Surprise Me
          </button>
        </div>

        {providersError ? (
          <p className="empty-state">{providersError}</p>
        ) : providers === null ? (
          <p className="state-panel" role="status" aria-busy="true">
            Loading providers...
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

        {hasPickableSources ? (
          <>
            <div className="section-heading">
              <div>
                <h3>{provider?.source_picker_title}</h3>
              </div>
            </div>
            <div className="deckfinder-sources" role="group" aria-label="Deck sources">
              {provider?.allow_all_sources ? (
                <button
                  className="quick-filter"
                  type="button"
                  onClick={() => provider && void runFetch(provider, format, '')}
                >
                  All ({provider.source_picker_all_label})
                </button>
              ) : null}
              {sources.map((source) => (
                <button
                  key={source.url}
                  className="quick-filter"
                  title={source.description}
                  type="button"
                  onClick={() => provider && void runFetch(provider, format, source.url)}
                >
                  {source.name}
                </button>
              ))}
            </div>
          </>
        ) : null}

        {busyNote ? (
          <p className="state-panel" role="status" aria-busy="true">
            {busyNote}
          </p>
        ) : null}
        {error ? (
          <div className="state-panel error-state" role="alert">
            <p>{error}</p>
          </div>
        ) : null}

        {results ? (
          <>
            <div className="section-heading">
              <div>
                <h3>
                  {variantsParent ? `${variantsParent.name} — variants` : results.view.title}
                  {` · ${results.decks.length} ${results.view.count_label.toLowerCase()}`}
                </h3>
                {results.view.helper_text ? (
                  <p className="section-description">{results.view.helper_text}</p>
                ) : null}
              </div>
              <button
                className="quick-filter"
                title="Fetch fresh results"
                type="button"
                onClick={() => provider && void runFetch(provider, format, '', true)}
              >
                <RefreshCw aria-hidden="true" /> Refresh
              </button>
            </div>
            {variantsParent ? (
              <p className="section-description">
                <button className="table-link deckfinder-back" type="button" onClick={() => provider && void runFetch(provider, format, '')}>
                  ← Back to {results.view.name_column_label.toLowerCase()}s
                </button>
              </p>
            ) : null}
            <SortableTable
              caption="Deck Finder results"
              columns={deckColumns}
              getRowKey={(row) => row.source_url}
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
                      ? 'Copy Failed'
                      : 'Copy for Arena'}
                </button>
                <a
                  className="quick-filter"
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
            ) : (
              <p className="empty-state">Loading deck list…</p>
            )}
          </div>
        ) : null}
      </Section>

      {config ? (
        <Section
          id="deck-finder-settings"
          title="Creator Settings"
          description={`Which creators the Moxfield / Aetherhub / TCGplayer providers follow. Saved to ${config.path}`}
        >
          <CreatorSettings
            config={config}
            status={configStatus}
            onSave={async (next) => {
              setConfigStatus('saving');
              try {
                const saved = await saveDeckFinderConfig(next);
                setConfig(saved);
                setConfigStatus('saved');
                window.setTimeout(() => setConfigStatus('idle'), 1800);
              } catch {
                setConfigStatus('error');
              }
            }}
          />
        </Section>
      ) : null}
    </>
  );
}

function CreatorSettings({
  config,
  status,
  onSave,
}: {
  config: DeckFinderConfig;
  status: 'idle' | 'saving' | 'saved' | 'error';
  onSave: (next: {
    moxfield: DeckFinderCreator[];
    aetherhub: DeckFinderCreator[];
    tcgplayer: DeckFinderCreator[];
  }) => void | Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({
    moxfield: config.moxfield.map((creator) => creator.name).join('\n'),
    aetherhub: config.aetherhub.map((creator) => creator.name).join('\n'),
    tcgplayer: config.tcgplayer.map((creator) => creator.name).join('\n'),
  });

  function parsed(key: string): DeckFinderCreator[] {
    return (drafts[key] ?? '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((name) => ({ name, short_name: null }));
  }

  return (
    <div className="deckfinder-settings">
      {(
        [
          ['moxfield', 'Moxfield creators'],
          ['aetherhub', 'Aetherhub creators'],
          ['tcgplayer', 'TCGplayer creators'],
        ] as const
      ).map(([key, label]) => (
        <label key={key} className="deckfinder-settings-field">
          <span>{label}</span>
          <textarea
            rows={4}
            spellCheck={false}
            value={drafts[key]}
            onChange={(event) => setDrafts((current) => ({ ...current, [key]: event.target.value }))}
          />
        </label>
      ))}
      <div>
        <button
          className="deck-export-button"
          disabled={status === 'saving'}
          type="button"
          onClick={() =>
            void onSave({
              moxfield: parsed('moxfield'),
              aetherhub: parsed('aetherhub'),
              tcgplayer: parsed('tcgplayer'),
            })
          }
        >
          {status === 'saving'
            ? 'Saving…'
            : status === 'saved'
              ? 'Saved'
              : status === 'error'
                ? 'Save Failed'
                : 'Save Creators'}
        </button>
      </div>
    </div>
  );
}
