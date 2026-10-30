/**
 * Hand-written five-turn game that exercises every stream event kind.
 * The local player is seat 2 and the opponent (seat 1) goes first, so any
 * code that assumes "player = seat 1" fails these tests.
 *
 * Final position: player hand 213 216 217 218, battlefield 211 214 215
 * (Insectile Aberration, Pacifism 106 attached); opponent hand 107 108 (hidden),
 * battlefield 101 103 106; player wins.
 */
import type { ReplayCard, ReplayStream } from '../types';
import { StreamBuilder, card } from './streamBuilder';

export { makeLongStream } from './longStream';

export const PLAYER = 2;
export const OPPONENT = 1;

export const SAMPLE_CARDS: Record<string, ReplayCard> = {
  a1001: card('Forest', 'Land', { arena_id: 1001, type_line: 'Basic Land — Forest' }),
  a1002: card('Llanowar Elves', 'Creature', { arena_id: 1002, power: '1', toughness: '1' }),
  a1003: card('Swamp', 'Land', { arena_id: 1003, type_line: 'Basic Land — Swamp' }),
  a1004: card('Cut Down', 'Instant', { arena_id: 1004 }),
  a1005: card('Pacifism', 'Enchantment', { arena_id: 1005, type_line: 'Enchantment — Aura' }),
  a1006: card('Grizzly Bears', 'Creature', { arena_id: 1006, power: '2', toughness: '2' }),
  'n:Saproling': card('Saproling', 'Creature', {
    type_line: 'Token Creature — Saproling',
    power: '1',
    toughness: '1',
    is_token: true,
  }),
  a1008: card('Negate', 'Instant', { arena_id: 1008 }),
  a1010: card('Delver of Secrets // Insectile Aberration', 'Creature', {
    arena_id: 1010,
    power: '1',
    toughness: '1',
    image_url: 'https://cards.scryfall.io/normal/front/1/1/delver.jpg',
  }),
  a1011: card('Insectile Aberration', 'Creature', { arena_id: 1011, power: '3', toughness: '2' }),
  a1012: card('Opt', 'Instant', { arena_id: 1012 }),
};

const OPENING_HAND = ['a1001', 'a1001', 'a1001', 'a1002', 'a1006', 'a1012', 'a1010'];
const KEPT_HAND: Array<[string, string]> = [
  ['211', 'a1001'],
  ['212', 'a1002'],
  ['213', 'a1006'],
  ['214', 'a1001'],
  ['215', 'a1010'],
  ['216', 'a1012'],
];

