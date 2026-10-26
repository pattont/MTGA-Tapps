/**
 * Pure event reducer: one stream event -> the next board state. Re-exported by
 * reducer.ts, which adds the keyframed timeline.
 */
import { BoardDraft, emptySeat, removeFrom, zoneSeatOf } from './boardState';
import { EMPTY_EFFECTS, clearsEffects, isEmptyEffects, noteEffects } from './effects';
import type { BoardState, ObjectState, SeatState } from './boardState';
import type {
  CardKey,
  MoveEvent,
  MulliganEvent,
  ObjId,
  ReplayEvent,
  ReplayStream,
  ScryEvent,
} from './types';
import { stackKindOf } from './types';

const EMPTY_HINDSIGHT: ReadonlyMap<ObjId, CardKey> = new Map();

export function createInitialState(
  stream: ReplayStream,
  hindsight: ReadonlyMap<ObjId, CardKey> = EMPTY_HINDSIGHT,
): BoardState {
  const seats: Record<number, SeatState> = {};
  const life: Record<number, number> = {};
  const commanders: Record<number, readonly string[]> = {};
  for (const [key, seat] of Object.entries(stream.seats)) {
    const seatId = Number(key);
    seats[seatId] = emptySeat();
    life[seatId] = seat.starting_life;
    commanders[seatId] = seat.commanders ?? [];
  }
  return {
    seq: -1,
    playerSeat: stream.player_seat,
    seats,
    objects: new Map(),
    stack: [],
    turn: 0,
    activeSeat: null,
    phase: null,
    step: null,
    life,
    attackers: new Map(),
    effects: EMPTY_EFFECTS,
    blocks: new Map(),
    lastEvent: null,
    winnerSeat: null,
    ended: false,
    cards: stream.cards,
    hindsight,
    commanders,
  };
}

function isCombatPhase(phase: string | null): boolean {
  return phase !== null && phase.toLowerCase().includes('combat');
}

function clearCombat(draft: BoardDraft): void {
  if (draft.base.attackers.size) draft.patch.attackers = new Map();
  if (draft.base.blocks.size) draft.patch.blocks = new Map();
}

/** An unseen hidden card becomes an object: take it out of the hidden count. */
function consumeHidden(draft: BoardDraft, event: MoveEvent): void {
  const seat = draft.seat(event.owner);
  if (event.from === 'library') {
    // Before turn 1 the opening hand is already counted in hiddenHand (game_start
    // or a mulligan seeded it), so an opening-hand draw materializes one of those.
    if (event.to === 'hand' && draft.base.turn === 0 && seat.hiddenHand > 0) {
      seat.hiddenHand -= 1;
    } else {
      seat.hiddenLibrary -= 1;
    }
  } else if (event.from === 'hand') {
    seat.hiddenHand -= 1;
  }
}

function leaveBattlefield(draft: BoardDraft, obj: ObjId): void {
  if (draft.base.attackers.has(obj)) draft.attackers().delete(obj);
  for (const [blocker, attacker] of draft.base.blocks) {
    if (blocker === obj || attacker === obj) draft.blocks().delete(blocker);
  }
  for (const seatId of Object.keys(draft.base.seats)) {
    for (const other of draft.base.seats[Number(seatId)].zones.battlefield) {
      if (draft.get(other)?.attachedTo === obj) draft.update(other, { attachedTo: null });
    }
  }
}

function applyMove(draft: BoardDraft, event: MoveEvent): void {
  const prev = draft.get(event.obj);
  if (prev) {
    removeFrom(draft.zone(zoneSeatOf(prev), prev.zone), prev.obj);
  } else {
    consumeHidden(draft, event);
  }
  const stays = prev?.zone === 'battlefield' && event.to === 'battlefield';
  if (prev?.zone === 'battlefield' && !stays) {
    leaveBattlefield(draft, event.obj);
  }
  if (event.from === 'stack' && event.to !== 'stack') {
    const stack = draft.base.stack;
    const index = stack.findIndex((item) => item.kind === 'spell' && item.obj === event.obj);
    if (index >= 0) draft.stack().splice(index, 1);
  }
  const card = event.card ?? prev?.card ?? null;
  const chosen = event.to === 'battlefield' ? (event.chosen ?? (stays ? prev.chosen : undefined)) : undefined;
  const next: ObjectState = {
    obj: event.obj,
    card,
    owner: event.owner,
    controller: event.controller,
    zone: event.to,
    tapped: stays ? prev.tapped : false,
    counters: stays ? prev.counters : {},
    power: stays ? prev.power : null,
    toughness: stays ? prev.toughness : null,
    attachedTo: stays ? prev.attachedTo : null,
    exiledWith: event.to === 'exile' ? (event.with ?? null) : null,
    fromHand: event.to === 'exile' && event.from === 'hand',
    faceDown: stays ? prev.faceDown : false,
    // A token's creation is its real arrival, even after rows that named it first.
    inferred: event.inferred || (event.reason !== 'token_create' && (prev?.inferred ?? false)),
    revealedAt: prev?.revealedAt ?? (card ? event.seq : null),
    ...(chosen ? { chosen } : {}),
  };
  draft.set(next);
  const list = draft.zone(zoneSeatOf(next), event.to);
  const index = event.index;
  if (index !== null && index >= 0 && index < list.length) {
    list.splice(index, 0, event.obj);
  } else {
    list.push(event.obj);
  }
}

