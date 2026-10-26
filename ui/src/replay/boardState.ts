/**
 * Board-state shapes plus the copy-on-write draft the reducer mutates for one
 * event. A draft copies only the seat records, zone arrays and object entries
 * an event touches, so untouched substructures stay shared between states.
 */
import type { EffectWindow } from './effects';
import type { CardKey, ObjId, ReplayCard, ReplayEvent, StackItemKind, Zone } from './types';
import { ZONES } from './types';

export interface SeatState {
  /**
   * Materialized objects per zone, in order. Library and hand order is
   * top/oldest first. Hidden cards nobody has referenced yet are NOT objects:
   * they are counted in `hiddenLibrary` / `hiddenHand` and sit below (library)
   * or before (hand) the listed objects. This keeps a 100-card Brawl library
   * from costing 100 object entries per state.
   */
  zones: Readonly<Record<Zone, readonly ObjId[]>>;
  /** zones.hand.length + hiddenHand */
  handSize: number;
  /** zones.library.length + hiddenLibrary */
  librarySize: number;
  hiddenHand: number;
  hiddenLibrary: number;
}

export interface ObjectState {
  obj: ObjId;
  card: CardKey | null;
  owner: number;
  controller: number;
  zone: Zone;
  tapped: boolean;
  counters: Readonly<Record<string, number>>;
  power: number | null;
  toughness: number | null;
  attachedTo: ObjId | null;
  /** In exile: the permanent that exiled it (shown tucked under that host while it is on the battlefield). */
  exiledWith: ObjId | null;
  /** In exile: it came straight from the hand (a plotted card shows beside the hand). */
  fromHand: boolean;
  faceDown: boolean;
  inferred: boolean;
  /** seq at which the card identity became known; null while hidden. */
  revealedAt: number | null;
  /** On the battlefield: the basic land type it chose as it entered (Multiversal Passage). */
  chosen?: string;
}

export interface StackItem {
  stackId: string;
  obj: ObjId | null;
  card: CardKey | null;
  kind: StackItemKind;
  controller: number;
  text: string | null;
  targets: readonly ObjId[];
  pushedAt: number;
}

export interface BoardState {
  /** seq of the last applied event; -1 before any event. */
  seq: number;
  playerSeat: number;
  seats: Readonly<Record<number, SeatState>>;
  objects: ReadonlyMap<ObjId, ObjectState>;
  /** Bottom first; the last item is the top of the stack. */
  stack: readonly StackItem[];
  turn: number;
  activeSeat: number | null;
  phase: string | null;
  step: string | null;
  life: Readonly<Record<number, number>>;
  /** attacker -> the planeswalker or battle it attacks, null when it attacks a player */
  attackers: ReadonlyMap<ObjId, ObjId | null>;
  /**
   * What the current action did (effects.ts): damage, life, removal, counters
   * and P/T changes with their sources, shown on the table until the next action.
   */
  effects: EffectWindow;
  /** blocker -> attacker */
  blocks: ReadonlyMap<ObjId, ObjId>;
  lastEvent: ReplayEvent | null;
  winnerSeat: number | null;
  ended: boolean;
  /** Shared by every state of one stream (not copied per event). */
  cards: Readonly<Record<CardKey, ReplayCard>>;
  /** Recorded streams: obj -> card it is later revealed as. Shared, see buildTimeline. */
  hindsight: ReadonlyMap<ObjId, CardKey>;
  /** Commander card names per seat (Brawl/Commander), from the stream's seat info. Shared. */
  commanders: Readonly<Record<number, readonly string[]>>;
}

interface MutableSeat {
  zones: Record<Zone, ObjId[]>;
  hiddenHand: number;
  hiddenLibrary: number;
}

export function emptyZones(): Record<Zone, ObjId[]> {
  const zones = {} as Record<Zone, ObjId[]>;
  for (const zone of ZONES) {
    zones[zone] = [];
  }
  return zones;
}

export function emptySeat(): SeatState {
  return { zones: emptyZones(), handSize: 0, librarySize: 0, hiddenHand: 0, hiddenLibrary: 0 };
}

