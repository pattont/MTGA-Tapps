import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { dashboardNavItems, type AppNavItem } from '../nav';
import type { ThemeName } from '../theme';

interface AppShellProps {
  theme: ThemeName;
  onToggleTheme: () => void;
  navItems?: AppNavItem[];
  eyebrow?: string;
  heading?: string;
  children: ReactNode;
}

function scrollToSection(id: string) {
  // Instant scroll: smooth behavior is silently dropped by some browsers
  // (e.g. with reduced motion), which would leave the click doing nothing.
  document.getElementById(id)?.scrollIntoView?.({ block: 'start' });
}

export function AppShell({
  theme,
  onToggleTheme,
  navItems = dashboardNavItems,
  eyebrow = 'SQLite analytics',
  heading = 'Performance overview',
  children,
}: AppShellProps) {
  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  const [activeSection, setActiveSection] = useState<string | null>(null);

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') {
      return;
    }
    const sectionIds = navItems.filter((item) => !item.route).map((item) => item.id);
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter((element): element is HTMLElement => Boolean(element));
    if (sections.length === 0) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible?.target.id) {
          setActiveSection(visible.target.id);
        }
      },
      { rootMargin: '-20% 0px -70% 0px', threshold: [0, 0.2, 0.8] },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [navItems, children]);

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
          {navItems.map((item) =>
            item.route ? (
              <a key={item.id} className="nav-route" href={item.route}>
                {item.label}
              </a>
            ) : (
              <a
                key={item.id}
                className={activeSection === item.id ? 'active' : undefined}
                href={`#${item.id}`}
                onClick={(event) => {
                  event.preventDefault();
                  scrollToSection(item.id);
                }}
              >
                {item.label}
              </a>
            ),
          )}
        </nav>
      </aside>
      <main className="dashboard-main">
        <header className="topbar">
          <div>
            <span className="eyebrow">{eyebrow}</span>
            <h2>{heading}</h2>
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
