import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronDown, CircleHelp, Funnel, ShoppingCart } from 'lucide-react';
import type { ImportSection } from '../deckFinderImport';
import { lookupPaperPrices, type PaperPriceMap } from '../cardPrices';
import {
  BOARD_LABELS, BOARD_ORDER, DEFAULT_BOARDS, buildCart, formatUsd, isBasicLand, isBuyable,
  paperDeckFromSections, rowSelected, type BoardId,
} from '../paperDeck';
import { PAPER_VENDORS, affiliateActive, openVendorRequest, vendorById, type PaperVendor } from '../paperVendors';
import { DeckModal } from './DeckModal';

const PREFS_KEY = 'mtga-tracker-buy-paper-v1';

interface Prefs {
  vendor: string;
  setCodes: boolean;
  skipBasics: boolean;
}

function loadPrefs(): Prefs {
  const fallback: Prefs = { vendor: PAPER_VENDORS[0].id, setCodes: false, skipBasics: false };
  try {
    const parsed = JSON.parse(localStorage.getItem(PREFS_KEY) ?? 'null') as Partial<Prefs> | null;
    if (!parsed) return fallback;
    return {
      vendor: vendorById(parsed.vendor ?? '')?.id ?? fallback.vendor,
      setCodes: Boolean(parsed.setCodes),
      skipBasics: Boolean(parsed.skipBasics),
    };
  } catch {
    return fallback;
  }
}

function savePrefs(prefs: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Preferences are a convenience only.
  }
}

function VendorMark({ vendor }: { vendor: PaperVendor }) {
  return <img className="buy-paper-vendor-icon" src={vendor.icon} alt="" width={20} height={20} />;
}

