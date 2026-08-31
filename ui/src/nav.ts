export interface AppNavItem {
  id: string;
  label: string;
  /** When set, the item navigates to this hash route instead of scrolling to a section. */
  route?: string;
}

// Live Log is not in this list: it renders as its own highlighted entry
// above the nav in AppShell, colored by tracker state.
export const dashboardNavItems: AppNavItem[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'trend', label: 'Win Rate Trend' },
  { id: 'rank-progress', label: 'Ranked Progress' },
  { id: 'recent-games', label: 'Recent Games' },
  { id: 'decks', label: 'Decks' },
  { id: 'land-drops', label: 'Land Statistics' },
  { id: 'habits', label: 'Habits & Schedule' },
  { id: 'brawl', label: 'Brawl' },
  { id: 'opponents', label: 'Opponents' },
  { id: 'formats', label: 'Formats' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'all-games', label: 'All Games', route: '#/games' },
];

export const gamesNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'all-games-list', label: 'All Games' },
];

export const opponentsNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#opponents' },
  { id: 'opponents-all', label: 'Opponents' },
];

export const auditNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'audit-summary', label: 'Summary' },
  { id: 'audit-findings', label: 'Findings' },
  { id: 'audit-danger', label: 'Danger Zone' },
];

export const deckNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'deck-combat', label: 'Combat Profile' },
  { id: 'deck-turn-timing', label: 'Turn Timing' },
  { id: 'deck-draw-quality', label: 'Draw Quality' },
  { id: 'deck-interaction', label: 'Combat & Resources' },
  { id: 'deck-formats', label: 'Formats' },
  { id: 'deck-trend', label: 'Win Rate Trend' },
  { id: 'deck-cards', label: 'Deck List & Card Performance' },
  { id: 'deck-mulligans', label: 'Mulligans' },
  { id: 'deck-lands', label: 'Land Statistics' },
  { id: 'deck-opponent-colors', label: 'Vs Colors' },
  { id: 'deck-versions', label: 'Decklist Changes' },
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
  { id: 'game-opponent-cards', label: 'Opponent Deck' },
  { id: 'game-timeline', label: 'Timeline' },
];

export const cardNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'card-summary', label: 'Card Summary' },
  { id: 'card-opener-impact', label: 'Opening Hand Impact' },
  { id: 'card-usage-by-side', label: 'Opponent Impact' },
  { id: 'card-usage-comparison', label: 'Played by Side' },
  { id: 'card-multiplicity', label: 'Repeat Draws' },
  { id: 'card-opponent-multiplicity', label: 'Opponent Repeat Draws' },
  { id: 'card-decks', label: 'Your Decks' },
];

export const opponentNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#recent-games' },
  { id: 'opponent-games', label: 'Game History' },
];

export const deckFinderNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '\u2190 Back to dashboard', route: '#overview' },
  { id: 'deck-finder-browse', label: 'Browse Decks' },
];

export const liveNavItems: AppNavItem[] = [
  { id: 'back-to-dashboard', label: '← Back to dashboard', route: '#overview' },
  { id: 'live-scoreboard', label: 'Scoreboard' },
];

export const settingsNavItems: AppNavItem[] = [
  // The Settings page is short and fits on one screen, so the sidebar is just
  // the way back plus a single "Settings" label \u2014 no per-section anchors that
  // wouldn't scroll anywhere anyway.
  { id: 'back-to-dashboard', label: '\u2190 Back to dashboard', route: '#overview' },
  { id: 'settings-tracker', label: 'Settings' },
];
