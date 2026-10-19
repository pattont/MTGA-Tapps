import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronDown, CircleHelp, Funnel, ShoppingCart } from 'lucide-react';
import type { ImportSection } from '../deckFinderImport';
import { lookupPaperPrices, type PaperPriceMap } from '../cardPrices';
import {
  BOARD_LABELS, BOARD_ORDER, DEFAULT_BOARDS, applyStorePrices, buildCart, formatUsd, isBasicLand, isBuyable,
  paperDeckFromSections, rowSelected, storeLookupName, type BoardId,
} from '../paperDeck';
import { PAPER_VENDORS, affiliateActive, openVendorRequest, vendorById, type PaperVendor } from '../paperVendors';
import { fetchStorePrices, type StorePriceResult, type StorePriceSource } from '../storePrices';
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

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

/**
 * A dollar amount that counts from its old value to the new one. Screen
 * readers get the final value only.
 */
function AnimatedAmount({ value, busy = false }: { value: number; busy?: boolean }) {
  const [shown, setShown] = useState(value);
  const shownRef = useRef(value);
  useEffect(() => {
    const from = shownRef.current;
    if (from === value) return undefined;
    const start = performance.now();
    const duration = reducedMotion() ? 0 : 650;
    let frame = 0;
    const step = (now: number) => {
      const progress = duration ? Math.min(1, (now - start) / duration) : 1;
      const next = from + (value - from) * (1 - (1 - progress) ** 3);
      shownRef.current = progress === 1 ? value : next;
      setShown(shownRef.current);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return (
    <span className={busy ? 'buy-paper-amount buy-paper-amount-busy' : 'buy-paper-amount'}>
      <span aria-hidden="true">{formatUsd(shown)}</span>
      <span className="visually-hidden">{formatUsd(value)}</span>
    </span>
  );
}

type StoreState =
  | { status: 'downloading' }
  | { status: 'error'; error: string }
  | undefined;

const STORE_SOURCES: StorePriceSource[] = ['cardkingdom', 'manapool'];

/** "Buy on paper": pick a store, choose cards, see live prices, open the store's cart. */
export function BuyPaperDialog({ deckName, sections, onClose, returnFocus }: BuyPaperDialogProps) {
  const rows = useMemo(() => paperDeckFromSections(sections), [sections]);
  const presentBoards = useMemo(() => BOARD_ORDER.filter((board) => rows.some((row) => row.board === board)), [rows]);
  const [prefs, setPrefs] = useState(loadPrefs);
  const [boards, setBoards] = useState<Set<BoardId>>(() => new Set(DEFAULT_BOARDS));
  const [excluded, setExcluded] = useState<Set<string>>(() => new Set());
  const [scryfall, setScryfall] = useState<PaperPriceMap>(() => new Map());
  // The lookup reports its real count as soon as it starts.
  const [pending, setPending] = useState(() => new Set(rows.map((row) => row.name)).size);
  const [interrupted, setInterrupted] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [storeData, setStoreData] = useState<Record<string, StorePriceResult>>({});
  const [storeState, setStoreState] = useState<Partial<Record<StorePriceSource, StoreState>>>({});
  const [storeAttempt, setStoreAttempt] = useState(0);
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
  const names = useMemo(() => (namesKey ? namesKey.split('\n') : []), [namesKey]);
  useEffect(() => {
    const controller = new AbortController();
    void lookupPaperPrices(names, (map, progress) => {
      if (controller.signal.aborted) return;
      setScryfall(map);
      setPending(progress.pending);
      setInterrupted(progress.interrupted);
    }, controller.signal);
    return () => controller.abort();
  }, [names, attempt]);

  // Every store with its own price list loads when the dialog opens, so
  // Compare stores can show all the totals and switching is instant.
  useEffect(() => {
    const controller = new AbortController();
    const lookupNames = Array.from(new Set(names.map(storeLookupName)));
    for (const storeSource of STORE_SOURCES) {
      fetchStorePrices(storeSource, lookupNames, {
        signal: controller.signal,
        onLoading: () => setStoreState((current) => ({ ...current, [storeSource]: { status: 'downloading' } })),
      }).then((result) => {
        if (controller.signal.aborted) return;
        setStoreData((current) => ({ ...current, [storeSource]: result }));
        setStoreState((current) => ({ ...current, [storeSource]: undefined }));
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : String(error);
        setStoreState((current) => ({ ...current, [storeSource]: { status: 'error', error: message } }));
      });
    }
    return () => controller.abort();
  }, [names, storeAttempt]);

  const options = { boards, excluded, skipBasics: prefs.skipBasics };
  const pricesFor = (priceSource: PaperVendor['priceSource']): PaperPriceMap | null => {
    if (priceSource === 'tcgplayer') return scryfall;
    const result = storeData[priceSource];
    if (result) return applyStorePrices(names, scryfall, result.prices);
    return storeState[priceSource]?.status === 'error' ? scryfall : null;
  };

  const source = vendor.priceSource;
  const storeResult = source === 'tcgplayer' ? null : storeData[source] ?? null;
  const sourceState = source === 'tcgplayer' ? undefined : storeState[source];
  const storeError = sourceState?.status === 'error' ? sourceState.error : null;
  const storeDownloading = sourceState?.status === 'downloading';
  const storeLoading = source !== 'tcgplayer' && !storeResult && !storeError;
  const prices = pricesFor(source) ?? scryfall;
  const cart = buildCart(rows, prices, options);
  const setCodes = prefs.setCodes && vendor.supportsSetCodes;

  // Compare stores: the same selection priced at each store.
  const comparison = PAPER_VENDORS.map((entry) => {
    const map = pricesFor(entry.priceSource);
    const ownPrices = entry.priceSource === 'tcgplayer' ? entry.id === 'tcgplayer' : Boolean(storeData[entry.priceSource]);
    return { vendor: entry, total: map ? buildCart(rows, map, options).total : null, ownPrices };
  });
  const comparable = comparison.filter((entry) => entry.ownPrices && entry.total !== null && entry.total > 0);
  const lowest = pending === 0 && comparable.length > 1 && comparison.every((entry) => entry.total !== null)
    ? comparable.reduce((best, entry) => (entry.total! < best.total! ? entry : best)).vendor.id
    : null;

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
  let rowIndex = 0;

  let status: ReactNode;
  if (opened) status = opened;
  else if (pending > 0) status = `Finding the cheapest printings… ${pending} card${pending === 1 ? '' : 's'} left`;
  else if (storeDownloading) status = `Downloading ${vendor.name}’s price list. This happens once a day and takes a few seconds.`;
  else if (storeLoading) status = `Loading ${vendor.name} prices…`;
  else if (storeError) {
    status = <>
      Couldn’t load {vendor.name}’s prices, so these are TCGplayer estimates.{' '}
      <button type="button" className="buy-paper-retry" onClick={() => { setStoreState({}); setStoreAttempt((value) => value + 1); }}>Try again</button>
    </>;
  } else if (interrupted) {
    status = <>
      {Array.from(scryfall.values()).some(Boolean)
        ? 'Scryfall is busy, so some prices come from a default printing.'
        : 'Couldn’t reach Scryfall for prices. You can still buy; the store prices the cart.'}{' '}
      <button type="button" className="buy-paper-retry" onClick={() => { setInterrupted(false); setAttempt((value) => value + 1); }}>Try again</button>
    </>;
  } else if (storeResult) {
    status = `${vendor.name} prices${storeResult.asOf ? ` as of ${storeResult.asOf.slice(0, 10)}` : ''}, cheapest in-stock copy of each card.`;
  } else {
    status = 'TCGplayer market prices via Scryfall, cheapest printing of each card.';
  }

  return (
    <DeckModal title="Buy on Paper" busy={false} onClose={onClose} returnFocus={returnFocus} wide className="buy-paper-modal">
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

          <h4 id="buy-paper-compare-label">Compare stores</h4>
          <ul className="buy-paper-compare" aria-labelledby="buy-paper-compare-label">
            {comparison.map((entry) => (
              <li key={entry.vendor.id}>
                <button
                  type="button"
                  className={entry.vendor.id === vendor.id ? 'buy-paper-compare-current' : undefined}
                  aria-pressed={entry.vendor.id === vendor.id}
                  onClick={() => { updatePrefs({ vendor: entry.vendor.id }); setOpened(null); }}
                >
                  <VendorMark vendor={entry.vendor} />
                  <span className="buy-paper-compare-name">
                    {entry.vendor.name}
                    {lowest === entry.vendor.id ? <em className="buy-paper-tag buy-paper-tag-best">Lowest</em> : null}
                  </span>
                  <span className="buy-paper-compare-total">
                    {entry.total === null || pending > 0
                      ? <span className="buy-paper-skeleton" />
                      : <>
                        {entry.ownPrices ? null : <small title={`${entry.vendor.name} publishes no price list; this is the TCGplayer estimate.`}>est.</small>}
                        <AnimatedAmount value={entry.total} />
                      </>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="buy-paper-compare-note">Your selection at each store’s cheapest in-stock prices. StarCityGames and CoolStuffInc publish no price list, so they show the TCGplayer estimate.</p>
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

          <div className="buy-paper-list" aria-label="Cards to buy" aria-busy={storeLoading || pending > 0}>
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
                    const stagger = { '--buy-paper-i': Math.min(rowIndex++, 30) } as CSSProperties;
                    const where = printing
                      ? [printing.set_name ? `${printing.set_name} (${printing.set})` : printing.set,
                        printing.collector_number ? `#${printing.collector_number}` : null,
                        printing.finish && printing.finish !== 'nonfoil' ? printing.finish : null].filter(Boolean).join(' ')
                      : null;
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
                                : storeLoading ? <span className="buy-paper-skeleton buy-paper-skeleton-wide" style={stagger} />
                                  : <span key={`${source}:${where}`} className="buy-paper-fade-in" style={stagger}>
                                    {where ?? (lookingUp ? 'Finding printings…' : 'Printing unknown')}
                                    {printing?.in_stock === false ? <em className="buy-paper-tag buy-paper-tag-warn">Sold out</em> : null}
                                    {printing?.estimate ? <em className="buy-paper-tag">Not listed · TCGplayer est.</em> : null}
                                  </span>}
                              {info?.rebalanced && buyable && !storeLoading ? ` · paper original of Arena’s rebalanced ${row.name}` : ''}
                            </small>
                          </span>
                          <span className={`buy-paper-price${lookingUp ? ' buy-paper-price-pending' : ''}`}>
                            {!buyable ? '—' : storeLoading ? <span className="buy-paper-skeleton" style={stagger} />
                              : printing?.usd != null ? (
                                <span key={`${source}:${printing.usd}`} className="buy-paper-fade-in" style={stagger}>
                                  {formatUsd(printing.usd * row.quantity)}
                                  {row.quantity > 1 ? <small>{formatUsd(printing.usd)} ea</small> : null}
                                </span>
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
            <div><dt>Estimated price of cards</dt><dd><AnimatedAmount value={cart.total} busy={storeLoading} /></dd></div>
            {cart.outOfStockCount && !storeLoading ? (
              <div className="buy-paper-summary-note"><dt>Sold out at {vendor.name}</dt><dd>{cart.outOfStockCount}</dd></div>
            ) : null}
            {cart.estimateCount && !storeLoading ? (
              <div className="buy-paper-summary-note"><dt>Not listed at {vendor.name} (TCGplayer estimate)</dt><dd>{cart.estimateCount}</dd></div>
            ) : null}
            {cart.unavailableCount ? (
              <div className="buy-paper-summary-note"><dt>Arena-only cards left out</dt><dd>{cart.unavailableCount}</dd></div>
            ) : null}
            {cart.unpricedCount && !pending && !storeLoading ? (
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
                  title={source === 'tcgplayer'
                    ? 'Each card’s cheapest English paper printing at its TCGplayer market price, from Scryfall (updated daily). The store sets its own prices and stock, so the cart total will differ.'
                    : `Each card’s cheapest in-stock copy in ${vendor.name}’s published price list (refreshed daily), any condition. Cards ${vendor.name} doesn’t list use the TCGplayer estimate. The cart total may differ.`}
                ><CircleHelp aria-hidden="true" /></span>
              </dt>
              <dd><AnimatedAmount value={cart.total} busy={storeLoading} /></dd>
            </div>
          </dl>
        </div>
      </div>

      <div className="buy-paper-footer">
        <div className="buy-paper-footer-text">
          <p className="buy-paper-status" role="status">{status}</p>
          {affiliateActive(vendor) ? <p className="buy-paper-disclosure">Tapps Tracker may earn a commission from purchases through this link, at no cost to you.</p> : null}
        </div>
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
      className={`buy-paper-open ${className}`.trim()}
      disabled={disabled}
      title={disabled ? 'No deck list to buy' : 'Price this deck in paper and open it in a store’s cart'}
      onClick={(event) => onOpen(event.currentTarget)}
    >
      <ShoppingCart aria-hidden="true" />Buy on Paper
    </button>
  );
}

