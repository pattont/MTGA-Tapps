import type { ReactNode } from 'react';

interface BadgeProps {
  tone?: 'neutral' | 'win' | 'loss' | 'draw' | 'screw' | 'play' | 'drawside' | 'mull' | 'flood' | 'streak';
  children: ReactNode;
  className?: string;
  /** Full text for a shortened badge, shown on hover. */
  title?: string;
}

export function Badge({ tone = 'neutral', children, className, title }: BadgeProps) {
  return (
    <span className={`badge badge-${tone}${className ? ` ${className}` : ''}`} title={title}>
      {children}
    </span>
  );
}
