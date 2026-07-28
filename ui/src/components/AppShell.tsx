import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { TRACKER_NAME } from '../branding';
import { dashboardNavItems, type AppNavItem } from '../nav';
import type { ThemeName } from '../theme';
import { CardSearch } from './CardSearch';

interface AppShellProps {
  theme: ThemeName;
  onToggleTheme: () => void;
  navItems?: AppNavItem[];
  heading: string;
  children: ReactNode;
}

function scrollToSection(id: string) {
  if (id === 'overview') {
    window.scrollTo({ top: 0, left: 0 });
    return;
  }
  document.getElementById(id)?.scrollIntoView?.({ block: 'start' });
}

export function AppShell({
  theme,
  onToggleTheme,
  navItems = dashboardNavItems,
  heading,
  children,
}: AppShellProps) {
  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  const [activeSection, setActiveSection] = useState<string | null>(null);

  useEffect(() => {
    const sectionIds = navItems.filter((item) => !item.route).map((item) => item.id);
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter((element): element is HTMLElement => Boolean(element));
    if (sections.length === 0) {
      return;
    }

    function updateActiveSection() {
      if (window.scrollY <= 1) {
        setActiveSection(sections[0].id);
        return;
      }
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        setActiveSection(sections[sections.length - 1].id);
        return;
      }

      const marker = 120;
      let nextSection = sections[0].id;
      for (const section of sections) {
        if (section.getBoundingClientRect().top > marker) {
          break;
        }
        nextSection = section.id;
      }
      setActiveSection(nextSection);
    }

    updateActiveSection();
    window.addEventListener('scroll', updateActiveSection, { passive: true });
    window.addEventListener('resize', updateActiveSection);
    return () => {
      window.removeEventListener('scroll', updateActiveSection);
      window.removeEventListener('resize', updateActiveSection);
    };
  }, [navItems, children]);

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand-row">
          <a
            aria-label={`${TRACKER_NAME} – Go to overview`}
            className="brand-home"
            href="#overview"
            onClick={(event) => {
              if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              ) {
                return;
              }
              event.preventDefault();
              if (window.location.hash !== '#overview') {
                window.location.hash = '#overview';
              }
              setActiveSection('overview');
              scrollToSection('overview');
            }}
          >
            <h1 className="brand-wordmark">{TRACKER_NAME}</h1>
            <p>Local analytics dashboard</p>
            <div className="mana-row" aria-hidden="true">
              {['W', 'U', 'B', 'R', 'G'].map((color) => (
                <img
                  key={color}
                  alt=""
                  className="mana-pip"
                  height={22}
                  src={`/icons/${color}.svg`}
                  width={22}
                />
              ))}
            </div>
          </a>
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
                  setActiveSection(item.id);
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
          <h2>{heading}</h2>
          <div className="topbar-actions">
            <CardSearch />
            <button className="theme-toggle" type="button" onClick={onToggleTheme}>
              Switch to {nextTheme} mode
            </button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
