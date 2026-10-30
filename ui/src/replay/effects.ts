/**
 * Effect window (docs/REPLAY_FORMAT.md §3): what the current action did to the
 * board, so the table can show it — damage and life at each seat, removal on
 * the permanents it hit, counters and power/toughness changes, discards and
 * mills, each with the source it came from.
 *
 * A window collects every effect from one action and stays open until the
 * next action (`clearsEffects`: a turn, phase, cast, ability, attack, block,
 * land, draw or the game's end; any event in a new step or phase; and an item
 * resolving once the previous one's effects are on the table). Its source is the stack item that resolved
 * last, kept after it left the stack; a damage or life event names its own
 * source when it knows it, and a removal move names its source in `by`
 * (recorded games) when Arena logged one. Removed permanents are held
 * (`held`) so the layout can keep them, dimmed, in their battlefield slot
 * until the window closes.
 */
import type { BoardDraft, ObjectState, StackItem } from './boardState';
import { zoneSeatOf } from './boardState';
import type { CardKey, MoveEvent, ObjId, ReplayEvent } from './types';

/** How a card left the battlefield (or the hand), as its chip names it. */
export type RemovalKind =
  | 'destroyed'
  | 'died'
  | 'exiled'
  | 'returned'
  | 'sacrificed'
  | 'graveyard'
  | 'library'
  | 'discarded';

/** Where an effect came from: a stack item (kept after it left the stack) or a permanent. */
export interface EffectSource {
  /** The stack item, when the effect came from one. */
  stackId: string | null;
  /** The source object: the spell itself, or the permanent an ability came from. */
  obj: ObjId | null;
  card: CardKey | null;
  controller: number;
  /** The stack item's targets (an effect on one of them is the targeted effect). */
  targets: readonly ObjId[];
}

export interface ObjectMarks {
  /** Damage dealt to it this window, summed. */
  damage: number;
  /** All of that damage was combat damage (combat already has attack/block arrows). */
  combat: boolean;
  removed: RemovalKind | null;
  /** Counters added (positive) or removed (negative) this window, per type; loyalty excluded. */
  counters: Readonly<Record<string, number>>;
  /** Net power/toughness change from an effect (not from counters), or null. */
  pt: { power: number; toughness: number } | null;
  /** Tapped by the resolving item's effect (it was one of its targets). */
  tapped: boolean;
  source: EffectSource | null;
}

export interface SeatMarks {
  /** Net life change this window (damage, drain, gain, paying life). */
  life: number;
  /** Damage dealt to the player this window, summed. */
  damage: number;
  /** Cards milled from this player's library this window. */
  milled: number;
  /** All of the damage was combat damage. */
  combat: boolean;
  source: EffectSource | null;
}

/** A permanent that left the battlefield this window, as it last stood there. */
export interface HeldCard {
  object: ObjectState;
  /** Battlefield seat (its controller) and its position in that seat's battlefield list. */
  seat: number;
  index: number;
}

export type StackExitKind = 'resolved' | 'countered' | 'fizzled';

/** A stack item that left the stack this window. */
export interface StackExitMark {
  item: StackItem;
  exit: StackExitKind;
  /** Countered: the item that countered it. */
  source: EffectSource | null;
}

export interface EffectWindow {
  /** The item that resolved last in this window (the default source of its effects). */
  source: EffectSource | null;
  objects: ReadonlyMap<ObjId, ObjectMarks>;
  seats: ReadonlyMap<number, SeatMarks>;
  held: ReadonlyMap<ObjId, HeldCard>;
  exits: readonly StackExitMark[];
}

export const EMPTY_EFFECTS: EffectWindow = Object.freeze({
  source: null,
  objects: new Map(),
  seats: new Map(),
  held: new Map(),
  exits: [],
}) as EffectWindow;

export function isEmptyEffects(window: EffectWindow): boolean {
  return (
    window.source === null &&
    window.objects.size === 0 &&
    window.seats.size === 0 &&
    window.held.size === 0 &&
    window.exits.length === 0
  );
}

