import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Bot, CalendarClock, Gamepad2, Tag } from 'lucide-react';
import { Badge } from './Badge';
import { BackupCard } from './BackupCard';
import { MetricCard } from './MetricCard';
import {
  collectionDownloadUrl,
  fetchCollectionExportJob,
  fetchDeckAiModels,
  fetchTrackerSettings,
  saveDeckAiSettings,
  saveDeckFinderCreators,
  saveSessionSettings,
  saveStartupSettings,
  startCollectionExport,
  setOverlayEnabled,
  type CollectionExportFormat,
  type CollectionExportJob,
  type OverlaySettings,
  type BuyOnPaperSettings,
  type SessionSettings,
  type DeckAiModel,
  type DeckAiProviderSettings,
  type DeckAiSettings,
  type DeckFinderCreator,
  type DeckFinderCreatorSettings,
  type PlatformSettings,
  type StartupSettings,
  type TrackerInfoSettings,
} from '../api';
import { formatDateTime } from '../format';
import { StreamKitSettings } from './StreamKitSettings';
import { Section } from './Section';
import { useSharedUpdateStatus } from './useUpdateStatus';
import {
  displayVersion,
  isNewerVersion,
  saveUpdateSettings,
  updatePillModel,
  updateReasonText,
  type UpdateSettings,
  type UpdateSettingsChange,
  type UpdateStatus,
} from '../updateStatus';
import { saveBuyOnPaperEnabled } from '../buyOnPaperSetting';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const CREATOR_SITES = [
  ['moxfield', 'Moxfield'],
  ['aetherhub', 'Aetherhub'],
  ['tcgplayer', 'TCGplayer'],
  ['youtube', 'YouTube'],
] as const;

