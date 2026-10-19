import type { UpdateStatus } from '../updateStatus';

/** A complete `/api/update` payload for tests; override what the case needs. */
export function updateStatus(overrides: Partial<UpdateStatus> = {}): UpdateStatus {
  return {
    state: 'up_to_date',
    current_version: '0.6.5.3',
    latest_version: '0.6.6',
    notes_url: 'https://github.com/pattont/MTGA-Tapps/releases/tag/v0.6.6',
    released_at: '2026-10-20T18:00:00Z',
    mandatory: false,
    below_minimum: false,
    install_kind: 'macos-app',
    can_install: true,
    reason: null,
    progress: null,
    error: null,
    last_check: '2026-10-11T14:02:11Z',
    skipped: false,
    auto_download: true,
    auto_install: false,
    pending_install: false,
    blocked_by: [],
    just_updated: null,
    ...overrides,
  };
}