/**
 * The next action after some effects: a new turn, phase, spell or ability,
 * attack, block, land, draw or cast. Damage, life changes and the deaths and
 * resolutions that follow it keep the window open.
 */
export function clearsEffects(event: ReplayEvent): boolean {
  switch (event.kind) {
    case 'turn':
    case 'phase':
    case 'stack_push':
    case 'attack':
    case 'block':
    case 'game_end':
      return true;
    case 'move':
      return event.reason === 'cast' || event.reason === 'play_land' || event.reason === 'draw';
    default:
      return false;
  }
}

/** Counter type recorded games use for planeswalker loyalty (its changes are costs, shown on the badge). */
const LOYALTY = 'loyalty';

const NO_COUNTERS: Readonly<Record<string, number>> = Object.freeze({});

function emptyObjectMarks(): ObjectMarks {
  return { damage: 0, combat: true, removed: null, counters: NO_COUNTERS, pt: null, tapped: false, source: null };
}

function emptySeatMarks(): SeatMarks {
  return { life: 0, damage: 0, milled: 0, combat: true, source: null };
}

function sourceOfItem(item: StackItem): EffectSource {
  return { stackId: item.stackId, obj: item.obj, card: item.card, controller: item.controller, targets: item.targets };
}

/** Copy-on-write editor for one event's changes to the window. */
class WindowDraft {
  private objects: Map<ObjId, ObjectMarks> | null = null;
  private seats: Map<number, SeatMarks> | null = null;
  private held: Map<ObjId, HeldCard> | null = null;
  private exits: StackExitMark[] | null = null;
  private source: EffectSource | null;
  private sourceChanged = false;

  readonly base: EffectWindow;

  constructor(base: EffectWindow) {
    this.base = base;
    this.source = base.source;
  }

  get current(): EffectSource | null {
    return this.source;
  }

  setSource(source: EffectSource): void {
    this.source = source;
    this.sourceChanged = true;
  }

  object(obj: ObjId): ObjectMarks | undefined {
    return (this.objects ?? this.base.objects).get(obj);
  }

  markObject(obj: ObjId, change: (marks: ObjectMarks) => ObjectMarks): void {
    this.objects ??= new Map(this.base.objects);
    this.objects.set(obj, change(this.objects.get(obj) ?? emptyObjectMarks()));
  }

  markSeat(seat: number, change: (marks: SeatMarks) => SeatMarks): void {
    this.seats ??= new Map(this.base.seats);
    this.seats.set(seat, change(this.seats.get(seat) ?? emptySeatMarks()));
  }

  hold(obj: ObjId, held: HeldCard): void {
    this.held ??= new Map(this.base.held);
    this.held.set(obj, held);
  }

  release(obj: ObjId): void {
    if (!(this.held ?? this.base.held).has(obj)) return;
    this.held ??= new Map(this.base.held);
    this.held.delete(obj);
  }

  exit(mark: StackExitMark): void {
    this.exits ??= this.base.exits.slice();
    this.exits.push(mark);
  }

  finish(): EffectWindow | null {
    if (!this.objects && !this.seats && !this.held && !this.exits && !this.sourceChanged) return null;
    return {
      source: this.source,
      objects: this.objects ?? this.base.objects,
      seats: this.seats ?? this.base.seats,
      held: this.held ?? this.base.held,
      exits: this.exits ?? this.base.exits,
    };
  }
}

/**
 * The source of an effect that names its source object: the window's item
 * when that object is the item's (Lightning Helix dealing its own damage,
 * after it left the stack), otherwise the object itself (a creature or a
 * permanent's ability).
 */
function sourceFor(window: WindowDraft, obj: ObjId | null | undefined, draft: BoardDraft): EffectSource | null {
  const current = window.current;
  if (!obj) return current;
  if (current && current.obj === obj) return current;
  const object = draft.get(obj);
  return { stackId: null, obj, card: object?.card ?? null, controller: object?.controller ?? current?.controller ?? 0, targets: [] };
}

