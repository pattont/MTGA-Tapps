import type { NativeDeckStatus } from './deckManagerApi';

/** The button label for reading Arena; the status text refers to it by name. */
export function loadLabel(native: NativeDeckStatus | null) {
  return native?.connected ? 'Rescan Arena' : 'Load Arena decks';
}

/**
 * The notice after loading or rescanning Arena. The status banner's own title
 * ("Arena decks loaded …") already says it, so the banner shows it without a
 * second message box.
 */
export const ARENA_LOADED_NOTICE = 'Arena decks refreshed.';
