import { describe, expect, it } from 'vitest';
import { StreamBuilder, card } from './fixtures/streamBuilder';
import { makeTokenStream } from './fixtures/tokenStream';
import { OPPONENT, PLAYER, makeSampleStream } from './fixtures/sampleStream';
import type { CardPlacement, LayoutOptions } from './layout';
import {
  ABILITY_CHIP_SCALE,
  BACK_ROW_SCALE,
  CARD_HEIGHT,
  CARD_WIDTH,
  DEFAULT_TABLE_WIDTH,
  FLYING_LIFT,
  HAND_MIN_VISIBLE,
  HAND_SCALE_FLOOR,
  HAND_SCALE_MAX,
  HAND_SCALE_MIN,
  HAND_FELT_OVERLAP,
  MAX_TABLE_WIDTH,
  MIN_TABLE_WIDTH,
  RAIL_WIDTH,
  ROW_Y,
  STACK_SCALE,
  TABLE_DEPTH,
  TAPPED_ROTATION,
  OPPONENT_HAND_INNER,
  OPPONENT_HAND_SCALE,
  PILE_CARD_DEPTH,
  PILE_MAX_CARDS,
  apronDepth,
  handY,
  opponentApronDepth,
  layoutBoard,
  placeRow,
  rowCenters,
  tableGeometry,
  usesCommandZone,
} from './layout';
import { stackView } from './scene/stackView';
import { sceneLabels } from './scene/labels';
import { buildTimeline, stateAt } from './reducer';
import type { ReplayEvent } from './types';

const OPTS: LayoutOptions = { mirrorOpponent: false, hindsight: false, playerSeat: PLAYER };

function sampleAt(predicate: (event: ReplayEvent) => boolean) {
  const stream = makeSampleStream();
  const timeline = buildTimeline(stream);
  const event = stream.events.find(predicate);
  if (!event) throw new Error('missing event');
  return stateAt(timeline, event.seq);
}

function byObj(cards: CardPlacement[], obj: string): CardPlacement {
  const found = cards.find((c) => c.obj === obj);
  if (!found) throw new Error(`no placement for ${obj}`);
  return found;
}

function bigBoard(count: number, tappedEvery = 4) {
  const b = new StreamBuilder();
  b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
  const kinds = ['a1', 'a2', 'a3'];
  const tapped: string[] = [];
  for (let i = 0; i < count; i += 1) {
    const obj = `o${String(i).padStart(3, '0')}`;
    b.move(obj, kinds[i % 3], 'limbo', 'battlefield', 1, 'put');
    if (i % tappedEvery === 0) tapped.push(obj);
  }
  b.add('tap', { objs: tapped });
  const stream = b.build(
    {
      a1: card('Forest', 'Land'),
      a2: card('Bear', 'Creature', { power: '2', toughness: '2' }),
      a3: card('Ring', 'Artifact'),
    },
    { playerSeat: 1 },
  );
  return buildTimeline(stream).final;
}

