export interface AppNavItem {
  id: string;
  label: string;
  /** When set, the item navigates to this hash route instead of scrolling to a section. */
  route?: string;
}

export const dashboardNavItems: AppNavItem[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'trend', label: 'Win Rate Trend' },
  { id: 'recent-games', label: 'Recent Games' },
  { id: 'decks', label: 'Decks' },
  { id: 'formats', label: 'Formats' },
  { id: 'deck-play-draw', label: 'Deck Play / Draw' },
  { id: 'visible-drawn-cards', label: 'Visible Drawn Cards' },
  { id: 'matches', label: 'Bo3 Matches' },
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
  { id: 'game-turn-timing', label: 'Turn Timing' },
  { id: 'game-draw-quality', label: 'Draw Quality' },
  { id: 'game-life', label: 'Life Totals' },
  { id: 'game-opening-hand', label: 'Opening Hand' },
  { id: 'game-draws', label: 'Drawn Cards' },
  { id: 'game-played', label: 'Cards Played' },
  { id: 'game-timeline', label: 'Timeline' },
];

export const cardNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'card-summary', label: 'Card Summary' },
  { id: 'card-usage-by-side', label: 'Usage by Side' },
  { id: 'card-decks', label: 'Your Decks' },
  { id: 'card-opener-impact', label: 'Opening Hand Impact' },
];
