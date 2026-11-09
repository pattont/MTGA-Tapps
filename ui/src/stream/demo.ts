/** Sample data for `demo=1`, so streamers can place sources with no game running. */

import type { LiveGameRow, LivePayload, LiveSeenCard } from '../api';
import type { OverlayCard, OverlayPayload, OverlaySideCard } from './types';

function card(
  name: string,
  type_category: string,
  mana_cost: string | null,
  mana_value: number,
  total: number,
  left: number,
  library: number,
  land = false,
): OverlayCard {
  const next = library > 0 ? (100 * left) / library : 0;
  return {
    name,
    type_category,
    mana_cost,
    mana_value,
    total,
    left,
    land,
    basic: land && name === 'Forest',
    odds: { '1': next, '2': next * 1.9, '3': next * 2.7 },
  };
}

const LIBRARY = 46;

function side(name: string, type_category: string, mana_cost: string, mana_value: number, count: number): OverlaySideCard {
  return { name, type_category, mana_cost, mana_value, count, land: false };
}

export const DEMO_OVERLAY: OverlayPayload = {
  tracker: { state: 'live' },
  state: {
    game_active: true,
    game_over: false,
    mid_game_attach: false,
    deck_name: 'Mono-Green Stompy',
    format_label: 'Standard (Ranked)',
    turn_number: 5,
    match_type: 'best_of_3',
    opponent_name: 'Opponent',
    on_play: false,
    player_commanders: [],
    deck_size: 60,
    library_size: LIBRARY,
    lands_left: 15,
    lands_total: 22,
    land_odds: { '1': 32.6, '2': 54.9, '3': 70.1 },
    cards: [
      card('Llanowar Elves', 'Creature', '{G}', 1, 4, 3, LIBRARY),
      card('Tinder Wall', 'Creature', '{G}', 1, 4, 3, LIBRARY),
      card('Snakeskin Veil', 'Instant', '{G}', 1, 4, 0, LIBRARY),
      card('Royal Treatment', 'Instant', '{G}', 1, 4, 4, LIBRARY),
      card('Bristly Bill, Spine Sower', 'Creature', '{1}{G}', 2, 2, 2, LIBRARY),
      card('Mosswood Dreadknight', 'Creature', '{1}{G}', 2, 4, 4, LIBRARY),
      card('Questing Druid', 'Creature', '{1}{G}', 2, 4, 4, LIBRARY),
      card('Sentinel of the Nameless City', 'Creature', '{2}{G}', 3, 4, 3, LIBRARY),
      card('Ouroboroid', 'Creature', '{2}{G}{G}', 4, 4, 4, LIBRARY),
      card('Mightform Harmonizer', 'Creature', '{2}{G}{G}', 4, 4, 4, LIBRARY),
      card('Forest', 'Land', null, 0, 18, 12, LIBRARY, true),
      card('Fabled Passage', 'Land', null, 0, 4, 3, LIBRARY, true),
    ],
    unaccounted: 0,
    sideboard: [
      side('Pick Your Poison', 'Sorcery', '{G}', 1, 3),
      side('Ghost Vacuum', 'Artifact', '{1}', 1, 2),
      side('Tranquil Frillback', 'Creature', '{2}{G}', 3, 2),
      side('Thrun, Breaker of Silence', 'Creature', '{4}{G}{G}', 6, 2),
      side('Vaultborn Tyrant', 'Creature', '{5}{G}{G}', 7, 1),
    ],
  },
  head_to_head: { wins: 2, losses: 1 },
};

function game(
  n: number,
  outcome: 'win' | 'loss',
  wentFirst: 0 | 1,
  opponent: string,
  turns: number,
  minutes: number,
  gameNumber = 1,
  deck = 'Mono-Green Stompy',
): LiveGameRow {
  return {
    id: `demo:match:${n}:game:${gameNumber}`,
    started_at: null,
    outcome,
    outcome_reason: null,
    total_turns: turns,
    duration_seconds: minutes * 60,
    game_number: gameNumber,
    format: 'Standard (Ranked)',
    best_of: 3,
    deck_name: deck,
    went_first: wentFirst,
    opponent_name: opponent,
  };
}

/** The session's eight games (6–2), newest first. */
const DEMO_GAMES: LiveGameRow[] = [
  game(8, 'loss', 1, 'Opponent', 9, 14),
  game(7, 'win', 0, 'MoxMaven', 7, 11, 2),
  game(6, 'win', 1, 'MoxMaven', 6, 8),
  game(5, 'win', 1, 'TolarianTom', 8, 12, 2),
  game(4, 'loss', 0, 'TolarianTom', 11, 19),
  game(3, 'win', 1, 'TolarianTom', 6, 9, 3),
  game(2, 'win', 0, 'GoblinGuide42', 5, 6),
  game(1, 'win', 1, 'ElfballEnjoyer', 7, 10, 1, 'Golgari Midrange (Duskmourn Brew v3)'),
];

