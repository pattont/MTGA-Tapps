/**
 * Pure view-model for the opponent panel and its rail. The grouping mirrors
 * the Stream Kit's opponent widget (ui/src/stream/liveView.ts `groupSeen`):
 * a change to one is a change to both.
 */

import type { OpponentCard, OverlayOpponent, OverlayPayload } from './types';

export interface SeenGroup {
  key: string;
  label: string;
  cards: OpponentCard[];
}

const GROUPS: Array<[string, string, (type: string) => boolean]> = [
  ['creature', 'Creatures', (t) => t.includes('creature')],
  ['walker', 'Planeswalkers', (t) => t.includes('planeswalker')],
  ['spell', 'Instants & sorceries', (t) => t.includes('instant') || t.includes('sorcery')],
  ['permanent', 'Artifacts & enchantments', (t) => t.includes('artifact') || t.includes('enchant') || t.includes('battle')],
  ['other', 'Other', () => true],
];

/** A land with no casting cost (a land on the back of a spell keeps its group). */
export function isLand(card: OpponentCard): boolean {
  return card.type.toLowerCase().includes('land') && !card.mana_cost;
}

/** Lands apart (one line), the rest by type, each by mana value then name. */
export function groupSeen(cards: OpponentCard[]): { groups: SeenGroup[]; lands: OpponentCard[] } {
  const lands = cards.filter(isLand);
  const rest = cards.filter((card) => !isLand(card));
  const groups: SeenGroup[] = [];
  const placed = new Set<OpponentCard>();
  for (const [key, label, test] of GROUPS) {
    const members = rest
      .filter((card) => !placed.has(card) && test(card.type.toLowerCase()))
      .sort((a, b) => (a.mana_value ?? 99) - (b.mana_value ?? 99) || a.name.localeCompare(b.name));
    members.forEach((card) => placed.add(card));
    if (members.length > 0) groups.push({ key, label, cards: members });
  }
  return { groups, lands: [...lands].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)) };
}

/** Distinct nonland cards played: the rail's "Seen" cell. */
export function nonlandSeen(cards: OpponentCard[]): number {
  return cards.filter((card) => !isLand(card)).length;
}

/** WUBRG letters in colour-wheel order, duplicates and other letters dropped. */
export function colorLetters(colors: string | null | undefined): string[] {
  const shown = new Set((colors ?? '').toUpperCase().split(''));
  return ['W', 'U', 'B', 'R', 'G'].filter((c) => shown.has(c));
}

/** The deck line: the name, and a short note on where it came from. A
    guess is always worded as one. */
export function deckLine(opponent: OverlayOpponent | null | undefined): { name: string; note: string | null } {
  const deck = opponent?.deck;
  if (!deck || !deck.label || deck.source === 'none') return { name: 'Not revealed yet', note: null };
  if (deck.source === 'commander') return { name: deck.label, note: 'Commander' };
  if (deck.source === 'history') {
    const matched = deck.matched_cards ?? 0;
    return { name: deck.label, note: `Likely · ${matched} card${matched === 1 ? '' : 's'} match your history` };
  }
  return { name: deck.label, note: 'From the colours shown' };
}

/** The opponent panel's band: a label and a note short enough for one line
    beside its three boxes (like the deck panel's "Land drops / 11 of 41 left"). */
export function bandText(opponent: OverlayOpponent | null | undefined): { label: string; note: string } {
  const deck = opponent?.deck;
  if (!deck || !deck.label || deck.source === 'none') return { label: 'Their deck', note: 'Nothing revealed yet' };
  if (deck.source === 'commander') return { label: 'Their deck', note: 'Their commander' };
  if (deck.source === 'history') {
    const matched = deck.matched_cards ?? 0;
    return { label: 'Likely deck', note: `${matched} card${matched === 1 ? '' : 's'} match history` };
  }
  return { label: 'Their deck', note: 'From their colours' };
}

/** The rail's tooltip: the deck line in words. */
export function railTitle(opponent: OverlayOpponent | null | undefined): string {
  const { name, note } = deckLine(opponent);
  if (!opponent) return 'Opponent';
  const record = opponent.record ? ` · You ${opponent.record.wins}–${opponent.record.losses}` : '';
  return note ? `${name} (${note.toLowerCase()})${record}` : `${name}${record}`;
}

/** What the opponent window shows: the block while a game is on screen and
    the tracker answers; nothing otherwise. */
export function opponentOf(payload: OverlayPayload | null | undefined): OverlayOpponent | null {
  if (!payload || payload.tracker.state === 'offline') return null;
  return payload.opponent ?? null;
}

/** Card names whose play count went up between two lists: the new plays to
    highlight (and the folded rail's pulse). A new game starts clean. */
export function freshPlays(before: OpponentCard[] | null, after: OpponentCard[]): string[] {
  if (!before) return [];
  const counts = new Map(before.map((card) => [card.name, card.count]));
  return after.filter((card) => card.count > (counts.get(card.name) ?? 0)).map((card) => card.name);
}

/** "Swamp ×3 · Blood Crypt" for the lands line. */
export function landsText(lands: OpponentCard[]): string {
  return lands.map((card) => (card.count > 1 ? `${card.name} ×${card.count}` : card.name)).join(' · ');
}
