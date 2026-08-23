export interface DeckVisual {
  card_id: number | null;
  card_name: string | null;
  type_category: string;
  image_url: string | null;
  /** By-name Scryfall URL tried when image_url (arena-id) 404s — new sets
      often reach Scryfall before their Arena-ID mapping does. */
  image_fallback_url?: string | null;
  source: 'local_metadata' | 'deck_name';
}

export interface Summary {
  games: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number | null;
  /** Player name owning most of the tracked history (multi-account safe). */
  player_name?: string | null;
}

export interface DeckRow {
  deck_name: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  deck_visual: DeckVisual;
  /** WUBRG letters from the newest decklist's casting costs (e.g. "WR"). */
  colors?: string;
}

export interface FormatRow {
  format_label: string;
  /** Comma-joined raw queue identifiers, kept for debugging (not displayed). */
  raw_formats: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface PlayDrawRow {
  play_draw: string | null;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_mulligans?: number | null;
}

export interface DeckPlayDrawRow {
  deck_name: string;
  play_draw: string | null;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface DrawQualityRow {
  game_id: string;
  started_at: string;
  deck_name: string;
  outcome: string | null;
  cards_seen: number | null;
  lands_seen: number | null;
  land_seen_pct: number | null;
  opening_cards: number | null;
  known_draws: number | null;
}

export interface DrawnCardRow {
  display_name: string;
  type_category: string | null;
  times_drawn: number;
  games_seen: number;
  pct_of_games: number | null;
}

export interface CombatDeckRow {
  deck_name: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_damage_dealt: number | null;
  avg_damage_taken: number | null;
  avg_attack_steps: number | null;
  attackers_per_attack: number | null;
  attackers_lost: number;
  blockers_lost: number;
  trade_ratio: number | null;
  avg_life_gained: number | null;
  avg_player_turns: number | null;
  damage_per_turn?: number | null;
  aggression_profile: 'Aggro' | 'Midrange' | 'Control' | null;
}

export interface CombatSplitRow {
  split: string;
  games: number;
  avg_damage_dealt: number | null;
  avg_damage_taken: number | null;
  avg_attack_steps: number | null;
  avg_life_gained: number | null;
  avg_cards_drawn: number | null;
  avg_cards_denied: number | null;
}

export interface ScheduleRow {
  label: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  weekday?: number;
  bucket?: number;
}

export interface FatigueRow {
  bucket: number;
  label: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface MatchLevelSummary {
  /** Decided matches: a Bo3 counts once (2-1 = one win); Bo1 game = one match. */
  matches: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  longest_win: number;
  longest_loss: number;
}

export interface StreakSummary {
  games: number;
  current: { kind: string; length: number } | null;
  longest_win: number;
  longest_loss: number;
}

export interface OutcomeReasonRow {
  reason: string;
  wins: number;
  losses: number;
  games: number;
}

export interface OpenerLandRow {
  lands: number;
  label: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_mulligans?: number | null;
}

export interface OpponentColorRow {
  color_label: string;
  colors: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  pct_of_games?: number | null;
}

export interface BrawlQueueRow {
  format_label: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface BrawlSummary {
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  queues: BrawlQueueRow[];
}

export interface CommanderRow {
  commander: string;
  colors: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface OpponentThreatRow {
  display_name: string;
  type_category: string;
  games: number;
  plays: number;
  wins: number;
  losses: number;
  loss_rate: number | null;
}

export interface MatchupRow {
  deck_name: string;
  opponent_archetype: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface ManaReadinessRow {
  threshold: number;
  label: string;
  games: number;
  on_time_games: number;
  on_time_pct: number;
  on_time_win_rate: number | null;
  behind_games: number;
  behind_win_rate: number | null;
}

export interface MomentumRow {
  split: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_mulligans: number | null;
  on_play_pct: number | null;
}

export interface RecentGameRow {
  game_id: string;
  match_id?: string | null;
  game_number?: number | null;
  started_at: string;
  deck_name: string;
  format_label: string;
  best_of?: number | null;
  match_wins?: number | null;
  match_losses?: number | null;
  outcome: string | null;
  mulligans: number | null;
  duration_seconds: number | null;
  total_turns: number | null;
  flood_reasons: string[];
  is_flood: boolean;
  screw_reasons?: string[];
  is_screw?: boolean;
  /** Opponent's revealed WUBRG colors (e.g. "UR"); empty when nothing colored was seen. */
  opp_colors?: string;
  /** Your deck's WUBRG colors (same derivation as the Decks table). */
  deck_colors?: string;
  /** Brawl: commander names (partners joined with " & "); null outside Brawl. */
  player_commander?: string | null;
  opponent_commander?: string | null;
  player_commander_colors?: string | null;
  opponent_commander_colors?: string | null;
}

export interface AllGamesRow extends RecentGameRow {
  duration_seconds: number | null;
  total_turns: number | null;
  mulligans: number | null;
  cards_seen: number | null;
  lands_seen: number | null;
  land_seen_pct: number | null;
}

export interface AllGamesResponse {
  games: AllGamesRow[];
  total: number;
}

export interface MatchRow {
  match_id: string;
  started_at: string | null;
  raw_format: string | null;
  format_label: string;
  best_of: number | null;
  deck_name: string;
  games: number;
  wins: number;
  losses: number;
  record: string;
  outcome: string | null;
}

export interface SessionRow {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  games: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number | null;
}

export interface TrendRow {
  game_id: string;
  started_at: string;
  outcome: string;
}

export interface RankProgressRow {
  id: number;
  captured_at: string;
  season_ordinal: number;
  rank_class: string;
  rank_level: number;
  rank_step: number;
  rank_steps: number;
  raw_step?: number | null;
  rank_score: number;
  rank_label: string;
  matches_won: number | null;
  matches_lost: number | null;
  mythic_percentile: number | null;
  mythic_rank: number | null;
  game_id: string | null;
  outcome: string | null;
  best_of: number | null;
  deck_name: string | null;
}

export interface FormatOption {
  raw_format: string;
  format_label: string;
}

export interface FilterOptions {
  decks: string[];
  formats: FormatOption[];
  rank_seasons?: number[];
}

export interface SnapshotFilters {
  deck?: string;
  format?: string;
  days?: number;
  season?: number;
  /** ISO date (YYYY-MM-DD) lower bound, inclusive. */
  since?: string;
  /** ISO date (YYYY-MM-DD) upper bound, inclusive. */
  until?: string;
  /** Opponent WUBRG color-combo filter (client-side, All Games page only). */
  colors?: string;
  /** Format quick-filter chip id (client-side, All Games page only). */
  quick?: string;
}

export interface DashboardSnapshot {
  summary: Summary;
  decks: DeckRow[];
  formats: FormatRow[];
  midweek_formats: FormatRow[];
  play_draw: PlayDrawRow[];
  deck_play_draw: DeckPlayDrawRow[];
  draw_quality: DrawQualityRow[];
  drawn_cards: DrawnCardRow[];
  momentum: MomentumRow[];
  combat_decks: CombatDeckRow[];
  combat_split: CombatSplitRow[];
  mana_readiness: ManaReadinessRow[];
  /** Overall flood/screw/normal split for the homepage Land Statistics. */
  land_profile?: DeckLandProfile | null;
  schedule: { by_weekday: ScheduleRow[]; by_time_of_day: ScheduleRow[] };
  fatigue: FatigueRow[];
  streaks: StreakSummary;
  match_summary?: MatchLevelSummary;
  ranked_summary?: MatchLevelSummary;
  ranked_season_summary?: (MatchLevelSummary & { season_ordinal: number }) | null;
  outcome_reasons: OutcomeReasonRow[];
  opener_lands: OpenerLandRow[];
  opponent_threats: OpponentThreatRow[];
  opponent_colors?: OpponentColorRow[];
  brawl?: BrawlSummary;
  your_commanders?: CommanderRow[];
  faced_commanders?: CommanderRow[];
  matchups: MatchupRow[];
  recent: RecentGameRow[];
  matches: MatchRow[];
  sessions: SessionRow[];
  trend: TrendRow[];
  rank_progress?: RankProgressRow[];
  filter_options: FilterOptions;
}

export interface DeckProfile {
  avg_duration_seconds: number | null;
  avg_turns: number | null;
  avg_mulligans: number | null;
  on_play_pct: number | null;
}

export interface CardPerformanceRow {
  display_name: string;
  type_category: string;
  games_seen: number;
  times_played: number;
  times_drawn: number;
  wins_when_seen: number;
  losses_when_seen: number;
  win_rate_when_seen: number | null;
}

export interface OpeningHandRow {
  display_name: string;
  type_category: string;
  games_in_opener: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface MulliganRow {
  mulligans: number;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface DeckGameRow {
  game_id: string;
  started_at: string;
  outcome: string | null;
  is_flood?: boolean;
  is_screw?: boolean;
  duration_seconds: number | null;
  total_turns: number | null;
  player_avg_turn_seconds: number | null;
  opponent_avg_turn_seconds: number | null;
  raw_format: string | null;
  format_label: string;
  mulligans: number | null;
  play_draw: string | null;
  opp_colors?: string;
}

export interface DeckPlayedManaCard {
  display_name: string;
  type_category: string;
  times_played: number;
}

export interface DeckPlayedManaSeat {
  /** Total turns this seat took across the deck's games; null if untracked. */
  turns: number | null;
  cards: DeckPlayedManaCard[];
}

/** Raw inputs for client-side mana-value stats (costs come from card_mana / Scryfall). */
export interface DeckPlayedMana {
  player?: DeckPlayedManaSeat;
  opponent?: DeckPlayedManaSeat;
}

/** Arena-card-DB mana costs keyed by display name (Scryfall notation). */
export type CardManaMap = Record<string, { mana_cost: string; mana_value: number }>;

export interface DeckExportCard {
  display_name: string;
  quantity: number;
  type_category: string;
}

export interface DeckExport {
  available: boolean;
  source_game_id: string | null;
  main_deck: DeckExportCard[];
  sideboard: DeckExportCard[];
  text: string | null;
}

export interface DeckCompositionRow {
  display_name: string;
  type_category: string;
  copies: number;
  games_in_deck: number;
  games_seen: number;
  games_seen_multiple: number;
  times_seen: number;
  seen_pct: number | null;
  multiple_pct: number | null;
  expected_seen: number;
  seen_delta: number;
  wins_when_seen: number;
  losses_when_seen: number;
  win_rate_when_seen: number | null;
  wins_when_not_seen: number;
  losses_when_not_seen: number;
  win_rate_when_not_seen: number | null;
}

export interface DeckVersionRow {
  version: number;
  first_played: string | null;
  last_played: string | null;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  added: string[];
  removed: string[];
}

export interface DeckSideboardRecord {
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface SideboardSwapRow {
  display_name: string;
  boarded_in: number;
  boarded_out: number;
  games_in: number;
  wins_in: number;
  losses_in: number;
  win_rate_in: number | null;
  vs_in: string;
  vs_out: string;
}

export interface DeckSideboardSummary {
  matches: number;
  game_one: DeckSideboardRecord;
  post_board: DeckSideboardRecord;
  boarded_in: { display_name: string; copies: number }[];
  swaps?: SideboardSwapRow[];
}

export interface DeckAccountRow {
  name: string;
  games: number;
}

export interface DeckLandProfile {
  deck_size: number | null;
  lands: number | null;
  flood_games: number;
  screw_games: number;
  normal_games: number;
  classified_games: number;
  /** Deck-level draw-quality averages across the classified games. */
  avg_cards_seen?: number | null;
  lands_seen_pct?: number | null;
  avg_cards_drawn?: number | null;
  lands_drawn_pct?: number | null;
  expected_land_pct?: number | null;
}

/** One seat's average turn-time telemetry across a deck's games. */
export interface DeckTurnTimingSide {
  avg_total_seconds: number | null;
  avg_turn_seconds: number | null;
  turns_timed: number;
  games: number;
}

/** One seat's per-game averages; null = never tracked. */
export interface DeckInteractionSide {
  attack_steps: number | null;
  attacking_creatures: number | null;
  attackers_lost: number | null;
  blocking_creatures: number | null;
  blockers_lost: number | null;
  damage_dealt: number | null;
  damage_taken: number | null;
  life_lost: number | null;
  self_damage: number | null;
  life_gained: number | null;
  poison_added: number | null;
  cards_played: number | null;
  cards_drawn: number | null;
  cards_discarded: number | null;
  cards_milled: number | null;
  cards_exiled: number | null;
  removal_played: number | null;
  removal_drawn: number | null;
  wipes_played: number | null;
  wipes_drawn: number | null;
  bounces_played: number | null;
  bounces_drawn: number | null;
  counters_played: number | null;
  counters_drawn: number | null;
  counters_landed: number | null;
  counters_failed: number | null;
  creatures_removed: number | null;
  noncreatures_removed: number | null;
  creatures_bounced: number | null;
  noncreatures_bounced: number | null;
  lands_lost: number | null;
  lands_replaced: number | null;
  lands_unreplaced: number | null;
  land_replacement_pct: number | null;
  tokens_created: number | null;
  tokens_destroyed: number | null;
  tokens_sacrificed: number | null;
  tokens_exiled: number | null;
}

/** Per-game interaction averages for both seats, mirroring the game page. */
export interface DeckInteractionProfile {
  games_tracked: number;
  player: DeckInteractionSide;
  opponent: DeckInteractionSide;
}

/** Match-level records by queue. Only splits with matches are present. */
export interface DeckModeSplits {
  standard?: {
    ranked: MatchLevelSummary | null;
    unranked: MatchLevelSummary | null;
    bo1: MatchLevelSummary | null;
    bo3: MatchLevelSummary | null;
  };
  brawl?: {
    competitive: MatchLevelSummary | null;
    casual: MatchLevelSummary | null;
  };
}

export interface DeckDetail {
  deck_name: string;
  deck_visual: DeckVisual;
  /** WUBRG letters from the newest decklist's casting costs (e.g. "B"). */
  deck_colors?: string;
  deck_export: DeckExport;
  summary: Summary;
  profile: DeckProfile;
  combat_profile: CombatDeckRow | null;
  interaction_profile?: DeckInteractionProfile | null;
  played_mana?: DeckPlayedMana | null;
  card_mana?: CardManaMap;
  turn_timing?: {
    player?: DeckTurnTimingSide;
    opponent?: DeckTurnTimingSide;
  } | null;
  mode_splits?: DeckModeSplits | null;
  streaks?: StreakSummary | null;
  composition: DeckCompositionRow[];
  versions: DeckVersionRow[];
  opponent_colors?: OpponentColorRow[];
  sideboard: DeckSideboardSummary | null;
  accounts?: DeckAccountRow[];
  land_profile?: DeckLandProfile | null;
  mana_readiness: ManaReadinessRow[];
  formats: FormatRow[];
  midweek_formats: FormatRow[];
  card_performance: CardPerformanceRow[];
  opening_hands: OpeningHandRow[];
  mulligans: MulliganRow[];
  recent: DeckGameRow[];
  trend: TrendRow[];
}

export interface GameHeader {
  game_id: string;
  match_id: string;
  game_number: number | null;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  total_turns: number | null;
  player_turns: number | null;
  opponent_turns: number | null;
  outcome: string | null;
  outcome_reason: string | null;
  raw_format: string | null;
  format_label: string;
  best_of: number | null;
}

export interface GameParticipant {
  id?: string;
  role: string;
  seat_id?: number | null;
  display_name?: string | null;
  deck_name?: string | null;
  deck_archetype?: string | null;
  went_first?: number | null;
  mulligans?: number | null;
  opening_hand_size?: number | null;
  starting_life?: number | null;
  ending_life?: number | null;
  colors?: string | null;
  color_label?: string | null;
}

export interface GameCardRow {
  display_name: string;
  type_category: string;
}

export interface GameOpeningHandRow extends GameCardRow {
  hand_position: number;
  copy_number: number;
}

export interface MulliganHandCard extends GameCardRow {
  hand_position: number;
  bottomed: boolean;
}

export interface MulliganHand {
  hand_number: number;
  cards: MulliganHandCard[];
}

export interface GameDrawnCardRow extends GameCardRow {
  turn_number: number | null;
  draw_position: number;
  copy_number: number;
}

export interface GamePlayedCardRow extends GameCardRow {
  played_count: number;
  /** Turn of every cast/play from the timeline (recasts repeat); absent on old games. */
  turns_played?: number[];
}

export interface OpponentVisibleCardRow extends GamePlayedCardRow {
  drawn_count: number;
  discarded_count: number;
  milled_count: number;
  exiled_count: number;
  /** First turn this card surfaced (cast, land, zone change, revealed draw). */
  first_seen_turn?: number | null;
}

export type TimelineTextSegment =
  | { kind: 'text'; text: string }
  | { kind: 'card'; text: string; card_name: string; card_type?: string | null };

export interface GameTimelineRow {
  turn_number: number | null;
  phase: string | null;
  step: string | null;
  event_type: string | null;
  actor_role: string | null;
  text: string;
  text_segments: TimelineTextSegment[];
  player_life: number | null;
  opponent_life: number | null;
}

export interface LifePoint {
  turn_number: number | null;
  player_life: number;
  opponent_life: number;
}

export interface GameDrawQuality {
  total_draws: number;
  identified_draws: number;
  land_draws: number;
  land_draw_pct: number | null;
  total_cards_seen?: number;
  opening_lands?: number;
  lands_seen?: number;
  land_seen_pct?: number | null;
  expected_land_rate?: number;
  expected_lands_seen?: number;
  flood_probability_pct?: number | null;
  screw_probability_pct?: number | null;
  longest_land_streak?: number;
  max_lands_in_eight?: number | null;
  longest_low_land_drought?: number;
  low_land_drought_lands?: number | null;
  flood_reasons?: string[];
  is_flood: boolean;
  screw_reasons?: string[];
  is_screw?: boolean;
}

export interface TurnTimingSummary {
  total_seconds: number | null;
  turns_timed: number;
  avg_seconds: number | null;
}

export interface GameTurnTimingRow {
  turn_number: number;
  seat_id: number | null;
  role: 'player' | 'opponent' | 'unknown';
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  timing_source: 'live' | 'estimated_header_events' | string;
}

export interface GameParticipantStatsRow {
  role: string;
  attack_steps: number;
  attacking_creatures: number;
  attackers_lost: number;
  blocking_creatures: number;
  blockers_lost: number;
  damage_dealt: number;
  damage_taken: number;
  life_lost: number;
  self_damage: number;
  life_gained: number;
  cards_played: number;
  cards_drawn: number;
  cards_discarded: number;
  cards_milled: number;
  cards_exiled: number;
  /* Removal/token tracking — null on games recorded before the feature. */
  removal_drawn?: number | null;
  removal_played?: number | null;
  wipes_drawn?: number | null;
  wipes_played?: number | null;
  bounces_drawn?: number | null;
  bounces_played?: number | null;
  creatures_removed?: number | null;
  noncreatures_removed?: number | null;
  creatures_bounced?: number | null;
  noncreatures_bounced?: number | null;
  poison_added?: number | null;
  counters_drawn?: number | null;
  counters_played?: number | null;
  spells_countered?: number | null;
  lands_lost?: number | null;
  lands_replaced?: number | null;
  tokens_created?: number | null;
  tokens_destroyed?: number | null;
  tokens_sacrificed?: number | null;
  tokens_exiled?: number | null;
}

export interface GameAnnotation {
  game_id: string;
  note: string;
  tags: string[];
  updated_at?: string | null;
}

export interface AuditFindingRow {
  code: string;
  severity: string;
  table_name: string;
  row_id: string;
  message: string;
  current_value: string | null;
  suggested_value: string | null;
  repairable: boolean;
}

export interface AuditReport {
  findings: AuditFindingRow[];
  total: number;
  by_code: { code: string; count: number }[];
}

export interface MatchGameRow {
  game_id: string;
  game_number: number | null;
  outcome: string | null;
  started_at: string | null;
  duration_seconds: number | null;
  total_turns: number | null;
}

export interface DeckChangeCard {
  display_name: string;
  type_category: string;
  /** Copies in this game's maindeck (0 for fully sideboarded-out cards). */
  quantity: number;
  /** Copies gained/lost vs the deck that started the match. */
  delta: number;
}

export interface DeckChanges {
  base_game_number: number;
  deck_total: number;
  base_deck_total: number;
  lands: number;
  base_lands: number;
  cards: DeckChangeCard[];
  removed: DeckChangeCard[];
}

export interface GameDetail {
  game: GameHeader;
  /** Every game of this Bo3 match in order; empty for Bo1 games. */
  match_games?: MatchGameRow[];
  multi_account?: boolean;
  /** Bo3 games 2+: the deck taken into this game vs the match's original deck. */
  deck_changes?: DeckChanges | null;
  /** Bo3 games 2+: maindeck changes vs the previous game of the match. */
  sideboard_changes?: { added: string[]; removed: string[] } | null;
  player: GameParticipant;
  opponent: GameParticipant;
  annotation?: GameAnnotation;
  participant_stats: GameParticipantStatsRow[];
  opening_hand: GameOpeningHandRow[];
  mulligan_hands?: MulliganHand[];
  drawn: GameDrawnCardRow[];
  draw_quality: GameDrawQuality;
  turn_timing: {
    player: TurnTimingSummary;
    opponent: TurnTimingSummary;
  };
  turns: GameTurnTimingRow[];
  cards_played: GamePlayedCardRow[];
  opponent_cards: OpponentVisibleCardRow[];
  card_mana?: CardManaMap;
  timeline: GameTimelineRow[];
  life_curve: LifePoint[];
}

export interface OpponentGameRow {
  game_id: string;
  started_at: string;
  outcome: string | null;
  duration_seconds: number | null;
  total_turns: number | null;
  player_turns: number | null;
  opponent_turns: number | null;
  raw_format: string | null;
  format_label: string;
  best_of: number | null;
  deck_name: string;
  play_draw: string;
  player_final_life: number | null;
  opponent_final_life: number | null;
}

export interface OpponentDetail {
  opponent_name: string;
  summary: Summary;
  games: OpponentGameRow[];
}

export interface CardSummary {
  games_seen: number;
  total_played: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface CardByDeckRow {
  deck_name: string;
  games_seen: number;
  total_played: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface CardAllUsage {
  games_seen: number;
  total_played: number;
  player_games_seen: number;
  player_played: number;
  opponent_games_seen: number;
  opponent_played: number;
}

export interface CardByRoleRow {
  role: 'player' | 'opponent';
  side_label: string;
  games_seen: number;
  total_played: number;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface CardOpenerImpact {
  games_in_opener: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  times_drawn: number;
}

export interface CardOpponentImpact {
  games: number;
  plays: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  loss_rate: number | null;
}

export interface CardMultiplicityBucket {
  copies_seen: number;
  label: string;
  games: number;
  pct_of_games: number;
  pct_at_least: number;
  expected_pct_at_least: number | null;
  wins: number;
  losses: number;
  win_rate: number | null;
}

export interface CardMultiplicity {
  games: number;
  buckets: CardMultiplicityBucket[];
}

export interface CardOpponentPlayable {
  /** WUBRG letters the card's cost strictly requires ("" = none). */
  required_colors: string;
  games_possible: number;
  games_played: number;
  pct: number | null;
}

export interface CardDetail {
  card_name: string;
  image_url: string | null;
  /** Games where the opponent's revealed colors could cast this card. */
  opponent_playable?: CardOpponentPlayable | null;
  summary: CardSummary;
  all_usage: CardAllUsage;
  by_role: CardByRoleRow[];
  opponent_impact?: CardOpponentImpact;
  by_deck: CardByDeckRow[];
  multiplicity?: CardMultiplicity;
  opponent_multiplicity?: CardMultiplicity;
  opener_impact: CardOpenerImpact;
}

export interface GlobalSearchResult {
  cards: CardSearchResult[];
  decks: { deck_name: string; games: number }[];
  opponents: { display_name: string; games: number }[];
}

export interface CardSearchResult {
  card_name: string;
  type_category: string;
  games_seen: number;
  deck_count: number;
  total_played: number;
  last_seen_at: string | null;
}

export async function fetchDeckDetail(
  deckName: string,
  filters: SnapshotFilters = {},
  signal?: AbortSignal,
): Promise<DeckDetail> {
  const params = new URLSearchParams({ name: deckName });
  if (filters.format) {
    params.set('format', filters.format);
  }
  if (filters.days) {
    params.set('days', String(filters.days));
  }
  if (filters.since) {
    params.set('since', filters.since);
  }
  if (filters.until) {
    params.set('until', filters.until);
  }
  const response = await fetch(`/api/deck?${params.toString()}`, { signal });
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`No recorded games for deck: ${deckName}`);
    }
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<DeckDetail>;
}

export async function fetchGameDetail(gameId: string, signal?: AbortSignal): Promise<GameDetail> {
  const params = new URLSearchParams({ id: gameId });
  const response = await fetch(`/api/game?${params.toString()}`, { signal });
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`No recorded game for id: ${gameId}`);
    }
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<GameDetail>;
}

function appendDetailFilters(params: URLSearchParams, filters: SnapshotFilters): void {
  if (filters.deck) {
    params.set('deck', filters.deck);
  }
  if (filters.format) {
    params.set('format', filters.format);
  }
  if (filters.days) {
    params.set('days', String(filters.days));
  }
  if (filters.since) {
    params.set('since', filters.since);
  }
  if (filters.until) {
    params.set('until', filters.until);
  }
}

export async function fetchOpponentDetail(
  opponentName: string,
  filters: SnapshotFilters = {},
  signal?: AbortSignal,
): Promise<OpponentDetail> {
  const params = new URLSearchParams({ name: opponentName });
  appendDetailFilters(params, filters);
  const response = await fetch(`/api/opponent?${params.toString()}`, { signal });
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`No recorded games against opponent: ${opponentName}`);
    }
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<OpponentDetail>;
}

export async function fetchCardDetail(
  cardName: string,
  filters: SnapshotFilters = {},
  signal?: AbortSignal,
): Promise<CardDetail> {
  const params = new URLSearchParams({ name: cardName });
  appendDetailFilters(params, filters);
  const response = await fetch(`/api/card?${params.toString()}`, { signal });
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`No recorded games for card: ${cardName}`);
    }
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<CardDetail>;
}

export async function fetchCardSearch(
  query: string,
  signal?: AbortSignal,
  limit = 8,
): Promise<CardSearchResult[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`/api/cards?${params.toString()}`, { signal });
  if (!response.ok) {
    throw new Error(`Card search API returned ${response.status}`);
  }
  return response.json() as Promise<CardSearchResult[]>;
}

export async function fetchGlobalSearch(
  query: string,
  limit = 6,
  signal?: AbortSignal,
): Promise<GlobalSearchResult> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`/api/search?${params.toString()}`, { signal });
  if (!response.ok) {
    throw new Error(`Search API returned ${response.status}`);
  }
  return response.json() as Promise<GlobalSearchResult>;
}

export async function fetchAllGames(
  filters: SnapshotFilters = {},
  signal?: AbortSignal,
): Promise<AllGamesResponse> {
  const response = await fetch(`/api/games${snapshotQueryString(filters)}`, { signal });
  if (!response.ok) {
    throw new Error(`Games API returned ${response.status}`);
  }
  return response.json() as Promise<AllGamesResponse>;
}

export async function saveGameAnnotation(
  gameId: string,
  note: string,
  tags: string[],
  signal?: AbortSignal,
): Promise<GameAnnotation> {
  const response = await fetch('/api/game/annotation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ game_id: gameId, note, tags }),
    signal,
  });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.text()).trim();
    } catch {
      // Body unavailable; fall back to the status code alone.
    }
    throw new Error(
      detail ? `HTTP ${response.status} — ${detail}` : `Annotation save failed (HTTP ${response.status})`,
    );
  }
  return response.json() as Promise<GameAnnotation>;
}