function isCreatureOrPlaneswalker(draft: BoardDraft, object: ObjectState): boolean {
  if (object.power !== null || object.toughness !== null) return true;
  const card = object.card ? draft.base.cards[object.card] : undefined;
  const types = `${card?.primary_type ?? ''} ${card?.type_line ?? ''}`.toLowerCase();
  return types.includes('creature') || types.includes('planeswalker');
}

/** How a permanent leaving the battlefield by `event` is named on its chip; null when it is not a removal. */
export function removalKind(draft: BoardDraft, event: MoveEvent, prev: ObjectState): RemovalKind | null {
  switch (event.reason) {
    case 'destroy':
      return 'destroyed';
    case 'exile':
      return 'exiled';
    case 'bounce':
      return 'returned';
    case 'sacrifice':
      return 'sacrificed';
    case 'sba':
    case 'token_cease':
      return isCreatureOrPlaneswalker(draft, prev) ? 'died' : 'graveyard';
    case 'cast':
    case 'play_land':
    case 'resolve':
    case 'draw':
    case 'token_create':
      return null;
    default:
      break;
  }
  switch (event.to) {
    case 'hand':
      return 'returned';
    case 'exile':
      return 'exiled';
    case 'library':
      return 'library';
    case 'graveyard':
      return 'graveyard';
    default:
      return null;
  }
}

function noteMove(window: WindowDraft, draft: BoardDraft, event: MoveEvent): void {
  const prev = draft.get(event.obj);
  if (event.to === 'battlefield') {
    // Back on the battlefield in the same window (a flicker): nothing to hold.
    window.release(event.obj);
    return;
  }
  if (prev?.zone === 'battlefield') {
    const kind = removalKind(draft, event, prev);
    if (!kind) return;
    const marks = window.object(event.obj);
    let source: EffectSource | null;
    if (event.by) source = sourceFor(window, event.by, draft);
    else if (kind === 'died') source = marks?.source ?? window.current;
    // A sacrifice is a cost unless an opponent's effect made it (an edict).
    else if (kind === 'sacrificed') source = window.current && window.current.controller !== prev.controller ? window.current : null;
    else source = window.current;
    window.markObject(event.obj, (m) => ({ ...m, removed: kind, source: source ?? m.source }));
    const seat = zoneSeatOf(prev);
    const index = draft.base.seats[seat]?.zones.battlefield.indexOf(event.obj) ?? -1;
    window.hold(event.obj, { object: prev, seat, index: Math.max(0, index) });
    return;
  }
  if (event.reason === 'discard' && event.from === 'hand') {
    const source = event.by ? sourceFor(window, event.by, draft) : window.current;
    window.markObject(event.obj, (m) => ({ ...m, removed: 'discarded', source }));
    return;
  }
  if (event.reason === 'mill' && event.from === 'library') {
    window.markSeat(event.owner, (m) => ({ ...m, milled: m.milled + 1, source: m.source ?? window.current }));
  }
}

function noteDamage(window: WindowDraft, draft: BoardDraft, event: Extract<ReplayEvent, { kind: 'damage' }>): void {
  // Reconstructed games print combat damage to a creature as "X took N damage"
  // with no source: during combat, damage with no source is combat damage.
  const combat = event.combat || (event.source === null && draft.base.attackers.size > 0);
  const source = combat && !event.source ? null : sourceFor(window, event.source, draft);
  if (event.target_obj) {
    window.markObject(event.target_obj, (m) => ({
      ...m,
      damage: m.damage + event.amount,
      combat: m.combat && combat,
      source: source ?? m.source,
    }));
  } else if (event.target_seat !== null) {
    window.markSeat(event.target_seat, (m) => ({
      ...m,
      damage: m.damage + event.amount,
      combat: m.combat && combat,
      source: source ?? m.source,
    }));
  }
}

