export interface ManagedCard {
  section: string;
  quantity: number;
  name: string;
  arena_id: number | null;
  set_code: string | null;
  collector_number: string | null;
}

export interface ManagedDeck {
  id: string;
  name: string;
  format_name: string;
  notes: string;
  tags: string[];
  current_revision_id: string;
  trashed_at: string | null;
  saved_at: string;
  updated_at: string;
  source: string;
  completeness: string;
  main_count: number;
  art_card: string | null;
  collection_id?: string | null;
  native_restorable?: boolean;
  native_arena_ids?: string[];
  /** WUBRG letters scored from the main deck; "C" colorless, "" unknown. */
  colors?: string;
  /** Tile art from local data: a Scryfall image-server URL and the printing's `set/number`. */
  art_url?: string | null;
  art_print?: string | null;
  /** Arena's last edit / last game for this deck, from a full backup; null when unknown. */
  arena_modified?: string | null;
  arena_played?: string | null;
  /** Wins and losses in tracked games, over every Arena deck this saved deck has been; null when never played. */
  record?: DeckRecord | null;
}

/** Wins and losses in the games the tracker recorded: in total, by ranked/unranked queue, and on the play/draw. */
export interface DeckRecord {
  wins: number;
  losses: number;
  ranked?: { wins: number; losses: number };
  unranked?: { wins: number; losses: number };
  play?: { wins: number; losses: number };
  draw?: { wins: number; losses: number };
}

/** Arena card-DB facts per card name; any field can be missing. */
export interface CardFacts { mana_cost?: string; mana_value?: number; type?: string }

export interface ManagedDeckDetail extends ManagedDeck {
  revision_id: string;
  card_info?: Record<string, CardFacts>;
  deck: { name: string; format_name: string; cards: ManagedCard[]; import_text: string | null; source: string; completeness: string };
  revisions: { id: string; created_at: string; source: string; content_hash: string }[];
}

export interface DeckCollection { id: string; name: string; }

export interface DeckLibrary {
  collections?: DeckCollection[];
  decks: ManagedDeck[];
  /** Tracked-game records by Arena deck id, for the Arena tab. */
  records?: Record<string, DeckRecord>;
  capabilities: { arena_transfers: boolean; native_section: boolean; capacity: number | null; message: string };
}

