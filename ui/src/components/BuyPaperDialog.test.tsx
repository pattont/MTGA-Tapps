import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PaperCardInfo } from '../cardPrices';
import { BuyPaperDialog } from './BuyPaperDialog';

vi.mock('../cardPrices', () => ({ lookupPaperPrices: vi.fn() }));
import { lookupPaperPrices } from '../cardPrices';

const paper = (name: string, usd: number, set = 'FDN'): PaperCardInfo => ({
  status: 'paper', name, rebalanced: false, cheapest: true,
  printing: { set, set_name: 'Foundations', collector_number: '12', usd, finish: 'nonfoil' },
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
});

function total() {
  return screen.getByText('Estimated Total').closest('div')!.querySelector('dd')!.textContent;
}

describe('BuyPaperDialog', () => {
  it('prices each card, leaves out Arena-only cards and updates the total live', async () => {
    render(<BuyPaperDialog deckName="Izzet Tempo" sections={sections} onClose={() => {}} returnFocus={null} />);

    expect(await screen.findByText('Cards')).toHaveTextContent('Cards (27 selected)');
    // 4 × 0.25 + 20 × 0.05 + 3 × 0.50
    expect(total()).toBe('$3.50');
    expect(screen.getByText('Arena only — not sold in paper')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Buy 2 Alchemy Only' })).toBeDisabled();
    expect(screen.getAllByText('$1.00')).toHaveLength(2); // 4 Opt and 20 Island
    expect(screen.getByText('$0.25 ea')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: 'Buy 4 Opt' }));
    expect(total()).toBe('$2.50');

    fireEvent.click(screen.getByRole('checkbox', { name: 'Sideboard' }));
    expect(total()).toBe('$1.00');
    expect(screen.queryByRole('checkbox', { name: 'Buy 3 Negate' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: /Skip basic lands/u }));
    expect(total()).toBe('$0.00');
    expect(screen.getByRole('button', { name: /Buy @/u })).toBeDisabled();
  });

  it('opens the chosen store with the selected cards', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    render(<BuyPaperDialog deckName="Izzet Tempo" sections={sections} onClose={() => {}} returnFocus={null} />);
    await screen.findByText('Cards');

    fireEvent.click(screen.getByRole('button', { name: /Store/u }));
    fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: 'Card Kingdom' }));
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
