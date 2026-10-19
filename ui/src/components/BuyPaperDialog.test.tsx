import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PaperCardInfo } from '../cardPrices';
import type { StorePrice } from '../storePrices';
import { BuyPaperButton, BuyPaperDialog } from './BuyPaperDialog';
import { resetBuyOnPaperSetting, saveBuyOnPaperEnabled } from '../buyOnPaperSetting';

vi.mock('../cardPrices', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../cardPrices')>()),
  lookupPaperPrices: vi.fn(),
}));
vi.mock('../storePrices', () => ({ fetchStorePrices: vi.fn() }));
import { lookupPaperPrices } from '../cardPrices';
import { fetchStorePrices } from '../storePrices';

const paper = (name: string, usd: number, set = 'FDN'): PaperCardInfo => ({
  status: 'paper', name, rebalanced: false, cheapest: true,
  printing: { set, set_name: 'Foundations', collector_number: '12', usd, finish: 'nonfoil' },
});

const store = (name: string, usd: number, inStock = true): StorePrice => ({
  name, usd, set: 'DOM', set_name: 'Dominaria', collector_number: '60', finish: 'nonfoil', in_stock: inStock, url: null,
});

const sections = [
  { name: 'Deck', cards: [{ quantity: 4, name: 'Opt' }, { quantity: 2, name: 'Alchemy Only' }, { quantity: 20, name: 'Island' }] },
  { name: 'Sideboard', cards: [{ quantity: 3, name: 'Negate' }] },
];

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', ''); } },
    close: { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open'); } },
  });
  vi.mocked(lookupPaperPrices).mockImplementation(async (names, onUpdate) => {
    const map = new Map<string, PaperCardInfo | null>([
      ['Opt', paper('Opt', 0.25)],
      ['Island', paper('Island', 0.05)],
      ['Negate', paper('Negate', 0.5, 'M21')],
      ['Alchemy Only', { status: 'digital_only', name: 'Alchemy Only', printing: null, rebalanced: false, cheapest: true }],
    ]);
    onUpdate(map, { pending: 0, interrupted: false });
    expect(names).toEqual(['Opt', 'Alchemy Only', 'Island', 'Negate']);
    return map;
  });
  vi.mocked(fetchStorePrices).mockResolvedValue({ prices: new Map(), asOf: '' });
});

/** The total's final value (the visible digits count up to it). */
function total() {
  return screen.getByText('Estimated Total').closest('div')!.querySelector('dd .visually-hidden')!.textContent;
}

