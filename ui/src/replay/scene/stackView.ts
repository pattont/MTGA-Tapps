/** What the DOM stack preview shows for a board state (pure). */
import { shownExits } from '../effects';
import type { BoardState, StackItem } from '../reducer';
import type { CardKey, StackItemKind } from '../types';

export interface StackViewItem {
  stackId: string;
  /** Card whose image is shown (an ability shows its source card). */
  card: CardKey | null;
  name: string;
  kind: StackItemKind;
  /** Ability text (triggers and activated abilities); null for spells. */
  text: string | null;
  controller: number;
  /** True for the item that resolves next. */
  top: boolean;
  targets: number;
  /** Another stack item targets this one (a counterspell aimed at it). */
  targeted: boolean;
  /** How many identical abilities this card stands for (`groupStack`); 1 alone. */
  count: number;
  /** Their stack ids, this one first, plus any folded-in just-resolved copy: arrows may start at any of them. */
  stackIds: string[];
  /** Identical copies that just resolved, folded into this card (`foldResolved`). */
  resolved: number;
}

export type StackExit = 'resolved' | 'countered' | 'fizzled';

export const STACK_KIND_LABELS: Record<StackItemKind, string> = {
  spell: 'Spell',
  trigger: 'Triggered ability',
  activated: 'Activated ability',
};

function viewOf(state: BoardState, item: StackItem, top: boolean, targeted: boolean): StackViewItem {
  const source = item.obj ? state.objects.get(item.obj) : undefined;
  const card = item.card ?? (source && !source.faceDown ? source.card : null);
  return {
    stackId: item.stackId,
    card,
    name: (card && state.cards[card]?.name) || 'Unknown card',
    kind: item.kind,
    text: item.kind === 'spell' ? null : item.text,
    controller: item.controller,
    top,
    targets: item.targets.length,
    targeted,
    count: 1,
    stackIds: [item.stackId],
    resolved: 0,
  };
}

/**
 * What makes two abilities on the stack the same card to the viewer: same
 * kind, source card, text and controller, with no targets. Spells, targeted
 * abilities and anything a counterspell aims at always show on their own.
 */
function groupKey(item: StackViewItem): string | null {
  if (item.kind === 'spell' || item.targets > 0 || item.targeted) return null;
  return JSON.stringify([item.kind, item.card, item.name, item.text, item.controller]);
}

/**
 * Identical abilities next to each other on the stack (Belladonna Took
 * triggering once per token) show as one card with a count, top first.
 */
export function groupStack(items: readonly StackViewItem[]): StackViewItem[] {
  const out: StackViewItem[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    const key = groupKey(item);
    if (last && key !== null && groupKey(last) === key) {
      out[out.length - 1] = { ...last, count: last.count + 1, stackIds: [...last.stackIds, item.stackId] };
    } else {
      out.push(item);
    }
  }
  return out;
}

/**
 * A copy that just resolved, while identical ones still wait on the stack,
 * folds into their card (which notes it) instead of showing a third card;
 * its effect arrows start from that card. Other exits are returned as they are.
 */
export function foldResolved<T extends StackViewItem & { exit: StackExit }>(
  items: readonly StackViewItem[],
  exits: readonly T[],
): { items: StackViewItem[]; exits: T[] } {
  const out = items.slice();
  const kept: T[] = [];
  for (const exit of exits) {
    const key = exit.exit === 'resolved' ? groupKey(exit) : null;
    const index = key === null ? -1 : out.findIndex((item) => groupKey(item) === key);
    if (index < 0) {
      kept.push(exit);
      continue;
    }
    const group = out[index];
    out[index] = { ...group, resolved: group.resolved + 1, stackIds: [...group.stackIds, exit.stackId] };
  }
  return { items: out, exits: kept };
}

export interface EffectExitView extends StackViewItem {
  exit: StackExit;
}

