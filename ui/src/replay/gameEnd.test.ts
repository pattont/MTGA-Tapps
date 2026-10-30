import { describe, expect, it } from 'vitest';
import { makeSampleStream } from './fixtures/sampleStream';
import { describeGameEnd, endReasonLabel, gameEndScore } from './gameEnd';
import { buildTimeline } from './reducer';

describe('endReasonLabel', () => {
  it('turns Arena codes into sentences from the player perspective', () => {
    expect(endReasonLabel('ResultReason_Concede', 'win')).toBe('Opponent conceded');
    expect(endReasonLabel('Concede', 'loss')).toBe('You conceded');
    expect(endReasonLabel('ResultReason_Game', 'loss')).toBe('You reached 0 life');
    expect(endReasonLabel('Timeout', 'win')).toBe('Opponent timed out');
    expect(endReasonLabel('DrawFromEmptyLib', 'loss')).toBe('You drew from an empty library');
  });

  it('passes stored sentences through and drops empty reasons', () => {
    expect(endReasonLabel('Opponent conceded/disconnected', 'win')).toBe('Opponent conceded/disconnected');
    expect(endReasonLabel('', 'win')).toBeNull();
    expect(endReasonLabel(null, 'loss')).toBeNull();
  });
});

describe('describeGameEnd', () => {
  it('reads the winner from the game_end event', () => {
    const stream = makeSampleStream();
    const timeline = buildTimeline(stream);
    const end = describeGameEnd(stream, timeline.final);
    expect(end).toEqual({ result: 'win', headline: 'Victory', reason: 'Opponent conceded' });
  });

  it('falls back to the game outcome when the event names no winner', () => {
    const stream = makeSampleStream();
    const last = stream.events[stream.events.length - 1];
    if (last.kind === 'game_end') {
      last.winner_seat = null;
      last.reason = null;
    }
    stream.game.outcome = 'loss';
    stream.game.outcome_reason = 'You reached 0 life';
    const timeline = buildTimeline(stream);
    const end = describeGameEnd(stream, timeline.final);
    expect(end).toEqual({ result: 'loss', headline: 'Defeat', reason: 'You reached 0 life' });
  });
});

describe('gameEndScore', () => {
  it('gives the final life totals, opponent name and game length the ending card shows', () => {
    const stream = makeSampleStream();
    const final = buildTimeline(stream).final;
    const score = gameEndScore(stream, final);
    const opponentSeat = Object.keys(stream.seats).map(Number).find((seat) => seat !== stream.player_seat) as number;
    expect(score.yourLife).toBe(final.life[stream.player_seat]);
    expect(score.theirLife).toBe(final.life[opponentSeat]);
    expect(score.opponentName).toBe(stream.seats[String(opponentSeat)].name || 'Opponent');
    expect(score.facts[0]).toBe(`${final.turn} turn${final.turn === 1 ? '' : 's'}`);
  });
});
