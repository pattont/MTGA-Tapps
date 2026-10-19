import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ARENA_RUNNING_CONFIRM, type UpdateStatus } from '../updateStatus';
import { updateStatus } from '../test/updateFixtures';
import { UpdateIndicator, UpdateNotices } from './UpdateIndicator';
import { useUpdateStatus } from './useUpdateStatus';

function Harness({ collapsed = false }: { collapsed?: boolean }) {
  const controller = useUpdateStatus();
  return (
    <div className={collapsed ? 'sidebar-bottom sidebar-bottom-mini' : 'sidebar-bottom'}>
      <UpdateIndicator collapsed={collapsed} controller={controller} />
      <UpdateNotices controller={controller} />
    </div>
  );
}

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, status: 200, ...init });
}

interface Api {
  status: UpdateStatus;
  version: string;
  posts: Array<{ url: string; body: unknown; contentType: string | null }>;
  /** Answer for the next POST /api/update/install, consumed in order. */
  installReplies: Response[];
  fetch: ReturnType<typeof vi.fn>;
}

function stubApi(initial: Partial<UpdateStatus>): Api {
  const api: Api = {
    status: updateStatus(initial),
    version: '0.6.5.3',
    posts: [],
    installReplies: [],
    fetch: vi.fn(),
  };
  api.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === 'POST') {
      const headers = new Headers(init.headers);
      api.posts.push({ url: path, body: JSON.parse(String(init.body)), contentType: headers.get('Content-Type') });
      if (path === '/api/update/install') {
        return api.installReplies.shift() ?? json({ status: 'installing' }, { status: 202 });
      }
      return json({ ok: true }, { status: path.endsWith('acknowledge') ? 200 : 202 });
    }
    if (path === '/api/update') {
      return json(api.status);
    }
    if (path === '/api/version') {
      return json({ version: api.version });
    }
    return json({});
  });
  vi.stubGlobal('fetch', api.fetch);
  return api;
}

