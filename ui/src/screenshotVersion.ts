import { isNewerVersion, type UpdateStatus } from './updateStatus';

/**
 * `?screenshotVersion=0.7.8` (before the hash route) shows that version
 * wherever the dashboard prints the tracker's version, for screenshots taken
 * before the tag exists. It changes labels only: the package version, the
 * update check and every update action stay as they are.
 */
export function screenshotVersion(search: string = window.location.search): string | null {
  const value = new URLSearchParams(search).get('screenshotVersion');
  return value && /^\d+(?:\.\d+){1,3}$/.test(value) ? value : null;
}

/**
 * The update status as a copy running `version` would show it: that version
 * installed and, unless a newer one is published, the latest and up to date.
 * A download, install or error in progress is left alone.
 */
export function screenshotUpdateStatus(
  status: UpdateStatus | null,
  version: string | null,
): UpdateStatus | null {
  if (!status || !version) {
    return status;
  }
  const latest = status.latest_version;
  if (latest !== null && isNewerVersion(latest, version)) {
    return { ...status, current_version: version };
  }
  const settled = status.state === 'available' || status.state === 'idle' || status.state === 'up_to_date';
  return {
    ...status,
    current_version: version,
    latest_version: version,
    state: settled ? 'up_to_date' : status.state,
    skipped: false,
  };
}
