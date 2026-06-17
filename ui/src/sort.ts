export type SortDirection = 'asc' | 'desc';

type Comparable = string | number | boolean | null | undefined;

function isBlankValue(value: unknown): boolean {
  return value === null || value === undefined || value === '';
}

function normalizeValue(value: Comparable): number | string | null {
  if (isBlankValue(value)) {
    return null;
  }
  if (typeof value === 'number') {
    return value;
  }
  if (typeof value === 'boolean') {
    return value ? 1 : 0;
  }
  const trimmed = String(value).trim();
  const percent = trimmed.match(/^(-?\d+(?:\.\d+)?)%$/);
  if (percent) {
    return Number(percent[1]);
  }
  const numeric = Number(trimmed.replace(/,/g, ''));
  if (trimmed !== '' && Number.isFinite(numeric)) {
    return numeric;
  }
  const timestamp = Date.parse(trimmed);
  if (Number.isFinite(timestamp) && /\d{4}-\d{2}-\d{2}/.test(trimmed)) {
    return timestamp;
  }
  return trimmed.toLocaleLowerCase();
}

export function compareValues(left: Comparable, right: Comparable): number {
  const a = normalizeValue(left);
  const b = normalizeValue(right);
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

export function sortRows<T extends object>(
  rows: T[],
  key: keyof T,
  direction: SortDirection,
): T[] {
  const multiplier = direction === 'asc' ? 1 : -1;
  return [...rows].sort((left, right) => {
    const leftValue = left[key] as Comparable;
    const rightValue = right[key] as Comparable;
    const leftBlank = isBlankValue(leftValue);
    const rightBlank = isBlankValue(rightValue);

    if (leftBlank && rightBlank) return 0;
    if (leftBlank) return 1;
    if (rightBlank) return -1;

    return multiplier * compareValues(leftValue, rightValue);
  });
}
