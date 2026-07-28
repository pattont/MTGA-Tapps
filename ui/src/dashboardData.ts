import type { DashboardSnapshot, DeckRow, SnapshotFilters } from './api';
import { deckRouteHashWithFilters } from './routes';

export interface MetricDefinition {
  label: string;
  value: string;
  detail?: string;
  href?: string;
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value}%`;
}

function confidenceAdjustedWinRate(deck: DeckRow): number {
  const decidedGames = deck.wins + deck.losses;
  if (decidedGames === 0) {
    return -1;
  }
  const winRate = deck.wins / decidedGames;
  const z = 1.96;
  const zSquared = z * z;
  return (
    (winRate +
      zSquared / (2 * decidedGames) -
      z *
        Math.sqrt(
          (winRate * (1 - winRate) + zSquared / (4 * decidedGames)) / decidedGames,
        )) /
    (1 + zSquared / decidedGames)
  );
}

function bestDeckFrom(decks: DeckRow[]): DeckRow | undefined {
  return [...decks]
    .filter((deck) => deck.deck_name !== '(unknown)' && deck.wins + deck.losses > 0)
    .sort((a, b) => {
      const scoreDelta = confidenceAdjustedWinRate(b) - confidenceAdjustedWinRate(a);
      const decidedGamesDelta = b.wins + b.losses - (a.wins + a.losses);
      return (
        scoreDelta ||
        decidedGamesDelta ||
        b.games - a.games ||
        b.wins - a.wins ||
        a.deck_name.localeCompare(b.deck_name)
      );
    })[0];
}

export function metricCards(snapshot: DashboardSnapshot, filters: SnapshotFilters = {}): MetricDefinition[] {
  const bestDeck = bestDeckFrom(snapshot.decks);
  return [
    { label: 'Games', value: String(snapshot.summary.games) },
    { label: 'Wins', value: String(snapshot.summary.wins) },
    { label: 'Losses', value: String(snapshot.summary.losses) },
    { label: 'Win Rate', value: formatPercent(snapshot.summary.win_rate) },
    bestDeck
      ? {
          label: 'Best Deck',
          value: bestDeck.deck_name,
          detail: `${formatPercent(bestDeck.win_rate)} WR · ${bestDeck.wins}–${bestDeck.losses} · ${bestDeck.games} ${
            bestDeck.games === 1 ? 'game' : 'games'
          }`,
          href: deckRouteHashWithFilters(bestDeck.deck_name, filters),
        }
      : { label: 'Best Deck', value: '—' },
  ];
}
