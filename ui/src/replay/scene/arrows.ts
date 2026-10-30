/**
 * Targeting arrows (pure): which arrows a board state shows, their colors and
 * curve geometry. The SVG overlay draws them; the arrow projector moves their
 * endpoints on rendered frames without React (scene/projection.ts).
 */
import type { Layout } from '../layout';
import { parseHex } from '../materials';
import { SLEEVE_COLORS } from '../prefs';
import type { SleeveColor } from '../prefs';
import { shownExits } from '../effects';
import type { EffectSource, ObjectMarks } from '../effects';
import type { BoardState } from '../reducer';
import { seatNumber } from './labels';
import { RAIL_WIDTH } from './cameraFit';

/** Where an arrow starts or ends. */
export type ArrowEnd =
  /** The stack item's card in the DOM stack preview. */
  | { kind: 'stack'; stackId: string }
  /** A card mesh (its animated pose). */
  | { kind: 'obj'; obj: string }
  /** A player: the middle of that seat's table edge. */
  | { kind: 'seat'; seat: number };

/**
 * How loud an arrow is. Bright: `target` (a stack item's target, or an effect on
 * an opponent's permanent), `damage` (harm), `strike` (an attack on a
 * planeswalker or battle). Dim: `attack` (on a player; they come by the dozen),
 * `block`, and `support` (an effect on its own side's permanents, like a
 * trigger handing out counters).
 */
export type ArrowTone = 'target' | 'damage' | 'attack' | 'strike' | 'block' | 'support';

export interface SceneArrow {
  id: string;
  from: ArrowEnd;
  to: ArrowEnd;
  /** Acting seat: picks the sleeve color. */
  seat: number;
  tone: ArrowTone;
  /**
   * Another arrow joins the same two ends the other way (two creatures that
   * damaged each other): the pair bows to opposite sides in separate lanes.
   */
  paired?: boolean;
}

function endKey(end: ArrowEnd): string {
  return end.kind === 'obj' ? `o:${end.obj}` : end.kind === 'seat' ? `p:${end.seat}` : `s:${end.stackId}`;
}

/** Flags every arrow whose reverse (same ends, swapped) is also drawn. */
function markPairs(arrows: SceneArrow[]): void {
  const keys = new Set(arrows.map((arrow) => `${endKey(arrow.from)}>${endKey(arrow.to)}`));
  for (const arrow of arrows) {
    if (keys.has(`${endKey(arrow.to)}>${endKey(arrow.from)}`)) arrow.paired = true;
  }
}

/** Combat damage (and a death from it) already has its attack and block arrows. */
function combatOnly(marks: ObjectMarks): boolean {
  return marks.damage > 0 && marks.combat && (marks.removed === null || marks.removed === 'died') && !marks.pt && !Object.keys(marks.counters).length;
}

/**
 * The current action's effects (effects.ts): from each source to what it hit —
 * a permanent it damaged, removed or changed, a card it made its owner
 * discard, a player who lost life, a spell it countered. A source is drawn
 * from its permanent when that is on the table, else from its card in the
 * stack preview (live, or kept there as resolved/countered for the action).
 */
function effectArrows(state: BoardState, layout: Layout, placed: ReadonlySet<string>, arrows: SceneArrow[]): void {
  const effects = state.effects;
  const exits = new Set(shownExits(effects).map((exit) => exit.item.stackId));
  const live = new Set(state.stack.map((item) => item.stackId));
  const fromOf = (source: EffectSource | null): ArrowEnd | null => {
    if (!source) return null;
    if (source.obj && placed.has(source.obj)) return { kind: 'obj', obj: source.obj };
    if (source.stackId && (exits.has(source.stackId) || live.has(source.stackId))) return { kind: 'stack', stackId: source.stackId };
    // A spell acting while it is still on the stack: its card in the stack
    // preview, or (cast but not yet pushed, a cast trigger) its card in the
    // table's stack column.
    const spell = source.obj ? state.stack.find((item) => item.kind === 'spell' && item.obj === source.obj) : undefined;
    if (spell) return { kind: 'stack', stackId: spell.stackId };
    return source.obj && onStack.has(source.obj) ? { kind: 'obj', obj: source.obj } : null;
  };
  const onStack = new Set(layout.cards.filter((c) => c.row === 'stack').map((c) => c.obj));
  const discarded = new Set(layout.cards.filter((c) => c.removed === 'discarded').map((c) => c.obj));
  for (const [obj, marks] of effects.objects) {
    if (combatOnly(marks)) continue;
    if (!placed.has(obj) && !discarded.has(obj)) continue;
    const from = fromOf(marks.source);
    if (!from || (from.kind === 'obj' && from.obj === obj)) continue;
    const harmful = marks.removed !== null || marks.damage > 0 || (marks.pt !== null && marks.pt.power + marks.pt.toughness < 0);
    const seat = marks.source?.controller ?? state.playerSeat;
    // Something done to the acting seat's own permanents is context, not the headline.
    const own = state.objects.get(obj)?.controller === seat;
    arrows.push({
      id: `effect:${obj}`,
      from,
      to: { kind: 'obj', obj },
      seat,
      tone: harmful ? 'damage' : own ? 'support' : 'target',
    });
  }
  for (const [seat, marks] of effects.seats) {
    if (marks.damage > 0 && marks.combat) continue;
    if (seatNumber(marks)?.tone !== 'life-loss') continue;
    const from = fromOf(marks.source);
    if (!from) continue;
    arrows.push({ id: `effect-seat:${seat}`, from, to: { kind: 'seat', seat }, seat: marks.source?.controller ?? state.playerSeat, tone: 'damage' });
  }
  for (const exit of effects.exits) {
    if (exit.exit !== 'countered' || !exits.has(exit.item.stackId)) continue;
    const from = fromOf(exit.source);
    if (!from) continue;
    arrows.push({
      id: `countered:${exit.item.stackId}`,
      from,
      to: { kind: 'stack', stackId: exit.item.stackId },
      seat: exit.source?.controller ?? state.playerSeat,
      tone: 'damage',
    });
  }
}

