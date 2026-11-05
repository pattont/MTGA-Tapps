import { useEffect, useState, type ReactNode } from 'react';
import { ArrowLeftRight, Check, ChevronDown } from 'lucide-react';
import { fetchArenaDeck, fetchManagedDeck, type CardFacts, type DeckRecord, type ManagedCard } from '../deckManagerApi';
import { DeckRecordBadge } from './DeckRecordBadge';
import { compareDecks, sectionLabel, type ComparedCard } from '../deckCompare';
import { CardLink } from './CardLink';
import { ColorPips } from './ColorPips';
import { ManaCost } from '../stream/widgets/ManaCost';

export interface CompareSide {
  key: string;
  name: string;
  /** Format and size, shown under the name. */
  summary: string;
  colors?: string;
  art: ReactNode;
  /** Where the cards come from; null when there is nothing to read yet. */
  source: CompareSource | null;
  note?: string;
  /** Tracked-game record; null when never played. */
  record?: DeckRecord | null;
}

/**
 * A saved deck's latest revision, or an Arena deck as of the last read.
 * `version` (a revision or read time) refetches when the list changes.
 */
export interface CompareSource { kind: 'saved' | 'arena'; id: string; version?: string }

type Loaded = { key: string; cards?: ManagedCard[]; facts?: Record<string, CardFacts>; error?: string };

