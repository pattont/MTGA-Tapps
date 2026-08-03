import type { DashboardSnapshot, DeckRow, SnapshotFilters } from './api';
import { deckRouteHashWithFilters } from './routes';

export interface MetricDefinition {
  label: string;
  value: string;
  detail?: string;
  href?: string;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—';
  }
  const rounded = Math.round(value * 10) / 10;
  return `${rounded}%`;
}

/**
 * A deck must have this many decided games before it can be "Best Deck";
 * a 4-0 weekend shouldn't outrank a 60%-over-80-games workhorse.
 */
export const BEST_DECK_MIN_DECIDED_GAMES = 8;

/**
 * Best Deck = the winning deck (>=50% WR) with the most wins.
 *
 * A great win rate over hundreds of games is a bigger achievement than the
 * same rate over 20 — a small-sample deck only surfaces when nothing else
 * has more wins. Win rate breaks ties between equal win counts, and when no
 * deck has a winning record we fall back to the least-losing record.
 */
function bestDeckFrom(decks: DeckRow[]): DeckRow | undefined {
  const named = decks.filter(
    (deck) => deck.deck_name !== '(unknown)' && deck.wins + deck.losses > 0,
  );
  const credible = named.filter(
    (deck) => deck.wins + deck.losses >= BEST_DECK_MIN_DECIDED_GAMES,
  );
  const winning = credible.filter((deck) => deck.wins >= deck.losses);
  const pool = winning.length ? winning : credible.length ? credible : named;
  const winRateOf = (deck: DeckRow) => deck.wins / Math.max(1, deck.wins + deck.losses);
  return [...pool]
    .sort(
      (a, b) =>
        b.wins - a.wins ||
        winRateOf(b) - winRateOf(a) ||
        b.games - a.games ||
        a.deck_name.localeCompare(b.deck_name),
    )[0];
}

export function metricCards(snapshot: DashboardSnapshot): MetricDefinition[] {
  return [
    { label: 'Games', value: String(snapshot.summary.games) },
    { label: 'Wins', value: String(snapshot.summary.wins) },
    { label: 'Losses', value: String(snapshot.summary.losses) },
    { label: 'Win Rate', value: formatPercent(snapshot.summary.win_rate) },
  ];
}

/** Best Deck rendered on its own slim full-width bar below the metric cards. */
export function bestDeckMetric(
  snapshot: DashboardSnapshot,
  filters: SnapshotFilters = {},
): MetricDefinition {
  const bestDeck = bestDeckFrom(snapshot.decks);
  if (!bestDeck) {
    return { label: 'Best Deck', value: '—' };
  }
  return {
    label:
      bestDeck.wins + bestDeck.losses >= BEST_DECK_MIN_DECIDED_GAMES
        ? 'Best Deck'
        : 'Best Deck (small sample)',
    value: bestDeck.deck_name,
    detail: `${formatPercent(bestDeck.win_rate)} WR · ${bestDeck.wins}–${bestDeck.losses} · ${bestDeck.games} ${
      bestDeck.games === 1 ? 'game' : 'games'
    }`,
    href: deckRouteHashWithFilters(bestDeck.deck_name, filters),
  };
}