/**
 * Arrows for one board state: every stack item to each of its targets
 * (bright, animated), the current action's effects from their sources, and during
 * combat attackers toward the planeswalker or battle they attack (else the
 * defending player) and blockers toward the
 * attacker they block (dimmer). Only ends the scene can place are kept.
 */
export function sceneArrows(state: BoardState, layout: Layout): SceneArrow[] {
  const placed = new Set<string>();
  for (const card of layout.cards) if (card.row !== 'pile' && card.row !== 'stack') placed.add(card.obj);
  const arrows: SceneArrow[] = [];
  for (const item of state.stack) {
    item.targets.forEach((obj) => {
      // A counterspell's target is a spell on the stack: aim at its preview card.
      const spell = state.stack.find((other) => other !== item && other.kind === 'spell' && other.obj === obj);
      const to: ArrowEnd | null = spell ? { kind: 'stack', stackId: spell.stackId } : placed.has(obj) ? { kind: 'obj', obj } : null;
      if (!to) return;
      arrows.push({
        id: `target:${item.stackId}:${obj}`,
        from: { kind: 'stack', stackId: item.stackId },
        to,
        seat: item.controller,
        tone: 'target',
      });
    });
  }
  effectArrows(state, layout, placed, arrows);
  if (state.attackers.size) {
    const blocked = new Set(state.blocks.values());
    const seats = Object.keys(state.seats).map(Number);
    for (const [obj, target] of state.attackers) {
      const attacker = state.objects.get(obj);
      if (!attacker || !placed.has(obj) || blocked.has(obj)) continue;
      const defender = seats.find((seat) => seat !== attacker.controller);
      if (defender === undefined) continue;
      arrows.push({
        id: `attack:${obj}`,
        from: { kind: 'obj', obj },
        to: target !== null && placed.has(target) ? { kind: 'obj', obj: target } : { kind: 'seat', seat: defender },
        seat: attacker.controller,
        tone: target !== null && placed.has(target) ? 'strike' : 'attack',
      });
    }
    for (const [blocker, attacker] of state.blocks) {
      const object = state.objects.get(blocker);
      if (!object || !placed.has(blocker) || !placed.has(attacker)) continue;
      arrows.push({
        id: `block:${blocker}:${attacker}`,
        from: { kind: 'obj', obj: blocker },
        to: { kind: 'obj', obj: attacker },
        seat: object.controller,
        tone: 'block',
      });
    }
  }
  markPairs(arrows);
  return arrows;
}

/** World point (table units) a player arrow aims at: the middle of that seat's rail. */
export function seatAnchor(
  layout: Pick<Layout, 'table'>,
  seat: number,
  playerSeat: number,
  out: { x: number; y: number; z: number } = { x: 0, y: 0, z: 0 },
): { x: number; y: number; z: number } {
  const y = layout.table.depth / 2 + RAIL_WIDTH / 2;
  out.x = 0;
  out.y = seat === playerSeat ? -y : y;
  out.z = 0.06;
  return out;
}

export interface NeonColors {
  /** Saturated halo color. */
  glow: string;
  /** Light core stroke. */
  core: string;
}