function updateGets(api: Api): number {
  return api.fetch.mock.calls.filter(([url, init]) => String(url) === '/api/update' && !init?.method).length;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('UpdateIndicator', () => {
  it('renders the expanded pill and the collapsed icon', async () => {
    stubApi({ state: 'ready' });
    const { unmount } = render(<Harness />);
    expect(await screen.findByRole('button', { name: 'Restart to update' })).toHaveClass('sidebar-update-install');
    unmount();

    render(<Harness collapsed />);
    const icon = await screen.findByRole('button', { name: 'Restart to update to v0.6.6' });
    expect(icon).toHaveClass('sidebar-update-mini');
    expect(icon).toHaveAttribute('title', 'Restart Tapps Tracker to update to v0.6.6');
  });

  it('renders nothing when up to date, and no collapsed icon for link-only copies', async () => {
    const api = stubApi({ state: 'up_to_date' });
    const { container, unmount } = render(<Harness />);
    await waitFor(() => expect(updateGets(api)).toBe(1));
    expect(container.querySelector('.sidebar-update, .sidebar-update-slot')).toBeNull();
    unmount();

    api.status = updateStatus({ state: 'unsupported', can_install: false, reason: 'source', install_kind: 'source' });
    const collapsed = render(<Harness collapsed />);
    await waitFor(() => expect(updateGets(api)).toBe(2));
    expect(collapsed.container.querySelector('.sidebar-update-mini')).toBeNull();
    collapsed.unmount();

    render(<Harness />);
    expect(await screen.findByRole('link', { name: 'Update v0.6.6 available →' })).toHaveAttribute(
      'title',
      'Running from source — update with git',
    );
  });

  it('posts install with a JSON body and content type', async () => {
    const api = stubApi({ state: 'ready' });
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: 'Restart to update' }));
    await waitFor(() => expect(api.posts).toHaveLength(1));
    expect(api.posts[0]).toEqual({ url: '/api/update/install', body: {}, contentType: 'application/json' });
  });

  it('offers "Install after this game" when a game is running', async () => {
    const api = stubApi({ state: 'ready' });
    api.installReplies.push(
      json({ error: 'A game is in progress', code: 'game-in-progress', blocked_by: ['game-in-progress'] }, { status: 409 }),
    );
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: 'Restart to update' }));
    expect(await screen.findByText('Finish your game first')).toBeInTheDocument();

    api.installReplies.push(json({ status: 'pending' }, { status: 202 }));
    api.status = updateStatus({ state: 'ready', pending_install: true });
    await user.click(screen.getByRole('button', { name: 'Install after this game' }));
    expect(await screen.findByText('Will install after this game')).toBeInTheDocument();
    expect(api.posts.map((post) => post.body)).toEqual([{}, { when: 'idle' }]);
    expect(screen.queryByText('Finish your game first')).toBeNull();
  });

  it('asks before installing while Arena is open, then forces', async () => {
    const api = stubApi({ state: 'ready' });
    api.installReplies.push(
      json({ error: 'Arena is running', code: 'arena-running', blocked_by: ['arena-running'] }, { status: 409 }),
    );
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: 'Restart to update' }));
    await waitFor(() => expect(api.posts).toHaveLength(2));
    expect(confirm).toHaveBeenCalledWith(ARENA_RUNNING_CONFIRM);
    expect(api.posts.map((post) => post.body)).toEqual([{}, { force: true }]);
  });

  it('does not force when the Arena warning is declined, and explains other refusals', async () => {
    const api = stubApi({ state: 'ready' });
    api.installReplies.push(
      json({ error: 'Arena is running', code: 'arena-running', blocked_by: ['arena-running'] }, { status: 409 }),
      json({ error: 'busy', code: 'deck-transfer', blocked_by: ['deck-transfer'] }, { status: 409 }),
    );
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup();
    render(<Harness />);
    const button = await screen.findByRole('button', { name: 'Restart to update' });
    await user.click(button);
    await waitFor(() => expect(api.posts).toHaveLength(1));
    await user.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A Deck Manager transfer is running — try again when it finishes',
    );
    expect(api.posts.map((post) => post.body)).toEqual([{}, {}]);
  });

  it('shows download progress as an accessible progress bar', async () => {
    stubApi({ state: 'downloading', progress: { received: 42, total: 100, fraction: 0.42 } });
    render(<Harness />);
    const bar = await screen.findByRole('progressbar', { name: 'Update download progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '42');
    expect(screen.getByText('Downloading v0.6.6 — 42%')).toBeInTheDocument();
  });

  it('starts a download when automatic download is off, and retries after an error', async () => {
    const api = stubApi({ state: 'available', auto_download: false });
    const user = userEvent.setup();
    const { unmount } = render(<Harness />);
    await user.click(await screen.findByRole('button', { name: 'Update v0.6.6 available — Download' }));
    await waitFor(() => expect(api.posts.map((post) => post.url)).toEqual(['/api/update/download']));
    unmount();

    api.status = updateStatus({ state: 'error', error: { code: 'network', message: 'GitHub did not answer' } });
    render(<Harness />);
    const retry = await screen.findByRole('button', { name: 'Update failed — retry' });
    expect(retry).toHaveAttribute('title', 'GitHub did not answer');
    await user.click(retry);
    await waitFor(() => expect(api.posts.map((post) => post.url)).toContain('/api/update/check'));
  });

  it('polls every 15 s, then every second while downloading', async () => {
    vi.useFakeTimers();
    const api = stubApi({ state: 'available' });
    render(<Harness />);
    await act(async () => {});
    expect(updateGets(api)).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_000);
    });
    expect(updateGets(api)).toBe(1);

    api.status = updateStatus({ state: 'downloading', progress: { received: 1, total: 4, fraction: 0.25 } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(updateGets(api)).toBe(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(updateGets(api)).toBe(5);

    // Back to the slow cadence once the download is done.
    api.status = updateStatus({ state: 'ready' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(updateGets(api)).toBe(6);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(updateGets(api)).toBe(6);
  });

  it('skips polls while the tab is hidden', async () => {
    vi.useFakeTimers();
    const api = stubApi({ state: 'available' });
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    render(<Harness />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(45_000);
    });
    expect(updateGets(api)).toBe(1);
    hidden.mockReturnValue(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(updateGets(api)).toBe(2);
  });

  it('shows "Updated to" once and acknowledges on dismiss', async () => {
    const api = stubApi({
      state: 'up_to_date',
      just_updated: { from: '0.6.5.3', to: '0.6.6', notes_url: 'https://example.test/notes', ok: true },
    });
    const user = userEvent.setup();
    render(<Harness />);
    expect(await screen.findByText(/Updated to v0\.6\.6/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: "What's new" })).toHaveAttribute('href', 'https://example.test/notes');
    await user.click(screen.getByRole('button', { name: 'Dismiss update notice' }));
    expect(screen.queryByText(/Updated to v0\.6\.6/)).toBeNull();
    await waitFor(() =>
      expect(api.posts).toEqual([{ url: '/api/update/acknowledge', body: {}, contentType: 'application/json' }]),
    );
  });

  it('warns when the database is newer than the app', async () => {
    stubApi({ state: 'up_to_date', db_newer_than_app: true });
    render(<Harness />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Database is newer than this version');
  });

  it('reloads the tab once the restarted tracker reports a new version', async () => {
    vi.useFakeTimers();
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    const api = stubApi({ state: 'installing' });
    render(<Harness />);
    await act(async () => {});
    expect(screen.getByText('Restarting…')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });
    expect(reload).not.toHaveBeenCalled();
    const versionPolls = api.fetch.mock.calls.filter(([url]) => String(url) === '/api/version').length;
    expect(versionPolls).toBeGreaterThanOrEqual(3);

    // The old process is gone for a moment, then the new one answers.
    api.fetch.mockImplementationOnce(async () => {
      throw new TypeError('Failed to fetch');
    });
    api.version = '0.6.6';
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(reload).toHaveBeenCalled();
  });
});
