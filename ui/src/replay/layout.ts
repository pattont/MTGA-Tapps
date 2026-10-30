/**
 * Deterministic table layout: BoardState -> placed cards and piles
 * (docs/REPLAY_FORMAT.md §3). Renderer-agnostic; the WebGL scene only draws
 * what this returns.
 *
 * Units: the table is TABLE_DEPTH deep (y) and `tableWidth` wide (x; it
 * follows the stage's aspect, see scene/cameraFit `fitTableForView`),
 * origin at the center, +y toward the opponent, z up. Each seat has two
 * battlefield tiers (Arena style): creatures in front with planeswalkers to
 * their right (after a gap), then after a clear gap a back row of lands
 * followed by the other permanents; the hand sits on an apron just past the
 * near rail, off the felt (the camera frames the aprons too, see
 * scene/cameraFit), and the library/graveyard/exile/command piles stand in a
 * lane on the left, keeping the right side free for the stack preview. Positions are
 * computed in "seat-local" coordinates for the player's half (y < 0) and
 * mapped to the opponent's half by reflecting y, or by a full 180° turn (x and
 * y, plus rotZ + π) when `mirrorOpponent` is on (piles stay in the left lane).
 */
import type { ObjectMarks, RemovalKind, SeatMarks } from './effects';
import type { BoardState, ObjectState, StackItem } from './reducer';
import type { CardKey, ObjId, ReplayCard, ReplayStream, Zone } from './types';

export const CARD_WIDTH = 0.86;
export const CARD_HEIGHT = 1.2;
/** Rotation (radians) of a tapped card. */
export const TAPPED_ROTATION = Math.PI / 2;

/** Felt depth: two battlefield tiers per seat. Fixed, so card size on screen is set by the stage height. */
export const TABLE_DEPTH = 6.4;
/** Wooden rail around the felt; the hands rest just past it. */
export const RAIL_WIDTH = 0.3;
/** Width used until the stage has been measured (and by tests). */
export const DEFAULT_TABLE_WIDTH = 12;
/** Narrowest table: the pile lane plus a row of six untapped creatures. */
export const MIN_TABLE_WIDTH = 7.2;
/** Ultra-wide stages stop widening the felt here. */
export const MAX_TABLE_WIDTH = 22;

/** Half the gap between the two creature rows (attackers step into it). */
const CENTER_GAP = 0.26;
const ATTACK_OFFSET = 0.3;
/** Clear gap between the creature row and the lands/permanents row. */
const BACK_ROW_GAP = 0.36;
/** Lands and other permanents are drawn slightly smaller than creatures. */
export const BACK_ROW_SCALE = 0.84;
/**
 * Hand card scale. The stage decides it (scene/cameraFit `fitTableForView`):
 * at least HAND_SCALE_MIN when the table alone fills the stage height, up to
 * HAND_SCALE_MAX when a tall stage leaves room past the rails.
 */
export const HAND_SCALE_MIN = 1;
export const HAND_SCALE_MAX = 1.7;
/** A crowded hand shrinks down to this before its cards hide more of each other. */
export const HAND_SCALE_FLOOR = 0.6;
/** Fanned hand cards keep at least this fraction of their width visible before the hand shrinks. */
export const HAND_MIN_VISIBLE = 0.55;
const HAND_STEP_GAP = 0.05;
/** The fan may use the table's width (it is off the felt, clear of the piles) up to this margin at each side. */
const HAND_SIDE_MARGIN = 0.5;
/**
 * Arena-style framing: each hand reaches this far onto the felt (over the
 * empty strip past that seat's lands) so the whole card shows, while the frame
 * past it stays short. The camera frames just past its outer edge.
 */
export const HAND_FELT_OVERLAP = 0.3;
const APRON_MARGIN = 0.04;
/**
 * The opponent's hand is drawn smaller than the player's: OPPONENT_HAND_SCALE
 * on a stage of ordinary resolution, growing to OPPONENT_HAND_SCALE_LARGE on a
 * tall high-resolution stage (scene/cameraFit `opponentHandBase`) and with the
 * player's hand on a narrow one. The stage decides it (`opts.opponentHandScale`).
 */
export const OPPONENT_HAND_SCALE = 0.75;
export const OPPONENT_HAND_SCALE_LARGE = 1;
/** Each card in a pile adds this much height, up to PILE_MAX_CARDS (the scene draws piles as boxes). */
export const PILE_CARD_DEPTH = 0.004;
export const PILE_MAX_CARDS = 60;
/** Hand cards float above the tallest pile, so a hand reaching onto the felt covers the library beside it. */
export const HAND_Z = PILE_CARD_DEPTH * PILE_MAX_CARDS + 0.02;
const ROW_GAP = 0.12;
const LAND_GAP = 0.06;
/** Space between the lands and the other permanents in the back row. */
const GROUP_GAP = 0.5;
/** Space between the last creature and the first planeswalker in the front row. */
const PLANESWALKER_GAP = 0.36;
/** Planeswalkers never take more than this share of the row; beyond it they overlap. */
const MAX_PLANESWALKER_SHARE = 0.45;
/** Overlapped cards keep at least this fraction of their width visible. */
const MIN_VISIBLE = 0.32;

/** Seat-local row centers (player half, y < 0). */
export const ROW_Y = {
  creatures: -(CENTER_GAP + CARD_HEIGHT / 2),
  back: -(CENTER_GAP + CARD_HEIGHT + BACK_ROW_GAP + (CARD_HEIGHT * BACK_ROW_SCALE) / 2),
} as const;
export function clampOpponentHandScale(scale: number | undefined): number {
  if (scale === undefined || !Number.isFinite(scale)) return OPPONENT_HAND_SCALE;
  return Math.min(HAND_SCALE_MAX, Math.max(OPPONENT_HAND_SCALE, scale));
}

export function clampHandScale(scale: number | undefined): number {
  if (scale === undefined || !Number.isFinite(scale)) return HAND_SCALE_MIN;
  return Math.min(HAND_SCALE_MAX, Math.max(HAND_SCALE_MIN, scale));
}

/**
 * Depth stretch the tilted camera's correction puts on the far side (scene/motion
 * `depthStretch`, which every card gets so it keeps its true proportions): about
 * 1.3 on the opponent's back row and up to cameraFit `FAR_STRETCH` (1.346) at
 * the far edge. The opponent's hand is placed and framed by these, so it
 * clears their land names and stays inside the frame.
 */
export const FAR_ROW_STRETCH = 1.3;
export const OPPONENT_HAND_STRETCH = 1.35;
/**
 * Seat-local distance from the table center to the inner edge of the
 * opponent's (stretched) hand: just past the top of their stretched lands,
 * the title strip left showing.
 */
export const OPPONENT_HAND_INNER = -ROW_Y.back + ((CARD_HEIGHT * BACK_ROW_SCALE) / 2) * FAR_ROW_STRETCH;

