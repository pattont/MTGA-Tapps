import { useEffect, useState } from 'react';
import { fetchAuditReport, resetDatabase, type AuditFindingRow, type AuditReport } from '../api';
import { Badge } from './Badge';
import { MetricCard } from './MetricCard';
import { Section } from './Section';
import { SortableTable, type Column } from './SortableTable';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; report: AuditReport }
  | { status: 'error'; message: string };

const findingColumns: Column<AuditFindingRow>[] = [
  { key: 'code', header: 'Code' },
  {
    key: 'severity',
    header: 'Severity',
    render: (row) => (
      <Badge tone={row.severity === 'error' ? 'loss' : 'draw'}>{row.severity}</Badge>
    ),
    sortValue: (row) => row.severity,
  },
  { key: 'table_name', header: 'Table' },
  { key: 'row_id', header: 'Row' },
  { key: 'message', header: 'Finding' },
  {
    key: 'repairable',
    header: 'Repairable',
    render: (row) => (row.repairable ? 'Yes — run db_audit --repair' : 'Manual'),
    sortValue: (row) => (row.repairable ? 1 : 0),
  },
];

export function AuditPage() {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    window.scrollTo(0, 0);
    const controller = new AbortController();
    void fetchAuditReport(controller.signal)
      .then((report) => setLoadState({ status: 'loaded', report }))
      .catch((error: unknown) => {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          setLoadState({
            status: 'error',
            message: error instanceof Error ? error.message : 'Audit failed',
          });
        }
      });
    return () => controller.abort();
  }, [retryToken]);

  if (loadState.status === 'loading') {
    return (
      <p className="state-panel" role="status" aria-busy="true">
        Auditing database consistency...
      </p>
    );
  }
  if (loadState.status === 'error') {
    return (
      <div className="state-panel error-state" role="alert">
        <p>{loadState.message}</p>
        <button className="retry-button" type="button" onClick={() => setRetryToken((token) => token + 1)}>
          Retry
        </button>
      </div>
    );
  }

  const { report } = loadState;
  return (
    <>
      <section className="metric-grid metric-grid-deck" aria-label="Audit summary" id="audit-summary">
        <MetricCard label="Total Findings" value={String(report.total)} />
        {report.by_code.slice(0, 4).map((entry) => (
          <MetricCard key={entry.code} label={entry.code} value={String(entry.count)} />
        ))}
      </section>
      <Section
        id="audit-findings"
        title="Findings"
        description="Consistency issues detected by db_audit. Repairable findings can be fixed with: venv/bin/python -m mtga_tracker.db_audit --repair"
      >
        {report.findings.length > 0 ? (
          <SortableTable
            caption="Database audit findings"
            columns={findingColumns}
            getRowKey={(row) => `${row.code}-${row.table_name}-${row.row_id}`}
            pageSize={20}
            rows={report.findings}
          />
        ) : (
          <p className="empty-state">No consistency issues found. The database looks healthy.</p>
        )}
      </Section>

      <Section
        id="audit-danger"
        title="Danger Zone"
        description="Reset wipes every tracked game, match, and session from the database. A timestamped backup is written first, and the schema stays intact so tracking resumes cleanly. Close the tracker before resetting."
      >
        <DangerZone onReset={() => setRetryToken((token) => token + 1)} />
      </Section>
    </>
  );
}

function DangerZone({ onReset }: { onReset: () => void }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [state, setState] = useState<
    { status: 'idle' } | { status: 'working' } | { status: 'done'; backup: string } | { status: 'error'; message: string }
  >({ status: 'idle' });
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
      onReset();
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
        <p>
          Wipe all tracked history and start fresh. A timestamped backup is saved next to the
          database first.
        </p>
        <button className="danger-zone-button" type="button" onClick={openModal}>
          Reset Database…
        </button>
      </div>
      {state.status === 'done' ? (
        <p className="danger-zone-result" role="status">
          Database reset. A backup of your old data was saved to:
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
            <h3 id="reset-modal-title">Reset the database?</h3>
            <p>
              This wipes <strong>every tracked game, match, and session</strong>. A timestamped
              backup is written next to the database first, but the dashboard cannot undo this.
              Close the tracker before resetting.
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
                {state.status === 'working' ? 'Resetting…' : 'Reset Database'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
