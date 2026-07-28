import { describe, expect, it } from 'vitest';
import { cardRouteHash, gameRouteHash, parseCardRoute, parseGameRoute } from './routes';

describe('detail route return context', () => {
  it('round-trips a timeline card route back to the same game timeline', () => {
    const gameHash = gameRouteHash('game:1', '#recent-games', 'game-timeline');
    const cardHash = cardRouteHash('Sheltered by Ghosts', gameHash);

    expect(parseCardRoute(cardHash)).toEqual({
      name: 'Sheltered by Ghosts',
      returnHash: gameHash,
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
    });
  });
});
