interface MetricCardProps {
  label: string;
  value: string;
  detail?: string;
  href?: string;
  tone?: 'default' | 'danger' | 'info' | 'warning';
}

export function MetricCard({ label, value, detail, href, tone = 'default' }: MetricCardProps) {
  const className =
    tone === 'danger'
      ? 'metric-card metric-card-danger'
      : tone === 'info'
        ? 'metric-card metric-card-info'
        : tone === 'warning'
          ? 'metric-card metric-card-warning'
        : 'metric-card';
  return (
    <article className={className}>
      <span>{label}</span>
      {href ? (
        <a className="metric-link" href={href}>
          <strong>{value}</strong>
        </a>
      ) : (
        <strong>{value}</strong>
      )}
      {detail ? <small className="metric-card-detail">{detail}</small> : null}
    </article>
  );
}
