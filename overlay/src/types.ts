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
  /** Cards that left the library without the log naming them: every `left` is then a ceiling. */
  unseen?: number;
  /** What the odds are taken over: the library, or with `unseen` every card not seen to leave. */
  draw_pool?: number;
  /** Arena summarized a message and has not listed the library since. */
  log_gap?: boolean;
  lands_left: number;
  lands_total: number;
  land_odds: Record<'1' | '2' | '3', number>;
  cards: OverlayCard[];
  /** The submitted sideboard, one row per distinct card (no odds). */
  sideboard?: OverlaySideCard[];
  updated_at: string | null;
}

export interface Score {
  wins: number;
  losses: number;
}

/** A ladder rank as the tracker last saw it. */
export interface OverlayRank {
  rank_class: string;
  rank_level: number;
  rank_step: number;
  rank_steps: number;
  mythic_percentile: number | null;
  mythic_rank: number | null;
}

/** Today's record, every game since local midnight (the Stream Kit record widget's totals), with the play/draw split. */
export interface OverlayToday extends Score {
  games: number;
  draws: number;
  win_rate: number | null;
  /** Games with unknown turn order count in neither. */
  play: Score;
  draw: Score;
  /** The ladder rank while the game on screen is ranked; null in any other queue. Absent from older trackers. */
  rank?: OverlayRank | null;
  /** Today's record with the deck on screen; null before its first result today. */
  deck?: Score | null;
}

/** A card the opponent has played this game (live_status.opponent_seen). */
export interface OpponentCard {
  name: string;
  /** Arena's type category ("Creature", "Land", ...). */
  type: string;
  mana_cost: string | null;
  mana_value: number | null;
  /** Times played this game. */
  count: number;
}

/** The opponent panel's block (live_api._overlay_opponent). */
export interface OverlayOpponent {
  /** WUBRG letters shown so far. */
  colors: string;
  /** Lands they have played. */
  lands: number;
  deck: {
    label: string | null;
    /** Where the name came from: their commander(s), your Deck AI history, the colour name, or nothing yet. */
    source: 'commander' | 'history' | 'colors' | 'none';
    /** Cards that matched the history guess. */
    matched_cards: number | null;
  };
  /** Your record against the deck line's subject; null before any. */
  record: Score | null;
  seen: OpponentCard[];
}

export interface OverlayPayload {
  tracker: { state: 'live' | 'idle' | 'offline'; session_id: string | null };
  state: OverlayState | null;
  head_to_head: Score | null;
  /** Today's record for the footer; null while the tracker is off. */
  today?: OverlayToday | null;
  /** Only while a game is on screen; absent from trackers older than the opponent panel. */
  opponent?: OverlayOpponent | null;
  /** The flood meter's numbers (the live game's, or the last game's between games); absent from older trackers. */
  draw_quality?: OverlayDrawQuality | null;
}

/** The tracker's live draw-quality numbers (`/api/live`'s `now.draw_quality`, the Stream Kit Lands widget's). */
export interface OverlayDrawQuality {
  lands_seen: number;
  total_cards_seen: number;
  expected_lands_seen: number;
  /** Percent of the deck that is lands. */
  expected_land_rate: number;
  deck_size: number;
  deck_lands: number | null;
  is_flood: boolean;
  is_screw: boolean;
  is_land_streak: boolean;
}

export type Dock = 'left' | 'right' | 'float';

export type SessionRecord = 'off' | 'scoreboard' | 'split';

/** The flood meter at the foot of the panel: off, above today's record (the default), or below it (the very bottom). */
export type FloodMeterPlace = 'off' | 'above' | 'below';

export interface Hotkeys {
  toggle: string;
  visibility: string;
  /** Toggles the opponent panel (registered only while it is on). */
  opponent: string;
}

export interface Settings {
  /** Background slider, 0–1: only the charcoal ground (≈88 % at 1, gone at 0); text is always fully visible. */
  opacity: number;
  /** The same, for the minimized rail on its own (it is small enough to want its own setting). */
  railOpacity: number;
  /** Size of everything, percent (50–200). */
  scale: number;
  /** The panel's height cap in logical pixels (before Scale); the screen caps it too. */
  panelMaxHeight: number;
  dock: Dock;
  returnAfterSeconds: number;
  /** Owned by the shell (arrow, chevron, pin, hotkey); echoed here so a save round-trips it. */
  panelOpen: boolean;
  panelPinned: boolean;
  clickThroughWhenPinned: boolean;
  lands: 'grouped' | 'all';
  density: 'comfortable' | 'compact';
  /** Card names in their type colour, or plain white. */
  nameColor: 'type' | 'white';
  /** Today's record at the foot of the panel (named for the session record it replaced, as saved in overlay.json). */
  sessionRecord: SessionRecord;
  /** The flood meter (the Stream Kit Lands widget) at the foot of the panel. */
  floodMeter: FloodMeterPlace;
  /** The deck panel is drawn. Off (opponent only) its window stays empty and holds
      just the settings. Chosen in the tracker's Settings → Panels, never here. */
  deckPanel: boolean;
  /** The opponent panel window, on the side opposite the deck panel. Chosen in the
      tracker's Settings → Panels like `deckPanel`. */
  opponentPanel: boolean;
  /** Owned by the shell (the opponent panel's arrow, chevron, pin, hotkey). */
  opponentOpen: boolean;
  opponentPinned: boolean;
  followArena: boolean;
  hideWhenArenaNotInFront: boolean;
  apiUrl: string;
  hotkeysMacos: Hotkeys;
  hotkeysWindows: Hotkeys;
  positions: {
    leftY: number | null;
    rightY: number | null;
    floatX: number | null;
    floatY: number | null;
    opponentLeftY?: number | null;
    opponentRightY?: number | null;
  };
  monitor: string | null;
}

export interface LayoutInfo {
  layout: 'rail' | 'panel';
  /** Pinned stays out; unpinned unfolds on rail hover and folds back after the cursor leaves. */
  pinned: boolean;
  /** The player turned the panel on (arrow / hotkey) and has not closed it. */
  panelOpen: boolean;
  visible: boolean;
  dock: Dock;
}

export type SortKey = 'odds' | 'mana' | 'name';

/** Connection state the page derives from the poll loop. */
export type Link = 'connecting' | 'online' | 'offline';
