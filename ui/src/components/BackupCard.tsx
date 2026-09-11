import { useEffect, useState } from 'react';
import {
  exportBackup,
  fetchBackupStatus,
  inspectBackup,
  restoreBackup,
  saveBackupFolder,
  type BackupFile,
  type BackupPreview,
  type BackupRestoreResult,
  type BackupStatus,
} from '../api';
import { formatDateTime } from '../format';
import { describePreview, plural } from '../backupText';

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined) {
    return '—';
  }
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function BackupCard() {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [folder, setFolder] = useState('');
  const [folderBusy, setFolderBusy] = useState(false);
  const [includeKeys, setIncludeKeys] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState<{ text: string; done: boolean } | null>(null);
  const [filePath, setFilePath] = useState('');
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [restoring, setRestoring] = useState(false);
  const [restored, setRestored] = useState<BackupRestoreResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBackupStatus()
      .then((next) => {
        if (!cancelled) {
          setStatus(next);
          setFolder(next.folder ?? '');
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : 'Backup status failed to load');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const message = (exc: unknown, fallback: string) => (exc instanceof Error ? exc.message : fallback);

  async function applyFolder(next: string) {
    setFolderBusy(true);
    setError(null);
    try {
      await saveBackupFolder(next);
      const refreshed = await fetchBackupStatus();
      setStatus(refreshed);
      setFolder(refreshed.folder ?? '');
    } catch (exc) {
      setError(message(exc, 'Could not save the folder'));
    } finally {
      setFolderBusy(false);
    }
  }

  async function runExport() {
    setExporting(true);
    setExportNote({ text: 'Taking a snapshot of the database…', done: false });
    setError(null);
    try {
      const result = await exportBackup({ include_keys: includeKeys });
      setStatus(result.status);
      setExportNote({
        text: `Saved ${result.backup.path.split(/[\\/]/).pop()} — ${plural(result.backup.games, 'game')}, ${formatSize(result.backup.size)}.`,
        done: true,
      });
    } catch (exc) {
      setExportNote(null);
      setError(message(exc, 'Backup failed'));
    } finally {
      setExporting(false);
    }
  }

  async function beginRestore(path: string) {
    setPreviewBusy(true);
    setPreview(null);
    setRestored(null);
    setConfirmText('');
    setError(null);
    try {
      setPreview(await inspectBackup(path));
    } catch (exc) {
      setError(message(exc, 'Could not read that backup'));
    } finally {
      setPreviewBusy(false);
    }
  }

  async function runRestore() {
    if (!preview) {
      return;
    }
    setRestoring(true);
    setError(null);
    try {
      const result = await restoreBackup(preview.path, preview.requires_confirm ? confirmText.trim() : undefined);
      setStatus(result.status);
      setRestored(result.restore);
      setPreview(null);
      setConfirmText('');
    } catch (exc) {
      setError(message(exc, 'Restore failed'));
    } finally {
      setRestoring(false);
    }
  }

  if (error && status === null) {
    return <p className="empty-state deckfinder-state">{error}</p>;
  }
  if (status === null) {
    return (
      <p className="state-panel deckfinder-state" role="status" aria-busy="true">
        Loading…
      </p>
    );
  }

  const described = preview ? describePreview(preview) : null;
  const confirmOk = !preview?.requires_confirm || confirmText.trim() === 'REPLACE';
  const backups = status.backups;

  return (
    <div className="backup-card">
      <p className="backup-summary">
        <strong>{plural(status.local.games, 'game')}</strong> on this computer
        {status.local.newest_game_at ? <> · newest {formatDateTime(status.local.newest_game_at)}</> : null}
        {' · '}
        {status.last_backup ? (
          <>
            last backed up {formatDateTime(status.last_backup.at)} ({plural(status.last_backup.games, 'game')})
          </>
        ) : (
          <span className="backup-summary-warn">never backed up</span>
        )}
      </p>

      <div className="settings-field">
        <span>Backup folder</span>
        <div className="settings-key-row">
          <input
            type="text"
            value={folder}
            placeholder={status.default_folder}
            onChange={(event) => setFolder(event.target.value)}
            aria-label="Backup folder"
          />
          <button
            type="button"
            className="deck-neutral-button"
            disabled={folderBusy || folder.trim() === (status.folder ?? '')}
            onClick={() => applyFolder(folder.trim())}
          >
            {folderBusy ? 'Saving…' : 'Save'}
          </button>
        </div>
        {status.detected_folders.length > 0 ? (
          <div className="backup-picks" aria-label="Synced folders on this computer">
            <span className="backup-picks-label">Synced here:</span>
            {status.detected_folders.map((pick) => (
              <button
                key={pick.path}
                type="button"
                className={pick.path === folder.trim() ? 'backup-pick backup-pick-active' : 'backup-pick'}
                title={pick.path}
                disabled={folderBusy}
                onClick={() => setFolder(pick.path)}
              >
                {pick.name}
              </button>
            ))}
          </div>
        ) : null}
        <p className="settings-hint">
          Choose a folder that Google Drive, iCloud, Dropbox or OneDrive syncs and your backups will show
          up on your other computers automatically. The folder is created with your first backup.
        </p>
      </div>

      <div className="backup-actions">
        <button
          type="button"
          className="deck-export-button"
          disabled={exporting || !status.folder}
          onClick={runExport}
        >
          {exporting ? 'Backing up…' : 'Back up now'}
        </button>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={includeKeys}
            onChange={(event) => setIncludeKeys(event.target.checked)}
          />
          Include API keys
        </label>
        {exportNote ? (
          <span className={exportNote.done ? 'backup-note backup-note-done' : 'backup-note'} role="status">
            {exportNote.text}
          </span>
        ) : null}
      </div>
      {!status.folder ? <p className="settings-hint">Choose a folder above to enable backups.</p> : null}

      {backups.length > 0 ? (
        <div className="table-wrap">
          <table className="backup-table">
            <thead>
              <tr>
                <th>Backup</th>
                <th>Computer</th>
                <th className="numeric">Games</th>
                <th>Newest game</th>
                <th className="numeric">Size</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {backups.map((file: BackupFile) => (
                <tr key={file.path} className={file.error ? 'backup-row-error' : undefined}>
                  <td>
                    {file.exported_at ? formatDateTime(file.exported_at) : file.name}
                    {file.error ? <span className="backup-row-note">{file.error}</span> : null}
                    {file.install_id && file.install_id === status.install_id ? (
                      <span className="backup-row-note">this computer</span>
                    ) : null}
                  </td>
                  <td>{file.machine ?? '—'}</td>
                  <td className="numeric">{file.games ?? '—'}</td>
                  <td>{file.newest_game_at ? formatDateTime(file.newest_game_at) : '—'}</td>
                  <td className="numeric">{formatSize(file.size)}</td>
                  <td>
                    {file.error ? null : (
                      <button
                        type="button"
                        className="deck-neutral-button backup-restore-button"
                        disabled={previewBusy || restoring}
                        onClick={() => beginRestore(file.path)}
                      >
                        Restore…
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : status.folder ? (
        <p className="settings-hint">No backups in this folder yet.</p>
      ) : null}

      <div className="settings-field">
        <span>Restore from a file elsewhere</span>
        <div className="settings-key-row">
          <input
            type="text"
            value={filePath}
            placeholder="Full path to a .tappsbackup file"
            onChange={(event) => setFilePath(event.target.value)}
            aria-label="Backup file path"
          />
          <button
            type="button"
            className="deck-neutral-button"
            disabled={previewBusy || restoring || filePath.trim() === ''}
            onClick={() => beginRestore(filePath.trim())}
          >
            {previewBusy ? 'Reading…' : 'Restore…'}
          </button>
        </div>
      </div>

      {preview && described ? (
        <div className="backup-preview" role="region" aria-label="Restore preview">
          <p className="backup-preview-title">
            Restore {preview.manifest.machine}'s backup from {formatDateTime(preview.manifest.exported_at)}
            {preview.same_install ? ' (this computer)' : ''}?
          </p>
          <p className="backup-preview-text">{described.text}</p>
          <p className="settings-hint">
            The tracker is paused for the swap and started again after. A copy of the current state is
            saved first, and can be restored back from this card.
          </p>
          {preview.requires_confirm && !described.blocked ? (
            <label className="settings-field backup-confirm">
              <span>Type REPLACE to confirm losing those games</span>
              <input
                type="text"
                value={confirmText}
                onChange={(event) => setConfirmText(event.target.value)}
                aria-label="Type REPLACE to confirm"
                autoComplete="off"
              />
            </label>
          ) : null}
          <div className="backup-actions">
            <button
              type="button"
              className="deck-export-button"
              disabled={restoring || described.blocked || !confirmOk}
              onClick={runRestore}
            >
              {restoring ? 'Restoring…' : 'Restore this backup'}
            </button>
            <button type="button" className="deck-neutral-button" disabled={restoring} onClick={() => setPreview(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {restored ? (
        <div className="backup-preview backup-done" role="status">
          <p className="backup-preview-title">
            Restored {plural(restored.games, 'game')} from {restored.manifest.machine}'s backup of{' '}
            {formatDateTime(restored.manifest.exported_at)}.
            {restored.tracker_restarted ? ' The tracker was restarted.' : ''}
          </p>
          {restored.undo ? (
            <div className="backup-actions">
              <button
                type="button"
                className="deck-neutral-button"
                disabled={previewBusy || restoring}
                onClick={() => beginRestore(restored.undo as string)}
              >
                Undo — put back what was here before
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <p className="backup-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
