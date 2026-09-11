import { useEffect, useState } from 'react';
import {
  deleteBackup,
  exportBackup,
  fetchBackupStatus,
  inspectBackup,
  mergeBackup,
  restoreBackup,
  revealBackup,
  saveBackupFolder,
  type BackupFile,
  type BackupMergeResult,
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
  const [merged, setMerged] = useState<BackupMergeResult | null>(null);
  const [pendingDelete, setPendingDelete] = useState<BackupFile | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  // Which confirmation the open dialog is for.
  const [action, setAction] = useState<'restore' | 'merge' | null>(null);

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

  function closeDialog() {
    setPreview(null);
    setAction(null);
    setPendingDelete(null);
    setConfirmText('');
    setDialogError(null);
  }

  async function begin(kind: 'restore' | 'merge', path: string) {
    setPreviewBusy(true);
    setPreview(null);
    setRestored(null);
    setMerged(null);
    setConfirmText('');
    setError(null);
    setDialogError(null);
    try {
      setPreview(await inspectBackup(path));
      setAction(kind);
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
    setDialogError(null);
    try {
      const result = await restoreBackup(preview.path, preview.requires_confirm ? confirmText.trim() : undefined);
      setStatus(result.status);
      setRestored(result.restore);
      closeDialog();
    } catch (exc) {
      setDialogError(message(exc, 'Restore failed'));
    } finally {
      setRestoring(false);
    }
  }

  async function runMerge() {
    if (!preview) {
      return;
    }
    setRestoring(true);
    setDialogError(null);
    try {
      const result = await mergeBackup(preview.path);
      setStatus(result.status);
      setMerged(result.merge);
      closeDialog();
    } catch (exc) {
      setDialogError(message(exc, 'Merge failed'));
    } finally {
      setRestoring(false);
    }
  }

  async function runDelete() {
    if (!pendingDelete) {
      return;
    }
    setRestoring(true);
    setDialogError(null);
    try {
      const result = await deleteBackup(pendingDelete.path);
      setStatus(result.status);
      closeDialog();
    } catch (exc) {
      setDialogError(message(exc, 'Delete failed'));
    } finally {
      setRestoring(false);
    }
  }

  async function reveal(path: string) {
    setError(null);
    try {
      await revealBackup(path);
    } catch (exc) {
      setError(message(exc, 'Could not open the file location'));
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
            {folderBusy ? 'Setting…' : 'Set'}
          </button>
        </div>
        {status.detected_folders.length > 0 ? (
          <div className="backup-picks" aria-label="Detected backup locations">
            <span className="backup-picks-label">Detected Backup Locations:</span>
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
        <div className="backup-files">
          <h3 className="backup-files-title">Backup Files</h3>
          <p className="backup-files-path">{status.folder}</p>
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
                      <div className="backup-row-actions">
                        {file.error ? null : (
                          <>
                            <button
                              type="button"
                              className="deck-neutral-button backup-row-button"
                              disabled={previewBusy || restoring}
                              onClick={() => begin('restore', file.path)}
                            >
                              Restore
                            </button>
                            <button
                              type="button"
                              className="deck-neutral-button backup-row-button"
                              disabled={previewBusy || restoring}
                              onClick={() => begin('merge', file.path)}
                            >
                              Merge
                            </button>
                          </>
                        )}
                        <button
                          type="button"
                          className="deck-neutral-button backup-row-button"
                          title="Open file location"
                          aria-label={`Open the location of ${file.name}`}
                          onClick={() => reveal(file.path)}
                        >
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
                          </svg>
                          Open location
                        </button>
                        <button
                          type="button"
                          className="backup-delete-button"
                          title="Delete this backup file"
                          aria-label={`Delete ${file.name}`}
                          disabled={previewBusy || restoring}
                          onClick={() => {
                            setPreview(null);
                            setAction(null);
                            setDialogError(null);
                            setPendingDelete(file);
                          }}
                        >
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
                            <path d="M6 6l12 12M18 6L6 18" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
            onClick={() => begin('restore', filePath.trim())}
          >
            {previewBusy ? 'Reading…' : 'Restore'}
          </button>
          <button
            type="button"
            className="deck-neutral-button"
            disabled={previewBusy || restoring || filePath.trim() === ''}
            onClick={() => begin('merge', filePath.trim())}
          >
            Merge
          </button>
        </div>
      </div>

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
                onClick={() => begin('restore', restored.undo as string)}
              >
                Undo — put back what was here before
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {merged ? (
        <div className="backup-preview backup-done" role="status">
          <p className="backup-preview-title">
            Merged {plural(merged.games_added, 'game')} from {merged.manifest.machine}'s backup of{' '}
            {formatDateTime(merged.manifest.exported_at)} — {plural(merged.games, 'game')} here now.
            {merged.tracker_restarted ? ' The tracker was restarted.' : ''}
          </p>
          <p className="settings-hint">Back up now to have everything in one file.</p>
          {merged.undo ? (
            <div className="backup-actions">
              <button
                type="button"
                className="deck-neutral-button"
                disabled={previewBusy || restoring}
                onClick={() => begin('restore', merged.undo as string)}
              >
                Undo — put back what was here before
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {preview && described && action ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget && !restoring) {
              closeDialog();
            }
          }}
        >
          <div
            aria-labelledby="backup-dialog-title"
            aria-modal="true"
            className={preview.requires_confirm && action === 'restore' ? 'modal danger-modal' : 'modal'}
            role="dialog"
            onKeyDown={(event) => {
              if (event.key === 'Escape' && !restoring) {
                closeDialog();
              }
            }}
          >
            <h3 id="backup-dialog-title">
              {action === 'restore' ? 'Restore' : 'Merge'} {preview.manifest.machine}'s backup from{' '}
              {formatDateTime(preview.manifest.exported_at)}
              {preview.same_install ? ' (this computer)' : ''}?
            </h3>
            <p className="backup-dialog-file">{preview.path.split(/[\\/]/).pop()}</p>
            {action === 'restore' ? (
              <>
                <p>{described.text}</p>
                <p>
                  The tracker is paused for the swap and started again after. A copy of the current state
                  is saved first and can be put back from this card.
                </p>
                {preview.requires_confirm && !described.blocked ? (
                  <>
                    <label className="danger-modal-label" htmlFor="backup-confirm-input">
                      Type <strong>REPLACE</strong> (all caps) to confirm losing those games:
                    </label>
                    <input
                      autoFocus
                      id="backup-confirm-input"
                      placeholder="REPLACE"
                      value={confirmText}
                      onChange={(event) => setConfirmText(event.target.value)}
                      autoComplete="off"
                    />
                  </>
                ) : null}
              </>
            ) : (
              <>
                <p>
                  {described.blocked
                    ? described.text
                    : preview.adds > 0
                      ? `Adds ${plural(preview.adds, 'game')} from the backup to the ${plural(preview.local.games, 'game')} already here. Nothing here is removed or changed; settings are not touched.`
                      : 'Every game in this backup is already here. Nothing would change.'}
                </p>
                <p>
                  The tracker is paused while the games are added and started again after. A copy of the
                  current state is saved first and can be put back from this card.
                </p>
              </>
            )}
            {dialogError ? (
              <p className="backup-error" role="alert">
                {dialogError}
              </p>
            ) : null}
            <div className="modal-actions">
              <button className="modal-cancel" disabled={restoring} type="button" onClick={closeDialog}>
                Cancel
              </button>
              {action === 'restore' ? (
                <button
                  className={preview.requires_confirm ? 'danger-zone-button' : 'deck-export-button'}
                  disabled={restoring || described.blocked || !confirmOk}
                  type="button"
                  onClick={() => void runRestore()}
                >
                  {restoring ? 'Restoring…' : 'Restore this backup'}
                </button>
              ) : (
                <button
                  className="deck-export-button"
                  disabled={restoring || described.blocked || preview.adds === 0}
                  type="button"
                  onClick={() => void runMerge()}
                >
                  {restoring ? 'Merging…' : `Merge ${plural(preview.adds, 'game')}`}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {pendingDelete ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget && !restoring) {
              closeDialog();
            }
          }}
        >
          <div
            aria-labelledby="backup-delete-title"
            aria-modal="true"
            className="modal danger-modal"
            role="dialog"
            onKeyDown={(event) => {
              if (event.key === 'Escape' && !restoring) {
                closeDialog();
              }
            }}
          >
            <h3 id="backup-delete-title">Delete this backup file?</h3>
            <p className="backup-dialog-file">{pendingDelete.name}</p>
            <p>
              {pendingDelete.exported_at ? `Made ${formatDateTime(pendingDelete.exported_at)}` : 'Unreadable file'}
              {pendingDelete.machine ? ` on ${pendingDelete.machine}` : ''}
              {typeof pendingDelete.games === 'number' ? ` · ${plural(pendingDelete.games, 'game')}` : ''}
              {' · '}
              {formatSize(pendingDelete.size)}. The file is removed from the backup folder; the database on
              this computer is not touched. This cannot be undone.
            </p>
            {dialogError ? (
              <p className="backup-error" role="alert">
                {dialogError}
              </p>
            ) : null}
            <div className="modal-actions">
              <button className="modal-cancel" disabled={restoring} type="button" onClick={closeDialog}>
                Cancel
              </button>
              <button className="danger-zone-button" disabled={restoring} type="button" onClick={() => void runDelete()}>
                {restoring ? 'Deleting…' : 'Delete file'}
              </button>
            </div>
          </div>
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