function useDeckCards(kind?: CompareSource['kind'], id?: string, version?: string): Loaded | null {
  const key = `${kind}:${id}:${version ?? ''}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  useEffect(() => {
    if (!kind || !id) return;
    const controller = new AbortController();
    const load = kind === 'saved'
      ? fetchManagedDeck(id, undefined, controller.signal).then((deck) => ({ cards: deck.deck.cards, facts: deck.card_info }))
      : fetchArenaDeck(id, controller.signal).then((deck) => ({ cards: deck.cards, facts: deck.card_info }));
    load.then((deck) => { if (!controller.signal.aborted) setLoaded({ key, ...deck }); })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setLoaded({ key, error: err instanceof Error ? err.message : 'This deck could not be loaded.' });
      });
    return () => controller.abort();
  }, [kind, id, key]);
  return loaded?.key === key ? loaded : null;
}

function CardName({ name }: { name: string }) {
  return name.startsWith('Card #') ? <span>{name}</span> : <CardLink cardName={name} returnHash="#/deck-manager" />;
}

function Cost({ facts }: { facts?: CardFacts }) {
  return facts?.mana_cost ? <ManaCost cost={facts.mana_cost} /> : null;
}

function DeckSide({ side, tone }: { side: CompareSide; tone: 'a' | 'b' }) {
  return (
    <div className={`deck-compare-deck deck-compare-${tone}`}>
      <span className="deck-compare-art">{side.art}</span>
      <span className="deck-compare-deck-text">
        <strong title={side.name}>{side.name}</strong>
        <small>{side.summary}</small>
        <span className="deck-compare-deck-meta"><ColorPips colors={side.colors} size={14} />{side.note ? <small>{side.note}</small> : null}</span>
        <DeckRecordBadge record={side.record} />
      </span>
    </div>
  );
}

function DiffColumn({ tone, deckName, otherName, cards, facts }: {
  tone: 'a' | 'b'; deckName: string; otherName: string; cards: ComparedCard[]; facts: Record<string, CardFacts>;
}) {
  const mine = (card: ComparedCard) => tone === 'a' ? card.a : card.b;
  const theirs = (card: ComparedCard) => tone === 'a' ? card.b : card.a;
  return (
    <div className={`deck-compare-column deck-compare-${tone}`}>
      <h5><span className="deck-compare-dot" aria-hidden="true" /><span className="deck-compare-column-name" title={deckName}>Only in <strong>{deckName}</strong></span></h5>
      {cards.length ? <ul aria-label={`Only in ${deckName}`}>{cards.map((card) => (
        <li key={card.name}>
          <span className="deck-compare-qty">+{mine(card) - theirs(card)}</span>
          <span className="deck-compare-name"><CardName name={card.name} /></span>
          {theirs(card) ? <small className="deck-compare-counts" title={`${mine(card)} in ${deckName}, ${theirs(card)} in ${otherName}`}>{mine(card)} vs {theirs(card)}</small> : null}
          <span className="deck-compare-cost"><Cost facts={facts[card.name]} /></span>
        </li>
      ))}</ul> : <p className="deck-compare-none">No extra cards</p>}
    </div>
  );
}

/** Body of the Compare dialog: two decks side by side, what differs, then what they share. */
export function DeckCompare({ sides, waiting }: { sides: [CompareSide, CompareSide]; waiting?: string }) {
  const [flipped, setFlipped] = useState(false);
  const first = useDeckCards(sides[0].source?.kind, sides[0].source?.id, sides[0].source?.version);
  const second = useDeckCards(sides[1].source?.kind, sides[1].source?.id, sides[1].source?.version);
  const [sideA, sideB] = flipped ? [sides[1], sides[0]] : sides;
  const [a, b] = flipped ? [second, first] : [first, second];
  const facts = { ...a?.facts, ...b?.facts };
  const result = a?.cards && b?.cards ? compareDecks(a.cards, b.cards, facts) : null;
  const missing = sides.filter((side) => !side.source);
  const error = a?.error ?? b?.error;
  const differing = result?.sections.filter((section) => section.onlyA.length || section.onlyB.length) ?? [];
  const percent = result?.similarity == null ? null
    : result.similarity < 1 ? Math.min(Math.round(result.similarity * 100), 99) : 100;

  return (
    <div className="deck-compare">
      <div className="deck-compare-hero">
        <DeckSide side={sideA} tone="a" />
        <div className="deck-compare-vs">
          <span aria-hidden="true">VS</span>
          <button type="button" className="deck-compare-swap" aria-label="Swap sides" title="Swap sides" onClick={() => setFlipped((value) => !value)}><ArrowLeftRight size={16} /></button>
        </div>
        <DeckSide side={sideB} tone="b" />
      </div>

      {!result ? (
        <p className="empty-state deck-compare-waiting" role={error ? 'alert' : 'status'}>
          {error ?? (missing.length ? waiting ?? `${missing.map((side) => side.name).join(' and ')} can’t be read right now.` : 'Loading both decks…')}
        </p>
      ) : <>
        <div className="deck-compare-meter">
          <div className="deck-compare-stat deck-compare-a"><strong>+{result.onlyA}</strong><span>only in {sideA.name}</span></div>
          <div className="deck-compare-stat deck-compare-match">
            <strong>{percent == null ? '—' : `${percent}%`}</strong>
            <span>main deck match · {result.shared} card{result.shared === 1 ? '' : 's'} in both</span>
          </div>
          <div className="deck-compare-stat deck-compare-b"><strong>+{result.onlyB}</strong><span>only in {sideB.name}</span></div>
          <div className="deck-compare-bar" role="img"
            aria-label={`${result.onlyA} only in ${sideA.name}, ${result.shared} in both, ${result.onlyB} only in ${sideB.name}`}>
            {result.onlyA ? <span className="deck-compare-bar-a" style={{ flexGrow: result.onlyA }} /> : null}
            {result.shared ? <span className="deck-compare-bar-shared" style={{ flexGrow: result.shared }} /> : null}
            {result.onlyB ? <span className="deck-compare-bar-b" style={{ flexGrow: result.onlyB }} /> : null}
          </div>
        </div>

        {result.identical ? (
          <div className="deck-compare-identical" role="status">
            <Check size={22} aria-hidden="true" />
            <span><strong>Same cards</strong>These two lists match card for card.</span>
          </div>
        ) : differing.map((section) => (
          <section key={section.section} className="deck-compare-section" aria-label={`${sectionLabel(section.section)} differences`}>
            <h4>{sectionLabel(section.section)}</h4>
            <div className="deck-compare-columns">
              <DiffColumn tone="a" deckName={sideA.name} otherName={sideB.name} cards={section.onlyA} facts={facts} />
              <DiffColumn tone="b" deckName={sideB.name} otherName={sideA.name} cards={section.onlyB} facts={facts} />
            </div>
          </section>
        ))}

        {result.shared ? (
          <details className="deck-compare-shared">
            <summary><ChevronDown size={16} aria-hidden="true" />Cards in both<span>{result.shared}</span></summary>
            <div className="deck-compare-shared-body">
              {result.sections.filter((section) => section.shared.length).map((section) => (
                <section key={section.section} className="deck-detail-section" aria-label={`${sectionLabel(section.section)} in both`}>
                  <h4>{sectionLabel(section.section)}<span>{section.shared.reduce((sum, card) => sum + Math.min(card.a, card.b), 0)}</span></h4>
                  <ul>{section.shared.map((card) => (
                    <li key={card.name}>
                      <span className="deck-detail-quantity">{Math.min(card.a, card.b)}</span>
                      <CardName name={card.name} />
                      <span className="deck-compare-cost"><Cost facts={facts[card.name]} /></span>
                    </li>
                  ))}</ul>
                </section>
              ))}
            </div>
          </details>
        ) : null}
      </>}
    </div>
  );
}
