import { useEffect, useRef, useState } from 'react';
import {
  collectionDownloadUrl,
  fetchCollectionExportJob,
  fetchTrackerSettings,
  saveDeckAiSettings,
  saveDeckFinderCreators,
  startCollectionExport,
  type CollectionExportFormat,
  type CollectionExportJob,
  type DeckAiSettings,
  type DeckFinderCreator,
  type DeckFinderCreatorSettings,
  type PlatformSettings,
  type TrackerInfoSettings,
} from '../api';
import { Section } from './Section';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const CREATOR_SITES = [
  ['moxfield', 'Moxfield'],
  ['aetherhub', 'Aetherhub'],
  ['tcgplayer', 'TCGplayer'],
] as const;

function creatorLines(creators: DeckFinderCreator[]): string {
  return creators
    .map((creator) =>
      creator.short_name ? `${creator.name} | ${creator.short_name}` : creator.name,
    )
    .join('\n');
}

function parseCreatorLines(text: string): DeckFinderCreator[] {
  return text
    .split('\n')
    .map((line) => {
      const [name, short] = line.split('|', 2).map((part) => part.trim());
      return { name: name ?? '', short_name: short || null };
    })
    .filter((creator) => creator.name.length > 0);
}

function saveLabel(status: SaveStatus, idle: string): string {
  if (status === 'saving') {
    return 'Saving…';
  }
  if (status === 'saved') {
    return 'Saved';
  }
  if (status === 'error') {
    return 'Save Failed';
  }
  return idle;
}

const TRACKER_INFO_ROWS: Array<[keyof TrackerInfoSettings, string]> = [
  ['monitoring', 'Monitoring'],
  ['card_db', 'Local Card DB'],
  ['log_db', 'Log DB'],
  ['deck_ai', 'Deck AI'],
  ['version', 'Tracker Version'],
];

function TrackerInfo({ info }: { info: TrackerInfoSettings }) {
  return (
    <dl className="settings-info">
      {TRACKER_INFO_ROWS.map(([key, label]) => (
        <div key={key} className="settings-info-row">
          <dt>{label}</dt>
          <dd>{info[key] ?? 'not found (start the tracker to detect it)'}</dd>
        </div>
      ))}
    </dl>
  );
}

const EXPORT_FORMATS: Array<[CollectionExportFormat, string]> = [
  ['json', 'Export to .json'],
  ['csv', 'Export to .csv'],
  ['txt', 'Export to .txt'],
];