/**
 * Seat-local center y of a hand drawn at `scale`: the player's inner edge
 * reaches onto the felt (HAND_FELT_OVERLAP); the opponent's stretched inner
 * edge sits just past their land names (OPPONENT_HAND_INNER).
 */
export function handY(scale: number, opponent = false): number {
  const height = CARD_HEIGHT * scale;
  if (opponent) return -(OPPONENT_HAND_INNER + (height * OPPONENT_HAND_STRETCH) / 2);
  return -(TABLE_DEPTH / 2 - HAND_FELT_OVERLAP + height / 2);
}

/** Framed apron past the player's rail: the rest of a hand drawn at `scale`, whole. */
export function apronDepth(scale: number): number {
  return CARD_HEIGHT * scale - HAND_FELT_OVERLAP - RAIL_WIDTH + APRON_MARGIN;
}

/** Framed apron past the opponent's rail: the rest of their smaller, stretched hand drawn at `scale`. */
export function opponentApronDepth(scale: number = OPPONENT_HAND_SCALE): number {
  const height = CARD_HEIGHT * scale * OPPONENT_HAND_STRETCH;
  return OPPONENT_HAND_INNER + height - TABLE_DEPTH / 2 - RAIL_WIDTH + APRON_MARGIN;
}

/** Largest scale a seat's hand is drawn at: the stage's hand scale for the player, its smaller one for the opponent. */
export function seatHandScale(table: TableGeometry, opponent: boolean): number {
  return opponent ? Math.min(table.opponentHandScale, table.handScale) : table.handScale;
}

/**
 * Cards tucked under a host (auras, equipment, cards it exiled) fan upward on
 * screen, away from the viewer for both seats, each showing its title strip:
 * a small sideways nudge and one title's height per card. The fan must stay
 * inside the clear gap before the next row (the opponent's rises toward
 * their lands, the player's toward the center) so no strip is ever hidden
 * under another row: a host with a tall fan first slides away from it (up to
 * ATTACH_SHIFT_MAX, into the gap behind it), then the strips compress. Three
 * cards show whole titles either way; longer fans show the top of each
 * title, and the hover preview lists and pictures them all.
 */
const ATTACH_DX = 0.05;
const ATTACH_DY = 0.17;
/** Clear space kept between the top strip and the next row. */
const ATTACH_MARGIN = 0.04;
/** How far a host may slide away from its fan to make room for it. */
const ATTACH_SHIFT_MAX = 0.2;

/** Room a fan has before the next row, for the seat it is on. */
export function attachRoom(opponent: boolean): number {
  return (opponent ? BACK_ROW_GAP : 2 * CENTER_GAP) - ATTACH_MARGIN;
}

/** Per-card offsets of a fan of `count` tucked cards with `room` to rise into, and how far its host slides away. */
export function attachStep(count: number, room: number = attachRoom(true)): { dx: number; dy: number; shift: number } {
  if (count <= 0) return { dx: 0, dy: 0, shift: 0 };
  const natural = ATTACH_DY * count;
  const shift = Math.min(ATTACH_SHIFT_MAX, Math.max(0, natural - room));
  return { dx: ATTACH_DX, dy: Math.min(ATTACH_DY, (room + shift) / count), shift };
}
/**
 * A noncreature artifact or enchantment holding more cards than this that it
 * exiled (Pinnacle Starcage can take a whole board) shows them as a pile with
 * a count in its top right corner instead of a fan; the hover preview lists
 * and pictures them all. Creatures, and anything with auras or equipment,
 * always fan.
 */
const TUCKED_FAN_MAX = 2;
/** Edges a pile of exiled cards shows under its host, however many it holds. */
const PILE_EDGES = 2;

/** Edge shown per card under the top of a stack of identical cards: enough to count them, nothing to read. */
const STACK_EDGE_DY = 0.07;
/** A stack's edges never spread wider than this to the side, however many cards it holds. */
const STACK_MAX_SPREAD = 0.2;

/** Offsets for a stack of `count` identical cards under the top one: thin edges, and the top never slides. */
function stackStep(count: number, room: number): { dx: number; dy: number; shift: number } {
  if (count <= 0) return { dx: 0, dy: 0, shift: 0 };
  return { dx: Math.min(ATTACH_DX, STACK_MAX_SPREAD / count), dy: Math.min(STACK_EDGE_DY, room / count), shift: 0 };
}
const BASE_Z = 0.02;
/** How far a flying creature hovers above the felt (its tucked cards rise with it). */
export const FLYING_LIFT = 0.25;
const STACK_Z = 0.9;
/** In-scene stack cards: the motion anchor under the DOM stack preview. */
export const STACK_SCALE = 0.6;
/**
 * Triggered and activated abilities are a small chip showing their source's
 * card, never a second full-size copy of a card that is already on the table
 * or the stack.
 */
export const ABILITY_CHIP_SCALE = 0.5;
const STACK_EDGE = 0.3;
/**
 * The column sits at the table's center line: the DOM stack preview is
 * centered on the stage, so a cast card flies from the hand straight to the
 * spot the preview's card appears over.
 */
export const STACK_ANCHOR_Y = 0;

/** Pile lane on the left: three piles, or four in commander formats. */
const PILE_MARGIN = 0.16;
const PILE_GAP = 0.14;
const PILE_SCALE = { 3: 0.74, 4: 0.54 } as const;
const LANE_PAD = 0.14;
const RIGHT_MARGIN = 0.2;

export type PlacementRow = 'lands' | 'creatures' | 'planeswalkers' | 'other' | 'hand' | 'castable' | 'stack' | 'pile';

/** Keywords (stream card `keywords`) that cast a card from its owner's graveyard. */
export const GRAVEYARD_CAST_KEYWORDS: readonly string[] = ['flashback', 'escape', 'disturb', 'harmonize'];

/**
 * A card its owner may cast from outside the hand, shown just beside the hand
 * (as Arena does): the keyword that allows it, `plot` for a plotted card, or
 * `cast_from_exile` for an exiled card whose own text lets it be cast from
 * there (card keywords `cast_from_exile` and, once it exiled itself from the
 * hand, `cast_while_exiled`: Emrakul, the Exigent Doom).
 */
export type CastableMark = 'flashback' | 'escape' | 'disturb' | 'harmonize' | 'plot' | 'cast_from_exile';

/** Gap between the hand and its side cards, and how much of each side card the next leaves showing. */
export const SIDE_GAP = 0.35;
export const SIDE_STEP = 0.6;
/** The rows a battlefield host can be placed in. */
export type BattlefieldRow = 'lands' | 'creatures' | 'planeswalkers' | 'other';
export type PlacementHighlight = 'attacking' | 'blocking' | 'damaged' | 'targeted' | null;
export type PileZone = 'library' | 'graveyard' | 'exile' | 'command';

