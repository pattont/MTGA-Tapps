import { describe, expect, it } from 'vitest';
import { PLAYER, SAMPLE_CARDS, makeSampleStream } from '../fixtures/sampleStream';
import { StreamBuilder, card } from '../fixtures/streamBuilder';
import { makeTokenStream } from '../fixtures/tokenStream';
import { CARD_HEIGHT, layoutBoard } from '../layout';
import { buildTimeline, stateAt } from '../reducer';
import { countersText, sceneLabels } from './labels';

describe('scene labels', () => {
  const stream = makeSampleStream();
  const timeline = buildTimeline(stream);
  const opts = { mirrorOpponent: false, hindsight: true, playerSeat: PLAYER };

  it('labels every pile except empty command zones', () => {
    const state = stateAt(timeline, stream.turns[0].first_seq);
    const labels = sceneLabels(layoutBoard(state, opts), SAMPLE_CARDS);
    const piles = labels.filter((l) => l.tone === 'pile').map((l) => l.text);
    expect(piles).toContain('Library 54');
    expect(piles).toContain('Graveyard 0');
    expect(piles.some((text) => text.startsWith('Command'))).toBe(false);
  });

  it('leaves stack captions to the DOM stack preview', () => {
    const push = stream.events.find((e) => e.kind === 'stack_push' && e.stack_id === 's5')!;
    const state = stateAt(timeline, push.seq);
    const layout = layoutBoard(state, opts);
    expect(layout.cards.some((c) => c.row === 'stack')).toBe(true);
    const labels = sceneLabels(layout, SAMPLE_CARDS);
    expect(labels.some((l) => l.obj?.startsWith('stack:'))).toBe(false);
  });

  it('puts pile badges across the lower edge of the scaled pile', () => {
    const state = stateAt(timeline, stream.turns[0].first_seq);
    const layout = layoutBoard(state, opts);
    const labels = sceneLabels(layout, SAMPLE_CARDS);
    for (const pile of layout.piles.filter((p) => p.zone !== 'command')) {
      const label = labels.find((l) => l.id === `pile:${pile.seat}:${pile.zone}`)!;
      expect(label.x).toBe(pile.x);
      expect(label.y).toBeLessThan(pile.y);
      expect(label.y).toBeGreaterThan(pile.y - (CARD_HEIGHT * pile.scale) / 2);
    }
  });

  it('badges every creature with its power/toughness, emphasized when modified, with other counters above', () => {
    const pt = stream.events.find((e) => e.kind === 'pt' && e.obj === 'tok1')!;
    const state = stateAt(timeline, pt.seq);
    const layout = layoutBoard(state, opts);
    const labels = sceneLabels(layout, SAMPLE_CARDS);
    const badge = labels.find((l) => l.id === 'stat:tok1')!;
    expect(badge).toMatchObject({ text: '2/2', tone: 'stat', emphasis: true, align: 'center' });
    const chip = labels.find((l) => l.id === 'counters:tok1')!;
    expect(chip).toMatchObject({ text: '+1/+1', tone: 'counters' });
    // Badge across the lower edge, counters across the upper edge.
    expect(badge.y).toBeLessThan(0);
    expect(chip.y).toBeGreaterThan(0);
    // An unmodified creature shows its printed values, not emphasized.
    const plain = labels.find((l) => l.id === 'stat:215');
    expect(plain?.text).toMatch(/^\d+\/\d+$/);
    expect(plain?.emphasis).toBe(false);
    expect(labels.some((l) => l.id === 'counters:215')).toBe(false);
  });

  it('shows a planeswalker\u2019s loyalty total, never the word "loyalty"', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('pw1', 'a9', 'limbo', 'battlefield', 1, 'put');
    b.add('counter', { obj: 'pw1', type: 'loyalty', delta: 1, total: 1 });
    b.add('counter', { obj: 'pw1', type: 'loyalty', delta: 3, total: 4 });
    b.add('counter', { obj: 'pw1', type: 'loyalty', delta: -2, total: 2 });
    const built = b.build({ a9: card('Ajani', 'Planeswalker') }, { playerSeat: 1 });
    const tl = buildTimeline(built);
    const counters = built.events.filter((e) => e.kind === 'counter');
    const at = (i: number) => sceneLabels(layoutBoard(stateAt(tl, counters[i].seq), { ...opts, playerSeat: 1 }), built.cards);
    expect(at(0).find((l) => l.id === 'stat:pw1')).toMatchObject({ text: '1', tone: 'loyalty' });
    expect(at(1).find((l) => l.id === 'stat:pw1')?.text).toBe('4');
    expect(at(2).find((l) => l.id === 'stat:pw1')?.text).toBe('2');
    expect(at(2).some((l) => l.id === 'counters:pw1')).toBe(false);
    // A planeswalker with no loyalty information (a reconstructed game) gets no badge at all.
    const quiet = sceneLabels(layoutBoard(stateAt(tl, built.events[1].seq), { ...opts, playerSeat: 1 }), built.cards);
    expect(quiet.some((l) => l.id === 'stat:pw1')).toBe(false);
  });
});

