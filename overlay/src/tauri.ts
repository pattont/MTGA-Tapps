/**
 * The page's door to the Rust side. Everything is optional: outside Tauri
 * (vitest, a browser tab during development) the same code runs against a
 * no-op shell so the UI can be developed and tested without the binary.
 */

import type { LayoutInfo, Settings } from './types';

type Unlisten = () => void;

interface Shell {
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
  listen<T>(event: string, handler: (payload: T) => void): Promise<Unlisten>;
  startDragging(): Promise<void>;
}

export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/** Which window this page is: the shell marks the opponent window before
    the page loads; in a browser, `?view=opponent` does the same. */
export function pageView(): 'deck' | 'opponent' {
  if (typeof window === 'undefined') return 'deck';
  const marked = (window as unknown as { __TAPPS_VIEW__?: string }).__TAPPS_VIEW__;
  if (marked === 'opponent') return 'opponent';
  if (!isTauri() && new URLSearchParams(window.location.search).get('view') === 'opponent') return 'opponent';
  return 'deck';
}

let shell: Shell | null = null;

async function loadShell(): Promise<Shell> {
  if (shell) return shell;
  if (isTauri()) {
    const [{ invoke }, { getCurrentWebviewWindow }, { getCurrentWindow }] = await Promise.all([
      import('@tauri-apps/api/core'),
      import('@tauri-apps/api/webviewWindow'),
      import('@tauri-apps/api/window'),
    ]);
    shell = {
      invoke: (command, args) => invoke(command, args),
      // This window's own events: the shell sends each window its layout and
      // cursor (emit_to), and those never reach a listener for "any" target.
      listen: async (event, handler) => getCurrentWebviewWindow().listen(event, (e) => handler(e.payload as never)),
      startDragging: () => getCurrentWindow().startDragging(),
    };
  } else {
    shell = browserShell();
  }
  return shell;
}

/** Development stand-in: settings live in memory, layout changes just resolve. */
function browserShell(): Shell {
  let layout: LayoutInfo = { layout: 'rail', pinned: false, panelOpen: false, visible: true, dock: 'right' };
  let settings: Settings | null = null;
  return {
    async invoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
      switch (command) {
        case 'get_settings':
          // `window.__TAPPS_SETTINGS__` starts the page from other settings
          // (tests and scripts/screenshots.mjs: opponent only, a dock side).
          return (settings ?? (settings = { ...defaultSettings(), ...((window as { __TAPPS_SETTINGS__?: Partial<Settings> }).__TAPPS_SETTINGS__ ?? {}) })) as T;
        case 'update_settings':
          settings = args.settings as Settings;
          return settings as T;
        case 'set_layout': {
          const next = args.layout as LayoutInfo['layout'];
          const panelOpen = args.auto ? layout.panelOpen : next === 'panel';
          layout = { ...layout, layout: next, panelOpen };
          return layout as T;
        }
        case 'set_pinned':
          layout = { ...layout, pinned: Boolean(args.pinned) };
          return layout as T;
        case 'get_layout':
          return layout as T;
        case 'platform':
          return (navigator.platform.toLowerCase().includes('mac') ? 'macos' : 'windows') as T;
        case 'arena_status':
          return { running: false, frontmost: false, bounds: null, overlayFrontmost: false } as T;
        default:
          return undefined as T;
      }
    },
    async listen<T>(event: string, handler: (payload: T) => void) {
      // The shell reports the cursor to the page; in a browser the mouse
      // events it stands in for are available directly.
      if (event === 'overlay-cursor' && typeof window !== 'undefined') {
        const move = (e: MouseEvent) => handler({ x: e.clientX, y: e.clientY } as T);
        const leave = () => handler(null as T);
        window.addEventListener('mousemove', move);
        document.documentElement.addEventListener('mouseleave', leave);
        return () => {
          window.removeEventListener('mousemove', move);
          document.documentElement.removeEventListener('mouseleave', leave);
        };
      }
      // Any other shell event can be sent by hand as a `tapps:<event>`
      // CustomEvent on the window, its detail the payload.
      if (typeof window === 'undefined') return () => undefined;
      const relay = (e: Event) => handler((e as CustomEvent).detail as T);
      window.addEventListener(`tapps:${event}`, relay);
      return () => window.removeEventListener(`tapps:${event}`, relay);
    },
    async startDragging() {
      /* no window to drag */
    },
  };
}

/** Mirrors `Settings::default()` in settings.rs — the Restore defaults button
    and the browser stub both use it. */
export function defaultSettings(): Settings {
  return {
    opacity: 0.8,
    railOpacity: 0.9,
    scale: 100,
    panelMaxHeight: 850,
    dock: 'left',
    returnAfterSeconds: 4,
    panelOpen: false,
    panelPinned: true,
    clickThroughWhenPinned: false,
    lands: 'grouped',
    density: 'comfortable',
    nameColor: 'type',
    sessionRecord: 'scoreboard',
    floodMeter: 'above',
    deckPanel: true,
    opponentPanel: true,
    opponentOpen: false,
    opponentPinned: true,
    followArena: true,
    hideWhenArenaNotInFront: true,
    apiUrl: 'http://127.0.0.1:8765',
    hotkeysMacos: { toggle: 'Alt+Shift+T', visibility: 'Alt+Shift+H', opponent: 'Alt+Shift+O' },
    hotkeysWindows: { toggle: 'Alt+Shift+T', visibility: 'Alt+Shift+H', opponent: 'Alt+Shift+O' },
    positions: { leftY: null, rightY: null, floatX: null, floatY: null },
    monitor: null,
  };
}

/** Lines worth keeping in the shell's overlay.log (errors, link changes). */
export function log(message: string): void {
  if (isTauri()) {
    void tauri.invoke('page_log', { message }).catch(() => undefined);
  } else {
    console.info(`[overlay] ${message}`);
  }
}

export const tauri = {
  invoke: async <T,>(command: string, args?: Record<string, unknown>): Promise<T> =>
    (await loadShell()).invoke<T>(command, args),
  listen: async <T,>(event: string, handler: (payload: T) => void): Promise<Unlisten> =>
    (await loadShell()).listen<T>(event, handler),
  startDragging: async (): Promise<void> => (await loadShell()).startDragging(),
};

/** Test hook: swap the shell (vitest). */
export function __setShell(next: Shell | null): void {
  shell = next;
}