export interface LayoutOptions {
  /** Real-table view: the opponent's half is turned 180° (their cards face them). */
  mirrorOpponent: boolean;
  /** Show hand cards whose identity is revealed later in the game face-up. */
  hindsight: boolean;
  playerSeat: number;
  /** Felt width (from the stage aspect); DEFAULT_TABLE_WIDTH when omitted. */
  tableWidth?: number;
  /** Hand card scale the stage has room for (clamped to HAND_SCALE_MIN..MAX); the minimum when omitted. */
  handScale?: number;
  /** The opponent's hand card scale (from OPPONENT_HAND_SCALE up); OPPONENT_HAND_SCALE when omitted. */
  opponentHandScale?: number;
  /** Reserve a command-zone pile (commander formats, see `usesCommandZone`). */
  commandZone?: boolean;
}

export interface CardPlacement {
  /** Mesh key: the object id, `stack:<stack_id>` for abilities, `hidden:<seat>:hand:<i>`. */
  obj: string;
  card: CardKey | null;
  faceUp: boolean;
  x: number;
  y: number;
  z: number;
  rotZ: number;
  /** 0 face up, π face down; the renderer animates the flip. */
  rotY: number;
  scale: number;
  zone: Zone;
  seat: number;
  row: PlacementRow;
  highlight: PlacementHighlight;
  tapped: boolean;
  inferred: boolean;
  counters: Readonly<Record<string, number>>;
  power: string | null;
  toughness: string | null;
  /** The seat's commander (Brawl/Commander), wherever it is: the scene marks it on the battlefield. */
  commander: boolean;
  /** On the battlefield: the basic land type it chose as it entered ("Mountain"), else null. */
  chosen: string | null;
  /** Cards tucked under this one (auras, equipment, cards it exiled), bottom first; empty for everything else. */
  under: readonly UnderCard[];
  /** Side cards beside the hand: why the owner may cast it from there; null elsewhere. */
  castable: CastableMark | null;
  /** Battlefield: damage dealt to it this moment (the effect window), else null. */
  damage: number | null;
  /** What the current action did to it (effects.ts), or null. */
  marks: ObjectMarks | null;
  /** A face-up creature with flying (printed or a flying counter): it hovers, lifted `FLYING_LIFT`. */
  flying: boolean;
  /** On the battlefield and summoning sick: a purple sleep badge (`Zzz`) centered above its top edge. */
  sick?: boolean;
  /** Removed this action: held dimmed in its battlefield slot (or, discarded, on the graveyard) with this chip. */
  removed: RemovalKind | null;
  /** The top card of a stack of identical tokens or lands: how many the stack holds (absent otherwise). */
  stackCount?: number;
  /** A token or land stacked under an identical one, or a card in a host's pile of exiled cards (that one's obj): drawn as an edge, without labels. */
  stackedUnder?: ObjId;
  /** A host showing the cards it exiled as a pile (`TUCKED_FAN_MAX`): how many the pile holds (absent otherwise). */
  tuckedCount?: number;
}

/** A seat's life change, damage taken and cards milled this action, at its table edge. */
export interface SeatMarkPlacement {
  seat: number;
  marks: SeatMarks;
  /** Where the number sits: the middle of that seat's rail (where attack and damage arrows land). */
  x: number;
  y: number;
}

/** One card tucked under a host, as the hover preview lists it. */
export interface UnderCard {
  obj: ObjId;
  card: CardKey | null;
  /** 'exile' for a card the host exiled, else 'battlefield' for an attachment. */
  zone: Zone;
}

export interface PilePlacement {
  seat: number;
  zone: PileZone;
  count: number;
  topCard: CardKey | null;
  x: number;
  y: number;
  /** Pile cards are drawn at this scale of a full card. */
  scale: number;
  /** π for a mirrored opponent pile, else 0. */
  rotZ: number;
}

export interface TableGeometry {
  width: number;
  depth: number;
  /** Battlefield and hand cards stay within [rowLeft, rowRight] (right of the pile lane). */
  rowLeft: number;
  rowRight: number;
  /** x of the in-scene stack column (under the DOM stack preview). */
  stackX: number;
  /** Largest hand card scale (a crowded hand may draw smaller); sizes the camera's hand aprons. */
  handScale: number;
  /** Largest opponent hand card scale; sizes the camera's far apron. */
  opponentHandScale: number;
}

export interface Layout {
  cards: CardPlacement[];
  piles: PilePlacement[];
  table: TableGeometry;
  /** Seats with a life change, damage or a mill this action. */
  seatMarks: SeatMarkPlacement[];
}

export function clampTableWidth(width: number): number {
  if (!Number.isFinite(width)) return DEFAULT_TABLE_WIDTH;
  return Math.min(MAX_TABLE_WIDTH, Math.max(MIN_TABLE_WIDTH, width));
}

function pileScale(commandZone: boolean): number {
  return commandZone ? PILE_SCALE[4] : PILE_SCALE[3];
}

export function tableGeometry(
  width: number = DEFAULT_TABLE_WIDTH,
  commandZone = false,
  handScale?: number,
  opponentHandScale?: number,
): TableGeometry {
  const w = clampTableWidth(width);
  const lane = PILE_MARGIN * 2 + CARD_WIDTH * pileScale(commandZone) + LANE_PAD;
  return {
    width: w,
    depth: TABLE_DEPTH,
    rowLeft: -w / 2 + lane,
    rowRight: w / 2 - RIGHT_MARGIN,
    stackX: w / 2 - STACK_EDGE - (CARD_WIDTH * STACK_SCALE) / 2,
    handScale: clampHandScale(handScale),
    opponentHandScale: clampOpponentHandScale(opponentHandScale),
  };
}

/** Commander formats get a fourth pile: any seat has commanders or any card visits the command zone. */
export function usesCommandZone(stream: Pick<ReplayStream, 'seats' | 'events'>): boolean {
  if (Object.values(stream.seats).some((seat) => (seat.commanders ?? []).length > 0)) return true;
  return stream.events.some((event) => event.kind === 'move' && (event.from === 'command' || event.to === 'command'));
}

interface Frame {
  seat: number;
  opponent: boolean;
  mirror: boolean;
}

function toTable(frame: Frame, x: number, y: number): { x: number; y: number } {
  if (!frame.opponent) return { x, y };
  return frame.mirror ? { x: -x, y: -y } : { x, y: -y };
}

function frameRotation(frame: Frame): number {
  return frame.opponent && frame.mirror ? Math.PI : 0;
}

/**
 * Battlefield row for a permanent: lands in the back row, creatures in front,
 * non-creature planeswalkers in front to the right of the creatures, and
 * every other permanent in the back row after the lands.
 */
