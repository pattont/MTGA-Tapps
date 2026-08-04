/** Once-a-day check against GitHub Releases for a newer published version. */

const RELEASES_API = 'https://api.github.com/repos/pattont/MTGA-Tapps/releases/latest';
const CACHE_KEY = 'mtga-update-check';
const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;

export interface UpdateInfo {
  tag: string;
  url: string;
}

/** Parse "v0.3.0" / "0.3.0-alpha.1" into comparable numbers (main triplet only). */
function versionTriplet(value: string): [number, number, number] | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(value.trim());
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

export function isNewerVersion(latest: string, current: string): boolean {
  const a = versionTriplet(latest);
  const b = versionTriplet(current);
  if (!a || !b) {
    return false;
  }
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) {
      return a[i] > b[i];
    }
  }
  return false;
}

/**
 * Returns the newer release if one exists, else null. Rate-limited to one
 * GitHub API call per day via localStorage; network failures return null.
 */
export async function checkForUpdate(currentVersion: string): Promise<UpdateInfo | null> {
  let cached: { checkedAt: number; tag: string; url: string } | null;
  try {
    cached = JSON.parse(window.localStorage.getItem(CACHE_KEY) ?? 'null');
  } catch {
    cached = null;
  }
  let tag = cached?.tag ?? '';
  let url = cached?.url ?? '';
  const stale = !cached || Date.now() - cached.checkedAt > CHECK_INTERVAL_MS;
  if (stale) {
    try {
      const response = await fetch(RELEASES_API, {
        headers: { Accept: 'application/vnd.github+json' },
      });
      if (!response.ok) {
        return null;
      }
      const payload = (await response.json()) as { tag_name?: string; html_url?: string };
      tag = payload.tag_name ?? '';
      url = payload.html_url ?? '';
      window.localStorage.setItem(
        CACHE_KEY,
        JSON.stringify({ checkedAt: Date.now(), tag, url }),
      );
    } catch {
      return null;
    }
  }
  return tag && url && isNewerVersion(tag, currentVersion) ? { tag, url } : null;
}
