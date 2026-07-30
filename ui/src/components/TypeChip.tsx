import { cardTypeToneClass as typeClass } from '../cardTypes';

export function TypeChip({
  type,
  compact = false,
}: {
  type: string | null | undefined;
  compact?: boolean;
}) {
  const label = type || 'Other';
  const className = typeClass[label] ?? 'type-chip-other';
  return (
    <span className={`type-chip ${className}${compact ? ' type-chip-compact' : ''}`}>
      {label}
    </span>
  );
}