describe('layoutBoard', () => {
  it('is deterministic and sorted by object key', () => {
    const state = sampleAt((e) => e.kind === 'block');
    const a = layoutBoard(state, OPTS);
    const b = layoutBoard(state, OPTS);
    expect(a).toEqual(b);
    const keys = a.cards.map((c) => c.obj);
    expect(keys).toEqual([...keys].sort());
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('places the player near (y < 0) and the opponent far, upright by default', () => {
    const state = sampleAt((e) => e.kind === 'block');
    const { cards } = layoutBoard(state, OPTS);
    expect(byObj(cards, '211').y).toBeLessThan(0);
    expect(byObj(cards, '101').y).toBeGreaterThan(0);
    expect(byObj(cards, '101').rotZ).toBe(0);
    expect(byObj(cards, '101').row).toBe('lands');
    expect(byObj(cards, '215')).toMatchObject({ row: 'creatures', highlight: 'attacking', faceUp: true });
    expect(byObj(cards, '104').highlight).toBe('blocking');

    const mirrored = layoutBoard(state, { ...OPTS, mirrorOpponent: true });
    expect(byObj(mirrored.cards, '101').rotZ).toBeCloseTo(Math.PI);
    expect(byObj(mirrored.cards, '101').x).toBeCloseTo(-byObj(cards, '101').x);
    // A mirrored opponent's piles are turned, but stay in the left lane.
    const opponentPile = mirrored.piles.find((p) => p.seat === OPPONENT && p.zone === 'library')!;
    expect(opponentPile.x).toBeLessThan(mirrored.table.rowLeft);
    expect(opponentPile.rotZ).toBeCloseTo(Math.PI);
  });

  it('builds two tiers per seat: creatures in front, a clear gap, then lands and other permanents', () => {
    const { cards } = layoutBoard(bigBoard(18), { ...OPTS, playerSeat: 1 });
    // Cards stacked under an identical one sit a few edges higher; the row is where the tops are.
    const rowY = (row: string) => [...new Set(cards.filter((c) => c.row === row && !c.tapped && !c.stackedUnder).map((c) => c.y.toFixed(4)))];
    expect(rowY('creatures')).toEqual([ROW_Y.creatures.toFixed(4)]);
    expect(rowY('lands')).toEqual([ROW_Y.back.toFixed(4)]);
    expect(rowY('other')).toEqual([ROW_Y.back.toFixed(4)]);
    // Clear vertical gap between the creature row and the back row.
    const creatureBottom = ROW_Y.creatures - CARD_HEIGHT / 2;
    const backTop = ROW_Y.back + (CARD_HEIGHT * BACK_ROW_SCALE) / 2;
    expect(creatureBottom - backTop).toBeGreaterThanOrEqual(0.3);
    // ...and a clear horizontal gap between the lands and the other permanents.
    const edge = (c: CardPlacement) => ((c.tapped ? CARD_HEIGHT : CARD_WIDTH) * c.scale) / 2;
    const landsRight = Math.max(...cards.filter((c) => c.row === 'lands').map((c) => c.x + edge(c)));
    const otherLeft = Math.min(...cards.filter((c) => c.row === 'other').map((c) => c.x - edge(c)));
    expect(otherLeft - landsRight).toBeGreaterThanOrEqual(0.3);
    // Both seats' creature rows are separated across the center line.
    expect(ROW_Y.creatures + CARD_HEIGHT / 2).toBeLessThan(0);
  });

  it('fits a full row of 8 lands and 6 creatures without overlap at the narrowest table', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    // Eight different lands (identical ones would stack into one slot).
    for (let i = 0; i < 8; i += 1) b.move(`l${i}`, `l${i}`, 'limbo', 'battlefield', 1, 'put');
    for (let i = 0; i < 6; i += 1) b.move(`c${i}`, 'a2', 'limbo', 'battlefield', 1, 'put');
    const lands = Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`l${i}`, card(`Land ${i}`, 'Land')]));
    const stream = b.build({ ...lands, a2: card('Bear', 'Creature', { power: '2', toughness: '2' }) }, { playerSeat: 1 });
    const layout = layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1, tableWidth: MIN_TABLE_WIDTH });
    for (const row of ['lands', 'creatures'] as const) {
      const placed = layout.cards.filter((c) => c.row === row).sort((a, b) => a.x - b.x);
      expect(placed).toHaveLength(row === 'lands' ? 8 : 6);
      for (let i = 1; i < placed.length; i += 1) {
        expect(placed[i].x - placed[i - 1].x).toBeGreaterThanOrEqual(CARD_WIDTH * placed[i].scale);
      }
      expect(placed[0].x - (CARD_WIDTH * placed[0].scale) / 2).toBeGreaterThanOrEqual(layout.table.rowLeft - 1e-9);
      expect(placed.at(-1)!.x + (CARD_WIDTH * placed[0].scale) / 2).toBeLessThanOrEqual(layout.table.rowRight + 1e-9);
    }
  });

  it('puts planeswalkers in the front row, right of the creatures, at full size', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    for (let i = 0; i < 3; i += 1) b.move(`l${i}`, 'a1', 'limbo', 'battlefield', 1, 'put');
    for (let i = 0; i < 3; i += 1) b.move(`c${i}`, 'a2', 'limbo', 'battlefield', 1, 'put');
    b.move('p0', 'a3', 'limbo', 'battlefield', 1, 'put');
    b.move('p1', 'a4', 'limbo', 'battlefield', 1, 'put');
    b.move('e0', 'a5', 'limbo', 'battlefield', 1, 'put');
    const stream = b.build(
      {
        a1: card('Forest', 'Land'),
        a2: card('Bear', 'Creature', { power: '2', toughness: '2' }),
        a3: card('Liliana', 'Planeswalker', { type_line: 'Legendary Planeswalker \u2014 Liliana' }),
        // Type line only (no primary type) is enough.
        a4: card('Nissa', '', { type_line: 'Legendary Planeswalker \u2014 Nissa' }),
        a5: card('Ring', 'Enchantment'),
      },
      { playerSeat: 1 },
    );
    for (const tableWidth of [MIN_TABLE_WIDTH, DEFAULT_TABLE_WIDTH]) {
      const { cards } = layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1, tableWidth });
      const creatures = cards.filter((c) => c.row === 'creatures');
      const walkers = cards.filter((c) => c.row === 'planeswalkers').sort((a, b) => a.x - b.x);
      expect(walkers.map((c) => c.obj)).toEqual(['p0', 'p1']);
      for (const walker of walkers) {
        expect(walker.y).toBeCloseTo(ROW_Y.creatures);
        expect(walker.scale).toBe(1);
      }
      // A clear gap between the last creature and the first planeswalker.
      const creaturesRight = Math.max(...creatures.map((c) => c.x + (CARD_WIDTH * c.scale) / 2));
      expect(walkers[0].x - CARD_WIDTH / 2 - creaturesRight).toBeGreaterThanOrEqual(0.3);
      expect(walkers[1].x - walkers[0].x).toBeGreaterThanOrEqual(CARD_WIDTH);
      // Planeswalkers hug the right edge of the row; creatures stay centered on the table.
      const { table } = layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1, tableWidth });
      expect(walkers[1].x + CARD_WIDTH / 2).toBeCloseTo(table.rowRight, 5);
      // Creatures center on the table when they fit, else in the room left of the planeswalkers.
      const creaturesLeft = Math.min(...creatures.map((c) => c.x - (CARD_WIDTH * c.scale) / 2));
      const creatureCenter = (creaturesLeft + creaturesRight) / 2;
      const roomCenter = (table.rowLeft + walkers[0].x - CARD_WIDTH / 2 - 0.36) / 2;
      expect(Math.min(Math.abs(creatureCenter), Math.abs(creatureCenter - roomCenter))).toBeLessThan(0.01);
      // Other non-creature permanents stay in the back row.
      expect(byObj(cards, 'e0')).toMatchObject({ row: 'other', scale: BACK_ROW_SCALE });
      expect(byObj(cards, 'e0').y).toBeCloseTo(ROW_Y.back);
    }
  });

  it("keeps the opponent's planeswalkers on the viewer's right, mirrored or not", () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    for (let i = 0; i < 2; i += 1) b.move(`c${i}`, 'a2', 'limbo', 'battlefield', 2, 'put');
    b.move('p0', 'a3', 'limbo', 'battlefield', 2, 'put');
    const stream = b.build(
      { a2: card('Bear', 'Creature', { power: '2', toughness: '2' }), a3: card('Liliana', 'Planeswalker') },
      { playerSeat: 1 },
    );
    for (const mirrorOpponent of [false, true]) {
      const layout = layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1, mirrorOpponent });
      const walker = byObj(layout.cards, 'p0');
      const creatures = layout.cards.filter((c) => c.row === 'creatures');
      expect(walker.row).toBe('planeswalkers');
      expect(walker.x + CARD_WIDTH / 2).toBeCloseTo(layout.table.rowRight, 5);
      for (const c of creatures) expect(c.x + CARD_WIDTH / 2).toBeLessThan(walker.x - CARD_WIDTH / 2 - 0.3);
    }
  });

  it('keeps six creatures and two planeswalkers inside the battlefield span at the narrowest table', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    for (let i = 0; i < 6; i += 1) b.move(`c${i}`, 'a2', 'limbo', 'battlefield', 1, 'put');
    for (let i = 0; i < 2; i += 1) b.move(`p${i}`, 'a3', 'limbo', 'battlefield', 1, 'put');
    const stream = b.build(
      { a2: card('Bear', 'Creature', { power: '2', toughness: '2' }), a3: card('Liliana', 'Planeswalker') },
      { playerSeat: 1 },
    );
    const layout = layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1, tableWidth: MIN_TABLE_WIDTH });
    const front = layout.cards.filter((c) => c.y === ROW_Y.creatures).sort((a, b) => a.x - b.x);
    expect(front).toHaveLength(8);
    expect(front.slice(-2).every((c) => c.row === 'planeswalkers')).toBe(true);
    for (const c of front) {
      expect(c.x - CARD_WIDTH / 2).toBeGreaterThanOrEqual(layout.table.rowLeft - 1e-9);
      expect(c.x + CARD_WIDTH / 2).toBeLessThanOrEqual(layout.table.rowRight + 1e-9);
    }
  });

  it('follows the requested table width, clamped to the supported range', () => {
    const state = sampleAt((e) => e.kind === 'block');
    expect(layoutBoard(state, OPTS).table.width).toBe(DEFAULT_TABLE_WIDTH);
    expect(layoutBoard(state, { ...OPTS, tableWidth: 15 }).table).toMatchObject({ width: 15, depth: TABLE_DEPTH });
    expect(layoutBoard(state, { ...OPTS, tableWidth: 2 }).table.width).toBe(MIN_TABLE_WIDTH);
    expect(layoutBoard(state, { ...OPTS, tableWidth: 99 }).table.width).toBe(MAX_TABLE_WIDTH);
    expect(layoutBoard(state, { ...OPTS, tableWidth: Number.NaN }).table.width).toBe(DEFAULT_TABLE_WIDTH);
    // Wider tables keep the pile lane on the left edge and the stack column on the right.
    const narrow = tableGeometry(8);
    const wide = tableGeometry(16);
    expect(wide.rowLeft - -8).toBeCloseTo(narrow.rowLeft - -4);
    expect(wide.stackX).toBeGreaterThan(narrow.stackX);
    expect(wide.stackX).toBeLessThan(8);
  });

  it('centers a short row on the table and overlaps only on overflow, lands first', () => {
    const one = [1];
    // Fits between the pile lane and its mirror: centered on x = 0.
    expect(placeRow([{ widths: [1, 1], gap: 0 }], -3, 4)).toEqual([[-0.5, 0.5]]);
    // Wider than the symmetric span: the whole free span, still packed.
    const [shifted] = placeRow([{ widths: [1, 1, 1, 1, 1, 1, 1], gap: 0 }], -3, 5);
    expect(shifted[0]).toBeCloseTo(-2);
    expect(shifted[6]).toBeCloseTo(4);
    // Overflow: the first group (lands) squeezes; the second keeps its natural spacing.
    const [lands, other] = placeRow([{ widths: [1, 1, 1, 1, 1, 1], gap: 0 }, { widths: [1, 1], gap: 0 }], -3, 3, 0.5);
    expect(other[1] - other[0]).toBeCloseTo(1);
    expect(lands[1] - lands[0]).toBeLessThan(1);
    expect(lands[0] - 0.5).toBeCloseTo(-3);
    expect(other[1] + 0.5).toBeCloseTo(3);
    expect(placeRow([{ widths: one, gap: 0 }, { widths: [], gap: 0 }], -2, 2)).toEqual([[0], []]);
  });

  it('rotates tapped permanents by 90 degrees', () => {
    const state = sampleAt((e) => e.kind === 'tap' && e.objs.length === 2);
    const { cards } = layoutBoard(state, OPTS);
    expect(byObj(cards, '211')).toMatchObject({ tapped: true, rotZ: TAPPED_ROTATION });
    expect(TAPPED_ROTATION).toBeCloseTo(Math.PI / 2);
  });

  it('never shares an x within a row that fits', () => {
    const { cards } = layoutBoard(bigBoard(18), { ...OPTS, playerSeat: 1 });
    for (const row of ['lands', 'creatures', 'other']) {
      const xs = cards.filter((c) => c.row === row).map((c) => c.x.toFixed(4));
      expect(xs.length).toBe(6);
      expect(new Set(xs).size).toBe(xs.length);
    }
  });

  it('keeps a 60-card battlefield on the felt and out of the pile lane by overlapping', () => {
    for (const tableWidth of [MIN_TABLE_WIDTH, DEFAULT_TABLE_WIDTH]) {
      const { cards, table } = layoutBoard(bigBoard(60), { ...OPTS, playerSeat: 1, tableWidth });
      const field = cards.filter((c) => c.zone === 'battlefield');
      expect(field).toHaveLength(60);
      for (const c of field) {
        const halfW = ((c.tapped ? CARD_HEIGHT : CARD_WIDTH) * c.scale) / 2;
        const halfH = ((c.tapped ? CARD_WIDTH : CARD_HEIGHT) * c.scale) / 2;
        expect(c.x - halfW).toBeGreaterThanOrEqual(table.rowLeft - 1e-9);
        expect(c.x + halfW).toBeLessThanOrEqual(table.rowRight + 1e-9);
        expect(Math.abs(c.y) + halfH).toBeLessThanOrEqual(TABLE_DEPTH / 2);
      }
    }
    expect(rowCenters([1, 1, 1], 1)).toEqual([-0.5, 0, 0.5]);
  });

  it('keeps a mirrored opponent\u2019s long rows out of the pile lane', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    for (let i = 0; i < 9; i += 1) b.move(`l${i}`, 'a1', 'limbo', 'battlefield', 2, 'put');
    for (let i = 0; i < 3; i += 1) b.move(`r${i}`, 'a3', 'limbo', 'battlefield', 2, 'put');
    for (let i = 0; i < 7; i += 1) b.move(`c${i}`, 'a2', 'limbo', 'battlefield', 2, 'put');
    const stream = b.build(
      { a1: card('Forest', 'Land'), a2: card('Bear', 'Creature', { power: '2', toughness: '2' }), a3: card('Ring', 'Artifact') },
      { playerSeat: 1 },
    );
    const state = buildTimeline(stream).final;
    for (const mirrorOpponent of [false, true]) {
      const { cards, table } = layoutBoard(state, { ...OPTS, playerSeat: 1, mirrorOpponent, tableWidth: MIN_TABLE_WIDTH });
      for (const c of cards.filter((p) => p.zone === 'battlefield')) {
        expect(c.y).toBeGreaterThan(0);
        expect(c.x - (CARD_WIDTH * c.scale) / 2).toBeGreaterThanOrEqual(table.rowLeft - 1e-9);
        expect(c.x + (CARD_WIDTH * c.scale) / 2).toBeLessThanOrEqual(table.rowRight + 1e-9);
      }
    }
  });

  it('keeps the hands off the felt, past each rail, with the framed part inside the framed depth', () => {
    const opening = sampleAt((e) => e.kind === 'game_start');
    for (const handScale of [undefined, HAND_SCALE_MIN, 1.1, HAND_SCALE_MAX]) {
      const { cards, table } = layoutBoard(opening, { ...OPTS, handScale });
      expect(table.handScale).toBe(handScale ?? HAND_SCALE_MIN);
      const hands = cards.filter((c) => c.row === 'hand');
      expect(hands.length).toBeGreaterThan(0);
      for (const c of hands) {
        const opponent = c.seat !== PLAYER;
        expect(c.scale).toBeLessThanOrEqual(opponent ? OPPONENT_HAND_SCALE : table.handScale);
        expect(c.scale).toBeGreaterThanOrEqual(opponent ? Math.min(HAND_SCALE_FLOOR, OPPONENT_HAND_SCALE) : HAND_SCALE_FLOOR);
        const height = CARD_HEIGHT * c.scale;
        const inner = Math.abs(c.y) - height / 2;
        expect(Math.abs(c.y)).toBeCloseTo(Math.abs(handY(c.scale, opponent)), 1);
        // Each whole hand is framed: the player's reaches onto its felt strip,
        // the opponent's sits just past their stretched land names. Both end
        // inside the framed depth (the fan's curve lowers the outer cards by
        // up to 0.04).
        expect(inner).toBeGreaterThanOrEqual(
          (opponent ? OPPONENT_HAND_INNER : TABLE_DEPTH / 2 - HAND_FELT_OVERLAP) - 0.04 - 1e-9,
        );
        const framed = opponent ? opponentApronDepth() : apronDepth(table.handScale);
        expect(inner + height).toBeLessThanOrEqual(TABLE_DEPTH / 2 + RAIL_WIDTH + framed + 0.04 + 1e-9);
        // Above the tallest pile, so a hand on the felt covers the library beside it.
        expect(c.z).toBeGreaterThan(PILE_CARD_DEPTH * PILE_MAX_CARDS);
      }
    }
    // The whole felt belongs to the battlefield and the piles.
    const { cards } = layoutBoard(opening, OPTS);
    for (const c of cards.filter((p) => p.zone === 'battlefield' || p.row === 'pile')) {
      expect(Math.abs(c.y) + (CARD_HEIGHT * c.scale) / 2).toBeLessThanOrEqual(TABLE_DEPTH / 2);
    }
  });

  it('draws a seven-card hand at the stage\u2019s hand scale and shrinks a crowded hand to fit its lane', () => {
    const handOf = (size: number, handScale: number, tableWidth = MIN_TABLE_WIDTH) => {
      const b = new StreamBuilder();
      b.add('game_start', { seats_hand_sizes: { 1: size, 2: size }, library_sizes: { 1: 40, 2: 40 } });
      const state = buildTimeline(b.build({}, { playerSeat: 1 })).final;
      const { cards, table } = layoutBoard(state, { ...OPTS, playerSeat: 1, handScale, tableWidth });
      return { mine: cards.filter((c) => c.row === 'hand' && c.seat === 1), theirs: cards.filter((c) => c.row === 'hand' && c.seat === 2), table };
    };
    const lane = (table: ReturnType<typeof handOf>['table']) => table.width - 1;
    const extent = (hand: CardPlacement[]) => {
      const xs = hand.map((c) => c.x);
      const half = (CARD_WIDTH * hand[0].scale) / 2;
      return { left: Math.min(...xs) - half, right: Math.max(...xs) + half };
    };
    // Seven cards at the largest hand scale: big, each showing at least HAND_MIN_VISIBLE of its width.
    const big = handOf(7, HAND_SCALE_MAX);
    expect(big.mine).toHaveLength(7);
    expect(big.mine[0].scale).toBeGreaterThan(1.6);
    // The opponent's hand (card backs) stays small, Arena style, unless the stage gives it a larger scale.
    expect(big.theirs[0].scale).toBe(OPPONENT_HAND_SCALE);
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 7, 2: 7 }, library_sizes: { 1: 40, 2: 40 } });
    const state = buildTimeline(b.build({}, { playerSeat: 1 })).final;
    const large = layoutBoard(state, { ...OPTS, playerSeat: 1, handScale: 1, opponentHandScale: 1, tableWidth: DEFAULT_TABLE_WIDTH });
    const theirs = large.cards.filter((c) => c.row === 'hand' && c.seat === 2);
    expect(theirs[0].scale).toBe(1);
    expect(Math.abs(theirs[0].y)).toBeCloseTo(Math.abs(handY(1, true)), 1);
    const step = big.mine[1].x - big.mine[0].x;
    expect(step).toBeGreaterThanOrEqual(HAND_MIN_VISIBLE * CARD_WIDTH * big.mine[0].scale - 1e-9);
    expect(extent(big.mine).left).toBeGreaterThanOrEqual(-lane(big.table) / 2 - 1e-9);
    expect(extent(big.mine).right).toBeLessThanOrEqual(lane(big.table) / 2 + 1e-9);
    // Fifteen cards shrink below even the smallest stage scale (never below the floor) and stay inside the lane.
    const crowded = handOf(15, HAND_SCALE_MAX);
    expect(crowded.mine).toHaveLength(15);
    expect(crowded.mine[0].scale).toBeLessThan(HAND_SCALE_MIN);
    expect(crowded.mine[0].scale).toBeGreaterThanOrEqual(HAND_SCALE_FLOOR);
    expect(extent(crowded.mine).left).toBeGreaterThanOrEqual(-lane(crowded.table) / 2 - 1e-9);
    expect(extent(crowded.mine).right).toBeLessThanOrEqual(lane(crowded.table) / 2 + 1e-9);
    expect(new Set(crowded.mine.map((c) => c.x.toFixed(3))).size).toBe(15);
    // A wider table gives the same hand more room: larger cards.
    expect(handOf(15, HAND_SCALE_MAX, DEFAULT_TABLE_WIDTH).mine[0].scale).toBeGreaterThan(crowded.mine[0].scale);
    // A single card never exceeds the stage's hand scale.
    expect(handOf(1, 1.1).mine[0].scale).toBeCloseTo(1.1, 9);
  });

  it('tucks a card exiled by a permanent under that permanent, back to the pile once the host leaves', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 1, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('bat', 'a2', 'limbo', 'battlefield', 2, 'put');
    b.move('isl', 'a1', 'hand', 'exile', 1, 'exile', { with: 'bat' });
    b.move('frs', 'a1', 'library', 'exile', 1, 'exile');
    b.move('bat', 'a2', 'battlefield', 'graveyard', 2, 'destroy');
    const stream = b.build(
      { a1: card('Island', 'Land'), a2: card('Deep-Cavern Bat', 'Creature', { power: '1', toughness: '1' }) },
      { playerSeat: 1 },
    );
    const tl = buildTimeline(stream);
    const moves = stream.events.filter((e) => e.kind === 'move');
    const under = layoutBoard(stateAt(tl, moves[2].seq), { ...OPTS, playerSeat: 1 });
    const bat = under.cards.find((c) => c.obj === 'bat')!;
    const tucked = under.cards.find((c) => c.obj === 'isl')!;
    expect(tucked.zone).toBe('exile');
    expect(tucked.row).toBe(bat.row);
    // Right behind the host, like an aura, not in the pile lane.
    expect(Math.abs(tucked.x - bat.x)).toBeLessThan(CARD_WIDTH);
    expect(Math.abs(tucked.y - bat.y)).toBeLessThan(CARD_HEIGHT / 2);
    expect(tucked.z).toBeLessThan(bat.z);
    // The host lists what is under it (for the hover preview); the tucked card lists nothing.
    expect(bat.under).toEqual([{ obj: 'isl', card: 'a1', zone: 'exile' }]);
    expect(tucked.under).toEqual([]);
    const exilePile = under.piles.find((p) => p.seat === 1 && p.zone === 'exile')!;
    expect(exilePile.count).toBe(1);
    expect(under.cards.find((c) => c.obj === 'frs')?.row).toBe('pile');
    // The host dies: the card is plain exile again (only the pile's top card is drawn).
    const after = layoutBoard(stateAt(tl, moves[3].seq), { ...OPTS, playerSeat: 1 });
    expect(after.cards.some((c) => c.obj === 'isl' && c.row !== 'pile')).toBe(false);
    expect(after.piles.find((p) => p.seat === 1 && p.zone === 'exile')?.count).toBe(2);
  });

  it('reports pile counts and top cards', () => {
    const state = sampleAt((e) => e.kind === 'game_end');
    const { piles, cards } = layoutBoard(state, OPTS);
    const pile = (seat: number, zone: string) => piles.find((p) => p.seat === seat && p.zone === zone);
    expect(pile(PLAYER, 'library')?.count).toBe(state.seats[PLAYER].librarySize);
    expect(pile(PLAYER, 'graveyard')).toMatchObject({ count: 1, topCard: 'a1002' });
    expect(pile(OPPONENT, 'graveyard')).toMatchObject({ count: 3, topCard: 'a1006' });
    expect(pile(OPPONENT, 'graveyard')!.y).toBeGreaterThan(0);
    expect(byObj(cards, '104').row).toBe('pile');
    expect(cards.some((c) => c.obj === '102')).toBe(false);
  });

  it('stands the piles in a left lane: opponent top-left, player bottom-left, library at the edge', () => {
    const state = sampleAt((e) => e.kind === 'game_end');
    const { piles, table } = layoutBoard(state, OPTS);
    expect(piles.map((p) => p.zone)).not.toContain('command');
    for (const p of piles) {
      expect(p.x + (CARD_WIDTH * p.scale) / 2).toBeLessThan(table.rowLeft);
      expect(Math.sign(p.y)).toBe(p.seat === PLAYER ? -1 : 1);
    }
    const ys = (seat: number) => piles.filter((p) => p.seat === seat).map((p) => Math.abs(p.y));
    // Library, graveyard, exile from the table edge toward the center, without overlapping.
    for (const seat of [PLAYER, OPPONENT]) {
      const [library, graveyard, exile] = ys(seat);
      expect(library).toBeGreaterThan(graveyard);
      expect(graveyard).toBeGreaterThan(exile);
      expect(graveyard - exile).toBeGreaterThan(CARD_HEIGHT * piles[0].scale);
      expect(exile - (CARD_HEIGHT * piles[0].scale) / 2).toBeGreaterThan(0);
    }
    // Commander formats get a fourth (smaller) pile, still inside the seat's half.
    const withCommand = layoutBoard(state, { ...OPTS, commandZone: true });
    const command = withCommand.piles.filter((p) => p.zone === 'command');
    expect(command).toHaveLength(2);
    for (const p of command) expect(Math.abs(p.y) - (CARD_HEIGHT * p.scale) / 2).toBeGreaterThan(0);
    expect(usesCommandZone(makeSampleStream())).toBe(false);
    const brawl = makeSampleStream();
    brawl.seats[String(PLAYER)].commanders = ['Some Commander'];
    expect(usesCommandZone(brawl)).toBe(true);
  });

  it('nests attachments behind their host, even across sides', () => {
    const state = sampleAt((e) => e.kind === 'attach');
    const { cards } = layoutBoard(state, OPTS);
    const host = byObj(cards, '215');
    const aura = byObj(cards, '106');
    expect(aura.seat).toBe(OPPONENT);
    expect(aura.y).toBeLessThan(0);
    expect(aura.x).toBeGreaterThan(host.x);
    expect(aura.z).toBeLessThan(host.z);
  });

  it('piles more than two cards exiled by a noncreature artifact, with a count, but always fans them under a creature', () => {
    const tuckUnder = (host: string, type: string, count: number) => {
      const b = new StreamBuilder();
      b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
      b.move('host', 'a2', 'limbo', 'battlefield', 2, 'put');
      for (let i = 0; i < count; i += 1) b.move(`x${i}`, 'a1', 'library', 'exile', 1, 'exile', { with: 'host' });
      const extra = type === 'Creature' ? { power: '1', toughness: '1' } : {};
      const stream = b.build({ a1: card('Bear', 'Creature', { power: '2', toughness: '2' }), a2: card(host, type, extra) }, { playerSeat: 1 });
      const tl = buildTimeline(stream);
      return layoutBoard(stateAt(tl, stream.events[stream.events.length - 1].seq), { ...OPTS, playerSeat: 1 });
    };
    const pile = tuckUnder('Pinnacle Starcage', 'Artifact', 6);
    const cage = byObj(pile.cards, 'host');
    expect(cage.tuckedCount).toBe(6);
    expect(cage.under).toHaveLength(6);
    const edges = pile.cards.filter((c) => c.obj.startsWith('x'));
    expect(edges.every((c) => c.stackedUnder === 'host')).toBe(true);
    // Two edges show, however many cards it holds: the rest square up behind the second.
    expect(new Set(edges.map((c) => c.y.toFixed(6))).size).toBe(2);
    expect(sceneLabels(pile, {}).some((l) => l.id === 'tucked:host' && l.text === '6 under')).toBe(true);

    const two = tuckUnder('Pinnacle Starcage', 'Artifact', 2);
    expect(byObj(two.cards, 'host').tuckedCount).toBeUndefined();
    expect(two.cards.some((c) => c.stackedUnder === 'host')).toBe(false);

    const bat = tuckUnder('Deep-Cavern Bat', 'Creature', 4);
    expect(byObj(bat.cards, 'host').tuckedCount).toBeUndefined();
    expect(new Set(bat.cards.filter((c) => c.obj.startsWith('x')).map((c) => c.y.toFixed(6))).size).toBe(4);
  });

  it('fans tucked cards upward on screen for either seat, sliding the host and compressing so the fan stays out of the next row', () => {
    const build = (seat: number, count: number) => {
      const b = new StreamBuilder();
      b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
      b.move('host', 'a1', 'limbo', 'battlefield', seat, 'put');
      for (let i = 0; i < count; i += 1) {
        b.move(`eq${i}`, 'a2', 'limbo', 'battlefield', seat, 'put');
        b.add('attach', { obj: `eq${i}`, to: 'host' });
      }
      const stream = b.build(
        { a1: card('Tidecaller', 'Creature', { power: '0', toughness: '2' }), a2: card('Sword', 'Artifact', { type_line: 'Artifact — Equipment' }) },
        { playerSeat: 1 },
      );
      return layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1 }).cards;
    };
    for (const seat of [1, 2]) {
      // Room before the next row: the opponent's fan rises toward their lands, the player's toward the center.
      const room = seat === 2 ? 0.36 - 0.04 : 0.52 - 0.04;
      const plainHost = byObj(build(seat, 1), 'host');

      // Three cards: whole title strips, the host slid a little away from the fan to make room.
      const three = build(seat, 3);
      const host3 = byObj(three, 'host');
      const fan3 = [0, 1, 2].map((i) => byObj(three, `eq${i}`));
      expect(host3.under.map((u) => u.obj)).toEqual(['eq0', 'eq1', 'eq2']);
      expect(host3.under.every((u) => u.zone === 'battlefield' && u.card === 'a2')).toBe(true);
      fan3.forEach((c, i) => expect(c.y - (i === 0 ? host3 : fan3[i - 1]).y).toBeCloseTo(0.17, 6));
      expect(plainHost.y - host3.y).toBeGreaterThan(0);
      expect(plainHost.y - host3.y).toBeLessThanOrEqual(0.2 + 1e-9);
      expect(fan3[2].y - plainHost.y).toBeLessThanOrEqual(room + 1e-9);

      // Five cards: the slide maxes out at 0.2 and the strips compress, still inside the gap.
      const five = build(seat, 5);
      const host5 = byObj(five, 'host');
      const fan5 = [0, 1, 2, 3, 4].map((i) => byObj(five, `eq${i}`));
      expect(plainHost.y - host5.y).toBeCloseTo(0.2, 6);
      for (let i = 0; i < fan5.length; i += 1) {
        const below = i === 0 ? host5 : fan5[i - 1];
        expect(fan5[i].y - below.y).toBeGreaterThan(0.1);
        expect(fan5[i].y - below.y).toBeLessThan(0.17);
        expect(fan5[i].z).toBeLessThan(below.z);
      }
      expect(fan5[4].y - plainHost.y).toBeLessThanOrEqual(room + 1e-9);
      // Barely any sideways spread: the fan does not crowd the neighbour.
      expect(Math.abs(fan5[4].x - host5.x)).toBeLessThan(0.3);
    }
  });

  it('stacks spells in a column under the stack preview, top item highest, with targets highlighted', () => {
    const state = sampleAt((e) => e.kind === 'stack_push' && e.stack_id === 's2');
    const { cards, table } = layoutBoard(state, OPTS);
    const stack = cards.filter((c) => c.row === 'stack');
    expect(stack.map((c) => c.obj).sort()).toEqual(['102', '212']);
    expect(byObj(cards, '102').z).toBeGreaterThan(byObj(cards, '212').z);
    expect(byObj(cards, '212')).toMatchObject({ x: table.stackX, highlight: 'targeted', scale: STACK_SCALE });
    // Right edge of the felt, on the opponent's side of center (under the preview's top card).
    expect(table.stackX + (CARD_WIDTH * STACK_SCALE) / 2).toBeLessThan(table.width / 2);
    expect(table.stackX).toBeGreaterThan(table.rowRight - CARD_WIDTH);
    expect(byObj(cards, '212').y).toBeGreaterThan(0);
  });

  it('places abilities on the stack under a synthetic key', () => {
    const state = sampleAt((e) => e.kind === 'stack_push' && e.stack_id === 's5');
    const { cards } = layoutBoard(state, OPTS);
    expect(byObj(cards, 'stack:s5')).toMatchObject({ card: 'a1010', row: 'stack', faceUp: true });
    expect(byObj(cards, '215').row).toBe('creatures');
  });

  it('draws an ability as a small chip of its source card, never a second full card', () => {
    const state = sampleAt((e) => e.kind === 'stack_push' && e.stack_id === 's5');
    const layout = layoutBoard(state, OPTS);
    const chip = byObj(layout.cards, 'stack:s5');
    expect(chip.scale).toBeCloseTo(STACK_SCALE * ABILITY_CHIP_SCALE);
    expect(chip.x).toBe(layout.table.stackX);
  });

  it('keeps a spell as its own card when its cast trigger goes on the stack above it', () => {
    // Reconstructed streams push "whenever you cast" triggers whose source is
    // the spell itself, before that spell resolves.
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 1, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('r:1', 'a1', 'library', 'hand', 1, 'draw');
    b.turnStart(1, 1);
    b.cast('r:1', 'a1', 1, 's1');
    b.add('stack_push', {
      stack_id: 's2',
      obj: 'r:1',
      card: 'a1',
      stack_kind: 'trigger',
      controller: 1,
      text: 'Whenever you cast a spell, draw a card.',
      targets: [],
    });
    const stream = b.build({ a1: card('Octopus Form', 'Instant') }, { playerSeat: 1 });
    const state = buildTimeline(stream).final;
    const layout = layoutBoard(state, { ...OPTS, playerSeat: 1 });
    const stack = layout.cards.filter((c) => c.row === 'stack');
    expect(stack.map((c) => c.obj).sort()).toEqual(['r:1', 'stack:s2']);
    const spell = byObj(layout.cards, 'r:1');
    const chip = byObj(layout.cards, 'stack:s2');
    expect(spell.scale).toBeCloseTo(STACK_SCALE);
    expect(chip).toMatchObject({ card: 'a1', faceUp: true });
    expect(chip.scale).toBeLessThanOrEqual(spell.scale / 2 + 1e-9);
    expect(chip.z).toBeGreaterThan(spell.z);
    // The preview lists the trigger (top) above the spell it came from.
    expect(stackView(state).map((item) => [item.kind, item.name, item.text, item.top])).toEqual([
      ['trigger', 'Octopus Form', 'Whenever you cast a spell, draw a card.', true],
      ['spell', 'Octopus Form', null, false],
    ]);
  });

  it('shows hidden hands as backs and applies hindsight on request', () => {
    const opening = sampleAt((e) => e.kind === 'game_start');
    const hidden = layoutBoard(opening, OPTS).cards.filter((c) => c.obj.startsWith('hidden:'));
    expect(hidden).toHaveLength(14);
    expect(hidden.every((c) => !c.faceUp && c.rotY === Math.PI)).toBe(true);

    const state = sampleAt((e) => e.kind === 'turn');
    expect(byObj(layoutBoard(state, OPTS).cards, '102').faceUp).toBe(false);
    const seen = byObj(layoutBoard(state, { ...OPTS, hindsight: true }).cards, '102');
    expect(seen).toMatchObject({ faceUp: true, card: 'a1008', row: 'hand' });
    expect(seen.y).toBeGreaterThan(0);
  });

  it('lays out 60 objects in well under 5 ms', () => {
    const state = bigBoard(60);
    const runs = 200;
    let average = Infinity;
    for (let round = 0; round < 3; round += 1) {
      const started = performance.now();
      for (let i = 0; i < runs; i += 1) layoutBoard(state, { ...OPTS, playerSeat: 1 });
      average = Math.min(average, (performance.now() - started) / runs);
    }
    console.info(`[replay perf] layoutBoard 60 objects: ${average.toFixed(3)} ms average`);
    expect(average).toBeLessThan(5);
  });
});

