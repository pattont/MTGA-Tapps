import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { updateStatus } from '../test/updateFixtures';
import type { UpdateStatus } from '../updateStatus';
import { SettingsPage } from './SettingsPage';

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, status: 200, ...init });
}

function stubSettings({
  games = 1284,
  collectionExport = true,
  updates = {},
  status = 'up_to_date',
}: {
  games?: number | null;
  collectionExport?: boolean;
  updates?: Record<string, unknown>;
  status?: 'up_to_date' | 'idle';
} = {}) {
  const state = {
    buyOnPaper: { enabled: true, cache_bytes: 0 },
    sessions: { break_hours: 4, choices: [0, 2, 4, 8] },
    deckAi: {
      enabled: true,
      provider: 'anthropic',
      providers: [{ key: 'anthropic', label: 'Anthropic (Claude)', api_key: 'sk-test', model: '', default_model: 'claude-haiku' }],
    },
    deckAiSaves: [] as unknown[],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === 'POST' && path === '/api/settings/buy-on-paper') {
      state.buyOnPaper = { ...state.buyOnPaper, ...JSON.parse(String(init.body)) };
      return json({ buy_on_paper: state.buyOnPaper });
    }
    if (init?.method === 'POST' && path === '/api/settings/deck-ai') {
      const body = JSON.parse(String(init.body));
      state.deckAiSaves.push(body);
      state.deckAi = {
        ...state.deckAi,
        enabled: body.enabled,
        providers: state.deckAi.providers.map((entry) => ({ ...entry, api_key: body.keys[entry.key] ?? '' })),
      };
      return json({ deck_ai: state.deckAi });
    }
    if (init?.method === 'POST' && path === '/api/settings/sessions') {
      state.sessions = { ...state.sessions, ...JSON.parse(String(init.body)) };
      return json({ sessions: state.sessions });
    }
    if (path === '/api/settings') {
      return json({
        tracker: {
          monitoring: '~/Library/Logs/Wizards Of The Coast/MTGA/Player.log',
          card_db: null,
          log_db: '~/data/mtga_tracker.sqlite3',
          deck_ai: 'disabled',
          version: '0.7.5',
          games,
          first_game_at: games ? '2026-03-02T10:00:00' : null,
          last_game_at: games ? '2026-10-30T21:15:00' : null,
        },
        deck_ai: state.deckAi,
        deck_finder: {
          path: '/tmp/deckfinder_config.json',
          moxfield: [{ name: 'CovertGoBlue', short_name: 'CGB' }],
          aetherhub: [],
          tcgplayer: [],
          youtube: [{ name: '@SlothMtg', short_name: 'Sloth' }],
        },
        platform: { system: 'macos', collection_export: collectionExport },
        startup: { start_at_login: true, open_dashboard_on_launch: true, available: true, registered: true, error: null },
        overlay: { enabled: false, available: true, running: false, binary: '/tmp/overlay', log: '/tmp/overlay.log', error: null },
        buy_on_paper: state.buyOnPaper,
        sessions: state.sessions,
        updates: {
          check: true,
          auto_download: true,
          auto_install: false,
          channel: 'stable',
          skipped_version: null,
          supported: true,
          install_kind: 'macos-app',
          ...updates,
        },
      });
    }
    if (path === '/api/update') {
      // The status reports the same install kind as the settings.
      const kind = updates.install_kind as UpdateStatus['install_kind'] | undefined;
      return json(updateStatus({ state: status, ...(kind ? { install_kind: kind, can_install: false } : {}) }));
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
        local: { schema_version: 35, games: games ?? 0, newest_game_at: null, oldest_game_at: null, sessions: 1 },
        tracker_active: false,
      });
    }
    return json({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return { state, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function sectionOf(heading: HTMLElement): HTMLElement {
  return heading.closest('section') as HTMLElement;
}

describe('Settings page layout', () => {
  it('groups the cards under General, Features, Streaming and Your data after the Tracker card', async () => {
    stubSettings();
    render(<SettingsPage />);
    await screen.findByText('Games captured');

    const groups = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(groups).toEqual(['General', 'Features', 'Streaming', 'Your data']);
    const cards = screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent);
    expect(cards).toEqual([
      'Tracker',
      'Startup',
      'Sessions',
      'Updates',
      'In-game overlay',
      'Buy on Paper',
      'Deck AI',
      'Deck Finder Creators',
      'Stream Kit',
      'Backup & restore',
      'Export MTGA Collection',
    ]);
  });

  it('shows games captured before the version, and keeps Database Health as a small link', async () => {
    stubSettings();
    render(<SettingsPage />);
    const tracker = sectionOf(await screen.findByRole('heading', { name: 'Tracker' }));
    await within(tracker).findByText('1,284');

    const labels = within(tracker)
      .getAllByText(/^(Games captured|Last game|Tracker version|Deck AI)$/)
      .map((node) => node.textContent);
    expect(labels).toEqual(['Games captured', 'Last game', 'Tracker version', 'Deck AI']);
    expect(within(tracker).getByText('v0.7.5')).toBeInTheDocument();
    expect(await within(tracker).findByText('Up to date')).toBeInTheDocument();
    expect(within(tracker).getByText('Anthropic (Claude) · claude-haiku')).toBeInTheDocument();

    expect(within(tracker).getByRole('link', { name: 'Database health' })).toHaveAttribute('href', '#/audit');
    expect(screen.queryByRole('heading', { name: 'Database Health' })).not.toBeInTheDocument();
  });

  it('tags each card with its state beside the title', async () => {
    stubSettings();
    render(<SettingsPage />);
    await screen.findByText('Games captured');

    const tag = (title: string) => sectionOf(screen.getByRole('heading', { name: title })).querySelector('.settings-badge')?.textContent;
    expect(tag('Startup')).toBe('Starts at sign-in');
    expect(tag('Sessions')).toBe('4 h break');
    // Feature cards carry an on/off switch instead of a tag.
    expect(screen.getByRole('switch', { name: 'In-game overlay' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('switch', { name: 'Buy on Paper' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: 'Deck AI' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.queryByLabelText(/Enable AI deck identification/)).toBeNull();
    expect(tag('Deck Finder Creators')).toBe('2 creators');
    expect(await screen.findByText('Up to date', { selector: '.settings-badge' })).toBeInTheDocument();
  });

  it('turns a feature off from the switch beside its title', async () => {
    const api = stubSettings();
    const user = userEvent.setup();
    render(<SettingsPage />);
    const buyOnPaper = sectionOf(await screen.findByRole('heading', { name: 'Buy on Paper' }));
    const toggle = within(buyOnPaper).getByRole('switch', { name: 'Buy on Paper' });

    await user.click(toggle);

    expect(await within(buyOnPaper).findByText(/No button and no price downloads/)).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(toggle).toHaveTextContent('Off');
    expect(api.state.buyOnPaper.enabled).toBe(false);
  });

  it('turns Deck AI on and off from its switch, keeping the saved key', async () => {
    const api = stubSettings();
    const user = userEvent.setup();
    render(<SettingsPage />);
    const deckAi = sectionOf(await screen.findByRole('heading', { name: 'Deck AI' }));
    const toggle = within(deckAi).getByRole('switch', { name: 'Deck AI' });

    // An unsaved key edit stays in the form; the switch saves only on/off.
    await user.clear(within(deckAi).getByPlaceholderText('API key'));
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(toggle).toHaveTextContent('Off');
    expect(api.state.deckAiSaves).toEqual([{ enabled: false, provider: 'anthropic', keys: { anthropic: 'sk-test' }, models: { anthropic: '' } }]);

    // Save in the form keeps the switch's choice.
    await user.type(within(deckAi).getByPlaceholderText('API key'), 'sk-new');
    await user.click(within(deckAi).getByRole('button', { name: /Save Deck AI/ }));
    expect(api.state.deckAiSaves.at(-1)).toMatchObject({ enabled: false, keys: { anthropic: 'sk-new' } });

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(within(deckAi).queryByText('No API key')).toBeNull();
  });

  it('warns beside the Deck AI switch when it is on without a key', async () => {
    const api = stubSettings();
    api.state.deckAi.providers[0].api_key = '';
    render(<SettingsPage />);
    const deckAi = sectionOf(await screen.findByRole('heading', { name: 'Deck AI' }));
    expect(within(deckAi).getByRole('switch', { name: 'Deck AI' })).toHaveAttribute('aria-checked', 'true');
    expect(within(deckAi).getByText('No API key', { selector: '.settings-badge' })).toBeInTheDocument();
  });

  it('updates a tag when its setting changes', async () => {
    stubSettings();
    const user = userEvent.setup();
    render(<SettingsPage />);
    const sessions = sectionOf(await screen.findByRole('heading', { name: 'Sessions' }));

    await user.selectOptions(within(sessions).getByLabelText('Start a new session'), '8');

    expect(await within(sessions).findByText('Saved. It applies from the next match.')).toBeInTheDocument();
    expect(sessions.querySelector('.settings-badge')?.textContent).toBe('8 h break');
  });

  it('names why this copy cannot update itself instead of saying Manual', async () => {
    stubSettings({ updates: { supported: false, install_kind: 'source' }, status: 'idle' });
    render(<SettingsPage />);
    const updates = sectionOf(await screen.findByRole('heading', { name: 'Updates' }));

    expect(await within(updates).findByText('Update with git', { selector: '.settings-badge' })).toBeInTheDocument();
  });
});

describe('Settings → Export MTGA Collection', () => {
  it('stays disabled until the tracker has recorded a game', async () => {
    stubSettings({ games: 0 });
    render(<SettingsPage />);
    const exportCard = sectionOf(await screen.findByRole('heading', { name: 'Export MTGA Collection' }));

    expect(await within(exportCard).findByText(/Play a game with the tracker running first/)).toBeInTheDocument();
    const formats = within(exportCard).getAllByRole('radio');
    expect(formats).toHaveLength(4);
    for (const radio of formats) {
      expect(radio).toBeDisabled();
    }
    expect(within(exportCard).getByRole('button', { name: 'Export collection' })).toBeDisabled();
  });

  it('offers each format as a choice and one Export button that turns on once one is picked', async () => {
    const user = userEvent.setup();
    const { fetchMock } = stubSettings();
    render(<SettingsPage />);
    const exportCard = sectionOf(await screen.findByRole('heading', { name: 'Export MTGA Collection' }));
    await screen.findByText('Games captured');

    const group = within(exportCard).getByRole('group', { name: 'File format' });
    expect(within(group).getAllByRole('radio').map((radio) => (radio as HTMLInputElement).value)).toEqual([
      'csv',
      'archidekt',
      'txt',
      'json',
    ]);
    const run = within(exportCard).getByRole('button', { name: 'Export collection' });
    expect(run).toBeDisabled();
    expect(within(exportCard).getByText('Choose a format to export.')).toBeInTheDocument();

    await user.click(within(group).getByRole('radio', { name: /Archidekt \(\.csv\)/ }));
    expect(run).toBeEnabled();
    expect(within(exportCard).queryByText('Choose a format to export.')).not.toBeInTheDocument();

    await user.click(run);
    const call = fetchMock.mock.calls.find(([url]) => String(url) === '/api/collection/export');
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ format: 'archidekt', refresh: false });
  });

  it('is available once a game is recorded', async () => {
    stubSettings({ games: 3 });
    render(<SettingsPage />);
    const exportCard = sectionOf(await screen.findByRole('heading', { name: 'Export MTGA Collection' }));
    await screen.findByText('Games captured');

    expect(within(exportCard).queryByText(/Play a game with the tracker running first/)).not.toBeInTheDocument();
    expect(within(exportCard).getByRole('radio', { name: /JSON \(\.json\)/ })).toBeEnabled();
  });

  it('stays usable when an older tracker does not report a game count', async () => {
    stubSettings({ games: null });
    render(<SettingsPage />);
    const exportCard = sectionOf(await screen.findByRole('heading', { name: 'Export MTGA Collection' }));
    await screen.findByText('Games captured');

    expect(within(exportCard).getByRole('radio', { name: /JSON \(\.json\)/ })).toBeEnabled();
  });
});