/**
 * Three producer shapes are accepted. A summary after the kept hand was dealt
 * (hand already at `to_size`, nothing bottomed) is a no-op. If a `bottomed` object is still in hand,
 * this is the keep step of a London mulligan: bottom those cards and keep the
 * rest. Otherwise the whole hand is shuffled away (identities forgotten) and
 * `to_size` hidden cards are dealt; opening-hand draws before turn 1 then
 * materialize them (see consumeHidden).
 */
function applyMulligan(draft: BoardDraft, event: MulliganEvent): void {
  const current = draft.base.seats[event.seat] ?? emptySeat();
  const bottomed = new Set(event.bottomed);
  const keepStep = current.zones.hand.some((obj) => bottomed.has(obj));
  // Producers also emit the mulligan as a summary after the kept hand was
  // already dealt (hand already at `to_size`): nothing left to change.
  if (!keepStep && current.zones.hand.length + current.hiddenHand === event.to_size) {
    return;
  }
  const hand = draft.zone(event.seat, 'hand');
  const library = draft.zone(event.seat, 'library');
  const seat = draft.seat(event.seat);
  const kept: ObjId[] = [];
  let returned = 0;
  for (const obj of hand) {
    if (bottomed.has(obj)) {
      library.push(obj);
      draft.update(obj, { zone: 'library' });
    } else if (keepStep) {
      kept.push(obj);
    } else {
      draft.delete(obj);
      returned += 1;
    }
  }
  hand.length = 0;
  hand.push(...kept);
  if (keepStep) {
    return;
  }
  seat.hiddenLibrary += returned + seat.hiddenHand;
  const dealt = Math.min(event.to_size, seat.hiddenLibrary);
  seat.hiddenLibrary -= dealt;
  seat.hiddenHand = dealt;
}

/** Library order: known top cards first, then hidden cards, bottom cards last. */
function applyScry(draft: BoardDraft, event: ScryEvent): void {
  const library = draft.zone(event.seat, 'library');
  const seat = draft.seat(event.seat);
  const ensure = (obj: ObjId): void => {
    if (draft.get(obj)) {
      removeFrom(library, obj);
      return;
    }
    seat.hiddenLibrary -= 1;
    draft.set({
      obj,
      card: null,
      owner: event.seat,
      controller: event.seat,
      zone: 'library',
      tapped: false,
      counters: {},
      power: null,
      toughness: null,
      attachedTo: null,
      exiledWith: null,
      fromHand: false,
      faceDown: false,
      inferred: false,
      revealedAt: null,
    });
  };
  event.top.forEach(ensure);
  event.bottom.forEach(ensure);
  library.unshift(...event.top);
  library.push(...event.bottom);
}

function applyShuffle(draft: BoardDraft, seatId: number): void {
  const library = draft.zone(seatId, 'library');
  for (const obj of library) draft.delete(obj);
  draft.seat(seatId).hiddenLibrary += library.length;
  library.length = 0;
}

function removeStackItem(draft: BoardDraft, stackId: string): void {
  const index = draft.base.stack.findLastIndex((item) => item.stackId === stackId);
  if (index >= 0) draft.stack().splice(index, 1);
}

