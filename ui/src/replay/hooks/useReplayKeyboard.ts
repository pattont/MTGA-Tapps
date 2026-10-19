/**
 * Page-wide replay shortcuts: Space play/pause, ←/→ step, J/K turn,
 * Home/End, [ ] speed, G go-to-turn, T Replay Options popover, +/- and 0
 * table zoom. Ignored while typing
 * and when a modifier key is held.
 */
import { useEffect, useRef } from 'react';
import { PLAYBACK_SPEEDS } from '../player';
import type { PlaybackClock } from '../player';
import { savePrefs } from '../prefs';

export interface KeyboardActions {
  focusGoToTurn: () => void;
  toggleTable: () => void;
  /** Table zoom; the zoom keys are not handled without it. */
  zoom?: (direction: 'in' | 'out' | 'reset') => void;
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = (target as HTMLInputElement).type;
  return !['checkbox', 'radio', 'button', 'submit', 'range', 'reset'].includes(type);
}

/** Returns true when the key was handled. */
export function handleReplayKey(key: string, clock: PlaybackClock, actions: KeyboardActions): boolean {
  const speeds = PLAYBACK_SPEEDS;
  const at = speeds.indexOf(clock.snapshot.speed);
  switch (key) {
    case ' ':
    case 'Spacebar':
      clock.toggle();
      return true;
    case 'ArrowRight':
      clock.step(1);
      return true;
    case 'ArrowLeft':
      clock.step(-1);
      return true;
    case 'j':
    case 'J':
      clock.prevTurn();
      return true;
    case 'k':
    case 'K':
      clock.nextTurn();
      return true;
    case 'Home':
      clock.pause();
      clock.seek(clock.firstSeq);
      return true;
    case 'End':
      clock.pause();
      clock.seek(clock.lastSeq);
      return true;
    case '[':
      if (at > 0) savePrefs({ speed: speeds[at - 1] });
      return true;
    case ']':
      if (at >= 0 && at < speeds.length - 1) savePrefs({ speed: speeds[at + 1] });
      return true;
    case 'g':
    case 'G':
      actions.focusGoToTurn();
      return true;
    case 't':
    case 'T':
      actions.toggleTable();
      return true;
    case '+':
    case '=':
      actions.zoom?.('in');
      return actions.zoom !== undefined;
    case '-':
    case '_':
      actions.zoom?.('out');
      return actions.zoom !== undefined;
    case '0':
      actions.zoom?.('reset');
      return actions.zoom !== undefined;
    default:
      return false;
  }
}

export function useReplayKeyboard(clock: PlaybackClock, actions: KeyboardActions): void {
  const latest = useRef(actions);
  useEffect(() => {
    latest.current = actions;
  });
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      // Let focused sliders/buttons keep Enter; Space is ours everywhere.
      if (handleReplayKey(event.key, clock, latest.current)) event.preventDefault();
    };
    const onKeyUp = (event: KeyboardEvent) => {
      // Stop a focused button from also "clicking" on Space release.
      if (event.key === ' ' && !isTypingTarget(event.target) && event.target instanceof HTMLButtonElement) {
        event.preventDefault();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [clock]);
}
