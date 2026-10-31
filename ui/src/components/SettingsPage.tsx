import { useEffect, useRef, useState } from 'react';
import { BackupCard } from './BackupCard';
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
  type DeckAiSettings,
  type DeckFinderCreator,
  type DeckFinderCreatorSettings,
  type PlatformSettings,
  type StartupSettings,
  type TrackerInfoSettings,
} from '../api';
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

const TRACKER_INFO_ROWS: Array<[keyof TrackerInfoSettings, string]> = [
  ['monitoring', 'Monitoring'],
  ['card_db', 'Local Card DB'],
  ['log_db', 'Log DB'],
  ['deck_ai', 'Deck AI'],
  ['version', 'Tracker Version'],
];

/** How long "Check for updates" waits for the tracker's answer. */
const VERSION_CHECK_TIMEOUT_MS = 15_000;
const VERSION_CHECK_POLL_MS = 1_000;

/** The result line after a manual check, from the updater's status. */
function versionCheckResult(status: UpdateStatus | null): { text: string; tone: 'ok' | 'update' | 'warn' } {
  if (!status) {
    return { text: 'Could not reach the tracker', tone: 'warn' };
  }
  const latest = status.latest_version;
  const newer = latest !== null && isNewerVersion(latest, status.current_version);
  switch (status.state) {
    case 'available':
    case 'downloading':
    case 'ready':
    case 'installing':
      return { text: `${displayVersion(latest)} is available`, tone: 'update' };
    case 'error':
      return { text: status.error?.message || 'The update check failed', tone: 'warn' };
    case 'idle':
      return latest === null
        ? { text: 'No release information was available', tone: 'warn' }
        : { text: "You're on the latest version", tone: 'ok' };
    default:
      return newer
        ? { text: `${displayVersion(latest)} is available`, tone: 'update' }
        : { text: "You're on the latest version", tone: 'ok' };
  }
}

/** A quiet "Check for updates" link at the end of the Tracker Version row. */
function VersionCheck() {
  const controller = useSharedUpdateStatus();
  const [phase, setPhase] = useState<'idle' | 'checking' | 'done'>('idle');
  const startedAt = useRef<string | null>(null);
  const deadline = useRef(0);
  const { status, refresh } = controller;

  useEffect(() => {
    if (phase !== 'checking') {
      return;
    }
    // Done once the updater has stamped a newer check and left "checking".
    if (status && status.state !== 'checking' && status.last_check !== startedAt.current) {
      setPhase('done');
      return;
    }
    if (Date.now() > deadline.current) {
      setPhase('done');
      return;
    }
    const id = window.setTimeout(() => void refresh(), VERSION_CHECK_POLL_MS);
    return () => window.clearTimeout(id);
  }, [phase, status, refresh]);

  async function check() {
    startedAt.current = status?.last_check ?? null;
    deadline.current = Date.now() + VERSION_CHECK_TIMEOUT_MS;
    setPhase('checking');
    await controller.check();
  }

  const result = phase === 'done' ? versionCheckResult(status) : null;
  return (
    <span className="settings-version-check">
      {result ? (
        <span className={`settings-version-result settings-version-result-${result.tone}`} role="status">
          {result.text}
        </span>
      ) : null}
      <button
        className="settings-version-check-button"
        disabled={phase === 'checking'}
        type="button"
        onClick={() => void check()}
      >
        {phase === 'checking' ? 'Checking…' : result ? 'Check again' : 'Check for updates'}
      </button>
    </span>
  );
}

function TrackerInfo({ info }: { info: TrackerInfoSettings }) {
  return (
    <dl className="settings-info">
      {TRACKER_INFO_ROWS.map(([key, label]) => (
        <div key={key} className="settings-info-row">
          <dt>{label}</dt>
          {key === 'version' ? (
            <dd className="settings-info-version">
              <span>{info[key] ?? 'not found (start the tracker to detect it)'}</span>
              <VersionCheck />
            </dd>
          ) : (
            <dd>{info[key] ?? 'not found (start the tracker to detect it)'}</dd>
          )}
        </div>
      ))}
    </dl>
  );
}

