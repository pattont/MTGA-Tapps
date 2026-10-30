import { describe, expect, it } from 'vitest';
import { makeLongStream } from './fixtures/longStream';
import { StreamBuilder, card } from './fixtures/streamBuilder';
import { OPPONENT, PLAYER, makeSampleStream } from './fixtures/sampleStream';
import type { BoardState } from './reducer';
import { applyEvent, buildTimeline, createInitialState, stateAt, turnAtSeq } from './reducer';
import type { ReplayEvent, ReplayStream } from './types';

function reduceTo(stream: ReplayStream, seq: number): BoardState {
  let state = createInitialState(stream);
  for (const event of stream.events) {
    if (event.seq > seq) break;
    state = applyEvent(state, event);
  }
  return state;
}

function seqWhere(stream: ReplayStream, predicate: (event: ReplayEvent) => boolean): number {
  const event = stream.events.find(predicate);
  if (!event) throw new Error('event not found');
  return event.seq;
}

/** Comparable plain snapshot (Maps/Sets flattened, shared refs dropped). */
function snapshot(state: BoardState) {
  return {
    seq: state.seq,
    seats: state.seats,
    objects: [...state.objects.entries()].sort(([a], [b]) => (a < b ? -1 : 1)),
    stack: state.stack,
    turn: state.turn,
    activeSeat: state.activeSeat,
    phase: state.phase,
    life: state.life,
    attackers: [...state.attackers.keys()].sort(),
    blocks: [...state.blocks.entries()].sort(),
    winnerSeat: state.winnerSeat,
  };
}

