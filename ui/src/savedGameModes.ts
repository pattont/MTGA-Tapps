import type { TrackingSettings, TrackedMode } from './api';

/** Settings → Saved game modes, in the order shown. Direct Challenge is on by default; the rest are off. */
export const SAVED_GAME_MODES: Array<{ key: TrackedMode; label: string; note: string }> = [
  { key: 'direct_challenge', label: 'Direct Challenge', note: 'Games against your friends.' },
  { key: 'jump_in', label: 'Jump In!', note: 'Two random half-decks shuffled together.' },
  { key: 'midweek_magic', label: 'Midweek Magic', note: "Arena's rotating weekly events." },
  { key: 'momir', label: 'Momir', note: 'Random creatures from the Momir avatar.' },
  { key: 'welcome_deck', label: 'Welcome Deck Duels', note: 'Pre-made decks on both sides.' },
  { key: 'practice', label: 'Practice vs Sparky', note: "Games against Arena's bot." },
];

/** How many of the modes this tracker offers are saved. */
export function savedModeCount(settings: TrackingSettings): number {
  return SAVED_GAME_MODES.filter((mode) => settings[mode.key] === true).length;
}
