import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getInitialTheme, hasStoredTheme, persistTheme, systemTheme, type ThemeName } from './theme';

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

  it('follows the OS light preference when nothing is stored', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: query.includes('light'),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    expect(systemTheme()).toBe('light');
    expect(getInitialTheme()).toBe('light');
    vi.unstubAllGlobals();
  });

  it('prefers a stored theme over the OS preference', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    );
    localStorage.setItem('mtga-dashboard-theme', 'dark');
    expect(getInitialTheme()).toBe('dark');
    expect(hasStoredTheme()).toBe(true);
    vi.unstubAllGlobals();
  });

  it('reports no stored theme for unknown values', () => {
    localStorage.setItem('mtga-dashboard-theme', 'sepia');
    expect(hasStoredTheme()).toBe(false);
  });

  it('persists theme to localStorage and the document element', () => {
    const theme: ThemeName = 'light';
    persistTheme(theme);

    expect(localStorage.getItem('mtga-dashboard-theme')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
