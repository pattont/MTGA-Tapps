/**
 * In-app update status: the `/api/update` contract, its actions, and the pure
 * presentation model behind the sidebar pill and Settings → Updates.
 *
 * The tracker owns checking, downloading, verifying and installing; the
 * dashboard only renders what `/api/update` reports and asks for actions. Any
 * payload that does not look like an update status (an older tracker, a test
 * stub that answers every URL with the snapshot) renders nothing.
 */

export const UPDATE_STATES = [
  'idle',
  'checking',
  'up_to_date',
  'available',
  'downloading',
  'ready',
  'installing',
  'error',
  'disabled',
  'unsupported',
] as const;
export type UpdateState = (typeof UPDATE_STATES)[number];

export type UpdateInstallKind =
  | 'macos-app'
  | 'windows-installer'
  | 'windows-portable'
  | 'source'
  | 'linux'
  | 'unknown';

export type UpdateReason =
  | 'source'
  | 'portable'
  | 'dashboard-only'
  | 'unsupported-platform'
  | 'unknown-version'
  | 'manual-required'
  | 'moved-install'
  | 'translocated'
  | 'not-writable';

export type UpdateBlocker =
  | 'game-in-progress'
  | 'arena-running'
  | 'deck-transfer'
  | 'collection-export'
  | 'backup-restore';

export interface UpdateProgress {
  received: number;
  total: number;
  fraction: number;
}

export interface UpdateJustUpdated {
  from: string;
  to: string;
  notes_url: string | null;
  ok: boolean;
}

export interface UpdateStatus {
  state: UpdateState;
  current_version: string;
  latest_version: string | null;
  notes_url: string | null;
  released_at: string | null;
  mandatory: boolean;
  below_minimum: boolean;
  install_kind: UpdateInstallKind;
  can_install: boolean;
  reason: UpdateReason | null;
  needs_elevation?: boolean;
  progress: UpdateProgress | null;
  error: { code: string; message: string } | null;
  last_check: string | null;
  skipped: boolean;
  auto_download: boolean;
  auto_install: boolean;
  pending_install: boolean;
  blocked_by: UpdateBlocker[];
  just_updated: UpdateJustUpdated | null;
  db_newer_than_app?: boolean;
}

/** The `updates` section of `GET /api/settings`. */
export interface UpdateSettings {
  check: boolean;
  auto_download: boolean;
  auto_install: boolean;
  channel: 'stable';
  skipped_version: string | null;
  /** Whether this copy can update itself (frozen installed build). */
  supported: boolean;
  install_kind: UpdateInstallKind | string;
}

export type UpdateSettingsChange = Partial<Pick<UpdateSettings, 'check' | 'auto_download' | 'auto_install'>>;

export type UpdateAction = 'check' | 'download' | 'install' | 'skip' | 'acknowledge';

export interface UpdateActionResult {
  ok: boolean;
  /** HTTP status; 0 when the request never got an answer. */
  status: number;
  code: string | null;
  error: string | null;
  blockedBy: UpdateBlocker[];
}

/** Where to send people when the payload has no release-notes link. */
export const RELEASES_URL = 'https://github.com/pattont/MTGA-Tapps/releases/latest';

