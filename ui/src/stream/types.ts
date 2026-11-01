/**
 * The `/api/overlay` payload, as overlay_state.py writes it. The in-game
 * overlay keeps its own copy of these shapes (overlay/src/types.ts); this is
 * the subset the stream widgets read.
 */

export interface OverlayCard {
  name: string;
  type_category: string;
  mana_cost: string | null;
  mana_value: number | null;
  total: number;
  left: number;
  land: boolean;
  basic: boolean;
  odds: Record<'1' | '2' | '3', number>;
}

export interface OverlaySideCard {
  name: string;
  type_category: string;
  mana_cost: string | null;
  mana_value: number | null;
  count: number;
  land: boolean;
}

export interface OverlayState {
  game_active: boolean;
  game_over: boolean;
  mid_game_attach: boolean;
  deck_name: string | null;
  format_label: string | null;
  turn_number: number | null;
  match_type?: string | null;
  opponent_name?: string | null;
  on_play?: boolean | null;
  player_commanders: string[];
  deck_size: number;
  library_size: number;
  lands_left: number;
  lands_total: number;
  land_odds: Record<'1' | '2' | '3', number>;
  cards: OverlayCard[];
  /** Cards in the library the tracker can't name. */
  unaccounted?: number;
  /** The submitted sideboard, one row per distinct card. */
  sideboard?: OverlaySideCard[];
}

export interface OverlayPayload {
  tracker: { state: 'live' | 'idle' | 'offline' };
  state: OverlayState | null;
  head_to_head?: { wins: number; losses: number } | null;
}
