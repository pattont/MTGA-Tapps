import type { SnapshotFilters } from './api';

export interface DeckRoute {
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
  return params.toString();
}

export function deckRouteHash(deckName: string): string {
  return deckRouteHashWithFilters(deckName, {});
}

export function deckRouteHashWithFilters(deckName: string, filters: SnapshotFilters = {}): string {
  const query = routeQuery(filters);
  return `#/deck/${encodeURIComponent(deckName)}${query ? `?${query}` : ''}`;
}

export function gameRouteHash(gameId: string): string {
  return `#/game/${encodeURIComponent(gameId)}`;
}

export function cardRouteHash(cardName: string): string {
  return `#/card/${encodeURIComponent(cardName)}`;
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

export function parseGameRoute(hash: string): string | null {
  if (!hash.startsWith('#/game/')) {
    return null;
  }
  const encoded = hash.slice('#/game/'.length);
  if (!encoded) {
    return null;
  }
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}

export function parseCardRoute(hash: string): string | null {
  if (!hash.startsWith('#/card/')) {
    return null;
  }
  const encoded = hash.slice('#/card/'.length);
  if (!encoded) {
    return null;
  }
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}
