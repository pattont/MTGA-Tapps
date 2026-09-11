import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BackupPreview, BackupStatus } from '../api';
import { describePreview } from '../backupText';
import { BackupCard } from './BackupCard';

const manifest = {
  format: 1,
  app_version: '0.6.3',
  schema_version: 29,
  machine: 'Laptop',
  install_id: 'laptop000001',
  exported_at: '2026-09-10T21:14:00+00:00',
  games: 981,
  sessions: 40,
  newest_game_at: '2026-09-10T20:50:00',
  oldest_game_at: '2026-06-01T10:00:00',
  includes: ['tracker.sqlite3', 'settings.json'],
  include_keys: true,
  tag: null,
};

function status(overrides: Partial<BackupStatus> = {}): BackupStatus {
  return {
    folder: '/Users/travis/My Drive/Tapps Tracker',
    detected_folders: [
      { name: 'Google Drive', path: '/Users/travis/My Drive/Tapps Tracker' },
      { name: 'iCloud Drive', path: '/Users/travis/iCloud/Tapps Tracker' },
    ],
    default_folder: '/Users/travis/My Drive/Tapps Tracker',
    machine: 'Desktop',
    install_id: 'desktop00001',
    last_backup: { at: '2026-09-09T02:00:00+00:00', path: '/x', games: 974 },
    last_restore: null,
    backups: [
      { ...manifest, path: '/Users/travis/My Drive/Tapps Tracker/TappsTracker-Laptop-20260910-211400.tappsbackup', name: 'TappsTracker-Laptop-20260910-211400.tappsbackup', size: 31_000_000 },
      { path: '/x/junk.tappsbackup', name: 'junk.tappsbackup', size: 4, error: 'junk.tappsbackup is not a Tapps Tracker backup' },
    ],
    local: { schema_version: 29, games: 974, newest_game_at: '2026-09-09T01:00:00', oldest_game_at: null, sessions: 39 },
    tracker_active: true,
    ...overrides,
  };
}

function preview(overrides: Partial<BackupPreview> = {}): BackupPreview {
  return {
    path: '/Users/travis/My Drive/Tapps Tracker/TappsTracker-Laptop-20260910-211400.tappsbackup',
    manifest,
    local: { schema_version: 29, games: 974, newest_game_at: '2026-09-09T01:00:00', oldest_game_at: null, sessions: 39 },
    adds: 7,
    drops: 0,
    same_install: false,
    schema_ok: true,
    supported_schema_version: 29,
    verdict: 'newer',
    requires_confirm: false,
    ...overrides,
  };
}

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, status: 200, ...init });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('describePreview', () => {
  it('names what a restore adds, drops, or refuses', () => {
    expect(describePreview(preview()).text).toBe('Adds 7 games this computer does not have. Nothing recorded here is lost.');
    expect(describePreview(preview({ verdict: 'older', adds: 0, drops: 12, requires_confirm: true })).text).toContain('would drop 12 games');
    expect(describePreview(preview({ verdict: 'diverged', adds: 3, drops: 1 })).text).toBe(
      'Adds 3 games from the backup and drops 1 game recorded here that it does not have.',
    );
    const blocked = describePreview(preview({ verdict: 'newer-schema', schema_ok: false, manifest: { ...manifest, schema_version: 31 } }));
    expect(blocked.blocked).toBe(true);
    expect(blocked.text).toContain('schema 31');
  });
});

