import { describe, expect, it } from 'vitest';
import type { LiveGameRow, LiveNow } from '../api';
import { DEMO_LIVE } from './demo';
import {
  clock,
  groupSeen,
  hypergeomPmf,
  landZones,
  matchLine,
  percent,
  periodGames,
  periodRecord,
  rankName,
  rankOrder,
  resultFacts,
  secondsSince,
  showsGame,
  span,
  streak,
} from './liveView';

const now = DEMO_LIVE.now as LiveNow;

function game(overrides: Partial<LiveGameRow> = {}): LiveGameRow {
  return {
    id: 'g1',
    started_at: null,
    outcome: 'win',
    outcome_reason: null,
    total_turns: 9,
    duration_seconds: 600,
    game_number: 1,
    format: 'Standard (Ranked)',
    best_of: 1,
    deck_name: 'Stompy',
    went_first: 1,
    opponent_name: 'Villain',
    ...overrides,
  };
}

describe('live view helpers', () => {
  it('formats clocks, spans and rates', () => {
    expect(clock(42)).toBe('0:42');
    expect(clock(725)).toBe('12:05');
    expect(clock(3729)).toBe('1:02:09');
    expect(span(38 * 60)).toBe('38m');
    expect(span(2 * 3600 + 4 * 60)).toBe('2h 04m');
    expect(percent(61.8)).toBe('61.8%');
    expect(percent(75)).toBe('75%');
    expect(percent(null)).toBe('—');
    expect(secondsSince('2026-11-05T10:00:00Z', Date.parse('2026-11-05T10:01:30Z'))).toBe(90);
    expect(secondsSince(null, 0)).toBeNull();
  });

  it('picks the games and record for a session or today', () => {
    const at = (id: string, started_at: string | null) => game({ id, started_at });
    const payload = {
      ...DEMO_LIVE,
      session: { ...DEMO_LIVE.session!, id: 'S2' },
      games: [at('S2:match:2:game:1', '2026-11-06T00:10:00'), at('S1:match:9:game:1', '2026-11-05T23:50:00')],
    };
    const midnight = new Date(2026, 10, 6, 0, 30).getTime();
    expect(periodGames(payload, 'session', midnight).map((row) => row.id)).toEqual(['S2:match:2:game:1']);
    expect(periodGames(payload, 'today', midnight).map((row) => row.id)).toEqual(['S2:match:2:game:1']);
    const late = { ...payload, session: { ...payload.session, id: 'S1' } };
    // Past midnight the session still holds the game from yesterday evening.
    expect(periodGames(late, 'session', midnight).map((row) => row.id)).toEqual(['S1:match:9:game:1']);
    expect(periodRecord(payload, 'today')).toBe(DEMO_LIVE.today);
    expect(periodRecord(payload, 'session')?.wins).toBe(6);
    expect(periodRecord(null, 'today')).toBeNull();
  });

  it('finds the current streak', () => {
    expect(streak(['win', 'win', 'loss', 'win'])).toEqual({ outcome: 'win', length: 2 });
    expect(streak(['loss'])).toEqual({ outcome: 'loss', length: 1 });
    expect(streak([])).toBeNull();
    expect(streak(undefined)).toBeNull();
  });

  it('shows game widgets in a game, and between games only with idle=show', () => {
    expect(showsGame(now, 'hide')).toBe(true);
    const between = { ...now, in_game: false, last_game_frozen: true };
    expect(showsGame(between, 'hide')).toBe(false);
    expect(showsGame(between, 'show')).toBe(true);
    expect(showsGame({ ...between, last_game_frozen: false }, 'show')).toBe(false);
    expect(showsGame(null, 'show')).toBe(false);
  });

  it('groups the opponent’s cards by type, lands apart', () => {
    const { groups, lands } = groupSeen(now.opponent_seen ?? []);
    expect(groups.map((group) => [group.label, group.cards.map((card) => card.name)])).toEqual([
      ['Creatures', ['Deep-Cavern Bat', 'Preacher of the Schism']],
      ['Planeswalkers', ['Kaito, Bane of Nightmares']],
      ['Instants & sorceries', ['Cut Down', 'Go for the Throat']],
    ]);
    // Most played first.
    expect(lands.map((card) => card.name)).toEqual(['Island', 'Swamp', 'Watery Grave']);
    // A land with a mana cost (a modal double-faced card's front) stays with the spells.
    const mdfc = groupSeen([{ name: 'Fell the Profane // Fell Mire', type: 'Land', mana_cost: '{2}{B}{B}', mana_value: 4, count: 1 }]);
    expect(mdfc.lands).toEqual([]);
    expect(mdfc.groups[0].label).toBe('Other');
  });

  it('matches draw_quality’s 10 % flood and screw tails', () => {
    // Reference bounds from draw_quality.hypergeom_tail_at_most / _at_least.
    expect(landZones(60, 24, 15)).toEqual({ screwMax: 3, floodMin: 9 });
    expect(landZones(60, 22, 12)).toEqual({ screwMax: 2, floodMin: 7 });
    expect(landZones(99, 36, 20)).toEqual({ screwMax: 4, floodMin: 11 });
    expect(landZones(40, 17, 7)).toEqual({ screwMax: 0, floodMin: 6 });
    const total = Array.from({ length: 8 }, (_, k) => hypergeomPmf(k, 60, 24, 7)).reduce((a, b) => a + b, 0);
    expect(total).toBeCloseTo(1, 10);
  });

  it('picks result highlights', () => {
    const frozen = { ...now, in_game: false, game_id: 'g1', player_life: 20, opponent_life: 0, draw_quality: null };
    expect(resultFacts(game({ went_first: 0, total_turns: 5 }), frozen)).toEqual([
      'Untouched: finished on 20 life',
      'Won on the draw',
    ]);
    const flooded = { ...now, player_life: 3, opponent_life: 2, draw_quality: { ...now.draw_quality!, is_flood: true, lands_seen: 10, total_cards_seen: 15 } };
    expect(resultFacts(game({ outcome: 'loss' }), flooded)).toEqual(['Flooded: 10 lands in 15 cards', 'So close: they were on 2 life']);
    expect(resultFacts(game({ total_turns: 6 }), null)).toEqual(['Turn-6 win']);
    expect(resultFacts(game({ outcome: 'loss' }), null)).toEqual([]);
  });

  it('describes the match in Bo3 only', () => {
    expect(matchLine(game(), now)).toBeNull();
    const bo3 = game({ best_of: 3, game_number: 2 });
    expect(matchLine(bo3, { ...now, match_score: { wins: 1, losses: 1, draws: 0 } })).toBe('Game 2 · Match 1–1');
    expect(matchLine(bo3, { ...now, match_score: { wins: 2, losses: 1, draws: 0 } })).toBe('Match won 2–1');
    expect(matchLine(bo3, { ...now, match_score: { wins: 0, losses: 2, draws: 0 } })).toBe('Match lost 0–2');
  });

  it('orders ranks for the climb', () => {
    const rank = (rank_class: string, rank_level: number, rank_step = 0) => ({
      rank_class,
      rank_level,
      rank_step,
      rank_steps: 6,
      mythic_percentile: null,
      mythic_rank: null,
    });
    expect(rankOrder(rank('Gold', 1)) > rankOrder(rank('Gold', 2))).toBe(true);
    expect(rankOrder(rank('Platinum', 4)) > rankOrder(rank('Gold', 1, 5))).toBe(true);
    expect(rankOrder(rank('Gold', 2, 3)) > rankOrder(rank('Gold', 2, 1))).toBe(true);
    expect(rankOrder({ ...rank('Mythic', 0), mythic_rank: 500 }) > rankOrder(rank('Diamond', 1, 5))).toBe(true);
    expect(rankName(rank('Diamond', 2))).toBe('Diamond 2');
    expect(rankName({ ...rank('Mythic', 0), mythic_percentile: 92 })).toBe('Mythic 92%');
  });
});
