import { describe, expect, it } from 'vitest';
import { OPPONENT, PLAYER, makeSampleStream } from '../fixtures/sampleStream';
import { StreamBuilder, card } from '../fixtures/streamBuilder';
import { makeTokenStream } from '../fixtures/tokenStream';
import { layoutBoard } from '../layout';
import { SLEEVE_COLORS } from '../prefs';
import { buildTimeline, stateAt } from '../reducer';
import type { ReplayEvent } from '../types';
import { arrowBend, arrowControlPoint, arrowShape, neonColors, sceneArrowShape, sceneArrows, seatAnchor, sleeveNeon } from './arrows';
import { foldResolved, groupStack, stackExit, stackView } from './stackView';
import type { StackViewItem } from './stackView';

const stream = makeSampleStream();
const timeline = buildTimeline(stream);
const OPTS = { mirrorOpponent: false, hindsight: true, playerSeat: PLAYER };

function at(predicate: (event: ReplayEvent) => boolean) {
  const event = stream.events.find(predicate);
  if (!event) throw new Error('missing event');
  const state = stateAt(timeline, event.seq);
  return { state, layout: layoutBoard(state, OPTS) };
}

function hue(color: string): number {
  return Number(/hsl\((\d+)/.exec(color)?.[1]);
}

describe('scene arrows', () => {
  it("points a removal spell from its stack card to the targeted permanent, in the caster's color", () => {
    const { state, layout } = at((e) => e.kind === 'stack_push' && e.stack_id === 's6');
    expect(sceneArrows(state, layout)).toEqual([
      { id: 'target:s6:tok1', from: { kind: 'stack', stackId: 's6' }, to: { kind: 'obj', obj: 'tok1' }, seat: OPPONENT, tone: 'target' },
    ]);
  });

  it('points a counterspell at the spell it targets on the stack', () => {
    const { state, layout } = at((e) => e.kind === 'stack_push' && e.stack_id === 's2');
    expect(sceneArrows(state, layout)).toEqual([
      { id: 'target:s2:212', from: { kind: 'stack', stackId: 's2' }, to: { kind: 'stack', stackId: 's1' }, seat: OPPONENT, tone: 'target' },
    ]);
    expect(stackView(state).find((item) => item.stackId === 's1')?.targeted).toBe(true);
  });

  it('draws attackers toward the defending player and blockers toward their attacker', () => {
    const attack = at((e) => e.kind === 'attack');
    expect(sceneArrows(attack.state, attack.layout)).toEqual([
      { id: 'attack:215', from: { kind: 'obj', obj: '215' }, to: { kind: 'seat', seat: OPPONENT }, seat: PLAYER, tone: 'attack' },
    ]);
    const block = at((e) => e.kind === 'block');
    expect(sceneArrows(block.state, block.layout)).toEqual([
      { id: 'block:104:215', from: { kind: 'obj', obj: '104' }, to: { kind: 'obj', obj: '215' }, seat: OPPONENT, tone: 'block' },
    ]);
  });

  it('shows non-combat damage from a permanent to a player for the action, and nothing after the next one', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('p1', 'a1', 'limbo', 'battlefield', 1, 'put');
    b.add('damage', { source: 'p1', target_obj: null, target_seat: 2, amount: 1, combat: false });
    b.add('note', {}, { text: 'later' });
    b.phaseTo('Phase_Combat');
    const built = b.build({ a1: card('Pinger', 'Creature', { power: '1', toughness: '1' }) }, { playerSeat: 1 });
    const tl = buildTimeline(built);
    const damage = built.events.find((e) => e.kind === 'damage')!;
    const expected = [{ id: 'effect-seat:2', from: { kind: 'obj', obj: 'p1' }, to: { kind: 'seat', seat: 2 }, seat: 1, tone: 'damage' }];
    const state = stateAt(tl, damage.seq);
    expect(sceneArrows(state, layoutBoard(state, { ...OPTS, playerSeat: 1 }))).toEqual(expected);
    // A note is not an action: the damage stays shown.
    const noted = stateAt(tl, damage.seq + 1);
    expect(sceneArrows(noted, layoutBoard(noted, { ...OPTS, playerSeat: 1 }))).toEqual(expected);
    const quiet = tl.final;
    expect(sceneArrows(quiet, layoutBoard(quiet, { ...OPTS, playerSeat: 1 }))).toEqual([]);
  });

  it("aims player arrows at the middle of that seat's rail", () => {
    const { layout } = at((e) => e.kind === 'attack');
    const mine = seatAnchor(layout, PLAYER, PLAYER);
    const theirs = seatAnchor(layout, OPPONENT, PLAYER);
    expect(mine.x).toBe(0);
    expect(mine.y).toBeLessThan(-layout.table.depth / 2);
    expect(theirs.y).toBe(-mine.y);
  });

  it('pairs the two arrows of creatures that damaged each other, so each keeps its own lane', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('p1', 'a1', 'limbo', 'battlefield', 1, 'put');
    b.move('o1', 'a2', 'limbo', 'battlefield', 2, 'put');
    b.add('damage', { source: 'p1', target_obj: 'o1', target_seat: null, amount: 1, combat: false });
    b.add('damage', { source: 'o1', target_obj: 'p1', target_seat: null, amount: 1, combat: false });
    const built = b.build({
      a1: card('Simulacrum Shaper', 'Creature', { power: '2', toughness: '2' }),
      a2: card('Freya Crescent', 'Creature', { power: '1', toughness: '1' }),
    }, { playerSeat: 1 });
    const state = buildTimeline(built).final;
    const arrows = sceneArrows(state, layoutBoard(state, { ...OPTS, playerSeat: 1 }));
    expect(arrows.map((arrow) => [arrow.id, arrow.seat, arrow.paired])).toEqual([
      ['effect:o1', 1, true],
      ['effect:p1', 2, true],
    ]);
  });
});

