import { useEffect, useState } from 'react';
import {
  fetchDashboardSnapshot,
  type DashboardSnapshot,
  type DeckPlayDrawRow,
  type DeckRow,
  type DrawQualityRow,
  type DrawnCardRow,
  type FormatRow,
  type MomentumRow,
  type PlayDrawRow,
  type RecentGameRow,
} from './api';
import { Badge } from './components/Badge';
import { DeckVisual } from './components/DeckVisual';
import { MetricCard } from './components/MetricCard';
import { SortableTable, type Column } from './components/SortableTable';
import { AppShell } from './components/AppShell';
import { formatPercent, metricCards } from './dashboardData';
import './styles.css';
import { getInitialTheme, persistTheme, type ThemeName } from './theme';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; snapshot: DashboardSnapshot }
  | { status: 'error'; message: string };

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : String(value);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  const minutes = Math.round(seconds / 60);
  return `${minutes} min`;
}

function outcomeTone(outcome: string | null | undefined): 'neutral' | 'win' | 'loss' | 'draw' {
  if (outcome === 'win' || outcome === 'loss' || outcome === 'draw') {
    return outcome;
  }
  return 'neutral';
}

function outcomeLabel(outcome: string | null | undefined): string {
  return outcome ? outcome[0].toUpperCase() + outcome.slice(1) : 'Unknown';
}

function readInitialTheme(): ThemeName {
  try {
    return getInitialTheme();
  } catch {
    return 'dark';
  }
}

function applyTheme(theme: ThemeName): void {
  try {
    persistTheme(theme);
  } catch {
    document.documentElement.dataset.theme = theme;
  }
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section className="dashboard-section" id={id}>
      <div className="section-heading">
        <h3>{title}</h3>
      </div>
      {children}
    </section>
  );
}

const deckColumns: Column<DeckRow>[] = [
  {
    key: 'deck_visual',
    header: 'Deck',
    render: (row) => (
      <div className="deck-cell">
        <DeckVisual deckName={row.deck_name} visual={row.deck_visual} />
        <div>
          <strong>{row.deck_name}</strong>
          <span>{row.deck_visual.source === 'local_metadata' ? 'Local metadata' : 'Deck name fallback'}</span>
        </div>
      </div>
    ),
    sortValue: (row) => row.deck_name,
  },
  { key: 'games', header: 'Games' },
  { key: 'wins', header: 'Wins' },
  { key: 'losses', header: 'Losses' },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => formatPercent(row.win_rate),
    sortValue: (row) => row.win_rate,
  },
];

const formatColumns: Column<FormatRow>[] = [
  { key: 'format_label', header: 'Format' },
  {
    key: 'raw_format',
    header: 'Raw Queue',
    render: (row) => row.raw_format ?? '—',
    sortValue: (row) => row.raw_format,
  },
  { key: 'games', header: 'Games' },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => formatPercent(row.win_rate),
    sortValue: (row) => row.win_rate,
  },
];

const playDrawColumns: Column<PlayDrawRow>[] = [
  {
    key: 'play_draw',
    header: 'Play / Draw',
    render: (row) => row.play_draw ?? 'Unknown',
    sortValue: (row) => row.play_draw,
  },
  { key: 'games', header: 'Games' },
  { key: 'wins', header: 'Wins' },
  { key: 'losses', header: 'Losses' },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => formatPercent(row.win_rate),
    sortValue: (row) => row.win_rate,
  },
];

const deckPlayDrawColumns: Column<DeckPlayDrawRow>[] = [
  { key: 'deck_name', header: 'Deck' },
  {
    key: 'play_draw',
    header: 'Play / Draw',
    render: (row) => row.play_draw ?? 'Unknown',
    sortValue: (row) => row.play_draw,
  },
  { key: 'games', header: 'Games' },
  { key: 'wins', header: 'Wins' },
  { key: 'losses', header: 'Losses' },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => formatPercent(row.win_rate),
    sortValue: (row) => row.win_rate,
  },
];

const drawQualityColumns: Column<DrawQualityRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => formatDateTime(row.started_at),
    sortValue: (row) => row.started_at,
  },
  { key: 'deck_name', header: 'Deck' },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
  },
  {
    key: 'cards_seen',
    header: 'Cards Seen',
    render: (row) => formatNumber(row.cards_seen),
    sortValue: (row) => row.cards_seen,
  },
  {
    key: 'lands_seen',
    header: 'Lands Seen',
    render: (row) => formatNumber(row.lands_seen),
    sortValue: (row) => row.lands_seen,
  },
  {
    key: 'land_seen_pct',
    header: 'Land Seen',
    render: (row) => formatPercent(row.land_seen_pct),
    sortValue: (row) => row.land_seen_pct,
  },
  {
    key: 'opening_cards',
    header: 'Opening',
    render: (row) => formatNumber(row.opening_cards),
    sortValue: (row) => row.opening_cards,
  },
  {
    key: 'known_draws',
    header: 'Known Draws',
    render: (row) => formatNumber(row.known_draws),
    sortValue: (row) => row.known_draws,
  },
];