export function rowOf(object: ObjectState, cards: Readonly<Record<CardKey, ReplayCard>>): BattlefieldRow {
  const card = object.card && !object.faceDown ? cards[object.card] : undefined;
  if (!card) return 'creatures';
  const primary = (card.primary_type ?? '').toLowerCase();
  const typeLine = (card.type_line ?? '').toLowerCase();
  if (primary === 'land' || (!primary && typeLine.includes('land'))) return 'lands';
  if (primary === 'creature' || typeLine.includes('creature') || object.power !== null) {
    return 'creatures';
  }
  if (primary === 'planeswalker' || typeLine.includes('planeswalker')) return 'planeswalkers';
  return 'other';
}

interface Context {
  state: BoardState;
  opts: LayoutOptions;
  table: TableGeometry;
  targeted: ReadonlySet<ObjId>;
  damaged: ObjId | null;
  blockers: ReadonlySet<ObjId>;
  /** host obj -> attached battlefield objects, across both seats (auras on enemy creatures), plus cards the host exiled. */
  attachments: ReadonlyMap<ObjId, ObjectState[]>;
  /** Exiled cards shown under their host (kept out of the exile pile). */
  tucked: ReadonlySet<ObjId>;
  /** Graveyard and exile cards shown beside their owner's hand instead of on their pile. */
  castable: ReadonlyMap<ObjId, CastableMark>;
  /** Permanents removed this action, still drawn in their battlefield slot (and nowhere else). */
  held: ReadonlySet<ObjId>;
  /** top token obj -> the identical tokens stacked under it (`stackIdenticalTokens`). */
  stacked: Map<ObjId, ObjectState[]>;
  out: CardPlacement[];
}

/** A face-up creature with flying, printed (card `keywords`) or from a flying counter. */
export function hasFlying(state: BoardState, object: ObjectState): boolean {
  if (object.faceDown) return false;
  if (Object.keys(object.counters).some((type) => type.toLowerCase() === 'flying')) return true;
  return object.card ? (state.cards[object.card]?.keywords?.includes('flying') ?? false) : false;
}

/** Why `object` shows beside its owner's hand, if it does. */
export function castableMark(state: BoardState, object: ObjectState): CastableMark | null {
  const keywords = (object.card ? state.cards[object.card]?.keywords : undefined) ?? [];
  if (!keywords.length) return null;
  if (object.zone === 'graveyard') {
    const keyword = keywords.find((k) => GRAVEYARD_CAST_KEYWORDS.includes(k));
    return keyword ? (keyword as CastableMark) : null;
  }
  if (object.zone !== 'exile') return null;
  if (object.fromHand && keywords.includes('plot')) return 'plot';
  if (keywords.includes('cast_from_exile')) return 'cast_from_exile';
  if (object.fromHand && keywords.includes('cast_while_exiled')) return 'cast_from_exile';
  return null;
}

function collectCastable(state: BoardState, seatIds: readonly number[], tucked: ReadonlySet<ObjId>): Map<ObjId, CastableMark> {
  const out = new Map<ObjId, CastableMark>();
  for (const seatId of seatIds) {
    const zones = state.seats[seatId].zones;
    for (const obj of [...zones.graveyard, ...zones.exile]) {
      if (tucked.has(obj) || state.effects.held.has(obj)) continue;
      const object = state.objects.get(obj);
      const mark = object ? castableMark(state, object) : null;
      if (mark) out.set(obj, mark);
    }
  }
  return out;
}

function highlightOf(ctx: Context, obj: ObjId): PlacementHighlight {
  if (ctx.damaged === obj || (ctx.state.effects.objects.get(obj)?.damage ?? 0) > 0) return 'damaged';
  if (ctx.targeted.has(obj)) return 'targeted';
  if (ctx.state.attackers.has(obj)) return 'attacking';
  if (ctx.blockers.has(obj)) return 'blocking';
  return null;
}

/**
 * A seat's commander is the card the stream's seat info names (Brawl decks are
 * singleton, so the name is enough). Rules-wise it is an ordinary permanent on
 * the battlefield; Arena puts it in the creature row like any other, so this
 * only marks it rather than moving it.
 */
function isCommander(ctx: Context, object: ObjectState): boolean {
  if (!object.card) return false;
  const names = ctx.state.commanders[object.owner];
  if (!names || names.length === 0) return false;
  const name = ctx.state.cards[object.card]?.name;
  return name !== undefined && names.includes(name);
}

function printedStat(ctx: Context, object: ObjectState, key: 'power' | 'toughness'): string | null {
  const value = object[key];
  if (value !== null) return String(value);
  const card = object.card ? ctx.state.cards[object.card] : undefined;
  return card ? card[key] : null;
}

function placeObject(
  ctx: Context,
  frame: Frame,
  object: ObjectState,
  local: { x: number; y: number; z: number; rotZ?: number; scale?: number },
  row: PlacementRow,
  faceCard: CardKey | null = object.card,
  seat: number = frame.seat,
  under: readonly UnderCard[] = NO_UNDER,
  flying = false,
): void {
  const { x, y } = toTable(frame, local.x, local.y);
  const faceUp = faceCard !== null && !object.faceDown;
  const marks = ctx.state.effects.objects.get(object.obj) ?? null;
  ctx.out.push({
    obj: object.obj,
    card: faceCard,
    faceUp,
    x,
    y,
    z: local.z,
    rotZ: (local.rotZ ?? 0) + (object.tapped ? TAPPED_ROTATION : 0) + frameRotation(frame),
    rotY: faceUp ? 0 : Math.PI,
    scale: local.scale ?? 1,
    zone: object.zone,
    seat,
    row,
    highlight: highlightOf(ctx, object.obj),
    tapped: object.tapped,
    inferred: object.inferred,
    counters: object.counters,
    power: printedStat(ctx, object, 'power'),
    toughness: printedStat(ctx, object, 'toughness'),
    commander: isCommander(ctx, object),
    chosen: object.zone === 'battlefield' ? (object.chosen ?? null) : null,
    under,
    castable: row === 'castable' ? (ctx.castable.get(object.obj) ?? null) : null,
    damage: object.zone === 'battlefield' ? marks?.damage || null : null,
    marks,
    flying,
    removed: ctx.held.has(object.obj) || (row === 'pile' && marks?.removed === 'discarded') ? (marks?.removed ?? null) : null,
    ...(object.zone === 'battlefield' && object.sick && !ctx.held.has(object.obj) ? { sick: true } : {}),
  });
}

const NO_UNDER: readonly UnderCard[] = [];

/** Width a host takes in its row: the card, plus its fan of tucked cards or stacked copies. */
function footprint(object: ObjectState, attachments: number, scale: number, stacked = 0): number {
  const fan = attachments ? attachments * attachStep(attachments).dx : stacked * stackStep(stacked, 1).dx;
  return ((object.tapped ? CARD_HEIGHT : CARD_WIDTH) + fan) * scale;
}

