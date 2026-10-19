import { describe, expect, it } from 'vitest';
import { card, StreamBuilder } from './fixtures/streamBuilder';
import { layoutBoard } from './layout';
import type { CardPlacement, LayoutOptions } from './layout';
import { buildTimeline, stateAt } from './reducer';
import type { BoardState } from './reducer';
import { sceneArrows } from './scene/arrows';
import { sceneLabels } from './scene/labels';
import { effectExits } from './scene/stackView';
import type { ReplayCard } from './types';

const ME = 1;
const OPP = 2;
const OPTS: LayoutOptions = { mirrorOpponent: false, hindsight: false, playerSeat: ME };

const CARDS: Record<string, ReplayCard> = {
  bear: card('Grizzly Bears', 'Creature', { power: '2', toughness: '2' }),
  helix: card('Lightning Helix', 'Instant'),
  murder: card('Murder', 'Instant'),
  wrath: card('Wrath of God', 'Sorcery'),
  edict: card('Diabolic Edict', 'Instant'),
  bounce: card('Unsummon', 'Instant'),
  cancel: card('Cancel', 'Instant'),
  growth: card('Giant Growth', 'Instant'),
  duress: card('Duress', 'Sorcery'),
  mill: card('Thought Scour', 'Instant'),
  ice: card('Frost Breath', 'Instant'),
  bat: card('Deep-Cavern Bat', 'Creature', { power: '1', toughness: '1' }),
  rip: card('Seam Rip', 'Enchantment'),
};

/** Two bears on each side, then whatever `script` does; returns the timeline and the stream's events. */
function game(script: (b: StreamBuilder) => void) {
  const b = new StreamBuilder();
  b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
  b.move('m1', 'bear', 'limbo', 'battlefield', ME, 'put');
  b.move('m2', 'bear', 'limbo', 'battlefield', ME, 'put');
  b.move('o1', 'bear', 'limbo', 'battlefield', OPP, 'put');
  b.move('o2', 'bear', 'limbo', 'battlefield', OPP, 'put');
  b.add('pt', { obj: 'm1', power: 2, toughness: 2 });
  b.add('pt', { obj: 'o1', power: 2, toughness: 2 });
  b.turnStart(3, ME);
  b.phaseTo('Phase_Main1');
  script(b);
  const stream = b.build(CARDS, { playerSeat: ME });
  return { timeline: buildTimeline(stream), events: stream.events };
}

function view(state: BoardState) {
  const layout = layoutBoard(state, OPTS);
  return { layout, labels: sceneLabels(layout, state.cards), arrows: sceneArrows(state, layout) };
}

const byObj = (cards: CardPlacement[], obj: string) => cards.filter((c) => c.obj === obj);
const labelText = (labels: ReturnType<typeof sceneLabels>, id: string) => labels.find((l) => l.id === id)?.text ?? null;

