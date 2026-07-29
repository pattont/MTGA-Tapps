export interface AppNavItem {
  id: string;
  label: string;
  /** When set, the item navigates to this hash route instead of scrolling to a section. */
  route?: string;
}

export const dashboardNavItems: AppNavItem[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'trend', label: 'Win Rate Trend' },
  { id: 'rank-progress', label: 'Ranked Progress' },
  { id: 'recent-games', label: 'Recent Games' },
  { id: 'decks', label: 'Decks' },
  { id: 'land-drops', label: 'Land Availability' },
  { id: 'habits', label: 'Habits & Schedule' },
  { id: 'outcomes', label: 'Streaks & Outcomes' },
  { id: 'opponent-meta', label: 'Opponent Meta' },
  { id: 'formats', label: 'Formats' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'all-games', label: 'All Games', route: '#/games' },
  { id: 'db-health', label: 'DB Health', route: '#/audit' },
];

export const gamesNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'all-games-list', label: 'All Games' },
];

export const auditNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'audit-summary', label: 'Summary' },
  { id: 'audit-findings', label: 'Findings' },
];

export const deckNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'deck-trend', label: 'Win Rate Trend' },
  { id: 'deck-combat', label: 'Combat Profile' },
  { id: 'deck-cards', label: 'Deck List & Card Performance' },
  { id: 'deck-mulligans', label: 'Mulligans' },
  { id: 'deck-versions', label: 'Decklist Changes' },
  { id: 'deck-lands', label: 'Land Availability' },
  { id: 'deck-formats', label: 'Formats' },
  { id: 'deck-games', label: 'Recent Games' },
];

export const gameNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'game-summary', label: 'Summary' },
  { id: 'game-turn-timing', label: 'Turn Timing' },
  { id: 'game-draw-quality', label: 'Draw Quality' },
  { id: 'game-combat', label: 'Combat & Resources' },
  { id: 'game-life', label: 'Life Totals' },
  { id: 'game-opening-hand', label: 'Opening Hand' },
  { id: 'game-draws', label: 'Drawn Cards' },
  { id: 'game-played', label: 'Cards Played' },
  { id: 'game-opponent-cards', label: 'Opponent Cards' },
  { id: 'game-timeline', label: 'Timeline' },
];

export const cardNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'card-summary', label: 'Card Summary' },
  { id: 'card-usage-by-side', label: 'Opponent Impact' },
  { id: 'card-usage-comparison', label: 'Played by Side' },
  { id: 'card-decks', label: 'Your Decks' },
  { id: 'card-multiplicity', label: 'Repeat Draws' },
  { id: 'card-opener-impact', label: 'Opening Hand Impact' },
];

export const opponentNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#recent-games' },
  { id: 'opponent-summary', label: 'Summary' },
  { id: 'opponent-games', label: 'Game History' },
];
