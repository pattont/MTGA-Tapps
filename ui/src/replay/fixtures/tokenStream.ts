import { StreamBuilder, card } from './streamBuilder';

/**
 * Three identical Spirit tokens (seat 1) with two +1/+1 counters each, a
 * fourth without counters, tapped and attacking the opponent's planeswalker.
 */
export function makeTokenStream() {
  const b = new StreamBuilder();
  b.add('game_start', { seats_hand_sizes: { 1: 0, 2: 0 }, library_sizes: { 1: 40, 2: 40 } });
  b.turnStart(1, 1);
  b.move('pw', 'a2', 'limbo', 'battlefield', 2, 'put');
  b.add('counter', { obj: 'pw', type: 'loyalty', delta: 4, total: 4 });
  for (const obj of ['t1', 't2', 't3', 't4']) b.move(obj, 'a1', 'limbo', 'battlefield', 1, 'token_create');
  for (const obj of ['t1', 't2', 't3']) b.add('counter', { obj, type: '+1/+1', delta: 2, total: 2 });
  b.phaseTo('Phase_Combat', 'Step_DeclareAttack');
  b.add('tap', { objs: ['t1', 't2', 't3', 't4'] });
  b.add('attack', { seat: 1, objs: ['t1', 't2', 't3', 't4'], target_seat: null, target_obj: 'pw' }, { text: 'attack' });
  return b.build(
    {
      a1: card('Ninja Turtle Spirit', 'Creature', { is_token: true, power: '1', toughness: '1' }),
      a2: card('Jace', 'Planeswalker', { is_token: true }),
    },
    { playerSeat: 1 },
  );
}
