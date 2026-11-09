/**
 * Pure helpers for the live-feed widgets (scorebug, game result, the
 * opponent's cards, the land meter, intermission, deck stats). Rendering
 * lives in widgets/; everything here is tested on its own.
 */

import type { LiveDrawQuality, LiveGameRow, LiveNow, LivePayload, LiveRank, LiveScore, LiveSeenCard } from '../api';
import { colorComboLabel } from '../colorCombos';
import { drawStatusOf, type DrawStatus } from '../drawStatus';

/** What the opponent is on: Brawl commanders, else the archetype guess, else their colors. */
export function opponentDeck(now: LiveNow): string | null {
  if (now.opponent_commanders.length > 0) return now.opponent_commanders.join(' + ');
  if (now.archetype_guess?.archetype) return now.archetype_guess.archetype;
  return colorComboLabel(now.opponent_colors);
}

/** A game widget is up during a game, and between games with idle=show. */
export function showsGame(now: LiveNow | null | undefined, idle: 'hide' | 'show'): now is LiveNow {
  return Boolean(now && (now.in_game || (idle === 'show' && now.last_game_frozen)));
}

/** "0:42", "12:05", "1:02:09" from whole seconds. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}

/** Seconds since an ISO time, or null. */
export function secondsSince(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null;
  const started = Date.parse(iso);
  return Number.isNaN(started) ? null : Math.max(0, Math.floor((nowMs - started) / 1000));
}

/** "2h 14m", "38m". */
export function span(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
}

export function rate(wins: number, losses: number): number | null {
  return wins + losses > 0 ? (100 * wins) / (wins + losses) : null;
}

/** Below this many games a rate says little, so stat columns show the record alone. */
export const RATE_MIN_GAMES = 5;

export function gamesIn(score: { wins: number; losses: number } | null | undefined): number {
  return score ? score.wins + score.losses : 0;
}

export type Period = 'session' | 'today';

export const PERIOD_LABEL: Record<Period, string> = { session: 'Session', today: 'Today' };

export interface PeriodRecord {
  wins: number;
  losses: number;
  draws: number;
  win_rate: number | null;
  play?: LiveScore;
  draw?: LiveScore;
}

/** The record for a span: this tracker session's, or every game today. */
export function periodRecord(payload: LivePayload | null, period: Period): PeriodRecord | null {
  if (!payload) return null;
  return period === 'today' ? payload.today ?? null : payload.session;
}

function localDate(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * The feed's games within a span. Game ids start with their session's id;
 * "today" is the local date of started_at, as the tracker stores it.
 */
export function periodGames(payload: LivePayload | null, period: Period, nowMs: number): LiveGameRow[] {
  const games = payload?.games ?? [];
  if (period === 'today') {
    const today = localDate(nowMs);
    return games.filter((game) => !game.started_at || game.started_at.slice(0, 10) === today);
  }
  const session = payload?.session?.id;
  return session ? games.filter((game) => game.id.startsWith(`${session}:`)) : games;
}

/** "61.9%"; whole numbers lose the decimal. */
export function percent(value: number | null): string {
  if (value === null) return '—';
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
}

/** The current run at the front of a newest-first result list. */
export function streak(recent: string[] | undefined): { outcome: 'win' | 'loss'; length: number } | null {
  const first = recent?.[0];
  if (first !== 'win' && first !== 'loss') return null;
  let length = 0;
  while (recent![length] === first) length += 1;
  return { outcome: first, length };
}

// ---------------------------------------------------------------------------
// The opponent's cards.

export interface SeenGroup {
  key: string;
  label: string;
  cards: LiveSeenCard[];
}

const GROUPS: Array<[string, string, (type: string) => boolean]> = [
  ['creature', 'Creatures', (t) => t.includes('creature')],
  ['walker', 'Planeswalkers', (t) => t.includes('planeswalker')],
  ['spell', 'Instants & sorceries', (t) => t.includes('instant') || t.includes('sorcery')],
  ['permanent', 'Artifacts & enchantments', (t) => t.includes('artifact') || t.includes('enchant') || t.includes('battle')],
  ['other', 'Other', () => true],
];

/** Lands apart (one line), the rest by type, each by mana value then name. */
export function groupSeen(cards: LiveSeenCard[]): { groups: SeenGroup[]; lands: LiveSeenCard[] } {
  const lands = cards.filter((card) => card.type.toLowerCase().includes('land') && !card.mana_cost);
  const rest = cards.filter((card) => !lands.includes(card));
  const groups: SeenGroup[] = [];
  const placed = new Set<LiveSeenCard>();
  for (const [key, label, test] of GROUPS) {
    const members = rest
      .filter((card) => !placed.has(card) && test(card.type.toLowerCase()))
      .sort((a, b) => (a.mana_value ?? 99) - (b.mana_value ?? 99) || a.name.localeCompare(b.name));
    members.forEach((card) => placed.add(card));
    if (members.length > 0) groups.push({ key, label, cards: members });
  }
  return { groups, lands: [...lands].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)) };
}

/** The type colour class the deck tracker uses (sk-type-*). */
export function typeClass(type: string): string {
  const t = type.toLowerCase();
  if (t.includes('creature')) return 'creature';
  if (t.includes('planeswalker')) return 'walker';
  if (t.includes('instant')) return 'instant';
  if (t.includes('sorcery')) return 'sorcery';
  if (t.includes('enchant')) return 'ench';
  if (t.includes('artifact')) return 'artifact';
  if (t.includes('land')) return 'land';
  return 'other';
}