function naturalWidth(widths: readonly number[], gap: number): number {
  return widths.length ? widths.reduce((sum, w) => sum + w, 0) + gap * (widths.length - 1) : 0;
}

/**
 * Centers for one group of cards starting at `start` and spanning `span`:
 * packed with `gap` when that fits, else overlapped with evenly spaced left
 * edges. A tapped (wider) card is clamped so it never pokes past the end.
 */
function groupCenters(widths: readonly number[], gap: number, start: number, span: number): number[] {
  const n = widths.length;
  if (!n) return [];
  if (span >= naturalWidth(widths, gap) - 1e-9 || n === 1) {
    let x = start;
    return widths.map((w) => {
      const center = x + w / 2;
      x += w + gap;
      return center;
    });
  }
  const end = start + span;
  const step = (end - widths[n - 1] - start) / (n - 1);
  // A span narrower than its last card (a row overflowing even when squeezed)
  // would push cards left of `start`, into the pile lane: they stay at it.
  return widths.map((w, i) => Math.max(start + w / 2, Math.min(start + step * i + w / 2, end - w / 2)));
}

/** Narrowest a group may be squeezed to (each card keeps MIN_VISIBLE of its width). */
function minimumWidth(widths: readonly number[]): number {
  if (!widths.length) return 0;
  const last = widths[widths.length - 1];
  return widths.slice(0, -1).reduce((sum, w) => sum + w * MIN_VISIBLE, 0) + last;
}

export interface RowGroup {
  widths: readonly number[];
  gap: number;
}

/**
 * Places one row made of consecutive groups (back row: lands, then other
 * permanents). Centered on the table while it fits between the pile lane
 * and its mirror image, then across the whole free span, and only when even
 * that overflows are cards overlapped: the earlier groups (lands) give up
 * width first, down to MIN_VISIBLE of each card.
 */
export function placeRow(groups: readonly RowGroup[], left: number, right: number, groupGap = GROUP_GAP): number[][] {
  const live = groups.filter((g) => g.widths.length > 0);
  const natural = live.map((g) => naturalWidth(g.widths, g.gap));
  const gaps = Math.max(0, live.length - 1) * groupGap;
  const total = natural.reduce((sum, w) => sum + w, 0) + gaps;
  const available = right - left;
  const symmetric = Math.max(0, Math.min(-left, right)) * 2;
  let start: number;
  const spans = [...natural];
  if (total <= symmetric) start = -total / 2;
  else if (total <= available) start = left + (available - total) / 2;
  else {
    start = left;
    let excess = total - available;
    for (let i = 0; i < live.length && excess > 0; i += 1) {
      const give = Math.min(excess, natural[i] - minimumWidth(live[i].widths));
      spans[i] -= give;
      excess -= give;
    }
    if (excess > 0) {
      // Even fully squeezed it overflows (dozens of tokens): share the rest evenly.
      const squeezed = spans.reduce((sum, w) => sum + w, 0);
      const room = Math.max(0.01, available - gaps);
      for (let i = 0; i < spans.length; i += 1) spans[i] *= room / squeezed;
    }
  }
  const out: number[][] = [];
  let x = start;
  let liveIndex = 0;
  for (const group of groups) {
    if (!group.widths.length) {
      out.push([]);
      continue;
    }
    out.push(groupCenters(group.widths, group.gap, x, spans[liveIndex]));
    x += spans[liveIndex] + groupGap;
    liveIndex += 1;
  }
  return out;
}

/** Centers for a single row inside [-halfWidth, halfWidth] (overlapping evenly once it overflows). */
export function rowCenters(widths: readonly number[], halfWidth: number): number[] {
  const n = widths.length;
  if (!n) return [];
  const total = naturalWidth(widths, ROW_GAP);
  if (total <= halfWidth * 2) return groupCenters(widths, ROW_GAP, -total / 2, total);
  return groupCenters(widths, ROW_GAP, -halfWidth, halfWidth * 2);
}

function attachedHost(state: BoardState, object: ObjectState): ObjectState | undefined {
  const hostId = object.zone === 'exile' ? object.exiledWith : object.attachedTo;
  const host = hostId ? state.objects.get(hostId) : undefined;
  return host && host.zone === 'battlefield' && host.obj !== object.obj && !host.attachedTo ? host : undefined;
}

/**
 * Cards drawn under a battlefield host: auras and equipment attached to it,
 * and cards it exiled (Deep-Cavern Bat, Pinnacle Starcage) for as long as it
 * stays on the battlefield; those leave the exile pile.
 */
function collectAttachments(state: BoardState, seatIds: number[]): Map<ObjId, ObjectState[]> {
  const attachments = new Map<ObjId, ObjectState[]>();
  for (const seatId of seatIds) {
    for (const zone of ['battlefield', 'exile'] as const) {
      for (const obj of state.seats[seatId].zones[zone]) {
        if (state.effects.held.has(obj)) continue;
        const object = state.objects.get(obj);
        const host = object && attachedHost(state, object);
        if (object && host) {
          const list = attachments.get(host.obj) ?? [];
          list.push(object);
          attachments.set(host.obj, list);
        }
      }
    }
  }
  return attachments;
}

/** Whether a host shows its tucked cards as a counted pile rather than a fan (`TUCKED_FAN_MAX`). */
function pilesTucked(cards: BoardState['cards'], host: ObjectState, tucked: readonly ObjectState[]): boolean {
  return tucked.length > TUCKED_FAN_MAX && tucked.every((o) => o.zone === 'exile') && rowOf(host, cards) === 'other';
}

/** Exiled cards tucked under a host are not in the pile. */
function tuckedAway(attachments: ReadonlyMap<ObjId, ObjectState[]>): ReadonlySet<ObjId> {
  const tucked = new Set<ObjId>();
  for (const list of attachments.values()) for (const object of list) if (object.zone === 'exile') tucked.add(object.obj);
  return tucked;
}

/**
 * What makes two tokens, or two lands, interchangeable on the table: the same
 * card (a land by name, whatever its printing), controller, tapped state,
 * summoning sickness, stats, counters, chosen land type, combat role and current-action marks.
 * Null for anything that must stay on its own: neither a token nor a land,
 * face down, carrying attachments, removed, damaged or targeted this action,
 * or in a block.
 */
function stackKey(ctx: Context, object: ObjectState, row: BattlefieldRow): string | null {
  const card = object.card ? ctx.state.cards[object.card] : undefined;
  const land = row === 'lands';
  if (!card || !(card.is_token || land) || object.faceDown || object.inferred) return null;
  if (ctx.attachments.has(object.obj) || ctx.held.has(object.obj)) return null;
  const highlight = highlightOf(ctx, object.obj);
  if (highlight === 'damaged' || highlight === 'targeted' || highlight === 'blocking') return null;
  for (const attacker of ctx.state.blocks.values()) if (attacker === object.obj) return null;
  const counters = Object.entries(object.counters).sort(([a], [b]) => (a < b ? -1 : 1));
  const attacking = ctx.state.attackers.has(object.obj) ? (ctx.state.attackers.get(object.obj) ?? 'player') : null;
  const marks = ctx.state.effects.objects.get(object.obj) ?? null;
  return JSON.stringify([
    land && !card.is_token ? `name:${card.name}` : object.card,
    object.controller,
    object.tapped,
    object.sick ?? false,
    object.power,
    object.toughness,
    counters,
    object.chosen ?? null,
    attacking,
    marks,
  ]);
}