describe('effect window: damage and life', () => {
  it('shows Lightning Helix: −3 at the opponent, +3 at its caster, an arrow from the resolved spell', () => {
    const { timeline } = game((b) => {
      b.move('h1', 'helix', 'limbo', 'hand', ME, 'draw');
      b.cast('h1', 'helix', ME, 's1');
      b.add('stack_resolve', { stack_id: 's1' });
      b.add('damage', { source: 'h1', target_obj: null, target_seat: OPP, amount: 3, combat: false });
      b.add('life', { seat: OPP, life: 17, delta: -3, source_obj: 'h1' });
      b.add('life', { seat: ME, life: 23, delta: 3, source_obj: 'h1' });
      b.move('h1', 'helix', 'stack', 'graveyard', ME, 'resolve');
    });
    const state = timeline.final;
    const { labels, arrows } = view(state);
    expect(labelText(labels, `seat:${OPP}`)).toBe('−3');
    expect(labels.find((l) => l.id === `seat:${OPP}`)?.tone).toBe('life-loss');
    expect(labelText(labels, `seat:${ME}`)).toBe('+3');
    expect(labels.find((l) => l.id === `seat:${ME}`)?.tone).toBe('life-gain');
    // The spell stays in the stack preview, resolved, as the arrow's source.
    expect(effectExits(state).map((e) => [e.name, e.exit])).toEqual([['Lightning Helix', 'resolved']]);
    expect(arrows).toEqual([
      { id: `effect-seat:${OPP}`, from: { kind: 'stack', stackId: 's1' }, to: { kind: 'seat', seat: OPP }, seat: ME, tone: 'damage' },
    ]);
  });

  it('marks Lightning Helix aimed at a creature on that creature', () => {
    const { timeline } = game((b) => {
      b.move('h1', 'helix', 'limbo', 'hand', ME, 'draw');
      b.cast('h1', 'helix', ME, 's1', ['o1']);
      b.add('stack_resolve', { stack_id: 's1' });
      b.add('damage', { source: 'h1', target_obj: 'o1', target_seat: null, amount: 3, combat: false });
      b.add('life', { seat: ME, life: 23, delta: 3, source_obj: 'h1' });
      b.move('h1', 'helix', 'stack', 'graveyard', ME, 'resolve');
      b.move('o1', 'bear', 'battlefield', 'graveyard', OPP, 'sba');
    });
    const { layout, labels, arrows } = view(timeline.final);
    expect(byObj(layout.cards, 'o1').map((c) => [c.zone, c.damage, c.removed])).toEqual([['battlefield', 3, 'died']]);
    expect(labelText(labels, 'damage:o1')).toBe('−3');
    expect(labelText(labels, 'removed:o1')).toBe('Died');
    expect(arrows.map((a) => [a.id, a.from])).toEqual([['effect:o1', { kind: 'stack', stackId: 's1' }]]);
  });

  it('leaves combat damage to its attack arrows but still shows the number at the player', () => {
    const { timeline } = game((b) => {
      b.phaseTo('Phase_Combat', 'Step_DeclareAttack');
      b.add('attack', { seat: ME, objs: ['m1'], target_seat: OPP, target_obj: null });
      b.add('damage', { source: 'm1', target_obj: null, target_seat: OPP, amount: 2, combat: true });
      b.add('life', { seat: OPP, life: 18, delta: -2, source_obj: 'm1' });
    });
    const { labels, arrows } = view(timeline.final);
    expect(labelText(labels, `seat:${OPP}`)).toBe('−2');
    expect(arrows.map((a) => a.id)).toEqual(['attack:m1']);
  });
});

