import { useState, type ReactNode } from 'react';
import { ChevronDown, Download, Pencil, Trash2, Undo2 } from 'lucide-react';
import type { DeckCollection, DeckRecord, ManagedCard, ManagedDeckDetail } from '../deckManagerApi';
import { DeckRecordBadge } from './DeckRecordBadge';
import { formatDateTime } from '../format';
import { DeckCardLists } from './DeckCardLists';
import { TagInput } from './TagInput';
import { addTags } from '../tagList';
import { ColorPips } from './ColorPips';
import { deckFormatLabel } from '../deckFormatLabel';
import { ArenaDates } from './ArenaDates';

const count = (cards: ManagedCard[]) => cards.reduce((sum, card) => sum + card.quantity, 0);

export interface DeckDetailProps {
  detail: ManagedDeckDetail;
  /** Tracked-game record over every Arena deck this has been; null when never played. */
  record?: DeckRecord | null;
  busy: boolean;
  collections: DeckCollection[];
  statusPills: ReactNode;
  onCollection: (collectionId: string | null) => void;
  onRevision: (revisionId: string) => void;
  onSaveMetadata: (notes: string, tags: string[]) => void;
  onEditRevision: () => void;
  onDownload: () => void;
  onTrash: () => void;
  onRestoreFromTrash: () => void;
  onDeletePermanently: () => void;
}

/** Body of the saved-deck dialog: summary, controls, a compact card grid, then notes. */
export function DeckDetail({
  detail, record, busy, collections, statusPills, onCollection, onRevision, onSaveMetadata,
  onEditRevision, onDownload, onTrash, onRestoreFromTrash, onDeletePermanently,
}: DeckDetailProps) {
  const [notes, setNotes] = useState(detail.notes);
  const [tags, setTags] = useState(detail.tags);
  const [tagDraft, setTagDraft] = useState('');
  const dirty = notes !== detail.notes || tags.join('\n') !== detail.tags.join('\n') || Boolean(tagDraft.trim());
  const cards = detail.deck.cards;
  const main = cards.filter((card) => card.section === 'Deck');
  const sideboard = cards.some((card) => card.section === 'Sideboard')
    ? { cards: cards.filter((card) => card.section === 'Sideboard') } : undefined;
  const revision = detail.revisions.find((r) => r.id === detail.revision_id);
  const summary = [
    deckFormatLabel(detail.deck.format_name) || 'Any format',
    `${count(main)} cards`,
    sideboard ? `${count(sideboard.cards)} sideboard` : null,
    detail.deck.completeness === 'main_only' ? 'Available piles only' : null,
  ].filter(Boolean).join(' · ');

  return (
    <div className="deck-detail">
      <div className="deck-detail-summary">
        <p><ColorPips colors={detail.colors} size={16} />{summary}</p>
        {statusPills}
      </div>
      <ArenaDates modified={detail.arena_modified} played={detail.arena_played} asOfBackup />
      <DeckRecordBadge record={record} className="deck-record-dialog" />

      <div className="deck-detail-controls">
        {!detail.trashed_at ? (
          <label>Collection
            <select aria-label="Deck collection" disabled={busy} value={detail.collection_id ?? ''} onChange={(event) => onCollection(event.target.value || null)}>
              <option value="">Unsorted</option>
              {collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}
            </select>
          </label>
        ) : null}
        <label>Revision
          <select aria-label="Saved revision" value={detail.revision_id} onChange={(event) => onRevision(event.target.value)}>
            {detail.revisions.map((r) => <option key={r.id} value={r.id}>{formatDateTime(r.created_at)}{r.id === detail.current_revision_id ? ' · Latest' : ''}</option>)}
          </select>
        </label>
        <div className="deck-detail-secondary">
          <button type="button" disabled={busy} onClick={onDownload} title="Download a .tappsdeck file with cards, styles and art"><Download size={16} /> Download backup</button>
          {!detail.trashed_at ? <button type="button" disabled={busy} onClick={onEditRevision}><Pencil size={16} /> Edit as new revision</button> : null}
          {detail.trashed_at ? <>
            <button type="button" disabled={busy} onClick={onRestoreFromTrash}><Undo2 size={16} /> Restore from trash</button>
            <button type="button" className="deck-manager-delete" disabled={busy} onClick={onDeletePermanently}><Trash2 size={16} /> Delete permanently</button>
          </> : <button type="button" className="deck-detail-trash" disabled={busy} onClick={onTrash}><Trash2 size={16} /> Move to trash</button>}
        </div>
      </div>
      {revision && revision.id !== detail.current_revision_id ? <p className="deck-detail-note">Viewing an earlier revision saved {formatDateTime(revision.created_at)}.</p> : null}

      <DeckCardLists cards={cards} facts={detail.card_info} />

      <details className="deck-detail-notes" open={Boolean(detail.notes || detail.tags.length) || undefined}>
        <summary>
          <ChevronDown size={16} aria-hidden="true" />Deck Info
          {detail.tags.length ? <span className="deck-detail-tags">{detail.tags.map((tag) => <span key={tag}>{tag}</span>)}</span> : null}
        </summary>
        <div className="deck-detail-notes-body">
          <label>Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} placeholder="Matchups, sideboard plans, changes to try…" /></label>
          <div className="deck-detail-tags-row">
            <div className="deck-detail-tags-field">
              <span className="deck-detail-field-label" aria-hidden="true">Tags</span>
              <TagInput tags={tags} draft={tagDraft} disabled={busy} onChange={(nextTags, draft) => { setTags(nextTags); setTagDraft(draft); }} />
            </div>
            <div className="deck-detail-notes-actions">
              {dirty ? <button type="button" disabled={busy} onClick={() => { setNotes(detail.notes); setTags(detail.tags); setTagDraft(''); }}>Discard</button> : null}
              <button type="button" className="deck-manager-add" disabled={busy || !dirty} onClick={() => { const saved = addTags(tags, [tagDraft]); setTags(saved); setTagDraft(''); onSaveMetadata(notes, saved); }}>Save notes &amp; tags</button>
            </div>
          </div>
        </div>
      </details>
    </div>
  );
}