/**
 * Identical tokens and lands stack under the first of them, Arena style, so a
 * board of Spirits, Treasures or Mountains takes one slot (tapped ones in a
 * stack of their own); the rest show as edges like tucked cards. Returns the
 * row's hosts with the stacked cards taken out.
 */
function stackIdenticalTokens(ctx: Context, list: readonly ObjectState[], row: BattlefieldRow): ObjectState[] {
  const tops = new Map<string, ObjectState>();
  const out: ObjectState[] = [];
  for (const object of list) {
    const key = stackKey(ctx, object, row);
    const top = key === null ? undefined : tops.get(key);
    if (top) {
      const members = ctx.stacked.get(top.obj) ?? [];
      members.push(object);
      ctx.stacked.set(top.obj, members);
      continue;
    }
    if (key !== null) tops.set(key, object);
    out.push(object);
  }
  return out;
}

function placeGroup(
  ctx: Context,
  frame: Frame,
  list: readonly ObjectState[],
  centers: readonly number[],
  widths: readonly number[],
  row: BattlefieldRow,
  y: number,
  scale: number,
): void {
  list.forEach((object, i) => {
    const attachments = ctx.attachments.get(object.obj) ?? [];
    const stack = ctx.stacked.get(object.obj) ?? [];
    const piled = pilesTucked(ctx.state.cards, object, attachments);
    // Identical tokens fan out under the top one exactly like tucked cards.
    const attached = attachments.length ? attachments : stack;
    const ownWidth = footprint(object, 0, scale);
    const x = centers[i] - widths[i] / 2 + ownWidth / 2;
    const step = piled
      ? stackStep(PILE_EDGES, attachRoom(frame.opponent))
      : attachments.length
        ? attachStep(attached.length, attachRoom(frame.opponent))
        : stackStep(stack.length, attachRoom(frame.opponent));
    // Up on screen for both seats (seat-local +y maps to world -y for the
    // opponent), and to the right as seen by the viewer.
    const up = frame.opponent ? -1 : 1;
    const right = frame.opponent && frame.mirror ? -1 : 1;
    // The host slides away from its fan to keep the strips out of the next row.
    const cardY = y + (ctx.state.attackers.has(object.obj) ? ATTACK_OFFSET : 0) - up * step.shift * scale;
    const flying = row === 'creatures' && hasFlying(ctx.state, object);
    const z = BASE_Z + 0.004 * (attached.length + 1) + i * 0.0005 + (flying ? FLYING_LIFT : 0);
    const under = attachments.map((child): UnderCard => ({ obj: child.obj, card: child.card, zone: child.zone }));
    placeObject(ctx, frame, object, { x, y: cardY, z, scale }, row, object.card, frame.seat, under, flying);
    if (stack.length) ctx.out[ctx.out.length - 1].stackCount = stack.length + 1;
    if (piled) ctx.out[ctx.out.length - 1].tuckedCount = attachments.length;
    attached.forEach((child, k) => {
      // Tucked cards sit under the host, each one a title strip higher; a pile
      // shows only its first edges, the rest squared up behind them.
      const offset = piled ? Math.min(k + 1, PILE_EDGES) : k + 1;
      const local = {
        x: x + right * step.dx * scale * offset,
        y: cardY + up * step.dy * scale * offset,
        z: z - 0.004 * (k + 1),
        scale,
      };
      placeObject(ctx, frame, child, local, row, child.card, child.controller, NO_UNDER, stack.length ? flying : false);
      if (stack.length || piled) ctx.out[ctx.out.length - 1].stackedUnder = object.obj;
    });
  });
}

/**
 * Seat-local span for battlefield rows. A mirrored opponent's x is negated on
 * the way to the table, so its rows are laid out in the reflected span and
 * land right of the pile lane like everyone else's.
 */
function rowSpan(table: TableGeometry, frame: Frame): { left: number; right: number } {
  return frame.opponent && frame.mirror
    ? { left: -table.rowRight, right: -table.rowLeft }
    : { left: table.rowLeft, right: table.rowRight };
}

function layoutBattlefield(ctx: Context, frame: Frame, objects: ObjectState[]): void {
  const { attachments } = ctx;
  const span = rowSpan(ctx.table, frame);
  const hosts: Record<BattlefieldRow, ObjectState[]> = { lands: [], creatures: [], planeswalkers: [], other: [] };
  for (const object of objects) {
    if (!attachedHost(ctx.state, object)) hosts[rowOf(object, ctx.state.cards)].push(object);
  }
  for (const row of Object.keys(hosts) as BattlefieldRow[]) hosts[row] = stackIdenticalTokens(ctx, hosts[row], row);
  const widthsOf = (list: ObjectState[], scale: number) =>
    list.map((o) => {
      const tucked = attachments.get(o.obj) ?? [];
      if (pilesTucked(ctx.state.cards, o, tucked)) return footprint(o, 0, scale, PILE_EDGES);
      return footprint(o, tucked.length, scale, ctx.stacked.get(o.obj)?.length ?? 0);
    });
  // Front row: creatures centered as before; planeswalkers at full size,
  // anchored to the viewer's right edge of the row (Arena puts them beside
  // the creatures, out to the right), with a gap kept between the two.
  const creatureWidths = widthsOf(hosts.creatures, 1);
  const walkerWidths = widthsOf(hosts.planeswalkers, 1);
  let creatureCenters: number[];
  let walkerCenters: number[];
  if (!walkerWidths.length) {
    [creatureCenters] = placeRow([{ widths: creatureWidths, gap: ROW_GAP }], span.left, span.right);
    walkerCenters = [];
  } else {
    const available = span.right - span.left;
    // Many planeswalkers overlap rather than push the creatures off the table.
    const walkerSpan = Math.min(naturalWidth(walkerWidths, ROW_GAP), available * MAX_PLANESWALKER_SHARE);
    // A mirrored opponent's seat-local x is negated, so the viewer's right is its left.
    const viewerRightIsLocalRight = !(frame.opponent && frame.mirror);
    const walkerStart = viewerRightIsLocalRight ? span.right - walkerSpan : span.left;
    walkerCenters = groupCenters(walkerWidths, ROW_GAP, walkerStart, walkerSpan);
    const creatureLeft = viewerRightIsLocalRight ? span.left : span.left + walkerSpan + PLANESWALKER_GAP;
    const creatureRight = viewerRightIsLocalRight ? span.right - walkerSpan - PLANESWALKER_GAP : span.right;
    [creatureCenters] = placeRow([{ widths: creatureWidths, gap: ROW_GAP }], creatureLeft, creatureRight);
  }
  placeGroup(ctx, frame, hosts.creatures, creatureCenters, creatureWidths, 'creatures', ROW_Y.creatures, 1);
  placeGroup(ctx, frame, hosts.planeswalkers, walkerCenters, walkerWidths, 'planeswalkers', ROW_Y.creatures, 1);

  const landWidths = widthsOf(hosts.lands, BACK_ROW_SCALE);
  const otherWidths = widthsOf(hosts.other, BACK_ROW_SCALE);
  const [landCenters, otherCenters] = placeRow(
    [
      { widths: landWidths, gap: LAND_GAP },
      { widths: otherWidths, gap: ROW_GAP },
    ],
    span.left,
    span.right,
  );
  placeGroup(ctx, frame, hosts.lands, landCenters, landWidths, 'lands', ROW_Y.back, BACK_ROW_SCALE);
  placeGroup(ctx, frame, hosts.other, otherCenters, otherWidths, 'other', ROW_Y.back, BACK_ROW_SCALE);
}

