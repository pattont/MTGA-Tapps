import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { UpdateSettings, UpdateStatus } from '../updateStatus';
import { updateStatus } from '../test/updateFixtures';
import { SettingsPage } from './SettingsPage';

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, status: 200, ...init });
}

function updateSettings(overrides: Partial<UpdateSettings> = {}): UpdateSettings {
  return {
    check: true,
    auto_download: true,
    auto_install: false,
    channel: 'stable',
    skipped_version: null,
    supported: true,
    install_kind: 'macos-app',
    ...overrides,
  };
}

function stubSettings({
  updates = updateSettings(),
  status = updateStatus({ state: 'available' }),
}: { updates?: UpdateSettings | null; status?: UpdateStatus } = {}) {
  const state = { updates, status };
  const posts: Array<{ url: string; body: unknown }> = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      posts.push({ url: path, body });
      if (path === '/api/settings/updates') {
        if (state.updates === null) {
          return json({ error: 'unknown' }, { status: 404 });
        }
        state.updates = { ...state.updates, ...body };
        return json({ updates: state.updates });
      }
      return json({ status: 'checking' }, { status: 202 });
    }
    if (path === '/api/settings') {
      return json({
        tracker: { monitoring: null, card_db: null, log_db: null, deck_ai: null, version: '0.6.5.3' },
        deck_ai: { enabled: false, provider: 'openai', providers: [{ key: 'openai', label: 'OpenAI', api_key: '', model: '', default_model: 'gpt-4o-mini' }] },
        deck_finder: { path: '/tmp/deckfinder_config.json', moxfield: [], aetherhub: [], tcgplayer: [], youtube: [] },
        platform: { system: 'macos', collection_export: false },
        startup: { start_at_login: false, open_dashboard_on_launch: true, available: true, registered: false, error: null },
        overlay: { enabled: false, available: false, running: false, binary: null, log: '/tmp/overlay.log', error: null },
        ...(state.updates ? { updates: state.updates } : {}),
      });
    }
    if (path === '/api/update') {
      return json(state.status);
    }
    if (path === '/api/backup') {
      return json({
        folder: null,
        detected_folders: [],
        default_folder: '/tmp/backups',
        machine: 'Mac',
        install_id: 'abc',
        last_backup: null,
        last_restore: null,
        backups: [],
        local: { schema_version: 35, games: 1, newest_game_at: null, oldest_game_at: null, sessions: 1 },
        tracker_active: false,
      });
    }
    return json({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return { state, posts, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function updatesSection() {
  const heading = await screen.findByRole('heading', { name: 'Updates' });
  const section = heading.closest('section') ?? heading.parentElement!.parentElement!;
  await within(section as HTMLElement).findByLabelText('Check for updates automatically');
  return section as HTMLElement;
}

describe('Settings → Updates', () => {
  it('sits between Startup and the overlay', async () => {
    stubSettings();
    render(<SettingsPage />);
    await updatesSection();
    const headings = screen.getAllByRole('heading').map((node) => node.textContent);
    expect(headings.indexOf('Startup')).toBeLessThan(headings.indexOf('Updates'));
    expect(headings.indexOf('Updates')).toBeLessThan(headings.indexOf('In-game overlay'));
  });

  it('saves each toggle to /api/settings/updates', async () => {
    const api = stubSettings();
    const user = userEvent.setup();
    render(<SettingsPage />);
    const section = await updatesSection();
    const scoped = within(section);
    expect(scoped.getByLabelText('Check for updates automatically')).toBeChecked();
    expect(scoped.getByLabelText('Download updates automatically')).toBeChecked();
    expect(scoped.getByLabelText('Install updates automatically when no game is running')).not.toBeChecked();
    expect(scoped.getByText('Only while MTG Arena is closed. Your game history is backed up first.')).toBeInTheDocument();

    await user.click(scoped.getByLabelText('Install updates automatically when no game is running'));
    await waitFor(() =>
      expect(scoped.getByLabelText('Install updates automatically when no game is running')).toBeChecked(),
    );
    await user.click(scoped.getByLabelText('Download updates automatically'));
    await waitFor(() => expect(scoped.getByLabelText('Download updates automatically')).not.toBeChecked());
    expect(api.posts.filter((post) => post.url === '/api/settings/updates').map((post) => post.body)).toEqual([
      { auto_install: true },
      { auto_download: false },
    ]);
    expect(api.fetchMock).toHaveBeenCalledWith(
      '/api/settings/updates',
      expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/json' } }),
    );

    // Turning checks off disables the automatic options.
    await user.click(scoped.getByLabelText('Check for updates automatically'));
    await waitFor(() => expect(scoped.getByLabelText('Check for updates automatically')).not.toBeChecked());
    expect(scoped.getByLabelText('Download updates automatically')).toBeDisabled();
    expect(scoped.getByLabelText('Install updates automatically when no game is running')).toBeDisabled();
  });

  it('disables automatic options and explains why when this copy cannot update itself', async () => {
    stubSettings({
      updates: updateSettings({ supported: false, install_kind: 'source' }),
      status: updateStatus({ state: 'unsupported', can_install: false, reason: 'source', install_kind: 'source' }),
    });
    render(<SettingsPage />);
    const scoped = within(await updatesSection());
    expect(scoped.getByLabelText('Check for updates automatically')).toBeEnabled();
    expect(scoped.getByLabelText('Download updates automatically')).toBeDisabled();
    expect(scoped.getByLabelText('Install updates automatically when no game is running')).toBeDisabled();
    expect(scoped.getByRole('note')).toHaveTextContent('Running from source — update with git');
    expect(scoped.queryByRole('button', { name: 'Restart to update' })).toBeNull();
  });

  it('checks now, downloads, skips and un-skips', async () => {
    const api = stubSettings({ status: updateStatus({ state: 'available', auto_download: false }) });
    const user = userEvent.setup();
    render(<SettingsPage />);
    const scoped = within(await updatesSection());
    expect(await scoped.findByText('v0.6.6 is available.')).toBeInTheDocument();
    expect(scoped.getByText('v0.6.5.3')).toBeInTheDocument();

    await user.click(scoped.getByRole('button', { name: 'Check now' }));
    await user.click(scoped.getByRole('button', { name: 'Download' }));
    api.state.status = updateStatus({ state: 'available', skipped: true });
    await user.click(scoped.getByRole('button', { name: 'Skip this version' }));
    await user.click(await scoped.findByRole('button', { name: 'Un-skip' }));
    await waitFor(() =>
      expect(api.posts.map((post) => [post.url, post.body])).toEqual([
        ['/api/update/check', {}],
        ['/api/update/download', {}],
        ['/api/update/skip', { version: '0.6.6' }],
        ['/api/update/skip', { version: null }],
      ]),
    );
  });

  it('offers Restart to update when ready, but never Skip for a mandatory update', async () => {
    const api = stubSettings({ status: updateStatus({ state: 'ready', mandatory: true }) });
    const user = userEvent.setup();
    render(<SettingsPage />);
    const scoped = within(await updatesSection());
    await user.click(await scoped.findByRole('button', { name: 'Restart to update' }));
    expect(scoped.queryByRole('button', { name: 'Skip this version' })).toBeNull();
    await waitFor(() => expect(api.posts).toEqual([{ url: '/api/update/install', body: {} }]));
  });

  it('calls a check that found no update file up to date, not an error', async () => {
    const api = stubSettings({
      status: updateStatus({ state: 'idle', latest_version: null, last_check: null }),
    });
    const user = userEvent.setup();
    render(<SettingsPage />);
    const scoped = within(await updatesSection());
    expect(await scoped.findByText('Not checked yet.')).toBeInTheDocument();

    // The newest release predates the updater, so the check finds no update file.
    api.state.status = updateStatus({ state: 'idle', latest_version: null, last_check: '2026-10-18T10:00:00Z' });
    await user.click(scoped.getByRole('button', { name: 'Check now' }));
    expect(await scoped.findByText('Tapps Tracker is up to date.')).toBeInTheDocument();
    expect(scoped.queryByText(/No release information/)).toBeNull();
    expect(scoped.queryByRole('button', { name: 'Skip this version' })).toBeNull();
  });

  it('tags a checked copy with no update file as up to date', async () => {
    stubSettings({ status: updateStatus({ state: 'idle', latest_version: null, last_check: '2026-10-18T10:00:00Z' }) });
    render(<SettingsPage />);
    const scoped = within(await updatesSection());
    expect(await scoped.findByText('Tapps Tracker is up to date.')).toBeInTheDocument();
    expect(scoped.getByText('Up to date', { selector: '.settings-badge' })).toBeInTheDocument();
  });

  it('copes with a tracker that has no update settings', async () => {
    stubSettings({ updates: null });
    render(<SettingsPage />);
    expect(await screen.findByText('This tracker does not report update settings.')).toBeInTheDocument();
  });
});
