interface MetricCardProps {
  label: string;
  value: string;
  href?: string;
}

export function MetricCard({ label, value, href }: MetricCardProps) {
  return (
    <article className="metric-card">
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
