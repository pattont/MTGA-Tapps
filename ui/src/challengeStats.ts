import type { ChallengeFriendRow, ChallengeGameRow } from './api';

/** A deck needs this many decided challenge games to be Best or Worst deck. */
export const MIN_DECK_GAMES = 3;
/** A friend needs this many decided matches to be your Nemesis or Favorite victim. */
export const MIN_RIVAL_MATCHES = 2;

export interface Tally {
  games: number;
  wins: number;
  losses: number;
  /** Whole-number percent of decided games; null when none were decided. */
  winRate: number | null;
}

/** A run of the same result, newest game first; null before any decided game. */
export interface Streak {
  result: 'win' | 'loss';
  length: number;
}

export interface DeckRecord extends Tally {
  deck: string;
  colors: string;
  lastPlayed: string | null;
}

export interface FriendExtras {
  /** Colours the friend showed most often (WUBRG letters), '' when nothing colored was seen. */
  colors: string;
  /** Current run of results against this friend, by game. */
  streak: Streak | null;
}

export interface GameHighlight {
  game: ChallengeGameRow;
  friend: string;
}

export interface ChallengeStats {
  games: Tally;
  matches: Tally;
  onPlay: Tally;
  onDraw: Tally;
  streak: Streak | null;
  longestWinStreak: number;
  nemesis: ChallengeFriendRow | null;
  favoriteVictim: ChallengeFriendRow | null;
  decks: DeckRecord[];
  bestDeck: DeckRecord | null;
  worstDeck: DeckRecord | null;
  fastestWin: GameHighlight | null;
  longestGame: GameHighlight | null;
  friendExtras: Map<string, FriendExtras>;
}

export function friendName(name: string | null | undefined): string {
  return String(name ?? '').trim() || 'Opponent';
}

function tally(wins: number, losses: number, games: number): Tally {
  const decided = wins + losses;
  return { games, wins, losses, winRate: decided ? Math.round((wins / decided) * 100) : null };
}

function tallyGames(games: ChallengeGameRow[]): Tally {
  const wins = games.filter((game) => game.outcome === 'win').length;
  const losses = games.filter((game) => game.outcome === 'loss').length;
  return tally(wins, losses, games.length);
}

/** The run of equal results at the newest end of `decided` (oldest first). */
function currentStreak(decided: ChallengeGameRow[]): Streak | null {
  const newest = decided.at(-1);
  if (!newest) return null;
  let length = 0;
  for (let index = decided.length - 1; index >= 0 && decided[index].outcome === newest.outcome; index -= 1) {
    length += 1;
  }
  return { result: newest.outcome as 'win' | 'loss', length };
}

function longestRun(decided: ChallengeGameRow[], result: 'win' | 'loss'): number {
  let best = 0;
  let run = 0;
  for (const game of decided) {
    run = game.outcome === result ? run + 1 : 0;
    best = Math.max(best, run);
  }
  return best;
}

function isDecided(game: ChallengeGameRow): boolean {
  return game.outcome === 'win' || game.outcome === 'loss';
}

function byStart(a: ChallengeGameRow, b: ChallengeGameRow): number {
  return a.started_at < b.started_at ? -1 : a.started_at > b.started_at ? 1 : 0;
}

function decidedRate(row: ChallengeFriendRow): number {
  return row.wins / (row.wins + row.losses);
}

/** Most often seen colour set, ties going to the more recent game. */
function favoriteColors(games: ChallengeGameRow[]): string {
  const counts = new Map<string, number>();
  for (const game of [...games].sort(byStart).reverse()) {
    const colors = game.opp_colors ?? '';
    if (colors) counts.set(colors, (counts.get(colors) ?? 0) + 1);
  }
  let best = '';
  let bestCount = 0;
  for (const [colors, count] of counts) {
    if (count > bestCount) {
      best = colors;
      bestCount = count;
    }
  }
  return best;
}

/**
 * The Challenges page's breakdown. Records against friends count a Bo3 match
 * once (the backend's `friends` rows); everything else counts games.
 */
