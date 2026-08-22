import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import { TRACKER_NAME } from '../branding';
import { dashboardNavItems, type AppNavItem } from '../nav';
import type { ThemeName } from '../theme';
import { checkForUpdate, type UpdateInfo } from '../updateCheck';
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
  const [showBackToTop, setShowBackToTop] = useState(false);
  // After a nav click, the clicked section stays active briefly even though
  // scroll events fire — otherwise the scroll-spy can immediately override
  // the choice (e.g. for sections near the page bottom).
  const spySuppressedUntilRef = useRef(0);

  function navigateToSection(id: string) {
    spySuppressedUntilRef.current = Date.now() + 700;
    setActiveSection(id);
    scrollToSection(id);
  }
  const [version, setVersion] = useState<string | null>(null);
  const [update, setUpdate] = useState<UpdateInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/version')
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { version?: string } | null) => {
        if (!cancelled && payload?.version) {
          setVersion(payload.version);
          // Production builds only: one GitHub API call per day, cached.
          if (import.meta.env.PROD) {
            void checkForUpdate(payload.version).then((info) => {
              if (!cancelled) {
                setUpdate(info);
              }
            });
          }
        }
      })
      .catch(() => {
        // Version display is cosmetic.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onScroll() {
      setShowBackToTop(window.scrollY > 600);
    }
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem('mtga-sidebar-collapsed') === '1';
    } catch {
      return false;
    }
  });

  const toggleSidebar = () => {
    setCollapsed((previous) => {
      const next = !previous;
      try {
        window.localStorage.setItem('mtga-sidebar-collapsed', next ? '1' : '0');
      } catch {
        // Preference just won't persist.
      }
      return next;
    });
  };

  useEffect(() => {
    const sectionIds = navItems.filter((item) => !item.route).map((item) => item.id);
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter((element): element is HTMLElement => Boolean(element));
    if (sections.length === 0) {
      return;
    }

    function updateActiveSection() {
      if (Date.now() < spySuppressedUntilRef.current) {
        return;
      }
      if (window.scrollY <= 1) {
        setActiveSection(sections[0].id);
        return;
      }
      const marker = 120;
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        // At the page bottom several sections may be unreachable at the top;
        // highlight whichever section's top sits closest to the marker
        // rather than blindly forcing the last one.
        let closest = sections[sections.length - 1].id;
        let closestDistance = Number.POSITIVE_INFINITY;
        for (const section of sections) {
          const distance = Math.abs(section.getBoundingClientRect().top - marker);
          if (distance < closestDistance) {
            closestDistance = distance;
            closest = section.id;
          }
        }
        setActiveSection(closest);
        return;
      }

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
    <div className={collapsed ? 'app-layout app-layout-collapsed' : 'app-layout'}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <button
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Show navigation' : 'Hide navigation'}
          className="sidebar-toggle"
          type="button"
          onClick={toggleSidebar}
        >
          {collapsed ? '\u00bb' : '\u00ab'}
        </button>
        {collapsed ? null : (
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
              navigateToSection('overview');
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
                  height={24}
                  src={`/icons/${color}.svg`}
                  width={24}
                />
              ))}
            </div>
          </a>
        </div>
        )}
        {collapsed ? null : (
        <nav aria-label="Dashboard sections">
          {navItems.map((item) =>
            item.route ? (
              <a key={item.id} className="nav-route" href={item.route}>
                {item.label}
              </a>
            ) : (
              <a
                key={item.id}
                aria-current={activeSection === item.id ? 'true' : undefined}
                className={activeSection === item.id ? 'active' : undefined}
                href={`#${item.id}`}
                onClick={(event) => {
                  event.preventDefault();
                  navigateToSection(item.id);
                  // Reflect the section in the URL without re-triggering routing
                  // (raw hash assignment would clobber scroll behavior).
                  try {
                    window.history.replaceState(null, '', `#${item.id}`);
                  } catch {
                    // history API unavailable; scrolling still worked.
                  }
                }}
              >
                {item.label}
              </a>
            ),
          )}
        </nav>
        )}
        {collapsed ? null : (
          <div className="sidebar-bottom">
            {update ? (
              <a
                className="sidebar-update"
                href={update.url}
                rel="noreferrer"
                target="_blank"
                title="A newer version is available on GitHub"
              >
                Update {update.tag} available →
              </a>
            ) : null}
            <a className="sidebar-deck-finder" href="#/deck-finder" title="Browse top decks inside the dashboard">
              Deck Finder
            </a>
            {version ? (
              <span aria-label={`Tracker version ${version}`} className="sidebar-version">
                v{version}
              </span>
            ) : null}
          </div>
        )}
      </aside>
      <main className="dashboard-main" id="main-content">
        <header className="topbar">
          <h2>{heading}</h2>
          <div className="topbar-actions">
            <CardSearch />
            <button
              aria-label={`Color theme: ${theme}. Switch to ${nextTheme} mode`}
              className="theme-toggle"
              type="button"
              onClick={onToggleTheme}
            >
              Switch to {nextTheme} mode
            </button>
          </div>
        </header>
        {children}
      </main>
      {showBackToTop ? (
        <button
          className="back-to-top"
          type="button"
          onClick={() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' })}
        >
          ↑ Back to top
        </button>
      ) : null}
    </div>
  );
}
