import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

/**
 * Native modal dialog shared by Deck Manager and Deck Finder. It closes only
 * with its close button or Esc, never from a click outside it: a stray click
 * on the page behind shouldn't throw away what you were looking at.
 */
export function DeckModal({ title, busy, onClose, returnFocus, headerActions, wide = false, className, children }: {
  title: string; busy: boolean; onClose: () => void; returnFocus: HTMLElement | null; headerActions?: ReactNode; wide?: boolean;
  /** Extra class on the dialog, for a modal with its own sizing. */
  className?: string;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  // Unique per dialog: Buy on Paper opens on top of the Deck Manager dialog.
  const titleId = `deck-manager-modal-title-${useId().replace(/:/gu, '')}`;
  useEffect(() => {
    const dialog = dialogRef.current;
    const opener = returnFocus ?? document.activeElement;
    const root = document.documentElement;
    const overflow = document.body.style.overflow;
    const gutter = root.style.scrollbarGutter;
    // Hiding the page scrollbar would widen the layout and shift every tile;
    // keep its space reserved while the page is locked.
    if (window.innerWidth > root.clientWidth) root.style.scrollbarGutter = 'stable';
    document.body.style.overflow = 'hidden';
    dialog?.showModal();
    return () => {
      dialog?.close();
      document.body.style.overflow = overflow;
      root.style.scrollbarGutter = gutter;
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, [returnFocus]);

  return (
    <dialog
      ref={dialogRef}
      className={['deck-manager-modal', wide ? 'deck-manager-modal-wide' : '', className ?? ''].filter(Boolean).join(' ')}
      aria-modal="true"
      aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}
    >
      <div className="deck-manager-modal-heading">
        <h3 id={titleId} tabIndex={-1} autoFocus>{title}</h3>
        <div className="deck-manager-heading-actions">
          {headerActions}
          <button type="button" className="deck-manager-close" aria-label="Close dialog" disabled={busy} onClick={onClose}>
            <X size={20} />
          </button>
        </div>
      </div>
      {children}
    </dialog>
  );
}
