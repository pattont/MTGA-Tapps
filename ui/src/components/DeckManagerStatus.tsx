import { RefreshCw, X } from 'lucide-react';
import type { NativeDeckAction, NativeDeckJob, NativeDeckStatus } from '../deckManagerApi';
import { formatDateTime } from '../format';
import { ARENA_LOADED_NOTICE, loadLabel } from '../deckManagerLabels';
import { DeckTransferProgress } from './DeckTransferProgress';

type Tone = 'ok' | 'warn' | 'idle' | 'busy';

const RUNNING: Record<NativeDeckAction, string> = {
  connect: 'Reading your Arena decks…',
  backup: 'Backing up Arena decks…',
  store: 'Moving decks to your collection…',
  restore: 'Restoring decks to Arena…',
  add: 'Adding the deck to Arena…',
  reconcile: 'Checking the interrupted transfer…',
  favorite: 'Updating Arena’s favorites…',
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

function chipLabel(native: NativeDeckStatus | null, busy: boolean) {
  if (busy) return 'Working with Arena…';
  if (!native) return 'Checking Arena…';
  if (!native.available) return 'Arena not connected';
  if (native.pending_transfers?.length) return 'Transfer interrupted';
  if (native.in_game) return 'In a game';
  if (!native.connected) return 'Arena not loaded';
  if (!native.deck_screen_open) return 'Arena not on Decks';
  const count = native.limit ? `${native.decks.length}/${native.limit}` : `${native.decks.length} decks`;
  const time = native.refreshed_at
    ? ` · ${new Date(native.refreshed_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}` : '';
  return `Arena ${count}${native.limit_reached ? ' full' : ''}${time}`;
}

/** One-line Arena summary for the tab row; the full explanation is its tooltip. */
export function ArenaStatusChip({ native, running }: { native: NativeDeckStatus | null; running: boolean }) {
  // Not loaded yet: the green Load Arena decks button beside it says it all.
  if (!running && native?.available && !native.connected && !native.in_game && !native.pending_transfers?.length) return null;
  const state = arenaState(native, running ? 'Working with Arena…' : null);
  const tone = state.tone === 'ok' && native?.limit_reached ? 'warn' : state.tone;
  return (
    <span className={`deck-manager-chip deck-manager-status-${tone}`} title={[state.title, state.detail].filter(Boolean).join('. ')}>
      <span className="deck-manager-status-dot" aria-hidden="true" />
      {chipLabel(native, running)}
    </span>
  );
}

/**
 * The page's status banner: shown only when something needs attention (a
 * warning, a running job, or the result of the last action).
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
  if (state.tone !== 'warn' && state.tone !== 'busy' && !message) return null;
  // A result is the banner's own headline, never a second box under it. After a
  // load or rescan the usual title already says it, so its text isn't repeated.
  const result = !error && message ? message : '';
  const headline = result && result !== ARENA_LOADED_NOTICE && (state.tone === 'ok' || state.tone === 'idle');
  const tone = headline ? 'ok' : state.tone;
  const title = headline ? result : state.title;
  // Arena's summary still fits under a result; "not loaded yet" advice doesn't.
  const detail = headline && state.tone === 'idle' ? '' : state.detail;
  // While a warning or a job holds the headline, the result is a plain line below it.
  const note = result && !headline && result !== ARENA_LOADED_NOTICE ? result : '';
  const dismiss = <button type="button" className="deck-manager-status-dismiss" aria-label="Dismiss message" onClick={onDismiss}><X size={16} /></button>;
  return (
    <section className={`deck-manager-status deck-manager-status-${tone}`} aria-label="Arena status">
      <div className="deck-manager-status-main">
        <span className="deck-manager-status-dot" aria-hidden="true" />
        <div className="deck-manager-status-copy" role={headline ? 'status' : undefined}>
          <strong>{title}</strong>
          {detail ? <span>{detail}</span> : null}
        </div>
        {!running && native?.available && native.pending_transfers?.length
          ? <button className="deck-manager-add" disabled={busy || native.in_game} onClick={onReconcile}><RefreshCw size={16} /> Reconcile transfers</button>
          : null}
        {result && !note ? dismiss : null}
      </div>
      {running && showMessages ? <DeckTransferProgress detail={jobDetail} progress={progress} showDetail={false} /> : null}
      {note ? (
        <div className="deck-manager-status-message deck-manager-status-note" role="status">
          <span>{note}</span>
          {dismiss}
        </div>
      ) : null}
      {error ? (
        <div className="deck-manager-status-message deck-manager-error" role="alert">
          <span>{error}</span>
          {dismiss}
        </div>
      ) : null}
    </section>
  );
}
