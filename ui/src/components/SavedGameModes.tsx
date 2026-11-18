import { useState } from 'react';
import { saveTrackingSettings, type TrackedMode, type TrackingSettings } from '../api';
import { SAVED_GAME_MODES } from '../savedGameModes';
import { FeatureSwitch } from './FeatureSwitch';

export function SavedGameModes({
  initial,
  onChange,
}: {
  initial: TrackingSettings;
  onChange?: (next: TrackingSettings) => void;
}) {
  const [settings, setSettings] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A tracker older than this card reports only Direct Challenge.
  const modes = SAVED_GAME_MODES.filter((mode) => typeof settings[mode.key] === 'boolean');

  async function update(key: TrackedMode, next: boolean) {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await saveTrackingSettings({ [key]: next });
      setSettings(saved);
      onChange?.(saved);
      setMessage('Saved. It applies from the next game.');
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'The setting could not be saved');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="saved-modes">
      <ul className="saved-modes-grid">
        {modes.map((mode) => {
          const checked = settings[mode.key] === true;
          return (
            <li key={mode.key} className={checked ? 'saved-mode saved-mode-on' : 'saved-mode'}>
              <span className="saved-mode-text">
                <span className="saved-mode-name">{mode.label}</span>
                <span className="saved-mode-note">{mode.note}</span>
              </span>
              <FeatureSwitch
                busy={busy}
                checked={checked}
                label={`Save ${mode.label} games`}
                onChange={(next) => void update(mode.key, next)}
              />
            </li>
          );
        })}
      </ul>
      <p className="settings-hint">
        Modes switched off still show on the Live Scoreboard and in the overlay; their games just
        aren't saved. Changes apply from the next game.
      </p>
      {message ? (
        <p className="backup-note backup-note-done startup-save-status" role="status">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="collection-export-status collection-export-fail" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