export function challengeStats(games: ChallengeGameRow[], friends: ChallengeFriendRow[]): ChallengeStats {
  const chronological = [...games].sort(byStart);
  const decided = chronological.filter(isDecided);

  const matchWins = friends.reduce((sum, row) => sum + row.wins, 0);
  const matchLosses = friends.reduce((sum, row) => sum + row.losses, 0);
  const matchCount = friends.reduce((sum, row) => sum + row.matches, 0);

  const rivals = friends.filter((row) => row.wins + row.losses >= MIN_RIVAL_MATCHES);
  const nemesis =
    rivals
      .filter((row) => row.losses > row.wins)
      .sort((a, b) => decidedRate(a) - decidedRate(b) || b.losses - a.losses)[0] ?? null;
  const favoriteVictim =
    rivals
      .filter((row) => row.wins > row.losses)
      .sort((a, b) => decidedRate(b) - decidedRate(a) || b.wins - a.wins)[0] ?? null;

  const deckGames = new Map<string, ChallengeGameRow[]>();
  for (const game of chronological) {
    const list = deckGames.get(game.deck_name) ?? [];
    list.push(game);
    deckGames.set(game.deck_name, list);
  }
  const decks: DeckRecord[] = [...deckGames].map(([deck, list]) => ({
    deck,
    colors: list.at(-1)?.deck_colors ?? '',
    lastPlayed: list.at(-1)?.started_at ?? null,
    ...tallyGames(list),
  }));
  decks.sort((a, b) => b.games - a.games || a.deck.localeCompare(b.deck));
  const rated = decks.filter((row) => row.wins + row.losses >= MIN_DECK_GAMES);
  const bestDeck =
    [...rated].filter((row) => row.wins > 0).sort((a, b) => (b.winRate ?? 0) - (a.winRate ?? 0) || b.wins - a.wins)[0] ??
    null;
  const worstDeck =
    [...rated]
      .filter((row) => row.losses > 0 && row.deck !== bestDeck?.deck)
      .sort((a, b) => (a.winRate ?? 0) - (b.winRate ?? 0) || b.losses - a.losses)[0] ?? null;

  // A win at 0 turns is a concession before turn 1, not a fast win.
  const wins = decided.filter((game) => game.outcome === 'win' && (game.total_turns ?? 0) > 0);
  const fastest = [...wins].sort(
    (a, b) => (a.total_turns ?? 0) - (b.total_turns ?? 0) || (a.duration_seconds ?? Infinity) - (b.duration_seconds ?? Infinity),
  )[0];
  const longest = [...chronological]
    .filter((game) => game.duration_seconds != null)
    .sort((a, b) => (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0))[0];

  const friendGames = new Map<string, ChallengeGameRow[]>();
  for (const game of chronological) {
    const name = friendName(game.opponent_name);
    const list = friendGames.get(name) ?? [];
    list.push(game);
    friendGames.set(name, list);
  }
  const friendExtras = new Map<string, FriendExtras>();
  for (const [name, list] of friendGames) {
    friendExtras.set(name, { colors: favoriteColors(list), streak: currentStreak(list.filter(isDecided)) });
  }

  return {
    games: tallyGames(chronological),
    matches: tally(matchWins, matchLosses, matchCount),
    onPlay: tallyGames(chronological.filter((game) => game.went_first === 1)),
    onDraw: tallyGames(chronological.filter((game) => game.went_first === 0)),
    streak: currentStreak(decided),
    longestWinStreak: longestRun(decided, 'win'),
    nemesis,
    favoriteVictim,
    decks,
    bestDeck,
    worstDeck,
    fastestWin: fastest ? { game: fastest, friend: friendName(fastest.opponent_name) } : null,
    longestGame: longest ? { game: longest, friend: friendName(longest.opponent_name) } : null,
    friendExtras,
  };
}

/** "W3" / "L2", or a dash before any decided game. */
export function streakLabel(streak: Streak | null): string {
  return streak ? `${streak.result === 'win' ? 'W' : 'L'}${streak.length}` : '—';
}
