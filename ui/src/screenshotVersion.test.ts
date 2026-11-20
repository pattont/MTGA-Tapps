import { describe, expect, it } from 'vitest';
import { screenshotUpdateStatus, screenshotVersion } from './screenshotVersion';
import type { UpdateStatus } from './updateStatus';

function status(overrides: Partial<UpdateStatus> = {}): UpdateStatus {
  return {
    state: 'available',
    current_version: '0.7.7.2.dev17+g1234567',
    latest_version: '0.7.7.1',
    notes_url: null,
    released_at: null,
    mandatory: false,
    below_minimum: false,
    install_kind: 'source',
    can_install: false,
    reason: null,
    progress: null,
    error: null,
    last_check: '2026-11-19T08:00:00Z',
    skipped: true,
    auto_download: false,
    auto_install: false,
    pending_install: false,
    blocked_by: [],
    just_updated: null,
    ...overrides,
  };
}

describe('screenshotVersion', () => {
  it('reads a plain release version from the query string', () => {
    expect(screenshotVersion('?screenshotVersion=0.7.8')).toBe('0.7.8');
    expect(screenshotVersion('?screenshotVersion=0.7.8.1')).toBe('0.7.8.1');
  });

  it('ignores anything else', () => {
    expect(screenshotVersion('')).toBeNull();
    expect(screenshotVersion('?screenshotVersion=latest')).toBeNull();
    expect(screenshotVersion('?screenshotVersion=0.7.8<b>')).toBeNull();
  });
});

describe('screenshotUpdateStatus', () => {
  it('leaves the status alone without a screenshot version', () => {
    const real = status();
    expect(screenshotUpdateStatus(real, null)).toBe(real);
    expect(screenshotUpdateStatus(null, '0.7.8')).toBeNull();
  });

  it('shows the screenshot version installed, latest and up to date', () => {
    const shown = screenshotUpdateStatus(status(), '0.7.8');
    expect(shown).toMatchObject({
      current_version: '0.7.8',
      latest_version: '0.7.8',
      state: 'up_to_date',
      skipped: false,
    });
  });

  it('keeps a newer published release on offer', () => {
    const shown = screenshotUpdateStatus(status({ latest_version: '0.7.9' }), '0.7.8');
    expect(shown).toMatchObject({ current_version: '0.7.8', latest_version: '0.7.9', state: 'available' });
  });

  it('does not hide a running download or an error', () => {
    expect(screenshotUpdateStatus(status({ state: 'downloading' }), '0.7.8')?.state).toBe('downloading');
    expect(screenshotUpdateStatus(status({ state: 'error' }), '0.7.8')?.state).toBe('error');
  });
});