const drawnCardColumns: Column<DrawnCardRow>[] = [
  { key: 'display_name', header: 'Card' },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => row.type_category ?? 'Other',
    sortValue: (row) => row.type_category,
  },
  { key: 'times_drawn', header: 'Times Drawn' },
  { key: 'games_seen', header: 'Games Seen' },
  {
    key: 'pct_of_games',
    header: 'Game Share',
    render: (row) => formatPercent(row.pct_of_games),
    sortValue: (row) => row.pct_of_games,
  },
];

const momentumColumns: Column<MomentumRow>[] = [
  { key: 'split', header: 'Split' },
  { key: 'games', header: 'Games' },
  { key: 'wins', header: 'Wins' },
  { key: 'losses', header: 'Losses' },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => formatPercent(row.win_rate),
    sortValue: (row) => row.win_rate,
  },
  {
    key: 'avg_mulligans',
    header: 'Avg Mulligans',
    render: (row) => formatNumber(row.avg_mulligans),
    sortValue: (row) => row.avg_mulligans,
  },
  {
    key: 'on_play_pct',
    header: 'On Play',
    render: (row) => formatPercent(row.on_play_pct),
    sortValue: (row) => row.on_play_pct,
  },
];

const recentColumns: Column<RecentGameRow>[] = [
  {
    key: 'started_at',
    header: 'Started',
    render: (row) => formatDateTime(row.started_at),
    sortValue: (row) => row.started_at,
  },
  { key: 'deck_name', header: 'Deck' },
  { key: 'format_label', header: 'Format' },
  {
    key: 'outcome',
    header: 'Outcome',
    render: (row) => <Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge>,
    sortValue: (row) => row.outcome,
  },
  {
    key: 'mulligans',
    header: 'Mulligans',
    render: (row) => formatNumber(row.mulligans),
    sortValue: (row) => row.mulligans,
  },
  {
    key: 'duration_seconds',
    header: 'Duration',
    render: (row) => formatDuration(row.duration_seconds),
    sortValue: (row) => row.duration_seconds,
  },
];

export default function App() {
  const [theme, setTheme] = useState<ThemeName>(() => readInitialTheme());
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    let ignore = false;

    fetchDashboardSnapshot()
      .then((snapshot) => {
        if (!ignore) {
          setLoadState({ status: 'loaded', snapshot });
        }
      })
      .catch((error: unknown) => {
        if (!ignore) {
          setLoadState({ status: 'error', message: error instanceof Error ? error.message : 'Dashboard API failed' });
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  function toggleTheme() {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }

  return (
    <AppShell theme={theme} onToggleTheme={toggleTheme}>
      {loadState.status === 'loading' ? <p className="state-panel">Loading dashboard snapshot...</p> : null}
      {loadState.status === 'error' ? (
        <div className="state-panel error-state" role="alert">
          {loadState.message}
        </div>
      ) : null}
      {loadState.status === 'loaded' ? <Dashboard snapshot={loadState.snapshot} /> : null}
    </AppShell>
  );
}

function Dashboard({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <>
      <section className="metric-grid" id="overview" aria-label="Overview metrics">
        {metricCards(snapshot).map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} />
        ))}
      </section>

      <Section id="decks" title="Decks">
        <SortableTable caption="Deck performance" columns={deckColumns} getRowKey={(row) => row.deck_name} rows={snapshot.decks} />
      </Section>

      <Section id="formats" title="Formats">
        <SortableTable
          caption="Format performance"
          columns={formatColumns}
          getRowKey={(row) => `${row.format_label}-${row.raw_format ?? 'unknown'}`}
          rows={snapshot.formats}
        />
      </Section>

      <Section id="play-draw" title="Play / Draw">
        <SortableTable
          caption="Play and draw performance"
          columns={playDrawColumns}
          getRowKey={(row) => row.play_draw ?? 'unknown'}
          rows={snapshot.play_draw}
        />
      </Section>

      <Section id="deck-play-draw" title="Deck Play / Draw">
        <SortableTable
          caption="Deck play and draw performance"
          columns={deckPlayDrawColumns}
          getRowKey={(row) => `${row.deck_name}-${row.play_draw ?? 'unknown'}`}
          rows={snapshot.deck_play_draw}
        />
      </Section>

      <Section id="draw-quality" title="Draw Quality">
        <SortableTable
          caption="Draw quality by game"
          columns={drawQualityColumns}
          getRowKey={(row) => `${row.started_at}-${row.deck_name}`}
          rows={snapshot.draw_quality}
        />
      </Section>

      <Section id="visible-drawn-cards" title="Visible Drawn Cards">
        <SortableTable
          caption="Visible drawn card frequency"
          columns={drawnCardColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category ?? 'unknown'}`}
          rows={snapshot.drawn_cards}
        />
      </Section>

      <Section id="momentum" title="Momentum">
        <SortableTable caption="Momentum splits" columns={momentumColumns} getRowKey={(row) => row.split} rows={snapshot.momentum} />
      </Section>

      <Section id="recent-games" title="Recent Games">
        <SortableTable
          caption="Recent games"
          columns={recentColumns}
          getRowKey={(row) => `${row.started_at}-${row.deck_name}-${row.outcome ?? 'unknown'}`}
          rows={snapshot.recent}
        />
      </Section>
    </>
  );
}