describe('replay reducer', () => {
  const stream = makeSampleStream();

  it('seeds life from the stream seats and starts empty', () => {
    const state = createInitialState(stream);
    expect(state.life).toEqual({ 1: 20, 2: 20 });
    expect(state.objects.size).toBe(0);
    expect(state.playerSeat).toBe(PLAYER);
    expect(state.seq).toBe(-1);
  });

  it('handles opening hands and a mulligan without double-counting draws', () => {
    const state = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'turn') - 1);
    expect(state.seats[PLAYER].handSize).toBe(6);
    expect(state.seats[PLAYER].hiddenHand).toBe(0);
    expect(state.seats[PLAYER].librarySize).toBe(54);
    expect(state.seats[PLAYER].zones.hand).toEqual(['211', '212', '213', '214', '215', '216']);
    expect(state.objects.has('201')).toBe(false);
    expect(state.seats[OPPONENT].handSize).toBe(7);
    expect(state.objects.get('101')?.card).toBeNull();
    expect(state.seats[OPPONENT].librarySize).toBe(53);
  });

  it('keeps bottomed cards when a mulligan arrives after the new hand', () => {
    const base = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'turn') - 1);
    const keep: ReplayEvent = {
      ...stream.events[0],
      seq: 999,
      kind: 'mulligan',
      seat: PLAYER,
      from_size: 7,
      to_size: 5,
      bottomed: ['216'],
    };
    const next = applyEvent(base, keep);
    expect(next.seats[PLAYER].zones.hand).toEqual(['211', '212', '213', '214', '215']);
    expect(next.seats[PLAYER].zones.library).toEqual(['216']);
    expect(next.objects.get('216')?.zone).toBe('library');
    expect(next.seats[PLAYER].librarySize).toBe(55);
  });

  it('treats a mulligan summary after the kept hand as a no-op', () => {
    const base = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'turn') - 1);
    const summary: ReplayEvent = {
      ...stream.events[0],
      seq: 999,
      kind: 'mulligan',
      seat: PLAYER,
      from_size: 7,
      to_size: 6,
      bottomed: [],
    };
    const next = applyEvent(base, summary);
    expect(next.seats[PLAYER]).toBe(base.seats[PLAYER]);
    expect(next.objects.get('211')?.card).toBe('a1001');
  });

  it('unions one-attacker-per-event attacks within a combat', () => {
    const base = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'attack'));
    const second: ReplayEvent = {
      ...stream.events[0],
      seq: 999,
      phase: 'Phase_Combat',
      kind: 'attack',
      seat: PLAYER,
      objs: ['211'],
      target_seat: OPPONENT,
      target_obj: null,
    };
    const next = applyEvent(base, second);
    expect([...next.attackers.keys()].sort()).toEqual(['211', '215']);
  });

  it('counters a spell: Negate resolves first, Elves go to the graveyard', () => {
    const at = seqWhere(stream, (e) => e.kind === 'stack_push' && e.stack_id === 's2');
    const mid = reduceTo(stream, at);
    expect(mid.stack.map((item) => item.stackId)).toEqual(['s1', 's2']);
    expect(mid.stack[1].targets).toEqual(['212']);
    const after = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'stack_countered') + 1);
    expect(after.stack).toEqual([]);
    expect(after.seats[PLAYER].zones.graveyard).toEqual(['212']);
    expect(after.seats[OPPONENT].zones.graveyard).toEqual(['102']);
    expect(after.objects.get('102')?.card).toBe('a1008');
  });

  it('taps, untaps and clears tapped state when a permanent leaves', () => {
    const tapped = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'tap'));
    expect(tapped.objects.get('211')?.tapped).toBe(true);
    const untapped = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'untap' && e.objs[0] === '211'));
    expect(untapped.objects.get('211')?.tapped).toBe(false);
  });

  it('creates tokens from limbo with counters and modified P/T, then removes them', () => {
    const at = seqWhere(stream, (e) => e.kind === 'pt');
    const state = reduceTo(stream, at);
    const token = state.objects.get('tok1');
    expect(token).toMatchObject({ zone: 'battlefield', counters: { '+1/+1': 1 }, power: 2, toughness: 2 });
    expect(state.seats[PLAYER].zones.battlefield).toContain('tok1');
    const gone = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'move' && e.reason === 'token_cease'));
    expect(gone.objects.get('tok1')).toMatchObject({ zone: 'limbo', counters: {}, power: null });
    expect(gone.seats[PLAYER].zones.battlefield).not.toContain('tok1');
  });

  it('reveals hidden cards and fizzles a spell whose target left', () => {
    const revealed = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'reveal'));
    expect(revealed.objects.get('105')).toMatchObject({ card: 'a1004', zone: 'hand' });
    expect(revealed.objects.get('105')?.revealedAt).toBe(seqWhere(stream, (e) => e.kind === 'reveal'));
    const fizzled = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'stack_fizzle'));
    expect(fizzled.stack).toEqual([]);
  });

  it('marks attackers and blocks through combat and clears them after', () => {
    const blocked = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'block'));
    expect([...blocked.attackers.keys()]).toEqual(['215']);
    expect(blocked.blocks.get('104')).toBe('215');
    const transformed = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'identity'));
    expect(transformed.objects.get('215')?.card).toBe('a1011');
    const died = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'move' && e.reason === 'sba'));
    expect(died.blocks.size).toBe(0);
    expect(died.attackers.has('215')).toBe(true);
    const main2 = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'phase' && e.phase === 'Phase_Main2'));
    expect(main2.attackers.size).toBe(0);
  });

  it('orders scried cards and forgets library identities on shuffle', () => {
    const scried = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'scry'));
    expect(scried.seats[PLAYER].zones.library).toEqual(['230', '231']);
    expect(scried.seats[PLAYER].librarySize).toBe(52);
    const shuffled = reduceTo(stream, seqWhere(stream, (e) => e.kind === 'shuffle'));
    expect(shuffled.seats[PLAYER].zones.library).toEqual([]);
    expect(shuffled.seats[PLAYER].librarySize).toBe(52);
    expect(shuffled.objects.has('230')).toBe(false);
  });

  it('reaches the documented final position', () => {
    const final = reduceTo(stream, Infinity);
    expect(final.seats[PLAYER].zones.hand).toEqual(['213', '216', '217', '218']);
    expect(final.seats[PLAYER].zones.battlefield).toEqual(['211', '214', '215']);
    expect(final.seats[OPPONENT].zones.battlefield).toEqual(['101', '103', '106']);
    expect(final.seats[OPPONENT].zones.hand).toEqual(['107', '108']);
    expect(final.objects.get('106')).toMatchObject({ attachedTo: '215', controller: OPPONENT });
    expect(final.life).toEqual({ [OPPONENT]: 19, [PLAYER]: 18 });
    expect(final).toMatchObject({ turn: 5, activeSeat: OPPONENT, winnerSeat: PLAYER, ended: true });
  });

  it('never mutates the previous state and shares untouched structure', () => {
    const at = seqWhere(stream, (e) => e.kind === 'life');
    const before = reduceTo(stream, at - 1);
    const frozen = JSON.stringify(snapshot(before));
    const after = applyEvent(before, stream.events[at]);
    expect(JSON.stringify(snapshot(before))).toBe(frozen);
    expect(after).not.toBe(before);
    expect(after.objects).toBe(before.objects);
    expect(after.seats).toBe(before.seats);

    const tapAt = seqWhere(stream, (e) => e.kind === 'tap');
    const pre = reduceTo(stream, tapAt - 1);
    const post = applyEvent(pre, stream.events[tapAt]);
    expect(post.objects).not.toBe(pre.objects);
    expect(post.objects.get('101')).toBe(pre.objects.get('101'));
    expect(post.seats).toBe(pre.seats);
  });
});