describe('arrow colors', () => {
  it('turns sleeve accents into neon: navy glows blue, crimson glows red', () => {
    const navy = sleeveNeon('navy');
    const crimson = sleeveNeon('crimson');
    expect(hue(navy.glow)).toBeGreaterThan(200);
    expect(hue(navy.glow)).toBeLessThan(240);
    expect(hue(crimson.glow) > 330 || hue(crimson.glow) < 10).toBe(true);
    expect(navy.glow).toMatch(/^hsl\(\d+ 92% 58%\)$/);
    expect(navy.core).toMatch(/^hsl\(\d+ 100% 86%\)$/);
    expect(neonColors(SLEEVE_COLORS.navy.accent)).toEqual(navy);
    // Grey sleeves stay neutral instead of picking up a random hue.
    expect(neonColors('#55595f').glow).toMatch(/ 0% 58%\)$/);
  });
});

describe('arrow geometry', () => {
  it('bends the curve toward the top of the screen, or to the left for a vertical chord', () => {
    const p = { x: 0, y: 0 };
    arrowControlPoint(0, 100, 200, 100, 0.25, p);
    expect(p).toEqual({ x: 100, y: 50 });
    // Same bulge whichever way the arrow travels.
    arrowControlPoint(200, 100, 0, 100, 0.25, p);
    expect(p).toEqual({ x: 100, y: 50 });
    arrowControlPoint(300, 0, 300, 200, 0.25, p);
    expect(p.x).toBeLessThan(300);
    expect(p.y).toBeCloseTo(100);
    // A diagonal arrow still arcs upward.
    arrowControlPoint(0, 300, 300, 0, 0.25, p);
    expect(p.y).toBeLessThan(150);
  });

  it('bends short arrows more than long ones', () => {
    expect(arrowBend(60)).toBeGreaterThan(arrowBend(400));
    expect(arrowBend(400)).toBeGreaterThan(arrowBend(900) - 1e-9);
  });

  it('puts an arrow and its reverse in separate lanes, bowing apart', () => {
    const down = sceneArrowShape(300, 100, 300, 500, { paired: true });
    const up = sceneArrowShape(300, 500, 300, 100, { paired: true });
    const start = (d: string) => d.split(/[MQ ]+/).filter(Boolean).map(Number);
    const [dsx, , dcx] = start(down.d);
    const [usx, , ucx] = start(up.d);
    // Ends sit on opposite sides of the chord, and the curves bow away from each other.
    expect(Math.sign(dsx - 300)).toBe(-Math.sign(usx - 300));
    expect(Math.sign(dcx - 300)).toBe(Math.sign(dsx - 300));
    expect(Math.sign(ucx - 300)).toBe(Math.sign(usx - 300));
    expect(Math.abs(dcx - ucx)).toBeGreaterThan(100);
  });

  it("stops an arrow at a card short of the card's centre, where the damage number sits", () => {
    const tip = (head: string) => head.split(' ')[0].split(',').map(Number);
    const [, ty] = tip(sceneArrowShape(300, 100, 300, 500, { atCard: true }).head);
    expect(500 - ty).toBeGreaterThanOrEqual(45);
    const [tx] = tip(sceneArrowShape(100, 300, 500, 300, { atCard: true }).head);
    expect(500 - tx).toBeGreaterThanOrEqual(50);
    // A player target keeps its tip on the reticle.
    expect(tip(sceneArrowShape(300, 100, 300, 500, {}).head)).toEqual([300, 500]);
  });

  it('ends the curve at the arrowhead base and puts the tip on the target', () => {
    const shape = arrowShape(600, 120, 200, 400);
    expect(shape.d.startsWith('M600 120 Q')).toBe(true);
    const tip = shape.head.split(' ')[0];
    expect(tip).toBe('200,400');
    const [, , , bx, by] = shape.d.split(/[ Q]+/).map(Number).filter((n) => !Number.isNaN(n));
    expect(Math.hypot(bx - 200, by - 400)).toBeCloseTo(16, 0);
  });
});