describe('effect window: removal', () => {
  it('holds a destroyed creature in its slot, dimmed with a chip, until the next action', () => {
    const { timeline, events } = game((b) => {
      b.move('k1', 'murder', 'limbo', 'hand', ME, 'draw');
      b.cast('k1', 'murder', ME, 's1', ['o1']);
      b.add('stack_resolve', { stack_id: 's1' });
      b.move('o1', 'bear', 'battlefield', 'graveyard', OPP, 'destroy');
      b.move('k1', 'murder', 'stack', 'graveyard', ME, 'resolve');
      b.phaseTo('Phase_Combat');
    });
    const destroyed = events.find((e) => e.kind === 'move' && e.reason === 'destroy')!;
    const during = stateAt(timeline, destroyed.seq + 1);
    expect(during.seats[OPP].zones.graveyard).toEqual(['o1']);
    const { layout, labels, arrows } = view(during);
    expect(byObj(layout.cards, 'o1').map((c) => [c.zone, c.row, c.removed])).toEqual([['battlefield', 'creatures', 'destroyed']]);
    // The graveyard counts it, but its top card is not drawn twice.
    expect(layout.piles.find((p) => p.seat === OPP && p.zone === 'graveyard')?.count).toBe(1);
    expect(labelText(labels, 'removed:o1')).toBe('Destroyed');
    expect(arrows.map((a) => [a.id, a.from, a.tone])).toEqual([['effect:o1', { kind: 'stack', stackId: 's1' }, 'damage']]);
    const after = view(timeline.final);
    expect(byObj(after.layout.cards, 'o1').map((c) => [c.zone, c.row, c.removed])).toEqual([['graveyard', 'pile', null]]);
    expect(after.arrows).toEqual([]);
  });

  it('marks everything a wrath destroyed, each from the wrath', () => {
    const { timeline } = game((b) => {
      b.move('w1', 'wrath', 'limbo', 'hand', ME, 'draw');
      b.cast('w1', 'wrath', ME, 's1');
      b.add('stack_resolve', { stack_id: 's1' });
      for (const [obj, seat] of [['m1', ME], ['m2', ME], ['o1', OPP], ['o2', OPP]] as const) {
        b.move(obj, 'bear', 'battlefield', 'graveyard', seat, 'destroy');
      }
      b.move('w1', 'wrath', 'stack', 'graveyard', ME, 'resolve');
    });
    const { layout, arrows } = view(timeline.final);
    expect(layout.cards.filter((c) => c.removed === 'destroyed').map((c) => c.obj)).toEqual(['m1', 'm2', 'o1', 'o2']);
    expect(arrows.every((a) => a.from.kind === 'stack' && a.from.stackId === 's1')).toBe(true);
    expect(arrows).toHaveLength(4);
  });

  it("draws an edict's sacrifice from the opponent's spell, but a sacrifice as a cost from nothing", () => {
    const edict = game((b) => {
      b.move('e1', 'edict', 'limbo', 'hand', OPP, 'draw');
      b.cast('e1', 'edict', OPP, 's1');
      b.add('stack_resolve', { stack_id: 's1' });
      b.move('m1', 'bear', 'battlefield', 'graveyard', ME, 'sacrifice');
    });
    const e = view(edict.timeline.final);
    expect(byObj(e.layout.cards, 'm1')[0].removed).toBe('sacrificed');
    expect(e.arrows.map((a) => a.id)).toEqual(['effect:m1']);
    const cost = game((b) => b.move('m1', 'bear', 'battlefield', 'graveyard', ME, 'sacrifice'));
    const c = view(cost.timeline.final);
    expect(byObj(c.layout.cards, 'm1')[0].removed).toBe('sacrificed');
    expect(c.arrows).toEqual([]);
  });

  it('shows a bounced creature as Returned to hand in its slot, not yet in the hand', () => {
    const { timeline } = game((b) => {
      b.move('u1', 'bounce', 'limbo', 'hand', ME, 'draw');
      b.cast('u1', 'bounce', ME, 's1', ['o1']);
      b.add('stack_resolve', { stack_id: 's1' });
      b.move('o1', 'bear', 'battlefield', 'hand', OPP, 'bounce');
    });
    const { layout, labels } = view(timeline.final);
    expect(byObj(layout.cards, 'o1').map((c) => [c.zone, c.row])).toEqual([['battlefield', 'creatures']]);
    expect(labelText(labels, 'removed:o1')).toBe('Returned to hand');
    expect(timeline.final.seats[OPP].handSize).toBe(1);
  });

  it('holds a card a permanent exiled, then tucks it under that permanent', () => {
    const { timeline, events } = game((b) => {
      b.move('r1', 'rip', 'limbo', 'battlefield', ME, 'put');
      b.move('o1', 'bear', 'battlefield', 'exile', OPP, 'exile', { with: 'r1' });
      b.phaseTo('Phase_Combat');
    });
    const exiled = events.find((e) => e.kind === 'move' && e.reason === 'exile')!;
    const during = view(stateAt(timeline, exiled.seq));
    expect(byObj(during.layout.cards, 'o1').map((c) => [c.zone, c.removed])).toEqual([['battlefield', 'exiled']]);
    const after = view(timeline.final);
    expect(byObj(after.layout.cards, 'r1')[0].under.map((u) => u.obj)).toEqual(['o1']);
  });

  it('attributes a removal to the permanent named in `by` when the capture logged one', () => {
    const { timeline } = game((b) => {
      b.move('r1', 'rip', 'limbo', 'battlefield', ME, 'put');
      b.add('move', {
        obj: 'o1', card: 'bear', from: 'battlefield', to: 'exile', owner: OPP, controller: OPP,
        reason: 'exile', inferred: false, index: null, with: null, by: 'r1',
      });
    });
    const { arrows } = view(timeline.final);
    expect(arrows.map((a) => [a.id, a.from])).toEqual([['effect:o1', { kind: 'obj', obj: 'r1' }]]);
  });

  it('shows nothing for a flicker that returns the card in the same action', () => {
    const { timeline } = game((b) => {
      b.move('o1', 'bear', 'battlefield', 'exile', OPP, 'exile');
      b.move('o1', 'bear', 'exile', 'battlefield', OPP, 'put');
    });
    expect(byObj(view(timeline.final).layout.cards, 'o1').map((c) => [c.zone, c.removed])).toEqual([['battlefield', null]]);
  });

  it('stamps a countered spell and draws the counterspell to it', () => {
    const { timeline } = game((b) => {
      b.move('g1', 'growth', 'limbo', 'hand', OPP, 'draw');
      b.cast('g1', 'growth', OPP, 's1', ['o1']);
      b.move('c1', 'cancel', 'limbo', 'hand', ME, 'draw');
      b.cast('c1', 'cancel', ME, 's2', ['g1']);
      b.add('stack_resolve', { stack_id: 's2' });
      b.add('stack_countered', { stack_id: 's1' });
      b.move('g1', 'growth', 'stack', 'graveyard', OPP, 'counter');
      b.move('c1', 'cancel', 'stack', 'graveyard', ME, 'resolve');
    });
    const state = timeline.final;
    expect(effectExits(state).map((e) => [e.name, e.exit])).toEqual([
      ['Cancel', 'resolved'],
      ['Giant Growth', 'countered'],
    ]);
    expect(view(state).arrows).toEqual([
      { id: 'countered:s1', from: { kind: 'stack', stackId: 's2' }, to: { kind: 'stack', stackId: 's1' }, seat: ME, tone: 'damage' },
    ]);
  });
});

