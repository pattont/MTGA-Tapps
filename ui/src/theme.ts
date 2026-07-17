export type ThemeName = 'dark' | 'light';

const STORAGE_KEY = 'mtga-dashboard-theme';

export function getInitialTheme(): ThemeName {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'dark';
}

export function persistTheme(theme: ThemeName): void {
  localStorage.setItem(STORAGE_KEY, theme);
  document.documentElement.dataset.theme = theme;
}
