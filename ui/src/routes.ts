import type { SnapshotFilters } from './api';

export interface DeckRoute {
  name: string;
  filters: SnapshotFilters;
}

export interface GameRoute {
  id: string;
  returnHash: string;
  focusId: 'game-timeline' | null;
}

export interface CardRoute {
  name: string;
  returnHash: string;
  filters: SnapshotFilters;
}

export interface OpponentRoute {
  name: string;
  filters: SnapshotFilters;
}

function routeQuery(filters: SnapshotFilters, includeDeck = false): string {
  const params = new URLSearchParams();
  if (includeDeck && filters.deck) {
    params.set('deck', filters.deck);
  }
  if (filters.format) {
    params.set('format', filters.format);
  }
  if (filters.days) {
    params.set('days', String(filters.days));
  }
  if (filters.season) {
    params.set('season', String(filters.season));
  }
  if (filters.since) {
    params.set('since', filters.since);
  }
  if (filters.until) {
    params.set('until', filters.until);
  }
  if (filters.colors) {
    params.set('colors', filters.colors);
  }
  if (filters.quick && filters.quick !== 'all') {
    params.set('q', filters.quick);
  }
  return params.toString();
}

export function deckRouteHash(deckName: string): string {
  return deckRouteHashWithFilters(deckName, {});
}

export function deckRouteHashWithFilters(deckName: string, filters: SnapshotFilters = {}): string {
  const query = routeQuery(filters);
  return `#/deck/${encodeURIComponent(deckName)}${query ? `?${query}` : ''}`;
}

export function gameRouteHash(
  gameId: string,
  returnHash?: string,
  focusId?: 'game-timeline',
): string {
  const params = new URLSearchParams();
  if (returnHash?.startsWith('#')) {
    params.set('return', returnHash);
  }
  if (focusId === 'game-timeline') {
    params.set('focus', focusId);
  }
  const query = params.toString();
  return `#/game/${encodeURIComponent(gameId)}${query ? `?${query}` : ''}`;
}

export function cardRouteHash(cardName: string, returnHash?: string): string {
  const params = new URLSearchParams();
  if (returnHash && (parseGameRoute(returnHash) || parseDeckManagerRoute(returnHash))) {
    params.set('return', returnHash);
  }
  const query = params.toString();
  return `#/card/${encodeURIComponent(cardName)}${query ? `?${query}` : ''}`;
}

export function opponentRouteHash(opponentName: string): string {
  return `#/opponent/${encodeURIComponent(opponentName)}`;
}

