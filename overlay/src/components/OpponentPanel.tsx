import { Fragment } from 'preact';
import { useEffect, useMemo, useState } from 'preact/hooks';
import { shortFormat, typeClass } from '../model';
import { bandText, colorLetters, deckLine, groupSeen, nonlandSeen } from '../opponentModel';
import type { OpponentCard, OverlayOpponent, OverlayPayload, Settings } from '../types';
import { Chevron, Gear, Pin } from './Icons';
import { ManaCost } from './ManaCost';
import W from '../icons/W.svg';
import U from '../icons/U.svg';
import B from '../icons/B.svg';
import R from '../icons/R.svg';
import G from '../icons/G.svg';

const PIP_ICONS: Record<string, string> = { W, U, B, R, G };

interface Props {
  payload: OverlayPayload | null;
  opponent: OverlayOpponent | null;
  settings: Settings;
  pinned: boolean;
  dock: 'left' | 'right' | 'float';
  /** Card names played since the last update, highlighted for a moment. */
  fresh: Set<string>;
  onCollapse: () => void;
  onTogglePin: () => void;
  /** Opens the overlay's settings. Given only while the deck panel is off:
      with it on, the ⚙ is on the deck panel. */
  onOpenSettings?: () => void;
  onDragStart: (event: MouseEvent) => void;
  onHover: (card: OpponentCard | null, box: { top: number; bottom: number } | null) => void;
  /** Where the shell says the cursor is over the page (see Panel). */
  cursor: { x: number; y: number } | null;
}

/** Key of the folded Lands row: highlighted under the cursor, no hover card. */
const TOGGLE_LANDS = '\u0000lands';

/** A card row exactly like the deck panel's: name over cost, and the times
    played where the deck panel has copies left and odds. */
function CardRow({ card, hot, fresh, sub }: { card: OpponentCard; hot: boolean; fresh: boolean; sub?: boolean }) {
  return (
    <div class={`row${sub ? ' sub' : ''}${hot ? ' hot' : ''}${fresh ? ' fresh' : ''}`} data-key={card.name}>
      <span class="body">
        <span class={`nm ${typeClass(card.type)}`} title={card.name}>
          {card.name.split(' // ')[0]}
        </span>
        <ManaCost cost={card.mana_cost} />
      </span>
      <span class="right">
        <span class="cnt" aria-label={`Played ${card.count} time${card.count === 1 ? '' : 's'}`}>
          ×<b>{card.count}</b>
        </span>
      </span>
    </div>
  );
}

/** The header's second line, built like the deck panel's: the results
    screen, the format, then the opponent with your record against them. */
export function headLine(gameOver: boolean, format: string | null, name: string | null, h2h: { wins: number; losses: number } | null): string {
  let text = `${gameOver ? 'Game over · ' : ''}${shortFormat(format)}`;
  if (name) text += `${text ? ' · ' : ''}vs ${name}`;
  if (h2h) text += ` (${h2h.wins}–${h2h.losses})`;
  return text;
}

/** What the opponent is on, laid out like the deck panel: the deck name in
    the header, a band with where the name came from and three boxes (cards
    seen, lands played, your record against it), then every card they have
    played by type, lands folded into one row at the end. */