function creatorLines(creators: DeckFinderCreator[]): string {
  return creators
    .map((creator) =>
      creator.short_name
        ? `${creator.channel ?? creator.name} | ${creator.short_name}`
        : creator.channel ?? creator.name,
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

const TRACKER_PATH_ROWS: Array<[keyof TrackerInfoSettings, string]> = [
  ['monitoring', 'Monitoring'],
  ['card_db', 'Local Card DB'],
  ['log_db', 'Log DB'],
];

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "Today", "Yesterday", "3 days ago", then a short date. */
function dayLabel(date: Date, now: Date = new Date()): string {
  const midnight = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((midnight(now) - midnight(date)) / 86_400_000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function deckAiProvider(deckAi: DeckAiSettings): DeckAiProviderSettings | undefined {
  return deckAi.providers.find((entry) => entry.key === deckAi.provider);
}

function TrackerOverview({ info, deckAi }: { info: TrackerInfoSettings; deckAi: DeckAiSettings | null }) {
  const status = useSharedUpdateStatus().status;
  const first = parseDate(info.first_game_at);
  const last = parseDate(info.last_game_at);
  const games = info.games;
  const latest = status?.latest_version ?? null;
  const versionDetail =
    status?.state === 'up_to_date'
      ? 'Up to date'
      : latest && (status?.state === 'available' || status?.state === 'downloading' || status?.state === 'ready')
        ? `${displayVersion(latest)} available`
        : undefined;
  const provider = deckAi ? deckAiProvider(deckAi) : undefined;
  const deckAiOn = Boolean(deckAi?.enabled && provider?.api_key.trim());

  return (
    <>
      <div className="settings-tiles">
        <MetricCard
          icon={<Gamepad2 />}
          label="Games captured"
          value={games == null ? '—' : games.toLocaleString()}
          detail={
            first
              ? `since ${first.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}`
              : games === 0
                ? 'Play a game with the tracker running'
                : undefined
          }
        />
        <MetricCard
          icon={<CalendarClock />}
          label="Last game"
          value={last ? dayLabel(last) : '—'}
          detail={last ? formatDateTime(info.last_game_at as string) : undefined}
        />
        <MetricCard icon={<Tag />} label="Tracker version" value={displayVersion(info.version) || info.version} detail={versionDetail} />
        <MetricCard
          icon={<Bot />}
          label="Deck AI"
          value={!deckAi ? '—' : deckAiOn ? 'On' : deckAi.enabled ? 'No API key' : 'Off'}
          detail={deckAi?.enabled && provider ? `${provider.label} · ${provider.model || provider.default_model}` : undefined}
        />
      </div>
      <dl className="settings-info settings-paths">
        {TRACKER_PATH_ROWS.map(([key, label]) => (
          <div key={key} className="settings-info-row">
            <dt>{label}</dt>
            <dd>{info[key] ?? 'not found (start the tracker to detect it)'}</dd>
            {key === 'log_db' ? (
              <a className="settings-quiet-link" href="#/audit">
                Database health
              </a>
            ) : null}
          </div>
        ))}
      </dl>
    </>
  );
}

type BadgeTone = 'on' | 'off' | 'update' | 'warn';

function StatusBadge({ tone, children }: { tone: BadgeTone; children: string }) {
  return <Badge className={`settings-badge settings-badge-${tone}`}>{children}</Badge>;
}

function startupBadge(startup: StartupSettings | null) {
  if (!startup?.available) return undefined;
  return startup.start_at_login ? (
    <StatusBadge tone="on">Starts at sign-in</StatusBadge>
  ) : (
    <StatusBadge tone="off">Manual start</StatusBadge>
  );
}

function sessionsBadge(sessions: SessionSettings | null) {
  if (!sessions) return undefined;
  return (
    <StatusBadge tone="off">
      {sessions.break_hours ? `${sessions.break_hours} h break` : 'One per launch'}
    </StatusBadge>
  );
}

/** The update state when there is one; otherwise why this copy can't update itself. */
function UpdatesBadge({ settings }: { settings: UpdateSettings }) {
  const status = useSharedUpdateStatus().status;
  if (!settings.check) return <StatusBadge tone="off">Off</StatusBadge>;
  switch (status?.state) {
    case 'ready':
      return <StatusBadge tone="update">{settings.supported ? 'Ready to install' : 'Update available'}</StatusBadge>;
    case 'available':
    case 'downloading':
      return <StatusBadge tone="update">Update available</StatusBadge>;
    case 'up_to_date':
      return <StatusBadge tone="on">Up to date</StatusBadge>;
    case 'idle':
      // Checked, and no release has an update file yet: nothing newer.
      if (status.last_check) return <StatusBadge tone="on">Up to date</StatusBadge>;
      break;
    case 'error':
      return <StatusBadge tone="warn">Check failed</StatusBadge>;
    default:
      break;
  }
  if (settings.supported) return null;
  const kind = status?.install_kind ?? settings.install_kind;
  const reason = status?.reason;
  if (reason === 'source' || kind === 'source') return <StatusBadge tone="off">Update with git</StatusBadge>;
  if (reason === 'portable' || kind === 'windows-portable') return <StatusBadge tone="off">Portable copy</StatusBadge>;
  return <StatusBadge tone="off">Manual install</StatusBadge>;
}

/** On/off switch beside a feature card's title; it saves as soon as it flips. */
function FeatureSwitch({
  label,
  checked,
  busy,
  onChange,
}: {
  label: string;
  checked: boolean;
  busy: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      aria-checked={checked}
      aria-label={label}
      className="settings-switch"
      disabled={busy}
      role="switch"
      type="button"
      onClick={() => onChange(!checked)}
    >
      <span aria-hidden="true" className="settings-switch-track">
        <span className="settings-switch-thumb" />
      </span>
      {checked ? 'On' : 'Off'}
    </button>
  );
}

/** The Deck AI switch, and a warning beside it when it is on without a key. */
function deckAiBadge(deckAi: DeckAiSettings | null, busy: boolean, onChange: (next: boolean) => void) {
  if (!deckAi) return undefined;
  const noKey = deckAi.enabled && !deckAiProvider(deckAi)?.api_key.trim();
  return (
    <>
      <FeatureSwitch busy={busy} checked={deckAi.enabled} label="Deck AI" onChange={onChange} />
      {noKey ? <StatusBadge tone="warn">No API key</StatusBadge> : null}
    </>
  );
}

function creatorCount(creators: DeckFinderCreatorSettings): number {
  return creators.moxfield.length + creators.aetherhub.length + creators.tcgplayer.length + (creators.youtube?.length ?? 0);
}

function creatorsBadge(creators: DeckFinderCreatorSettings | null) {
  if (!creators) return undefined;
  const count = creatorCount(creators);
  return <StatusBadge tone="off">{`${count} creator${count === 1 ? '' : 's'}`}</StatusBadge>;
}

/** A labelled band of settings cards laid out in equal columns. */
/** columns 'split' is a wide card beside a narrower one (60/40). */
function SettingsGroup({ title, columns, children }: { title: string; columns: 1 | 2 | 'split'; children: ReactNode }) {
  return (
    <div className="settings-group">
      <h2 className="settings-group-heading">{title}</h2>
      <div className={`settings-grid settings-grid-${columns}`}>{children}</div>
    </div>
  );
}

// Most-used first. The descriptions say what each file is for.
const EXPORT_FORMATS: Array<{ format: CollectionExportFormat; label: string; note: string }> = [
  { format: 'csv', label: 'Moxfield (.csv)', note: "Moxfield's collection import" },
  { format: 'archidekt', label: 'Archidekt (.csv)', note: 'Exact printings, by Scryfall ID' },
  { format: 'txt', label: 'Card list (.txt)', note: 'Pastes into most sites' },
  { format: 'json', label: 'JSON (.json)', note: 'Every field, for scripts' },
];

function formatDuration(seconds: number | null): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.max(1, Math.round(seconds));
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

function triggerDownload(fileName: string): void {
  const link = document.createElement('a');
  link.href = collectionDownloadUrl(fileName);
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function CollectionExport({ platform, games }: { platform: PlatformSettings; games: number | null }) {
  const [job, setJob] = useState<CollectionExportJob | null>(null);
  const [running, setRunning] = useState(false);
  const [format, setFormat] = useState<CollectionExportFormat | null>(null);
  const pollRef = useRef<number | null>(null);
  // The scan finds the collection by cards the tracker has seen you play, so
  // it can't work before the first recorded game. Unknown (null) stays enabled.
  const needsGame = games === 0;
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
      duration_seconds: null,
      warning: null,
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
    setJob({ state: 'running', detail: 'Starting…', format, file: null, unique: null, total: null, duration_seconds: null, warning: null, error_code: null });
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

      <fieldset className="collection-export-formats" disabled={running || needsGame}>
        <legend className="collection-export-legend">File format</legend>
        <div className="collection-export-choices">
          {EXPORT_FORMATS.map((choice) => (
            <label key={choice.format} className="collection-export-choice">
              <input
                type="radio"
                name="collection-export-format"
                value={choice.format}
                checked={format === choice.format}
                onChange={() => setFormat(choice.format)}
              />
              <span className="collection-export-choice-text">
                <span className="collection-export-choice-label">{choice.label}</span>
                <span className="collection-export-choice-note">{choice.note}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="collection-export-actions">
        <button
          className="deck-export-button collection-export-run"
          type="button"
          disabled={running || needsGame || format === null}
          onClick={() => format && runExport(format)}
        >
          Export collection
        </button>
        {format === null && !needsGame ? (
          <span className="collection-export-hint">Choose a format to export.</span>
        ) : null}
      </div>

      {needsGame ? (
        <p className="collection-export-status collection-export-warning" role="note">
          Play a game with the tracker running first. The export finds your collection by the cards
          it has seen you play.
        </p>
      ) : null}

      {job && job.state === 'running' ? (
        <p className="collection-export-status" role="status" aria-busy="true">
          <span className="collection-export-spinner" aria-hidden="true" />
          {job.detail}
        </p>
      ) : null}

      {job && job.state === 'done' ? (
        <p className="collection-export-status collection-export-done" role="status">
          <span aria-hidden="true">✓</span>{' '}
          <span>
            Exported <strong>{(job.unique ?? 0).toLocaleString()}</strong> unique cards (
            {(job.total ?? 0).toLocaleString()} total)
            {formatDuration(job.duration_seconds)
              ? ` in ${formatDuration(job.duration_seconds)}`
              : ''}
            . Your download should start on its own
            {job.file ? (
              <>
                {' '}
                — if it doesn&rsquo;t,{' '}
                <a className="collection-export-download" href={collectionDownloadUrl(job.file)}>
                  download it here
                </a>
              </>
            ) : null}
            . A copy was also saved to your MTGA&nbsp;Tracker data folder.
          </span>
        </p>
      ) : null}

      {job && job.state === 'done' && job.warning ? (
        <p className="collection-export-status collection-export-warning" role="status">
          ⚠ {job.warning}
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
  const [startup, setStartup] = useState<StartupSettings | null>(null);
  const [overlay, setOverlay] = useState<OverlaySettings | null>(null);
  // undefined while loading; null when the tracker predates the updater.
  const [updates, setUpdates] = useState<UpdateSettings | null | undefined>(undefined);
  const [buyOnPaper, setBuyOnPaper] = useState<BuyOnPaperSettings | null>(null);
  const [sessions, setSessions] = useState<SessionSettings | null>(null);
  // The overlay, Buy on Paper and Deck AI switches sit in their card titles,
  // so the page owns saving them.
  const [overlayBusy, setOverlayBusy] = useState(false);
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const [buyOnPaperBusy, setBuyOnPaperBusy] = useState(false);
  const [buyOnPaperError, setBuyOnPaperError] = useState<string | null>(null);
  const [deckAiBusy, setDeckAiBusy] = useState(false);
  const [deckAiError, setDeckAiError] = useState<string | null>(null);

  async function changeOverlay(enabled: boolean) {
    setOverlayBusy(true);
    setOverlayError(null);
    try {
      setOverlay(await setOverlayEnabled(enabled));
    } catch (exc: unknown) {
      setOverlayError(exc instanceof Error ? exc.message : 'The overlay could not be changed');
    } finally {
      setOverlayBusy(false);
    }
  }

  async function changeBuyOnPaper(enabled: boolean) {
    setBuyOnPaperBusy(true);
    setBuyOnPaperError(null);
    try {
      setBuyOnPaper(await saveBuyOnPaperEnabled(enabled));
    } catch (exc: unknown) {
      setBuyOnPaperError(exc instanceof Error ? exc.message : 'Buy on Paper could not be changed');
    } finally {
      setBuyOnPaperBusy(false);
    }
  }

  // The switch saves only on/off, with the provider, keys and models as last
  // saved; unsaved edits in the form stay in the form for its Save button.
  async function changeDeckAi(enabled: boolean) {
    if (!deckAi) return;
    setDeckAiBusy(true);
    setDeckAiError(null);
    try {
      setDeckAi(
        await saveDeckAiSettings({
          enabled,
          provider: deckAi.provider,
          keys: Object.fromEntries(deckAi.providers.map((entry) => [entry.key, entry.api_key])),
          models: Object.fromEntries(deckAi.providers.map((entry) => [entry.key, entry.model])),
        }),
      );
    } catch (exc: unknown) {
      setDeckAiError(exc instanceof Error ? exc.message : 'Deck AI could not be changed');
    } finally {
      setDeckAiBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    fetchTrackerSettings()
      .then((settings) => {
        if (!cancelled) {
          setTrackerInfo(settings.tracker);
          setDeckAi(settings.deck_ai);
          setCreators(settings.deck_finder);
          setPlatform(settings.platform);
          setStartup(settings.startup);
          setOverlay(settings.overlay ?? null);
          setUpdates(settings.updates ?? null);
          setBuyOnPaper(settings.buy_on_paper ?? { enabled: true, cache_bytes: 0 });
          setSessions(settings.sessions ?? null);
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

  // Every card shows the load error, or a spinner until its settings arrive.
  function settingsBody<T>(value: T | null, render: (loaded: T) => ReactNode): ReactNode {
    if (error) return <p className="empty-state deckfinder-state">{error}</p>;
    if (value === null) {
      return (
        <p className="state-panel deckfinder-state" role="status" aria-busy="true">
          Loading...
        </p>
      );
    }
    return render(value);
  }

  return (
    <>
      <Section
        id="settings-tracker"
        title="Tracker"
        description="What this tracker watches and records. Refreshed every time it starts."
      >
        {settingsBody(trackerInfo, (info) => (
          <TrackerOverview info={info} deckAi={deckAi} />
        ))}
      </Section>

      <SettingsGroup title="General" columns={2}>
        <div className="settings-stack">
          <Section
            id="settings-startup"
            title="Startup"
            badge={startupBadge(startup)}
            description="When Tapps Tracker starts, and whether it opens the dashboard."
          >
            {settingsBody(startup, (loaded) => (
              <StartupForm initial={loaded} platform={platform} onChange={setStartup} />
            ))}
          </Section>

          {sessions ? (
            <Section
              id="settings-sessions"
              title="Sessions"
              badge={sessionsBadge(sessions)}
              description="One sitting of play, shown on the Live Scoreboard and in the Overview."
            >
              <SessionsForm initial={sessions} onChange={setSessions} />
            </Section>
          ) : null}
        </div>

        <Section
          id="settings-updates"
          title="Updates"
          badge={updates ? <UpdatesBadge settings={updates} /> : undefined}
          description="New releases from GitHub, verified before they install. Nothing installs until you choose Restart to update."
        >
          {error ? (
            <p className="empty-state deckfinder-state">{error}</p>
          ) : updates === undefined ? (
            <p className="state-panel deckfinder-state" role="status" aria-busy="true">
              Loading...
            </p>
          ) : updates === null ? (
            <p className="settings-hint settings-standalone-hint">This tracker does not report update settings.</p>
          ) : (
            <UpdatesForm initial={updates} onChange={setUpdates} />
          )}
        </Section>
      </SettingsGroup>

      <SettingsGroup title="Features" columns={2}>
        <Section
          id="settings-overlay"
          title="In-game overlay"
          badge={
            !overlay ? undefined : overlay.available ? (
              <FeatureSwitch busy={overlayBusy} checked={overlay.enabled} label="In-game overlay" onChange={(next) => void changeOverlay(next)} />
            ) : (
              <StatusBadge tone="off">Not in this build</StatusBadge>
            )
          }
          description="Your library, draw odds and land drops in a small window beside Arena. It reads only this tracker, never the game."
        >
          {settingsBody(overlay, (loaded) => (
            <OverlayDetails
              busy={overlayBusy}
              error={overlayError}
              overlay={loaded}
              platform={platform}
              onStart={() => void changeOverlay(true)}
            />
          ))}
        </Section>

        <Section
          id="settings-buy-on-paper"
          title="Buy on Paper"
          badge={
            buyOnPaper ? (
              <FeatureSwitch busy={buyOnPaperBusy} checked={buyOnPaper.enabled} label="Buy on Paper" onChange={(next) => void changeBuyOnPaper(next)} />
            ) : undefined
          }
          description="Price a deck in paper and open it at a card store, from Deck Finder, Deck Manager and deck pages."
        >
          {settingsBody(buyOnPaper, (loaded) => (
            <BuyOnPaperDetails error={buyOnPaperError} settings={loaded} />
          ))}
        </Section>

        <Section
          id="settings-deck-ai"
          title="Deck AI"
          badge={deckAiBadge(deckAi, deckAiBusy, (next) => void changeDeckAi(next))}
          description="Names your opponent's deck after each game, shown as the game's Opponent Deck Type."
        >
          {settingsBody(deckAi, (loaded) => (
            <>
              {deckAiError ? (
                <p className="collection-export-status collection-export-fail" role="alert">
                  {deckAiError}
                </p>
              ) : null}
              <DeckAiForm enabled={loaded.enabled} initial={loaded} onSaved={setDeckAi} />
            </>
          ))}
        </Section>

        <Section
          id="settings-creators"
          title="Deck Finder Creators"
          badge={creatorsBadge(creators)}
          description="Creators Deck Finder follows. One per line, with an optional short name after a pipe."
        >
          {settingsBody(creators, (loaded) => (
            <CreatorsForm initial={loaded} onSaved={setCreators} />
          ))}
        </Section>
      </SettingsGroup>

      <SettingsGroup title="Streaming" columns={1}>
        <Section
          id="settings-streaming"
          title="Stream Kit"
          description="Widgets for OBS and Streamlabs that show viewers your overlay, deck, record, recent games, matchup and the cards being cast."
        >
          <StreamKitSettings />
        </Section>
      </SettingsGroup>

      <SettingsGroup title="Your data" columns={platform?.collection_export ? 'split' : 1}>
        <Section
          id="settings-backup"
          title="Backup & restore"
          description="Games, settings, Deck Finder creators and overlay preferences in one file, to keep safe or move to another computer."
        >
          <BackupCard />
        </Section>

        {platform?.collection_export ? (
          <Section
            id="settings-collection-export"
            title="Export MTGA Collection"
            description="Read your card collection from the running game for Moxfield, Archidekt and similar sites."
          >
            <CollectionExport platform={platform} games={trackerInfo?.games ?? null} />
          </Section>
        ) : null}
      </SettingsGroup>
    </>
  );
}

function StartupForm({
  initial,
  platform,
  onChange,
}: {
  initial: StartupSettings;
  platform: PlatformSettings | null;
  onChange?: (next: StartupSettings) => void;
}) {
  const [startup, setStartup] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loginLabel =
    platform?.system === 'macos'
      ? 'Start with macOS'
      : platform?.system === 'windows'
        ? 'Start with Windows'
        : 'Start at login';

  async function update(
    change: Partial<Pick<StartupSettings, 'start_at_login' | 'open_dashboard_on_launch'>>,
  ) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await saveStartupSettings(change);
      setStartup(saved);
      onChange?.(saved);
      setMessage('Saved. The change applies the next time Tapps Tracker launches.');
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'The startup setting could not be saved');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-form startup-settings">
      <label className="settings-check">
        <input
          checked={startup.start_at_login}
          disabled={busy || !startup.available}
          type="checkbox"
          onChange={(event) => void update({ start_at_login: event.target.checked })}
        />
        {loginLabel}
      </label>
      <p className="settings-hint">
        Start Tapps Tracker in the {platform?.system === 'macos' ? 'menu bar' : 'system tray'} when
        you sign in, so tracking is ready before you queue.
      </p>

      <label className="settings-check">
        <input
          checked={startup.open_dashboard_on_launch}
          disabled={busy}
          type="checkbox"
          onChange={(event) => void update({ open_dashboard_on_launch: event.target.checked })}
        />
        Open dashboard on launch
      </label>
      <p className="settings-hint">
        When off, tracking still starts and the dashboard remains available from the Tapps Tracker
        menu.
      </p>

      {!startup.available ? (
        <p className="settings-hint" role="status">
          Start at login is available on Windows and macOS.
        </p>
      ) : startup.start_at_login && !startup.registered ? (
        <p className="collection-export-status collection-export-warning" role="status">
          Start at login is saved, but its operating-system registration is missing.
        </p>
      ) : null}
      {startup.error ? (
        <p className="collection-export-status collection-export-warning" role="status">
          {startup.error}
        </p>
      ) : null}
      {message ? (
        <p className="backup-note backup-note-done startup-save-status" role="status">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function updateStateText(status: UpdateStatus | null): string {
  if (!status) {
    return 'Update status is not available right now.';
  }
  const latest = displayVersion(status.latest_version);
  const newer =
    status.latest_version !== null && isNewerVersion(status.latest_version, status.current_version);
  switch (status.state) {
    case 'idle':
      // A finished check that found no update file: the newest published
      // release predates the updater, so nothing newer can be installed.
      return status.last_check ? 'Tapps Tracker is up to date.' : 'Not checked yet.';
    case 'checking':
      return 'Checking for updates…';
    case 'up_to_date':
      return 'Tapps Tracker is up to date.';
    case 'available':
      return status.skipped ? `${latest} is available (skipped).` : `${latest} is available.`;
    case 'downloading':
      return updatePillModel(status).label;
    case 'ready':
      return status.pending_install
        ? `${latest} is downloaded and verified. It will install after this game.`
        : `${latest} is downloaded and verified.`;
    case 'installing':
      return 'Restarting…';
    case 'error':
      return status.error?.message ? `Update failed: ${status.error.message}` : 'Update failed.';
    case 'disabled':
      return 'Automatic checks are off. Check now looks once.';
    case 'unsupported':
      return newer ? `${latest} is available.` : 'This copy cannot update itself.';
    default:
      return '';
  }
}

function formatCheckTime(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
}

function UpdatesForm({
  initial,
  onChange,
}: {
  initial: UpdateSettings;
  onChange?: (next: UpdateSettings) => void;
}) {
  const controller = useSharedUpdateStatus();
  const [updates, setUpdates] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const status = controller.status;

  async function update(change: UpdateSettingsChange) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await saveUpdateSettings(change);
      setUpdates(saved);
      onChange?.(saved);
      setMessage('Saved.');
      void controller.refresh();
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'The update setting could not be saved');
    } finally {
      setBusy(false);
    }
  }

  async function skip(version: string | null) {
    await controller.skip(version);
    setUpdates((current) => ({ ...current, skipped_version: version }));
  }

  const automatic = updates.check && updates.supported;
  const state = status?.state;
  const working = busy || controller.busy;
  const moving = state === 'checking' || state === 'downloading' || state === 'installing';
  const latest = status?.latest_version ?? null;
  const offerable = status !== null && latest !== null && isNewerVersion(latest, status.current_version);
  const canDownload = status?.state === 'available' && status.can_install;
  const canInstall = status?.state === 'ready' && status.can_install;
  const skipped = Boolean(status?.skipped || updates.skipped_version);
  const lastCheck = formatCheckTime(status?.last_check ?? null);

  return (
    <div className="settings-form update-settings">
      <label className="settings-check">
        <input
          checked={updates.check}
          disabled={busy}
          type="checkbox"
          onChange={(event) => void update({ check: event.target.checked })}
        />
        Check for updates automatically
      </label>
      <p className="settings-hint">
        One small request to GitHub at startup and every few hours. No account, nothing about you or
        your games is sent.
      </p>

      <label className="settings-check">
        <input
          checked={updates.auto_download}
          disabled={busy || !automatic}
          type="checkbox"
          onChange={(event) => void update({ auto_download: event.target.checked })}
        />
        Download updates automatically
      </label>
      <p className="settings-hint">When off, the sidebar offers a Download button instead.</p>

      <label className="settings-check">
        <input
          checked={updates.auto_install}
          disabled={busy || !automatic}
          type="checkbox"
          onChange={(event) => void update({ auto_install: event.target.checked })}
        />
        Install updates automatically when no game is running
      </label>
      <p className="settings-hint">Only while MTG Arena is closed. Your game history is backed up first.</p>

      {!updates.supported ? (
        <p className="settings-hint update-unsupported" role="note">
          {updateReasonText(status?.reason, updates.install_kind)}
        </p>
      ) : null}

      <div className="update-status-row">
        <dl className="settings-info update-status-versions">
          <div className="settings-info-row">
            <dt>Installed</dt>
            <dd>{displayVersion(status?.current_version) || '—'}</dd>
          </div>
          <div className="settings-info-row">
            <dt>Latest</dt>
            <dd>
              {latest ? (
                status?.notes_url ? (
                  <a href={status.notes_url} rel="noreferrer" target="_blank">
                    {displayVersion(latest)}
                  </a>
                ) : (
                  displayVersion(latest)
                )
              ) : (
                '—'
              )}
            </dd>
          </div>
          {lastCheck ? (
            <div className="settings-info-row">
              <dt>Last checked</dt>
              <dd>{lastCheck}</dd>
            </div>
          ) : null}
        </dl>
        <p className="settings-hint update-state" role="status">
          {updateStateText(status)}
        </p>
        <div className="update-actions">
          <button
            className="deck-neutral-button"
            disabled={working || moving}
            type="button"
            onClick={() => void controller.check()}
          >
            Check now
          </button>
          {canDownload ? (
            <button
              className="deck-export-button"
              disabled={working}
              type="button"
              onClick={() => void controller.download()}
            >
              Download
            </button>
          ) : null}
          {canInstall ? (
            <button
              className="deck-export-button"
              disabled={working}
              title={status?.needs_elevation ? 'Windows will ask for permission' : undefined}
              type="button"
              onClick={() => void controller.install()}
            >
              Restart to update
            </button>
          ) : null}
          {status && !status.mandatory && offerable && !skipped && state !== 'installing' ? (
            <button
              className="deck-neutral-button"
              disabled={working}
              type="button"
              onClick={() => void skip(latest)}
            >
              Skip this version
            </button>
          ) : null}
          {skipped && !status?.mandatory ? (
            <button
              className="deck-neutral-button"
              disabled={working}
              type="button"
              onClick={() => void skip(null)}
            >
              Un-skip
            </button>
          ) : null}
        </div>
        {controller.notice?.kind === 'game' ? (
          <div className="update-actions">
            <p className="collection-export-status collection-export-warning" role="status">
              {controller.notice.text}
            </p>
            <button
              className="deck-neutral-button"
              disabled={working}
              type="button"
              onClick={() => void controller.installAfterGame()}
            >
              Install after this game
            </button>
          </div>
        ) : controller.notice ? (
          <p className="collection-export-status collection-export-warning" role="alert">
            {controller.notice.text}
          </p>
        ) : null}
        {status?.db_newer_than_app ? (
          <p className="collection-export-status collection-export-warning" role="alert">
            Database is newer than this version. Update Tapps Tracker before recording more games.
          </p>
        ) : null}
      </div>

      {message ? (
        <p className="backup-note backup-note-done startup-save-status" role="status">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function OverlayDetails({
  overlay,
  platform,
  busy,
  error,
  onStart,
}: {
  overlay: OverlaySettings;
  platform: PlatformSettings | null;
  busy: boolean;
  error: string | null;
  onStart: () => void;
}) {
  const macos = platform?.system === 'macos';
  // One sentence of state under the title's switch. "Off" is the whole story
  // for people who never want the overlay: no process runs and none will start.
  const state = !overlay.available
    ? { tone: 'off', text: 'Release builds ship the overlay. From a checkout, run scripts/build_overlay.sh first.' }
    : overlay.running
      ? { tone: 'on', text: 'Running now. It shows itself when Arena is up.' }
      : overlay.enabled
        ? { tone: 'stopped', text: 'Not running right now. It starts with the tracker next time.' }
        : { tone: 'off', text: 'Nothing runs. Turn it on to launch it now and with the tracker from then on.' };

  return (
    <div className="feature-body">
      <p className={`feature-status feature-status-${state.tone}`} role="status">
        <span aria-hidden="true" className="feature-dot" />
        {state.text}
        {overlay.available && overlay.enabled && !overlay.running ? (
          <button className="deck-export-button" disabled={busy} type="button" onClick={onStart}>
            Start now
          </button>
        ) : null}
      </p>
      {overlay.available ? (
        <div className="feature-keys">
          <span className="overlay-key">
            Deck panel <kbd>{macos ? '⌥⇧T' : 'Alt+Shift+T'}</kbd>
          </span>
          <span className="overlay-key">
            Hide / show <kbd>{macos ? '⌥⇧H' : 'Alt+Shift+H'}</kbd>
          </span>
          <span className="overlay-key overlay-key-note">
            Looks and behaviour: the overlay's ⚙ menu. Also in the menu bar: Start / Stop Overlay.
          </span>
        </div>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function formatMegabytes(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function sessionBreakLabel(hours: number): string {
  if (hours === 0) return 'Only when the app opens';
  return `After ${hours} hour${hours === 1 ? '' : 's'} without a game`;
}

function SessionsForm({
  initial,
  onChange,
}: {
  initial: SessionSettings;
  onChange?: (next: SessionSettings) => void;
}) {
  const [settings, setSettings] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function update(hours: number) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await saveSessionSettings(hours);
      setSettings(saved);
      onChange?.(saved);
      setMessage('Saved. It applies from the next match.');
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'The session setting could not be saved');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-form">
      <label className="settings-field">
        <span>Start a new session</span>
        <select disabled={busy} value={settings.break_hours} onChange={(event) => void update(Number(event.target.value))}>
          {settings.choices.map((hours) => (
            <option key={hours} value={hours}>
              {sessionBreakLabel(hours)}
            </option>
          ))}
        </select>
      </label>
      <p className="settings-hint">
        Opening the app always starts a new session. With a break set, a match that starts that long
        after your last game starts one too, so leaving the app running for days doesn't pile every
        night into one record. A Best-of-3 match always stays in one session.
      </p>
      {message ? (
        <p className="backup-note backup-note-done startup-save-status" role="status">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function BuyOnPaperDetails({ settings, error }: { settings: BuyOnPaperSettings; error: string | null }) {
  const stored = settings.cache_bytes > 0 ? ` Saved price lists use ${formatMegabytes(settings.cache_bytes)}.` : '';
  return (
    <div className="feature-body">
      {settings.enabled ? (
        <>
          <p className="feature-text" role="status">
            Decks show a Buy on Paper button. To price cards, the tracker downloads Card Kingdom’s and
            Mana Pool’s public price lists (about 120 MB together) the first time you open it each day,
            and keeps a small summary in its data folder. TCGplayer prices come from Scryfall.{stored}
          </p>
          <p className="feature-keys">
            Turning it off hides the button, stops any download in progress and deletes the saved price
            lists.
          </p>
        </>
      ) : (
        <p className="feature-text" role="status">
          No button and no price downloads. The saved price lists have been deleted.
        </p>
      )}
      {error ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface ModelList {
  status: 'loading' | 'ready' | 'error';
  /** The key the list was loaded with. */
  key: string;
  models: DeckAiModel[];
  error?: string;
}

function DeckAiForm({
  enabled,
  initial,
  onSaved,
}: {
  /** On/off belongs to the switch in the card title; Save keeps it as it is. */
  enabled: boolean;
  initial: DeckAiSettings;
  onSaved?: (next: DeckAiSettings) => void;
}) {
  const [provider, setProvider] = useState(initial.provider);
  const [keys, setKeys] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.providers.map((entry) => [entry.key, entry.api_key])),
  );
  const [models, setModels] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.providers.map((entry) => [entry.key, entry.model])),
  );
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<SaveStatus>('idle');
  // The saved provider's list starts loading as the form opens.
  const [modelLists, setModelLists] = useState<Record<string, ModelList>>(() => {
    const savedKey = (keys[initial.provider] ?? '').trim();
    return savedKey ? { [initial.provider]: { status: 'loading', key: savedKey, models: [] } } : {};
  });
  const latestRequest = useRef<Record<string, number>>({});

  const active = initial.providers.find((entry) => entry.key === provider) ?? initial.providers[0];
  const list = modelLists[provider];
  const key = (keys[provider] ?? '').trim();
  const model = models[provider] ?? '';

  function requestModels(target: string, apiKey: string) {
    const request = (latestRequest.current[target] ?? 0) + 1;
    latestRequest.current[target] = request;
    fetchDeckAiModels(target, apiKey)
      .then((loaded) => {
        if (latestRequest.current[target] !== request) return;
        setModelLists((current) => ({
          ...current,
          [target]: { status: 'ready', key: apiKey, models: loaded },
        }));
      })
      .catch((reason: unknown) => {
        if (latestRequest.current[target] !== request) return;
        setModelLists((current) => ({
          ...current,
          [target]: {
            status: 'error',
            key: apiKey,
            models: [],
            error: reason instanceof Error ? reason.message : String(reason),
          },
        }));
      });
  }

  function loadModels(target: string, apiKey: string) {
    setModelLists((current) => ({
      ...current,
      [target]: { status: 'loading', key: apiKey, models: current[target]?.models ?? [] },
    }));
    requestModels(target, apiKey);
  }

  useEffect(() => {
    const saved = initial.providers.find((entry) => entry.key === initial.provider);
    const savedKey = (saved?.api_key ?? '').trim();
    if (savedKey) {
      requestModels(initial.provider, savedKey);
    }
    // Once, for the saved provider; the state above already says loading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A provider with a key loads its list the first time it is picked; a key
  // typed in later loads it when the field loses focus.
  function changeProvider(next: string) {
    setProvider(next);
    const nextKey = (keys[next] ?? '').trim();
    if (nextKey && !modelLists[next]) {
      loadModels(next, nextKey);
    }
  }

  function keyCommitted() {
    if (key && list?.key !== key) {
      loadModels(provider, key);
    }
  }

  async function save() {
    setStatus('saving');
    try {
      await saveDeckAiSettings({ enabled, provider, keys, models });
      onSaved?.({
        enabled,
        provider,
        providers: initial.providers.map((entry) => ({
          ...entry,
          api_key: keys[entry.key] ?? '',
          model: models[entry.key] ?? '',
        })),
      });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  const setModel = (value: string) =>
    setModels((current) => ({ ...current, [provider]: value }));
  const showList = list !== undefined && list.models.length > 0 && list.status !== 'error';
  const listed = new Set(list?.models.map((entry) => entry.id) ?? []);

  return (
    <div className="settings-form">
      <label className="settings-field">
        <span>Provider</span>
        <select value={provider} onChange={(event) => changeProvider(event.target.value)}>
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
            onBlur={keyCommitted}
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
        <div className="settings-key-row">
          {showList ? (
            <select value={model} onChange={(event) => setModel(event.target.value)}>
              <option value="">Default ({active?.default_model})</option>
              {model && !listed.has(model) ? (
                <option value={model}>{model} (not in your list)</option>
              ) : null}
              {list.models.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label === entry.id ? entry.id : `${entry.label} (${entry.id})`}
                </option>
              ))}
            </select>
          ) : (
            <input
              placeholder={active?.default_model ?? ''}
              spellCheck={false}
              type="text"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          )}
          <button
            className="quick-filter"
            disabled={!key || list?.status === 'loading'}
            type="button"
            onClick={() => loadModels(provider, key)}
          >
            {list?.status === 'loading' ? 'Loading…' : showList ? 'Refresh' : 'Load models'}
          </button>
        </div>
      </label>
      <p className="settings-hint" role="status">
        {list?.status === 'error'
          ? `${list.error} Type a model name instead, or `
          : list?.status === 'ready' && list.models.length === 0
            ? `${active?.label} listed no models for this key. Type a model name, or `
            : showList
              ? `Models your key can use, from ${active?.label}. Compare them on `
              : key
                ? 'Leave blank for the default. Compare models on '
                : 'Enter an API key to choose from your models, or compare them on '}
        {active?.models_url ? (
          <a href={active.models_url} rel="noreferrer" target="_blank">
            {active.label}'s model page
          </a>
        ) : (
          "the provider's model page"
        )}
        .
      </p>
      <p className="settings-hint">
        One small request after each game, in the background, carrying only the names of the cards
        your opponent revealed (at least three) — never your deck, account or log. The key is kept
        in settings.json and goes nowhere else.
      </p>

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

function CreatorsForm({
  initial,
  onSaved,
}: {
  initial: DeckFinderCreatorSettings;
  onSaved?: (next: DeckFinderCreatorSettings) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => ({
    moxfield: creatorLines(initial.moxfield),
    aetherhub: creatorLines(initial.aetherhub),
    tcgplayer: creatorLines(initial.tcgplayer),
    youtube: creatorLines(initial.youtube ?? []),
  }));
  const [status, setStatus] = useState<SaveStatus>('idle');

  async function save() {
    setStatus('saving');
    try {
      const saved = {
        moxfield: parseCreatorLines(drafts.moxfield ?? ''),
        aetherhub: parseCreatorLines(drafts.aetherhub ?? ''),
        tcgplayer: parseCreatorLines(drafts.tcgplayer ?? ''),
        youtube: parseCreatorLines(drafts.youtube ?? ''),
      };
      await saveDeckFinderCreators(saved);
      onSaved?.({ ...initial, ...saved });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  // Size each editor to its content so nothing scrolls out of view; the
  // side-by-side sites share the tallest one's height so they line up.
  const lineRows = (key: string) => Math.max((drafts[key] ?? '').split('\n').length + 1, 3);
  const siteRows = Math.max(...CREATOR_SITES.filter(([key]) => key !== 'youtube').map(([key]) => lineRows(key)));

  function creatorField(key: string, label: string) {
    const value = drafts[key] ?? '';
    const rows = key === 'youtube' ? lineRows(key) : siteRows;
    return (
      <label key={key} className="settings-field">
        <span>{label}</span>
        <textarea
          placeholder={key === 'youtube' ? '@HelloGoodGame | HGG\n@SlothMtg | Sloth' : 'CreatorName | Short name'}
          rows={rows}
          spellCheck={false}
          value={value}
          onChange={(event) => setDrafts((current) => ({ ...current, [key]: event.target.value }))}
        />
      </label>
    );
  }

  return (
    <div className="settings-form">
      {/* Short creator names sit side by side; YouTube's channel links need the full width. */}
      <div className="settings-creator-sites">
        {CREATOR_SITES.filter(([key]) => key !== 'youtube').map(([key, label]) => creatorField(key, label))}
      </div>
      {CREATOR_SITES.filter(([key]) => key === 'youtube').map(([key, label]) => creatorField(key, label))}
      <p className="settings-hint">
        For YouTube, enter a channel URL or @handle: “@SlothMtg | Sloth” adds “(Sloth)” to imported
        deck names.
      </p>
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
