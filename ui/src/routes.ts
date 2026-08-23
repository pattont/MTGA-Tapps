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
  if (returnHash && parseGameRoute(returnHash)) {
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
  if (colors && /^[WUBRG]{1,5}$/.test(colors)) {
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
  const returnHash = returnParam && parseGameRoute(returnParam) ? returnParam : '#overview';
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

export function parseSettingsRoute(hash: string): boolean {
  return hash === '#/settings' || hash.startsWith('#/settings?');
}

export function gamesRouteHash(filters: SnapshotFilters = {}): string {
  const query = routeQuery(filters, true);
  return `#/games${query ? `?${query}` : ''}`;
}

export function parseGamesRoute(hash: string): { filters: SnapshotFilters } | null {
  if (hash !== '#/games' && !hash.startsWith('#/games?')) {
    return null;
  }
  const query = hash.startsWith('#/games?') ? hash.slice('#/games?'.length) : '';
  return { filters: parseFilters(query, true) };
}
