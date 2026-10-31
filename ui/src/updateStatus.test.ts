import { describe, expect, it } from 'vitest';
import {
  RELEASES_URL,
  isNewerVersion,
  parseUpdateStatus,
  updatePillModel,
  updateReasonText,
  type UpdateStatus,
} from './updateStatus';
import { updateStatus } from './test/updateFixtures';

describe('updatePillModel', () => {
  it.each(['idle', 'checking', 'up_to_date', 'disabled'] as const)('hides the pill while %s', (state) => {
    const model = updatePillModel(updateStatus({ state }));
    expect(model.visible).toBe(false);
    expect(model.showCollapsed).toBe(false);
  });

  it('stays hidden when a check found no release information', () => {
    const model = updatePillModel(
      updateStatus({ state: 'idle', latest_version: null, notes_url: null, last_check: '2026-10-18T10:00:00Z' }),
    );
    expect(model.visible).toBe(false);
    expect(model.showCollapsed).toBe(false);
  });

  it('tolerates garbage and payloads from other endpoints', () => {
    for (const payload of [null, undefined, 42, 'ready', [], {}, { state: 'nonsense' }, { summary: { games: 2 } }]) {
      expect(updatePillModel(payload).visible).toBe(false);
    }
    expect(parseUpdateStatus({ state: 'ready' })).toMatchObject({
      state: 'ready',
      current_version: '',
      can_install: false,
      blocked_by: [],
      progress: null,
    });
    // Unknown blockers and a malformed progress object are dropped, not trusted.
    expect(
      parseUpdateStatus({ state: 'downloading', blocked_by: ['game-in-progress', 'mystery', 3], progress: 'half' }),
    ).toMatchObject({ blocked_by: ['game-in-progress'], progress: null });
  });

  it('offers a download when automatic download is off', () => {
    const model = updatePillModel(updateStatus({ state: 'available', auto_download: false }));
    expect(model).toMatchObject({ visible: true, kind: 'download', label: 'Update v0.6.6 available — Download' });
    expect(updatePillModel(updateStatus({ state: 'available' }))).toMatchObject({
      kind: 'download',
      label: 'Update v0.6.6 available',
    });
  });

  it('links out with the reason when this copy cannot install', () => {
    const cases: Array<[UpdateStatus['reason'], string]> = [
      ['source', 'Running from source — update with git'],
      ['portable', 'Portable copy — download the new zip'],
      ['translocated', 'Move Tapps Tracker to Applications, then update'],
      ['not-writable', 'Move Tapps Tracker to Applications, then update'],
      ['moved-install', 'This install was moved; download the new installer'],
      ['manual-required', 'Update manually — this version is too old to update in place'],
    ];
    for (const [reason, title] of cases) {
      const model = updatePillModel(updateStatus({ state: 'available', can_install: false, reason }));
      expect(model).toMatchObject({
        visible: true,
        kind: 'link',
        label: 'Update v0.6.6 available →',
        href: 'https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.6',
        title,
      });
    }
    expect(updatePillModel(updateStatus({ state: 'available', can_install: false, notes_url: null })).href).toBe(
      RELEASES_URL,
    );
  });

  it('shows a link for unsupported copies only when a newer version exists', () => {
    const newer = updatePillModel(
      updateStatus({ state: 'unsupported', can_install: false, reason: 'source', install_kind: 'source' }),
    );
    expect(newer).toMatchObject({ visible: true, kind: 'link', showCollapsed: false });
    expect(updatePillModel(updateStatus({ state: 'unsupported', latest_version: null })).visible).toBe(false);
    expect(updatePillModel(updateStatus({ state: 'unsupported', latest_version: '0.6.5.3' })).visible).toBe(false);
  });

  it('rounds the download percentage and reports bytes', () => {
    const model = updatePillModel(
      updateStatus({
        state: 'downloading',
        progress: { received: 48_234_496, total: 114_849_792, fraction: 0.4199 },
      }),
    );
    expect(model).toMatchObject({ kind: 'progress', percent: 42, label: 'Downloading — 42%' });
    expect(model.title).toBe('Downloading v0.6.6: 46.0 MB of 109.5 MB');
    expect(updatePillModel(updateStatus({ state: 'downloading', progress: { received: 1, total: 1, fraction: 1.7 } })).percent).toBe(100);
    expect(updatePillModel(updateStatus({ state: 'downloading', progress: null }))).toMatchObject({
      percent: undefined,
      label: 'Downloading update…',
    });
  });

  it('asks for a restart once ready, warning about elevation', () => {
    expect(updatePillModel(updateStatus({ state: 'ready' }))).toMatchObject({
      kind: 'install',
      label: 'Restart to update',
      title: 'Restart Tapps Tracker to update to v0.6.6',
      showCollapsed: true,
    });
    expect(updatePillModel(updateStatus({ state: 'ready', needs_elevation: true })).title).toBe(
      'Windows will ask for permission',
    );
  });

  it('shows restarting and retry states', () => {
    expect(updatePillModel(updateStatus({ state: 'installing' }))).toMatchObject({ kind: 'none', label: 'Restarting…' });
    expect(
      updatePillModel(updateStatus({ state: 'error', error: { code: 'sha256-mismatch', message: 'Checksum mismatch' } })),
    ).toMatchObject({ kind: 'retry', label: 'Update failed — retry', title: 'Checksum mismatch' });
  });

  it('hides skipped versions unless the update is mandatory', () => {
    expect(updatePillModel(updateStatus({ state: 'available', skipped: true })).visible).toBe(false);
    const mandatory = updatePillModel(updateStatus({ state: 'available', skipped: true, mandatory: true }));
    expect(mandatory.visible).toBe(true);
    expect(mandatory.skippable).toBe(false);
    expect(updatePillModel(updateStatus({ state: 'available' })).skippable).toBe(true);
  });
});

describe('isNewerVersion', () => {
  it('compares every segment, including four-part hotfixes and pre-releases', () => {
    expect(isNewerVersion('0.6.5.4', '0.6.5.3')).toBe(true);
    expect(isNewerVersion('v0.6.6', '0.6.5.3')).toBe(true);
    expect(isNewerVersion('0.6.5', '0.6.5.0')).toBe(false);
    expect(isNewerVersion('0.6.3', '0.6.3rc8')).toBe(true);
    expect(isNewerVersion('0.6.3rc8', '0.6.3')).toBe(false);
    expect(isNewerVersion('0.6.4', '0.6.10')).toBe(false);
  });

  it('orders pre-releases by kind and number, whatever the spelling', () => {
    expect(isNewerVersion('0.7.5rc2', '0.7.5-rc.1')).toBe(true);
    expect(isNewerVersion('0.7.5-rc.1', '0.7.5rc2')).toBe(false);
    expect(isNewerVersion('0.7.5rc2', '0.7.5-rc.2')).toBe(false);
    expect(isNewerVersion('0.7.5rc1', '0.7.5b3')).toBe(true);
    expect(isNewerVersion('0.7.5a1', '0.7.5.dev9')).toBe(true);
    expect(isNewerVersion('0.7.5', '0.7.5-rc.9')).toBe(true);
  });
});

describe('updateReasonText', () => {
  it('falls back to the install kind', () => {
    expect(updateReasonText(null, 'source')).toBe('Running from source — update with git');
    expect(updateReasonText(null, 'windows-portable')).toBe('Portable copy — download the new zip');
  });
});
