import type { OverlayPayload, OverlayState } from '../types';

export function card(name: string, type: string, cost: string | null, total: number, left: number, library: number, extra: Partial<OverlayState['cards'][number]> = {}) {
  const mv = cost ? (cost.match(/\{([^}]+)\}/g) ?? []).reduce((sum, s) => sum + (/^\{\d+\}$/.test(s) ? Number(s.slice(1, -1)) : 1), 0) : 0;
  const odds = (n: number) => (left <= 0 || library <= 0 ? 0 : Math.round((1 - [...Array(Math.min(n, library))].reduce((r, _, i) => (r * (library - left - i)) / (library - i), 1)) * 1000) / 10);
  return {
    name,
    type_category: type,
    mana_cost: cost,
    mana_value: mv,
    total,
    left,
    land: type === 'Land',
    basic: ['Plains', 'Island', 'Swamp', 'Mountain', 'Forest'].includes(name),
    odds: { '1': odds(1), '2': odds(2), '3': odds(3) },
    ...extra,
  };
}

/** Mono-red-ish 60-card deck, turn 5, 41 in the library. */
export function inGameState(): OverlayState {
  const lib = 41;
  const cards = [
    card('Monastery Swiftspear', 'Creature', '{R}', 4, 2, lib),
    card('Heartfire Hero', 'Creature', '{R}', 4, 3, lib),
    card('Emberheart Challenger', 'Creature', '{1}{R}', 4, 4, lib),
    card('Slickshot Show-Off', 'Creature', '{1}{R}', 4, 3, lib),
    card('Screaming Nemesis', 'Creature', '{2}{R}', 3, 2, lib),
    card('Lightning Strike', 'Instant', '{1}{R}', 4, 3, lib),
    card('Monstrous Rage', 'Instant', '{R}', 4, 4, lib),
    card('Shock', 'Instant', '{R}', 4, 0, lib),
    card('Torch the Tower', 'Instant', '{R}', 2, 2, lib),
    card('Witchstalker Frenzy', 'Instant', '{2}{R}', 2, 2, lib),
    card('Burst Lightning', 'Instant', '{R}', 3, 3, lib),
    card('Kumano Faces Kakkazan', 'Enchantment', '{R}', 2, 2, lib),
    card('Mountain', 'Land', null, 16, 8, lib),
    card('Rockface Village', 'Land', null, 4, 3, lib),
  ];
  const landsLeft = 11;
  return {
    game_active: true,
    mid_game_attach: false,
    deck_name: 'Mono-Red Aggro',
    format_label: 'Standard Best-of-1 (Ranked)',
    match_type: 'Ladder',
    opponent_name: 'sansastark',
    turn_number: 5,
    on_play: true,
    player_commanders: [],
    opponent_commanders: [],
    deck_size: 60,
    library_size: lib,
    unaccounted: 0,
    lands_left: landsLeft,
    lands_total: 20,
    land_odds: { '1': 26.8, '2': 47.3, '3': 62.1 },
    cards,
    updated_at: '2026-09-02T18:00:00Z',
  };
}

export function inGamePayload(): OverlayPayload {
  return { tracker: { state: 'live', updated_at: '2026-09-02T18:00:00Z', session_id: 's1' }, state: inGameState(), head_to_head: { wins: 1, losses: 2 } };
}

export function idlePayload(): OverlayPayload {
  return {
    tracker: { state: 'idle', updated_at: null, session_id: 's1' },
    state: { ...inGameState(), game_active: false, deck_name: null, opponent_name: null, turn_number: null, cards: [], library_size: 0, deck_size: 0, lands_left: 0, lands_total: 0, land_odds: { '1': 0, '2': 0, '3': 0 } },
    head_to_head: null,
  };
}

export function offlinePayload(): OverlayPayload {
  return { tracker: { state: 'offline', updated_at: null, session_id: null }, state: null, head_to_head: null };
}

export function brawlState(): OverlayState {
  const lib = 84;
  const names = ['Sol Ring', 'Arcane Signet', 'Swords to Plowshares', 'Counterspell', 'Teferi, Hero of Dominaria', 'Wrath of God', 'Mulldrifter', 'Path to Exile'];
  const cards = names.map((n, i) => card(n, i % 2 ? 'Instant' : 'Creature', i % 3 ? '{1}{W}' : '{U}{U}', 1, i < 3 ? 0 : 1, lib));
  cards.push(card('Plains', 'Land', null, 18, 15, lib), card('Island', 'Land', null, 16, 14, lib), card('Hallowed Fountain', 'Land', null, 1, 1, lib));
  return {
    ...inGameState(),
    deck_name: 'Azorius Control',
    format_label: 'Historic Brawl',
    player_commanders: ['Teferi, Time Raveler'],
    deck_size: 100,
    library_size: lib,
    lands_left: 30,
    lands_total: 35,
    cards,
  };
}