describe('side cards beside the hand', () => {
  function sideBoard(extra: (b: StreamBuilder) => void = () => {}) {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('h1', 'bear', 'limbo', 'hand', PLAYER, 'draw');
    b.move('g1', 'looting', 'limbo', 'graveyard', PLAYER, 'put');
    b.move('g2', 'bear', 'limbo', 'graveyard', PLAYER, 'put');
    b.move('p1', 'show', 'limbo', 'hand', PLAYER, 'draw');
    b.move('p1', 'show', 'hand', 'exile', PLAYER, 'exile');
    b.move('x1', 'show', 'limbo', 'battlefield', PLAYER, 'put');
    b.move('x1', 'show', 'battlefield', 'exile', PLAYER, 'exile');
    b.move('o1', 'looting', 'limbo', 'graveyard', OPPONENT, 'put');
    // The next action ends the exile's effect window (x1 is no longer held on the battlefield).
    b.phaseTo('Phase_Main1');
    extra(b);
    const stream = b.build(
      {
        bear: card('Bear', 'Creature', { power: '2', toughness: '2' }),
        looting: card('Faithless Looting', 'Sorcery', { keywords: ['flashback'] }),
        show: card('Slickshot Show-Off', 'Creature', { keywords: ['plot'] }),
      },
      { playerSeat: PLAYER },
    );
    return layoutBoard(buildTimeline(stream).final, OPTS);
  }

  it('shows flashback and plotted cards to the right of their hand, marked', () => {
    const layout = sideBoard();
    const hand = byObj(layout.cards, 'h1');
    const flashback = byObj(layout.cards, 'g1');
    const plotted = byObj(layout.cards, 'p1');
    expect([flashback.row, flashback.castable, flashback.zone]).toEqual(['castable', 'flashback', 'graveyard']);
    expect([plotted.row, plotted.castable, plotted.zone]).toEqual(['castable', 'plot', 'exile']);
    expect(flashback.x).toBeGreaterThan(hand.x);
    expect(plotted.x).toBeGreaterThan(hand.x);
    expect(flashback.y).toBeCloseTo(hand.y, 1);
    expect(hand.castable).toBeNull();
  });

  it('keeps them counted on their piles, which show the card underneath', () => {
    const layout = sideBoard();
    const graveyard = layout.piles.find((p) => p.seat === PLAYER && p.zone === 'graveyard');
    expect(graveyard?.count).toBe(2);
    expect(graveyard?.topCard).toBe('bear');
    expect(byObj(layout.cards, 'g2').row).toBe('pile');
    expect(layout.cards.filter((c) => c.obj === 'g1')).toHaveLength(1);
  });

  it('leaves a plot card exiled from the battlefield on the exile pile', () => {
    const exiled = byObj(sideBoard().cards, 'x1');
    expect([exiled.row, exiled.castable]).toEqual(['pile', null]);
  });

  it('marks the opponent side too, and drops a card once it is cast', () => {
    const before = byObj(sideBoard().cards, 'o1');
    expect(before.castable).toBe('flashback');
    const after = sideBoard((b) => b.move('g1', 'looting', 'graveyard', 'stack', PLAYER, 'cast'));
    expect(byObj(after.cards, 'g1').castable).toBeNull();
  });

  it('shows a card its own text lets its owner cast from exile', () => {
    // Emrakul, the Exigent Doom exiles itself from the hand; Eternal Scourge
    // may be cast from exile however it got there.
    const cards = {
      emrakul: card('Emrakul, the Exigent Doom', 'Creature', { keywords: ['cast_while_exiled'] }),
      scourge: card('Eternal Scourge', 'Creature', { keywords: ['cast_from_exile'] }),
    };
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('e1', 'emrakul', 'limbo', 'hand', PLAYER, 'draw');
    b.move('e1', 'emrakul', 'hand', 'exile', PLAYER, 'exile');
    b.move('e2', 'emrakul', 'limbo', 'battlefield', PLAYER, 'put');
    b.move('e2', 'emrakul', 'battlefield', 'exile', PLAYER, 'exile');
    b.move('s1', 'scourge', 'limbo', 'battlefield', PLAYER, 'put');
    b.move('s1', 'scourge', 'battlefield', 'exile', PLAYER, 'exile');
    b.phaseTo('Phase_Main1');
    const layout = layoutBoard(buildTimeline(b.build(cards, { playerSeat: PLAYER })).final, OPTS);
    expect([byObj(layout.cards, 'e1').row, byObj(layout.cards, 'e1').castable]).toEqual([
      'castable',
      'cast_from_exile',
    ]);
    expect(byObj(layout.cards, 'e2').row).toBe('pile');
    expect(byObj(layout.cards, 's1').castable).toBe('cast_from_exile');
  });
});

