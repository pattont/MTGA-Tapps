/**
 * Arena-style stack preview: the stack as large card images in a column at
 * the right edge of the stage, top of the stack first. The newest item slides
 * in; an item that leaves the stack flashes (resolved) or is stamped
 * (countered, fizzled) on its way out. While playback is paused the leaving
 * item is held on screen with its stamp, so a viewer stepping one event at a
 * time can read it; it goes on the next step or seek, or once play resumes.
 * A DOM overlay over the canvas; only the
 * cards themselves take pointer events. Arrow sources are read from the card
 * nodes registered in `nodes` (keyed by stack id).
 *
 * The top card's size depends only on the stage height (CSS `--stack-w`), so
 * it never shrinks as the stack grows; the column is centered on the stage,
 * and the rows below the top card are as many as fit (`stackRows`), the rest
 * summarized as "+N more".
 */
import { memo, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { formatCardName } from '../../format';
import type { BoardState } from '../reducer';
import { STACK_KIND_LABELS, compactExits, effectExits, stackExit, stackRows, stackView } from '../scene/stackView';
import type { StackExit, StackViewItem } from '../scene/stackView';
import type { TextureStore } from '../scene/textureStore';
import type { CardKey } from '../types';
import { PreviewCard } from './CardPreview';

/** Exit animation length (CSS keeps in step); leaving cards are dropped after it. */
export const STACK_EXIT_MS = 420;
/** Height of the stack layer (the stage), or null before it is measured or without ResizeObserver. */
function useLayerHeight(node: HTMLElement | null): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    const layer = node?.parentElement;
    if (!layer || typeof ResizeObserver === 'undefined') return;
    const measure = () => setHeight(Math.round(layer.getBoundingClientRect().height) || null);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(layer);
    return () => observer.disconnect();
  }, [node]);
  return height;
}

interface Leaving extends StackViewItem {
  exit: StackExit;
}

const EXIT_LABELS: Record<StackExit, string> = { resolved: 'Resolved', countered: 'Countered', fizzled: 'Fizzled' };

export interface StackPreviewProps {
  state: BoardState;
  playerSeat: number;
  store: TextureStore;
  /** A seek jump: no enter/exit animations. */
  snap: boolean;
  /** Playback is running: leaving items animate out and are dropped. Paused, they are held. */
  playing: boolean;
  nodes: Map<string, HTMLElement>;
  onCardClick: (card: CardKey) => void;
}

function StackCard({
  item,
  compact,
  playerSeat,
  store,
  nodes,
  onCardClick,
  exit,
  effect = false,
}: {
  item: StackViewItem;
  compact: boolean;
  playerSeat: number;
  store: TextureStore;
  nodes: Map<string, HTMLElement> | null;
  onCardClick: (card: CardKey) => void;
  exit?: StackExit;
  /** Kept for the current action (its effects' arrows start here), not leaving. */
  effect?: boolean;
}) {
  const mine = item.controller === playerSeat;
  const name = formatCardName(item.name);
  const className = [
    'replay-stack-card',
    compact ? 'replay-stack-chip' : 'replay-stack-full',
    mine ? 'replay-stack-you' : 'replay-stack-opp',
    item.top && !exit ? 'replay-stack-top' : '',
    item.targeted && !exit ? 'replay-stack-targeted' : '',
    exit ? `${effect ? 'replay-stack-effect' : 'replay-stack-leaving'} replay-stack-${exit}` : '',
  ]
    .filter(Boolean)
    .join(' ');
  const card = item.card;
  return (
    <li
      className={className}
      data-stack-id={item.stackId}
      ref={
        nodes
          ? (node) => {
              if (!node) return undefined;
              nodes.set(item.stackId, node);
              return () => {
                if (nodes.get(item.stackId) === node) nodes.delete(item.stackId);
              };
            }
          : undefined
      }
      title={item.text ? `${name}: ${item.text}` : name}
      onClick={card ? () => onCardClick(card) : undefined}
    >
      <div className="card-preview-media replay-stack-media">
        <PreviewCard key={`${card ?? ''}|${item.name}`} store={store} card={card} name={item.name} />
      </div>
      <div className="replay-stack-caption">
        <strong>{name}</strong>
        <span className="replay-stack-kind">
          {mine ? 'You' : 'Opponent'} · {STACK_KIND_LABELS[item.kind]}
          {item.top && !exit ? ' · resolves next' : ''}
        </span>
        {item.text && !compact ? <span className="replay-stack-text">{item.text}</span> : null}
      </div>
      {exit ? <span className="replay-stack-stamp">{EXIT_LABELS[exit]}</span> : null}
    </li>
  );
}

