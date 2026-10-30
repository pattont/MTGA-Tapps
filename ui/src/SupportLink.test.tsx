import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
import { buyMeACoffeeUrl } from './supportLink';

vi.mock('./api', () => ({ fetchDashboardSnapshot: vi.fn() }));
vi.mock('./components/DeckManagerPage', () => ({ DeckManagerPage: () => <p>Saved deck library</p> }));
vi.mock('./supportLink', () => ({ buyMeACoffeeUrl: vi.fn() }));

afterEach(() => { window.location.hash = ''; vi.unstubAllGlobals(); });

function renderDeckManager() {
  window.location.hash = '#/deck-manager';
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ tracker: { state: 'idle' } }) }));
  render(<App />);
}

it('shows the Buy me a coffee tile right below Deck Manager once a username is set', () => {
  vi.mocked(buyMeACoffeeUrl).mockReturnValue('https://buymeacoffee.com/tapps');
  renderDeckManager();
  const tile = screen.getByRole('link', { name: 'Buy me a coffee' });
  expect(tile).toHaveClass('sidebar-coffee');
  expect(tile).toHaveAttribute('href', 'https://buymeacoffee.com/tapps');
  expect(tile).toHaveAttribute('target', '_blank');
  expect(tile).toHaveAttribute('rel', 'noreferrer');
  const manager = screen.getByRole('link', { name: 'Deck Manager Beta' });
  expect(manager.nextElementSibling).toBe(tile);
});

it('hides the tile while no username is set', () => {
  vi.mocked(buyMeACoffeeUrl).mockReturnValue(null);
  renderDeckManager();
  expect(screen.queryByRole('link', { name: 'Buy me a coffee' })).not.toBeInTheDocument();
});