describe('flying', () => {
  function skies(extra: (b: StreamBuilder) => void = () => {}) {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('drake', 'drake', 'limbo', 'battlefield', PLAYER, 'put');
    b.move('aura', 'aura', 'limbo', 'battlefield', PLAYER, 'put');
    b.add('attach', { obj: 'aura', to: 'drake' });
    b.move('bear', 'bear', 'limbo', 'battlefield', PLAYER, 'put');
    b.move('wall', 'wall', 'limbo', 'battlefield', OPPONENT, 'put');
    extra(b);
    const stream = b.build(
      {
        drake: card('Drake', 'Creature', { power: '2', toughness: '2', keywords: ['flying'] }),
        aura: card('Pacifism', 'Enchantment', { type_line: 'Enchantment — Aura' }),
        bear: card('Bear', 'Creature', { power: '2', toughness: '2' }),
        wall: card('Wall', 'Creature', { power: '0', toughness: '4' }),
      },
      { playerSeat: PLAYER },
    );
    return layoutBoard(buildTimeline(stream).final, OPTS).cards;
  }

  it('lifts a flying creature off the felt, its tucked cards with it', () => {
    const cards = skies();
    const drake = byObj(cards, 'drake');
    const bear = byObj(cards, 'bear');
    expect(drake.flying).toBe(true);
    expect(bear.flying).toBe(false);
    expect(drake.z - bear.z).toBeGreaterThan(FLYING_LIFT - 0.01);
    const aura = byObj(cards, 'aura');
    expect(aura.flying).toBe(false);
    expect(aura.z).toBeLessThan(drake.z);
    expect(aura.z).toBeGreaterThan(bear.z + FLYING_LIFT - 0.02);
  });

  it('lifts a creature given a flying counter', () => {
    const cards = skies((b) => b.add('counter', { obj: 'wall', type: 'flying', delta: 1, total: 1 }));
    expect(byObj(cards, 'wall').flying).toBe(true);
    expect(byObj(skies(), 'wall').flying).toBe(false);
  });
});

