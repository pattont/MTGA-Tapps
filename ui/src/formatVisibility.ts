interface FormatIdentity {
  format_label: string;
  raw_format?: string;
  raw_formats?: string;
}

export function showInFormatAnalytics(format: FormatIdentity) {
  const label = format.format_label.trim().toLocaleLowerCase();
  const raw = (format.raw_format ?? format.raw_formats ?? '').trim().toLocaleLowerCase();
  return !label.startsWith('midweek magic') && !raw.startsWith('mwm_') && !label.includes('momir');
}
