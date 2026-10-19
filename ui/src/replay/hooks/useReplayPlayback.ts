/**
 * Playback plumbing for a loaded stream: the keyframed timeline (built once),
 * the PlaybackClock (subscribed through useSyncExternalStore), the board at
 * the current event and its table layout. React re-renders once per event,
 * never per animation frame.
 */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { layoutBoard, usesCommandZone } from '../layout';
import type { Layout } from '../layout';
import { PlaybackClock } from '../player';
import type { PlaybackSnapshot } from '../player';
import { loadPrefs, subscribePrefs } from '../prefs';
import type { ReplayPrefs } from '../prefs';
import { buildTimeline, stateAt } from '../reducer';
import type { BoardState, ReplayTimeline } from '../reducer';
import type { ReplayStream } from '../types';

export function usePrefs(): ReplayPrefs {
  const [prefs, setPrefs] = useState(loadPrefs);
  useEffect(() => subscribePrefs(setPrefs), []);
  return prefs;
}

export interface ReplayPlayback {
  timeline: ReplayTimeline;
  clock: PlaybackClock;
  snapshot: PlaybackSnapshot;
  state: BoardState;
  layout: Layout;
  /** True when the last change jumped more than a couple of events (scene snaps). */
  jumped: boolean;
}

const SNAP_DISTANCE = 2;

export function useReplayPlayback(
  stream: ReplayStream,
  prefs: ReplayPrefs,
  initialSeq: number | null,
  tableFit?: { width: number; handScale: number; opponentHandScale?: number },
): ReplayPlayback {
  const timeline = useMemo(() => buildTimeline(stream), [stream]);
  const [clock] = useState(
    () =>
      new PlaybackClock(timeline, {
        seq: initialSeq ?? undefined,
        speed: prefs.speed,
        pacing: prefs.pacing,
      }),
  );
  const subscribe = useCallback((listener: () => void) => clock.subscribe(listener), [clock]);
  const getSnapshot = useCallback(() => clock.snapshot, [clock]);
  const snapshot = useSyncExternalStore(subscribe, getSnapshot);

  useEffect(() => clock.setSpeed(prefs.speed), [clock, prefs.speed]);
  useEffect(() => clock.setPacing(prefs.pacing), [clock, prefs.pacing]);
  // Pause at once on unmount and dispose (timer, listeners) a tick later:
  // StrictMode's effect replay re-mounts the same clock before that tick and
  // cancels the dispose, exactly like TextureStore's retain/release.
  const disposeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (disposeTimer.current) clearTimeout(disposeTimer.current);
    disposeTimer.current = null;
    return () => {
      clock.pause();
      disposeTimer.current = setTimeout(() => {
        disposeTimer.current = null;
        clock.dispose();
      }, 0);
    };
  }, [clock]);

  const state = useMemo(() => stateAt(timeline, snapshot.seq), [timeline, snapshot.seq]);
  const { mirrorOpponent, hindsight } = prefs;
  const commandZone = useMemo(() => usesCommandZone(stream), [stream]);
  const tableWidth = tableFit?.width;
  const handScale = tableFit?.handScale;
  const opponentHandScale = tableFit?.opponentHandScale;
  const layout = useMemo(
    () => layoutBoard(state, { mirrorOpponent, hindsight, playerSeat: stream.player_seat, tableWidth, handScale, opponentHandScale, commandZone }),
    [state, mirrorOpponent, hindsight, stream.player_seat, tableWidth, handScale, opponentHandScale, commandZone],
  );

  const [jump, setJump] = useState({ index: snapshot.index, jumped: true });
  if (jump.index !== snapshot.index) {
    setJump({ index: snapshot.index, jumped: Math.abs(snapshot.index - jump.index) > SNAP_DISTANCE });
  }
  return { timeline, clock, snapshot, state, layout, jumped: jump.jumped };
}