describe('damage marks', () => {
  function burned(extra: (b: StreamBuilder) => void = () => {}) {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    b.move('c1', 'bear', 'limbo', 'battlefield', OPPONENT, 'put');
    b.move('c2', 'bear', 'limbo', 'battlefield', OPPONENT, 'put');
    b.move('c3', 'bear', 'limbo', 'battlefield', PLAYER, 'put');
    b.move('s1', 'smaug', 'limbo', 'hand', PLAYER, 'draw');
    b.cast('s1', 'smaug', PLAYER, 'st1');
    b.resolve('s1', 'smaug', PLAYER, 'st1', 'graveyard');
    for (const obj of ['c1', 'c2']) {
      b.add('damage', { source: null, target_obj: obj, target_seat: null, amount: 6, combat: false });
    }
    b.add('damage', { source: null, target_obj: 'c1', target_seat: null, amount: 2, combat: false });
    extra(b);
    const stream = b.build(
      { bear: card('Bear', 'Creature', { power: '2', toughness: '2' }), smaug: card('Desolation of Smaug', 'Sorcery') },
      { playerSeat: PLAYER },
    );
    return buildTimeline(stream).final;
  }

  it('marks every permanent one burst hit, summed, with the damage glow', () => {
    const state = burned();
    expect([...state.effects.objects].map(([obj, m]) => [obj, m.damage])).toEqual([
      ['c1', 8],
      ['c2', 6],
    ]);
    const { cards } = layoutBoard(state, OPTS);
    expect([byObj(cards, 'c1').damage, byObj(cards, 'c1').highlight]).toEqual([8, 'damaged']);
    expect([byObj(cards, 'c2').damage, byObj(cards, 'c2').highlight]).toEqual([6, 'damaged']);
    expect([byObj(cards, 'c3').damage, byObj(cards, 'c3').highlight]).toEqual([null, null]);
  });

  it('holds a creature that dies of the damage in its slot, dimmed as Died, until the next action', () => {
    const dying = burned((b) => b.move('c2', 'bear', 'battlefield', 'graveyard', OPPONENT, 'sba'));
    expect(dying.effects.objects.get('c1')?.damage).toBe(8);
    expect(dying.seats[OPPONENT].zones.graveyard).toEqual(['c2']);
    const held = layoutBoard(dying, OPTS).cards.filter((c) => c.obj === 'c2');
    expect(held.map((c) => [c.zone, c.row, c.damage, c.removed])).toEqual([['battlefield', 'creatures', 6, 'died']]);
    const next = burned((b) => {
      b.move('c2', 'bear', 'battlefield', 'graveyard', OPPONENT, 'sba');
      b.turnStart(2, OPPONENT);
    });
    expect(next.effects.objects.size).toBe(0);
    const gone = layoutBoard(next, OPTS).cards.filter((c) => c.obj === 'c2');
    expect(gone.map((c) => [c.zone, c.row, c.removed])).toEqual([['graveyard', 'pile', null]]);
  });
});

