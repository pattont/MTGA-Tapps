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
  // Compact locale-aware date ("8/2/26, 12:49AM" in the US, "2/8/26, 12:49AM"
  // in day-first regions) so date columns stay narrow and read naturally.
  const formatted = date.toLocaleString(undefined, {
    year: '2-digit',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
  // Tighten "12:49 AM" to "12:49AM" without disturbing 24-hour locales.
  return formatted.replace(/\s([AaPp])\.?\s?[Mm]\.?$/, (_, letter: string) => `${letter.toUpperCase()}M`);
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

/** One letter for tight lists: "W", "L", "D", "?" for unknown. */
export function outcomeShortLabel(outcome: string | null | undefined): string {
  const label = outcomeLabel(outcome);
  return label === 'Unknown' ? '?' : label[0];
}

/** "Standard Best-of-1 (Ranked)" -> "Standard BO1 (Ranked)" (full label kept). */
export function boFormatLabel(label: string | null | undefined): string {
  return String(label ?? '').replace('Best-of-1', 'BO1').replace('Best-of-3', 'BO3');
}

/** "Standard Best-of-1 (Ranked)" -> "Standard BO1 (Ranked)" for tight table columns. */
export function shortFormatLabel(label: string | null | undefined): string {
  return String(label ?? '')
    .replace('Standard ', 'Std. ')
    .replace('Best-of-1', 'BO1')
    .replace('Best-of-3', 'BO3')
    .replace(' (Unranked)', '');
}

/** "Platinum 2 · 3/6", or Mythic with rank/percentile when available. */
export function rankText(rank: {
  rank_class: string;
  rank_level: number;
  rank_step: number;
  rank_steps: number;
  mythic_percentile: number | null;
  mythic_rank: number | null;
}): string {
  if (rank.rank_class === 'Mythic') {
    if (rank.mythic_rank) return `Mythic #${rank.mythic_rank}`;
    if (rank.mythic_percentile != null) return `Mythic ${rank.mythic_percentile}%`;
    return 'Mythic';
  }
  return `${rank.rank_class} ${rank.rank_level} · ${rank.rank_step}/${rank.rank_steps}`;
}
