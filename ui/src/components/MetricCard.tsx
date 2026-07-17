interface MetricCardProps {
  label: string;
  value: string;
  href?: string;
  tone?: 'default' | 'danger';
}

export function MetricCard({ label, value, href, tone = 'default' }: MetricCardProps) {
  return (
    <article className={tone === 'danger' ? 'metric-card metric-card-danger' : 'metric-card'}>
      <span>{label}</span>
      {href ? (
        <a className="metric-link" href={href}>
          <strong>{value}</strong>
        </a>
      ) : (
        <strong>{value}</strong>
      )}
    </article>
  );
}
