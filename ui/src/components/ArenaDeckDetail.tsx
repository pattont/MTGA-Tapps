import type { ReactNode } from 'react';
import { Archive, FolderInput, Star, Trash2 } from 'lucide-react';
import type { ArenaDeck, ArenaDeckCards, DeckRecord, ManagedDeck } from '../deckManagerApi';
import { DeckRecordBadge } from './DeckRecordBadge';
import { formatDateTime } from '../format';
import { deckFormatLabel } from '../deckFormatLabel';
import { ColorPips } from './ColorPips';
import { DeckCardLists } from './DeckCardLists';
import { ArenaDates } from './ArenaDates';

export interface ArenaDeckDetailProps {
  deck: ArenaDeck;
  /** Tracked-game record for this Arena deck; null when never played. */
  record?: DeckRecord | null;
  /** The saved entry tied to this Arena deck, if any. */
  copy?: ManagedDeck;
  /** The deck's cards from the last Arena read; null while loading. */
  cards: ArenaDeckCards | null;
  error: string;
  statusPills: ReactNode;
  busy: boolean;
  /** Why backing up or moving is unavailable right now; empty when it is available. */
  arenaBlocked: string;
  onBackup: () => void;
  onMove: () => void;
  onTrash: () => void;
  /** Stars or unstars the deck in Arena. */
  onFavorite: () => void;
}

const copyKind = (copy: ManagedDeck) => copy.native_restorable ? 'Exact copy' : 'Deck list';

/** Body of an Arena deck's dialog: its cards as Arena reported them, and the Arena actions. */
export function ArenaDeckDetail({ deck, record, copy, cards, error, statusPills, busy, arenaBlocked, onBackup, onMove, onTrash, onFavorite }: ArenaDeckDetailProps) {
  return (
    <div className="deck-detail">
      <div className="deck-detail-summary">
        <p><ColorPips colors={deck.colors} size={16} />{deckFormatLabel(deck.format_name) || 'Any format'} · {deck.main_count} cards</p>
        {statusPills}
      </div>
      <ArenaDates modified={deck.arena_modified} played={deck.arena_played} />
      <DeckRecordBadge record={record} className="deck-record-dialog" />

      <div className="deck-detail-controls deck-arena-controls">
        <p className="deck-arena-copy">
          {copy ? <>Saved copy: <time dateTime={copy.updated_at}>{formatDateTime(copy.updated_at)}</time> · {copyKind(copy)}</> : 'Not saved locally yet'}
        </p>
        <div className="deck-detail-secondary">
          <button type="button" className={`deck-arena-favorite${deck.is_favorite ? ' is-favorite' : ''}`} aria-pressed={Boolean(deck.is_favorite)} disabled={busy || Boolean(arenaBlocked)}
            title={arenaBlocked || (deck.is_favorite ? 'Removes the star in Arena.' : 'Stars this deck in Arena, like its own favorite button.')} onClick={onFavorite}>
            <Star size={16} aria-hidden="true" /> {deck.is_favorite ? 'Favorite' : 'Add to favorites'}
          </button>
          <button type="button" disabled={busy || Boolean(arenaBlocked)} title={arenaBlocked || 'Saves a full copy of this deck to your collection. Arena is only read.'} onClick={onBackup}><Archive size={16} /> {copy?.native_restorable ? 'Back up again' : 'Back up'}</button>
          <button type="button" disabled={busy || Boolean(arenaBlocked)} title={arenaBlocked || 'Backs up this deck, then removes it from Arena to free a slot.'} onClick={onMove}><FolderInput size={16} /> Move to collection</button>
          <button type="button" className="deck-detail-trash" disabled={busy || Boolean(arenaBlocked)} title={arenaBlocked || 'Backs up this deck, removes it from Arena and puts the backup in Trash.'} onClick={onTrash}><Trash2 size={16} /> Move to trash</button>
        </div>
      </div>

      {cards ? <>
        {cards.refreshed_at ? <p className="deck-arena-note">Cards as Arena reported them at {formatDateTime(cards.refreshed_at)}. Click Rescan Arena after editing this deck in Arena.</p> : null}
        <DeckCardLists cards={cards.cards} facts={cards.card_info} />
      </> : error ? <p role="alert" className="deck-manager-error">{error}</p>
        : <p role="status" className="empty-state">Loading deck…</p>}
    </div>
  );
}