export function makeSampleStream(): ReplayStream {
  const b = new StreamBuilder();
  b.add('game_start', { seats_hand_sizes: { 1: 7, 2: 7 }, library_sizes: { 1: 53, 2: 53 } }, { dt: 0 });
  OPENING_HAND.forEach((key, i) => b.move(String(201 + i), key, 'library', 'hand', PLAYER, 'draw', { dt: 0 }));
  for (let i = 0; i < 7; i += 1) b.move(String(101 + i), null, 'library', 'hand', OPPONENT, 'draw', { dt: 0 });
  b.add('mulligan', { seat: PLAYER, from_size: 7, to_size: 6, bottomed: [] });
  for (const [obj, key] of KEPT_HAND) b.move(obj, key, 'library', 'hand', PLAYER, 'draw', { dt: 0 });

  // Turn 1 (opponent)
  b.turnStart(1, OPPONENT);
  b.phaseTo('Phase_Main1');
  b.move('101', 'a1003', 'hand', 'battlefield', OPPONENT, 'play_land');
  b.add('note', {}, { text: 'Opponent passes' });

  // Turn 2 (player): Llanowar Elves is countered by Negate.
  b.turnStart(2, PLAYER);
  b.phaseTo('Phase_Beginning', 'Step_Draw');
  b.move('217', 'a1001', 'library', 'hand', PLAYER, 'draw');
  b.phaseTo('Phase_Main1');
  b.move('211', 'a1001', 'hand', 'battlefield', PLAYER, 'play_land');
  b.add('tap', { objs: ['211'] });
  b.cast('212', 'a1002', PLAYER, 's1');
  b.add('tap', { objs: ['101'] });
  b.cast('102', 'a1008', OPPONENT, 's2', ['212']);
  b.resolve('102', 'a1008', OPPONENT, 's2', 'graveyard');
  b.add('stack_countered', { stack_id: 's1' }, { text: 'countered' });
  b.move('212', 'a1002', 'stack', 'graveyard', PLAYER, 'counter');

  // Turn 3 (opponent): Grizzly Bears.
  b.turnStart(3, OPPONENT);
  b.add('untap', { objs: ['101'] });
  b.move('108', null, 'library', 'hand', OPPONENT, 'draw');
  b.phaseTo('Phase_Main1');
  b.move('103', 'a1003', 'hand', 'battlefield', OPPONENT, 'play_land');
  b.cast('104', 'a1006', OPPONENT, 's3');
  b.resolve('104', 'a1006', OPPONENT, 's3', 'battlefield');
  b.add('sick', { objs: ['104'] });
  b.add('life', { seat: OPPONENT, life: 19, delta: -1, source_obj: null }, { text: 'Opponent lost 1 life' });

  // Turn 4 (player): Delver, token, counters, scry, reveal, fizzle, combat.
  b.turnStart(4, PLAYER);
  b.add('untap', { objs: ['211'] });
  b.move('218', 'a1001', 'library', 'hand', PLAYER, 'draw');
  b.phaseTo('Phase_Main1');
  b.move('214', 'a1001', 'hand', 'battlefield', PLAYER, 'play_land');
  b.add('tap', { objs: ['211', '214'] });
  b.cast('215', 'a1010', PLAYER, 's4');
  b.resolve('215', 'a1010', PLAYER, 's4', 'battlefield');
  b.move('tok1', 'n:Saproling', 'limbo', 'battlefield', PLAYER, 'token_create');
  b.add('counter', { obj: 'tok1', type: '+1/+1', delta: 1, total: 1 });
  b.add('pt', { obj: 'tok1', power: 2, toughness: 2 });
  b.add(
    'stack_push',
    { stack_id: 's5', obj: '215', card: 'a1010', stack_kind: 'trigger', controller: PLAYER, text: 'Look at the top card', targets: [] },
    { text: 'trigger' },
  );
  b.add('stack_resolve', { stack_id: 's5' });
  b.add('scry', { seat: PLAYER, top: ['230'], bottom: ['231'], looked: 2 }, { text: 'scried 2' });
  b.add('reveal', { obj: '105', card: 'a1004' });
  b.cast('105', 'a1004', OPPONENT, 's6', ['tok1']);
  b.move('tok1', 'n:Saproling', 'battlefield', 'graveyard', PLAYER, 'sacrifice');
  b.move('tok1', 'n:Saproling', 'graveyard', 'limbo', PLAYER, 'token_cease');
  b.add('stack_fizzle', { stack_id: 's6' }, { text: 'fizzled' });
  b.move('105', 'a1004', 'stack', 'graveyard', OPPONENT, 'resolve');
  b.phaseTo('Phase_Combat', 'Step_DeclareAttack');
  b.add('attack', { seat: PLAYER, objs: ['215'], target_seat: OPPONENT, target_obj: null }, { text: 'attack' });
  b.add('block', { seat: OPPONENT, pairs: [{ blocker: '104', attacker: '215' }] });
  b.add('identity', { obj: '215', card: 'a1011', face_down: false });
  b.add('damage', { source: '215', target_obj: '104', target_seat: null, amount: 3, combat: true });
  b.add('damage', { source: '104', target_obj: '215', target_seat: null, amount: 2, combat: true });
  b.move('104', 'a1006', 'battlefield', 'graveyard', OPPONENT, 'sba');
  b.phaseTo('Phase_Main2');

  // Turn 5 (opponent): Pacifism on the Aberration, burn, shuffle, concede.
  b.turnStart(5, OPPONENT);
  b.add('unsick', { objs: ['104'] });
  b.phaseTo('Phase_Main1');
  b.cast('106', 'a1005', OPPONENT, 's7', ['215']);
  b.resolve('106', 'a1005', OPPONENT, 's7', 'battlefield');
  b.add('attach', { obj: '106', to: '215' });
  b.add('damage', { source: null, target_obj: null, target_seat: PLAYER, amount: 2, combat: false });
  b.add('life', { seat: PLAYER, life: 18, delta: -2, source_obj: null }, { text: 'You lost 2 life' });
  b.add('shuffle', { seat: PLAYER });
  b.add('game_end', { winner_seat: PLAYER, reason: 'Concede' }, { text: 'Opponent conceded' });

  return b.build(SAMPLE_CARDS, { playerSeat: PLAYER, firstSeat: OPPONENT });
}

export const sampleStream: ReplayStream = makeSampleStream();
