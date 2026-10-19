import { useState, type ReactNode } from 'react';
import { ChevronDown, Download, Pencil, Trash2, Undo2 } from 'lucide-react';
import type { DeckCollection, ManagedCard, ManagedDeckDetail } from '../deckManagerApi';
import { formatDateTime } from '../format';
import { CardLink } from './CardLink';
import { ColorPips } from './ColorPips';
import { deckFormatLabel } from '../deckFormatLabel';

// The main deck gets the wide column; everything else stacks beside it.
const SIDE_SECTIONS = ['Commander', 'Companion', 'Sideboard', 'Maybeboard'];

const count = (cards: ManagedCard[]) => cards.reduce((sum, card) => sum + card.quantity, 0);

function CardSection({ title, cards }: { title: string; cards: ManagedCard[] }) {
  return (
    <section className="deck-detail-section" aria-label={`${title} (${count(cards)})`}>
      <h4>{title}<span>{count(cards)}</span></h4>
      <ul>
        {cards.map((card, i) => (
          <li key={`${title}-${i}`}>
            <span className="deck-detail-quantity">{card.quantity}</span>
            {card.name.startsWith('Card #') ? <span>{card.name}</span> : <CardLink cardName={card.name} returnHash="#/deck-manager" />}
          </li>
        ))}
      </ul>
    </section>
  );
}

export interface DeckDetailProps {
  detail: ManagedDeckDetail;
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
  detail, busy, collections, statusPills, onCollection, onRevision, onSaveMetadata,
  onEditRevision, onDownload, onTrash, onRestoreFromTrash, onDeletePermanently,
}: DeckDetailProps) {
  const [notes, setNotes] = useState(detail.notes);
  const [tags, setTags] = useState(detail.tags.join(', '));
  const savedTags = detail.tags.join(', ');
  const dirty = notes !== detail.notes || tags !== savedTags;
  const cards = detail.deck.cards;
  const main = cards.filter((card) => card.section === 'Deck');
  const side = SIDE_SECTIONS.map((section) => ({ section, cards: cards.filter((card) => card.section === section) }))
    .filter((group) => group.cards.length);
  const sideboard = side.find((group) => group.section === 'Sideboard');
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

      <div className={`deck-detail-lists${side.length ? '' : ' deck-detail-lists-single'}`}>
        <CardSection title="Deck" cards={main} />
        {side.length ? <div className="deck-detail-side">{side.map((group) => <CardSection key={group.section} title={group.section} cards={group.cards} />)}</div> : null}
      </div>

      <details className="deck-detail-notes" open={Boolean(detail.notes || detail.tags.length) || undefined}>
        <summary>
          <ChevronDown size={16} aria-hidden="true" />Notes &amp; tags
          {detail.tags.length ? <span className="deck-detail-tags">{detail.tags.map((tag) => <span key={tag}>{tag}</span>)}</span> : null}
        </summary>
        <div className="deck-detail-notes-body">
          <label>Tags<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="Separate tags with commas" /></label>
          <label>Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></label>
          <div className="deck-detail-notes-actions">
            {dirty ? <button type="button" disabled={busy} onClick={() => { setNotes(detail.notes); setTags(savedTags); }}>Discard</button> : null}
            <button type="button" className="deck-manager-add" disabled={busy || !dirty} onClick={() => onSaveMetadata(notes, tags.split(','))}>Save notes &amp; tags</button>
          </div>
        </div>
      </details>
    </div>
  );
}
