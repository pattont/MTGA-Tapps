import { describe, expect, it } from 'vitest';
import { castCardName, ingestFeed, START_CURSOR, type FeedEvent } from './spotlight';

function cast(id: number, text: string, actor: string | null = 'opponent', segments?: FeedEvent['text_segments']): FeedEvent {
  return { id, event_type: 'cast', actor_role: actor, text, text_segments: segments };
}

describe('castCardName', () => {
  it('prefers the linked card segment and falls back to the bracket text', () => {
    expect(
      castCardName(cast(1, '[4:37] Opponent: cast [Memory Trap (Enchantment)]', 'opponent', [
        { kind: 'text' },
        { kind: 'card', card_name: 'Memory Trap' },
      ])),
    ).toBe('Memory Trap');
    expect(castCardName(cast(2, '[2:25] Opponent: cast [Duress (Sorcery)] -> [you]'))).toBe('Duress');
    expect(castCardName(cast(3, '[3:50] You: cast [Nova Hellkite (Creature 4/5)]', 'player'))).toBe('Nova Hellkite');
    expect(castCardName(cast(4, '[1:00] You: cast [Fire // Ice (Instant)]', 'player'))).toBe('Fire // Ice');
  });

  it('ignores other events and hidden cards', () => {
    expect(castCardName({ id: 5, event_type: 'land', actor_role: 'player', text: 'You: play [Forest (Land)]' })).toBeNull();
    expect(castCardName(cast(6, 'Opponent: cast [Card #12345]'))).toBeNull();
  });
});

describe('ingestFeed', () => {
  const history = [
    cast(10, 'Opponent: cast [Duress (Sorcery)]'),
    cast(11, 'You: cast [Llanowar Elves (Creature 1/1)]', 'player'),
  ];

  it('catches up silently before spotlighting anything', () => {
    // First answer: the game so far. Nothing shows.
    let step = ingestFeed(START_CURSOR, history, 11, 'both');
    expect(step).toEqual({ cursor: { seq: 11, caughtUp: false }, cast: null });
    // Next poll re-sends the tail only: caught up, still nothing shown.
    step = ingestFeed(step.cursor, history, 11, 'both');
    expect(step).toEqual({ cursor: { seq: 11, caughtUp: true }, cast: null });
    // A new cast after that is spotlighted; the re-sent tail is not.
    step = ingestFeed(step.cursor, [...history, cast(12, 'Opponent: cast [Go for the Throat (Instant)]')], 12, 'both');
    expect(step.cast).toEqual({ id: 12, name: 'Go for the Throat', role: 'opponent' });
    expect(step.cursor).toEqual({ seq: 12, caughtUp: true });
  });

  it('is caught up at once when there is no game yet', () => {
    expect(ingestFeed(START_CURSOR, [], 0, 'both')).toEqual({ cursor: { seq: 0, caughtUp: true }, cast: null });
  });

  it('shows the newest wanted cast and filters by who cast it', () => {
    const cursor = { seq: 11, caughtUp: true };
    const fresh = [
      cast(12, 'Opponent: cast [Duress (Sorcery)]'),
      cast(13, 'You: cast [Tinder Wall (Creature 0/3)]', 'player'),
      { id: 14, event_type: 'land', actor_role: 'opponent', text: 'Opponent: play [Swamp (Land)]' },
    ];
    expect(ingestFeed(cursor, fresh, 14, 'both').cast?.name).toBe('Tinder Wall');
    expect(ingestFeed(cursor, fresh, 14, 'opponent').cast?.name).toBe('Duress');
    expect(ingestFeed(cursor, fresh, 14, 'you').cast?.name).toBe('Tinder Wall');
    expect(ingestFeed(cursor, [cast(15, 'cast [Shock (Instant)]', null)], 15, 'both').cast).toBeNull();
  });
});
