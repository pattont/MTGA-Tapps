import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { cardPreviewImageUrl, cardPreviewMetadataUrl } from '../cardPreview';
import { CardLink } from './CardLink';

describe('CardLink', () => {
  it('mounts a full card image only after the hover delay and closes after exit', async () => {
    const user = userEvent.setup();
    render(<CardLink cardName="Sheltered by Ghosts" />);
    const link = screen.getByRole('link', { name: 'Sheltered by Ghosts' });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();

    await user.hover(link);
    const preview = await screen.findByRole('tooltip');
    const image = screen.getByRole('img', { name: 'Sheltered by Ghosts card preview' });
    expect(preview).toHaveAttribute('data-card-name', 'Sheltered by Ghosts');
    expect(image).toHaveAttribute('src', cardPreviewImageUrl('Sheltered by Ghosts'));

    await user.unhover(link);
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  });

  it('opens from keyboard focus and dismisses on Escape', async () => {
    const user = userEvent.setup();
    render(<CardLink cardName="Case of the Stashed Skeleton" />);

    await user.tab();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  });

  it('preserves normal anchor properties and return-aware navigation', () => {
    const onClick = vi.fn();
    render(
      <CardLink
        cardName="Mouse Mentor"
        returnHash="#/game/game-1?focus=game-timeline"
        className="search-option"
        role="option"
        aria-selected={false}
        onClick={onClick}
      />,
    );

    const link = screen.getByRole('option', { name: 'Mouse Mentor' });
    expect(link).toHaveClass('card-link', 'search-option');
    expect(link).toHaveAttribute(
      'href',
      '#/card/Mouse%20Mentor?return=%23%2Fgame%2Fgame-1%3Ffocus%3Dgame-timeline',
    );
    fireEvent.click(link);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('remembers failed preview images for the browser session', async () => {
    const cardName = 'Definitely Missing Preview Card';
    const { unmount } = render(<CardLink cardName={cardName} />);
    const firstLink = screen.getByRole('link', { name: cardName });

    firstLink.focus();
    const image = await screen.findByRole('img', { name: `${cardName} card preview` });
    fireEvent.error(image);
    expect(await screen.findByText('Card image unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    unmount();

    render(<CardLink cardName={cardName} />);
    screen.getByRole('link', { name: cardName }).focus();
    expect(await screen.findByText('Card image unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('encodes punctuation and requests Scryfall normal images', () => {
    const url = new URL(cardPreviewImageUrl("Fire // Ice's Test"));

    expect(url.origin).toBe('https://api.scryfall.com');
    expect(url.pathname).toBe('/cards/named');
    expect(url.searchParams.get('exact')).toBe("Fire // Ice's Test");
    expect(url.searchParams.get('format')).toBe('image');
    expect(url.searchParams.get('version')).toBe('normal');
  });

  it('uses Scryfall split layout to rotate previews while displaying a single slash', async () => {
    const cardName = 'Unholy Annex // Ritual Chamber';
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ layout: 'split' }), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<CardLink cardName={cardName} />);

    const link = screen.getByRole('link', { name: 'Unholy Annex / Ritual Chamber' });
    expect(link).toHaveAttribute('href', '#/card/Unholy%20Annex%20%2F%2F%20Ritual%20Chamber');
    await user.hover(link);

    const preview = await screen.findByRole('tooltip');
    await waitFor(() => expect(preview).toHaveAttribute('data-card-orientation', 'landscape'));
    expect(preview).toHaveClass('card-preview-landscape');
    expect(screen.getByRole('img', { name: 'Unholy Annex / Ritual Chamber card preview' })).toHaveAttribute(
      'src',
      cardPreviewImageUrl(cardName),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      cardPreviewMetadataUrl(cardName),
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );
    vi.unstubAllGlobals();
  });
});