const EXPORT_FORMATS: Array<[CollectionExportFormat, string]> = [
  ['json', 'Export to .json'],
  ['csv', 'Export to .csv'],
  ['txt', 'Export to .txt'],
  ['archidekt', 'Export for Archidekt (.csv)'],
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
        id="settings-startup"
        title="Startup"
        description="Choose whether Tapps Tracker starts when you sign in and whether a launch opens the dashboard in your browser."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : startup === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading...
          </p>
        ) : (
          <StartupForm initial={startup} platform={platform} />
        )}
      </Section>

      {sessions ? (
        <Section
          id="settings-sessions"
          title="Sessions"
          description="A session is one sitting of play: its record shows on the Live Scoreboard and in the Overview's Sessions table."
        >
          <SessionsForm initial={sessions} />
        </Section>
      ) : null}

      <Section
        id="settings-updates"
        title="Updates"
        description="Tapps Tracker looks for a newer release on GitHub, downloads it in the background and verifies it against a signed manifest. Nothing installs until you choose Restart to update, unless you allow automatic installs below."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : updates === undefined ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading...
          </p>
        ) : updates === null ? (
          <p className="settings-hint">This tracker does not report update settings.</p>
        ) : (
          <UpdatesForm initial={updates} />
        )}
      </Section>

      <Section
        id="settings-overlay"
        title="In-game overlay"
        description="A small always-on-top window beside Arena with your library, per-card draw odds and land drops. It runs as its own small process, shows only while Arena is up, and reads only this tracker's local API — never the game."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : overlay === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading...
          </p>
        ) : (
          <OverlayForm initial={overlay} platform={platform} />
        )}
      </Section>

      <Section
        id="settings-buy-on-paper"
        title="Buy on Paper"
        description="Price a deck in paper and open it at a card store, from Deck Finder, Deck Manager and deck pages."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : buyOnPaper === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading...
          </p>
        ) : (
          <BuyOnPaperForm initial={buyOnPaper} />
        )}
      </Section>

      <Section
        id="settings-backup"
        title="Backup & restore"
        description="Everything the tracker knows — games, settings, Deck Finder creators, overlay preferences — in one file. Back up into a folder a sync client mirrors and restore it on another computer; restore the newer one back when you come home."
      >
        <BackupCard />
      </Section>

      <Section
        id="settings-deck-ai"
        title="Deck AI"
        description="Names your opponent's deck after each game: one small request to the provider you pick, in the background, carrying only the names of the cards they revealed (at least three) — never your deck, account, or log. The answer becomes the game's Opponent Deck Type. The key lives in settings.json and goes nowhere else."
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
        description="Which creators Deck Finder follows on Moxfield, Aetherhub, TCGplayer, and YouTube. One creator per line, with an optional short name after a pipe. For YouTube, enter a channel URL or @handle — “@SlothMtg | Sloth” adds “(Sloth)” to imported deck names."
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
          description="Read your full card collection from the running game and export it for Moxfield, Archidekt, and similar sites."
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

