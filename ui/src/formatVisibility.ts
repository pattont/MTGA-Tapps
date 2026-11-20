interface FormatIdentity {
  format_label: string;
  raw_format?: string;
  raw_formats?: string;
  /** Set by the tracker when Settings → Saved game modes saves this format's games. */
  saved_mode?: boolean;
}

// Midweek Magic, Momir and Welcome Deck Duels stay out of format lists, as a
// safeguard against old rows, unless the tracker says their games are saved.
export function showInFormatAnalytics(format: FormatIdentity) {
  if (format.saved_mode) return true;
  const label = format.format_label.trim().toLocaleLowerCase();
  const raw = (format.raw_format ?? format.raw_formats ?? '').trim().toLocaleLowerCase();
  return (
    !label.startsWith('midweek magic') &&
    !raw.startsWith('mwm_') &&
    !label.includes('momir') &&
    !label.includes('welcome deck') &&
    !raw.includes('welcome_deck')
  );
}
