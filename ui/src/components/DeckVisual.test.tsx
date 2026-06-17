import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DeckVisual as DeckVisualData } from '../api';
import { DeckVisual } from './DeckVisual';

describe('DeckVisual', () => {
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
