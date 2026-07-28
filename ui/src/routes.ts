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

function parseFilters(query: string, includeDeck = false): SnapshotFilters {
  const params = new URLSearchParams(query);
  const filters: SnapshotFilters = {};
  const deck = params.get('deck');
  const format = params.get('format');
  const daysRaw = params.get('days');
  const days = daysRaw ? Number(daysRaw) : NaN;
  if (includeDeck && deck) {
    filters.deck = deck;
  }
  if (format) {
    filters.format = format;
  }
  if (Number.isFinite(days) && days > 0) {
    filters.days = days;
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
  try {
    return { name: decodeURIComponent(encoded), returnHash };
  } catch {
    return { name: encoded, returnHash };
  }
}

export function parseOpponentRoute(hash: string): string | null {
  if (!hash.startsWith('#/opponent/')) {
    return null;
  }
  const encoded = hash.slice('#/opponent/'.length).split('?')[0];
  if (!encoded) {
    return null;
  }
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}
