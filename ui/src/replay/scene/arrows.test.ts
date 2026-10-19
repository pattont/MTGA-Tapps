import { describe, expect, it } from 'vitest';
import { OPPONENT, PLAYER, makeSampleStream } from '../fixtures/sampleStream';
import { StreamBuilder, card } from '../fixtures/streamBuilder';
import { layoutBoard } from '../layout';
import { SLEEVE_COLORS } from '../prefs';
import { buildTimeline, stateAt } from '../reducer';
import type { ReplayEvent } from '../types';
import { arrowBend, arrowControlPoint, arrowShape, neonColors, sceneArrows, seatAnchor, sleeveNeon } from './arrows';
import { stackExit, stackView } from './stackView';

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
      },
    ]);
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
