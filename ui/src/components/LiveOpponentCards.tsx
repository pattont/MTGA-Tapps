import type { LiveSeenCard } from '../api';
import { groupSeen } from '../stream/liveView';
import { CardLink } from './CardLink';
import { ManaCost } from './ManaCost';

const times = (card: LiveSeenCard) => (card.count > 1 ? `${card.count}× ` : '');

/**
 * Every card the opponent has played this game, by type and mana value, with
 * lands on one line. Sits in the rail beside the feed, so nobody has to read
 * their deck out of the log.
 */
export function LiveOpponentCards({ cards }: { cards: LiveSeenCard[] }) {
  const { groups, lands } = groupSeen(cards);
  const played = cards.reduce((total, card) => total + card.count, 0);
  return (
    <section className="dashboard-section live-opp-cards">
      <div className="section-heading">
        <h3>Opponent's Cards</h3>
        <span className="live-opp-count">{played} played</span>
      </div>
      <div className="live-opp-list">
        {groups.map((group) => (
          <div key={group.key} className="live-opp-group">
            <h4>{group.label}</h4>
            <ul>
              {group.cards.map((card) => (
                <li key={card.name}>
                  <span className="live-opp-name">
                    {times(card)}
                    <CardLink cardName={card.name} returnHash="#/live">
                      {card.name}
                    </CardLink>
                  </span>
                  {card.mana_cost ? <ManaCost info={{ mana_cost: card.mana_cost, cmc: card.mana_value ?? 0 }} /> : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {lands.length > 0 ? (
          <div className="live-opp-group">
            <h4>Lands</h4>
            <p className="live-opp-lands">
              {lands.map((card, index) => (
                <span key={card.name}>
                  {index > 0 ? ', ' : ''}
                  {times(card)}
                  <CardLink cardName={card.name} returnHash="#/live">
                    {card.name}
                  </CardLink>
                </span>
              ))}
            </p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
