import { useEffect, useState } from 'react';
import { fetchAuditReport, type AuditFindingRow, type AuditReport } from '../api';
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
    </>
  );
}