describe('stack view', () => {
  it('lists stack items top first with names, kinds and ability text', () => {
    const { state } = at((e) => e.kind === 'stack_push' && e.stack_id === 's5');
    expect(stackView(state)).toEqual([
      {
        stackId: 's5',
        card: 'a1010',
        name: 'Delver of Secrets // Insectile Aberration',
        kind: 'trigger',
        text: 'Look at the top card',
        controller: PLAYER,
        top: true,
        targets: 0,
        targeted: false,
        count: 1,
        stackIds: ['s5'],
        resolved: 0,
      },
    ]);
  });

  it('groups identical abilities next to each other and folds a copy that just resolved', () => {
    const view = (stackId: string, extra: Partial<StackViewItem> = {}): StackViewItem => ({
      stackId,
      card: 'a1',
      name: 'Belladonna Took',
      kind: 'trigger',
      text: 'Whenever a token you control enters',
      controller: PLAYER,
      top: false,
      targets: 0,
      targeted: false,
      count: 1,
      stackIds: [stackId],
      resolved: 0,
      ...extra,
    });
    const grouped = groupStack([view('s3', { top: true }), view('s2'), view('s9', { targets: 1 }), view('s1')]);
    expect(grouped.map((item) => [item.stackId, item.count, item.stackIds, item.top])).toEqual([
      ['s3', 2, ['s3', 's2'], true],
      ['s9', 1, ['s9'], false],
      ['s1', 1, ['s1'], false],
    ]);
    const { items, exits } = foldResolved(grouped, [{ ...view('s4'), exit: 'resolved' as const }, { ...view('s8'), exit: 'countered' as const }]);
    expect(items[0]).toMatchObject({ resolved: 1, stackIds: ['s3', 's2', 's4'] });
    expect(exits.map((item) => item.stackId)).toEqual(['s8']);
  });

  it('tells resolved, countered and fizzled exits apart', () => {
    const countered = stream.events.find((e) => e.kind === 'stack_countered')!;
    expect(stackExit(stateAt(timeline, countered.seq), 's1')).toBe('countered');
    const fizzled = stream.events.find((e) => e.kind === 'stack_fizzle')!;
    expect(stackExit(stateAt(timeline, fizzled.seq), 's6')).toBe('fizzled');
    const resolved = stream.events.find((e) => e.kind === 'stack_resolve' && e.stack_id === 's5')!;
    expect(stackExit(stateAt(timeline, resolved.seq), 's5')).toBe('resolved');
  });
});

describe('attacks on a planeswalker', () => {
  it('point at the planeswalker, not the player, at full brightness', () => {
    const state = buildTimeline(makeTokenStream()).final;
    const arrows = sceneArrows(state, layoutBoard(state, { ...OPTS, playerSeat: 1 }));
    expect(arrows.some((a) => a.tone === 'attack')).toBe(false);
    const attacks = arrows.filter((a) => a.tone === 'strike');
    expect(attacks.map((a) => a.to)).toEqual([
      { kind: 'obj', obj: 'pw' },
      { kind: 'obj', obj: 'pw' },
      { kind: 'obj', obj: 'pw' },
      { kind: 'obj', obj: 'pw' },
    ]);
  });
});

describe('effect arrow tones', () => {
  it('are dim on the acting seat\u2019s own permanents and bright on the opponent\u2019s', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.turnStart(1, 1);
    b.move('src', 'a1', 'limbo', 'battlefield', 1, 'put');
    b.move('mine', 'a2', 'limbo', 'battlefield', 1, 'put');
    b.move('theirs', 'a2', 'limbo', 'battlefield', 2, 'put');
    b.add('stack_push', { stack_id: 's1', obj: 'src', card: 'a1', stack_kind: 'trigger', controller: 1, text: 'Put counters', targets: [] });
    b.add('stack_resolve', { stack_id: 's1' });
    b.add('counter', { obj: 'mine', type: '+1/+1', delta: 1, total: 1 });
    b.add('counter', { obj: 'theirs', type: '+1/+1', delta: 1, total: 1 });
    const stream = b.build(
      { a1: card('Source', 'Creature', { power: '1', toughness: '1' }), a2: card('Bear', 'Creature', { power: '2', toughness: '2' }) },
      { playerSeat: 1 },
    );
    const state = buildTimeline(stream).final;
    const tones = Object.fromEntries(
      sceneArrows(state, layoutBoard(state, { ...OPTS, playerSeat: 1 })).map((a) => [a.id, a.tone]),
    );
    expect(tones['effect:mine']).toBe('support');
    expect(tones['effect:theirs']).toBe('target');
  });
});
