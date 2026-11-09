import { useState } from 'react';
import { resetDatabase } from '../api';
import { Section } from './Section';

/** Where Settings' "Reset Settings" link goes. */
export const RESET_ROUTE = '#/reset';

const DELETED = [
  'Every game, match and session the tracker recorded, with their wins, losses and stats',
  'The decklists you played, opening hands, mulligans, draws and the cards each side showed',
  'Turn timings and game replays',
  'Your notes and tags on games',
  'Rank history',
  "Live Scoreboard's log of past games",
];

const KEPT = [
  "Deck Manager's saved decks, their revisions and collections",
  'Your Arena account and the decks in Arena. A reset never touches Arena.',
  'Your settings: Deck AI keys, overlay, Stream Kit links, startup and backup folder',
  'The last wildcard, gold and gem counts the tracker saw',
  'Backup files you made in Settings → Backup & restore',
];

export function ResetPage() {
  return (
    <>
      <Section
        id="reset-overview"
        title="Reset tracker data"
        description="Start your stats over from zero. Overview, Decks, Opponents, All Games, Replays and the Stream Kit records all start empty, and the next game you play is tracked as usual. You don't need to restart the app."
        collapsible={false}
      >
        <div className="reset-lists">
          <div className="reset-list reset-list-deleted">
            <h3>What gets deleted</h3>
            <ul>
              {DELETED.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div className="reset-list reset-list-kept">
            <h3>What stays</h3>
            <ul>
              {KEPT.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section id="reset-before" title="Before you reset" collapsible={false}>
        <ul className="reset-notes">
          <li>
            A copy of the whole database is saved next to it first, with <code>pre-reset</code> in
            its name. The page shows where once the reset is done.
          </li>
          <li>
            That copy can only be put back by replacing the database file by hand. To be able to
            undo from the app, make a backup first in{' '}
            <a href="#/settings">Settings → Backup &amp; restore</a>; restoring it brings
            everything back.
          </li>
          <li>
            Close MTG Arena first. The reset won't run while Arena is open, so no match is left half
            recorded.
          </li>
        </ul>
        <ResetPanel />
      </Section>
    </>
  );
}

type ResetState =
  | { status: 'idle' }
  | { status: 'working' }
  | { status: 'done'; backup: string }
  | { status: 'error'; message: string };

function ResetPanel() {
  const [modalOpen, setModalOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [state, setState] = useState<ResetState>({ status: 'idle' });
  const armed = confirmText === 'RESET';

  function openModal() {
    setConfirmText('');
    if (state.status === 'error') {
      setState({ status: 'idle' });
    }
    setModalOpen(true);
  }

  function closeModal() {
    if (state.status !== 'working') {
      setModalOpen(false);
      setConfirmText('');
    }
  }

  async function handleReset() {
    setState({ status: 'working' });
    try {
      const result = await resetDatabase(confirmText);
      setState({ status: 'done', backup: result.backup });
      setModalOpen(false);
      setConfirmText('');
    } catch (error: unknown) {
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : 'Reset failed',
      });
    }
  }

  return (
    <>
      <div className="danger-zone-panel">
        <p>Delete all tracked games and stats. Saved decks and settings stay.</p>
        <button className="danger-zone-button" type="button" onClick={openModal}>
          Reset tracker data…
        </button>
      </div>
      {state.status === 'done' ? (
        <p className="danger-zone-result" role="status">
          Reset done. Your stats start from zero. The old data was saved to:
          <br />
          <code>{state.backup}</code>
        </p>
      ) : null}
      {modalOpen ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeModal();
            }
          }}
        >
          <div
            aria-labelledby="reset-modal-title"
            aria-modal="true"
            className="modal danger-modal"
            role="dialog"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                closeModal();
              }
            }}
          >
            <h3 id="reset-modal-title">Reset tracker data?</h3>
            <p>
              This deletes <strong>every tracked game, match and session</strong>, with their
              stats, replays, notes and rank history. Deck Manager's saved decks and your settings
              stay. A copy of the database is saved first.
            </p>
            <label className="danger-modal-label" htmlFor="reset-confirm-input">
              Type <strong>RESET</strong> (all caps) to confirm:
            </label>
            <input
              autoFocus
              id="reset-confirm-input"
              placeholder="RESET"
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
            />
            {state.status === 'error' ? (
              <p className="danger-zone-error" role="alert">
                {state.message}
              </p>
            ) : null}
            <div className="modal-actions">
              <button
                className="modal-cancel"
                disabled={state.status === 'working'}
                type="button"
                onClick={closeModal}
              >
                Cancel
              </button>
              <button
                className="danger-zone-button"
                disabled={!armed || state.status === 'working'}
                type="button"
                onClick={() => void handleReset()}
              >
                {state.status === 'working' ? 'Resetting…' : 'Reset tracker data'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
