export type ThemeName = 'dark' | 'light';

const STORAGE_KEY = 'mtga-dashboard-theme';

export function systemTheme(): ThemeName {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  return 'dark';
}

export function hasStoredTheme(): boolean {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'light' || stored === 'dark';
}

export function getInitialTheme(): ThemeName {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') {
    return stored;
  }
  return systemTheme();
}

export function persistTheme(theme: ThemeName): void {
  localStorage.setItem(STORAGE_KEY, theme);
  document.documentElement.dataset.theme = theme;
}