/** Store picker styled like a select, with each store's icon in the list. */
function VendorPicker({ value, onChange }: { value: PaperVendor; onChange: (vendor: PaperVendor) => void }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!open) return;
    listRef.current?.focus();
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  function openList() {
    setActive(Math.max(0, PAPER_VENDORS.findIndex((vendor) => vendor.id === value.id)));
    setOpen(true);
  }

  function choose(index: number) {
    onChange(PAPER_VENDORS[index]);
    setOpen(false);
    rootRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }

  function onListKey(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((index) => Math.min(index + 1, PAPER_VENDORS.length - 1)); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((index) => Math.max(index - 1, 0)); }
    else if (event.key === 'Home') { event.preventDefault(); setActive(0); }
    else if (event.key === 'End') { event.preventDefault(); setActive(PAPER_VENDORS.length - 1); }
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(active); }
    else if (event.key === 'Escape' || event.key === 'Tab') {
      // Escape closes the list, not the whole dialog.
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); }
      setOpen(false);
      rootRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    }
  }

  return (
    <div className="buy-paper-picker" ref={rootRef}>
      <button
        type="button"
        className="buy-paper-picker-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby="buy-paper-store-label buy-paper-store-value"
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); openList(); }
        }}
      >
        <VendorMark vendor={value} />
        <span id="buy-paper-store-value">{value.name}</span>
        <ChevronDown aria-hidden="true" className="buy-paper-picker-chevron" />
      </button>
      {open ? (
        <ul
          ref={listRef}
          className="buy-paper-picker-list"
          role="listbox"
          tabIndex={-1}
          aria-labelledby="buy-paper-store-label"
          aria-activedescendant={`buy-paper-store-${PAPER_VENDORS[active].id}`}
          onKeyDown={onListKey}
        >
          {PAPER_VENDORS.map((vendor, index) => (
            <li
              key={vendor.id}
              id={`buy-paper-store-${vendor.id}`}
              role="option"
              aria-selected={vendor.id === value.id}
              className={index === active ? 'buy-paper-picker-option-active' : undefined}
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(index)}
            >
              <VendorMark vendor={vendor} />
              {vendor.name}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export interface BuyPaperDialogProps {
  deckName: string;
  sections: ImportSection[];
  onClose: () => void;
  returnFocus: HTMLElement | null;
}

/** "Buy on paper": pick a store, choose cards, see live prices, open the store's cart. */
export function BuyPaperDialog({ deckName, sections, onClose, returnFocus }: BuyPaperDialogProps) {
  const rows = useMemo(() => paperDeckFromSections(sections), [sections]);
  const presentBoards = useMemo(() => BOARD_ORDER.filter((board) => rows.some((row) => row.board === board)), [rows]);
  const [prefs, setPrefs] = useState(loadPrefs);
  const [boards, setBoards] = useState<Set<BoardId>>(() => new Set(DEFAULT_BOARDS));
  const [excluded, setExcluded] = useState<Set<string>>(() => new Set());
  const [prices, setPrices] = useState<PaperPriceMap>(() => new Map());
  // The lookup reports its real count as soon as it starts.
  const [pending, setPending] = useState(() => new Set(rows.map((row) => row.name)).size);
  const [interrupted, setInterrupted] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [opened, setOpened] = useState<string | null>(null);

  const vendor = vendorById(prefs.vendor) ?? PAPER_VENDORS[0];
  const updatePrefs = (patch: Partial<Prefs>) => setPrefs((current) => {
    const next = { ...current, ...patch };
    savePrefs(next);
    return next;
  });

  // Keyed by the names themselves: callers may pass a fresh sections array on
  // every render, and that must not restart the price lookup.
  const namesKey = Array.from(new Set(rows.map((row) => row.name))).join('\n');
  useEffect(() => {
    const names = namesKey ? namesKey.split('\n') : [];
    const controller = new AbortController();
    void lookupPaperPrices(names, (map, progress) => {
      if (controller.signal.aborted) return;
      setPrices(map);
      setPending(progress.pending);
      setInterrupted(progress.interrupted);
    }, controller.signal);
    return () => controller.abort();
  }, [namesKey, attempt]);

  const options = { boards, excluded, skipBasics: prefs.skipBasics };
  const cart = buildCart(rows, prices, options);
  const setCodes = prefs.setCodes && vendor.supportsSetCodes;

  function toggleRow(key: string) {
    setExcluded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleBoard(board: BoardId) {
    setBoards((current) => {
      const next = new Set(current);
      if (next.has(board)) next.delete(board);
      else next.add(board);
      return next;
    });
  }

  async function buy() {
    const { copied } = await openVendorRequest(vendor.buildRequest(cart.lines, { setCodes }));
    setOpened(copied === null
      ? `Opened ${vendor.name} in a new tab. Review the cart there before checking out.`
      : copied
        ? `Copied your list and opened ${vendor.name}. Paste the list into its deck builder.`
        : `Opened ${vendor.name}, but the list couldn’t be copied. Use your deck’s Arena export instead.`);
  }

  const shownBoards = presentBoards.filter((board) => boards.has(board));

  return (
    <DeckModal title="Buy on Paper" busy={false} onClose={onClose} returnFocus={returnFocus} wide>
      <div className="buy-paper">
        <div className="buy-paper-options">
          <p className="buy-paper-deck-name">{deckName}</p>
          <h4 id="buy-paper-store-label">Store</h4>
          <VendorPicker value={vendor} onChange={(next) => { updatePrefs({ vendor: next.id }); setOpened(null); }} />
          <p className="buy-paper-store-note">{vendor.note}</p>

          <h4>Options</h4>
          <label className="buy-paper-check">
            <input
              type="checkbox"
              checked={setCodes}
              disabled={!vendor.supportsSetCodes}
              onChange={(event) => updatePrefs({ setCodes: event.target.checked })}
            />
            <span>
              Include set codes (when applicable)
              <small>{vendor.supportsSetCodes
                ? 'Asks for the printings priced here. Off lets the store pick any printing.'
                : `${vendor.name} picks the printing.`}</small>
            </span>
          </label>
          <label className="buy-paper-check">
            <input type="checkbox" checked={prefs.skipBasics} onChange={(event) => updatePrefs({ skipBasics: event.target.checked })} />
            <span>Skip basic lands<small>Leave out Plains, Island, Swamp, Mountain, Forest and Wastes.</small></span>
          </label>
        </div>

        <div className="buy-paper-cards">
          <div className="buy-paper-cards-heading">
            <h4>Cards <span>({cart.cardCount} selected)</span></h4>
            {presentBoards.length > 1 ? (
              <details className="buy-paper-boards">
                <summary><Funnel aria-hidden="true" />Boards</summary>
                <div className="buy-paper-boards-menu">
                  {presentBoards.map((board) => (
                    <label key={board} className="buy-paper-check">
                      <input type="checkbox" checked={boards.has(board)} onChange={() => toggleBoard(board)} />
                      <span>{BOARD_LABELS[board]}</span>
                    </label>
                  ))}
                </div>
              </details>
            ) : null}
          </div>

          <div className="buy-paper-list" aria-label="Cards to buy">
            {shownBoards.length ? shownBoards.map((board) => (
              <div key={board} className="buy-paper-board">
                <h5>{BOARD_LABELS[board]}</h5>
                <ul>
                  {rows.filter((row) => row.board === board).map((row) => {
                    const info = prices.get(row.name) ?? null;
                    const buyable = isBuyable(info);
                    const selected = buyable && rowSelected(row, options);
                    const printing = info?.printing;
                    const lookingUp = pending > 0 && (!info || !info.cheapest);
                    const basicSkipped = prefs.skipBasics && isBasicLand(row.name);
                    return (
                      <li key={row.key} className={selected ? undefined : 'buy-paper-row-off'}>
                        <label className="buy-paper-row">
                          <input
                            type="checkbox"
                            className="buy-paper-row-check"
                            checked={selected}
                            disabled={!buyable || basicSkipped}
                            onChange={() => toggleRow(row.key)}
                            aria-label={`Buy ${row.quantity} ${row.name}`}
                          />
                          <span className="buy-paper-qty" aria-hidden="true">{row.quantity}</span>
                          <span className="buy-paper-card">
                            <strong>{info?.rebalanced && info.name ? info.name : row.name}</strong>
                            <small>
                              {!buyable
                                ? info?.status === 'not_found' ? 'No paper card found' : 'Arena only — not sold in paper'
                                : printing
                                  ? `${printing.set_name} (${printing.set}) #${printing.collector_number}${printing.finish && printing.finish !== 'nonfoil' ? ` · ${printing.finish}` : ''}`
                                  : lookingUp ? 'Finding printings…' : 'Printing unknown'}
                              {info?.rebalanced && buyable ? ` · paper original of Arena’s rebalanced ${row.name}` : ''}
                            </small>
                          </span>
                          <span className={`buy-paper-price${lookingUp ? ' buy-paper-price-pending' : ''}`}>
                            {!buyable ? '—' : printing?.usd != null ? (
                              <>
                                {formatUsd(printing.usd * row.quantity)}
                                {row.quantity > 1 ? <small>{formatUsd(printing.usd)} ea</small> : null}
                              </>
                            ) : lookingUp ? '…' : '—'}
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )) : <p className="empty-state">Choose at least one board.</p>}
          </div>

          <dl className="buy-paper-summary">
            <div><dt>Estimated price of cards</dt><dd>{formatUsd(cart.total)}</dd></div>
            {cart.unavailableCount ? (
              <div className="buy-paper-summary-note"><dt>Arena-only cards left out</dt><dd>{cart.unavailableCount}</dd></div>
            ) : null}
            {cart.unpricedCount && !pending ? (
              <div className="buy-paper-summary-note"><dt>Cards without a listed price</dt><dd>{cart.unpricedCount}</dd></div>
            ) : null}
            <div className="buy-paper-total">
              <dt>
                Estimated Total
                <span
                  className="buy-paper-help"
                  tabIndex={0}
                  role="img"
                  aria-label="About this estimate"
                  title="Each card's cheapest English paper printing at its TCGplayer market price, from Scryfall (updated daily). The store sets its own prices and stock, so the cart total will differ."
                ><CircleHelp aria-hidden="true" /></span>
              </dt>
              <dd aria-live="polite">{formatUsd(cart.total)}</dd>
            </div>
          </dl>
          <p className="buy-paper-status" role="status">
            {pending > 0
              ? `Finding the cheapest printings… ${pending} card${pending === 1 ? '' : 's'} left`
              : opened
                ? opened
                : interrupted
                  ? <>
                    {Array.from(prices.values()).some(Boolean)
                      ? 'Scryfall is busy, so some prices come from a default printing.'
                      : 'Couldn’t reach Scryfall for prices. You can still buy; the store prices the cart.'}
                    {' '}
                    <button type="button" className="buy-paper-retry" onClick={() => { setInterrupted(false); setAttempt((value) => value + 1); }}>Try again</button>
                  </>
                  : ''}
          </p>
        </div>
      </div>

      <div className="buy-paper-footer">
        {affiliateActive(vendor) ? <p className="buy-paper-disclosure">Tapps Tracker may earn a commission from purchases through this link, at no cost to you.</p> : null}
        <button type="button" className="deck-neutral-button" onClick={onClose}>Cancel</button>
        <button type="button" className="buy-paper-buy" disabled={!cart.lines.length} onClick={() => void buy()}>
          <VendorMark vendor={vendor} />Buy @ {vendor.name}
        </button>
      </div>
    </DeckModal>
  );
}

/** The button the three deck screens show beside their Arena export. */
export function BuyPaperButton({ disabled, onOpen, className = '' }: {
  disabled?: boolean; onOpen: (opener: HTMLElement) => void; className?: string;
}) {
  return (
    <button
      type="button"
      className={`deck-neutral-button buy-paper-open ${className}`.trim()}
      disabled={disabled}
      title={disabled ? 'No deck list to buy' : 'Price this deck in paper and open it in a store’s cart'}
      onClick={(event) => onOpen(event.currentTarget)}
    >
      <ShoppingCart aria-hidden="true" />Buy on Paper
    </button>
  );
}
