import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  ARENA_RUNNING_CONFIRM,
  fetchUpdateStatus,
  installBlockedText,
  postUpdateAction,
  type UpdateStatus,
} from '../updateStatus';

/** Poll cadence for `/api/update`: in-memory on the tracker side, so cheap. */
export const UPDATE_POLL_MS = 15_000;
/** While a download or install is moving, poll fast so the bar moves. */
export const UPDATE_FAST_POLL_MS = 1_000;
/** While installing, how often to ask whether the new version is answering. */
export const VERSION_POLL_MS = 2_000;

export interface UpdateNotice {
  /** `game`: refused because a game is running (offer "Install after this game"). */
  kind: 'game' | 'blocked';
  text: string;
}

export interface UpdateController {
  status: UpdateStatus | null;
  busy: boolean;
  notice: UpdateNotice | null;
  refresh: () => Promise<void>;
  check: () => Promise<void>;
  download: () => Promise<void>;
  /** Ask for an install now; resolves to the refusal notice, if any. */
  install: (body?: Record<string, unknown>) => Promise<UpdateNotice | null>;
  installAfterGame: () => Promise<void>;
  skip: (version: string | null) => Promise<void>;
  acknowledge: () => Promise<void>;
  clearNotice: () => void;
}

/** Lets the Settings page share the shell's poller instead of starting a second one. */
export const UpdateStatusContext = createContext<UpdateController | null>(null);

function isFast(status: UpdateStatus | null): boolean {
  return status?.state === 'downloading' || status?.state === 'installing';
}

/**
 * Polls `/api/update` (15 s, skipped while the tab is hidden; 1 s while
 * downloading or installing) and exposes the update actions. While
 * installing it also polls `/api/version` and reloads the tab once the
 * restarted tracker answers with a different version than the one first seen.
 */
export function useUpdateStatus({ enabled = true }: { enabled?: boolean } = {}): UpdateController {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<UpdateNotice | null>(null);
  const mounted = useRef(true);
  const baselineVersion = useRef<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchUpdateStatus();
      if (mounted.current) {
        setStatus(next);
      }
    } catch {
      // Keep the last status: during a restart the tracker is briefly away.
    }
  }, []);

  const pollVersion = useCallback(async () => {
    try {
      const response = await fetch('/api/version', { cache: 'no-store' });
      if (!response.ok) {
        return;
      }
      const payload = (await response.json()) as { version?: unknown } | null;
      const version = typeof payload?.version === 'string' ? payload.version : '';
      if (!version) {
        return;
      }
      if (baselineVersion.current === null) {
        baselineVersion.current = version;
      } else if (version !== baselineVersion.current && mounted.current) {
        window.location.reload();
      }
    } catch {
      // The old tracker has exited and the new one is not up yet.
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    fetchUpdateStatus()
      .then((next) => {
        if (!cancelled) {
          setStatus(next);
        }
      })
      .catch(() => {
        // The pill simply stays hidden until the next poll.
      });
    // Remember the running version early, so a fast restart is still noticed.
    void pollVersion();
    return () => {
      cancelled = true;
    };
  }, [enabled, pollVersion]);

  const fast = isFast(status);
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const id = window.setInterval(
      () => {
        if (!document.hidden) {
          void refresh();
        }
      },
      fast ? UPDATE_FAST_POLL_MS : UPDATE_POLL_MS,
    );
    return () => window.clearInterval(id);
  }, [enabled, fast, refresh]);

  const installing = status?.state === 'installing';
  useEffect(() => {
    if (!enabled || !installing) {
      return;
    }
    void pollVersion();
    const id = window.setInterval(() => void pollVersion(), VERSION_POLL_MS);
    return () => window.clearInterval(id);
  }, [enabled, installing, pollVersion]);

  const run = useCallback(
    async (work: () => Promise<void>) => {
      setBusy(true);
      try {
        await work();
      } finally {
        if (mounted.current) {
          setBusy(false);
        }
      }
    },
    [],
  );

  const simple = useCallback(
    (action: 'check' | 'download' | 'acknowledge', body: Record<string, unknown> = {}) =>
      run(async () => {
        setNotice(null);
        const result = await postUpdateAction(action, body);
        if (!result.ok && action !== 'acknowledge' && mounted.current) {
          setNotice({ kind: 'blocked', text: result.error ?? 'The tracker refused the request' });
        }
        await refresh();
      }),
    [refresh, run],
  );

  const install = useCallback(
    async (body: Record<string, unknown> = {}): Promise<UpdateNotice | null> => {
      setBusy(true);
      setNotice(null);
      try {
        let request = body;
        let result = await postUpdateAction('install', request);
        if (!result.ok && result.status === 409 && result.code === 'arena-running' && request.force !== true) {
          // Only Arena being open can be overridden, and only by the user.
          if (!window.confirm(ARENA_RUNNING_CONFIRM)) {
            return null;
          }
          request = { ...request, force: true };
          result = await postUpdateAction('install', request);
        }
        if (result.ok) {
          await refresh();
          return null;
        }
        const refusal: UpdateNotice =
          result.status === 409 && result.code === 'game-in-progress' && request.when !== 'idle'
            ? { kind: 'game', text: installBlockedText('game-in-progress') }
            : { kind: 'blocked', text: installBlockedText(result.code, result.error) };
        if (mounted.current) {
          setNotice(refusal);
        }
        await refresh();
        return refusal;
      } finally {
        if (mounted.current) {
          setBusy(false);
        }
      }
    },
    [refresh],
  );

  const installAfterGame = useCallback(async () => {
    await install({ when: 'idle' });
  }, [install]);

  const skip = useCallback(
    (version: string | null) =>
      run(async () => {
        setNotice(null);
        await postUpdateAction('skip', { version });
        await refresh();
      }),
    [refresh, run],
  );

  const check = useCallback(() => simple('check'), [simple]);
  const download = useCallback(() => simple('download'), [simple]);
  const acknowledge = useCallback(() => simple('acknowledge'), [simple]);
  const clearNotice = useCallback(() => setNotice(null), []);

  return useMemo(
    () => ({
      status,
      busy,
      notice,
      refresh,
      check,
      download,
      install,
      installAfterGame,
      skip,
      acknowledge,
      clearNotice,
    }),
    [status, busy, notice, refresh, check, download, install, installAfterGame, skip, acknowledge, clearNotice],
  );
}

/** The shell's shared controller when there is one, else a private poller. */
export function useSharedUpdateStatus(): UpdateController {
  const shared = useContext(UpdateStatusContext);
  const own = useUpdateStatus({ enabled: shared === null });
  return shared ?? own;
}
