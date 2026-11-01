/**
 * Which casts the spotlight widget shows. The live feed's first answer holds
 * the whole current game (up to the server's line limit), and every delta
 * re-sends a short tail of rows already sent, so the widget must tell a new
 * cast from history: it catches up silently until a poll brings nothing
 * newer, and only rows that arrive after that are spotlighted.
 */

import type { SpotlightWho } from './options';

export interface FeedEvent {
  id: number;
  event_type: string | null;
  actor_role: string | null;
  text: string | null;
  text_segments?: Array<{ kind: string; card_name?: string }>;
}

export interface Cast {
  id: number;
  name: string;
  role: 'player' | 'opponent';
}

export interface SpotlightCursor {
  /** The live feed's `since` for the next poll. */
  seq: number;
  /** False until a poll brings no row newer than seq. */
  caughtUp: boolean;
}

export const START_CURSOR: SpotlightCursor = { seq: 0, caughtUp: false };

// "[1:59] Opponent: cast [Lifecreed Duo (Creature 1/2)] -> [you]"
const CAST_RE = /\bcast \[([^\]]+?)(?: \([^()]*\))?\]/i;
const HIDDEN_NAME_RE = /^(card #\d+|a card|face-down|unknown)/i;

/** The card a cast line names, or null for anything else. */
export function castCardName(event: FeedEvent): string | null {
  if (event.event_type !== 'cast') return null;
  const linked = event.text_segments?.find((segment) => segment.kind === 'card' && segment.card_name);
  const name = linked?.card_name ?? event.text?.match(CAST_RE)?.[1]?.trim() ?? null;
  if (!name || HIDDEN_NAME_RE.test(name)) return null;
  return name;
}

function wanted(role: string | null, who: SpotlightWho): role is 'player' | 'opponent' {
  if (role === 'player') return who !== 'opponent';
  if (role === 'opponent') return who !== 'you';
  return false;
}

/**
 * Advance the cursor over one poll's events. Returns the next cursor and the
 * newest cast to show, if this poll brought one.
 */
export function ingestFeed(
  cursor: SpotlightCursor,
  events: FeedEvent[],
  seq: number,
  who: SpotlightWho,
): { cursor: SpotlightCursor; cast: Cast | null } {
  const fresh = events.filter((event) => event.id > cursor.seq);
  const nextSeq = Math.max(cursor.seq, seq, ...fresh.map((event) => event.id));
  if (!cursor.caughtUp) {
    return { cursor: { seq: nextSeq, caughtUp: fresh.length === 0 }, cast: null };
  }
  let cast: Cast | null = null;
  for (const event of fresh) {
    const name = castCardName(event);
    if (name && wanted(event.actor_role, who) && (!cast || event.id > cast.id)) {
      cast = { id: event.id, name, role: event.actor_role };
    }
  }
  return { cursor: { seq: nextSeq, caughtUp: true }, cast };
}
