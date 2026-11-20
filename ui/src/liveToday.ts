/**
 * The Live Scoreboard's Today box and games list: every game that started
 * today (local calendar day, from midnight) with its record, play/draw split,
 * current streak, flood and mana-screw games, decks, and the games
 * themselves. The list holds exactly the games the record counts.
 * `components/LiveTodayPanel.tsx` draws the box.
 */

import type { LiveDeckScore, LivePayload, LiveScore } from './api';
import { streak, todayGames, todayRecord } from './stream/liveView';

export { todayGames };

export const NO_GAMES_TEXT = 'No finished games yet today — go queue up!';

export interface TodayView {
  wins: number;
  losses: number;
  draws: number;
  /** Finished games, draws included. */
  games: number;
  winRate: number | null;
  play: LiveScore;
  draw: LiveScore;
  /** The run of wins or losses the newest games make; null after a draw or before any game. */
  streak: { outcome: 'win' | 'loss'; length: number } | null;
  /** Games that were Flood / Mana Screw (Game Detail's rule); null from a tracker that does not count them. */
  floodGames: number | null;
  screwGames: number | null;
  /** Most played first. */
  decks: LiveDeckScore[];
}

const NO_GAMES: LiveScore = { wins: 0, losses: 0 };

/** What the box shows, or null before the tracker has written anything. */
export function todayView(payload: LivePayload | null, nowMs: number): TodayView | null {
  const record = todayRecord(payload);
  if (!payload?.today || !record) return null;
  const today = payload.today;
  const outcomes = todayGames(payload, nowMs).map((game) => game.outcome ?? '');
  return {
    wins: record.wins,
    losses: record.losses,
    draws: record.draws,
    games: record.wins + record.losses + record.draws,
    winRate: record.win_rate,
    play: record.play ?? NO_GAMES,
    draw: record.draw ?? NO_GAMES,
    streak: streak(outcomes),
    floodGames: today.flood_games ?? null,
    screwGames: today.screw_games ?? null,
    decks: today.decks ?? [],
  };
}