describe('replay timeline', () => {
  it('keyframes every turn and seeks to the same state as a full replay', () => {
    const stream = makeSampleStream();
    const timeline = buildTimeline(stream);
    expect(timeline.keyframes.length).toBe(1 + stream.turns.length);
    expect(timeline.keyframes.map((k) => k.index)).toEqual([-1, ...stream.turns.map((t) => t.first_seq)]);
    for (const seq of [0, 5, 40, 17, 18, 19, 3, stream.events.length - 1, 25]) {
      expect(snapshot(stateAt(timeline, seq))).toEqual(snapshot(reduceTo(stream, seq)));
    }
    expect(stateAt(timeline, -5)).toBe(timeline.initial);
    expect(stateAt(timeline, 1e9).seq).toBe(timeline.final.seq);
  });

  it('memoizes the last seek so stepping forward applies one event', () => {
    const timeline = buildTimeline(makeSampleStream());
    const a = stateAt(timeline, 30);
    expect(stateAt(timeline, 30)).toBe(a);
    const b = stateAt(timeline, 31);
    expect(b.objects === a.objects || b.lastEvent === timeline.events[31]).toBe(true);
    expect(timeline.memo.index).toBe(31);
  });

  it('computes hindsight identities for recorded streams only', () => {
    const recorded = buildTimeline(makeSampleStream());
    expect(recorded.hindsight.get('102')).toBe('a1008');
    expect(recorded.hindsight.get('105')).toBe('a1004');
    expect(recorded.hindsight.has('107')).toBe(false);
    expect(stateAt(recorded, 20).hindsight).toBe(recorded.hindsight);
    const reconstructed = buildTimeline({ ...makeSampleStream(), fidelity: 'reconstructed' });
    expect(reconstructed.hindsight.size).toBe(0);
  });

  it('finds the turn containing a seq', () => {
    const stream = makeSampleStream();
    expect(turnAtSeq(stream.turns, 0)).toBeNull();
    expect(turnAtSeq(stream.turns, stream.turns[2].first_seq + 1)?.turn).toBe(3);
  });
});

describe('replay timeline performance', () => {
  // Best of three rounds, so a busy machine does not fail the budget.
  it('builds a 2,000-event timeline and seeks randomly within budget', () => {
    const stream = makeLongStream(40, 50);
    expect(stream.events.length).toBeGreaterThanOrEqual(2000);
    let built = Infinity;
    let seeks = Infinity;
    let timeline = buildTimeline(stream);
    for (let round = 0; round < 3; round += 1) {
      const started = performance.now();
      timeline = buildTimeline(stream);
      built = Math.min(built, performance.now() - started);

      let seed = 42 + round;
      const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
      const seekStart = performance.now();
      for (let i = 0; i < 1000; i += 1) {
        stateAt(timeline, Math.floor(next() * stream.events.length));
      }
      seeks = Math.min(seeks, performance.now() - seekStart);
    }
    console.info(
      `[replay perf] buildTimeline ${stream.events.length} events: ${built.toFixed(1)} ms; ` +
        `1000 random seeks: ${seeks.toFixed(1)} ms; keyframes ${timeline.keyframes.length}`,
    );
    expect(built).toBeLessThan(150);
    expect(seeks).toBeLessThan(1000);
  });

  it('keeps cold build and seek within budget too', () => {
    const stream = makeLongStream(40, 50, 99);
    const started = performance.now();
    const timeline = buildTimeline(stream);
    stateAt(timeline, Math.floor(stream.events.length / 2));
    expect(performance.now() - started).toBeLessThan(500);
  });
});

describe('token creation', () => {
  it("clears the inferred mark of a token that rows named before its creation", () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('310', null, 'limbo', 'battlefield', 1, 'unknown', { inferred: true });
    b.move('310', 'a1', 'battlefield', 'battlefield', 1, 'token_create');
    const warrior = card('Warrior', 'Creature', { is_token: true, power: '1', toughness: '1' });
    const final = buildTimeline(b.build({ a1: warrior }, { playerSeat: 1 })).final;
    expect(final.objects.get('310')).toMatchObject({ card: 'a1', inferred: false });
  });
});

describe('effect window', () => {
  it('closes when play moves to a new step, even without a phase event', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.turnStart(1, 1);
    b.move('src', 'a1', 'limbo', 'battlefield', 1, 'put');
    b.move('bear', 'a1', 'limbo', 'battlefield', 1, 'put');
    b.phaseTo('Phase_Combat', 'Step_DeclareBlock');
    b.add('stack_push', { stack_id: 's1', obj: 'src', card: 'a1', stack_kind: 'trigger', controller: 1, text: 'Counters', targets: [] });
    b.add('stack_resolve', { stack_id: 's1' });
    b.add('counter', { obj: 'bear', type: '+1/+1', delta: 1, total: 1 });
    const resolved = buildTimeline(b.build({ a1: card('Bear', 'Creature') }, { playerSeat: 1 })).final;
    expect(resolved.effects.exits).toHaveLength(1);
    // Combat damage carries its own step; the resolution's effects end there.
    const damage: ReplayEvent = {
      ...b.events[b.events.length - 1],
      seq: b.events.length,
      step: 'Step_CombatDamage',
      kind: 'damage',
      source: 'bear',
      target_obj: null,
      target_seat: 2,
      amount: 2,
      combat: true,
    } as ReplayEvent;
    const next = applyEvent(resolved, damage);
    expect(next.effects.exits).toHaveLength(0);
    expect(next.effects.objects.has('bear')).toBe(false);
  });
});
