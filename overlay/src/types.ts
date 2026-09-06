/** Shapes shared with the Python side (overlay_state.py, live_api.py) and the Rust side (settings.rs). */

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
  /** The game ended but Arena is still on the results screen: the final library stays up. */
  game_over: boolean;
  mid_game_attach: boolean;
  deck_name: string | null;
  format_label: string | null;
  match_type: string | null;
  opponent_name: string | null;
  turn_number: number | null;
  on_play: boolean | null;
  player_commanders: string[];
  opponent_commanders: string[];
  deck_size: number;
  library_size: number;
  unaccounted: number;
  lands_left: number;
  lands_total: number;
  land_odds: Record<'1' | '2' | '3', number>;
  cards: OverlayCard[];
  /** The submitted sideboard, one row per distinct card (no odds). */
  sideboard?: OverlaySideCard[];
  updated_at: string | null;
}

export interface OverlayPayload {
  tracker: { state: 'live' | 'idle' | 'offline'; updated_at: string | null; session_id: string | null };
  state: OverlayState | null;
  head_to_head: { wins: number; losses: number } | null;
}

export type Dock = 'left' | 'right' | 'float';

export interface Hotkeys {
  toggle: string;
  visibility: string;
}

export interface Settings {
  /** Background slider, 0–1: only the charcoal ground (≈88 % at 1, gone at 0); text is always fully visible. */
  opacity: number;
  /** The same, for the minimized rail on its own (it is small enough to want its own setting). */
  railOpacity: number;
  /** Size of everything, percent (50–200). */
  scale: number;
  /** The panel never grows past this share of the screen height (30–100). */
  panelMaxHeightPct: number;
  dock: Dock;
  returnAfterSeconds: number;
  openPinned: boolean;
  clickThroughWhenPinned: boolean;
  lands: 'grouped' | 'all';
  density: 'comfortable' | 'compact';
  /** Card names in their type colour, or plain white. */
  nameColor: 'type' | 'white';
  followArena: boolean;
  hideWhenArenaNotInFront: boolean;
  apiUrl: string;
  hotkeysMacos: Hotkeys;
  hotkeysWindows: Hotkeys;
  positions: { leftY: number | null; rightY: number | null; floatX: number | null; floatY: number | null };
  monitor: string | null;
}

export interface LayoutInfo {
  layout: 'rail' | 'panel';
  pinned: boolean;
  visible: boolean;
  dock: Dock;
}

export type SortKey = 'odds' | 'mana' | 'name';

/** Connection state the page derives from the poll loop. */
export type Link = 'connecting' | 'online' | 'offline';
