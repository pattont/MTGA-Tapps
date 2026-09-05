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

let shell: Shell | null = null;

async function loadShell(): Promise<Shell> {
  if (shell) return shell;
  if (isTauri()) {
    const [{ invoke }, { listen }, { getCurrentWindow }] = await Promise.all([
      import('@tauri-apps/api/core'),
      import('@tauri-apps/api/event'),
      import('@tauri-apps/api/window'),
    ]);
    shell = {
      invoke: (command, args) => invoke(command, args),
      listen: async (event, handler) => listen(event, (e) => handler(e.payload as never)),
      startDragging: () => getCurrentWindow().startDragging(),
    };
  } else {
    shell = browserShell();
  }
  return shell;
}

/** Development stand-in: settings live in memory, layout changes just resolve. */
function browserShell(): Shell {
  let layout: LayoutInfo = { layout: 'rail', pinned: true, visible: true, dock: 'right' };
  let settings: Settings | null = null;
  return {
    async invoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
      switch (command) {
        case 'get_settings':
          return (settings ?? (settings = defaultSettings())) as T;
        case 'update_settings':
          settings = args.settings as Settings;
          return settings as T;
        case 'set_layout':
          layout = { ...layout, layout: args.layout as LayoutInfo['layout'] };
          return layout as T;
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
    async listen() {
      return () => undefined;
    },
    async startDragging() {
      /* no window to drag */
    },
  };
}

export function defaultSettings(): Settings {
  return {
    background: true,
    opacity: 1,
    panelMaxHeightPct: 70,
    dock: 'right',
    returnAfterSeconds: 4,
    openPinned: true,
    clickThroughWhenPinned: false,
    lands: 'grouped',
    density: 'comfortable',
    followArena: true,
    hideWhenArenaNotInFront: true,
    apiUrl: 'http://127.0.0.1:8765',
    hotkeysMacos: { toggle: 'Alt+Shift+T', visibility: 'Alt+Shift+H' },
    hotkeysWindows: { toggle: 'Alt+Shift+T', visibility: 'Alt+Shift+H' },
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