export function dashboardRouteHash(filters: SnapshotFilters = {}): string {
  const query = routeQuery(filters, true);
  return `#overview${query ? `?${query}` : ''}`;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseFilters(query: string, includeDeck = false): SnapshotFilters {
  const params = new URLSearchParams(query);
  const filters: SnapshotFilters = {};
  const deck = params.get('deck');
  const format = params.get('format');
  const daysRaw = params.get('days');
  const days = daysRaw ? Number(daysRaw) : NaN;
  const seasonRaw = params.get('season');
  const season = seasonRaw ? Number(seasonRaw) : NaN;
  const since = params.get('since');
  const until = params.get('until');
  if (includeDeck && deck) {
    filters.deck = deck;
  }
  if (format) {
    filters.format = format;
  }
  if (Number.isFinite(days) && days > 0) {
    filters.days = days;
  }
  if (Number.isFinite(season) && season > 0) {
    filters.season = season;
  }
  if (since && ISO_DATE.test(since)) {
    filters.since = since;
  }
  if (until && ISO_DATE.test(until)) {
    filters.until = until;
  }
  const colors = params.get('colors');
  // "C" alone is the colorless filter; it never mixes with real colors.
  if (colors && /^([WUBRG]{1,5}|C)$/.test(colors)) {
    filters.colors = colors;
  }
  const quick = params.get('q');
  if (quick && /^[a-z0-9_-]{1,32}$/.test(quick)) {
    filters.quick = quick;
  }
  return filters;
}

export function parseDashboardRouteFilters(hash: string): SnapshotFilters | null {
  if (!hash.startsWith('#overview?')) {
    return null;
  }
  return parseFilters(hash.slice('#overview?'.length), true);
}

export function parseDeckRoute(hash: string): DeckRoute | null {
  if (!hash.startsWith('#/deck/')) {
    return null;
  }
  const route = hash.slice('#/deck/'.length);
  const [encoded, query = ''] = route.split('?');
  if (!encoded) {
    return null;
  }
  try {
    return { name: decodeURIComponent(encoded), filters: parseFilters(query) };
  } catch {
    return { name: encoded, filters: parseFilters(query) };
  }
}

export function parseGameRoute(hash: string): GameRoute | null {
  if (!hash.startsWith('#/game/')) {
    return null;
  }
  const route = hash.slice('#/game/'.length);
  const [encoded, query = ''] = route.split('?');
  if (!encoded) {
    return null;
  }
  const returnParam = new URLSearchParams(query).get('return');
  const requestedReturnHash = returnParam?.startsWith('#') ? returnParam : '#overview';
  const returnHash = requestedReturnHash === '#draw-quality' ? '#recent-games' : requestedReturnHash;
  const focusId = new URLSearchParams(query).get('focus') === 'game-timeline' ? 'game-timeline' : null;
  try {
    return { id: decodeURIComponent(encoded), returnHash, focusId };
  } catch {
    return { id: encoded, returnHash, focusId };
  }
}

export function parseCardRoute(hash: string): CardRoute | null {
  if (!hash.startsWith('#/card/')) {
    return null;
  }
  const route = hash.slice('#/card/'.length);
  const [encoded, query = ''] = route.split('?');
  if (!encoded) {
    return null;
  }
  const returnParam = new URLSearchParams(query).get('return');
  const returnHash = returnParam && (parseGameRoute(returnParam) || parseDeckManagerRoute(returnParam)) ? returnParam : '#overview';
  const filters = parseFilters(query, true);
  try {
    return { name: decodeURIComponent(encoded), returnHash, filters };
  } catch {
    return { name: encoded, returnHash, filters };
  }
}

export function parseOpponentRoute(hash: string): OpponentRoute | null {
  if (!hash.startsWith('#/opponent/')) {
    return null;
  }
  const route = hash.slice('#/opponent/'.length);
  const [encoded, query = ''] = route.split('?');
  if (!encoded) {
    return null;
  }
  const filters = parseFilters(query, true);
  try {
    return { name: decodeURIComponent(encoded), filters };
  } catch {
    return { name: encoded, filters };
  }
}

export function parseAuditRoute(hash: string): boolean {
  return hash === '#/audit' || hash.startsWith('#/audit?');
}

export function parseDeckFinderRoute(hash: string): boolean {
  return hash === '#/deck-finder' || hash.startsWith('#/deck-finder?');
}

export function parseDeckManagerRoute(hash: string): boolean {
  return ['#/deck-manager', '#deck-manager-library', '#deck-manager-import'].includes(hash.split('?')[0]);
}

export function parseResetRoute(hash: string): boolean {
  return hash === '#/reset' || hash.startsWith('#/reset?');
}

export function parseSettingsRoute(hash: string): boolean {
  return hash === '#/settings' || hash.startsWith('#/settings?');
}

export function parseLiveRoute(hash: string): boolean {
  return hash === '#/live' || hash.startsWith('#/live?');
}

export function gamesRouteHash(filters: SnapshotFilters = {}): string {
  const query = routeQuery(filters, true);
  return `#/games${query ? `?${query}` : ''}`;
}

export const OPPONENTS_ROUTE_HASH = '#/opponents';

export function parseOpponentsRoute(hash: string): boolean {
  return hash === OPPONENTS_ROUTE_HASH;
}

export function parseGamesRoute(hash: string): { filters: SnapshotFilters } | null {
  if (hash !== '#/games' && !hash.startsWith('#/games?')) {
    return null;
  }
  const query = hash.startsWith('#/games?') ? hash.slice('#/games?'.length) : '';
  return { filters: parseFilters(query, true) };
}

export interface ReplayRoute {
  /** null for the Replay list page (`#/replay`). */
  gameId: string | null;
  /** Event seq to open at, from `?at=`. */
  at: number | null;
  /**
   * `game_events.id` to open at, from `?row=` (Game Detail timeline deep
   * links). The viewer seeks to the first event with that `row_id`; `at` wins
   * when both are present.
   */
  row: number | null;
  /** Where the back button goes, from `?return=` (always a `#` hash). */
  returnHash: string | null;
}

export const REPLAY_ROUTE_HASH = '#/replay';

export function replayRouteHash(
  gameId?: string | null,
  options: { at?: number | null; row?: number | null; returnHash?: string | null } = {},
): string {
  if (!gameId) {
    return REPLAY_ROUTE_HASH;
  }
  const params = new URLSearchParams();
  if (options.at !== null && options.at !== undefined && Number.isInteger(options.at) && options.at >= 0) {
    params.set('at', String(options.at));
  }
  if (options.row !== null && options.row !== undefined && Number.isInteger(options.row) && options.row >= 0) {
    params.set('row', String(options.row));
  }
  if (options.returnHash?.startsWith('#')) {
    params.set('return', options.returnHash);
  }
  const query = params.toString();
  return `#/replay/${encodeURIComponent(gameId)}${query ? `?${query}` : ''}`;
}

export function parseReplayRoute(hash: string): ReplayRoute | null {
  if (hash === REPLAY_ROUTE_HASH || hash.startsWith(`${REPLAY_ROUTE_HASH}?`)) {
    return { gameId: null, at: null, row: null, returnHash: null };
  }
  if (!hash.startsWith(`${REPLAY_ROUTE_HASH}/`)) {
    return null;
  }
  const route = hash.slice(REPLAY_ROUTE_HASH.length + 1);
  const [encoded, query = ''] = route.split('?');
  if (!encoded) {
    return { gameId: null, at: null, row: null, returnHash: null };
  }
  const params = new URLSearchParams(query);
  const atRaw = params.get('at');
  const at = atRaw !== null && /^\d+$/.test(atRaw) ? Number(atRaw) : null;
  const rowRaw = params.get('row');
  const row = rowRaw !== null && /^\d+$/.test(rowRaw) ? Number(rowRaw) : null;
  const returnParam = params.get('return');
  const returnHash = returnParam?.startsWith('#') ? returnParam : null;
  let gameId = encoded;
  try {
    gameId = decodeURIComponent(encoded);
  } catch {
    // Keep the raw segment.
  }
  return { gameId, at, row, returnHash };
}