const STATE_SET = new Set<string>(UPDATE_STATES);
const BLOCKERS = new Set<string>([
  'game-in-progress',
  'arena-running',
  'deck-transfer',
  'collection-export',
  'backup-restore',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringOrNull(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function parseProgress(value: unknown): UpdateProgress | null {
  if (!isRecord(value)) {
    return null;
  }
  const received = finiteNumber(value.received) ?? 0;
  const total = finiteNumber(value.total) ?? 0;
  let fraction = finiteNumber(value.fraction);
  if (fraction === null) {
    fraction = total > 0 ? received / total : 0;
  }
  return { received, total, fraction: Math.min(1, Math.max(0, fraction)) };
}

function parseJustUpdated(value: unknown): UpdateJustUpdated | null {
  if (!isRecord(value)) {
    return null;
  }
  const to = stringOrNull(value.to);
  if (!to) {
    return null;
  }
  return {
    from: stringOrNull(value.from) ?? '',
    to,
    notes_url: stringOrNull(value.notes_url),
    ok: value.ok !== false,
  };
}

/**
 * Normalize an `/api/update` payload. Returns null for anything that is not
 * recognizably an update status, so callers can render nothing.
 */
export function parseUpdateStatus(raw: unknown): UpdateStatus | null {
  if (!isRecord(raw) || typeof raw.state !== 'string' || !STATE_SET.has(raw.state)) {
    return null;
  }
  const error = isRecord(raw.error)
    ? {
        code: typeof raw.error.code === 'string' ? raw.error.code : 'error',
        message: typeof raw.error.message === 'string' ? raw.error.message : '',
      }
    : null;
  return {
    state: raw.state as UpdateState,
    current_version: typeof raw.current_version === 'string' ? raw.current_version : '',
    latest_version: stringOrNull(raw.latest_version),
    notes_url: stringOrNull(raw.notes_url),
    released_at: stringOrNull(raw.released_at),
    mandatory: raw.mandatory === true,
    below_minimum: raw.below_minimum === true,
    install_kind: (stringOrNull(raw.install_kind) ?? 'unknown') as UpdateInstallKind,
    can_install: raw.can_install === true,
    reason: stringOrNull(raw.reason) as UpdateReason | null,
    needs_elevation: raw.needs_elevation === true,
    progress: parseProgress(raw.progress),
    error,
    last_check: stringOrNull(raw.last_check),
    skipped: raw.skipped === true,
    auto_download: raw.auto_download === true,
    auto_install: raw.auto_install === true,
    pending_install: raw.pending_install === true,
    blocked_by: Array.isArray(raw.blocked_by)
      ? (raw.blocked_by.filter((item) => typeof item === 'string' && BLOCKERS.has(item)) as UpdateBlocker[])
      : [],
    just_updated: parseJustUpdated(raw.just_updated),
    db_newer_than_app: raw.db_newer_than_app === true,
  };
}

function versionParts(value: string): { release: number[]; pre: boolean } | null {
  const match = /^v?(\d+(?:\.\d+)*)(.*)$/i.exec(value.trim());
  if (!match) {
    return null;
  }
  return {
    release: match[1].split('.').map(Number),
    // "rc1", "a2", "b1", ".dev3" sort before the final release; "+local" does not.
    pre: /^[.-]?(a|b|c|rc|alpha|beta|pre|preview|dev)/i.test(match[2]),
  };
}

/**
 * True when `latest` is a newer release than `current`. Compares every
 * numeric segment (four-part hotfix tags included) and ranks pre-releases
 * below their final release. Unparseable input falls back to inequality.
 */
export function isNewerVersion(latest: string, current: string): boolean {
  const a = versionParts(latest);
  const b = versionParts(current);
  if (!a || !b) {
    return latest.trim() !== '' && latest.trim() !== current.trim();
  }
  const length = Math.max(a.release.length, b.release.length);
  for (let index = 0; index < length; index += 1) {
    const left = a.release[index] ?? 0;
    const right = b.release[index] ?? 0;
    if (left !== right) {
      return left > right;
    }
  }
  return b.pre && !a.pre;
}

export function displayVersion(version: string | null | undefined): string {
  if (!version) {
    return '';
  }
  return version.startsWith('v') ? version : `v${version}`;
}

/** Why this copy links out instead of updating itself. */
export function updateReasonText(reason: UpdateReason | string | null | undefined, installKind?: string | null): string {
  switch (reason) {
    case 'source':
      return 'Running from source — update with git';
    case 'portable':
      return 'Portable copy — download the new zip';
    case 'translocated':
    case 'not-writable':
      return 'Move Tapps Tracker to Applications, then update';
    case 'moved-install':
      return 'This install was moved; download the new installer';
    case 'manual-required':
      return 'Update manually — this version is too old to update in place';
    case 'dashboard-only':
      return 'Dashboard-only run — updates come with the Tapps Tracker app';
    case 'unsupported-platform':
      return 'Automatic updates are not available on this system — download the new release';
    case 'unknown-version':
      return 'This copy has no release version — download the new release';
    default:
      break;
  }
  if (installKind === 'source') {
    return 'Running from source — update with git';
  }
  if (installKind === 'windows-portable') {
    return 'Portable copy — download the new zip';
  }
  return 'Download the new release from GitHub';
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${bytes} B`;
}

export type UpdatePillKind = 'link' | 'download' | 'install' | 'progress' | 'retry' | 'none';

export interface UpdatePillModel {
  visible: boolean;
  label: string;
  kind: UpdatePillKind;
  href?: string;
  /** Whole-number download percentage, 0–100, while downloading. */
  percent?: number;
  title: string;
  /** False for mandatory updates: they can be postponed, never skipped. */
  skippable: boolean;
  /** Collapsed-sidebar icon button is shown for this state. */
  showCollapsed: boolean;
}

const HIDDEN: UpdatePillModel = {
  visible: false,
  label: '',
  kind: 'none',
  title: '',
  skippable: false,
  showCollapsed: false,
};

/** Pure presentation model for the sidebar pill; tolerates any input. */
export function updatePillModel(input: unknown): UpdatePillModel {
  const status = parseUpdateStatus(input);
  if (!status) {
    return HIDDEN;
  }
  const version = displayVersion(status.latest_version);
  const named = version ? ` ${version}` : '';
  const skippable = !status.mandatory && status.latest_version !== null;
  const base = { visible: true, skippable, showCollapsed: true };
  const linkOut = (): UpdatePillModel => ({
    ...base,
    label: `Update${named} available →`,
    kind: 'link',
    href: status.notes_url ?? RELEASES_URL,
    title: updateReasonText(status.reason, status.install_kind),
  });

  switch (status.state) {
    case 'available':
      if (status.skipped && !status.mandatory) {
        return HIDDEN;
      }
      if (!status.can_install) {
        return linkOut();
      }
      if (!status.auto_download) {
        return {
          ...base,
          label: `Update${named} available — Download`,
          kind: 'download',
          title: `Download${named} now`,
        };
      }
      return {
        ...base,
        label: `Update${named} available`,
        kind: 'download',
        title: 'The download starts by itself; click to start it now',
      };
    case 'downloading': {
      const progress = status.progress;
      const percent = progress ? Math.min(100, Math.max(0, Math.round(progress.fraction * 100))) : undefined;
      const title =
        progress && progress.total > 0
          ? `${formatBytes(progress.received)} of ${formatBytes(progress.total)}`
          : `Downloading${named}`;
      return {
        ...base,
        label: percent === undefined ? `Downloading${named}…` : `Downloading${named} — ${percent}%`,
        kind: 'progress',
        percent,
        title,
      };
    }
    case 'ready':
      if (!status.can_install) {
        return linkOut();
      }
      return {
        ...base,
        label: 'Restart to update',
        kind: 'install',
        title: status.needs_elevation
          ? 'Windows will ask for permission'
          : `Restart Tapps Tracker to update to${named || ' the new version'}`,
      };
    case 'installing':
      return { ...base, label: 'Restarting…', kind: 'none', title: `Installing${named}` };
    case 'error':
      return {
        ...base,
        label: 'Update failed — retry',
        kind: 'retry',
        title: status.error?.message || 'The update failed; click to check again',
      };
    case 'unsupported':
      // Copies that cannot update themselves still hear about a newer release.
      if (
        status.latest_version &&
        isNewerVersion(status.latest_version, status.current_version) &&
        !(status.skipped && !status.mandatory)
      ) {
        return { ...linkOut(), showCollapsed: false };
      }
      return HIDDEN;
    default:
      return HIDDEN;
  }
}

/** Text for a refused install (HTTP 409), by its `code`. */
export function installBlockedText(code: string | null, fallback?: string | null): string {
  switch (code) {
    case 'game-in-progress':
      return 'Finish your game first';
    case 'arena-running':
      return 'MTG Arena is open';
    case 'deck-transfer':
      return 'A Deck Manager transfer is running — try again when it finishes';
    case 'collection-export':
      return 'A collection export is running — try again when it finishes';
    case 'backup-restore':
      return 'A backup restore is running — try again when it finishes';
    case 'not-ready':
      return 'The update is not ready yet';
    default:
      return fallback || 'The update could not start';
  }
}

export const ARENA_RUNNING_CONFIRM =
  "Arena is open. The tracker will be offline for about 10 seconds; don't start a match until it's back.";

export async function fetchUpdateStatus(signal?: AbortSignal): Promise<UpdateStatus | null> {
  const response = await fetch('/api/update', { signal, cache: 'no-store' });
  if (!response.ok) {
    return null;
  }
  try {
    return parseUpdateStatus(await response.json());
  } catch {
    return null;
  }
}

/** POST an update action. Never throws: refusals and network errors come back as results. */
export async function postUpdateAction(
  action: UpdateAction,
  body: Record<string, unknown> = {},
): Promise<UpdateActionResult> {
  let response: Response;
  try {
    response = await fetch(`/api/update/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (exc: unknown) {
    return {
      ok: false,
      status: 0,
      code: null,
      error: exc instanceof Error ? exc.message : 'The tracker did not answer',
      blockedBy: [],
    };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const record = isRecord(payload) ? payload : {};
  return {
    ok: response.ok,
    status: response.status,
    code: typeof record.code === 'string' ? record.code : null,
    error: response.ok
      ? null
      : typeof record.error === 'string'
        ? record.error
        : `Update API returned ${response.status}`,
    blockedBy: Array.isArray(record.blocked_by)
      ? (record.blocked_by.filter((item) => typeof item === 'string' && BLOCKERS.has(item)) as UpdateBlocker[])
      : [],
  };
}

export async function saveUpdateSettings(change: UpdateSettingsChange): Promise<UpdateSettings> {
  const response = await fetch('/api/settings/updates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  });
  if (!response.ok) {
    let message = `Settings API returned ${response.status}`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) {
        message = body.error;
      }
    } catch {
      // keep the status message
    }
    throw new Error(message);
  }
  const body = (await response.json()) as { updates: UpdateSettings };
  return body.updates;
}