export function applyEvent(state: BoardState, event: ReplayEvent): BoardState {
  const draft = new BoardDraft(state);
  // A new step (blockers declared, then combat damage) is a new action too, even
  // when no phase event marks it: the last resolution's effects end there.
  const newStep =
    (event.step != null && state.step != null && event.step !== state.step) ||
    (event.phase != null && state.phase != null && event.phase !== state.phase);
  // The next item resolving after the last one's effects are on the table is a
  // new action as well: otherwise both show as resolved at once (Belladonna
  // Took's second trigger beside the first, whose counters were still shown).
  const nextResolution =
    (event.kind === 'stack_resolve' || event.kind === 'stack_fizzle') &&
    (state.effects.objects.size > 0 || state.effects.seats.size > 0);
  if (!isEmptyEffects(state.effects) && (clearsEffects(event) || newStep || nextResolution)) {
    draft.patch.effects = EMPTY_EFFECTS;
  }
  noteEffects(draft, event);
  if (event.phase !== null && event.phase !== undefined) draft.patch.phase = event.phase;
  if (event.step !== null && event.step !== undefined) draft.patch.step = event.step;
  switch (event.kind) {
    case 'game_start':
      for (const [key, size] of Object.entries(event.seats_hand_sizes)) {
        draft.seat(Number(key)).hiddenHand = size;
      }
      for (const [key, size] of Object.entries(event.library_sizes)) {
        draft.seat(Number(key)).hiddenLibrary = size;
      }
      break;
    case 'turn':
      draft.patch.turn = event.turn;
      draft.patch.activeSeat = event.active_seat;
      draft.patch.phase = event.phase ?? null;
      draft.patch.step = event.step ?? null;
      clearCombat(draft);
      break;
    case 'phase':
      draft.patch.phase = event.phase ?? null;
      draft.patch.step = event.step ?? null;
      if (!isCombatPhase(event.phase ?? null)) clearCombat(draft);
      break;
    case 'life':
      draft.life()[event.seat] = event.life;
      break;
    case 'mulligan':
      applyMulligan(draft, event);
      break;
    case 'move':
      applyMove(draft, event);
      break;
    case 'tap':
    case 'untap': {
      const tapped = event.kind === 'tap';
      for (const obj of event.objs) {
        if (draft.get(obj) && draft.get(obj)?.tapped !== tapped) draft.update(obj, { tapped });
      }
      break;
    }
    case 'counter': {
      const current = draft.get(event.obj);
      if (!current) break;
      const counters = { ...current.counters };
      const total = event.total ?? (counters[event.type] ?? 0) + event.delta;
      if (total > 0) counters[event.type] = total;
      else delete counters[event.type];
      draft.update(event.obj, { counters });
      break;
    }
    case 'pt':
      draft.update(event.obj, { power: event.power, toughness: event.toughness });
      break;
    case 'attach':
      draft.update(event.obj, { attachedTo: event.to });
      break;
    case 'identity':
      draft.update(event.obj, {
        card: event.card,
        faceDown: event.face_down,
        revealedAt: draft.get(event.obj)?.revealedAt ?? event.seq,
      });
      break;
    case 'reveal':
      draft.update(event.obj, {
        card: event.card,
        revealedAt: draft.get(event.obj)?.revealedAt ?? event.seq,
      });
      break;
    case 'stack_push':
      draft.stack().push({
        stackId: event.stack_id,
        obj: event.obj,
        card: event.card ?? (event.obj ? (draft.get(event.obj)?.card ?? null) : null),
        kind: stackKindOf(event),
        controller: event.controller,
        text: event.text,
        targets: event.targets ?? [],
        pushedAt: event.seq,
      });
      break;
    case 'stack_resolve':
    case 'stack_fizzle':
    case 'stack_countered':
      removeStackItem(draft, event.stack_id);
      break;
    case 'attack': {
      const attackers = draft.attackers();
      for (const obj of event.objs) attackers.set(obj, event.target_obj ?? null);
      break;
    }
    case 'block': {
      const blocks = draft.blocks();
      for (const pair of event.pairs) blocks.set(pair.blocker, pair.attacker);
      break;
    }
    case 'scry':
      applyScry(draft, event);
      break;
    case 'shuffle':
      applyShuffle(draft, event.seat);
      break;
    case 'game_end':
      draft.patch.winnerSeat = event.winner_seat;
      draft.patch.ended = true;
      break;
    case 'damage':
      // Damage never changes life (life events carry totals); noteEffects marked what it hit.
      break;
    case 'note':
      break;
    default: {
      const unhandled: never = event;
      void unhandled;
    }
  }
  return draft.finish(event);
}