/** Scryfall's art crop for a card, for the small thumbnails. */
export function artCropUrl(name: string): string {
  const params = new URLSearchParams({ exact: name.split(' // ')[0], format: 'image', version: 'art_crop' });
  return `https://api.scryfall.com/cards/named?${params.toString()}`;
}

// ---------------------------------------------------------------------------
// The land meter: Game Detail's hypergeometric tails, for the gauge's zones.

function logChoose(n: number, k: number): number {
  if (k < 0 || k > n) return -Infinity;
  let total = 0;
  for (let i = 1; i <= k; i += 1) total += Math.log(n - k + i) - Math.log(i);
  return total;
}

/** P(exactly k lands among `draws` cards of a `deck` with `lands` lands). */
export function hypergeomPmf(k: number, deck: number, lands: number, draws: number): number {
  const value = logChoose(lands, k) + logChoose(deck - lands, draws - k) - logChoose(deck, draws);
  return Number.isFinite(value) ? Math.exp(value) : 0;
}

/** Below `screwMax` lands reads as screw, from `floodMin` as flood (≤10 % tails, like draw_quality). */
export function landZones(deck: number, lands: number, seen: number): { screwMax: number; floodMin: number } {
  const draws = Math.min(seen, deck);
  const pmf = Array.from({ length: draws + 1 }, (_, k) => hypergeomPmf(k, deck, lands, draws));
  let screwMax = -1;
  let low = 0;
  for (let k = 0; k <= draws; k += 1) {
    low += pmf[k];
    if (low * 100 <= 10) screwMax = k;
    else break;
  }
  let floodMin = draws + 1;
  let high = 0;
  for (let k = draws; k >= 0; k -= 1) {
    high += pmf[k];
    if (high * 100 <= 10) floodMin = k;
    else break;
  }
  return { screwMax, floodMin };
}

export const DRAW_STATUS_LABEL: Record<DrawStatus, string> = {
  flood: 'Flooding',
  screw: 'Mana screw',
  streak: 'Land streak',
  normal: 'Normal',
};

export function drawStatus(quality: LiveDrawQuality): DrawStatus {
  return drawStatusOf(quality);
}

// ---------------------------------------------------------------------------
// Game result.

export type ResultTone = 'win' | 'loss' | 'draw';

export function resultTone(outcome: string | null): ResultTone | null {
  if (outcome === 'win' || outcome === 'loss' || outcome === 'draw') return outcome;
  return null;
}

/**
 * Up to two highlights for a finished game, best first. `now` is the frozen
 * scoreboard of that same game (null when it isn't).
 */
export function resultFacts(game: LiveGameRow, now: LiveNow | null): string[] {
  const facts: string[] = [];
  const won = game.outcome === 'win';
  const quality = now?.draw_quality ?? null;
  const startLife = (now?.format ?? game.format ?? '').toLowerCase().includes('brawl') ? 25 : 20;
  if (won && now?.player_life != null && now.player_life >= startLife) {
    facts.push(`Untouched: finished on ${now.player_life} life`);
  }
  if (quality) {
    const status = drawStatus(quality);
    const lands = `${quality.lands_seen} lands in ${quality.total_cards_seen} cards`;
    if (status === 'flood') facts.push(won ? `Won through a flood: ${lands}` : `Flooded: ${lands}`);
    if (status === 'screw') facts.push(won ? `Won through mana screw: ${lands}` : `Mana screw: ${lands}`);
  }
  if (won && game.went_first === 0) facts.push('Won on the draw');
  if (won && game.total_turns != null && game.total_turns <= 6) facts.push(`Turn-${game.total_turns} win`);
  if (!won && now?.opponent_life != null && now.opponent_life > 0 && now.opponent_life <= 3) {
    facts.push(`So close: they were on ${now.opponent_life} life`);
  }
  return facts.slice(0, 2);
}

/** "Game 2 · Match 1–1", "Match won 2–1", or null outside Bo3. */
export function matchLine(game: LiveGameRow, now: LiveNow | null): string | null {
  if ((game.best_of ?? 1) < 3 || !now?.match_score) return null;
  const { wins, losses } = now.match_score;
  if (wins >= 2) return `Match won ${wins}–${losses}`;
  if (losses >= 2) return `Match lost ${wins}–${losses}`;
  return `Game ${game.game_number ?? wins + losses} · Match ${wins}–${losses}`;
}

// ---------------------------------------------------------------------------
// Rank.

const RANK_CLASSES = ['Bronze', 'Silver', 'Gold', 'Platinum', 'Diamond', 'Mythic'];

/** A number that grows with rank, for comparing two snapshots. */
export function rankOrder(rank: LiveRank): number {
  const tier = RANK_CLASSES.indexOf(rank.rank_class);
  if (rank.rank_class === 'Mythic') {
    return 1000 + (rank.mythic_rank ? 10000 - Math.min(rank.mythic_rank, 9999) : rank.mythic_percentile ?? 0);
  }
  return Math.max(0, tier) * 100 + (5 - rank.rank_level) * 10 + rank.rank_step;
}

/** "Gold 2", without the steps: the rank-climb line. */
export function rankName(rank: LiveRank): string {
  if (rank.rank_class === 'Mythic') {
    if (rank.mythic_rank) return `Mythic #${rank.mythic_rank}`;
    if (rank.mythic_percentile != null) return `Mythic ${rank.mythic_percentile}%`;
    return 'Mythic';
  }
  return `${rank.rank_class} ${rank.rank_level}`;
}
