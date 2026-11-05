import type { CardFacts, ManagedCard } from '../deckManagerApi';
import { byManaValue, groupByType } from '../deckCardGroups';
import { CardLink } from './CardLink';
// The in-game overlay's symbols (shared with the Stream Kit), not the mana-font set.
import { ManaCost } from '../stream/widgets/ManaCost';

// The main deck gets the wide column; everything else stacks beside it.
const SIDE_SECTIONS = ['Commander', 'Companion', 'Sideboard', 'Maybeboard'];

const count = (cards: ManagedCard[]) => cards.reduce((sum, card) => sum + card.quantity, 0);

function CardRow({ card, facts }: { card: ManagedCard; facts?: CardFacts }) {
  return (
    <li className="deck-card-row">
      <span className="deck-detail-quantity">{card.quantity}</span>
      <span className="deck-card-name" title={card.name}>
        {card.name.startsWith('Card #') ? card.name : <CardLink cardName={card.name} returnHash="#/deck-manager" />}
      </span>
      {facts?.mana_cost ? <span className="deck-card-cost" aria-label={`Mana cost ${facts.mana_cost}`}><ManaCost cost={facts.mana_cost} /></span> : null}
    </li>
  );
}

function CardSection({ title, cards, facts, grouped }: { title: string; cards: ManagedCard[]; facts: Record<string, CardFacts>; grouped?: boolean }) {
  const groups = grouped ? groupByType(cards, facts) : null;
  return (
    <section className="deck-detail-section" aria-label={`${title} (${count(cards)})`}>
      <h4>{title}<span>{count(cards)}</span></h4>
      {groups ? (
        <div className="deck-card-groups">
          {groups.map(({ group, cards: members, count: total }) => (
            <ul key={group.type} className="deck-card-group" aria-label={`${group.label} (${total})`}>
              {/* The heading and first card stay together when the list breaks into columns. */}
              <li className="deck-card-group-heading" aria-hidden="true">
                <i className={`ms ms-${group.icon} type-chip-${group.type.toLowerCase()}`} />
                {group.label}<span>{total}</span>
              </li>
              {members.map((card, i) => <CardRow key={`${group.type}-${i}`} card={card} facts={facts[card.name]} />)}
            </ul>
          ))}
        </div>
      ) : (
        <ul>
          {(Object.keys(facts).length ? byManaValue(cards, facts) : cards).map((card, i) => <CardRow key={`${title}-${i}`} card={card} facts={facts[card.name]} />)}
        </ul>
      )}
    </section>
  );
}

/**
 * Main deck grouped by type in a wide column, with commander, companion and
 * sideboard beside it. Costs and types come from Arena's card DB (`card_info`).
 */
export function DeckCardLists({ cards, facts = {} }: { cards: ManagedCard[]; facts?: Record<string, CardFacts> }) {
  const main = cards.filter((card) => card.section === 'Deck');
  const side = SIDE_SECTIONS.map((section) => ({ section, cards: cards.filter((card) => card.section === section) }))
    .filter((group) => group.cards.length);
  return (
    <div className={`deck-detail-lists${side.length ? '' : ' deck-detail-lists-single'}`}>
      <CardSection title="Deck" cards={main} facts={facts} grouped />
      {side.length ? <div className="deck-detail-side">{side.map((group) => <CardSection key={group.section} title={group.section} cards={group.cards} facts={facts} />)}</div> : null}
    </div>
  );
}