function StackPreviewImpl({ state, playerSeat, store, snap, playing, nodes, onCardClick }: StackPreviewProps) {
  const items = useMemo(() => stackView(state), [state]);
  const effectItems = useMemo(() => effectExits(state), [state]);
  // Derived state: items that just left the stack keep animating for a moment.
  const [tracked, setTracked] = useState<{ items: StackViewItem[]; leaving: Leaving[] }>({ items, leaving: [] });
  if (tracked.items !== items) {
    const live = new Set(items.map((item) => item.stackId));
    const gone: Leaving[] = snap
      ? []
      : tracked.items
          .filter((item) => !live.has(item.stackId))
          .map((item) => ({ ...item, exit: stackExit(state, item.stackId) }));
    // Paused, a held item lasts only until the board changes again: the next
    // step shows just what that step took off the stack.
    const kept = playing ? tracked.leaving.filter((l) => !live.has(l.stackId)) : [];
    setTracked({ items, leaving: snap ? [] : [...kept, ...gone].slice(-2) });
  }
  // An item kept for the current action is drawn from the board state, not as a leaving card.
  const effectIds = new Set(effectItems.map((item) => item.stackId));
  const leaving = tracked.leaving.filter((item) => !effectIds.has(item.stackId));
  const held = !playing && leaving.length > 0;
  const anyLeaving = tracked.leaving.length > 0;
  useEffect(() => {
    // Paused: hold the leaving items (no timer); resuming play starts it.
    if (!anyLeaving || !playing) return;
    // A timer, not animationend: reduced motion turns the animation off.
    const timer = setTimeout(() => setTracked((t) => ({ ...t, leaving: [] })), STACK_EXIT_MS);
    return () => clearTimeout(timer);
  }, [tracked.leaving, anyLeaving, playing]);

  const [root, setRoot] = useState<HTMLDivElement | null>(null);
  const height = useLayerHeight(root);
  if (!items.length && !leaving.length && !effectItems.length) return null;
  const { full, chips } = stackRows(items.length, height);
  const hidden = items.length - full - chips;
  const exits: Leaving[] = [...effectItems, ...leaving];
  const exitCompact = compactExits(exits, stackRows(exits.length, height).full);
  const style = { '--stack-full': Math.max(1, full), '--stack-chips': chips } as CSSProperties;
  return (
    <div
      ref={setRoot}
      className={[
        'replay-stack-preview',
        snap ? 'replay-stack-snap' : '',
        items.length ? '' : 'replay-stack-empty',
        held ? 'replay-stack-held' : '',
        effectItems.length ? 'replay-stack-kept' : '',
        effectItems.length && items.length ? 'replay-stack-beside' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={style}
    >
      <ol className="replay-stack-list" aria-label="Stack">
        {items.slice(0, full + chips).map((item, i) => (
          <StackCard
            key={item.stackId}
            item={item}
            compact={i >= full}
            playerSeat={playerSeat}
            store={store}
            nodes={nodes}
            onCardClick={onCardClick}
          />
        ))}
        {hidden > 0 ? <li className="replay-stack-more">+{hidden} more on the stack</li> : null}
      </ol>
      {leaving.length || effectItems.length ? (
        <ol className="replay-stack-exits" aria-hidden="true">
          {effectItems.map((item, i) => (
            <StackCard
              key={`effect:${item.stackId}`}
              item={item}
              compact={exitCompact[i]}
              playerSeat={playerSeat}
              store={store}
              nodes={nodes}
              onCardClick={onCardClick}
              exit={item.exit}
              effect
            />
          ))}
          {leaving.map((item, i) => (
            <StackCard
              key={`exit:${item.stackId}`}
              item={item}
              compact={exitCompact[effectItems.length + i]}
              playerSeat={playerSeat}
              store={store}
              nodes={null}
              onCardClick={onCardClick}
              exit={item.exit}
            />
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export const StackPreview = memo(StackPreviewImpl);
