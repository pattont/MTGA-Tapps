import { CalendarClock } from 'lucide-react';
import { formatDateTime } from '../format';

/**
 * When Arena last saw the deck edited and played. `asOfBackup` marks dates
 * read from a saved backup rather than from Arena now.
 */
export function ArenaDates({ modified, played, asOfBackup = false }: { modified?: string | null; played?: string | null; asOfBackup?: boolean }) {
  if (!modified && !played) return null;
  return (
    <p className="deck-arena-dates" title={asOfBackup ? 'As Arena reported them when this deck was backed up' : undefined}>
      <CalendarClock size={15} aria-hidden="true" />
      {modified ? <span>Modified in Arena <time dateTime={modified}>{formatDateTime(modified)}</time></span> : null}
      <span>{played ? <>Last played <time dateTime={played}>{formatDateTime(played)}</time></> : 'Never played'}</span>
      {asOfBackup ? <small>as of the backup</small> : null}
    </p>
  );
}
