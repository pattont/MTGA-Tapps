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

export interface DashboardSnapshot {
  summary: Summary;
  decks: DeckRow[];
  formats: Record<string, unknown>[];
  play_draw: Record<string, unknown>[];
  deck_play_draw: Record<string, unknown>[];
  draw_quality: Record<string, unknown>[];
  drawn_cards: Record<string, unknown>[];
  momentum: Record<string, unknown>[];
  recent: Record<string, unknown>[];
}

export async function fetchDashboardSnapshot(): Promise<DashboardSnapshot> {
  const response = await fetch('/api/snapshot');
  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return response.json() as Promise<DashboardSnapshot>;
}
