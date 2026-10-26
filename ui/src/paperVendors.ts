/**
 * Stores the Buy on Paper dialog can hand a deck to. Each one turns the cart
 * into what its bulk-entry page accepts, and the browser opens it in a new
 * tab. Nothing here talks to a store.
 *
 * Formats follow what EDHREC and Cube Cobra send today (see
 * docs/BUY_ON_PAPER.md). StarCityGames and CoolStuffInc publish no prices and
 * document no way to prefill their deck builders, so the dialog lists them as
 * coming soon and they can't be chosen. Their copy-and-open handoff stays here
 * for when a way to price them turns up.
 *
 * Fill in AFFILIATE once a store approves an account (Mana Pool has): an
 * empty value sends a plain link, and the dialog only shows its commission
 * disclosure for a store whose code is set.
 */

import type { CartLine } from './paperDeck';
import type { StorePriceSource } from './storePrices';

export type VendorId = 'tcgplayer' | 'cardkingdom' | 'manapool' | 'starcitygames' | 'coolstuffinc';

export const AFFILIATE = {
  /**
   * Impact tracking link from the TCGplayer affiliate dashboard, without a
   * query, e.g. "https://partner.tcgplayer.com/c/<publisher>/1830156/21018".
   * The Mass Entry URL is passed to it as `u`.
   */
  tcgplayer: '',
  /** Card Kingdom partner code (their in-house program), sent as `partner`. */
  cardkingdom: '',
  /** Mana Pool referral code (affiliates.manapool.com), sent as `ref`. */
  manapool: 'tappstracker',
  /** No affiliate programs found for these two yet. */
  starcitygames: '',
  coolstuffinc: '',
} satisfies Record<VendorId, string>;

/** Shown to the store as the traffic source alongside an affiliate code. */
const SOURCE = 'tappstracker';

export type VendorRequest =
  | { kind: 'link'; url: string }
  | { kind: 'copy'; url: string; text: string };

export interface VendorOptions {
  setCodes: boolean;
}

export interface PaperVendor {
  id: VendorId;
  name: string;
  icon: string;
  /**
   * Where card prices come from: the store's own list via the dashboard,
   * Scryfall (TCGplayer market prices), or null for a store that publishes
   * no prices. Never another store's prices: they'd be wrong for this one.
   */
  priceSource: StorePriceSource | 'tcgplayer' | null;
  /** One line under the store list saying what happens on Buy. */
  note: string;
  /**
   * Listed but not yet usable: no way to price the cart. The dialog shows
   * "Coming soon" and the store can't be chosen.
   */
  comingSoon?: boolean;
  supportsSetCodes: boolean;
  buildRequest: (lines: CartLine[], options: VendorOptions) => VendorRequest;
}

/** Stores take the front face of a double-faced or split card. */
function storeName(name: string): string {
  return name.split(' // ')[0].trim();
}

function plainLines(lines: CartLine[]): string[] {
  return lines.map((line) => `${line.quantity} ${storeName(line.name)}`);
}

function withQuery(base: string, params: Record<string, string>): string {
  const url = new URL(base);
  for (const [key, value] of Object.entries(params)) {
    if (value) url.searchParams.set(key, value);
  }
  return url.toString();
}

/**
 * UTF-8 text as URL-safe base64 without padding (`-` and `_` for `+` and `/`),
 * which is what Mana Pool's affiliate instructions say add-deck expects.
 */
function base64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/gu, '-').replace(/\//gu, '_').replace(/=+$/u, '');
}

const ICON_BASE = `${import.meta.env.BASE_URL}stores/`;

