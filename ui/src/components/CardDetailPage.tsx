import { useEffect, useState } from 'react';
import { fetchCardDetail, type CardByDeckRow, type CardDetail } from '../api';
import { formatPercent } from '../dashboardData';
import { formatNumber } from '../format';
import { DeckLink } from './DeckLink';
import { MetricCard } from './MetricCard';
import { SortableTable, type Column } from './SortableTable';
import { WinRateBar } from './WinRateBar';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: CardDetail }
  | { status: 'error'; message: string };

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="dashboard-section" id={id}>
      <div className="section-heading">
        <div>
          <h3>{title}</h3>
          {description ? <p className="section-description">{description}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

const deckColumns: Column<CardByDeckRow>[] = [
  {
    key: 'deck_name',
    header: 'Deck',
    render: (row) => <DeckLink deckName={row.deck_name} />,
    sortValue: (row) => row.deck_name,
  },
  { key: 'games_seen', header: 'Games Seen', numeric: true },
  { key: 'total_played', header: 'Played', numeric: true },
  { key: 'wins', header: 'Wins', numeric: true },
  { key: 'losses', header: 'Losses', numeric: true },
  {
    key: 'win_rate',
    header: 'Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

export function CardDetailPage({ cardName }: { cardName: string }) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [failedImageCard, setFailedImageCard] = useState<string | null>(null);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [cardName]);

  useEffect(() => {
    let ignore = false;
    let activeController: AbortController | null = null;

    async function loadDetail() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const detail = await fetchCardDetail(cardName, controller.signal);
        if (!ignore) {
          setLoadState({ status: 'loaded', detail });
        }
      } catch (error: unknown) {
        if (!ignore && !isAbortError(error)) {
          const message = error instanceof Error ? error.message : 'Dashboard API failed';
          setLoadState((current) => (current.status === 'loaded' ? current : { status: 'error', message }));
        }
      }
    }

    void loadDetail();
    const refreshId = window.setInterval(() => {
      void loadDetail();
    }, DETAIL_REFRESH_MS);

    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [cardName]);

  useEffect(() => {
    if (loadState.status === 'loaded') {
      document.title = `${loadState.detail.card_name} – MTGA Tracker`;
    }
  }, [loadState]);

  if (loadState.status === 'loading') {
    return <p className="state-panel">Loading card details...</p>;
  }
  if (loadState.status === 'error') {
    return (
      <div className="state-panel error-state" role="alert">
        <p>{loadState.message}</p>
        <a className="back-link" href="#overview">
          ← Back to dashboard
        </a>
      </div>
    );
  }

  const { detail } = loadState;
  const metrics = [
    { label: 'Games Seen', value: formatNumber(detail.summary.games_seen) },
    { label: 'Played', value: formatNumber(detail.summary.total_played) },
    { label: 'Record', value: `${detail.summary.wins}–${detail.summary.losses}` },
    { label: 'Win Rate', value: formatPercent(detail.summary.win_rate) },
    { label: 'In Opener', value: formatNumber(detail.opener_impact.games_in_opener) },
    { label: 'Visible Draws', value: formatNumber(detail.opener_impact.times_drawn) },
  ];
  const canShowImage = Boolean(detail.image_url) && failedImageCard !== detail.card_name;

  return (
    <>
      <div className="card-detail-header" id="card-summary">
        <a className="back-link" href="#overview">
          ← Back to dashboard
        </a>
        <div className="card-detail-title">
          <div className="card-art-panel">
            {canShowImage ? (
              <img
                src={detail.image_url ?? ''}
                alt={`${detail.card_name} art`}
                onError={() => setFailedImageCard(detail.card_name)}
              />
            ) : (
              <div className="card-art-fallback">{detail.card_name.slice(0, 1).toUpperCase()}</div>
            )}
          </div>
          <div>
            <span className="eyebrow">Card drill-down</span>
            <h2>{detail.card_name}</h2>
            <p>Performance whenever this card was visible in tracked games.</p>
          </div>
        </div>
      </div>

      <Section id="card-summary-metrics" title="Card Summary">
        <section className="metric-grid metric-grid-deck" aria-label="Card metrics">
          {metrics.map((metric) => (
            <MetricCard key={metric.label} label={metric.label} value={metric.value} />
          ))}
        </section>
      </Section>

      <Section id="card-decks" title="Decks" description="Deck results in games where this card appeared.">
        <SortableTable
          caption="Card performance by deck"
          columns={deckColumns}
          getRowKey={(row) => row.deck_name}
          rows={detail.by_deck}
        />
      </Section>

      <Section
        id="card-opener-impact"
        title="Opening Hand Impact"
        description="Results when the card was in your opening hand, plus visible draws recorded later."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Opening hand impact">
          <MetricCard label="Games In Opener" value={formatNumber(detail.opener_impact.games_in_opener)} />
          <MetricCard
            label="Opener Record"
            value={`${detail.opener_impact.wins}–${detail.opener_impact.losses}`}
          />
          <MetricCard label="Opener Win Rate" value={formatPercent(detail.opener_impact.win_rate)} />
          <MetricCard label="Visible Draws" value={formatNumber(detail.opener_impact.times_drawn)} />
        </section>
      </Section>
    </>
  );
}
