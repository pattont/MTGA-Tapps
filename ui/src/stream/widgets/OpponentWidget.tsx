import { useEffect, useRef, useState } from 'react';
import type { LiveNow, LiveSeenCard } from '../../api';
import { ColorPips } from '../../components/ColorPips';
import { artCropUrl, groupSeen, opponentDeck, percent, rate, showsGame, typeClass } from '../liveView';
import { shows, type StreamOptions } from '../options';
import { useLiveSnapshot } from '../useLive';
import { AutoScroll } from './AutoScroll';
import { Brand } from './Brand';
import { ManaCost } from './ManaCost';

/** How long a newly played card stays highlighted. */
const FRESH_MS = 4000;

/** Card names whose play count went up since the last poll, for a short highlight. */
function useFresh(cards: LiveSeenCard[], gameId: string | null): Set<string> {
  const counts = useRef<{ game: string | null; seen: Map<string, number> } | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  useEffect(() => {
    const before = counts.current;
    const seen = new Map(cards.map((card) => [card.name, card.count]));
    counts.current = { game: gameId, seen };
    // The first look at a game is the game so far, not news.
    if (!before || before.game !== gameId) return undefined;
    const changed = cards.filter((card) => card.count > (before.seen.get(card.name) ?? 0)).map((card) => card.name);
    if (changed.length === 0) return undefined;
    setFresh(new Set(changed));
    const timer = window.setTimeout(() => setFresh(new Set()), FRESH_MS);
    return () => window.clearTimeout(timer);
  }, [cards, gameId]);
  return fresh;
}

function Art({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="op-art op-art-none" aria-hidden="true" />;
  return <img className="op-art" src={artCropUrl(name)} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

function CardLine({ card, art, fresh }: { card: LiveSeenCard; art: boolean; fresh: boolean }) {
  return (
    <li className={`op-card sk-type-${typeClass(card.type)}${fresh ? ' op-fresh' : ''}`}>
      {art ? <Art name={card.name} /> : null}
      <span className="op-name">{card.name.split(' // ')[0]}</span>
      <span className="op-cost">
        <ManaCost cost={card.mana_cost} />
      </span>
      <span className="op-count">{card.count > 1 ? `×${card.count}` : ''}</span>
    </li>
  );
}

export function OpponentView({ now, options, fresh }: { now: LiveNow; options: StreamOptions; fresh: Set<string> }) {
  const cards = now.opponent_seen ?? [];
  const { groups, lands } = groupSeen(cards);
  const guess = now.archetype_guess;
  const deck = opponentDeck(now);
  const name = options.opponent && now.opponent_name ? now.opponent_name : 'Opponent';
  const record = shows(options, 'record') && guess && guess.wins + guess.losses > 0 ? guess : null;
  const showLands = options.lands === 'all' ? lands : [];
  return (
    <div className="sk-panel op">
      <div className="op-head">
        <span className="sk-label">{name} is on</span>
        <Brand show={options.brand} />
      </div>
      <div className="op-deck">
        <span className="op-deck-name">{deck ?? 'Not revealed yet'}</span>
        <ColorPips colors={now.opponent_colors} size={16} />
      </div>
      {guess || record ? (
        <div className="op-guess">
          {guess && now.opponent_commanders.length === 0 ? <span>Likely · {guess.matched_cards} cards match</span> : null}
          {record ? (
            <span>
              You{' '}
              <span className="sk-win">{record.wins}</span>
              <span className="sk-dash">–</span>
              <span className="sk-loss">{record.losses}</span> vs it ({percent(rate(record.wins, record.losses))})
            </span>
          ) : null}
        </div>
      ) : null}
      {groups.length > 0 || showLands.length > 0 ? (
        <AutoScroll frameClassName="op-list-frame" className="op-list" label="Cards they’ve played">
          {groups.map((group) => (
            <section key={group.key} className="op-group">
              <div className="op-group-label">
                {group.label}
                <span>{group.cards.reduce((sum, card) => sum + card.count, 0)}</span>
              </div>
              <ul>
                {group.cards.map((card) => (
                  <CardLine key={card.name} card={card} art={shows(options, 'art')} fresh={fresh.has(card.name)} />
                ))}
              </ul>
            </section>
          ))}
          {showLands.length > 0 ? (
            <section className="op-group">
              <div className="op-group-label">
                Lands<span>{showLands.reduce((sum, card) => sum + card.count, 0)}</span>
              </div>
              <ul>
                {showLands.map((card) => (
                  <CardLine key={card.name} card={card} art={shows(options, 'art')} fresh={fresh.has(card.name)} />
                ))}
              </ul>
            </section>
          ) : null}
        </AutoScroll>
      ) : (
        <div className="op-empty">Nothing played yet</div>
      )}
      {options.lands !== 'all' && lands.length > 0 ? (
        <div className="op-lands">
          <span className="op-lands-label">Lands</span>
          <span className="op-lands-names">
            {lands.map((card) => (card.count > 1 ? `${card.name} ×${card.count}` : card.name)).join(' · ')}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** What they're on: up during a game (and between games with idle=show). */
export function OpponentWidget({ options }: { options: StreamOptions }) {
  const payload = useLiveSnapshot(options.demo);
  const now = payload?.tracker.state === 'offline' ? null : payload?.now;
  const fresh = useFresh(now?.opponent_seen ?? EMPTY, now?.game_id ?? null);
  if (!showsGame(now, options.idle)) return null;
  return <OpponentView now={now} options={options} fresh={fresh} />;
}

const EMPTY: LiveSeenCard[] = [];