function hueOf([r, g, b]: [number, number, number]): number {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return 0;
  let h: number;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

function saturationOf([r, g, b]: [number, number, number]): number {
  const max = Math.max(r, g, b) / 255;
  const min = Math.min(r, g, b) / 255;
  const l = (max + min) / 2;
  return max === min ? 0 : (max - min) / (1 - Math.abs(2 * l - 1));
}

/**
 * Neon version of a sleeve's accent: same hue, pushed to a vivid halo and a
 * near-white core, so a navy sleeve glows blue and crimson glows red. Grey
 * sleeves (charcoal) stay neutral instead of picking up a random hue.
 */
export function neonColors(hex: string): NeonColors {
  const rgb = parseHex(hex);
  const hue = Math.round(hueOf(rgb));
  const grey = saturationOf(rgb) < 0.12;
  const sat = grey ? 0 : 92;
  return {
    glow: `hsl(${hue} ${sat}% 58%)`,
    core: `hsl(${hue} ${grey ? 0 : 100}% 86%)`,
  };
}

export function sleeveNeon(sleeve: SleeveColor): NeonColors {
  return neonColors(SLEEVE_COLORS[sleeve].accent);
}

export interface Point {
  x: number;
  y: number;
}

/**
 * Control point of the quadratic curve from (sx, sy) to (tx, ty): the
 * midpoint pushed sideways by `bend` × the chord length, always toward the
 * top of the screen (or to the left for a vertical chord, away from the stack
 * preview on the right edge) so arrows arc over the board instead of cutting
 * straight across it. With `ownSide`, the side follows the direction instead.
 */
export function arrowControlPoint(sx: number, sy: number, tx: number, ty: number, bend: number, out: Point, ownSide = false): Point {
  const dx = tx - sx;
  const dy = ty - sy;
  const length = Math.hypot(dx, dy);
  let nx = length ? dy / length : 0;
  let ny = length ? -dx / length : -1;
  // `ownSide` keeps the side the direction gives, so an arrow and its reverse
  // bow apart instead of sharing one curve.
  if (!ownSide && (ny > 0 || (ny === 0 && nx > 0))) {
    nx = -nx;
    ny = -ny;
  }
  out.x = (sx + tx) / 2 + nx * bend * length;
  out.y = (sy + ty) / 2 + ny * bend * length;
  return out;
}

/** Bend for a chord: gentle on long arrows, a little rounder on short ones. */
export function arrowBend(length: number): number {
  return length < 120 ? 0.32 : length > 600 ? 0.16 : 0.32 - ((length - 120) / 480) * 0.16;
}

export interface ArrowShape {
  /** SVG path data of the curve (ends at the arrowhead's base). */
  d: string;
  /** SVG polygon points of the arrowhead. */
  head: string;
}

const control: Point = { x: 0, y: 0 };

/**
 * Curve and arrowhead between two screen points (integers in CSS pixels).
 * The head points along the curve's tangent at the target; the curve stops
 * at the head's base so the stroke never pokes through the tip.
 */
export function arrowShape(sx: number, sy: number, tx: number, ty: number, headLength = 16, ownSide = false): ArrowShape {
  const length = Math.hypot(tx - sx, ty - sy);
  arrowControlPoint(sx, sy, tx, ty, arrowBend(length), control, ownSide);
  let ux = tx - control.x;
  let uy = ty - control.y;
  const tangent = Math.hypot(ux, uy) || 1;
  ux /= tangent;
  uy /= tangent;
  const head = Math.min(headLength, length * 0.4);
  const bx = tx - ux * head;
  const by = ty - uy * head;
  const half = head * 0.55;
  const r = (v: number) => Math.round(v * 10) / 10;
  return {
    d: `M${r(sx)} ${r(sy)} Q${r(control.x)} ${r(control.y)} ${r(bx)} ${r(by)}`,
    head: `${r(tx)},${r(ty)} ${r(bx - uy * half)},${r(by + ux * half)} ${r(bx + uy * half)},${r(by - ux * half)}`,
  };
}

/** How far apart (CSS pixels, each side of the chord) a paired arrow's ends sit. */
const PAIR_OFFSET = 14;
/**
 * Half-extents of the area around a card's centre the tip stays out of: the
 * damage pill sits just above the centre and a removal chip just below.
 */
const CLEAR_X = 56;
const CLEAR_Y = 50;

/**
 * Curve and arrowhead for one scene arrow between two screen points. A paired
 * arrow moves to its own lane (ends shifted to its side of the chord, bowing
 * that way). An arrow at a card stops short of the card's centre, so its head
 * lands beside the damage number instead of over it.
 */
export function sceneArrowShape(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  { paired = false, atCard = false }: { paired?: boolean; atCard?: boolean },
): ArrowShape {
  const length = Math.hypot(tx - sx, ty - sy);
  if (!length) return arrowShape(sx, sy, tx, ty);
  const ux = (tx - sx) / length;
  const uy = (ty - sy) / length;
  if (paired) {
    // The direction's own normal: the reverse arrow's points the other way.
    sx += uy * PAIR_OFFSET;
    sy -= ux * PAIR_OFFSET;
    tx += uy * PAIR_OFFSET;
    ty -= ux * PAIR_OFFSET;
  }
  if (atCard) {
    const clear = 1 / Math.hypot(ux / CLEAR_X, uy / CLEAR_Y);
    const back = Math.min(clear, length * 0.35);
    tx -= ux * back;
    ty -= uy * back;
  }
  return arrowShape(Math.round(sx), Math.round(sy), Math.round(tx), Math.round(ty), 16, paired);
}
