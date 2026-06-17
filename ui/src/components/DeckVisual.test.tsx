import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
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
});
