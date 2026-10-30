/**
 * Turn-segmented scrub bar colored by the active seat, with turn ticks and a
 * draggable playhead. Dragging pauses playback and resumes it on release if
 * it was playing.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent, PointerEvent } from 'react';
import type { PlaybackClock, PlaybackSnapshot } from '../player';
import { fractionOfIndex, indexAtFraction, openingEndIndex, scrubSegments, visibleTurnLabels } from '../scrub';
import type { ReplayStream } from '../types';

interface ScrubBarProps {
  stream: ReplayStream;
  clock: PlaybackClock;
  snapshot: PlaybackSnapshot;
}

export function ScrubBar({ stream, clock, snapshot }: ScrubBarProps) {
  const segments = useMemo(() => scrubSegments(stream), [stream]);
  // The bar covers the navigable range: from the first turn header to the end.
  const first = useMemo(() => openingEndIndex(stream.events), [stream]);
  const total = stream.events.length - first;
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<{ resume: boolean; frame: number; fraction: number } | null>(null);
  const [width, setWidth] = useState(800);

  useEffect(() => {
    const node = track.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width || 800));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Leaving the page mid-drag must not run a queued seek against a disposed clock.
  useEffect(() => {
    const dragRef = drag;
    return () => {
      if (dragRef.current?.frame) cancelAnimationFrame(dragRef.current.frame);
      dragRef.current = null;
    };
  }, []);

  const seekFraction = (fraction: number) => {
    const event = stream.events[first + indexAtFraction(fraction, total)];
    if (event) clock.seek(event.seq);
  };
  const fractionAt = (clientX: number) => {
    const rect = track.current?.getBoundingClientRect();
    return rect && rect.width > 0 ? Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) : 0;
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    // No text selection and no native drag-and-drop: either would let the
    // browser lift the bar off its track as a drag image and cancel this drag.
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    drag.current = { resume: snapshot.playing, frame: 0, fraction: fractionAt(event.clientX) };
    clock.pause();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    seekFraction(drag.current.fraction);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    state.fraction = fractionAt(event.clientX);
    if (state.frame) return;
    state.frame = requestAnimationFrame(() => {
      state.frame = 0;
      seekFraction(state.fraction);
    });
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>, fraction: number | null) => {
    const state = drag.current;
    if (!state) return;
    if (state.frame) cancelAnimationFrame(state.frame);
    drag.current = null;
    seekFraction(fraction ?? state.fraction);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (state.resume && !clock.snapshot.atEnd) clock.play();
  };
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => endDrag(event, fractionAt(event.clientX));
  // A cancelled drag (the browser took the pointer) stays where it was last
  // dragged to: a cancel event's coordinates are not a place on the bar.
  const onPointerCancel = (event: PointerEvent<HTMLDivElement>) => endDrag(event, null);
  const onDragStart = (event: DragEvent<HTMLDivElement>) => event.preventDefault();
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Arrow keys are handled by the page-wide shortcuts; Page keys jump turns here.
    if (event.key === 'PageUp') {
      event.preventDefault();
      clock.nextTurn();
    } else if (event.key === 'PageDown') {
      event.preventDefault();
      clock.prevTurn();
    }
  };

  const turnSegments = segments.filter((segment) => segment.turn !== null);
  const labelled = useMemo(() => visibleTurnLabels(segments, width), [segments, width]);
  const position = fractionOfIndex(snapshot.index - first, total) * 100;
  const current = stream.events[snapshot.index];
  return (
    <div className="replay-scrub">
      <div className="replay-scrub-labels" aria-hidden="true">
        {turnSegments.map((segment) =>
          labelled.has(segment.key) ? (
            <span key={segment.key} style={{ left: `${segment.start * 100}%` }}>
              T{segment.turn}
            </span>
          ) : null,
        )}
      </div>
      <div
        ref={track}
        className="replay-scrub-track"
        role="slider"
        tabIndex={0}
        aria-label="Replay position"
        aria-valuemin={0}
        aria-valuemax={Math.max(0, total - 1)}
        aria-valuenow={Math.max(0, snapshot.index - first)}
        aria-valuetext={`Event ${snapshot.index - first + 1} of ${total}${snapshot.turn ? `, turn ${snapshot.turn}` : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onLostPointerCapture={onPointerCancel}
        onDragStart={onDragStart}
        onKeyDown={onKeyDown}
      >
        {segments.map((segment) => (
          <span
            key={segment.key}
            className={`replay-scrub-segment ${
              segment.seat === null ? 'replay-seg-pre' : segment.seat === stream.player_seat ? 'replay-seg-you' : 'replay-seg-opp'
            }${current && segment.turn !== null && segment.turn === snapshot.turn ? ' replay-seg-current' : ''}`}
            style={{ left: `${segment.start * 100}%`, width: `${(segment.end - segment.start) * 100}%` }}
            title={segment.turn === null ? 'Pre-game' : `Turn ${segment.turn}`}
          />
        ))}
        <span className="replay-scrub-head" style={{ left: `${position}%` }} />
      </div>
    </div>
  );
}
