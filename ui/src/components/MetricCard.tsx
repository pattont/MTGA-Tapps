import type { ReactNode } from 'react';

interface MetricCardProps {
  label: string;
  value: ReactNode;
  detail?: string;
  href?: string;
  tone?: 'default' | 'danger' | 'info' | 'warning' | 'win' | 'loss';
  /** Small icon rendered top-right; inherits the card's text color. */
  icon?: ReactNode;
}

const toneClass: Record<string, string> = {
  danger: 'metric-card metric-card-danger',
  info: 'metric-card metric-card-info',
  warning: 'metric-card metric-card-warning',
  win: 'metric-card metric-card-win',
  loss: 'metric-card metric-card-loss',
};

export function MetricCard({ label, value, detail, href, tone = 'default', icon }: MetricCardProps) {
  const className = toneClass[tone] ?? 'metric-card';
  return (
    <article className={className}>
      <span>{label}</span>
      {icon ? (
        <span className="metric-card-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
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