describe('BackupCard', () => {
  it('shows the folder, the synced-folder picks, and the backups in the folder', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(status())));
    render(<BackupCard />);

    expect(await screen.findByText('974 games')).toBeInTheDocument();
    expect(screen.getByLabelText('Backup folder')).toHaveValue('/Users/travis/My Drive/Tapps Tracker');
    expect(screen.getByRole('button', { name: 'Google Drive' })).toHaveClass('backup-pick-active');
    expect(screen.getByRole('button', { name: 'iCloud Drive' })).toBeInTheDocument();
    // A chip only fills the field: nothing is sent until Set.
    const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.setup().click(screen.getByRole('button', { name: 'iCloud Drive' }));
    expect(screen.getByLabelText('Backup folder')).toHaveValue('/Users/travis/iCloud/Tapps Tracker');
    expect(screen.getByRole('button', { name: 'iCloud Drive' })).toHaveClass('backup-pick-active');
    expect(screen.getByRole('button', { name: 'Set' })).toBeEnabled();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls);
    expect(screen.getByRole('button', { name: 'Back up now' })).toBeEnabled();
    // The readable backup gets Restore / Merge / Open location / Delete; the
    // junk file says why it only gets Open location and Delete.
    expect(screen.getAllByRole('button', { name: 'Restore' })).toHaveLength(2); // row + "from a file elsewhere"
    expect(screen.getAllByRole('button', { name: 'Merge' })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /Open the location of/ })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: /^Delete / })).toHaveLength(2);
    expect(screen.getByText('junk.tappsbackup is not a Tapps Tracker backup')).toBeInTheDocument();
    expect(screen.getByText('Laptop')).toBeInTheDocument();
    expect(screen.getByText('29.6 MB')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Backup Files' })).toBeInTheDocument();
    expect(screen.getByText('Detected Backup Locations:')).toBeInTheDocument();
  });

  it('backs up into the folder and reports the file', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/backup/export') {
        expect(JSON.parse(String(init?.body))).toEqual({ include_keys: true });
        return json({
          backup: { ...manifest, machine: 'Desktop', games: 974, path: '/Users/travis/My Drive/Tapps Tracker/TappsTracker-Desktop-20260911-030405.tappsbackup', size: 30_500_000 },
          status: status({ last_backup: { at: '2026-09-11T03:04:05+00:00', path: '/y', games: 974 } }),
        });
      }
      return json(status());
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<BackupCard />);

    await user.click(await screen.findByRole('button', { name: 'Back up now' }));
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Saved TappsTracker-Desktop-20260911-030405.tappsbackup — 974 games, 29.1 MB.',
    );
  });

  it('previews a restore, demands REPLACE when games would be lost, then restores and offers undo', async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(url);
      if (url === '/api/backup/inspect') {
        return json(preview({ verdict: 'diverged', adds: 7, drops: 2, requires_confirm: true }));
      }
      if (url === '/api/backup/restore') {
        expect(JSON.parse(String(init?.body))).toEqual({
          path: '/Users/travis/My Drive/Tapps Tracker/TappsTracker-Laptop-20260910-211400.tappsbackup',
          confirm: 'REPLACE',
        });
        return json({
          restore: { ok: true, restored_from: '/x', manifest, games: 981, newest_game_at: null, undo: '/data/backups/undo.tappsbackup', tracker_restarted: true },
          status: status({ local: { schema_version: 29, games: 981, newest_game_at: null, oldest_game_at: null, sessions: 40 } }),
        });
      }
      return json(status());
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<BackupCard />);

    const [rowRestore] = await screen.findAllByRole('button', { name: 'Restore' });
    await user.click(rowRestore);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent("Restore Laptop's backup");
    expect(dialog).toHaveTextContent('TappsTracker-Laptop-20260910-211400.tappsbackup');
    expect(dialog).toHaveTextContent('Adds 7 games from the backup and drops 2 games recorded here');
    const go = screen.getByRole('button', { name: 'Restore this backup' });
    expect(go).toBeDisabled();
    const confirm = screen.getByPlaceholderText('REPLACE');
    await user.type(confirm, 'replace');
    expect(go).toBeDisabled();
    await user.clear(confirm);
    await user.type(confirm, 'REPLACE');
    expect(go).toBeEnabled();
    await user.click(go);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent("Restored 981 games from Laptop's backup"));
    expect(screen.getByRole('status')).toHaveTextContent('The tracker was restarted.');
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
    expect(screen.getByText('981 games')).toBeInTheDocument();
    expect(calls).toContain('/api/backup/restore');
  });

  it('shows the server reason when a restore is refused', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/backup/inspect') {
        return json(preview());
      }
      if (url === '/api/backup/restore') {
        return json({ error: 'The tracker is running and writing to this database; stop it first', code: 'tracker-running' }, { status: 409 });
      }
      return json(status());
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<BackupCard />);

    const [rowRestore] = await screen.findAllByRole('button', { name: 'Restore' });
    await user.click(rowRestore);
    await user.click(await screen.findByRole('button', { name: 'Restore this backup' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The tracker is running and writing to this database; stop it first');
    // The dialog stays open with the reason; Cancel closes it.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('merges after a confirmation and suggests backing up again', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/backup/inspect') {
        return json(preview({ verdict: 'diverged', adds: 7, drops: 2, requires_confirm: true }));
      }
      if (url === '/api/backup/merge') {
        expect(JSON.parse(String(init?.body))).toEqual({ path: preview().path });
        return json({
          merge: { ok: true, merged_from: '/x', manifest, games_added: 7, games: 981, newest_game_at: null, undo: '/data/backups/undo.tappsbackup', tracker_restarted: true },
          status: status({ local: { schema_version: 29, games: 981, newest_game_at: null, oldest_game_at: null, sessions: 40 } }),
        });
      }
      return json(status());
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<BackupCard />);

    const [rowMerge] = await screen.findAllByRole('button', { name: 'Merge' });
    await user.click(rowMerge);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent("Merge Laptop's backup");
    // A merge never drops anything, so no REPLACE even though a restore would need it.
    expect(dialog).toHaveTextContent('Adds 7 games from the backup to the 974 games already here. Nothing here is removed');
    expect(screen.queryByPlaceholderText('REPLACE')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Merge 7 games' }));

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent("Merged 7 games from Laptop's backup"));
    expect(screen.getByRole('status')).toHaveTextContent('981 games here now');
    expect(screen.getByText('Back up now to have everything in one file.')).toBeInTheDocument();
    expect(screen.getByText('981 games')).toBeInTheDocument();
  });

  it('deletes a backup file only after the confirmation names it', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/backup/delete') {
        expect(JSON.parse(String(init?.body))).toEqual({ path: preview().path });
        return json({ delete: { ok: true, deleted: preview().path }, status: status({ backups: [] }) });
      }
      if (url === '/api/backup/reveal') {
        return json({ ok: true });
      }
      return json(status());
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<BackupCard />);

    const [openLocation] = await screen.findAllByRole('button', { name: /Open the location of/ });
    await user.click(openLocation);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/backup/reveal')).toBe(true));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); // no confirmation for opening a folder

    await user.click(screen.getByRole('button', { name: 'Delete TappsTracker-Laptop-20260910-211400.tappsbackup' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Delete this backup file?');
    expect(dialog).toHaveTextContent('TappsTracker-Laptop-20260910-211400.tappsbackup');
    expect(dialog).toHaveTextContent('on Laptop · 981 games · 29.6 MB');
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/backup/delete')).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Delete file' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('No backups in this folder yet.')).toBeInTheDocument();
  });
});
