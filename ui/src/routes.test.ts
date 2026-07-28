import { describe, expect, it } from 'vitest';
import { cardRouteHash, gameRouteHash, parseCardRoute, parseGameRoute } from './routes';

describe('detail route return context', () => {
  it('round-trips a timeline card route back to the same game timeline', () => {
    const gameHash = gameRouteHash('game:1', '#recent-games', 'game-timeline');
    const cardHash = cardRouteHash('Sheltered by Ghosts', gameHash);

    expect(parseCardRoute(cardHash)).toEqual({
      name: 'Sheltered by Ghosts',
      returnHash: gameHash,
      filters: {},
    });
    expect(parseGameRoute(gameHash)).toEqual({
      id: 'game:1',
      returnHash: '#recent-games',
      focusId: 'game-timeline',
    });
  });

  it('rejects non-game return locations on card routes', () => {
    expect(parseCardRoute('#/card/Swamp?return=https%3A%2F%2Fexample.com')).toEqual({
      name: 'Swamp',
      returnHash: '#overview',
      filters: {},
    });
  });
});


describe('filter round-trips', () => {
  it('carries season and date-range filters through the dashboard route', async () => {
    const { dashboardRouteHash, parseDashboardRouteFilters } = await import('./routes');
    const hash = dashboardRouteHash({
      deck: 'Boros Mouse',
      format: 'Play',
      days: 30,
      season: 91,
      since: '2026-06-01',
      until: '2026-06-30',
    });
    expect(parseDashboardRouteFilters(hash)).toEqual({
      deck: 'Boros Mouse',
      format: 'Play',
      days: 30,
      season: 91,
      since: '2026-06-01',
      until: '2026-06-30',
    });
  });

  it('parses opponent routes with filters', async () => {
    const { parseOpponentRoute } = await import('./routes');
    expect(parseOpponentRoute('#/opponent/Foe?format=Play&days=7')).toEqual({
      name: 'Foe',
      filters: { format: 'Play', days: 7 },
    });
  });

  it('drops malformed date filters', async () => {
    const { parseDashboardRouteFilters } = await import('./routes');
    expect(parseDashboardRouteFilters('#overview?since=yesterday&until=2026-13-99x')).toEqual({});
  });
});

describe('all-games route', () => {
  it('round-trips filters through the games route', async () => {
    const { gamesRouteHash, parseGamesRoute } = await import('./routes');
    expect(parseGamesRoute('#/games')).toEqual({ filters: {} });
    const hash = gamesRouteHash({ deck: 'Boros Mouse', days: 30 });
    expect(parseGamesRoute(hash)).toEqual({ filters: { deck: 'Boros Mouse', days: 30 } });
    expect(parseGamesRoute('#/game/abc')).toBeNull();
  });
});
