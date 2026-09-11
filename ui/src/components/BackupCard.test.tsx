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
    // A chip only fills the field: nothing is sent until Save.
    const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.setup().click(screen.getByRole('button', { name: 'iCloud Drive' }));
    expect(screen.getByLabelText('Backup folder')).toHaveValue('/Users/travis/iCloud/Tapps Tracker');
    expect(screen.getByRole('button', { name: 'iCloud Drive' })).toHaveClass('backup-pick-active');
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls);
    expect(screen.getByRole('button', { name: 'Back up now' })).toBeEnabled();
    // The readable backup gets a Restore button; the junk file says why it has none.
    expect(screen.getAllByRole('button', { name: 'Restore…' })).toHaveLength(2); // row + "from a file elsewhere"
    expect(screen.getByText('junk.tappsbackup is not a Tapps Tracker backup')).toBeInTheDocument();
    expect(screen.getByText('Laptop')).toBeInTheDocument();
    expect(screen.getByText('29.6 MB')).toBeInTheDocument();
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

    const [rowRestore] = await screen.findAllByRole('button', { name: 'Restore…' });
    await user.click(rowRestore);

    const region = await screen.findByRole('region', { name: 'Restore preview' });
    expect(region).toHaveTextContent("Restore Laptop's backup");
    expect(region).toHaveTextContent('Adds 7 games from the backup and drops 2 games recorded here');
    const go = screen.getByRole('button', { name: 'Restore this backup' });
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText('Type REPLACE to confirm'), 'replace');
    expect(go).toBeDisabled();
    await user.clear(screen.getByLabelText('Type REPLACE to confirm'));
    await user.type(screen.getByLabelText('Type REPLACE to confirm'), 'REPLACE');
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

    const [rowRestore] = await screen.findAllByRole('button', { name: 'Restore…' });
    await user.click(rowRestore);
    await user.click(await screen.findByRole('button', { name: 'Restore this backup' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The tracker is running and writing to this database; stop it first');
  });
});
