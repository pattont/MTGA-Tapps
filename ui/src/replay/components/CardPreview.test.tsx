import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { card } from '../fixtures/streamBuilder';
import { ImageQueue, resolvedImageCache } from '../images';
import { HoverStore, SICK_NOTE } from '../scene/hoverStore';
import { TextureStore } from '../scene/textureStore';
import { CardPreview } from './CardPreview';

const LARGE = 'https://cards.scryfall.io/large/front/g/g/goblin.jpg';

describe('CardPreview', () => {
  beforeEach(() => resolvedImageCache.reset(true));
  afterEach(() => vi.restoreAllMocks());

  it('never points an <img> at api.scryfall.com: lookups go through the rate-limited queue', async () => {
    let finish!: (url: string) => void;
    const resolve = vi.fn<(url: string) => Promise<string>>(
      () =>
        new Promise<string>((done) => {
          finish = done;
        }),
    );
    const store = new TextureStore(
      {
        a9: card('Goblin Guide', 'Creature', { arena_id: 9 }),
        a2: card('Bear', 'Creature', { image_url: 'https://cards.scryfall.io/normal/front/b/2/bear.jpg' }),
      },
      { queue: new ImageQueue({ resolve }) },
    );
    const hover = new HoverStore();
    render(<CardPreview hover={hover} store={store} />);

    act(() => hover.set({ key: 'scene:1', card: 'a9', name: 'Goblin Guide', x: 10, y: 10, source: 'scene' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Goblin Guide');
    expect(screen.queryByRole('img')).toBeNull();
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(resolve.mock.calls[0][0]).toContain('api.scryfall.com');

    // Pointer moves over the same card do not start another lookup.
    act(() => hover.set({ key: 'scene:1', card: 'a9', name: 'Goblin Guide', x: 20, y: 30, source: 'scene' }));
    expect(resolve).toHaveBeenCalledTimes(1);

    await act(async () => finish(LARGE));
    expect(screen.getByRole('img')).toHaveAttribute('src', LARGE);

    // A card with a CDN image previews immediately, without the queue.
    act(() => hover.set({ key: 'scene:2', card: 'a2', name: 'Bear', x: 10, y: 10, source: 'scene' }));
    expect(screen.getByRole('img')).toHaveAttribute('src', 'https://cards.scryfall.io/large/front/b/2/bear.jpg');
    expect(resolve).toHaveBeenCalledTimes(1);
    for (const image of screen.queryAllByRole('img')) {
      expect(image.getAttribute('src')).not.toContain('api.scryfall.com');
    }
    store.dispose();
  });

  it('says when the hovered creature is summoning sick', () => {
    const store = new TextureStore({ a2: card('Bear', 'Creature', { image_url: 'https://cards.scryfall.io/normal/front/b/2/bear.jpg' }) });
    const hover = new HoverStore();
    render(<CardPreview hover={hover} store={store} />);
    act(() => hover.set({ key: 'scene:2', card: 'a2', name: 'Bear', note: SICK_NOTE, x: 10, y: 10, source: 'scene' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent("Summoning sick: can't attack");
    act(() => hover.set({ key: 'scene:3', card: 'a2', name: 'Bear', x: 10, y: 10, source: 'scene' }));
    expect(screen.getByRole('tooltip')).not.toHaveTextContent('Summoning sick');
    store.dispose();
  });

  it('lists the cards tucked under the hovered permanent, top of the stack first', () => {
    const store = new TextureStore(
      {
        a1: card('Deep-Cavern Bat', 'Creature', { image_url: 'https://cards.scryfall.io/normal/front/b/a/bat.jpg' }),
        a2: card('Island', 'Land', { image_url: 'https://cards.scryfall.io/normal/front/i/s/island.jpg' }),
        a3: card('Sword', 'Artifact', { image_url: 'https://cards.scryfall.io/normal/front/s/w/sword.jpg' }),
      },
      { queue: new ImageQueue({ resolve: async () => Promise.reject(new Error('unused')) }) },
    );
    const hover = new HoverStore();
    render(<CardPreview hover={hover} store={store} />);
    act(() =>
      hover.set({
        key: 'scene:bat',
        card: 'a1',
        name: 'Deep-Cavern Bat',
        under: [
          { card: 'a3', name: 'Sword', zone: 'battlefield' },
          { card: 'a2', name: 'Island', zone: 'exile' },
          { card: null, name: '', zone: 'exile' },
        ],
        x: 10,
        y: 10,
        source: 'scene',
      }),
    );
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('Under this card');
    const rows = tooltip.querySelectorAll('.replay-preview-under li');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Face-down card');
    expect(rows[1]).toHaveTextContent('Island');
    expect(rows[1]).toHaveTextContent('exiled');
    expect(rows[2]).toHaveTextContent('Sword');
    expect(rows[2]).not.toHaveTextContent('exiled');
    expect(rows[2].querySelector('img')).toHaveAttribute('src', 'https://cards.scryfall.io/large/front/s/w/sword.jpg');
    // Beside it, one picture per distinct card (top of the stack first), the face-down card skipped.
    const pictures = tooltip.querySelectorAll('.replay-preview-picture');
    expect(pictures).toHaveLength(2);
    expect(pictures[0].querySelector('img')).toHaveAttribute('src', 'https://cards.scryfall.io/large/front/i/s/island.jpg');
    expect(pictures[1].querySelector('img')).toHaveAttribute('src', 'https://cards.scryfall.io/large/front/s/w/sword.jpg');
    expect(pictures[0].querySelector('.replay-preview-picture-count')).toBeNull();

    // Three copies of one card: one picture with a count.
    act(() =>
      hover.set({
        key: 'scene:host',
        card: 'a1',
        name: 'Deep-Cavern Bat',
        under: [1, 2, 3].map(() => ({ card: 'a3', name: 'Sword', zone: 'battlefield' as const })),
        x: 10,
        y: 10,
        source: 'scene',
      }),
    );
    const only = screen.getByRole('tooltip').querySelectorAll('.replay-preview-picture');
    expect(only).toHaveLength(1);
    expect(only[0].querySelector('.replay-preview-picture-count')).toHaveTextContent('×3');

    // A plain card shows no list and no pictures.
    act(() => hover.set({ key: 'scene:isl', card: 'a2', name: 'Island', x: 10, y: 10, source: 'scene' }));
    expect(screen.getByRole('tooltip').querySelector('.replay-preview-under')).toBeNull();
    expect(screen.getByRole('tooltip').querySelector('.replay-preview-pictures')).toBeNull();
    store.dispose();
  });

  it('falls back to the procedural face when no image exists anywhere', async () => {
    const store = new TextureStore(
      { 'n:Treefolk': card('Treefolk', 'Creature', { is_token: true, power: '*', toughness: '4' }) },
      { queue: new ImageQueue({ resolve: async () => Promise.reject(new Error('404')), burst: 10 }) },
    );
    vi.spyOn(store, 'generatedFaceUrl').mockReturnValue('data:image/png;base64,AAAA');
    const hover = new HoverStore();
    render(<CardPreview hover={hover} store={store} />);
    await act(async () => hover.set({ key: 'scene:3', card: 'n:Treefolk', name: 'Treefolk', x: 10, y: 10, source: 'scene' }));
    await act(async () => {
      await new Promise((done) => setTimeout(done, 0));
    });
    const image = screen.getByRole('img');
    expect(image).toHaveAttribute('src', 'data:image/png;base64,AAAA');
    expect(image).toHaveClass('card-preview-generated');
    expect(screen.queryByText('Card image unavailable')).toBeNull();
    store.dispose();
  });
});