/** Width of `count` side cards (castable from the graveyard or plotted) at `scale`. */
function sideWidth(count: number, scale: number): number {
  return count ? CARD_WIDTH * scale * (1 + SIDE_STEP * (count - 1)) : 0;
}

function layoutHand(
  ctx: Context,
  frame: Frame,
  objects: ObjectState[],
  hidden: number,
  side: readonly ObjectState[] = [],
): void {
  const n = hidden + objects.length;
  if (!n && !side.length) return;
  // Off the felt, the fan may run nearly the table's width (centered), less
  // what the side cards beside it need.
  const base = seatHandScale(ctx.table, frame.opponent);
  const floor = Math.min(HAND_SCALE_FLOOR, base);
  const available = ctx.table.width - 2 * HAND_SIDE_MARGIN;
  const reserve = side.length ? sideWidth(side.length, base) + SIDE_GAP : 0;
  const maxWidth = Math.max(CARD_WIDTH * floor, available - reserve);
  // Cards overlap down to HAND_MIN_VISIBLE first; a hand too crowded even
  // then shrinks (to the floor), and past that overlaps further.
  const fitScale = n ? maxWidth / ((HAND_MIN_VISIBLE * (n - 1) + 1) * CARD_WIDTH) : base;
  const scale = Math.max(floor, Math.min(base, fitScale));
  const cardWidth = CARD_WIDTH * scale;
  const step = n > 1 ? Math.min(cardWidth + HAND_STEP_GAP, (maxWidth - cardWidth) / (n - 1)) : 0;
  const y = handY(scale, frame.opponent);
  // The hand and its side cards are centered together; the side cards sit to its right.
  const handWidth = n ? cardWidth + step * (n - 1) : 0;
  const sideSpan = sideWidth(side.length, scale);
  const total = handWidth + (n && side.length ? SIDE_GAP : 0) + sideSpan;
  const handCenter = -total / 2 + handWidth / 2;
  const sideStart = handCenter + handWidth / 2 + (n ? SIDE_GAP : 0);
  side.forEach((object, i) => {
    const local = {
      x: sideStart + cardWidth / 2 + i * cardWidth * SIDE_STEP,
      y,
      z: HAND_Z + i * 0.003,
      rotZ: 0,
      scale,
    };
    placeObject(ctx, frame, object, local, 'castable');
  });
  const slot = (i: number) => {
    const offset = i - (n - 1) / 2;
    return {
      x: handCenter + offset * step,
      y: y - Math.min(0.04, offset * offset * 0.005),
      z: HAND_Z + i * 0.003,
      rotZ: -offset * 0.03,
      scale,
    };
  };
  for (let i = 0; i < hidden; i += 1) {
    const placeholder: ObjectState = {
      obj: `hidden:${frame.seat}:hand:${i}`,
      card: null,
      owner: frame.seat,
      controller: frame.seat,
      zone: 'hand',
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
    };
    placeObject(ctx, frame, placeholder, slot(i), 'hand', null);
  }
  objects.forEach((object, i) => {
    const face = object.card ?? (ctx.opts.hindsight ? (ctx.state.hindsight.get(object.obj) ?? null) : null);
    placeObject(ctx, frame, object, slot(hidden + i), 'hand', face);
  });
}

/** Seat-local pile slots in the left lane, from the table edge toward the center line. */
export function pileSlots(table: TableGeometry, commandZone: boolean): Array<{ zone: PileZone; x: number; y: number; scale: number }> {
  const zones: PileZone[] = commandZone ? ['library', 'graveyard', 'exile', 'command'] : ['library', 'graveyard', 'exile'];
  const scale = pileScale(commandZone);
  const height = CARD_HEIGHT * scale;
  const x = -table.width / 2 + PILE_MARGIN + (CARD_WIDTH * scale) / 2;
  return zones.map((zone, i) => ({
    zone,
    x,
    y: -(table.depth / 2 - PILE_MARGIN - height / 2 - i * (height + PILE_GAP)),
    scale,
  }));
}

function layoutPiles(ctx: Context, frame: Frame, piles: PilePlacement[]): void {
  const seat = ctx.state.seats[frame.seat];
  // Piles always stand in the left lane: a mirrored opponent's are turned, not moved.
  const pileFrame: Frame = { ...frame, mirror: false };
  const rotZ = frameRotation(frame);
  for (const slot of pileSlots(ctx.table, ctx.opts.commandZone ?? false)) {
    const { zone, scale } = slot;
    const objs = zone === 'library' ? [] : zone === 'exile' ? seat.zones.exile.filter((obj) => !ctx.tucked.has(obj)) : seat.zones[zone];
    const count = zone === 'library' ? seat.librarySize : objs.length;
    // Cards shown beside the hand (or held on the battlefield this action) still
    // count here, but the pile shows the card under them.
    const onPile = objs.filter((obj) => !ctx.castable.has(obj) && !ctx.held.has(obj));
    const { x, y } = toTable(pileFrame, slot.x, slot.y);
    const top = onPile.length ? ctx.state.objects.get(onPile[onPile.length - 1]) : undefined;
    piles.push({ seat: frame.seat, zone, count, topCard: top?.card ?? null, x, y, scale, rotZ });
    // Visible pile cards: every command-zone card, the top graveyard/exile card.
    const shown = zone === 'command' ? onPile : onPile.slice(-1);
    shown.forEach((obj, i) => {
      const object = ctx.state.objects.get(obj);
      if (!object) return;
      const z = BASE_Z + Math.min(count, 60) * 0.004 + i * 0.004;
      placeObject(ctx, pileFrame, object, { x: slot.x + i * 0.18, y: slot.y, z, scale, rotZ }, 'pile');
    });
  }
}

