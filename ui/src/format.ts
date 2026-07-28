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
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
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
