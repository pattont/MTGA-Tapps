/**
 * Replay stream types: the JSON `GET /api/replay?id=` returns
 * (docs/REPLAY_FORMAT.md §2). Field names match the wire format exactly.
 */

/** Arena root instance id (recorded) or `r:<n>` (reconstructed). */
export type ObjId = string;
/** `a<arena_id>`, `n:<name>`, or `unknown`; indexes `ReplayStream.cards`. */
export type CardKey = string;

export const ZONES = [
  'library',
  'hand',
  'battlefield',
  'graveyard',
  'exile',
  'stack',
  'command',
  'limbo',
] as const;
export type Zone = (typeof ZONES)[number];

export const MOVE_REASONS = [
  'draw',
  'play_land',
  'cast',
  'resolve',
  'destroy',
  'exile',
  'sacrifice',
  'discard',
  'mill',
  'bounce',
  'counter',
  'sba',
  'put',
  'token_create',
  'token_cease',
  'shuffle_in',
  'unknown',
] as const;
export type MoveReason = (typeof MOVE_REASONS)[number];

export type ReplayFidelity = 'recorded' | 'reconstructed';
export type SeatRole = 'player' | 'opponent';
export type StackItemKind = 'spell' | 'trigger' | 'activated';

export interface ReplayAvailability {
  state: 'recorded' | 'reconstructed' | 'unavailable';
  reason: string | null;
}

/**
 * Action-log segment. The contract writes `{text}` / `{card_name, card_type}`;
 * the Game Detail timeline also carries `kind`, so both spellings are accepted.
 */
export type ReplayLogSegment =
  | { kind?: 'text'; text: string }
  | { kind?: 'card'; text?: string; card_name: string; card_type?: string | null };

export interface ReplayLog {
  text: string;
  segments: ReplayLogSegment[];
}

export interface ReplayGame {
  id: string;
  started_at: string;
  ended_at: string | null;
  format: string;
  best_of: number;
  game_number: number | null;
  outcome: 'win' | 'loss' | 'draw' | 'unknown';
  outcome_reason: string | null;
  winner_seat: number | null;
  total_turns: number | null;
  duration_seconds: number | null;
}

export interface ReplaySeat {
  role: SeatRole;
  name: string;
  deck_name: string | null;
  starting_life: number;
  went_first: boolean | null;
  commanders: string[];
  deck_size: number | null;
  colors: string | null;
}

export interface ReplayCardFace {
  name: string;
  type_line: string | null;
}

export interface ReplayCard {
  name: string;
  arena_id: number | null;
  type_line: string | null;
  primary_type: string | null;
  power: string | null;
  toughness: string | null;
  mana_cost: string | null;
  color_identity: string | null;
  is_token: boolean;
  image_url: string | null;
  faces: ReplayCardFace[];
  /**
   * Replay-relevant keywords from Arena's card DB: `flashback`, `escape`,
   * `disturb`, `harmonize` (cast from the graveyard), `plot`,
   * `cast_from_exile` / `cast_while_exiled` (its own text lets it be cast from
   * exile; the latter only once it exiled itself from the hand), and `flying`
   * (the creature hovers on the battlefield). Absent in
   * streams built before they existed.
   */
  keywords?: string[];
  /** The back face of a double-faced card: Scryfall's image is the back image. */
  back_face?: boolean;
  /**
   * A token's Scryfall `set/number` ("ttdm/13"), from Arena's card DB. Tokens
   * never get `image_url`: their Arena number names another card in the set.
   */
  token_print?: string | null;
  /**
   * A card's Scryfall `set/number` ("fra/23") when the server had no direct
   * image link; looked up before the Arena id, which Scryfall learns late.
   */
  print?: string | null;
}

export interface ReplayTurn {
  turn: number;
  seat: number;
  first_seq: number;
  last_seq: number;
  started_at: string | null;
  duration_seconds: number | null;
}

export interface ReplayEventBase {
  seq: number;
  /** Elapsed seconds, monotonic non-decreasing. */
  t: number;
  turn: number;
  phase: string | null;
  step: string | null;
  log: ReplayLog | null;
  /** `game_events.id` this event was derived from; null for synthesized events. */
  row_id?: number | null;
}

