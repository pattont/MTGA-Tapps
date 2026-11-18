import { useState } from 'react';
import { restoreDefaultSettings } from '../api';

// What Restore defaults changes, and what it leaves alone. The backend's
// settings_api._restore_defaults is the authority; keep these in step.
const RESTORED = [
  'Startup: no start at sign-in, open the dashboard on launch',
  'Updates: check and download automatically, install when you choose',
  'Saved game modes: Direct Challenge on, the rest off',
  'In-game overlay and Buy on Paper on',
  'Deck AI off',
];

const KEPT = [
  'Deck AI provider, API keys and models',
  'Deck Finder creators',
  'Stream Kit links and choices',
  'Backup folder and backup files',
  'Your games, stats and Deck Manager decks',
];

type RestoreState =
  | { status: 'idle' }
  | { status: 'working' }
  | { status: 'done'; errors: string[] }
  | { status: 'error'; message: string };

/** The Restore defaults card at the foot of Settings, with its confirmation. */
export function RestoreDefaults({ onRestored }: { onRestored: () => void }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<RestoreState>({ status: 'idle' });
  const working = state.status === 'working';

  function close() {
    if (!working) setOpen(false);
  }

  async function restore() {
    setState({ status: 'working' });
    try {
      const result = await restoreDefaultSettings();
      setState({ status: 'done', errors: result.errors });
      setOpen(false);
      onRestored();
    } catch (exc: unknown) {
      setState({ status: 'error', message: exc instanceof Error ? exc.message : 'Defaults could not be restored' });
    }
  }

  return (
    <>
      <div className="restore-defaults-panel">
        <p>Put the settings on this page back the way the app came. Your API keys, creators and backups stay.</p>
        <button
          className="restore-defaults-button"
          type="button"
          onClick={() => {
            setState({ status: 'idle' });
            setOpen(true);
          }}
        >
          Restore defaults…
        </button>
      </div>
      {state.status === 'done' ? (
        state.errors.length ? (
          <div className="restore-defaults-result restore-defaults-partial" role="alert">
            <p>Defaults restored, except:</p>
            <ul>
              {state.errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="restore-defaults-result" role="status">
            Defaults restored.
          </p>
        )
      ) : null}
      {open ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) close();
          }}
        >
          <div
            aria-labelledby="restore-defaults-title"
            aria-modal="true"
            className="modal restore-defaults-modal"
            role="dialog"
            onKeyDown={(event) => {
              if (event.key === 'Escape') close();
            }}
          >
            <h3 id="restore-defaults-title">Restore default settings?</h3>
            <div className="restore-defaults-lists">
              <div className="reset-list restore-defaults-changed">
                <h3>Goes back to default</h3>
                <ul>
                  {RESTORED.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="reset-list reset-list-kept">
                <h3>Stays as it is</h3>
                <ul>
                  {KEPT.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
            {state.status === 'error' ? (
              <p className="danger-zone-error" role="alert">
                {state.message}
              </p>
            ) : null}
            <div className="modal-actions">
              {/* Focus starts on Cancel, so Enter never restores by accident. */}
              <button autoFocus className="modal-cancel" disabled={working} type="button" onClick={close}>
                Cancel
              </button>
              <button className="restore-defaults-button" disabled={working} type="button" onClick={() => void restore()}>
                {working ? 'Restoring…' : 'Restore defaults'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
