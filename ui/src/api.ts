export interface DeckVisual {
  card_id: number | null;
  card_name: string | null;
  type_category: string;
  image_url: string | null;
  source: 'local_metadata' | 'deck_name';
}

export interface Summary {
  games: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number | null;
}

export interface DeckRow {
  deck_name: string;
  games: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  deck_visual: DeckVisual;
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
  started_at: string;
  deck_name: string;
  format_label: string;
  outcome: string | null;
  mulligans: number | null;
  duration_seconds: number | null;
  total_turns: number | null;
  flood_reasons: string[];
  is_flood: boolean;
  screw_reasons?: string[];
  is_screw?: boolean;
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
  schedule: { by_weekday: ScheduleRow[]; by_time_of_day: ScheduleRow[] };
  fatigue: FatigueRow[];
  streaks: StreakSummary;
  outcome_reasons: OutcomeReasonRow[];
  opener_lands: OpenerLandRow[];
  opponent_threats: OpponentThreatRow[];
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
  duration_seconds: number | null;
  total_turns: number | null;
  player_avg_turn_seconds: number | null;
  opponent_avg_turn_seconds: number | null;
  raw_format: string | null;
  format_label: string;
  mulligans: number | null;
  play_draw: string | null;
}

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
  times_seen: number;
  seen_pct: number | null;
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

export interface DeckSideboardSummary {
  matches: number;
  game_one: DeckSideboardRecord;
  post_board: DeckSideboardRecord;
  boarded_in: { display_name: string; copies: number }[];
}

export interface DeckDetail {
  deck_name: string;
  deck_visual: DeckVisual;
  deck_export: DeckExport;
  summary: Summary;
  profile: DeckProfile;
  combat_profile: CombatDeckRow | null;
  composition: DeckCompositionRow[];
  versions: DeckVersionRow[];
  sideboard: DeckSideboardSummary | null;
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
  went_first?: number | null;
  mulligans?: number | null;
  opening_hand_size?: number | null;
  starting_life?: number | null;
  ending_life?: number | null;
}

export interface GameCardRow {
  display_name: string;
  type_category: string;
}

export interface GameOpeningHandRow extends GameCardRow {
  hand_position: number;
  copy_number: number;
}

export interface GameDrawnCardRow extends GameCardRow {
  turn_number: number | null;
  draw_position: number;
  copy_number: number;
}

export interface GamePlayedCardRow extends GameCardRow {
  played_count: number;
}

export interface OpponentVisibleCardRow extends GamePlayedCardRow {
  drawn_count: number;
  discarded_count: number;
  milled_count: number;
  exiled_count: number;
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
}

export interface GameDetail {
  game: GameHeader;
  player: GameParticipant;
  opponent: GameParticipant;
  participant_stats: GameParticipantStatsRow[];
  opening_hand: GameOpeningHandRow[];
  drawn: GameDrawnCardRow[];
  draw_quality: GameDrawQuality;
  turn_timing: {
    player: TurnTimingSummary;
    opponent: TurnTimingSummary;
  };
  turns: GameTurnTimingRow[];
  cards_played: GamePlayedCardRow[];
  opponent_cards: OpponentVisibleCardRow[];
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

export interface CardDetail {
  card_name: string;
  image_url: string | null;
  summary: CardSummary;
  all_usage: CardAllUsage;
  by_role: CardByRoleRow[];
  opponent_impact?: CardOpponentImpact;
  by_deck: CardByDeckRow[];
  multiplicity?: CardMultiplicity;
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
