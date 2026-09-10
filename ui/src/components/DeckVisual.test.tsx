import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DeckVisual as DeckVisualData } from '../api';
import { ART_LOAD_TIMEOUT_MS, DeckVisual } from './DeckVisual';

describe('DeckVisual', () => {
  it('renders card art when an image url is available', () => {
    render(
      <DeckVisual
        deckName="Boros Mouse"
        visual={{
          card_id: 123,
          card_name: 'Mouse Mentor',
          type_category: 'Creature',
          image_url: 'https://api.scryfall.com/cards/named?fuzzy=Mouse%20Mentor&format=image&version=art_crop',
          source: 'local_metadata',
        }}
      />,
    );

    const art = screen.getByRole('img', { name: 'Mouse Mentor' });
    expect(art).toBeInTheDocument();
    // The frame is the base layer; the art is only shown once it has loaded.
    expect(art.className).not.toContain('deck-visual-art-loaded');
    expect(screen.getByText('Creature')).toBeInTheDocument();
    fireEvent.load(art);
    expect(art.className).toContain('deck-visual-art-loaded');
  });

  it('falls back to the type frame when the image fails to load', () => {
    render(
      <DeckVisual
        deckName="Boros Mouse"
        visual={{
          card_id: 123,
          card_name: 'Mouse Mentor',
          type_category: 'Creature',
          image_url: 'https://api.scryfall.com/cards/named?fuzzy=Mouse%20Mentor&format=image&version=art_crop',
          source: 'local_metadata',
        }}
      />,
    );

    fireEvent.error(screen.getByRole('img', { name: 'Mouse Mentor' }));

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('Mouse Mentor')).toBeInTheDocument();
    expect(screen.getByText('Creature')).toBeInTheDocument();
  });

  it('gives up on a request that neither loads nor errors and tries the next source', () => {
    vi.useFakeTimers();
    try {
      render(
        <DeckVisual
          deckName="Boros Mouse"
          visual={{
            card_id: 123,
            card_name: 'Mouse Mentor',
            type_category: 'Creature',
            image_url: 'https://api.scryfall.com/cards/arena/97593?format=image&version=art_crop',
            image_fallback_url:
              'https://api.scryfall.com/cards/named?fuzzy=Mouse%20Mentor&format=image&version=art_crop',
            source: 'local_metadata',
          }}
        />,
      );
      const first = screen.getByRole('img', { name: 'Mouse Mentor' });
      expect(first.getAttribute('src')).toContain('/cards/arena/');
      act(() => {
        vi.advanceTimersByTime(ART_LOAD_TIMEOUT_MS + 1);
      });
      const second = screen.getByRole('img', { name: 'Mouse Mentor' });
      expect(second.getAttribute('src')).toContain('/cards/named');
      act(() => {
        vi.advanceTimersByTime(ART_LOAD_TIMEOUT_MS + 1);
      });
      // Both sources gave up: only the frame remains.
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
      expect(screen.getByText('Mouse Mentor')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders local metadata without an image tag', () => {
    render(
      <DeckVisual
        deckName="Boros Mouse"
        visual={{
          card_id: 123,
          card_name: 'Mouse Mentor',
          type_category: 'Creature',
          image_url: null,
          source: 'local_metadata',
        }}
      />,
    );

    expect(screen.getByText('Mouse Mentor')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('falls back when runtime metadata is blank or nullish', () => {
    const visual = {
      card_id: null,
      card_name: '',
      type_category: null,
      image_url: null,
      source: 'deck_name',
    } as unknown as DeckVisualData;

    render(<DeckVisual deckName="Boros Mouse" visual={visual} />);

    expect(screen.getByText('Boros Mouse')).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
  });
});
