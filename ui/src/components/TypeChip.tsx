const typeClass: Record<string, string> = {
  Land: 'type-chip-land',
  Creature: 'type-chip-creature',
  Instant: 'type-chip-instant',
  Sorcery: 'type-chip-sorcery',
  Artifact: 'type-chip-artifact',
  Enchantment: 'type-chip-enchantment',
  Planeswalker: 'type-chip-planeswalker',
  Battle: 'type-chip-other',
};

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