describe('BuyPaperDialog', () => {
  it('prices each card, leaves out Arena-only cards and updates the total live', async () => {
    render(<BuyPaperDialog sections={sections} onClose={() => {}} returnFocus={null} />);

    expect(await screen.findByText('Cards')).toHaveTextContent('Cards (27 selected)');
    // 4 × 0.25 + 20 × 0.05 + 3 × 0.50
    expect(total()).toBe('$3.50');
    expect(screen.getByText('Arena only — not sold in paper')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Buy 2 Alchemy Only' })).toBeDisabled();
    expect(screen.getAllByText('$1.00')).toHaveLength(2); // 4 Opt and 20 Island
    expect(screen.getByText('$0.25 ea')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('TCGplayer market prices via Scryfall');

    fireEvent.click(screen.getByRole('checkbox', { name: 'Buy 4 Opt' }));
    expect(total()).toBe('$2.50');

    fireEvent.click(screen.getByRole('checkbox', { name: 'Sideboard' }));
    expect(total()).toBe('$1.00');
    expect(screen.queryByRole('checkbox', { name: 'Buy 3 Negate' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: /Skip basic lands/u }));
    expect(total()).toBe('$0.00');
    expect(screen.getByRole('button', { name: /Buy @/u })).toBeDisabled();
  });

  it('reprices the cart from the chosen store’s own list', async () => {
    let finish!: (value: { prices: Map<string, StorePrice | null>; asOf: string }) => void;
    vi.mocked(fetchStorePrices).mockImplementation((vendor, _names, options) => {
      if (vendor === 'manapool') {
        return Promise.resolve({ prices: new Map([['Opt', store('Opt', 0.15)], ['Island', store('Island', 0.05)], ['Negate', store('Negate', 0.2)]]), asOf: '' });
      }
      options?.onLoading?.();
      return new Promise((resolve) => { finish = resolve; });
    });
    const { container } = render(<BuyPaperDialog sections={sections} onClose={() => {}} returnFocus={null} />);
    await screen.findByText('Cards');
    // Both store lists load as the dialog opens.
    expect(fetchStorePrices).toHaveBeenCalledWith('cardkingdom', ['Opt', 'Alchemy Only', 'Island', 'Negate'], expect.anything());
    expect(fetchStorePrices).toHaveBeenCalledWith('manapool', ['Opt', 'Alchemy Only', 'Island', 'Negate'], expect.anything());

    fireEvent.click(within(screen.getByRole('list', { name: 'Store' })).getByRole('button', { name: /^Card Kingdom/u }));

    expect(screen.getByRole('status')).toHaveTextContent('Downloading Card Kingdom’s price list');
    expect(container.querySelectorAll('.buy-paper-price .buy-paper-skeleton')).toHaveLength(3);

    await act(async () => {
      finish({
        prices: new Map([['Opt', store('Opt', 0.35)], ['Island', store('Island', 0.1, false)], ['Negate', null]]),
        asOf: '2026-10-18 19:08:27',
      });
    });
    // 4 × 0.35 + 20 × 0.10. Negate isn't listed, so it has no price and isn't
    // in the total: no other store's price stands in for it.
    expect(total()).toBe('$3.40');
    expect(screen.getByText('Sold out')).toBeInTheDocument();
    expect(screen.getByText('Not listed at Card Kingdom')).toBeInTheDocument();
    expect(screen.queryByText('$1.50')).not.toBeInTheDocument();
    expect(screen.getByText('Sold out at Card Kingdom')).toBeInTheDocument();
    expect(screen.getByText('Not listed at Card Kingdom (not in total)')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Card Kingdom prices as of 2026-10-18');
    expect(screen.getAllByText('Dominaria (DOM) #60')).toHaveLength(2);

    // The store list: alphabetical, each store's own total, lowest marked only
    // among stores that price every card.
    const compare = screen.getByRole('list', { name: 'Store' });
    expect(Array.from(compare.querySelectorAll('.buy-paper-compare-name'), (name) => name.firstChild?.textContent))
      .toEqual(['Card Kingdom', 'CoolStuffInc', 'Mana Pool', 'StarCityGames', 'TCGplayer']);
    const rowFor = (name: string) => within(compare).getByRole('button', { name: new RegExp(`^${name}`, 'u') });
    expect(rowFor('Card Kingdom')).toHaveAttribute('aria-pressed', 'true');
    expect(rowFor('Card Kingdom').querySelector('.visually-hidden')).toHaveTextContent('$3.40');
    expect(rowFor('Card Kingdom')).toHaveTextContent('3 missing');
    expect(rowFor('Mana Pool').querySelector('.visually-hidden')).toHaveTextContent('$2.20');
    expect(rowFor('TCGplayer').querySelector('.visually-hidden')).toHaveTextContent('$3.50');
    expect(rowFor('Mana Pool')).toHaveTextContent('Lowest');
    // Stores with no way to price the cart are coming soon and can't be chosen.
    for (const name of ['StarCityGames', 'CoolStuffInc']) {
      expect(rowFor(name)).toHaveTextContent('Coming soon');
      expect(rowFor(name)).not.toHaveTextContent('$');
      expect(rowFor(name)).toBeDisabled();
    }
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    fireEvent.click(rowFor('Mana Pool'));
    expect(total()).toBe('$2.20');
    expect(screen.getByRole('button', { name: 'Buy @ Mana Pool' })).toBeInTheDocument();
  });

  it('shows no prices when a store’s list can’t be loaded', async () => {
    vi.mocked(fetchStorePrices).mockRejectedValue(new Error('down'));
    localStorage.setItem('mtga-tracker-buy-paper-v1', JSON.stringify({ vendor: 'cardkingdom' }));
    const { container } = render(<BuyPaperDialog sections={sections} onClose={() => {}} returnFocus={null} />);
    await screen.findByText('Cards');

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Couldn’t load Card Kingdom’s price list, so no prices are shown.'));
    expect(screen.getByText('Estimated Total').closest('div')!.querySelector('dd')).toHaveTextContent('—');
    container.querySelectorAll('.buy-paper-price').forEach((cell) => expect(cell).toHaveTextContent(/^—$/u));
    const compare = screen.getByRole('list', { name: 'Store' });
    expect(within(compare).getByRole('button', { name: /^Mana Pool/u })).not.toHaveTextContent('$');
    expect(within(compare).getByRole('button', { name: /^TCGplayer/u }).querySelector('.visually-hidden')).toHaveTextContent('$3.50');
  });

  it('starts on TCGplayer', async () => {
    render(<BuyPaperDialog sections={sections} onClose={() => {}} returnFocus={null} />);
    expect(await screen.findByRole('button', { name: 'Buy @ TCGplayer' })).toBeInTheDocument();
  });

  it('falls back to TCGplayer when the saved store is coming soon', async () => {
    localStorage.setItem('mtga-tracker-buy-paper-v1', JSON.stringify({ vendor: 'starcitygames' }));
    render(<BuyPaperDialog sections={sections} onClose={() => {}} returnFocus={null} />);
    expect(await screen.findByRole('button', { name: 'Buy @ TCGplayer' })).toBeInTheDocument();
  });

  it('opens the chosen store with the selected cards', async () => {
    vi.mocked(fetchStorePrices).mockResolvedValue({ prices: new Map(), asOf: '' });
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    render(<BuyPaperDialog sections={sections} onClose={() => {}} returnFocus={null} />);
    await screen.findByText('Cards');

    fireEvent.click(within(screen.getByRole('list', { name: 'Store' })).getByRole('button', { name: /^Card Kingdom/u }));
    fireEvent.click(screen.getByRole('button', { name: 'Buy @ Card Kingdom' }));

    await waitFor(() => expect(open).toHaveBeenCalled());
    const url = new URL(String(open.mock.calls[0][0]));
    expect(url.origin + url.pathname).toBe('https://www.cardkingdom.com/builder');
    expect(url.searchParams.get('c')).toBe('4 Opt\n20 Island\n3 Negate');
    expect(open.mock.calls[0][1]).toBe('_blank');
    expect(screen.getByRole('status')).toHaveTextContent('Opened Card Kingdom in a new tab.');
    expect(JSON.parse(localStorage.getItem('mtga-tracker-buy-paper-v1')!).vendor).toBe('cardkingdom');
  });
});

describe('Buy on Paper setting', () => {
  it('hides the button until the switch is known and when it is turned off', async () => {
    resetBuyOnPaperSetting();
    let answer!: (response: Response) => void;
    const fetchMock = vi.fn((url: string) => (url === '/api/paper-prices/status'
      ? new Promise<Response>((resolve) => { answer = resolve; })
      : Promise.resolve(new Response(JSON.stringify({ buy_on_paper: { enabled: false, cache_bytes: 0 } }), { status: 200 }))));
    vi.stubGlobal('fetch', fetchMock);
    localStorage.setItem('mtga-tracker-paper-prices-v1', '{}');

    render(<BuyPaperButton onOpen={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Buy on Paper' })).not.toBeInTheDocument();
    await act(async () => { answer(new Response(JSON.stringify({ enabled: true, cache_bytes: 0 }), { status: 200 })); });
    expect(screen.getByRole('button', { name: 'Buy on Paper' })).toBeInTheDocument();

    await act(async () => { await saveBuyOnPaperEnabled(false); });
    expect(fetchMock).toHaveBeenCalledWith('/api/settings/buy-on-paper', expect.objectContaining({ body: '{"enabled":false}' }));
    expect(screen.queryByRole('button', { name: 'Buy on Paper' })).not.toBeInTheDocument();
    expect(localStorage.getItem('mtga-tracker-paper-prices-v1')).toBeNull();
    vi.unstubAllGlobals();
  });
});
