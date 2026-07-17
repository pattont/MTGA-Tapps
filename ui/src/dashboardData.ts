import type { DashboardSnapshot, SnapshotFilters } from './api';
import { deckRouteHashWithFilters } from './routes';

export interface MetricDefinition {
  label: string;
  value: string;
  href?: string;
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value}%`;
}

export function metricCards(snapshot: DashboardSnapshot, filters: SnapshotFilters = {}): MetricDefinition[] {
  const bestDeck = [...snapshot.decks].sort((a, b) => {
    const winRateDelta = (b.win_rate ?? -1) - (a.win_rate ?? -1);
    return winRateDelta || b.games - a.games || a.deck_name.localeCompare(b.deck_name);
  })[0];
  return [
    { label: 'Games', value: String(snapshot.summary.games) },
    { label: 'Wins', value: String(snapshot.summary.wins) },
    { label: 'Losses', value: String(snapshot.summary.losses) },
    { label: 'Win Rate', value: formatPercent(snapshot.summary.win_rate) },
    bestDeck
      ? { label: 'Best Deck', value: bestDeck.deck_name, href: deckRouteHashWithFilters(bestDeck.deck_name, filters) }
      : { label: 'Best Deck', value: '—' },
  ];
}