describe('commanders', () => {
  const cards = {
    cmd: card('Belladonna Took', 'Creature', { power: '2', toughness: '2' }),
    bear: card('Grizzly Bears', 'Creature', { power: '2', toughness: '2' }),
  };
  const opts = { mirrorOpponent: false, hindsight: true, playerSeat: PLAYER, commandZone: true };

  function brawl() {
    const b = new StreamBuilder();
    b.move('c1', 'cmd', 'limbo', 'command', PLAYER, 'put');
    b.turnStart(1, PLAYER);
    b.move('c1', 'cmd', 'command', 'stack', PLAYER, 'cast');
    b.add('stack_push', { stack_id: 's1', obj: 'c1', card: 'cmd', stack_kind: 'spell', controller: PLAYER, text: null, targets: [] });
    b.resolve('c1', 'cmd', PLAYER, 's1', 'battlefield');
    b.move('b1', 'bear', 'limbo', 'battlefield', PLAYER, 'put');
    b.add('counter', { obj: 'c1', type: '+1/+1', delta: 1, total: 1 });
    const stream = b.build(cards, { playerSeat: PLAYER });
    stream.seats[String(PLAYER)].commanders = ['Belladonna Took'];
    return stream;
  }

  it('marks the commander on the battlefield and keeps its empty command zone labelled', () => {
    const stream = brawl();
    const timeline = buildTimeline(stream);
    const resolved = stream.events.findIndex((e) => e.kind === 'move' && e.to === 'battlefield' && e.obj === 'c1');
    const state = stateAt(timeline, stream.events[resolved].seq);
    const layout = layoutBoard(state, opts);
    expect(layout.cards.find((c) => c.obj === 'c1')?.commander).toBe(true);
    const labels = sceneLabels(layout, cards);
    const chip = labels.find((l) => l.id === 'counters:c1')!;
    expect(chip.text).toBe('Commander');
    expect(chip.tone).toBe('commander');
    expect(labels.find((l) => l.id === `pile:${PLAYER}:command`)?.text).toBe('Command');
  });

  it('is not marked before it is cast, and ordinary creatures never are', () => {
    const stream = brawl();
    const timeline = buildTimeline(stream);
    const start = stateAt(timeline, stream.turns[0].first_seq);
    const first = layoutBoard(start, opts);
    expect(first.cards.find((c) => c.obj === 'c1')?.zone).toBe('command');
    expect(sceneLabels(first, cards).find((l) => l.id === `pile:${PLAYER}:command`)?.text).toBe('Command 1');
    expect(sceneLabels(first, cards).some((l) => l.tone === 'commander')).toBe(false);
    const end = layoutBoard(stateAt(timeline, stream.events[stream.events.length - 1].seq), opts);
    expect(end.cards.find((c) => c.obj === 'b1')?.commander).toBe(false);
    const chip = sceneLabels(end, cards).find((l) => l.id === 'counters:c1')!;
    expect(chip.text).toBe('Commander · +1/+1');
    expect(chip.tone).toBe('commander');
  });
});

describe('side card chips', () => {
  it('names why a card sits beside the hand, gold when plotted', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('g1', 'looting', 'limbo', 'graveyard', PLAYER, 'put');
    b.move('p1', 'show', 'limbo', 'hand', PLAYER, 'draw');
    b.move('p1', 'show', 'hand', 'exile', PLAYER, 'exile');
    const cards = {
      looting: card('Faithless Looting', 'Sorcery', { keywords: ['flashback'] }),
      show: card('Slickshot Show-Off', 'Creature', { keywords: ['plot'] }),
    };
    const stream = b.build(cards, { playerSeat: PLAYER });
    const layout = layoutBoard(buildTimeline(stream).final, { mirrorOpponent: false, hindsight: false, playerSeat: PLAYER });
    const labels = sceneLabels(layout, cards);
    const flashback = labels.find((l) => l.id === 'castable:g1');
    const plotted = labels.find((l) => l.id === 'castable:p1');
    expect([flashback?.text, flashback?.tone, flashback?.emphasis]).toEqual(['Flashback', 'castable', false]);
    expect([plotted?.text, plotted?.emphasis]).toEqual(['Plotted', true]);
    expect(labels.some((l) => l.id === 'stat:p1')).toBe(false);
  });
});

