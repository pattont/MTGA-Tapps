import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { cardPreviewImageUrl } from '../cardPreview';
import { DeckFinderDeckList } from './DeckFinderDeckList';

const deck = {
  name: 'Mono-Red',
  mainCount: 4,
  sections: [{ name: 'Deck', cards: [{ quantity: 4, name: 'Burst Lightning' }] }],
};

it('shows the card image on hover without linking to the card page', async () => {
  const user = userEvent.setup();
  render(<DeckFinderDeckList deck={deck as never} />);
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  // Nothing loads until a card is hovered.
  expect(screen.queryByRole('img')).not.toBeInTheDocument();

  const name = screen.getByText('Burst Lightning');
  await user.hover(name);
  await screen.findByRole('tooltip');
  expect(screen.getByRole('img', { name: 'Burst Lightning card preview' })).toHaveAttribute('src', cardPreviewImageUrl('Burst Lightning'));

  await user.unhover(name);
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
});