/** The seat whose zone list holds an object: controller on the battlefield, owner elsewhere. */
export function zoneSeatOf(object: ObjectState): number {
  return object.zone === 'battlefield' || object.zone === 'stack' ? object.controller : object.owner;
}

export class BoardDraft {
  readonly base: BoardState;
  private seatCopies = new Map<number, { seat: MutableSeat; copied: Set<Zone> }>();
  private objectsCopy: Map<ObjId, ObjectState> | null = null;
  private stackCopy: StackItem[] | null = null;
  private attackersCopy: Map<ObjId, ObjId | null> | null = null;
  private blocksCopy: Map<ObjId, ObjId> | null = null;
  private lifeCopy: Record<number, number> | null = null;
  readonly patch: Partial<BoardState> = {};

  constructor(base: BoardState) {
    this.base = base;
  }

  get(obj: ObjId): ObjectState | undefined {
    return (this.objectsCopy ?? this.base.objects).get(obj);
  }

  set(object: ObjectState): void {
    this.objectsCopy ??= new Map(this.base.objects);
    this.objectsCopy.set(object.obj, object);
  }

  update(obj: ObjId, changes: Partial<ObjectState>): void {
    const current = this.get(obj);
    if (current) {
      this.set({ ...current, ...changes });
    }
  }

  delete(obj: ObjId): void {
    this.objectsCopy ??= new Map(this.base.objects);
    this.objectsCopy.delete(obj);
  }

  seat(seatId: number): MutableSeat {
    let entry = this.seatCopies.get(seatId);
    if (!entry) {
      const source = this.base.seats[seatId] ?? emptySeat();
      const seat: MutableSeat = {
        zones: { ...source.zones } as Record<Zone, ObjId[]>,
        hiddenHand: source.hiddenHand,
        hiddenLibrary: source.hiddenLibrary,
      };
      entry = { seat, copied: new Set() };
      this.seatCopies.set(seatId, entry);
    }
    return entry.seat;
  }

  /** Mutable copy of one zone list (copied once per event). */
  zone(seatId: number, zone: Zone): ObjId[] {
    const seat = this.seat(seatId);
    const entry = this.seatCopies.get(seatId)!;
    if (!entry.copied.has(zone)) {
      seat.zones[zone] = seat.zones[zone].slice();
      entry.copied.add(zone);
    }
    return seat.zones[zone];
  }

  stack(): StackItem[] {
    this.stackCopy ??= this.base.stack.slice();
    return this.stackCopy;
  }

  attackers(): Map<ObjId, ObjId | null> {
    this.attackersCopy ??= new Map(this.base.attackers);
    return this.attackersCopy;
  }

  blocks(): Map<ObjId, ObjId> {
    this.blocksCopy ??= new Map(this.base.blocks);
    return this.blocksCopy;
  }

  life(): Record<number, number> {
    this.lifeCopy ??= { ...this.base.life };
    return this.lifeCopy;
  }

  finish(event: ReplayEvent): BoardState {
    const next: BoardState = { ...this.base, ...this.patch, seq: event.seq, lastEvent: event };
    if (this.seatCopies.size) {
      const seats: Record<number, SeatState> = { ...this.base.seats };
      for (const [seatId, { seat }] of this.seatCopies) {
        const hiddenHand = Math.max(0, seat.hiddenHand);
        const hiddenLibrary = Math.max(0, seat.hiddenLibrary);
        seats[seatId] = {
          zones: seat.zones,
          hiddenHand,
          hiddenLibrary,
          handSize: seat.zones.hand.length + hiddenHand,
          librarySize: seat.zones.library.length + hiddenLibrary,
        };
      }
      next.seats = seats;
    }
    if (this.objectsCopy) next.objects = this.objectsCopy;
    if (this.stackCopy) next.stack = this.stackCopy;
    if (this.attackersCopy) next.attackers = this.attackersCopy;
    if (this.blocksCopy) next.blocks = this.blocksCopy;
    if (this.lifeCopy) next.life = this.lifeCopy;
    return next;
  }
}

export function removeFrom(list: ObjId[], obj: ObjId): boolean {
  const index = list.lastIndexOf(obj);
  if (index < 0) {
    return false;
  }
  list.splice(index, 1);
  return true;
}
