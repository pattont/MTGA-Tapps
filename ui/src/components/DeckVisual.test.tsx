import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DeckVisual as DeckVisualData } from '../api';
import { DeckVisual } from './DeckVisual';

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

    expect(screen.getByRole('img', { name: 'Mouse Mentor' })).toBeInTheDocument();
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
