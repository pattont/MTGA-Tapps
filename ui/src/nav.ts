export interface AppNavItem {
  id: string;
  label: string;
  /** When set, the item navigates to this hash route instead of scrolling to a section. */
  route?: string;
}

export const dashboardNavItems: AppNavItem[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'trend', label: 'Win Rate Trend' },
  { id: 'decks', label: 'Decks' },
  { id: 'formats', label: 'Formats' },
  { id: 'play-draw', label: 'Play / Draw' },
  { id: 'deck-play-draw', label: 'Deck Play / Draw' },
  { id: 'draw-quality', label: 'Draw Quality' },
  { id: 'visible-drawn-cards', label: 'Visible Drawn Cards' },
  { id: 'momentum', label: 'Momentum' },
  { id: 'recent-games', label: 'Recent Games' },
  { id: 'matches', label: 'Matches' },
  { id: 'sessions', label: 'Sessions' },
];

export const deckNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'deck-trend', label: 'Win Rate Trend' },
  { id: 'deck-cards', label: 'Card Performance' },
  { id: 'deck-openers', label: 'Opening Hands' },
  { id: 'deck-mulligans', label: 'Mulligans' },
  { id: 'deck-formats', label: 'Formats' },
  { id: 'deck-games', label: 'Recent Games' },
];

export const gameNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'game-summary', label: 'Summary' },
  { id: 'game-life', label: 'Life Totals' },
  { id: 'game-opening-hand', label: 'Opening Hand' },
  { id: 'game-draws', label: 'Drawn Cards' },
  { id: 'game-played', label: 'Cards Played' },
  { id: 'game-timeline', label: 'Timeline' },
];

export const cardNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'card-summary', label: 'Card Summary' },
  { id: 'card-decks', label: 'Decks' },
  { id: 'card-opener-impact', label: 'Opening Hand Impact' },
];
