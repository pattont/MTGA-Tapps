import { RefreshCw, X } from 'lucide-react';
import type { NativeDeckAction, NativeDeckJob, NativeDeckStatus } from '../deckManagerApi';
import { formatDateTime } from '../format';
import { loadLabel } from '../deckManagerLabels';
import { DeckTransferProgress } from './DeckTransferProgress';

type Tone = 'ok' | 'warn' | 'idle' | 'busy';

const RUNNING: Record<NativeDeckAction, string> = {
  connect: 'Reading your Arena decks…',
  backup: 'Backing up Arena decks…',
  store: 'Moving decks to your collection…',
  restore: 'Restoring decks to Arena…',
  add: 'Adding the deck to Arena…',
  reconcile: 'Checking the interrupted transfer…',
};

function arenaState(native: NativeDeckStatus | null, job: string | null): { tone: Tone; title: string; detail: string } {
  if (job) return { tone: 'busy', title: job, detail: 'Keep Arena open on the Decks screen until this finishes.' };
  if (!native) return { tone: 'idle', title: 'Checking Arena…', detail: '' };
  if (!native.available) return { tone: 'idle', title: 'Direct Arena transfers aren’t available here', detail: `${native.message} You can still save, organize and copy decks.` };
  const loaded = native.connected && native.refreshed_at ? ` The Arena list below is from ${formatDateTime(native.refreshed_at)}.` : '';
  if (native.pending_transfers?.length) {
    return { tone: 'warn', title: 'A transfer was interrupted', detail: 'Check it before doing anything else. Checking only reads Arena and never repeats a change.' };
  }
  if (native.in_game) {
    return { tone: 'warn', title: 'You’re in a game', detail: `Deck Manager won’t touch Arena until the game ends.${loaded}` };
  }
  if (!native.connected) {
    return { tone: 'idle', title: 'Arena decks not loaded yet', detail: `Open Arena to its Decks screen (not in a match), then click ${loadLabel(native)}.` };
  }
  const count = `${native.decks.length} deck${native.decks.length === 1 ? '' : 's'} in Arena`;
  const slots = native.limit_reached ? 'deck slots full' : native.limit ? `limit ${native.limit}` : '';
  if (!native.deck_screen_open) {
    return { tone: 'warn', title: 'Arena wasn’t on the Decks screen', detail: `Open Decks in Arena, then click ${loadLabel(native)} before backing up or moving decks.${loaded}` };
  }
  return {
    tone: 'ok',
    title: `Arena decks loaded ${formatDateTime(native.refreshed_at ?? '')}`,
    detail: `${[count, slots].filter(Boolean).join(' · ')}. Changed something in Arena? Click ${loadLabel(native)}.`,
  };
}

/**
 * The page's single status panel: what Deck Manager last learned from Arena,
 * what is running, and the result of the last action.
 */
export function DeckManagerStatus({ native, jobAction, jobDetail, progress, error, notice, showMessages, busy, onReconcile, onDismiss }: {
  native: NativeDeckStatus | null;
  jobAction: NativeDeckAction | null;
  jobDetail: string;
  progress: NativeDeckJob['progress'];
  error: string;
  notice: string;
  showMessages: boolean;
  busy: boolean;
  onReconcile: () => void;
  onDismiss: () => void;
}) {
  const running = jobDetail ? RUNNING[jobAction ?? 'connect'] : null;
  const state = arenaState(native, running);
  const message = showMessages ? error || notice : '';
  return (
    <section className={`deck-manager-status deck-manager-status-${state.tone}`} aria-label="Arena status">
      <div className="deck-manager-status-main">
        <span className="deck-manager-status-dot" aria-hidden="true" />
        <div className="deck-manager-status-copy">
          <strong>{state.title}</strong>
          {state.detail ? <span>{state.detail}</span> : null}
        </div>
        {!running && native?.available && native.pending_transfers?.length
          ? <button className="deck-manager-add" disabled={busy || native.in_game} onClick={onReconcile}><RefreshCw size={16} /> Reconcile transfers</button>
          : null}
      </div>
      {running && showMessages ? <DeckTransferProgress detail={jobDetail} progress={progress} /> : null}
      {message ? (
        <div className={error ? 'deck-manager-status-message deck-manager-error' : 'deck-manager-status-message deck-manager-notice'} role={error ? 'alert' : 'status'}>
          <span>{message}</span>
          <button type="button" className="deck-manager-status-dismiss" aria-label="Dismiss message" onClick={onDismiss}><X size={16} /></button>
        </div>
      ) : null}
    </section>
  );
}