describe('identical lands', () => {
  it('stack by name, untapped and tapped apart', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
    // Two printings of Mountain, one Plains.
    for (const [obj, key] of [['m1', 'a1'], ['m2', 'a2'], ['m3', 'a1'], ['m4', 'a1'], ['m5', 'a2'], ['p1', 'a3']]) {
      b.move(obj, key, 'limbo', 'battlefield', 1, 'play_land');
    }
    b.add('tap', { objs: ['m4', 'm5'] });
    const stream = b.build({ a1: card('Mountain', 'Land'), a2: card('Mountain', 'Land'), a3: card('Plains', 'Land') }, { playerSeat: 1 });
    const cards = layoutBoard(buildTimeline(stream).final, { ...OPTS, playerSeat: 1 }).cards;
    const byObj = new Map(cards.map((c) => [c.obj, c]));
    expect(byObj.get('m1')).toMatchObject({ stackCount: 3, tapped: false });
    expect(['m2', 'm3'].map((obj) => byObj.get(obj)?.stackedUnder)).toEqual(['m1', 'm1']);
    expect(byObj.get('m4')).toMatchObject({ stackCount: 2, tapped: true });
    expect(byObj.get('m5')?.stackedUnder).toBe('m4');
    expect(byObj.get('p1')?.stackCount).toBeUndefined();
  });
});

describe('identical tokens', () => {
  it('stack under the first one and take one slot, apart from a token that differs', () => {
    const layout = layoutBoard(buildTimeline(makeTokenStream()).final, { ...OPTS, playerSeat: 1 });
    const byObj = new Map(layout.cards.map((c) => [c.obj, c]));
    expect(byObj.get('t1')).toMatchObject({ stackCount: 3 });
    expect(byObj.get('t2')).toMatchObject({ stackedUnder: 't1' });
    expect(byObj.get('t3')).toMatchObject({ stackedUnder: 't1' });
    // The one without counters keeps its own slot.
    expect(byObj.get('t4')?.stackCount).toBeUndefined();
    expect(byObj.get('t4')?.stackedUnder).toBeUndefined();
    // The stacked ones fan just off the top card, under it.
    const top = byObj.get('t1')!;
    const second = byObj.get('t2')!;
    expect(Math.abs(second.x - top.x)).toBeLessThan(0.2);
    expect(second.z).toBeLessThan(top.z);
    expect(Math.abs(byObj.get('t4')!.x - top.x)).toBeGreaterThan(CARD_HEIGHT * 0.9);
  });
});