function StartupForm({
  initial,
  platform,
}: {
  initial: StartupSettings;
  platform: PlatformSettings | null;
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
      setStartup(await saveStartupSettings(change));
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
      // A finished check that found no manifest (no release published yet).
      return status.last_check ? 'No release information was available.' : 'Not checked yet.';
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

function UpdatesForm({ initial }: { initial: UpdateSettings }) {
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
      setUpdates(await saveUpdateSettings(change));
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

function OverlayForm({
  initial,
  platform,
}: {
  initial: OverlaySettings;
  platform: PlatformSettings | null;
}) {
  const [overlay, setOverlay] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function setEnabled(enabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      setOverlay(await setOverlayEnabled(enabled));
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'The overlay could not be changed');
    } finally {
      setBusy(false);
    }
  }

  const macos = platform?.system === 'macos';
  // One card, one sentence, one action. "Off" is the whole story for people
  // who never want the overlay: no process runs and none will start.
  const state = !overlay.available
    ? {
        tone: 'unavailable',
        title: 'Not in this build',
        detail: 'Release builds ship the overlay. From a checkout, run scripts/build_overlay.sh first.',
      }
    : overlay.running
      ? { tone: 'on', title: 'Overlay is on', detail: 'Running now, and it starts with the tracker. It shows itself when Arena is up.' }
      : overlay.enabled
        ? { tone: 'stopped', title: 'Overlay is on', detail: 'Not running right now — it starts with the tracker next time.' }
        : { tone: 'off', title: 'Overlay is off', detail: 'Nothing runs. Turn it on to launch it now and with the tracker from then on.' };

  return (
    <div className={`overlay-card overlay-card-${state.tone}`}>
      <div className="overlay-card-main">
        <span aria-hidden="true" className="overlay-card-dot" />
        <div className="overlay-card-text">
          <p className="overlay-card-title" role="status">
            {state.title}
          </p>
          <p className="overlay-card-detail">{state.detail}</p>
        </div>
        {overlay.available ? (
          <div className="overlay-card-actions">
            {overlay.running ? (
              <button className="deck-neutral-button" disabled={busy} type="button" onClick={() => void setEnabled(false)}>
                Turn off
              </button>
            ) : (
              <>
                <button className="deck-export-button" disabled={busy} type="button" onClick={() => void setEnabled(true)}>
                  {overlay.enabled ? 'Start now' : 'Turn on'}
                </button>
                {overlay.enabled ? (
                  <button className="deck-neutral-button" disabled={busy} type="button" onClick={() => void setEnabled(false)}>
                    Turn off
                  </button>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </div>
      {overlay.available ? (
        <div className="overlay-card-keys">
          <span className="overlay-key">
            Deck panel <kbd>{macos ? '⌥⇧T' : 'Alt+Shift+T'}</kbd>
          </span>
          <span className="overlay-key">
            Hide / show <kbd>{macos ? '⌥⇧H' : 'Alt+Shift+H'}</kbd>
          </span>
          <span className="overlay-key overlay-key-note">Looks and behaviour: the overlay's ⚙ menu. Also in the menu bar: Start / Stop Overlay.</span>
        </div>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail overlay-card-error" role="alert">
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

function SessionsForm({ initial }: { initial: SessionSettings }) {
  const [settings, setSettings] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function update(hours: number) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      setSettings(await saveSessionSettings(hours));
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

function BuyOnPaperForm({ initial }: { initial: BuyOnPaperSettings }) {
  const [settings, setSettings] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function setEnabled(enabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      setSettings(await saveBuyOnPaperEnabled(enabled));
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'Buy on Paper could not be changed');
    } finally {
      setBusy(false);
    }
  }

  const stored = settings.cache_bytes > 0 ? ` Saved price lists use ${formatMegabytes(settings.cache_bytes)}.` : '';
  return (
    <div className={`overlay-card overlay-card-${settings.enabled ? 'on' : 'off'}`}>
      <div className="overlay-card-main">
        <span aria-hidden="true" className="overlay-card-dot" />
        <div className="overlay-card-text">
          <p className="overlay-card-title" role="status">
            {settings.enabled ? 'Buy on Paper is on' : 'Buy on Paper is off'}
          </p>
          <p className="overlay-card-detail">
            {settings.enabled
              ? <>Decks show a Buy on Paper button. To price cards, the tracker downloads Card Kingdom’s and
                Mana Pool’s public price lists (about 120 MB together) the first time you open it each day,
                and keeps a small summary in its data folder. TCGplayer prices come from Scryfall.{stored}</>
              : 'No button and no price downloads. The saved price lists have been deleted.'}
          </p>
        </div>
        <div className="overlay-card-actions">
          {settings.enabled ? (
            <button aria-label="Turn off Buy on Paper" className="deck-neutral-button" disabled={busy} type="button" onClick={() => void setEnabled(false)}>
              Turn off
            </button>
          ) : (
            <button aria-label="Turn on Buy on Paper" className="deck-export-button" disabled={busy} type="button" onClick={() => void setEnabled(true)}>
              Turn on
            </button>
          )}
        </div>
      </div>
      {settings.enabled ? (
        <p className="overlay-card-keys buy-paper-settings-note">
          Turning it off hides the button, stops any download in progress and deletes the saved price lists.
        </p>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail overlay-card-error" role="alert">
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
    youtube: creatorLines(initial.youtube ?? []),
  }));
  const [status, setStatus] = useState<SaveStatus>('idle');

  async function save() {
    setStatus('saving');
    try {
      await saveDeckFinderCreators({
        moxfield: parseCreatorLines(drafts.moxfield ?? ''),
        aetherhub: parseCreatorLines(drafts.aetherhub ?? ''),
        tcgplayer: parseCreatorLines(drafts.tcgplayer ?? ''),
        youtube: parseCreatorLines(drafts.youtube ?? ''),
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
              placeholder={key === 'youtube' ? '@HelloGoodGame | HGG\n@SlothMtg | Sloth' : 'CreatorName | Short name'}
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
