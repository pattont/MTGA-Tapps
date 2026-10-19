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
}

export interface ManagedDeckDetail extends ManagedDeck {
  revision_id: string;
  deck: { name: string; format_name: string; cards: ManagedCard[]; import_text: string | null; source: string; completeness: string };
  revisions: { id: string; created_at: string; source: string; content_hash: string }[];
}

export interface DeckCollection { id: string; name: string; }

export interface DeckLibrary {
  collections?: DeckCollection[];
  decks: ManagedDeck[];
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
export type NativeDeckAction = 'connect' | 'backup' | 'store' | 'restore' | 'reconcile' | 'add';
export interface NativeDeckJob {
  state: 'running' | 'done' | 'error';
  detail: string;
  progress?: { completed: number; total: number | null };
  action?: NativeDeckAction;
  cancel?: boolean;
  result?: { count: number; action: NativeDeckAction; cancelled?: boolean };
}
export const fetchNativeDeckStatus = (signal?: AbortSignal) => request<NativeDeckStatus>('/native', undefined, signal);
/** `collection_id` is where a store (move out of Arena) saves the decks; null is Unsorted. */
export const startNativeDeckJob = (action: NativeDeckAction, decks: { id: string; revision?: string }[] = [], collection_id?: string | null) =>
  request<{ job_id: string }>('/native/run', { action, decks, request_id: crypto.randomUUID(), ...(action === 'store' ? { confirm: 'MOVE' } : {}), ...(action === 'store' && collection_id !== undefined ? { collection_id } : {}) });
export const cancelNativeDeckJob = (job_id: string) => request<{ state: string; cancel: boolean }>('/native/cancel', { job_id });
export const fetchNativeDeckJob = (id: string, signal?: AbortSignal) => request<NativeDeckJob>(`/native/job?${new URLSearchParams({ id })}`, undefined, signal);
export const addDeckToArena = (text: string, name: string, format_name: string, saved_deck_id?: string, collection_id?: string) =>
  request<{ job_id: string }>('/native/run', { action: 'add', decks: [], request_id: crypto.randomUUID(), import: { text, name, format_name, ...(saved_deck_id ? { saved_deck_id } : {}), ...(collection_id ? { collection_id } : {}) } });

export const saveDeckCollection = (name: string, id?: string) =>
  request<DeckCollection>('/collections/save', { name, id });
export const removeDeckCollection = (id: string) =>
  request<{ ok: boolean; count: number }>('/collections/remove', { id, confirm: 'REMOVE' });
export const moveDecksToCollection = (ids: string[], collection_id: string | null) =>
  request<{ ok: boolean; count: number }>('/collections/move', { ids, collection_id });
