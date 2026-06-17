import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getInitialTheme, persistTheme, type ThemeName } from './theme';

function installLocalStorage(): void {
  const store = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      clear: () => store.clear(),
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    },
  });
}

describe('theme helpers', () => {
  beforeEach(() => {
    installLocalStorage();
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    vi.restoreAllMocks();
  });

  it('uses a stored theme when available', () => {
    localStorage.setItem('mtga-dashboard-theme', 'light');
    expect(getInitialTheme()).toBe('light');
  });

  it('falls back to dark when no stored preference exists', () => {
    expect(getInitialTheme()).toBe('dark');
  });

  it('persists theme to localStorage and the document element', () => {
    const theme: ThemeName = 'light';
    persistTheme(theme);

    expect(localStorage.getItem('mtga-dashboard-theme')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