export function OpponentPanel(props: Props) {
  const { payload, opponent, pinned, dock, fresh, onCollapse, onTogglePin, onOpenSettings, onDragStart, onHover, cursor, settings } = props;
  const state = payload?.state ?? null;
  const cards = opponent?.seen ?? [];
  const { groups, lands } = useMemo(() => groupSeen(cards), [cards]);
  const pips = colorLetters(opponent?.colors);
  const line = deckLine(opponent);
  const band = bandText(opponent);
  const revealed = Boolean(opponent?.deck.label && opponent.deck.source !== 'none');
  const record = opponent?.record ?? null;
  const h2h = payload?.head_to_head ?? null;
  const landCount = opponent?.lands ?? lands.reduce((sum, card) => sum + card.count, 0);
  const [landsOpen, setLandsOpen] = useState(false);

  // The row under the shell-reported cursor: highlighted, and reported up
  // for the hover card. Only from the shell's cursor, never CSS :hover (see Panel).
  const [hotKey, setHotKey] = useState<string | null>(null);
  useEffect(() => {
    const byName = new Map(cards.map((card) => [card.name, card]));
    const hit = cursor && typeof document !== 'undefined' ? document.elementFromPoint(cursor.x, cursor.y) : null;
    const el = hit instanceof Element ? hit.closest<HTMLElement>('.list [data-key]') : null;
    const key = el?.dataset.key ?? null;
    const card = key ? byName.get(key) ?? null : null;
    setHotKey(key);
    if (card && el) {
      const rect = el.getBoundingClientRect();
      onHover(card, { top: rect.top, bottom: rect.bottom });
    } else {
      onHover(null, null);
    }
  }, [cursor, cards, onHover]);

  return (
    <div class={`panel opp density-${settings.density}`} role="group" aria-label="Opponent panel">
      <div class="head" onMouseDown={onDragStart}>
        <div class="deck">
          <b>
            {revealed ? line.name : 'Opponent'}
            {pips.length > 0 ? (
              <span class="pips">
                {pips.map((c) => (
                  <img key={c} src={PIP_ICONS[c]} alt={c} />
                ))}
              </span>
            ) : null}
          </b>
          <span>{headLine(state?.game_over ?? false, state?.format_label ?? null, state?.opponent_name ?? null, h2h)}</span>
        </div>
        <div class="ctl" onMouseDown={(event) => event.stopPropagation()}>
          <button type="button" onClick={onCollapse} title="Collapse to rail" aria-label="Collapse to rail">
            <Chevron dir={dock === 'left' ? 'left' : 'right'} />
          </button>
          <button type="button" class={pinned ? 'on' : ''} onClick={onTogglePin} title={pinned ? 'Pinned — stays open' : 'Unpinned — returns to the rail when idle'} aria-label="Pin">
            <Pin filled={pinned} />
          </button>
          {onOpenSettings ? (
            <button type="button" onClick={onOpenSettings} title="Settings" aria-label="Settings">
              <Gear />
            </button>
          ) : null}
        </div>
      </div>

      <div class="lands opp-band">
        <div class="t">
          {band.label}
          <small>{band.note}</small>
        </div>
        <div class="odd now" aria-label="Different nonland cards played">
          <small>SEEN</small>
          <b>{nonlandSeen(cards)}</b>
        </div>
        <div class="odd" aria-label="Lands played">
          <small>LANDS</small>
          <b>{landCount}</b>
        </div>
        <div class="odd you" aria-label={record ? `Your record against it: ${record.wins} wins, ${record.losses} losses` : 'No record against it yet'}>
          <small>YOU</small>
          <b>
            {record ? (
              <>
                <span class="w">{record.wins}</span>
                <span class="dash">–</span>
                <span class="l">{record.losses}</span>
              </>
            ) : (
              '—'
            )}
          </b>
        </div>
      </div>

      <div class="list">
        <div class={`list-body${groups.length === 0 && lands.length === 0 ? ' bare' : ''}`}>
          {groups.map((group) => (
            <Fragment key={group.key}>
              <div class="grp">
                {group.label} ({group.cards.reduce((sum, card) => sum + card.count, 0)})
              </div>
              {group.cards.map((card) => (
                <CardRow key={card.name} card={card} hot={hotKey === card.name} fresh={fresh.has(card.name)} />
              ))}
            </Fragment>
          ))}
          {lands.length > 0 ? (
            <>
              <button
                type="button"
                class={`row land-row${landsOpen ? ' open' : ''}${hotKey === TOGGLE_LANDS ? ' hot' : ''}`}
                data-key={TOGGLE_LANDS}
                onClick={() => setLandsOpen((v) => !v)}
                aria-expanded={landsOpen}
                aria-label={`Lands, ${landCount} played`}
              >
                <span class="body">
                  <span class="nm land">
                    Lands <Chevron dir={landsOpen ? 'down' : 'right'} />
                  </span>
                </span>
                <span class="right">
                  <span class="cnt">
                    ×<b>{landCount}</b>
                  </span>
                </span>
              </button>
              {landsOpen ? lands.map((card) => <CardRow key={card.name} card={card} hot={hotKey === card.name} fresh={fresh.has(card.name)} sub />) : null}
            </>
          ) : null}
          {groups.length === 0 && lands.length === 0 ? <div class="note">Nothing played yet</div> : null}
        </div>
      </div>
    </div>
  );
}
