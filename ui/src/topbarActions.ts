import { createContext } from 'react';

/**
 * DOM node inside the topbar (next to the card search) where pages portal
 * their own actions — e.g. the deck page's Copy Arena Deck button. Provided
 * by AppShell via a ref callback; null until the topbar has mounted.
 */
export const TopbarActionsContext = createContext<HTMLElement | null>(null);
