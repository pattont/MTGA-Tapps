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
  raw_format: string | null;
  games: number;
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
  started_at: string;
  deck_name: string;
  format_label: string;
  outcome: string | null;
  mulligans: number | null;
  duration_seconds: number | null;
}

export interface DashboardSnapshot {
  summary: Summary;
  decks: DeckRow[];
  formats: FormatRow[];
  play_draw: PlayDrawRow[];
  deck_play_draw: DeckPlayDrawRow[];
  draw_quality: DrawQualityRow[];
  drawn_cards: DrawnCardRow[];
  momentum: MomentumRow[];
  recent: RecentGameRow[];
}

export async function fetchDashboardSnapshot(): Promise<DashboardSnapshot> {
  const response = await fetch('/api/snapshot');
  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<DashboardSnapshot>;
}
