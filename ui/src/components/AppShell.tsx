import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  Bot,
  CalendarClock,
  Circle,
  Clock,
  Database,
  FileText,
  GitBranch,
  Hand,
  Heart,
  History,
  Info,
  Layers,
  LayoutDashboard,
  List,
  ListOrdered,
  Moon,
  Mountain,
  Palette,
  Play,
  Repeat,
  Repeat2,
  Search,
  Settings,
  Shapes,
  Shield,
  ShieldAlert,
  Sparkles,
  Sun,
  Swords,
  Timer,
  TrendingUp,
  Trophy,
  Users,
  type LucideIcon,
} from 'lucide-react';
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
  /** Extra class for the main content area (e.g. the Live Log's
      viewport-filling layout wants less bottom padding). */
  mainClassName?: string;
  children: ReactNode;
}

/** One small icon per nav entry — shown left of the label, and standing in
    for it entirely when the sidebar is collapsed. */
const NAV_ICONS: Record<string, LucideIcon> = {
  'back-to-dashboard': ArrowLeft,
  overview: LayoutDashboard,
  trend: TrendingUp,
  'rank-progress': Trophy,
  'recent-games': History,
  decks: Layers,
  'land-drops': Mountain,
  habits: CalendarClock,
  'opponent-meta': Swords,
  formats: Shapes,
  sessions: Clock,
  'all-games': List,
  'all-games-list': List,
  'audit-summary': FileText,
  'audit-findings': AlertTriangle,
  'audit-danger': ShieldAlert,
  'deck-combat': Swords,
  'deck-turn-timing': Timer,
  'deck-draw-quality': Sparkles,
  'deck-interaction': Shield,
  'deck-formats': Shapes,
  'deck-trend': TrendingUp,
  'deck-cards': Layers,
  'deck-mulligans': Repeat,
  'deck-lands': Mountain,
  'deck-opponent-colors': Palette,
  'deck-versions': GitBranch,
  'deck-games': History,
  'game-summary': FileText,
  'game-turn-timing': Timer,
  'game-draw-quality': Sparkles,
  'game-combat': Swords,
  'game-life': Heart,
  'game-opening-hand': Hand,
  'game-draws': Repeat,
  'game-played': Play,
  'game-opponent-cards': Users,
  'game-timeline': ListOrdered,
  'card-summary': FileText,
  'card-opener-impact': Hand,
  'card-usage-by-side': Users,
  'card-usage-comparison': ArrowLeftRight,
  'card-multiplicity': Repeat,
  'card-opponent-multiplicity': Repeat2,
  'card-decks': Layers,
  'opponent-summary': FileText,
  'opponent-games': History,
  'deck-finder-browse': Search,
  'live-scoreboard': Activity,
  'settings-tracker': Info,
  'settings-deck-ai': Bot,
  'settings-creators': Users,
  'settings-db-health': Database,
};

function NavIcon({ id }: { id: string }) {
  const Icon = NAV_ICONS[id] ?? Circle;
  return <Icon aria-hidden="true" className="sidebar-nav-icon" />;
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
  mainClassName,
  children,
}: AppShellProps) {
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
  // Green when the tracker is running (live or idle), red when it is not.
  const [trackerState, setTrackerState] = useState<'live' | 'idle' | 'offline' | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkTracker() {
      try {
        const response = await fetch('/api/live?status=1');
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as {
          tracker?: { state?: 'live' | 'idle' | 'offline' };
        };
        if (!cancelled && payload.tracker?.state) {
          setTrackerState(payload.tracker.state);
        }
      } catch {
        // The link just keeps its last color.
      }
    }

    void checkTracker();
    const id = window.setInterval(() => {
      if (!document.hidden) {
        void checkTracker();
      }
    }, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

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
        <div className="sidebar-live-block">
          <a
            className={
              trackerState === null
                ? 'sidebar-live-link'
                : trackerState === 'offline'
                  ? 'sidebar-live-link sidebar-live-offline'
                  : 'sidebar-live-link sidebar-live-running'
            }
            href="#/live"
            title={
              trackerState === 'offline'
                ? 'Live Log — tracker is not running'
                : trackerState
                  ? 'Live Log — tracker is running'
                  : 'Live Log'
            }
          >
            <span aria-hidden="true" className="sidebar-live-dot" />
            <span className="sidebar-nav-label">Live Log</span>
          </a>
          <hr className="sidebar-live-rule" />
        </div>
        <nav aria-label="Dashboard sections">
          {navItems.map((item) => {
            // Icons carry the arrow for back links; drop the text version.
            const label = item.label.replace(/^←\s*/u, '');
            return item.route ? (
              <a key={item.id} className="nav-route" href={item.route} title={label}>
                <NavIcon id={item.id} />
                <span className="sidebar-nav-label">{label}</span>
              </a>
            ) : (
              <a
                key={item.id}
                aria-current={activeSection === item.id ? 'true' : undefined}
                className={activeSection === item.id ? 'active' : undefined}
                href={`#${item.id}`}
                title={label}
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
                <NavIcon id={item.id} />
                <span className="sidebar-nav-label">{label}</span>
              </a>
            );
          })}
        </nav>
        {collapsed ? (
          <a
            aria-label="Deck Finder"
            className="sidebar-deck-finder sidebar-deck-finder-mini"
            href="#/deck-finder"
            title="Deck Finder"
          >
            <Search aria-hidden="true" />
          </a>
        ) : (
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
              <Search aria-hidden="true" />
              <span className="sidebar-nav-label">Deck Finder</span>
            </a>
            {version ? (
              <span aria-label={`Tracker version ${version}`} className="sidebar-version">
                v{version}
              </span>
            ) : null}
          </div>
        )}
      </aside>
      <main
        className={mainClassName ? `dashboard-main ${mainClassName}` : 'dashboard-main'}
        id="main-content"
      >
        <header className="topbar">
          <h2>{heading}</h2>
          <div className="topbar-actions">
            <CardSearch />
            <button
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              className="topbar-icon-link"
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              type="button"
              onClick={onToggleTheme}
            >
              {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
            </button>
            <a aria-label="Settings" className="topbar-icon-link" href="#/settings" title="Settings">
              <Settings aria-hidden="true" />
            </a>
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
