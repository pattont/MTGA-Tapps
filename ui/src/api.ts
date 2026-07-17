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

export interface FormatOption {
  raw_format: string;
  format_label: string;
}

export interface FilterOptions {
  decks: string[];
  formats: FormatOption[];
}

export interface SnapshotFilters {
  deck?: string;
  format?: string;
  days?: number;
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
  recent: RecentGameRow[];
  matches: MatchRow[];
  sessions: SessionRow[];
  trend: TrendRow[];
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
  raw_format: string | null;
  format_label: string;
  mulligans: number | null;
  play_draw: string | null;
}

export interface DeckDetail {
  deck_name: string;
  deck_visual: DeckVisual;
  summary: Summary;
  profile: DeckProfile;
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

export interface GameTimelineRow {
  turn_number: number | null;
  phase: string | null;
  step: string | null;
  event_type: string | null;
  actor_role: string | null;
  text: string;
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
  is_flood: boolean;
}

export interface GameDetail {
  game: GameHeader;
  player: GameParticipant;
  opponent: GameParticipant;
  opening_hand: GameOpeningHandRow[];
  drawn: GameDrawnCardRow[];
  draw_quality: GameDrawQuality;
  cards_played: GamePlayedCardRow[];
  timeline: GameTimelineRow[];
  life_curve: LifePoint[];
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

export interface CardDetail {
  card_name: string;
  image_url: string | null;
  summary: CardSummary;
  all_usage: CardAllUsage;
  by_role: CardByRoleRow[];
  by_deck: CardByDeckRow[];
  opener_impact: CardOpenerImpact;
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

export async function fetchCardDetail(cardName: string, signal?: AbortSignal): Promise<CardDetail> {
  const params = new URLSearchParams({ name: cardName });
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