describe('effect window: smaller effects', () => {
  it('shows a pump as +3/+3 and −1/−1 counters as −1/−1, but not a creature entering', () => {
    const { timeline } = game((b) => {
      b.move('g1', 'growth', 'limbo', 'hand', ME, 'draw');
      b.cast('g1', 'growth', ME, 's1', ['m1']);
      b.add('stack_resolve', { stack_id: 's1' });
      b.add('pt', { obj: 'm1', power: 5, toughness: 5 });
      b.add('counter', { obj: 'o1', type: '-1/-1', delta: 1, total: 1 });
      b.add('pt', { obj: 'o1', power: 1, toughness: 1 });
      b.move('g1', 'growth', 'stack', 'graveyard', ME, 'resolve');
      b.move('n1', 'bat', 'limbo', 'battlefield', ME, 'token_create');
      b.add('pt', { obj: 'n1', power: 1, toughness: 1 });
    });
    const { labels } = view(timeline.final);
    expect(labels.find((l) => l.id === 'change:m1')).toMatchObject({ text: '+3/+3', tone: 'buff' });
    expect(labels.find((l) => l.id === 'change:o1')).toMatchObject({ text: '−1/−1', tone: 'debuff' });
    expect(labels.find((l) => l.id === 'change:n1')).toBeUndefined();
  });

  it('marks a creature a spell tapped, a discard on the graveyard, and a mill on the pile', () => {
    const { timeline } = game((b) => {
      b.move('f1', 'ice', 'limbo', 'hand', ME, 'draw');
      b.cast('f1', 'ice', ME, 's1', ['o1']);
      b.add('stack_resolve', { stack_id: 's1' });
      b.add('tap', { objs: ['o1'] });
      b.move('y1', 'bear', 'library', 'graveyard', OPP, 'mill');
      b.move('y2', 'bear', 'library', 'graveyard', OPP, 'mill');
      // The discarded card lands on top of the graveyard, so its card shows the chip.
      b.move('x1', 'helix', 'limbo', 'hand', OPP, 'put');
      b.move('x1', 'helix', 'hand', 'graveyard', OPP, 'discard');
    });
    const { labels, arrows } = view(timeline.final);
    expect(labelText(labels, 'tapped:o1')).toBe('Tapped');
    expect(labelText(labels, `milled:${OPP}`)).toBe('Milled 2');
    expect(labelText(labels, 'removed:x1')).toBe('Discarded');
    expect(arrows.map((a) => a.id).sort()).toEqual(['effect:o1', 'effect:x1']);
  });
});