export interface StackEntryKey {
  /** Placement `obj`: the spell's own object id, or `stack:<stack_id>` for an ability chip. */
  key: string;
  item: StackItem;
  /** True for triggered and activated abilities (drawn as a chip). */
  ability: boolean;
}

/**
 * Which placement shows each stack item (shared with the scene labels). A
 * spell is its own card on the stack. An ability is always its own chip, even
 * when its source is a spell still on the stack: reconstructed streams push a
 * spell's "when you cast" trigger before that spell resolves, and keying the
 * trigger by the spell's object drew the spell labelled "Trigger".
 */
export function stackEntryKeys(state: BoardState): StackEntryKey[] {
  const keys: StackEntryKey[] = [];
  const claimed = new Set<ObjId>();
  for (const item of state.stack) {
    const object = item.obj ? state.objects.get(item.obj) : undefined;
    if (item.kind === 'spell' && object && object.zone === 'stack' && !claimed.has(object.obj)) {
      claimed.add(object.obj);
      keys.push({ key: object.obj, item, ability: false });
    } else {
      keys.push({ key: `stack:${item.stackId}`, item, ability: item.kind !== 'spell' });
    }
  }
  return keys;
}

/**
 * The in-scene stack is a small column at the right edge, underneath the DOM
 * stack preview: it is the motion anchor (a cast card flies from the hand
 * into the preview and later from there onto the battlefield), while the
 * preview is what the viewer reads.
 */
function layoutStack(ctx: Context): void {
  const { state, table } = ctx;
  const entries: Array<{ key: string; object: ObjectState | null; item: StackItem | null; ability: boolean }> = [];
  const covered = new Set<ObjId>();
  for (const { key, item, ability } of stackEntryKeys(state)) {
    const object = key === item.obj ? (state.objects.get(key) ?? null) : null;
    if (object) covered.add(object.obj);
    entries.push({ key, object, item, ability });
  }
  for (const seatId of Object.keys(state.seats).map(Number).sort((a, b) => a - b)) {
    for (const obj of state.seats[seatId].zones.stack) {
      const object = state.objects.get(obj);
      if (object && !covered.has(obj)) entries.push({ key: obj, object, item: null, ability: false });
    }
  }
  const n = entries.length;
  const step = n > 1 ? Math.min(0.25, 1 / (n - 1)) : 0;
  entries.forEach((entry, i) => {
    const controller = entry.item?.controller ?? entry.object?.controller ?? ctx.opts.playerSeat;
    const frame: Frame = { seat: controller, opponent: controller !== ctx.opts.playerSeat, mirror: ctx.opts.mirrorOpponent };
    const y = STACK_ANCHOR_Y + ((n - 1) / 2 - i) * step;
    const scale = entry.ability ? STACK_SCALE * ABILITY_CHIP_SCALE : STACK_SCALE;
    const local = { x: table.stackX, y, z: STACK_Z + i * 0.06, scale };
    const source = entry.item?.obj ? state.objects.get(entry.item.obj) : undefined;
    const object: ObjectState = entry.object ?? {
      obj: entry.key,
      card: entry.item?.card ?? (source && !source.faceDown ? source.card : null),
      owner: controller,
      controller,
      zone: 'stack',
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
    };
    // The stack column is shared by both seats, so it is not side-mapped.
    placeObject(ctx, { ...frame, opponent: false }, object, local, 'stack');
    ctx.out[ctx.out.length - 1].rotZ += frameRotation(frame);
  });
}

function compareKeys(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function layoutBoard(state: BoardState, opts: LayoutOptions): Layout {
  const blockers = new Set(state.blocks.keys());
  const targeted = new Set<ObjId>();
  for (const item of state.stack) item.targets.forEach((obj) => targeted.add(obj));
  const last = state.lastEvent;
  const damaged = last?.kind === 'damage' ? last.target_obj : null;
  const seatIds = Object.keys(state.seats).map(Number).sort((a, b) => a - b);
  const attachments = collectAttachments(state, seatIds);
  const tucked = tuckedAway(attachments);
  const castable = collectCastable(state, seatIds, tucked);
  const table = tableGeometry(opts.tableWidth, opts.commandZone ?? false, opts.handScale, opts.opponentHandScale);
  const held = new Set(state.effects.held.keys());
  const ctx: Context = { state, opts, table, targeted, damaged, blockers, attachments, tucked, castable, held, stacked: new Map(), out: [] };
  const piles: PilePlacement[] = [];

  for (const seatId of seatIds) {
    const frame: Frame = { seat: seatId, opponent: seatId !== opts.playerSeat, mirror: opts.mirrorOpponent };
    const seat = state.seats[seatId];
    const resolve = (obj: ObjId) => (held.has(obj) ? undefined : state.objects.get(obj));
    const battlefield = withHeld(state, seatId, seat.zones.battlefield.map(resolve).filter((o): o is ObjectState => !!o));
    const hand = seat.zones.hand.map(resolve).filter((o): o is ObjectState => !!o);
    const side = [...seat.zones.graveyard, ...seat.zones.exile]
      .filter((obj) => castable.has(obj))
      .map(resolve)
      .filter((o): o is ObjectState => !!o);
    layoutBattlefield(ctx, frame, battlefield);
    layoutHand(ctx, frame, hand, seat.hiddenHand, side);
    layoutPiles(ctx, frame, piles);
  }
  layoutStack(ctx);
  ctx.out.sort((a, b) => compareKeys(a.obj, b.obj));
  return { cards: ctx.out, piles, table, seatMarks: seatMarkPlacements(state, table, opts.playerSeat) };
}

/**
 * A seat's battlefield with the permanents removed this action put back in
 * their slots, as they last stood there (unattached, so a destroyed aura
 * shows on its own rather than vanishing under its host).
 */
function withHeld(state: BoardState, seatId: number, battlefield: ObjectState[]): ObjectState[] {
  const held = [...state.effects.held.values()].filter((h) => h.seat === seatId).sort((a, b) => a.index - b.index);
  if (!held.length) return battlefield;
  const out = battlefield.slice();
  for (const h of held) {
    out.splice(Math.min(h.index, out.length), 0, { ...h.object, attachedTo: null, exiledWith: null });
  }
  return out;
}

function seatMarkPlacements(state: BoardState, table: TableGeometry, playerSeat: number): SeatMarkPlacement[] {
  const out: SeatMarkPlacement[] = [];
  for (const [seat, marks] of state.effects.seats) {
    if (!marks.life && !marks.damage && !marks.milled) continue;
    const y = table.depth / 2 + RAIL_WIDTH / 2;
    out.push({ seat, marks, x: 0, y: seat === playerSeat ? -y : y });
  }
  return out.sort((a, b) => a.seat - b.seat);
}