export async function resetDatabase(confirm: string): Promise<{ ok: boolean; backup: string }> {
  const response = await fetch('/api/db/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm }),
  });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.text()).trim();
    } catch {
      // Body unavailable; fall back to the status code alone.
    }
    throw new Error(detail ? `HTTP ${response.status} — ${detail}` : `Reset failed (HTTP ${response.status})`);
  }
  return response.json() as Promise<{ ok: boolean; backup: string }>;
}

export async function fetchAuditReport(signal?: AbortSignal): Promise<AuditReport> {
  const response = await fetch('/api/audit', { signal });
  if (!response.ok) {
    throw new Error(`Audit API returned ${response.status}`);
  }
  return response.json() as Promise<AuditReport>;
}

export function snapshotQueryString(filters: SnapshotFilters): string {
  const params = new URLSearchParams();
  if (filters.deck) {
    params.set('deck', filters.deck);
  }
  if (filters.format) {
    params.set('format', filters.format);
  }
  if (filters.days) {
    params.set('days', String(filters.days));
  }
  if (filters.season) {
    params.set('season', String(filters.season));
  }
  if (filters.since) {
    params.set('since', filters.since);
  }
  if (filters.until) {
    params.set('until', filters.until);
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

export async function fetchDashboardSnapshot(
  filters: SnapshotFilters = {},
  signal?: AbortSignal,
): Promise<DashboardSnapshot> {
  const response = await fetch(`/api/snapshot${snapshotQueryString(filters)}`, { signal });
  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<DashboardSnapshot>;
}

// ---------------------------------------------------------------------------
// Deck Finder (in-app): thin client over /api/deckfinder/*.

export interface DeckFinderProvider {
  key: string;
  display_name: string;
  description: string;
  homepage: string;
  /** Formats worth offering for this site ('any' only means no choice). */
  format_options: string[];
  uses_source_picker: boolean;
  allow_all_sources: boolean;
  source_picker_title: string;
  source_picker_all_label: string;
  /** Configured creators shown next to the format choice (Aetherhub). */
  creators: DeckFinderProviderCreator[];
}

export interface DeckFinderProviderCreator {
  label: string;
  name: string;
  url: string;
  description: string;
}

export interface DeckFinderSource {
  name: string;
  url: string;
  description: string;
  formats: string[];
}

export interface DeckFinderDeck {
  name: string;
  source_site: string;
  source_url: string;
  format_label: string;
  matches: number | null;
  win_rate: number | null;
  player_name: string | null;
  placing: string | null;
  event_name: string | null;
  event_date: string | null;
  deck_text: string | null;
  notes: string | null;
  /** Display strings per table column, computed server-side to match the
      terminal Deck Finder's per-site tables. */
  cells?: Record<string, string>;
}

export interface DeckFinderColumn {
  key: string;
  label: string;
  numeric?: boolean;
}

export interface DeckFinderView {
  title: string;
  count_label: string;
  name_column_label: string;
  selection_label: string;
  selection_action: string;
  helper_text: string | null;
  show_notes: boolean | null;
  columns: DeckFinderColumn[];
}

export interface DeckFinderResults {
  decks: DeckFinderDeck[];
  view: DeckFinderView;
}

export interface DeckFinderJobStatus {
  status: 'running' | 'done' | 'error' | 'unknown';
  note?: string;
  error?: string;
  decks?: DeckFinderDeck[];
  view?: DeckFinderView;
  provider?: string;
  deck?: DeckFinderDeck;
}

async function deckFinderJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Deck Finder API returned ${response.status}`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) {
        message = body.error;
      }
    } catch {
      // keep the status message
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function fetchDeckFinderProviders(signal?: AbortSignal): Promise<DeckFinderProvider[]> {
  const response = await fetch('/api/deckfinder/providers', { signal });
  const body = await deckFinderJson<{ providers: DeckFinderProvider[] }>(response);
  return body.providers;
}

export async function fetchDeckFinderSources(
  provider: string,
  format: string,
  signal?: AbortSignal,
): Promise<DeckFinderSource[]> {
  const response = await fetch(
    `/api/deckfinder/sources?provider=${encodeURIComponent(provider)}&format=${encodeURIComponent(format)}`,
    { signal },
  );
  const body = await deckFinderJson<{ sources: DeckFinderSource[] }>(response);
  return body.sources;
}

export async function startDeckFinderFetch(payload: {
  provider: string;
  format: string;
  source_url?: string;
  source_name?: string;
  limit?: number;
  refresh?: boolean;
}): Promise<{ job?: string; done?: boolean; decks?: DeckFinderDeck[]; view?: DeckFinderView }> {
  const response = await fetch('/api/deckfinder/fetch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return deckFinderJson(response);
}

export async function fetchDeckFinderJob(jobId: string, signal?: AbortSignal): Promise<DeckFinderJobStatus> {
  const response = await fetch(`/api/deckfinder/job?id=${encodeURIComponent(jobId)}`, { signal });
  return deckFinderJson(response);
}

export async function hydrateDeckFinderDeck(
  provider: string,
  deck: DeckFinderDeck,
): Promise<DeckFinderDeck> {
  const response = await fetch('/api/deckfinder/hydrate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, deck }),
  });
  const body = await deckFinderJson<{ deck: DeckFinderDeck }>(response);
  return body.deck;
}

export async function startDeckFinderVariants(payload: {
  provider: string;
  format: string;
  deck: DeckFinderDeck;
  source_name?: string;
}): Promise<{ job: string }> {
  const response = await fetch('/api/deckfinder/variants', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return deckFinderJson(response);
}

export async function startDeckFinderSurprise(format: string): Promise<{ job: string }> {
  const response = await fetch('/api/deckfinder/surprise', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format }),
  });
  return deckFinderJson(response);
}

// ---------------------------------------------------------------------------
// Live Log page: thin client over /api/live.

export interface LiveTrackerInfo {
  state: 'live' | 'idle' | 'offline';
  updated_at: string | null;
  session_id: string | null;
}

export interface LiveNow {
  in_game: boolean;
  match_id: string | null;
  game_id: string | null;
  format: string | null;
  match_type: string | null;
  game_number: number | null;
  player_name: string | null;
  opponent_name: string | null;
  deck_name: string | null;
  turn_number: number | null;
  active_role: 'player' | 'opponent' | null;
  on_play: boolean | null;
  player_life: number | null;
  opponent_life: number | null;
  mulligans: number | null;
  game_started_at: string | null;
  player_commanders: string[];
  opponent_commanders: string[];
}

export interface LiveSessionInfo {
  id: string;
  started_at: string;
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  runtime_seconds: number | null;
  win_rate: number | null;
}

export interface LiveGameRow {
  id: string;
  started_at: string | null;
  outcome: string | null;
  total_turns: number | null;
  duration_seconds: number | null;
  game_number: number | null;
  format: string | null;
  best_of: number | null;
  deck_name: string | null;
  opponent_name: string | null;
}

/** One live feed row — a GameTimelineRow (same shape the /game Timeline
    renders) plus its game_events id for delta polling. */
export interface LiveEventRow extends GameTimelineRow {
  id: number;
  at: string;
}

export interface LivePayload {
  tracker: LiveTrackerInfo;
  now: LiveNow | null;
  session: LiveSessionInfo | null;
  games: LiveGameRow[];
  events: LiveEventRow[];
  seq: number;
}

export async function fetchLiveStatus(since: number, signal?: AbortSignal): Promise<LivePayload> {
  const response = await fetch(`/api/live?since=${since}`, { signal });
  return deckFinderJson(response);
}

// ---------------------------------------------------------------------------
// Settings page: thin client over /api/settings.

export interface DeckAiProviderSettings {
  key: string;
  label: string;
  api_key: string;
  model: string;
  default_model: string;
}

export interface DeckAiSettings {
  enabled: boolean;
  provider: string;
  providers: DeckAiProviderSettings[];
}

export interface DeckFinderCreator {
  name: string;
  short_name: string | null;
}

export interface DeckFinderCreatorSettings {
  path: string;
  moxfield: DeckFinderCreator[];
  aetherhub: DeckFinderCreator[];
  tcgplayer: DeckFinderCreator[];
}

export interface TrackerInfoSettings {
  monitoring: string | null;
  card_db: string | null;
  log_db: string | null;
  deck_ai: string;
  version: string;
}

export interface TrackerSettings {
  tracker: TrackerInfoSettings;
  deck_ai: DeckAiSettings;
  deck_finder: DeckFinderCreatorSettings;
}

export async function fetchTrackerSettings(signal?: AbortSignal): Promise<TrackerSettings> {
  const response = await fetch('/api/settings', { signal });
  return deckFinderJson(response);
}

export async function saveDeckAiSettings(payload: {
  enabled: boolean;
  provider: string;
  keys: Record<string, string>;
  models: Record<string, string>;
}): Promise<DeckAiSettings> {
  const response = await fetch('/api/settings/deck-ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await deckFinderJson<{ deck_ai: DeckAiSettings }>(response);
  return body.deck_ai;
}

export async function saveDeckFinderCreators(payload: {
  moxfield: DeckFinderCreator[];
  aetherhub: DeckFinderCreator[];
  tcgplayer: DeckFinderCreator[];
}): Promise<DeckFinderCreatorSettings> {
  const response = await fetch('/api/settings/deck-finder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await deckFinderJson<{ deck_finder: DeckFinderCreatorSettings }>(response);
  return body.deck_finder;
}