describe('damage badges', () => {
  it('shows a red minus badge on each damaged permanent', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('c1', 'bear', 'limbo', 'battlefield', PLAYER, 'put');
    b.add('damage', { source: null, target_obj: 'c1', target_seat: null, amount: 6, combat: false });
    const cards = { bear: card('Bear', 'Creature', { power: '2', toughness: '2' }) };
    const stream = b.build(cards, { playerSeat: PLAYER });
    const layout = layoutBoard(buildTimeline(stream).final, { mirrorOpponent: false, hindsight: false, playerSeat: PLAYER });
    const badge = sceneLabels(layout, cards).find((l) => l.id === 'damage:c1');
    expect([badge?.text, badge?.tone]).toEqual(['−6', 'damage']);
  });
});

describe('chosen land type', () => {
  const cards = { passage: card('Multiversal Passage', 'Land') };
  const opts = { mirrorOpponent: false, hindsight: true, playerSeat: PLAYER };

  it('chips a land with the basic land type it chose, in that color, until it leaves', () => {
    const b = new StreamBuilder();
    b.move('p1', 'passage', 'limbo', 'hand', PLAYER, 'put');
    b.turnStart(1, PLAYER);
    b.add('move', {
      obj: 'p1',
      card: 'passage',
      from: 'hand',
      to: 'battlefield',
      owner: PLAYER,
      controller: PLAYER,
      reason: 'play_land',
      inferred: false,
      index: null,
      with: null,
      chosen: 'Mountain',
    });
    b.add('tap', { objs: ['p1'] });
    b.move('p1', 'passage', 'battlefield', 'graveyard', PLAYER, 'destroy');
    b.phaseTo('Phase_Main2');
    const stream = b.build(cards, { playerSeat: PLAYER });
    const timeline = buildTimeline(stream);
    const at = (kind: string, to?: string) => {
      const event = stream.events.findLast((e) => e.kind === kind && (!to || (e.kind === 'move' && e.to === to)))!;
      return sceneLabels(layoutBoard(stateAt(timeline, event.seq), opts), cards);
    };
    expect(at('move', 'battlefield').find((l) => l.id === 'counters:p1')).toMatchObject({ text: 'Mountain', tone: 'land-mountain' });
    // Tapping keeps the choice; once it has left the battlefield (after the
    // destroy's own action, where it is held in its slot) the choice is gone.
    expect(at('tap').find((l) => l.id === 'counters:p1')?.text).toBe('Mountain');
    expect(at('phase').some((l) => l.id === 'counters:p1')).toBe(false);
  });
});

describe('tapped cards and token stacks', () => {
  it('keeps a tapped card\u2019s chips above and below it, and labels a token stack once with its count', () => {
    const stream = makeTokenStream();
    const layout = layoutBoard(buildTimeline(stream).final, { mirrorOpponent: false, hindsight: true, playerSeat: 1 });
    const labels = sceneLabels(layout, stream.cards);
    const stat = labels.find((l) => l.id === 'stat:t1')!;
    const chip = labels.find((l) => l.id === 'counters:t1')!;
    // Upright, within the sideways card: not out at its left and right edges.
    expect(Math.abs(stat.x)).toBeLessThan(0.01);
    expect(stat.y).toBeLessThan(0);
    expect(Math.abs(chip.x)).toBeLessThan(0.01);
    expect(chip.y).toBeGreaterThan(0);
    expect(chip.y).toBeLessThan(0.43);
    expect(labels.find((l) => l.id === 'stack:t1')).toMatchObject({ text: '\u00d73' });
    // The stacked tokens carry no labels of their own.
    expect(labels.some((l) => l.obj === 't2' || l.obj === 't3')).toBe(false);
  });

  it('shows a land stack\u2019s count centered above its top edge, a token stack\u2019s in its corner', () => {
    const stream = makeTokenStream();
    const layout = layoutBoard(buildTimeline(stream).final, { mirrorOpponent: false, hindsight: true, playerSeat: 1 });
    const token = layout.cards.find((c) => c.obj === 't1')!;
    const land = { ...token, obj: 'l1', row: 'lands' as const, tapped: false, rotZ: 0, counters: {} };
    const labels = sceneLabels({ ...layout, cards: [{ ...token, tapped: false, rotZ: 0 }, land] }, stream.cards);
    const landCount = labels.find((l) => l.id === 'stack:l1')!;
    const tokenCount = labels.find((l) => l.id === 'stack:t1')!;
    const half = (CARD_HEIGHT * land.scale) / 2;
    expect(landCount.x).toBeCloseTo(0);
    expect(landCount.y).toBeGreaterThan(half);
    expect(tokenCount.x).toBeLessThan(0);
    expect(tokenCount.y).toBeLessThan(0);
  });
});

