import { useEffect, useState } from 'react';
import { fetchCardDetail, type CardByDeckRow, type CardByRoleRow, type CardDetail } from '../api';
import { pageTitle } from '../branding';
import {
  cardPreviewImageUrl,
  previewImageHasFailed,
  rememberFailedPreviewImage,
} from '../cardPreview';
import { formatPercent } from '../dashboardData';
import { formatCardName, formatNumber } from '../format';
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

const roleColumns: Column<CardByRoleRow>[] = [
  { key: 'side_label', header: 'Card Played By' },
  { key: 'games_seen', header: 'Games', numeric: true },
  { key: 'total_played', header: 'Plays', numeric: true },
  {
    key: 'wins',
    header: 'Your Record',
    render: (row) => `${row.wins}–${row.losses}`,
    sortValue: (row) => row.wins - row.losses,
    numeric: true,
  },
  {
    key: 'win_rate',
    header: 'Your Win Rate',
    render: (row) => <WinRateBar losses={row.losses} winRate={row.win_rate} wins={row.wins} />,
    sortValue: (row) => row.win_rate,
    numeric: true,
  },
];

export function CardDetailPage({
  cardName,
  backHref = '#overview',
}: {
  cardName: string;
  backHref?: string;
}) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [failedImageCard, setFailedImageCard] = useState<string | null>(null);
  const [loadedImageCard, setLoadedImageCard] = useState<string | null>(null);
  const backLabel = backHref.startsWith('#/game/') ? '← Back to game' : '← Back to dashboard';

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
      document.title = pageTitle(formatCardName(loadState.detail.card_name));
    }
  }, [loadState]);

  if (loadState.status === 'loading') {
    return <p className="state-panel">Loading card details...</p>;
  }
  if (loadState.status === 'error') {
    return (
      <div className="state-panel error-state" role="alert">
        <p>{loadState.message}</p>
        <a className="back-link" href={backHref}>
          {backLabel}
        </a>
      </div>
    );
  }

  const { detail } = loadState;
  const displayName = formatCardName(detail.card_name);
  const metrics = [
    { label: 'Games Appeared', value: formatNumber(detail.all_usage.games_seen) },
    { label: 'Total Plays', value: formatNumber(detail.all_usage.total_played) },
    { label: 'Your Plays', value: formatNumber(detail.all_usage.player_played) },
    { label: 'Opponent Plays', value: formatNumber(detail.all_usage.opponent_played) },
    { label: 'Your Games', value: formatNumber(detail.all_usage.player_games_seen) },
    { label: 'Opponent Games', value: formatNumber(detail.all_usage.opponent_games_seen) },
  ];
  const cardImageUrl = cardPreviewImageUrl(detail.card_name);
  const canShowImage =
    failedImageCard !== detail.card_name && !previewImageHasFailed(cardImageUrl);
  const imageLoaded = loadedImageCard === detail.card_name;
  const legacyOpponentRow = detail.by_role.find((row) => row.role === 'opponent');
  const opponentImpact = detail.opponent_impact ?? {
    games: legacyOpponentRow?.games_seen ?? 0,
    plays: legacyOpponentRow?.total_played ?? 0,
    wins: legacyOpponentRow?.losses ?? 0,
    losses: legacyOpponentRow?.wins ?? 0,
    win_rate: legacyOpponentRow?.win_rate == null ? null : 100 - legacyOpponentRow.win_rate,
    loss_rate: legacyOpponentRow?.win_rate ?? null,
  };
  const roleRows = detail.opponent_impact
    ? detail.by_role
    : detail.by_role.map((row) =>
        row.role === 'opponent'
          ? {
              ...row,
              wins: row.losses,
              losses: row.wins,
              win_rate: row.win_rate == null ? null : 100 - row.win_rate,
            }
          : row,
      );

  return (
    <>
      <div className="card-detail-header" id="card-summary">
        <a className="back-link" href={backHref}>
          {backLabel}
        </a>
        <div className="card-detail-title">
          <div className="card-art-panel">
            {canShowImage ? (
              <>
                {!imageLoaded ? <div className="card-art-loading">Loading card...</div> : null}
                <img
                  className={imageLoaded ? 'card-art-image card-art-image-loaded' : 'card-art-image'}
                  src={cardImageUrl}
                  alt={`${displayName} card`}
                  onLoad={() => setLoadedImageCard(detail.card_name)}
                  onError={() => {
                    rememberFailedPreviewImage(cardImageUrl);
                    setFailedImageCard(detail.card_name);
                  }}
                />
              </>
            ) : (
              <div className="card-art-fallback">
                <strong>{displayName}</strong>
                <span>Card image unavailable</span>
              </div>
            )}
          </div>
          <div>
            <span className="eyebrow">Card drill-down</span>
            <h2>{displayName}</h2>
            <p>Usage by either player whenever this card appeared in a tracked game.</p>
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

      <Section
        id="card-usage-by-side"
        title="When Opponent Plays This Card"
        description="Your results only in games where the opponent actually played this card."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Opponent card impact">
          <MetricCard label="Games" value={formatNumber(opponentImpact.games)} />
          <MetricCard label="Opponent Plays" value={formatNumber(opponentImpact.plays)} />
          <MetricCard label="Your Record" value={`${opponentImpact.wins}–${opponentImpact.losses}`} />
          <MetricCard label="Your Win Rate" value={formatPercent(opponentImpact.win_rate)} />
          <MetricCard label="Your Loss Rate" value={formatPercent(opponentImpact.loss_rate)} />
        </section>
      </Section>

      <Section
        id="card-usage-comparison"
        title="Played By Side"
        description="Only games where that side played the card. Every record and win rate is shown from your perspective."
      >
        <SortableTable
          caption="Your results by card-playing side"
          columns={roleColumns}
          compact
          getRowKey={(row) => row.role}
          rows={roleRows}
        />
      </Section>

      <Section id="card-decks" title="Your Decks" description="Your results in games where you used this card.">
        <SortableTable
          caption="Card performance by deck"
          columns={deckColumns}
          compact
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