function notePt(window: WindowDraft, draft: BoardDraft, event: Extract<ReplayEvent, { kind: 'pt' }>): void {
  const current = window.current;
  // Only an effect of a resolving item: a creature entering or an end-of-turn reset is not one.
  if (!current || current.stackId === null || current.obj === event.obj) return;
  const prev = draft.get(event.obj);
  if (!prev || prev.zone !== 'battlefield' || prev.power === null || prev.toughness === null) return;
  if (event.power === null || event.toughness === null) return;
  const marks = window.object(event.obj);
  if (marks && Object.keys(marks.counters).length) return;
  const power = event.power - prev.power;
  const toughness = event.toughness - prev.toughness;
  if (!power && !toughness) return;
  window.markObject(event.obj, (m) => {
    const pt = { power: (m.pt?.power ?? 0) + power, toughness: (m.pt?.toughness ?? 0) + toughness };
    return { ...m, pt: pt.power || pt.toughness ? pt : null, source: m.source ?? current };
  });
}

/**
 * Records `event`'s effects into the draft's window. Called before the event
 * changes the board, so the draft still shows the objects as they were.
 */
export function noteEffects(draft: BoardDraft, event: ReplayEvent): void {
  const base = draft.patch.effects ?? draft.base.effects;
  const window = new WindowDraft(base);
  switch (event.kind) {
    case 'stack_resolve': {
      const item = draft.base.stack.find((i) => i.stackId === event.stack_id);
      if (!item) break;
      window.setSource(sourceOfItem(item));
      window.exit({ item, exit: 'resolved', source: null });
      break;
    }
    case 'stack_fizzle': {
      const item = draft.base.stack.find((i) => i.stackId === event.stack_id);
      if (item) window.exit({ item, exit: 'fizzled', source: null });
      break;
    }
    case 'stack_countered': {
      const item = draft.base.stack.find((i) => i.stackId === event.stack_id);
      if (!item) break;
      // The counterspell is the item aimed at this one (still on the stack, or resolving).
      const counter = draft.base.stack.find((other) => other !== item && item.obj !== null && other.targets.includes(item.obj));
      window.exit({ item, exit: 'countered', source: counter ? sourceOfItem(counter) : window.current });
      break;
    }
    case 'damage':
      noteDamage(window, draft, event);
      break;
    case 'life': {
      const source = sourceFor(window, event.source_obj, draft);
      window.markSeat(event.seat, (m) => ({ ...m, life: m.life + event.delta, source: m.source ?? source }));
      break;
    }
    case 'move':
      noteMove(window, draft, event);
      break;
    case 'counter': {
      if (event.type === LOYALTY || !event.delta) break;
      const object = draft.get(event.obj);
      if (!object || object.zone !== 'battlefield') break;
      const source = window.current;
      window.markObject(event.obj, (m) => {
        const counters = { ...m.counters, [event.type]: (m.counters[event.type] ?? 0) + event.delta };
        if (!counters[event.type]) delete counters[event.type];
        return { ...m, counters, pt: null, source: m.source ?? source };
      });
      break;
    }
    case 'pt':
      notePt(window, draft, event);
      break;
    case 'tap': {
      const current = window.current;
      if (!current || current.stackId === null) break;
      for (const obj of event.objs) {
        if (current.targets.includes(obj) && draft.get(obj)?.tapped === false) {
          window.markObject(obj, (m) => ({ ...m, tapped: true, source: m.source ?? current }));
        }
      }
      break;
    }
    default:
      break;
  }
  const next = window.finish();
  if (next) draft.patch.effects = next;
}

/** Stack items whose exit the stack preview keeps showing: countered, fizzled, or resolved with a visible effect. */
export function shownExits(window: EffectWindow): StackExitMark[] {
  const used = new Set<string>();
  const note = (source: EffectSource | null) => {
    if (source?.stackId) used.add(source.stackId);
  };
  for (const marks of window.objects.values()) if (!(marks.combat && marks.damage && !marks.removed)) note(marks.source);
  for (const marks of window.seats.values()) note(marks.source);
  for (const exit of window.exits) note(exit.source);
  const shown = window.exits.filter((exit) => exit.exit !== 'resolved' || used.has(exit.item.stackId));
  // Newest last; the preview keeps room for two.
  return shown.slice(-2);
}