export interface GameStartEvent extends ReplayEventBase {
  kind: 'game_start';
  seats_hand_sizes: Record<string, number>;
  library_sizes: Record<string, number>;
}
export interface TurnEvent extends ReplayEventBase {
  kind: 'turn';
  active_seat: number;
}
export interface PhaseEvent extends ReplayEventBase {
  kind: 'phase';
}
export interface LifeEvent extends ReplayEventBase {
  kind: 'life';
  seat: number;
  life: number;
  delta: number;
  source_obj: ObjId | null;
}
export interface MulliganEvent extends ReplayEventBase {
  kind: 'mulligan';
  seat: number;
  from_size: number;
  to_size: number;
  bottomed: ObjId[];
}
export interface MoveEvent extends ReplayEventBase {
  kind: 'move';
  obj: ObjId;
  card: CardKey | null;
  from: Zone;
  to: Zone;
  owner: number;
  controller: number;
  reason: MoveReason;
  inferred: boolean;
  /** Position in the destination zone (0 = library top / stack bottom) when known. */
  index: number | null;
  /** Exile only: the battlefield permanent whose ability exiled the card (recorded games). */
  with?: ObjId | null;
  /** The object whose effect moved it (Arena's affector, recorded games), when logged. */
  by?: ObjId | null;
  /** Onto the battlefield: the basic land type it chose as it entered ("Mountain", Multiversal Passage). */
  chosen?: string | null;
}
export interface TapEvent extends ReplayEventBase {
  kind: 'tap';
  objs: ObjId[];
}
export interface UntapEvent extends ReplayEventBase {
  kind: 'untap';
  objs: ObjId[];
}
/** Summoning sickness began: these creatures can't attack or use {T} abilities yet. */
export interface SickEvent extends ReplayEventBase {
  kind: 'sick';
  objs: ObjId[];
}
/** Summoning sickness ended (their controller's turn began, or they attacked). */
export interface UnsickEvent extends ReplayEventBase {
  kind: 'unsick';
  objs: ObjId[];
}
export interface CounterEvent extends ReplayEventBase {
  kind: 'counter';
  obj: ObjId;
  type: string;
  delta: number;
  total: number | null;
}
export interface PtEvent extends ReplayEventBase {
  kind: 'pt';
  obj: ObjId;
  power: number | null;
  toughness: number | null;
}
export interface AttachEvent extends ReplayEventBase {
  kind: 'attach';
  obj: ObjId;
  to: ObjId | null;
}
export interface IdentityEvent extends ReplayEventBase {
  kind: 'identity';
  obj: ObjId;
  card: CardKey;
  face_down: boolean;
}
export interface StackPushEvent extends ReplayEventBase {
  kind: 'stack_push';
  stack_id: string;
  obj: ObjId | null;
  card: CardKey | null;
  /**
   * The contract table calls this `kind`, which collides with the event
   * discriminator; the stream must send it as `stack_kind`. `item_kind` is
   * tolerated. Read it through `stackKindOf`.
   */
  stack_kind?: StackItemKind;
  item_kind?: StackItemKind;
  controller: number;
  text: string | null;
  targets: ObjId[];
}
export interface StackResolveEvent extends ReplayEventBase {
  kind: 'stack_resolve';
  stack_id: string;
}
export interface StackFizzleEvent extends ReplayEventBase {
  kind: 'stack_fizzle';
  stack_id: string;
}
export interface StackCounteredEvent extends ReplayEventBase {
  kind: 'stack_countered';
  stack_id: string;
}
export interface AttackEvent extends ReplayEventBase {
  kind: 'attack';
  seat: number;
  objs: ObjId[];
  target_seat: number | null;
  target_obj: ObjId | null;
}
export interface BlockPair {
  blocker: ObjId;
  attacker: ObjId;
}
export interface BlockEvent extends ReplayEventBase {
  kind: 'block';
  seat: number;
  pairs: BlockPair[];
}
export interface DamageEvent extends ReplayEventBase {
  kind: 'damage';
  source: ObjId | null;
  target_obj: ObjId | null;
  target_seat: number | null;
  amount: number;
  combat: boolean;
}
export interface RevealEvent extends ReplayEventBase {
  kind: 'reveal';
  obj: ObjId;
  card: CardKey;
}
export interface ScryEvent extends ReplayEventBase {
  kind: 'scry';
  seat: number;
  top: ObjId[];
  bottom: ObjId[];
  looked: number;
}
export interface ShuffleEvent extends ReplayEventBase {
  kind: 'shuffle';
  seat: number;
}
export interface GameEndEvent extends ReplayEventBase {
  kind: 'game_end';
  winner_seat: number | null;
  reason: string | null;
}
export interface NoteEvent extends ReplayEventBase {
  kind: 'note';
}

export type ReplayEvent =
  | GameStartEvent
  | TurnEvent
  | PhaseEvent
  | LifeEvent
  | MulliganEvent
  | MoveEvent
  | TapEvent
  | UntapEvent
  | SickEvent
  | UnsickEvent
  | CounterEvent
  | PtEvent
  | AttachEvent
  | IdentityEvent
  | StackPushEvent
  | StackResolveEvent
  | StackFizzleEvent
  | StackCounteredEvent
  | AttackEvent
  | BlockEvent
  | DamageEvent
  | RevealEvent
  | ScryEvent
  | ShuffleEvent
  | GameEndEvent
  | NoteEvent;

export type ReplayEventKind = ReplayEvent['kind'];
export type ReplayEventOf<K extends ReplayEventKind> = Extract<ReplayEvent, { kind: K }>;

export const EVENT_KINDS: readonly ReplayEventKind[] = [
  'game_start',
  'turn',
  'phase',
  'life',
  'mulligan',
  'move',
  'tap',
  'untap',
  'sick',
  'unsick',
  'counter',
  'pt',
  'attach',
  'identity',
  'stack_push',
  'stack_resolve',
  'stack_fizzle',
  'stack_countered',
  'attack',
  'block',
  'damage',
  'reveal',
  'scry',
  'shuffle',
  'game_end',
  'note',
];

export interface ReplayStream {
  version: number;
  fidelity: ReplayFidelity;
  replay_version: number | null;
  limitations: string[];
  game: ReplayGame;
  player_seat: number;
  seats: Record<string, ReplaySeat>;
  cards: Record<CardKey, ReplayCard>;
  turns: ReplayTurn[];
  events: ReplayEvent[];
}

export function isZone(value: unknown): value is Zone {
  return typeof value === 'string' && (ZONES as readonly string[]).includes(value);
}

export function stackKindOf(event: StackPushEvent): StackItemKind {
  return event.stack_kind ?? event.item_kind ?? (event.text ? 'trigger' : 'spell');
}