/** Alphabetical, as the dialog lists them. */
export const PAPER_VENDORS: PaperVendor[] = [
  {
    id: 'cardkingdom',
    name: 'Card Kingdom',
    icon: `${ICON_BASE}cardkingdom.png`,
    priceSource: 'cardkingdom',
    note: 'Opens Card Kingdom’s deck builder with your list filled in.',
    supportsSetCodes: false,
    buildRequest(lines) {
      const tracked: Record<string, string> = AFFILIATE.cardkingdom
        ? { partner: AFFILIATE.cardkingdom, utm_source: SOURCE, utm_medium: 'affiliate', utm_campaign: SOURCE }
        : {};
      return {
        kind: 'link',
        url: withQuery('https://www.cardkingdom.com/builder', { ...tracked, c: plainLines(lines).join('\n') }),
      };
    },
  },
  {
    id: 'coolstuffinc',
    comingSoon: true,
    name: 'CoolStuffInc',
    icon: `${ICON_BASE}coolstuffinc.png`,
    priceSource: null,
    note: 'Copies your list and opens the CoolStuffInc deck builder. Paste it there and choose Build It!',
    supportsSetCodes: false,
    buildRequest(lines) {
      return { kind: 'copy', url: 'https://www.coolstuffinc.com/main_deckBuilder.php', text: plainLines(lines).join('\n') };
    },
  },
  {
    id: 'manapool',
    name: 'Mana Pool',
    icon: `${ICON_BASE}manapool.png`,
    priceSource: 'manapool',
    note: 'Opens Mana Pool’s deck import with your list filled in.',
    supportsSetCodes: false,
    buildRequest(lines) {
      return {
        kind: 'link',
        url: withQuery('https://manapool.com/add-deck', {
          deck: base64Url(plainLines(lines).join('\n')),
          ref: AFFILIATE.manapool,
        }),
      };
    },
  },
  {
    id: 'starcitygames',
    comingSoon: true,
    name: 'StarCityGames',
    icon: `${ICON_BASE}starcitygames.png`,
    priceSource: null,
    note: 'Copies your list and opens the StarCityGames deck builder. Paste it there and choose Get My Deck!',
    supportsSetCodes: false,
    buildRequest(lines) {
      return { kind: 'copy', url: 'https://starcitygames.com/shop/deck-builder/', text: plainLines(lines).join('\n') };
    },
  },
  {
    id: 'tcgplayer',
    name: 'TCGplayer',
    icon: `${ICON_BASE}tcgplayer.ico`,
    priceSource: 'tcgplayer',
    note: 'Opens TCGplayer Mass Entry with your list, where you add it to the cart.',
    supportsSetCodes: true,
    buildRequest(lines, { setCodes }) {
      const entries = lines.map((line) => {
        const base = `${line.quantity} ${storeName(line.name)}`;
        return setCodes && line.set ? `${base} [${line.set}]${line.collector_number ? ` ${line.collector_number}` : ''}` : base;
      });
      const massEntry = withQuery('https://store.tcgplayer.com/massentry', { c: entries.join('||') });
      return {
        kind: 'link',
        url: AFFILIATE.tcgplayer ? withQuery(AFFILIATE.tcgplayer, { subId1: SOURCE, u: massEntry }) : massEntry,
      };
    },
  },
];

/** The store a new user starts on. */
export const DEFAULT_VENDOR_ID: VendorId = 'tcgplayer';

export function vendorById(id: string): PaperVendor | undefined {
  return PAPER_VENDORS.find((vendor) => vendor.id === id);
}

/** A store the dialog can switch to: listed and not coming soon. */
export function selectableVendor(id: string): PaperVendor | undefined {
  const vendor = vendorById(id);
  return vendor && !vendor.comingSoon ? vendor : undefined;
}

export function affiliateActive(vendor: PaperVendor): boolean {
  return Boolean(AFFILIATE[vendor.id]);
}

/**
 * Open the store in a new tab, copying the list first when the store can't
 * take it in the link. Resolves to whether a copy was needed and worked.
 */
export async function openVendorRequest(request: VendorRequest): Promise<{ copied: boolean | null }> {
  let copied: boolean | null = null;
  if (request.kind === 'copy') {
    // Copy before opening: the clipboard needs this page focused, and the
    // click still counts as the user's action for window.open afterwards.
    try {
      await navigator.clipboard.writeText(request.text);
      copied = true;
    } catch {
      copied = false;
    }
  }
  window.open(request.url, '_blank', 'noopener,noreferrer');
  return { copied };
}