function seen(name: string, type: string, mana_cost: string | null, mana_value: number | null, count = 1): LiveSeenCard {
  return { name, type, mana_cost, mana_value, count };
}

/** Local time `seconds` ago, as the tracker writes it. */
function ago(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

/** What a Dimir opponent has shown by turn 5. */
const DEMO_SEEN: LiveSeenCard[] = [
  seen('Watery Grave', 'Land', null, null),
  seen('Island', 'Land', null, null, 2),
  seen('Deep-Cavern Bat', 'Creature', '{1}{B}', 2),
  seen('Cut Down', 'Instant', '{B}', 1, 2),
  seen('Swamp', 'Land', null, null),
  seen('Preacher of the Schism', 'Creature', '{2}{B}', 3),
  seen('Go for the Throat', 'Instant', '{1}{B}', 2),
  seen('Kaito, Bane of Nightmares', 'Planeswalker', '{2}{U}{B}', 4),
];

export const DEMO_LIVE: LivePayload = {
  tracker: { state: 'live', session_id: 'demo' },
  now: {
    in_game: true,
    last_game_frozen: false,
    match_id: 'demo',
    game_id: 'demo',
    format: 'Standard (Ranked)',
    match_type: 'best_of_3',
    game_number: 2,
    player_name: 'You',
    opponent_name: 'Opponent',
    deck_name: 'Mono-Green Stompy',
    turn_number: 5,
    active_role: 'player',
    on_play: false,
    player_life: 17,
    opponent_life: 12,
    mulligans: 0,
    game_started_at: null,
    turn_started_at: ago(42),
    player_commanders: [],
    opponent_commanders: [],
    player_colors: 'G',
    opponent_colors: 'UB',
    head_to_head: { wins: 2, losses: 1 },
    deck_record: {
      wins: 34,
      losses: 21,
      win_rate: 61.8,
      today_wins: 4,
      today_losses: 1,
      session_wins: 3,
      session_losses: 1,
      ranked: { wins: 22, losses: 12 },
      unranked: { wins: 12, losses: 9 },
      play: { wins: 19, losses: 9 },
      draw: { wins: 15, losses: 12 },
      recent: ['win', 'win', 'win', 'loss', 'win', 'loss', 'win', 'win', 'loss', 'win'],
    },
    rank: {
      rank_format: 'constructed',
      rank_class: 'Diamond',
      rank_level: 2,
      rank_step: 3,
      rank_steps: 6,
      mythic_percentile: null,
      mythic_rank: null,
      start: {
        rank_class: 'Diamond',
        rank_level: 4,
        rank_step: 1,
        rank_steps: 6,
        mythic_percentile: null,
        mythic_rank: null,
      },
    },
    match_score: { wins: 1, losses: 0, draws: 0 },
    opponent_seen: DEMO_SEEN,
    draw_quality: {
      lands_seen: 5,
      total_cards_seen: 12,
      ramped_lands: 0,
      expected_lands_seen: 4.4,
      expected_land_rate: 36.7,
      deck_size: 60,
      deck_lands: 22,
      flood_probability_pct: 36.2,
      screw_probability_pct: 85.1,
      is_flood: false,
      is_screw: false,
      is_land_streak: false,
      reason: null,
      next_land_pct: 32.6,
      library_size: 46,
      lands_left: 15,
    },
    archetype_guess: { archetype: 'Dimir Midrange', matched_cards: 4, wins: 7, losses: 5 },
  },
  session: {
    id: 'demo',
    started_at: ago(2 * 3600 + 14 * 60),
    games_played: 8,
    wins: 6,
    losses: 2,
    draws: 0,
    runtime_seconds: null,
    win_rate: 75,
    play: { wins: 4, losses: 1 },
    draw: { wins: 2, losses: 1 },
  },
  today: {
    games: 11,
    wins: 8,
    losses: 3,
    draws: 0,
    win_rate: 72.7,
    play: { wins: 5, losses: 1 },
    draw: { wins: 3, losses: 2 },
  },
  games: DEMO_GAMES,
  events: [],
  seq: 0,
};

/** Cards the spotlight demo cycles through. */
export const DEMO_CASTS: Array<{ name: string; role: 'player' | 'opponent' }> = [
  { name: 'Llanowar Elves', role: 'player' },
  { name: 'Go for the Throat', role: 'opponent' },
  { name: 'Sentinel of the Nameless City', role: 'player' },
  { name: 'Preacher of the Schism', role: 'opponent' },
];

/** The game the result widget shows in demo mode: a win on the draw. */
export const DEMO_RESULT: LiveGameRow = DEMO_GAMES[1];