async function request<T>(path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/deck-manager${path}`, payload === undefined ? { signal } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal,
  });
  const body = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(body.error ?? `Deck Manager returned ${response.status}`);
  return body;
}

export const fetchDeckLibrary = (signal?: AbortSignal) => request<DeckLibrary>('', undefined, signal);
export const fetchManagedDeck = (id: string, revision?: string, signal?: AbortSignal) =>
  request<ManagedDeckDetail>(`/deck?${new URLSearchParams({ id, ...(revision ? { revision } : {}) })}`, undefined, signal);
export const importManagedDeck = (text: string, name: string, format_name: string, deck_id?: string, collection_id?: string | null) =>
  request<ManagedDeckDetail>('/import', { text, name, format_name, deck_id, ...(collection_id !== undefined ? { collection_id } : {}) });
export const updateManagedDeck = (id: string, fields: { notes?: string; tags?: string[]; trashed?: boolean }) =>
  request<{ ok: boolean }>('/update', { id, ...fields });
export const deleteManagedDeck = (id: string) => request<{ ok: boolean }>('/delete', { id, confirm: 'DELETE' });
export const removeManagedDecks = (ids: string[], action: 'trash' | 'delete') =>
  request<{ ok: boolean; count: number }>('/remove-selected', { ids, action, confirm: action.toUpperCase() });
export const captureArenaDecks = () => request<{ captured: number; rejected: number; note: string }>('/capture', {});
export const exportManagedDeck = (id: string, revision: string, format: 'backup' | 'arena') =>
  request<{ text: string; name: string; extension: string; note?: string }>(`/export?${new URLSearchParams({ id, revision, format })}`);

export interface ArenaDeck {
  id: string;
  name: string;
  format_name: string;
  main_count: number;
  art_card?: string | null;
  art_card_id?: number | null;
  colors?: string;
  /** When the deck was last edited / played in Arena; null when never or unknown. */
  arena_modified?: string | null;
  arena_played?: string | null;
  art_url?: string | null;
  art_print?: string | null;
  /** Starred in Arena's deck list. */
  is_favorite?: boolean;
}
export interface NativeDeckStatus {
  available: boolean;
  in_game?: boolean;
  connected: boolean;
  busy: boolean;
  active_job?: string | null;
  decks: ArenaDeck[];
  limit: number | null;
  limit_reached: boolean | null;
  deck_screen_open: boolean;
  message: string;
  refreshed_at?: string;
  pending_transfers?: { id: string; action: string; phase: string; deck_id: string }[];
}
export type NativeDeckAction = 'connect' | 'backup' | 'store' | 'restore' | 'reconcile' | 'add' | 'favorite';
export interface NativeDeckJob {
  state: 'running' | 'done' | 'error';
  detail: string;
  progress?: { completed: number; total: number | null };
  action?: NativeDeckAction;
  cancel?: boolean;
  result?: { count: number; action: NativeDeckAction; cancelled?: boolean; favorite?: boolean };
}
export const fetchNativeDeckStatus = (signal?: AbortSignal) => request<NativeDeckStatus>('/native', undefined, signal);
/** One Arena deck's cards from the last time Deck Manager read Arena; never contacts Arena. */
export interface ArenaDeckCards { id: string; name: string; format_name: string; refreshed_at?: string; cards: ManagedCard[]; card_info?: Record<string, CardFacts> }
export const fetchArenaDeck = (id: string, signal?: AbortSignal) =>
  request<ArenaDeckCards>(`/native/deck?${new URLSearchParams({ id })}`, undefined, signal);
/**
 * `collection_id` is where a store (move out of Arena) saves the decks; null is Unsorted.
 * `trash` sends each verified backup to Trash once Arena has removed the deck.
 */
export const startNativeDeckJob = (action: NativeDeckAction, decks: { id: string; revision?: string; favorite?: boolean }[] = [], collection_id?: string | null, options: { trash?: boolean } = {}) =>
  request<{ job_id: string }>('/native/run', {
    action, decks, request_id: crypto.randomUUID(), ...(action === 'store' ? { confirm: 'MOVE' } : {}),
    ...(action === 'store' && collection_id !== undefined ? { collection_id } : {}),
    ...(action === 'store' && options.trash ? { trash: true } : {}),
  });
export const cancelNativeDeckJob = (job_id: string) => request<{ state: string; cancel: boolean }>('/native/cancel', { job_id });
export const fetchNativeDeckJob = (id: string, signal?: AbortSignal) => request<NativeDeckJob>(`/native/job?${new URLSearchParams({ id })}`, undefined, signal);
/** `renameIfTaken` numbers the name ("Name (1)") when Arena already has a deck called that. */
export const addDeckToArena = (text: string, name: string, format_name: string, saved_deck_id?: string, collection_id?: string, options: { renameIfTaken?: boolean } = {}) =>
  request<{ job_id: string }>('/native/run', { action: 'add', decks: [], request_id: crypto.randomUUID(), import: {
    text, name, format_name, ...(saved_deck_id ? { saved_deck_id } : {}), ...(collection_id ? { collection_id } : {}),
    ...(options.renameIfTaken ? { rename_if_taken: true } : {}),
  } });

export const saveDeckCollection = (name: string, id?: string) =>
  request<DeckCollection>('/collections/save', { name, id });
export const removeDeckCollection = (id: string) =>
  request<{ ok: boolean; count: number }>('/collections/remove', { id, confirm: 'REMOVE' });
export const moveDecksToCollection = (ids: string[], collection_id: string | null) =>
  request<{ ok: boolean; count: number }>('/collections/move', { ids, collection_id });