describe('counter chips', () => {
  it('show a count on every counter type but a single +1/+1 or -1/-1', () => {
    const base = { counters: {} } as unknown as Parameters<typeof countersText>[0];
    expect(countersText({ ...base, counters: { plan: 1 } })).toBe('plan ×1');
    expect(countersText({ ...base, counters: { '+1/+1': 1, oil: 3 } })).toBe('+1/+1 · oil ×3');
    expect(countersText({ ...base, counters: { '+1/+1': 2, loyalty: 4 } })).toBe('+1/+1 ×2');
  });
});

describe('summoning sickness', () => {
  const cards = {
    bear: card('Bear', 'Creature', { power: '2', toughness: '2' }),
    token: card('Soldier', 'Creature', { power: '1', toughness: '1', is_token: true }),
  };
  const opts = { mirrorOpponent: false, hindsight: true, playerSeat: PLAYER };

  function sleepy() {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.turnStart(1, PLAYER);
    b.move('b1', 'bear', 'limbo', 'battlefield', PLAYER, 'put');
    b.add('sick', { objs: ['b1'] });
    b.move('t1', 'token', 'limbo', 'battlefield', PLAYER, 'token_create');
    b.move('t2', 'token', 'limbo', 'battlefield', PLAYER, 'token_create');
    b.add('sick', { objs: ['t2'] });
    b.turnStart(2, PLAYER);
    b.add('unsick', { objs: ['b1', 't2'] });
    b.move('b1', 'bear', 'battlefield', 'graveyard', PLAYER, 'destroy');
    return b.build(cards, { playerSeat: PLAYER });
  }

  it('puts a purple sleep badge on a sick creature until it can attack', () => {
    const stream = sleepy();
    const timeline = buildTimeline(stream);
    const at = (kind: string) => {
      const state = stateAt(timeline, stream.events.find((e) => e.kind === kind)!.seq);
      return { state, layout: layoutBoard(state, opts) };
    };
    const sick = at('sick');
    expect(sick.state.objects.get('b1')?.sick).toBe(true);
    const badge = sceneLabels(sick.layout, cards).find((l) => l.id === 'sick:b1')!;
    expect([badge.text, badge.tone]).toEqual(['Zzz', 'sick']);
    // Centered just above the card's top edge, clear of its name.
    const bear = sick.layout.cards.find((c) => c.obj === 'b1')!;
    expect(badge.x).toBeCloseTo(0);
    expect(badge.y).toBeGreaterThan((CARD_HEIGHT * bear.scale) / 2 + 0.05);
    const awake = at('unsick');
    expect(awake.state.objects.get('b1')?.sick).toBe(false);
    expect(sceneLabels(awake.layout, cards).some((l) => l.tone === 'sick')).toBe(false);
  });

  it('keeps sick and ready tokens in separate stacks, and forgets sickness off the battlefield', () => {
    const stream = sleepy();
    const timeline = buildTimeline(stream);
    const sickSeq = stream.events.filter((e) => e.kind === 'sick')[1].seq;
    const split = layoutBoard(stateAt(timeline, sickSeq), opts).cards;
    expect(split.find((c) => c.obj === 't2')?.stackedUnder).toBeUndefined();
    expect(split.find((c) => c.obj === 't2')?.sick).toBe(true);
    const unsick = stream.events.find((e) => e.kind === 'unsick')!.seq;
    const merged = layoutBoard(stateAt(timeline, unsick), opts).cards;
    expect(merged.find((c) => c.obj === 't2')?.stackedUnder).toBe('t1');
    expect(timeline.final.objects.get('b1')?.sick).toBeUndefined();
  });
});