/**
 * Items that left the stack in the current action and stay in the preview
 * while it lasts (effects.shownExits): a spell or ability that resolved with
 * an effect shown on the table (the arrows start from it), or one that was
 * countered or fizzled. Oldest first.
 */
export function effectExits(state: BoardState): EffectExitView[] {
  return shownExits(state.effects).map(({ item, exit }) => ({ ...viewOf(state, item, false, false), exit }));
}

/** Stack items, top of the stack first, identical neighbours grouped (`groupStack`). */
export function stackView(state: BoardState): StackViewItem[] {
  const items: StackViewItem[] = [];
  const n = state.stack.length;
  const targeted = new Set<string>();
  for (const item of state.stack) item.targets.forEach((obj) => targeted.add(obj));
  for (let i = n - 1; i >= 0; i -= 1) {
    const item = state.stack[i];
    items.push(viewOf(state, item, i === n - 1, item.kind === 'spell' && item.obj !== null && targeted.has(item.obj)));
  }
  return groupStack(items);
}

/** How an item that just left the stack left it (from the event that removed it). */
export function stackExit(state: BoardState, stackId: string): StackExit {
  const last = state.lastEvent;
  if (last?.kind === 'stack_countered' && last.stack_id === stackId) return 'countered';
  if (last?.kind === 'stack_fizzle' && last.stack_id === stackId) return 'fizzled';
  return 'resolved';
}

/** Below the full-size cards, the rest of a deep stack shows as compact rows. */
const MAX_FULL = 2;
const MAX_CHIPS = 6;
/*
 * Pixel geometry shared with replay.css: the layer's vertical padding, a
 * full card's caption and frame, a compact row, the list gap, and the card
 * width limits (width = (stage height − PAD − FULL_EXTRA − 2 rows) / 1.395).
 */
const LAYER_PAD = 20;
const FULL_EXTRA = 64;
const CHIP_ROW = 70;
const ROW_GAP = 8;
const MIN_W = 150;
const MAX_W = 240;
const CARD_RATIO = 1.395;

/** Card width the CSS gives the top card for a stage `height` px tall. */
export function stackCardWidth(height: number): number {
  return Math.min(MAX_W, Math.max(MIN_W, (height - LAYER_PAD - FULL_EXTRA - 2 * CHIP_ROW) / CARD_RATIO));
}

/**
 * How many stack items show in full and as compact rows for `count` items on
 * a stage `height` px tall (null: not measured yet, assume room). The top
 * card is always full size; a second full card only when two fit.
 */
export function stackRows(count: number, height: number | null): { full: number; chips: number } {
  if (!count) return { full: 0, chips: 0 };
  if (height === null) {
    const full = count <= MAX_FULL ? count : 1;
    return { full, chips: Math.min(count - full, MAX_CHIPS) };
  }
  const cardH = stackCardWidth(height) * CARD_RATIO + FULL_EXTRA;
  const available = height - LAYER_PAD;
  const twoFit = 2 * cardH + ROW_GAP <= available;
  const full = count <= MAX_FULL && twoFit ? count : 1;
  const left = available - full * cardH - (full - 1) * ROW_GAP;
  const chips = Math.max(0, Math.min(count - full, MAX_CHIPS, Math.floor((left - ROW_GAP) / (CHIP_ROW + ROW_GAP))));
  return { full, chips };
}

/**
 * Which cards that left the stack show as compact rows: when fewer than all
 * fit full size, a countered or fizzled spell keeps its full card first (it is
 * what the viewer needs to see), then the newest.
 */
export function compactExits(exits: readonly { exit: StackExit }[], full: number): boolean[] {
  const order = exits
    .map((item, i) => ({ i, rank: item.exit === 'resolved' ? 1 : 0 }))
    .sort((a, b) => a.rank - b.rank || b.i - a.i);
  const shown = new Set(order.slice(0, full).map((o) => o.i));
  return exits.map((_, i) => !shown.has(i));
}
