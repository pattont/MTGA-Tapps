import type { ReactNode } from 'react';
import type { ThemeName } from '../theme';

interface AppShellProps {
  theme: ThemeName;
  onToggleTheme: () => void;
  children: ReactNode;
}

const navItems = ['Overview', 'Decks', 'Formats', 'Draw Quality', 'Recent Games'];

export function AppShell({ theme, onToggleTheme, children }: AppShellProps) {
  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true">
            A
          </div>
          <div>
            <h1>MTGA Tracker</h1>
            <p>Local analytics dashboard</p>
          </div>
        </div>
        <nav aria-label="Dashboard sections">
          {navItems.map((item) => (
            <a key={item} href={`#${item.toLowerCase().replace(/\s+/g, '-')}`}>
              {item}
            </a>
          ))}
        </nav>
      </aside>
      <main className="dashboard-main">
        <header className="topbar">
          <div>
            <span className="eyebrow">SQLite analytics</span>
            <h2>Performance overview</h2>
          </div>
          <button className="theme-toggle" type="button" onClick={onToggleTheme}>
            Switch to {nextTheme} mode
          </button>
        </header>
        {children}
      </main>
    </div>
  );
}