function triggerDownload(fileName: string): void {
  const link = document.createElement('a');
  link.href = collectionDownloadUrl(fileName);
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function CollectionExport({ platform }: { platform: PlatformSettings }) {
  const [job, setJob] = useState<CollectionExportJob | null>(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<number | null>(null);
  const deliveredRef = useRef<string | null>(null);

  useEffect(
    () => () => {
      if (pollRef.current !== null) {
        window.clearTimeout(pollRef.current);
      }
    },
    [],
  );

  const settle = (next: CollectionExportJob) => {
    setJob(next);
    setRunning(false);
    // Deliver the file straight to the browser's downloads once, so it
    // "pops up" the way a Save dialog would.
    if (next.state === 'done' && next.file && deliveredRef.current !== next.file) {
      deliveredRef.current = next.file;
      triggerDownload(next.file);
    }
  };

  const fail = (format: CollectionExportFormat, message: string) =>
    setJob({
      state: 'error',
      detail: message,
      format,
      file: null,
      unique: null,
      total: null,
      error_code: 'scan_failed',
    });

  const poll = (jobId: string) => {
    fetchCollectionExportJob(jobId)
      .then((next) => {
        if (next.state === 'running') {
          setJob(next);
          pollRef.current = window.setTimeout(() => poll(jobId), 600);
        } else {
          settle(next);
        }
      })
      .catch((exc: unknown) => {
        fail('json', exc instanceof Error ? exc.message : 'Export failed');
        setRunning(false);
      });
  };

  const runExport = (format: CollectionExportFormat) => {
    setRunning(true);
    deliveredRef.current = null;
    setJob({ state: 'running', detail: 'Starting…', format, file: null, unique: null, total: null, error_code: null });
    startCollectionExport(format)
      .then((started) => {
        if (started.job && started.state === 'running') {
          setJob(started);
          pollRef.current = window.setTimeout(() => poll(started.job as string), 600);
        } else {
          settle(started);
        }
      })
      .catch((exc: unknown) => {
        fail(format, exc instanceof Error ? exc.message : 'Export failed');
        setRunning(false);
      });
  };

  return (
    <div className="collection-export">
      <ul className="collection-export-reqs">
        <li>
          MTG Arena must be <strong>running</strong>, with your collection loaded —{' '}
          <span className="collection-export-flag">open the Decks tab in Arena once</span> before you
          export.
        </li>
        {platform.system === 'macos' ? (
          <li>
            macOS will show an <strong>administrator password prompt</strong> — reading another app's
            memory needs elevated access. The password only runs the scan; nothing is installed or
            changed.
          </li>
        ) : null}
        <li>
          Reading the collection out of memory can take a few minutes (rarely up to ~10).{' '}
          <span className="collection-export-flag">Stay on this page while it runs</span> — leaving
          cancels the export.
        </li>
      </ul>

      <div className="collection-export-buttons">
        {EXPORT_FORMATS.map(([format, label]) => (
          <button
            key={format}
            className="deck-export-button"
            type="button"
            disabled={running}
            onClick={() => runExport(format)}
          >
            {label}
          </button>
        ))}
      </div>

      {job && job.state === 'running' ? (
        <p className="collection-export-status" role="status" aria-busy="true">
          <span className="collection-export-spinner" aria-hidden="true" />
          {job.detail}
        </p>
      ) : null}

      {job && job.state === 'done' ? (
        <p className="collection-export-status collection-export-done" role="status">
          ✓ {job.detail} Your download should start automatically —{' '}
          {job.file ? (
            <a className="collection-export-download" href={collectionDownloadUrl(job.file)}>
              download again
            </a>
          ) : null}
          . A copy is also saved in your MTGA Tracker data folder.
        </p>
      ) : null}

      {job && job.state === 'error' ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {job.detail}
        </p>
      ) : null}

      <p className="collection-export-fineprint">
        Unofficial: Arena doesn't expose your collection, so this reads it from the game's memory —
        the game is never modified. An Arena update can temporarily break this until the tool is
        adjusted. Quantities come straight from the game's own data. Extraction technique by{' '}
        <a
          href="https://github.com/NthPhantom10/MTGA-collection-exporter"
          rel="noreferrer"
          target="_blank"
        >
          NthPhantom10's MTGA-collection-exporter
        </a>
        .
      </p>
    </div>
  );
}

export function SettingsPage() {
  const [error, setError] = useState<string | null>(null);
  const [trackerInfo, setTrackerInfo] = useState<TrackerInfoSettings | null>(null);
  const [deckAi, setDeckAi] = useState<DeckAiSettings | null>(null);
  const [creators, setCreators] = useState<DeckFinderCreatorSettings | null>(null);
  const [platform, setPlatform] = useState<PlatformSettings | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTrackerSettings()
      .then((settings) => {
        if (!cancelled) {
          setTrackerInfo(settings.tracker);
          setDeckAi(settings.deck_ai);
          setCreators(settings.deck_finder);
          setPlatform(settings.platform);
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : 'Settings failed to load');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <Section
        id="settings-tracker"
        title="Tracker"
        description="What this tracker is watching and writing. Detected when the tracker starts and refreshed on every restart."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : trackerInfo === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading...
          </p>
        ) : (
          <TrackerInfo info={trackerInfo} />
        )}
      </Section>

      <Section
        id="settings-deck-ai"
        title="Deck AI"
        description="Identify your opponent's deck with an AI provider. One small, cheap request per completed game — tracking never waits on it. The key is stored locally in settings.json and only ever sent to the provider you choose."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : deckAi === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading settings...
          </p>
        ) : (
          <DeckAiForm initial={deckAi} />
        )}
      </Section>

      <Section
        id="settings-creators"
        title="Deck Finder Creators"
        description="Which creators the Deck Finder's Moxfield, Aetherhub, and TCGplayer sites follow. One creator per line. Add a short display name after a pipe — “Ashlizzlle | Ash” makes imported decks show up as “Jeskai Artifacts (Ash)” in Arena."
      >
        {error ? null : creators === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading creators...
          </p>
        ) : (
          <CreatorsForm initial={creators} />
        )}
      </Section>

      {platform?.collection_export ? (
        <Section
          id="settings-collection-export"
          title="Export MTGA Collection"
          description="Read your full card collection from the running game and export it for Moxfield and similar sites."
        >
          <CollectionExport platform={platform} />
        </Section>
      ) : null}

      <Section
        id="settings-db-health"
        title="Database Health"
        description="Audit the tracker database for incomplete or suspicious games, review findings, and reset data if something went wrong."
      >
        <div className="settings-form">
          <div>
            <a className="deck-export-button settings-link-button" href="#/audit">
              Open Database Health
            </a>
          </div>
        </div>
      </Section>
    </>
  );
}

