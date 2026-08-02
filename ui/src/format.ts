export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : String(value);
}

export function formatCardName(cardName: string): string {
  return cardName.replace(/\s*\/\/\s*/g, ' / ');
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  // Compact "8/2/26, 12:49AM" so date columns stay narrow in game tables.
  const hours24 = date.getHours();
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const meridiem = hours24 < 12 ? 'AM' : 'PM';
  const year = String(date.getFullYear() % 100).padStart(2, '0');
  return `${date.getMonth() + 1}/${date.getDate()}/${year}, ${hours12}:${minutes}${meridiem}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  const minutes = Math.round(seconds / 60);
  return `${minutes} min`;
}

export function formatTurnDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  const roundedSeconds = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(roundedSeconds / 60);
  const remainingSeconds = roundedSeconds % 60;
  if (minutes === 0) {
    return `${remainingSeconds} sec`;
  }
  return `${minutes}m ${String(remainingSeconds).padStart(2, '0')}s`;
}

export function outcomeTone(outcome: string | null | undefined): 'neutral' | 'win' | 'loss' | 'draw' {
  if (outcome === 'win' || outcome === 'loss' || outcome === 'draw') {
    return outcome;
  }
  return 'neutral';
}

export function outcomeLabel(outcome: string | null | undefined): string {
  return outcome ? outcome[0].toUpperCase() + outcome.slice(1) : 'Unknown';
}

/** "Standard Best-of-1 (Ranked)" -> "Standard BO1 (Ranked)" for tight table columns. */
export function shortFormatLabel(label: string | null | undefined): string {
  return String(label ?? '')
    .replace('Standard ', 'Std. ')
    .replace('Best-of-1', 'BO1')
    .replace('Best-of-3', 'BO3')
    .replace(' (Unranked)', '');
}