function DeckAiForm({ initial }: { initial: DeckAiSettings }) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [provider, setProvider] = useState(initial.provider);
  const [keys, setKeys] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.providers.map((entry) => [entry.key, entry.api_key])),
  );
  const [models, setModels] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.providers.map((entry) => [entry.key, entry.model])),
  );
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<SaveStatus>('idle');

  const active = initial.providers.find((entry) => entry.key === provider) ?? initial.providers[0];

  async function save() {
    setStatus('saving');
    try {
      await saveDeckAiSettings({ enabled, provider, keys, models });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  return (
    <div className="settings-form">
      <label className="settings-check">
        <input
          checked={enabled}
          type="checkbox"
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enable AI deck identification
      </label>

      <label className="settings-field">
        <span>Provider</span>
        <select value={provider} onChange={(event) => setProvider(event.target.value)}>
          {initial.providers.map((entry) => (
            <option key={entry.key} value={entry.key}>
              {entry.label}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-field">
        <span>API key</span>
        <div className="settings-key-row">
          <input
            autoComplete="off"
            placeholder="API key"
            spellCheck={false}
            type={showKey ? 'text' : 'password'}
            value={keys[provider] ?? ''}
            onChange={(event) =>
              setKeys((current) => ({ ...current, [provider]: event.target.value }))
            }
          />
          <button
            className="quick-filter"
            type="button"
            onClick={() => setShowKey((current) => !current)}
          >
            {showKey ? 'Hide' : 'Show'}
          </button>
        </div>
      </label>

      <label className="settings-field">
        <span>Model</span>
        <input
          placeholder={active?.default_model ?? ''}
          spellCheck={false}
          type="text"
          value={models[provider] ?? ''}
          onChange={(event) =>
            setModels((current) => ({ ...current, [provider]: event.target.value }))
          }
        />
      </label>

      <div>
        <button
          className="deck-export-button"
          disabled={status === 'saving'}
          type="button"
          onClick={() => void save()}
        >
          {saveLabel(status, 'Save Deck AI Settings')}
        </button>
      </div>
    </div>
  );
}

function CreatorsForm({ initial }: { initial: DeckFinderCreatorSettings }) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => ({
    moxfield: creatorLines(initial.moxfield),
    aetherhub: creatorLines(initial.aetherhub),
    tcgplayer: creatorLines(initial.tcgplayer),
  }));
  const [status, setStatus] = useState<SaveStatus>('idle');

  async function save() {
    setStatus('saving');
    try {
      await saveDeckFinderCreators({
        moxfield: parseCreatorLines(drafts.moxfield ?? ''),
        aetherhub: parseCreatorLines(drafts.aetherhub ?? ''),
        tcgplayer: parseCreatorLines(drafts.tcgplayer ?? ''),
      });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  return (
    <div className="settings-form">
      {CREATOR_SITES.map(([key, label]) => {
        const value = drafts[key] ?? '';
        // Size the editor to its content so nothing scrolls out of view.
        const rows = Math.max(value.split('\n').length + 1, 3);
        return (
          <label key={key} className="settings-field">
            <span>{label}</span>
            <textarea
              placeholder={'CreatorName | Short name'}
              rows={rows}
              spellCheck={false}
              value={value}
              onChange={(event) =>
                setDrafts((current) => ({ ...current, [key]: event.target.value }))
              }
            />
          </label>
        );
      })}
      <div>
        <button
          className="deck-export-button"
          disabled={status === 'saving'}
          type="button"
          onClick={() => void save()}
        >
          {saveLabel(status, 'Save Creators')}
        </button>
      </div>
    </div>
  );
}
